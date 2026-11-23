"""Multi-turn Context Intake service scenarios with offline fake ports."""

import json

import pytest

from clinical_warrant.modules.context_intake.application.intake import ContextIntakeService
from clinical_warrant.modules.context_intake.domain.category_registry import validate_category_registry
from clinical_warrant.modules.context_intake.domain.classification import IntakeClassificationResult


def make_registry():
    return validate_category_registry([
        {
            "category_id": "exposure",
            "category_name": "暴露情境",
            "fields": {
                "exposure_datetime": {"type": "string", "description": "暴露時間"},
                "test_count": {"type": "integer", "description": "次數"},
                "is_protected": {"type": "boolean", "description": "是否有防護"},
            },
        },
        {
            "category_id": "window_period",
            "category_name": "空窗期",
            "fields": {
                "exposure_datetime": {"type": "string", "description": "暴露時間"},
            },
        },
        {
            "category_id": "test_result_interpretation",
            "category_name": "檢驗結果",
            "fields": {
                "exposure_datetime": {"type": "string", "description": "暴露時間"},
            },
        },
        {
            "category_id": "education",
            "category_name": "一般衛教",
            "fields": {"topic": {"type": "string", "description": "主題"}},
        },
    ])


class FakeClassifier:
    def __init__(self, results, catalog_version):
        self.results = list(results)
        self.catalog_version = catalog_version
        self.calls = []

    def classify(self, message):
        self.calls.append(message)
        result = self.results.pop(0)
        top1 = result or "exposure"
        top2 = "window_period" if top1 != "window_period" else "exposure"
        return IntakeClassificationResult(
            top1, 0.2 if result is None else 0.9, top2, 0.1,
            result is None, "fake/intake", "revision-test", self.catalog_version,
        )


class FakeExtractor:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def extract(self, request):
        self.requests.append(request)
        return json.dumps(self.responses.pop(0), ensure_ascii=False)


def payload(selected, attrs=None, question=None, key=None):
    return {
        "selected_fields": selected,
        "extracted_attributes": attrs or {},
        "selection_reason": "與本輪內容相關",
        "clarification_question": question,
        "clarification_field_key": key,
    }


def service(classifications, responses):
    ids = iter(f"id-{index}" for index in range(100))
    registry = make_registry()
    classifier = FakeClassifier(classifications, registry.version)
    extractor = FakeExtractor(responses)
    sut = ContextIntakeService(
        classifier=classifier, extractor=extractor, registry=registry,
        id_factory=lambda: next(ids),
    )
    return sut, classifier, extractor


def test_unknown_does_not_extract_or_assign_category():
    sut, classifier, extractor = service([None], [])

    result = sut.process_turn(participant_id="p1", session_id="s1", message="不確定的問題")

    assert result.category_id is None
    assert result.session.active_category_id is None
    assert result.session.active_case_id is None
    assert result.clarification
    assert not extractor.requests
    assert len(classifier.calls) == 1
    event = result.session.turn_events[0]
    assert event.case_id is None and event.category_id is None
    assert event.classification.is_unknown is True
    assert event.classification.top1_similarity == 0.2
    assert event.catalog_version == sut.registry.version
    assert event.category_source == "classification"


def test_pending_answer_continues_without_reclassification_and_only_updates_pending_key():
    sut, classifier, extractor = service(
        ["exposure"],
        [
            payload(["exposure_datetime"], question="大約是哪一天？", key="exposure_datetime"),
            # Even if the model selects another field, a short answer may only
            # populate the field asked in the preceding turn.
            payload(["exposure_datetime", "test_count"],
                    {"exposure_datetime": "昨天", "test_count": 4}),
        ],
    )

    first = sut.process_turn(
        participant_id="p1", session_id="s1", message="我想詢問一次暴露", new_case=True,
    )
    second = sut.process_turn(participant_id="p1", session_id="s1", message="昨天")

    assert first.session.active_case_id is not None
    assert second.category_id == "exposure"
    assert second.category_source == "continuation"
    assert second.classification is None
    assert len(classifier.calls) == 1
    assert second.session.active_case_id == first.session.active_case_id
    case = second.session.cases[second.session.active_case_id]
    assert case.attributes["exposure_datetime"].value == "昨天"
    assert "test_count" not in case.attributes
    assert second.session.pending_question is None
    assert extractor.requests[1].context == ("大約是哪一天？",)
    assert [event.category_source for event in second.session.turn_events] == [
        "classification", "continuation",
    ]
    assert second.extraction.selected_fields == ("exposure_datetime", "test_count")
    assert second.session.turn_events[-1].selected_fields == ("exposure_datetime",)
    assert second.session.turn_events[-1].case_id == first.session.active_case_id
    assert second.session.turn_events[-1].classification is None


def test_category_switch_reuses_same_case_attribute_and_new_event_is_separate_case():
    sut, _, extractor = service(
        ["exposure", "window_period", "exposure"],
        [
            payload(["exposure_datetime"], {"exposure_datetime": "昨天"}),
            payload(["exposure_datetime"], {}),
            payload(["exposure_datetime"], {"exposure_datetime": "今天"}),
        ],
    )

    first = sut.process_turn(participant_id="p1", session_id="s1", message="暴露問題", new_case=True)
    switched = sut.process_turn(participant_id="p1", session_id="s1", message="空窗期多久？")
    second_event = sut.process_turn(
        participant_id="p1", session_id="s1", message="又有一次暴露", new_case=True,
    )

    assert switched.session.active_case_id == first.session.active_case_id
    assert extractor.requests[1].known_attributes["exposure_datetime"] == "昨天"
    assert second_event.session.active_case_id != first.session.active_case_id
    assert second_event.session.cases[first.session.active_case_id].attributes["exposure_datetime"].value == "昨天"
    assert second_event.session.cases[second_event.session.active_case_id].attributes["exposure_datetime"].value == "今天"
    assert [event.category_id for event in second_event.session.turn_events] == [
        "exposure", "window_period", "exposure",
    ]
    assert [event.case_id for event in second_event.session.turn_events] == [
        first.session.active_case_id, first.session.active_case_id,
        second_event.session.active_case_id,
    ]


def test_corrected_exposure_datetime_is_reused_by_another_category():
    sut, _, extractor = service(
        ["exposure", "exposure", "test_result_interpretation"],
        [
            payload(["exposure_datetime"], {"exposure_datetime": "昨天"}),
            payload(["exposure_datetime"], {"exposure_datetime": "前天"}),
            payload(["exposure_datetime"], {}),
        ],
    )

    first = sut.process_turn(participant_id="p1", session_id="s1", message="一次暴露", new_case=True)
    corrected = sut.process_turn(
        participant_id="p1", session_id="s1", message="更正暴露時間", correct_fields=("exposure_datetime",),
    )
    interpreted = sut.process_turn(
        participant_id="p1", session_id="s1", message="詢問檢驗結果",
    )

    assert interpreted.session.active_case_id == first.session.active_case_id
    assert interpreted.session.cases[first.session.active_case_id].attributes["exposure_datetime"].value == "前天"
    assert extractor.requests[-1].known_attributes["exposure_datetime"] == "前天"
    assert corrected.session.turn_events[-1].selected_fields == ("exposure_datetime",)


def test_conflicting_value_is_pending_then_explicit_correction_is_historicized():
    sut, _, _ = service(
        ["exposure", "window_period"],
        [
            payload(["exposure_datetime"], {"exposure_datetime": "昨天"}),
            payload(["exposure_datetime"], {"exposure_datetime": "今天"}),
            payload(["exposure_datetime"], {"exposure_datetime": "前天"}),
        ],
    )

    first = sut.process_turn(participant_id="p1", session_id="s1", message="第一次", new_case=True)
    conflict = sut.process_turn(participant_id="p1", session_id="s1", message="空窗期")
    case_id = first.session.active_case_id
    assert conflict.session.cases[case_id].attributes["exposure_datetime"].value == "昨天"
    assert conflict.session.pending_conflict is not None
    assert conflict.session.pending_conflict.candidate_value == "今天"
    corrected = sut.process_turn(
        participant_id="p1", session_id="s1", message="我更正為前天", correct_fields=("exposure_datetime",),
    )

    value = corrected.session.cases[case_id].attributes["exposure_datetime"]
    assert value.value == "前天"
    assert [change.action for change in value.history] == ["add", "correct"]
    assert value.history[-1].old_value == "昨天"
    assert corrected.session.pending_conflict is None


def test_false_and_zero_are_valid_and_education_without_case_skips_extraction():
    sut, _, extractor = service(
        ["exposure", "education"],
        [payload(["is_protected", "test_count"], {"is_protected": False, "test_count": 0})],
    )

    case_turn = sut.process_turn(
        participant_id="p1", session_id="s1", message="事件情境", new_case=True,
    )
    case = case_turn.session.cases[case_turn.session.active_case_id]
    assert case.attributes["is_protected"].value is False
    assert case.attributes["test_count"].value == 0
    education = sut.process_turn(participant_id="p2", session_id="s2", message="一般知識")
    assert education.category_id == "education"
    assert education.session.active_case_id is None
    assert education.session.turn_events[0].case_id is None
    assert education.session.turn_events[0].category_id == "education"
    assert not hasattr(education.session.turn_events[0], "message")
    assert len(extractor.requests) == 1


def test_explicit_conflict_confirmation_records_confirm_action():
    sut, _, _ = service(
        ["exposure", "window_period"],
        [
            payload(["exposure_datetime"], {"exposure_datetime": "昨天"}),
            payload(["exposure_datetime"], {"exposure_datetime": "今天"}),
        ],
    )
    first = sut.process_turn(participant_id="p1", session_id="s1", message="第一次", new_case=True)
    conflict = sut.process_turn(participant_id="p1", session_id="s1", message="空窗期")
    confirmed = sut.process_turn(
        participant_id="p1", session_id="s1", message="是", confirm_conflict=True,
    )
    value = confirmed.session.cases[first.session.active_case_id].attributes["exposure_datetime"]
    assert value.value == "今天"
    assert value.history[-1].action == "confirm"
    assert conflict.session.pending_conflict is not None


def test_pending_conflict_can_keep_old_value_and_requires_explicit_pending_conflict():
    sut, classifier, _ = service(
        ["exposure", "window_period"],
        [
            payload(["exposure_datetime"], {"exposure_datetime": "昨天"}),
            payload(["exposure_datetime"], {"exposure_datetime": "今天"}),
        ],
    )
    first = sut.process_turn(participant_id="p1", session_id="s1", message="第一次", new_case=True)
    sut.process_turn(participant_id="p1", session_id="s1", message="空窗期")
    resolved = sut.process_turn(
        participant_id="p1", session_id="s1", message="保留原本", keep_existing=True,
    )
    value = resolved.session.cases[first.session.active_case_id].attributes["exposure_datetime"]
    assert value.value == "昨天"
    assert len(value.history) == 1
    assert resolved.session.pending_conflict is None
    assert len(classifier.calls) == 2
    with pytest.raises(ValueError, match="requires a pending conflict"):
        sut.process_turn(participant_id="p1", session_id="s1", message="確認", keep_existing=True)


def test_explicit_new_question_clears_pending_and_reclassifies_unknown():
    sut, classifier, extractor = service(
        ["exposure", None],
        [payload(["exposure_datetime"], question="哪一天？", key="exposure_datetime")],
    )
    first = sut.process_turn(participant_id="p1", session_id="s1", message="暴露", new_case=True)
    switched = sut.process_turn(
        participant_id="p1", session_id="s1", message="換個問題", new_question=True,
    )
    assert len(classifier.calls) == 2
    assert len(extractor.requests) == 1
    assert first.session.pending_question is not None
    assert switched.session.pending_question is None
    assert switched.session.active_category_id is None
    assert switched.session.active_case_id == first.session.active_case_id


def test_multiple_conflicts_reject_turn_without_mutating_session():
    sut, _, _ = service(
        ["exposure", "exposure"],
        [
            payload(["exposure_datetime", "test_count"],
                    {"exposure_datetime": "昨天", "test_count": 1}),
            payload(["exposure_datetime", "test_count"],
                    {"exposure_datetime": "今天", "test_count": 2}),
        ],
    )
    first = sut.process_turn(participant_id="p1", session_id="s1", message="第一次", new_case=True)
    with pytest.raises(ValueError, match="multiple fields"):
        sut.process_turn(participant_id="p1", session_id="s1", message="第二次說明")
    stored = sut.sessions["s1"]
    case = stored.cases[first.session.active_case_id]
    assert case.attributes["exposure_datetime"].value == "昨天"
    assert case.attributes["test_count"].value == 1
    assert stored.pending_conflict is None
    assert len(stored.turn_events) == 1


def test_continuation_cannot_redirect_clarification_to_another_field():
    sut, _, _ = service(
        ["exposure"],
        [
            payload(["exposure_datetime"], question="哪一天？", key="exposure_datetime"),
            payload(["exposure_datetime", "test_count"], {},
                    question="幾次？", key="test_count"),
        ],
    )
    first = sut.process_turn(participant_id="p1", session_id="s1", message="暴露", new_case=True)
    with pytest.raises(ValueError, match="cannot change the pending"):
        sut.process_turn(participant_id="p1", session_id="s1", message="昨天")
    assert sut.sessions["s1"].pending_question == first.session.pending_question
    assert len(sut.sessions["s1"].cases[first.session.active_case_id].attributes) == 0


def test_caller_urgent_handoff_preempts_pending_intake_without_clearing_state():
    sut, classifier, extractor = service(
        ["exposure"],
        [payload(["exposure_datetime"], question="哪一天？", key="exposure_datetime")],
    )
    first = sut.process_turn(participant_id="p1", session_id="s1", message="暴露", new_case=True)
    result = sut.process_turn(
        participant_id="p1", session_id="s1", message="急迫狀況", urgent_handoff=True,
    )
    assert result.handoff_required is True
    assert result.category_source == "handoff"
    assert result.classification is None and result.extraction is None
    assert result.session.pending_question == first.session.pending_question
    assert len(classifier.calls) == 1
    assert len(extractor.requests) == 1
    assert result.session.turn_events[-1].category_source == "handoff"
    assert result.session.turn_events[-1].case_id == first.session.active_case_id
    assert result.session.turn_events[-1].category_id == "exposure"


def test_extractor_does_not_repeat_clarification_for_known_field():
    sut, _, _ = service(
        ["exposure"],
        [payload(["exposure_datetime"], {"exposure_datetime": "昨天"},
                 question="哪一天？", key="exposure_datetime")],
    )
    result = sut.process_turn(participant_id="p1", session_id="s1", message="昨天", new_case=True)
    assert result.clarification is None
    assert result.session.pending_question is None


def test_corrections_without_known_fields_or_with_duplicates_are_rejected():
    sut, _, _ = service(["exposure"], [])
    with pytest.raises(ValueError, match="not contain duplicates"):
        sut.process_turn(
            participant_id="p1", session_id="s1", message="暴露", new_case=True,
            correct_fields=("exposure_datetime", "exposure_datetime"),
        )
    with pytest.raises(ValueError, match="requires an active case"):
        sut.process_turn(
            participant_id="p1", session_id="s1", message="暴露", correct_fields=("exposure_datetime",),
        )


def test_clear_case_keeps_history_but_unbinds_later_education_turn():
    sut, _, extractor = service(
        ["exposure", "education"],
        [payload(["exposure_datetime"], {"exposure_datetime": "昨天"})],
    )
    first = sut.process_turn(
        participant_id="p1", session_id="s1", message="暴露情境", new_case=True,
    )
    old_case_id = first.session.active_case_id
    cleared = sut.process_turn(
        participant_id="p1", session_id="s1", message="一般衛教問題", clear_case=True,
    )

    assert cleared.session.active_case_id is None
    assert old_case_id in cleared.session.cases
    assert cleared.session.cases[old_case_id].attributes["exposure_datetime"].value == "昨天"
    assert len(extractor.requests) == 1
    assert [event.category_id for event in cleared.session.turn_events] == ["exposure", "education"]
    assert [event.case_id for event in cleared.session.turn_events] == [old_case_id, None]
    assert cleared.session.turn_events[-1].selected_fields == ()
