from dataclasses import replace

import pytest

from clinical_warrant.modules.context_intake.domain.state import (
    CaseState,
    PendingConflict,
    PendingQuestion,
    SessionState,
    TurnEvent,
)
from clinical_warrant.modules.context_intake.domain.classification import IntakeClassificationResult


def case_with_attribute(value="yesterday"):
    return CaseState("case-1", "participant-1").with_attribute("exposure_datetime", value, "turn-1")


def test_add_and_same_value_are_immutable_and_do_not_duplicate_history():
    empty = CaseState("case-1", "participant-1")

    added = empty.with_attribute("exposure_datetime", "yesterday", "turn-1")
    unchanged = added.with_attribute("exposure_datetime", "yesterday", "turn-2")

    assert empty.attributes == {}
    assert unchanged is added
    attribute = added.attributes["exposure_datetime"]
    assert attribute.value == "yesterday"
    assert attribute.source_turn_id == "turn-1"
    assert [change.action for change in attribute.history] == ["add"]


@pytest.mark.parametrize("value", [False, 0])
def test_false_and_zero_are_valid_values(value):
    case = CaseState("case-1", "participant-1").with_attribute("field", value, "turn-1")

    assert case.attributes["field"].value is value


def test_false_and_zero_are_not_treated_as_the_same_value():
    case = CaseState("case-1", "participant-1").with_attribute("field", False, "turn-1")

    with pytest.raises(ValueError, match="explicit correct or confirm"):
        case.with_attribute("field", 0, "turn-2")

    corrected = case.with_attribute("field", 0, "turn-2", action="correct")
    assert corrected.attributes["field"].value == 0
    assert type(corrected.attributes["field"].value) is int


def test_different_value_requires_explicit_correction_and_keeps_history():
    case = case_with_attribute()

    with pytest.raises(ValueError, match="explicit correct or confirm"):
        case.with_attribute("exposure_datetime", "today", "turn-2")

    corrected = case.with_attribute("exposure_datetime", "today", "turn-2", action="correct")
    attribute = corrected.attributes["exposure_datetime"]
    assert attribute.value == "today"
    assert [(item.action, item.old_value, item.new_value, item.source_turn_id) for item in attribute.history] == [
        ("add", None, "yesterday", "turn-1"),
        ("correct", "yesterday", "today", "turn-2"),
    ]
    assert case.attributes["exposure_datetime"].value == "yesterday"


def test_pending_conflict_preserves_existing_value_until_explicit_confirmation():
    case = case_with_attribute("yesterday")
    conflict = PendingConflict(
        case_id="case-1", category_id="personal_exposure_risk", field_key="exposure_datetime",
        old_value="yesterday", candidate_value="today", old_source_turn_id="turn-1",
        candidate_source_turn_id="turn-2",
    )
    session = SessionState(
        "session-1", "participant-1", {case.case_id: case}, case.case_id,
        "personal_exposure_risk", pending_conflict=conflict,
    )

    assert session.cases["case-1"].attributes["exposure_datetime"].value == "yesterday"
    confirmed = case.with_attribute("exposure_datetime", conflict.candidate_value,
                                    "turn-3", action="confirm")
    assert confirmed.attributes["exposure_datetime"].value == "today"
    assert confirmed.attributes["exposure_datetime"].history[-1].action == "confirm"


def test_pending_question_tracks_the_case_category_and_field_for_followup():
    case = CaseState("case-1", "participant-1")
    question = PendingQuestion("case-1", "personal_exposure_risk", "exposure_datetime", "何時發生？")

    state = SessionState("session-1", "participant-1", {case.case_id: case}, case.case_id,
                         "personal_exposure_risk", pending_question=question)

    assert state.pending_question == question
    assert question.field_key == "exposure_datetime"


def test_session_rejects_foreign_or_missing_active_case():
    foreign = CaseState("case-1", "participant-2")

    with pytest.raises(ValueError, match="participant"):
        SessionState("session-1", "participant-1", {"case-1": foreign})
    with pytest.raises(ValueError, match="active case"):
        SessionState("session-1", "participant-1", active_case_id="missing")


def test_pending_question_must_match_session_active_case_and_category():
    case = CaseState("case-1", "participant-1")
    question = PendingQuestion("case-1", "hiv_basics", "field", "請提供資訊")

    with pytest.raises(ValueError, match="active case and category"):
        SessionState("session-1", "participant-1", {"case-1": case}, "case-1",
                     "personal_exposure_risk", pending_question=question)


@pytest.mark.parametrize("value", [None, "", "   "])
def test_attribute_values_reject_missing_values(value):
    with pytest.raises(ValueError):
        CaseState("case-1", "participant-1").with_attribute("field", value, "turn-1")


def classification(*, unknown=False):
    return IntakeClassificationResult(
        top1_category_id="personal_exposure_risk", top1_similarity=0.8,
        top2_category_id="hiv_basics", top2_similarity=0.4, is_unknown=unknown,
        model_id="model", model_revision="revision", catalog_version="catalog-v1",
    )


def test_session_keeps_turn_category_history_when_active_category_changes():
    case = CaseState("case-1", "participant-1")
    first = TurnEvent(
        "turn-1", "case-1", "personal_exposure_risk", "classification",
        classification(), ("exposure_datetime",), "catalog-v1",
    )
    second = TurnEvent(
        "turn-2", "case-1", "hiv_basics", "classification",
        IntakeClassificationResult(
            top1_category_id="hiv_basics", top1_similarity=0.9,
            top2_category_id="personal_exposure_risk", top2_similarity=0.4,
            is_unknown=False, model_id="model", model_revision="revision", catalog_version="catalog-v1",
        ), (), "catalog-v1",
    )

    state = SessionState("session-1", "participant-1", {"case-1": case}, "case-1",
                         "hiv_basics", turn_events=(first, second))

    assert state.active_category_id == "hiv_basics"
    assert [(event.category_id, event.case_id) for event in state.turn_events] == [
        ("personal_exposure_risk", "case-1"), ("hiv_basics", "case-1"),
    ]


def test_exposure_datetime_is_isolated_between_cases():
    first_case = CaseState("case-1", "participant-1").with_attribute(
        "exposure_datetime", "昨天", "turn-1"
    )
    second_case = CaseState("case-2", "participant-1").with_attribute(
        "exposure_datetime", "今天", "turn-2"
    )
    events = (
        TurnEvent("turn-1", "case-1", "personal_exposure_risk", "classification",
                  classification(), ("exposure_datetime",), "catalog-v1"),
        TurnEvent("turn-2", "case-2", "window_period", "classification",
                  IntakeClassificationResult(
                      top1_category_id="window_period", top1_similarity=0.8,
                      top2_category_id="personal_exposure_risk", top2_similarity=0.4,
                      is_unknown=False, model_id="model", model_revision="revision",
                      catalog_version="catalog-v1",
                  ), ("exposure_datetime",), "catalog-v1"),
    )

    session = SessionState(
        "session-1", "participant-1", {"case-1": first_case, "case-2": second_case},
        "case-2", "window_period", turn_events=events,
    )

    assert session.cases["case-1"].attributes["exposure_datetime"].value == "昨天"
    assert session.cases["case-2"].attributes["exposure_datetime"].value == "今天"
    assert [event.case_id for event in session.turn_events] == ["case-1", "case-2"]


def test_unknown_turn_can_keep_scores_without_case_or_category():
    result = classification(unknown=True)
    event = TurnEvent("turn-unknown", None, None, "classification", result, (), "catalog-v1")
    state = SessionState("session-1", "participant-1", turn_events=[event])

    assert state.turn_events == (event,)
    assert state.turn_events[0].classification is result
    assert state.turn_events[0].classification.top1_category_id == "personal_exposure_risk"
    assert state.turn_events[0].category_id is None


def test_continuation_turn_can_omit_classification_but_keep_case_and_category():
    case = CaseState("case-1", "participant-1")
    event = TurnEvent("turn-2", "case-1", "personal_exposure_risk", "continuation",
                      None, (), "catalog-v1")

    state = SessionState("session-1", "participant-1", {"case-1": case}, "case-1",
                         "personal_exposure_risk", turn_events=(event,))

    assert state.turn_events[0].classification is None
    assert state.turn_events[0].catalog_version == "catalog-v1"


def test_session_rejects_turn_event_for_foreign_case_or_duplicate_turn_id():
    case = CaseState("case-1", "participant-1")
    event = TurnEvent("turn-1", "case-1", "personal_exposure_risk", "classification",
                      classification(), (), "catalog-v1")
    foreign_case_event = replace(event, turn_id="turn-2", case_id="missing-case")

    with pytest.raises(ValueError, match="turn event case"):
        SessionState("session-1", "participant-1", {"case-1": case}, turn_events=(foreign_case_event,))
    with pytest.raises(ValueError, match="unique"):
        SessionState("session-1", "participant-1", {"case-1": case}, turn_events=(event, event))
