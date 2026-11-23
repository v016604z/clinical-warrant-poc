"""Offline contract tests for the constrained Context Intake case router."""

import json

import pytest

from clinical_warrant.modules.context_intake.application.case_router import (
    CaseRouteError,
    CaseRouteRequest,
    parse_case_route,
)
from clinical_warrant.modules.context_intake.domain.category_registry import validate_category_registry
from clinical_warrant.modules.context_intake.domain.state import CaseState, SessionState
from clinical_warrant.modules.context_intake.infrastructure.openai_case_router import OpenAICaseRouter


def category(*, fields=None):
    return validate_category_registry([{
        "category_id": "exposure",
        "category_name": "暴露情境",
        "fields": fields if fields is not None else {
            "exposure_datetime": {"type": "string", "description": "暴露時間"},
        },
    }]).get("exposure")


def route_json(action="new_case", evidence="我昨天有一次可能的暴露", question=None, **extra):
    return json.dumps({
        "action": action,
        "evidence": evidence,
        "clarification_question": question,
        **extra,
    }, ensure_ascii=False)


class FakeAdapter:
    def __init__(self, output):
        self.output = output
        self.calls = []

    def create_structured_response(self, **kwargs):
        self.calls.append(kwargs)
        return self.output


def test_openai_router_uses_strict_action_schema_and_does_not_send_identifiers():
    adapter = FakeAdapter(route_json())
    router = OpenAICaseRouter(adapter=adapter)
    category_definition = category()
    case = CaseState("private-case-id", "private-participant-id").with_attribute(
        "exposure_datetime", "昨天", "turn-1",
    )
    session = SessionState(
        "private-session-id", "private-participant-id", {case.case_id: case}, case.case_id,
        category_definition.category_id,
    )

    request = CaseRouteRequest("我昨天有一次可能的暴露", category_definition, session)
    raw = router.route(request)

    assert raw == adapter.output
    assert len(adapter.calls) == 1
    call = adapter.calls[0]
    assert call["schema_name"] == "context_intake_case_route"
    assert set(call["schema"]["properties"]) == {
        "action", "evidence", "clarification_question",
    }
    assert call["schema"]["properties"]["action"]["enum"] == [
        "new_case", "continue_case", "no_case", "clarify",
    ]
    assert "restate a new personal event and when it happened" in call["instructions"]
    assert "short reply such as only 'new' or 'same' is not enough" in call["instructions"]
    sent = call["input"]
    assert "我昨天有一次可能的暴露" in sent
    assert '"exposure_datetime":"昨天"' in sent
    assert "private-case-id" not in sent
    assert "private-participant-id" not in sent
    assert "private-session-id" not in sent


@pytest.mark.parametrize(
    "raw",
    [
        "{malformed json",
        route_json(evidence="昨天曾提到別的事件"),
        route_json(action="unknown"),
        route_json(action="clarify", question=None),
        route_json(action="continue_case", question="不允許非 clarify 使用"),
        route_json(case_id="arbitrary-id"),
    ],
)
def test_case_route_parser_rejects_invalid_or_unauthorized_decisions(raw):
    request = CaseRouteRequest(
        "我昨天有一次可能的暴露", category(), SessionState("s1", "p1"),
    )

    with pytest.raises(CaseRouteError):
        parse_case_route(raw, request)


def test_case_route_parser_requires_active_case_for_continue():
    request = CaseRouteRequest(
        "延續同一事件", category(), SessionState("s1", "p1"),
    )

    with pytest.raises(CaseRouteError, match="requires an active case"):
        parse_case_route(route_json("continue_case", evidence="延續同一事件"), request)


def test_case_route_parser_rejects_empty_field_category_as_new_case():
    request = CaseRouteRequest(
        "一般衛教問題", category(fields={}), SessionState("s1", "p1"),
    )

    with pytest.raises(CaseRouteError, match="without fields"):
        parse_case_route(route_json("new_case", evidence="一般衛教問題"), request)


def test_case_route_parser_accepts_explicit_new_continue_no_case_and_clarify():
    category_definition = category()
    case = CaseState("case-1", "p1")
    active_session = SessionState("s1", "p1", {case.case_id: case}, case.case_id,
                                  category_definition.category_id)
    requests = {
        "new_case": CaseRouteRequest("我昨天有一次可能的暴露", category_definition, SessionState("s0", "p1")),
        "continue_case": CaseRouteRequest("是同一次", category_definition, active_session),
        "no_case": CaseRouteRequest("只想了解基本知識", category_definition, SessionState("s2", "p1")),
        "clarify": CaseRouteRequest("好像有另一件事", category_definition, active_session),
    }
    route_raw = {
        "new_case": route_json("new_case", "昨天有一次可能的暴露"),
        "continue_case": route_json("continue_case", "是同一次"),
        "no_case": route_json("no_case", "基本知識"),
        "clarify": route_json("clarify", "另一件事", "您指的是原本那次事件，還是新的事件？"),
    }

    for action, request in requests.items():
        decision = parse_case_route(route_raw[action], request)
        assert decision.action == action
        assert decision.clarification_question == (
            "您指的是原本那次事件，還是新的事件？" if action == "clarify" else None
        )
