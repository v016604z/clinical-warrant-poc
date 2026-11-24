"""Offline integration tests for automatic Context Intake case routing."""

import json

import pytest

from clinical_warrant.modules.context_intake.application.case_router import CaseRouteError
from clinical_warrant.modules.context_intake.application.conversation_orchestrator import ConversationOrchestrator
from clinical_warrant.modules.context_intake.application.extraction import ExtractionRequest
from clinical_warrant.modules.context_intake.application.intake import ContextIntakeService
from clinical_warrant.modules.context_intake.domain.category_registry import validate_category_registry
from clinical_warrant.modules.context_intake.domain.classification import IntakeClassificationResult
from clinical_warrant.modules.context_intake.domain.state import CaseState, SessionState, TurnEvent
from clinical_warrant.modules.context_intake.infrastructure.openai_adapter import OpenAIAdapterError


def make_registry():
    return validate_category_registry([
        {
            "category_id": "exposure",
            "category_name": "暴露情境",
            "fields": {
                "exposure_datetime": {"type": "string", "description": "暴露時間"},
                "exposure_route": {"type": "string", "description": "暴露方式"},
            },
        },
        {
            "category_id": "window_period",
            "category_name": "空窗期",
            "fields": {"exposure_datetime": {"type": "string", "description": "暴露時間"}},
        },
        {
            "category_id": "education",
            "category_name": "一般衛教",
            "fields": {"topic": {"type": "string", "description": "衛教主題"}},
        },
        {"category_id": "faq", "category_name": "常見問題", "fields": {}},
    ])


def classification_json(action, evidence, question=None, **extra):
    return json.dumps({
        "action": action,
        "evidence": evidence,
        "clarification_question": question,
        **extra,
    }, ensure_ascii=False)


def extraction_json(selected=(), attributes=None, question=None, field_key=None):
    return json.dumps({
        "selected_fields": list(selected),
        "extracted_attributes": attributes if attributes is not None else {},
        "selection_reason": "依目前訊息選取",
        "clarification_question": question,
        "clarification_field_key": field_key,
    }, ensure_ascii=False)


class FakeClassifier:
    def __init__(self, categories, catalog_version):
        self.categories = list(categories)
        self.catalog_version = catalog_version
        self.calls = []

    def classify(self, message):
        self.calls.append(message)
        category_id = self.categories.pop(0)
        top1 = category_id or "exposure"
        top2 = "window_period" if top1 != "window_period" else "exposure"
        return IntakeClassificationResult(
            top1, 0.9 if category_id else 0.2, top2, 0.1,
            category_id is None, "fake/intake", "revision-test", self.catalog_version,
        )


class FakeRouter:
    def __init__(self, decisions):
        self.decisions = list(decisions)
        self.requests = []

    def route(self, request):
        self.requests.append(request)
        decision = self.decisions.pop(0)
        if isinstance(decision, Exception):
            raise decision
        return decision


class FakeExtractor:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.requests = []

    def extract(self, request: ExtractionRequest):
        self.requests.append(request)
        output = self.outputs.pop(0)
        if isinstance(output, Exception):
            raise output
        return output


class SaveSpy:
    def __init__(self, persisted=None):
        self.saved = []
        self.persisted = dict(persisted or {})
        self.loaded = []

    def save_session(self, session):
        self.saved.append(session)
        self.persisted[session.session_id] = session

    def load_session(self, session_id):
        self.loaded.append(session_id)
        return self.persisted.get(session_id)

    def delete_case(self, _case_id, _participant_id):
        return False


class SequentialIdFactory:
    def __init__(self):
        self.calls = []

    def __call__(self):
        value = f"id-{len(self.calls)}"
        self.calls.append(value)
        return value


def make_orchestrator(categories, route_outputs, extraction_outputs, *, registry=None, repository=None):
    registry = registry or make_registry()
    classifier = FakeClassifier(categories, registry.version)
    extractor = FakeExtractor(extraction_outputs)
    repository = repository if repository is not None else SaveSpy()
    ids = SequentialIdFactory()
    service = ContextIntakeService(
        classifier=classifier,
        extractor=extractor,
        registry=registry,
        repository=repository,
        id_factory=ids,
    )
    router = FakeRouter(route_outputs)
    return ConversationOrchestrator(service, router), classifier, router, extractor, repository


def persisted_session(registry, participant_id="p1"):
    case = CaseState("case-persisted", participant_id).with_attribute(
        "exposure_datetime", "昨天", "turn-persisted",
    )
    prior_classification = IntakeClassificationResult(
        "exposure", 0.9, "window_period", 0.8, False,
        "fake/intake", "revision-test", registry.version,
    )
    event = TurnEvent(
        "turn-persisted", case.case_id, "exposure", "classification",
        prior_classification, ("exposure_datetime",), registry.version,
    )
    return SessionState(
        "s1", participant_id, {case.case_id: case}, case.case_id,
        "exposure", turn_events=(event,),
    )


def test_new_question_classifies_once_and_routes_into_a_new_case():
    orchestrator, classifier, router, extractor, repository = make_orchestrator(
        ["exposure"],
        [classification_json("new_case", "昨天有一次可能的暴露")],
        [extraction_json(["exposure_datetime"], {"exposure_datetime": "昨天"})],
    )

    result = orchestrator.process_turn(
        participant_id="p1", session_id="s1", message="我昨天有一次可能的暴露",
    )

    assert classifier.calls == ["我昨天有一次可能的暴露"]
    assert len(router.requests) == 1
    assert router.requests[0].category.category_id == "exposure"
    assert result.route_decision.action == "new_case"
    assert result.session.active_case_id is not None
    assert result.session.cases[result.session.active_case_id].attributes["exposure_datetime"].value == "昨天"
    assert len(extractor.requests) == 1
    assert repository.saved == [result.session]


def test_session_id_is_generated_once_when_caller_omits_it():
    orchestrator, _, _, _, _ = make_orchestrator(
        ["exposure"],
        [classification_json("new_case", "昨天有一次暴露")],
        [extraction_json(["exposure_datetime"], {"exposure_datetime": "昨天"})],
    )

    result = orchestrator.process_turn(
        participant_id="p1", message="昨天有一次暴露",
    )

    generated = orchestrator.intake_service.id_factory.calls
    assert result.session.session_id == "id-0"
    assert result.session.active_case_id == "id-2"
    assert generated == ["id-0", "id-1", "id-2"]


def test_foreign_participant_session_is_rejected_before_classification_or_routing():
    registry = make_registry()
    foreign = SessionState("s1", "p2")
    repository = SaveSpy({"s1": foreign})
    orchestrator, classifier, router, extractor, repository = make_orchestrator(
        ["exposure"], [], [], registry=registry, repository=repository,
    )

    with pytest.raises(ValueError, match="participant"):
        orchestrator.process_turn(
            participant_id="p1", session_id="s1", message="昨天有一次暴露",
        )

    assert repository.loaded == ["s1"]
    assert classifier.calls == []
    assert router.requests == []
    assert extractor.requests == []
    assert repository.saved == []


def test_uncached_same_participant_session_is_loaded_and_continued():
    registry = make_registry()
    stored = persisted_session(registry)
    repository = SaveSpy({stored.session_id: stored})
    orchestrator, classifier, router, extractor, repository = make_orchestrator(
        ["window_period"],
        [classification_json("continue_case", "同一次")],
        [extraction_json()],
        registry=registry,
        repository=repository,
    )

    result = orchestrator.process_turn(
        participant_id="p1", session_id="s1", message="同一次，想問空窗期",
    )

    assert repository.loaded == ["s1", "s1"]
    assert router.requests[0].session is stored
    assert len(classifier.calls) == 1
    assert result.session.active_case_id == stored.active_case_id
    assert result.session.cases[stored.active_case_id].attributes["exposure_datetime"].value == "昨天"
    assert extractor.requests[0].known_attributes == {"exposure_datetime": "昨天"}
    assert repository.saved == [result.session]


def test_pending_answer_reuses_active_category_and_routes_without_reclassification():
    orchestrator, classifier, router, extractor, _ = make_orchestrator(
        ["exposure"],
        [
            classification_json("new_case", "暴露事件"),
            classification_json("continue_case", "昨天"),
        ],
        [
            extraction_json(["exposure_datetime"], {}, "大約是哪一天？", "exposure_datetime"),
            extraction_json(["exposure_datetime"], {"exposure_datetime": "昨天"}),
        ],
    )

    first = orchestrator.process_turn(
        participant_id="p1", session_id="s1", message="我想詢問一個暴露事件",
    )
    second = orchestrator.process_turn(
        participant_id="p1", session_id="s1", message="昨天",
    )

    assert classifier.calls == ["我想詢問一個暴露事件"]
    assert len(router.requests) == 2
    assert second.route_decision.action == "continue_case"
    assert second.category_id == "exposure"
    assert second.session.active_case_id == first.session.active_case_id
    assert second.session.cases[first.session.active_case_id].attributes["exposure_datetime"].value == "昨天"
    assert extractor.requests[1].category.category_id == "exposure"
    assert extractor.requests[1].context == ("大約是哪一天？",)


def test_new_event_while_question_is_pending_creates_separate_case():
    orchestrator, classifier, router, extractor, _ = make_orchestrator(
        ["exposure", "exposure"],
        [
            classification_json("new_case", "一次可能的暴露"),
            classification_json("new_case", "又有另一件新暴露"),
        ],
        [
            extraction_json(["exposure_datetime"], {}, "大約是哪一天？", "exposure_datetime"),
            extraction_json(["exposure_datetime"], {"exposure_datetime": "今天"}),
        ],
    )
    first = orchestrator.process_turn(
        participant_id="p1", session_id="s1", message="我有一次可能的暴露",
    )
    old_case_id = first.session.active_case_id
    assert first.session.pending_question is not None

    second = orchestrator.process_turn(
        participant_id="p1", session_id="s1", message="今天又有另一件新暴露",
    )

    new_case_id = second.session.active_case_id
    assert second.route_decision.action == "new_case"
    assert len(classifier.calls) == 2
    assert len(router.requests) == 2
    assert new_case_id != old_case_id
    assert len(second.session.cases) == 2
    assert second.session.pending_question is None
    assert second.session.cases[old_case_id].attributes == {}
    assert second.session.cases[new_case_id].attributes["exposure_datetime"].value == "今天"
    assert extractor.requests[1].context == ()


@pytest.mark.parametrize(
    ("new_category", "expected_clarification"),
    [
        ("faq", "這類問題不需要建立個人事件資料"),
        (None, "我還不確定這個新事件屬於哪一類"),
    ],
)
def test_pending_new_case_route_with_fieldless_or_unknown_classification_preserves_pending(
    new_category, expected_clarification,
):
    orchestrator, classifier, router, extractor, repository = make_orchestrator(
        ["exposure", new_category],
        [
            classification_json("new_case", "一次可能的暴露"),
            classification_json("new_case", "另一個問題"),
        ],
        [extraction_json(["exposure_datetime"], {}, "大約是哪一天？", "exposure_datetime")],
    )
    first = orchestrator.process_turn(
        participant_id="p1", session_id="s1", message="我有一次可能的暴露",
    )
    saved_count = len(repository.saved)

    second = orchestrator.process_turn(
        participant_id="p1", session_id="s1", message="另一個問題",
    )

    assert second.route_decision.action == "new_case"
    assert expected_clarification in second.clarification
    assert second.session.active_case_id == first.session.active_case_id
    assert second.session.pending_question == first.session.pending_question
    assert second.session.cases == first.session.cases
    assert second.session.turn_events == first.session.turn_events
    assert second.session.awaiting_case_restatement is True
    assert classifier.calls == ["我有一次可能的暴露", "另一個問題"]
    assert len(router.requests) == 2
    assert len(extractor.requests) == 1
    assert len(repository.saved) == saved_count + 1


def test_explicit_new_event_creates_separate_case_instead_of_merging():
    orchestrator, classifier, router, _, _ = make_orchestrator(
        ["exposure", "exposure"],
        [
            classification_json("new_case", "昨天有一次暴露"),
            classification_json("new_case", "今天又有一次暴露"),
        ],
        [
            extraction_json(["exposure_datetime"], {"exposure_datetime": "昨天"}),
            extraction_json(["exposure_datetime"], {"exposure_datetime": "今天"}),
        ],
    )

    first = orchestrator.process_turn(participant_id="p1", session_id="s1", message="昨天有一次暴露")
    second = orchestrator.process_turn(participant_id="p1", session_id="s1", message="今天又有一次暴露")

    assert len(classifier.calls) == 2
    assert len(router.requests) == 2
    first_case_id = first.session.active_case_id
    second_case_id = second.session.active_case_id
    assert first_case_id != second_case_id
    assert len(second.session.cases) == 2
    assert second.session.cases[first_case_id].attributes["exposure_datetime"].value == "昨天"
    assert second.session.cases[second_case_id].attributes["exposure_datetime"].value == "今天"


def test_explicit_new_question_route_new_case_does_not_pass_mutually_exclusive_flags():
    orchestrator, classifier, router, _, _ = make_orchestrator(
        ["exposure", "exposure"],
        [
            classification_json("new_case", "昨天有一次暴露"),
            classification_json("new_case", "另一件新的暴露"),
        ],
        [
            extraction_json(["exposure_datetime"], {"exposure_datetime": "昨天"}),
            extraction_json(["exposure_datetime"], {"exposure_datetime": "今天"}),
        ],
    )
    first = orchestrator.process_turn(
        participant_id="p1", session_id="s1", message="昨天有一次暴露",
    )

    second = orchestrator.process_turn(
        participant_id="p1", session_id="s1", message="另一件新的暴露",
        new_question=True,
    )

    assert second.route_decision.action == "new_case"
    assert second.session.active_case_id != first.session.active_case_id
    assert second.session.cases[first.session.active_case_id].attributes["exposure_datetime"].value == "昨天"
    assert second.session.cases[second.session.active_case_id].attributes["exposure_datetime"].value == "今天"
    assert len(classifier.calls) == 2
    assert len(router.requests) == 2


def test_uncertain_event_identity_asks_clarification_without_merging_or_persisting():
    orchestrator, classifier, router, extractor, repository = make_orchestrator(
        ["exposure", "exposure"],
        [
            classification_json("new_case", "昨天有一次暴露"),
            classification_json("clarify", "好像又一次", "您指的是原本那次，還是新的事件？"),
        ],
        [extraction_json(["exposure_datetime"], {"exposure_datetime": "昨天"})],
    )
    first = orchestrator.process_turn(participant_id="p1", session_id="s1", message="昨天有一次暴露")
    before = len(repository.saved)

    second = orchestrator.process_turn(
        participant_id="p1", session_id="s1", message="好像又一次",
    )

    assert second.route_decision.action == "clarify"
    assert second.clarification.startswith("您指的是原本那次，還是新的事件？")
    assert second.session.active_case_id == first.session.active_case_id
    assert len(second.session.cases) == 1
    assert second.session.awaiting_case_restatement is True
    assert second.session.cases == first.session.cases
    assert second.session.turn_events == first.session.turn_events
    assert len(repository.saved) == before + 1
    assert len(extractor.requests) == 1
    assert len(classifier.calls) == 2 and len(router.requests) == 2


def test_clarification_requires_full_event_restatement_and_short_answer_does_not_merge():
    orchestrator, classifier, router, extractor, repository = make_orchestrator(
        ["exposure", "exposure", None],
        [
            classification_json("new_case", "昨天有一次暴露"),
            classification_json("clarify", "可能又一次", "您指的是同一次事件，還是新的事件？"),
        ],
        [extraction_json(["exposure_datetime"], {"exposure_datetime": "昨天"})],
    )
    first = orchestrator.process_turn(
        participant_id="p1", session_id="s1", message="昨天有一次暴露",
    )
    first_save_count = len(repository.saved)
    clarification = orchestrator.process_turn(
        participant_id="p1", session_id="s1", message="可能又一次",
    )

    assert clarification.route_decision.action == "clarify"
    assert "重新完整描述事件及發生時間" in clarification.clarification
    assert "新的" in clarification.clarification
    assert clarification.session.awaiting_case_restatement is True
    assert clarification.session.cases == first.session.cases
    assert clarification.session.turn_events == first.session.turn_events
    assert len(repository.saved) == first_save_count + 1
    assert clarification.session.pending_question is None
    assert clarification.session.pending_conflict is None

    short_answer = orchestrator.process_turn(
        participant_id="p1", session_id="s1", message="新的",
    )

    assert short_answer.clarification
    assert short_answer.session.awaiting_case_restatement is True
    assert short_answer.session.cases == first.session.cases
    assert len(short_answer.session.cases) == 1
    assert short_answer.session.active_case_id == first.session.active_case_id
    assert short_answer.session.cases[first.session.active_case_id].attributes[
        "exposure_datetime"
    ].value == "昨天"
    assert len(repository.saved) == first_save_count + 1
    assert len(extractor.requests) == 1
    assert len(classifier.calls) == 3
    assert len(router.requests) == 2


def test_pending_clarify_short_answer_cannot_fill_old_field_before_full_new_event():
    orchestrator, classifier, router, extractor, repository = make_orchestrator(
        ["exposure", None, "exposure"],
        [
            classification_json("new_case", "一次可能的暴露"),
            classification_json("clarify", "又一次", "您是指原本事件還是新事件？"),
            classification_json("new_case", "今天又有另一件暴露"),
        ],
        [
            extraction_json(["exposure_datetime"], {}, "大約是哪一天？", "exposure_datetime"),
            extraction_json(["exposure_datetime"], {"exposure_datetime": "今天"}),
        ],
    )
    first = orchestrator.process_turn(
        participant_id="p1", session_id="s1", message="我有一次可能的暴露",
    )
    old_case_id = first.session.active_case_id
    old_question = first.session.pending_question
    assert old_question is not None

    clarified = orchestrator.process_turn(
        participant_id="p1", session_id="s1", message="好像又一次",
    )
    assert clarified.route_decision.action == "clarify"
    assert clarified.session.pending_question == old_question
    assert clarified.session.awaiting_case_restatement is True

    short = orchestrator.process_turn(
        participant_id="p1", session_id="s1", message="新的",
    )
    assert short.clarification
    assert short.session.awaiting_case_restatement is True
    assert short.session.pending_question == old_question
    assert short.session.cases[old_case_id].attributes == {}
    assert len(extractor.requests) == 1
    assert len(repository.saved) == 2
    assert len(router.requests) == 2

    full = orchestrator.process_turn(
        participant_id="p1", session_id="s1", message="今天又有另一件暴露",
    )
    new_case_id = full.session.active_case_id
    assert full.route_decision.action == "new_case"
    assert new_case_id != old_case_id
    assert len(full.session.cases) == 2
    assert full.session.pending_question is None
    assert full.session.cases[old_case_id].attributes == {}
    assert full.session.cases[new_case_id].attributes["exposure_datetime"].value == "今天"
    assert classifier.calls == [
        "我有一次可能的暴露", "新的", "今天又有另一件暴露",
    ]
    assert len(router.requests) == 3
    assert len(extractor.requests) == 2
    assert len(repository.saved) == 3


def test_failed_router_after_clarification_keeps_marker_for_safe_retry():
    orchestrator, classifier, router, extractor, repository = make_orchestrator(
        ["exposure", None, "exposure", None, "exposure"],
        [
            classification_json("new_case", "一次可能的暴露"),
            classification_json("clarify", "又一次", "您是指原本事件還是新事件？"),
            OpenAIAdapterError("router request failed"),
            classification_json("new_case", "今天又有另一件暴露"),
        ],
        [
            extraction_json(["exposure_datetime"], {}, "大約是哪一天？", "exposure_datetime"),
            extraction_json(["exposure_datetime"], {"exposure_datetime": "今天"}),
        ],
    )
    first = orchestrator.process_turn(
        participant_id="p1", session_id="s1", message="我有一次可能的暴露",
    )
    old_case_id = first.session.active_case_id
    orchestrator.process_turn(participant_id="p1", session_id="s1", message="好像又一次")
    orchestrator.process_turn(participant_id="p1", session_id="s1", message="新的")
    saved_count = len(repository.saved)

    with pytest.raises(OpenAIAdapterError):
        orchestrator.process_turn(
            participant_id="p1", session_id="s1", message="今天又有另一件暴露",
        )

    assert len(repository.saved) == saved_count
    assert len(extractor.requests) == 1
    # A short reply after the failed full restatement remains a clarification,
    # which proves the persisted marker was not cleared by the router failure.
    short_retry = orchestrator.process_turn(
        participant_id="p1", session_id="s1", message="新的",
    )
    assert short_retry.clarification
    assert len(router.requests) == 3
    assert len(repository.saved) == saved_count
    assert short_retry.session.pending_question == first.session.pending_question

    full_retry = orchestrator.process_turn(
        participant_id="p1", session_id="s1", message="今天又有另一件暴露",
    )
    assert full_retry.route_decision.action == "new_case"
    assert full_retry.session.active_case_id != old_case_id
    assert full_retry.session.cases[old_case_id].attributes == {}
    assert full_retry.session.cases[full_retry.session.active_case_id].attributes[
        "exposure_datetime"
    ].value == "今天"
    assert len(classifier.calls) == 5
    assert len(router.requests) == 4
    assert len(extractor.requests) == 2
    assert len(repository.saved) == 3


def test_no_case_route_clears_active_association_without_creating_or_extracting_case():
    orchestrator, _, _, extractor, _ = make_orchestrator(
        ["exposure", "education"],
        [
            classification_json("new_case", "昨天有一次暴露"),
            classification_json("no_case", "一般衛教問題"),
        ],
        [extraction_json(["exposure_datetime"], {"exposure_datetime": "昨天"})],
    )
    first = orchestrator.process_turn(participant_id="p1", session_id="s1", message="昨天有一次暴露")
    first_case_id = first.session.active_case_id

    result = orchestrator.process_turn(
        participant_id="p1", session_id="s1", message="一般衛教問題",
    )

    assert result.route_decision.action == "no_case"
    assert result.session.active_case_id is None
    assert result.session.cases[first_case_id].attributes["exposure_datetime"].value == "昨天"
    assert len(result.session.cases) == 1
    assert result.session.turn_events[-1].case_id is None
    assert len(extractor.requests) == 1


def test_cross_category_continuation_reuses_same_case_attributes():
    orchestrator, classifier, router, extractor, _ = make_orchestrator(
        ["exposure", "window_period"],
        [
            classification_json("new_case", "昨天有一次暴露"),
            classification_json("continue_case", "同一件事"),
        ],
        [
            extraction_json(["exposure_datetime"], {"exposure_datetime": "昨天"}),
            extraction_json(),
        ],
    )
    first = orchestrator.process_turn(participant_id="p1", session_id="s1", message="昨天有一次暴露")

    second = orchestrator.process_turn(
        participant_id="p1", session_id="s1", message="同一件事，想問空窗期",
    )

    case_id = first.session.active_case_id
    assert second.category_id == "window_period"
    assert second.session.active_case_id == case_id
    assert second.session.cases[case_id].attributes["exposure_datetime"].value == "昨天"
    assert extractor.requests[1].known_attributes == {"exposure_datetime": "昨天"}
    assert len(classifier.calls) == 2 and len(router.requests) == 2


def test_fieldless_category_and_continue_without_case_cannot_create_or_merge_case():
    registry = make_registry()
    orchestrator, _, _, extractor, repository = make_orchestrator(
        ["faq", "exposure"],
        [
            classification_json("new_case", "一般衛教"),
            classification_json("continue_case", "延續同一事件"),
        ],
        [],
        registry=registry,
    )
    with pytest.raises(CaseRouteError, match="Category without fields"):
        orchestrator.process_turn(participant_id="p1", session_id="s1", message="一般衛教")
    assert repository.saved == []
    assert orchestrator.intake_service.sessions == {}

    with pytest.raises(CaseRouteError, match="requires an active case"):
        orchestrator.process_turn(participant_id="p1", session_id="s2", message="延續同一事件")
    assert repository.saved == []
    assert orchestrator.intake_service.sessions == {}
    assert extractor.requests == []


def test_case_router_cannot_assign_arbitrary_case_id_or_write_state():
    orchestrator, _, _, extractor, repository = make_orchestrator(
        ["exposure"],
        [classification_json("new_case", "昨天有一次暴露", case_id="attacker-selected")],
        [],
    )

    with pytest.raises(CaseRouteError):
        orchestrator.process_turn(participant_id="p1", session_id="s1", message="昨天有一次暴露")

    assert repository.saved == []
    assert orchestrator.intake_service.sessions == {}
    assert extractor.requests == []


def test_openai_router_failure_does_not_call_service_or_persist():
    orchestrator, _, _, extractor, repository = make_orchestrator(
        ["exposure"],
        [OpenAIAdapterError("request failed")],
        [],
    )

    with pytest.raises(OpenAIAdapterError):
        orchestrator.process_turn(participant_id="p1", session_id="s1", message="昨天有一次暴露")

    assert repository.saved == []
    assert orchestrator.intake_service.sessions == {}
    assert extractor.requests == []


def test_explicit_correction_and_confirmed_conflict_preserve_history():
    orchestrator, classifier, router, _, _ = make_orchestrator(
        ["exposure", "window_period", "exposure"],
        [
            classification_json("new_case", "昨天有一次暴露"),
            classification_json("continue_case", "更正為前天"),
            classification_json("continue_case", "其實是今天"),
        ],
        [
            extraction_json(["exposure_datetime"], {"exposure_datetime": "昨天"}),
            extraction_json(["exposure_datetime"], {"exposure_datetime": "前天"}),
            extraction_json(["exposure_datetime"], {"exposure_datetime": "今天"}),
        ],
    )
    first = orchestrator.process_turn(participant_id="p1", session_id="s1", message="昨天有一次暴露")
    case_id = first.session.active_case_id
    corrected = orchestrator.process_turn(
        participant_id="p1", session_id="s1", message="更正為前天",
        correct_fields=("exposure_datetime",),
    )
    conflict = orchestrator.process_turn(
        participant_id="p1", session_id="s1", message="其實是今天",
    )
    confirmed = orchestrator.process_turn(
        participant_id="p1", session_id="s1", message="確認是今天", confirm_conflict=True,
    )

    value = confirmed.session.cases[case_id].attributes["exposure_datetime"]
    assert corrected.session.cases[case_id].attributes["exposure_datetime"].value == "前天"
    assert conflict.session.pending_conflict is not None
    assert value.value == "今天"
    assert [change.action for change in value.history] == ["add", "correct", "confirm"]
    assert len(classifier.calls) == 3
    assert len(router.requests) == 3
