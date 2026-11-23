"""Application contract for deciding whether a turn belongs to a case."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from clinical_warrant.modules.context_intake.domain.category_registry import CategoryDefinition
from clinical_warrant.modules.context_intake.domain.state import SessionState


CaseAction = Literal["new_case", "continue_case", "no_case", "clarify"]


class CaseRouteError(ValueError):
    """The case router returned an invalid or unsupported decision."""


@dataclass(frozen=True)
class CaseRouteRequest:
    message: str
    category: CategoryDefinition
    session: SessionState


@dataclass(frozen=True)
class CaseRouteDecision:
    action: CaseAction
    clarification_question: str | None


class CaseRouter(Protocol):
    """Return raw JSON; the application validates it against the current request."""

    def route(self, request: CaseRouteRequest) -> str: ...


def parse_case_route(raw: str, request: CaseRouteRequest) -> CaseRouteDecision:
    """Validate a route decision and require its evidence in the current message."""
    if not isinstance(raw, str) or raw.lstrip().startswith("```"):
        raise CaseRouteError("case route output must be plain JSON text")
    try:
        payload = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (json.JSONDecodeError, ValueError) as error:
        raise CaseRouteError("case route output is not strict JSON") from error
    if not isinstance(payload, dict) or set(payload) != {"action", "evidence", "clarification_question"}:
        raise CaseRouteError("case route output must contain exactly action, evidence, and clarification_question")

    action = payload["action"]
    if action not in ("new_case", "continue_case", "no_case", "clarify"):
        raise CaseRouteError("case route action is unsupported")
    evidence = payload["evidence"]
    if not isinstance(evidence, str) or not evidence.strip() or evidence not in request.message:
        raise CaseRouteError("case route evidence must be an exact substring of the current message")
    question = payload["clarification_question"]
    if action == "clarify":
        if not isinstance(question, str) or not question.strip():
            raise CaseRouteError("clarify action requires a non-empty clarification_question")
    elif question is not None:
        raise CaseRouteError("clarification_question is only allowed for clarify action")
    if action == "continue_case" and request.session.active_case_id is None:
        raise CaseRouteError("continue_case requires an active case in the current session")
    if action == "new_case" and not request.category.fields:
        raise CaseRouteError("new_case is not allowed for a Category without fields")
    return CaseRouteDecision(action, question)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant: {value}")


__all__ = [
    "CaseAction", "CaseRouteDecision", "CaseRouteError", "CaseRouteRequest",
    "CaseRouter", "parse_case_route",
]
