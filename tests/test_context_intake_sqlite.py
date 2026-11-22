import sqlite3

import pytest

from clinical_warrant.modules.context_intake.domain.classification import IntakeClassificationResult
from clinical_warrant.modules.context_intake.domain.state import (
    AttributeChange,
    AttributeValue,
    CaseState,
    PendingConflict,
    PendingQuestion,
    SessionState,
    TurnEvent,
)
from clinical_warrant.modules.context_intake.infrastructure.sqlite_repository import (
    SQLiteContextIntakeRepository,
    initialize_database,
)


def classification(*, unknown=False):
    return IntakeClassificationResult(
        "personal_exposure_risk", 0.82, "hiv_basics", 0.31, unknown,
        "model-x", "rev-7", "catalog-v1",
    )


def session_fixture():
    case = CaseState("case-1", "participant-1").with_attribute(
        "exposure_datetime", "yesterday", "turn-1"
    )
    case = case.with_attribute("exposure_datetime", "today", "turn-3", action="correct")
    events = (
        TurnEvent("turn-1", "case-1", "personal_exposure_risk", "classification",
                  classification(), ("exposure_datetime",), "catalog-v1"),
        TurnEvent("turn-2", None, None, "classification", classification(unknown=True), (), "catalog-v1"),
        TurnEvent("turn-3", "case-1", "personal_exposure_risk", "continuation",
                  None, ("exposure_datetime",), "catalog-v1"),
    )
    question = PendingQuestion("case-1", "personal_exposure_risk", "exposure_datetime", "何時發生？")
    return SessionState(
        "session-1", "participant-1", {"case-1": case}, "case-1",
        "personal_exposure_risk", question, None, events,
    )


def repository():
    connection = sqlite3.connect(":memory:")
    initialize_database(connection)
    return connection, SQLiteContextIntakeRepository(connection)


def test_initialization_creates_six_tables_and_is_idempotent():
    connection = sqlite3.connect(":memory:")
    initialize_database(connection)
    initialize_database(connection)

    tables = {row[0] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    assert tables == {"participants", "sessions", "case_contexts", "turn_events",
                      "case_attributes", "attribute_history"}
    assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
    assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_unknown_schema_version_is_rejected_without_downgrade():
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA user_version=99")

    with pytest.raises((ValueError, RuntimeError)):
        initialize_database(connection)

    assert connection.execute("PRAGMA user_version").fetchone()[0] == 99


def test_unknown_turn_has_no_active_catalog_version():
    connection, repo = repository()
    event = TurnEvent("turn-unknown", None, None, "classification",
                      classification(unknown=True), (), "catalog-v1")
    repo.save_session(SessionState("session-unknown", "participant-1", turn_events=(event,)))

    assert connection.execute(
        "SELECT active_category_id, active_catalog_version FROM sessions WHERE session_id=?",
        ("session-unknown",),
    ).fetchone() == (None, None)


def test_session_pending_attributes_and_events_round_trip():
    connection, repo = repository()
    original = session_fixture()

    repo.save_session(original)
    loaded = repo.load_session("session-1")

    assert loaded == original
    attr = loaded.cases["case-1"].attributes["exposure_datetime"]
    assert (attr.value, attr.source_turn_id) == ("today", "turn-3")
    assert [(item.action, item.old_value, item.new_value, item.source_turn_id)
            for item in attr.history] == [
        ("add", None, "yesterday", "turn-1"),
        ("correct", "yesterday", "today", "turn-3"),
    ]
    assert loaded.pending_question == original.pending_question
    assert loaded.turn_events == original.turn_events
    assert connection.execute(
        "SELECT active_catalog_version FROM sessions WHERE session_id='session-1'"
    ).fetchone() == ("catalog-v1",)
    assert loaded.turn_events[1].case_id is None
    assert loaded.turn_events[1].category_id is None
    assert loaded.turn_events[1].classification.top1_similarity == 0.82
    assert loaded.turn_events[1].classification.top2_similarity == 0.31
    assert loaded.turn_events[0].selected_fields == ("exposure_datetime",)
    assert loaded.turn_events[2].classification is None
    assert loaded.turn_events[2].catalog_version == "catalog-v1"
    assert [row[0] for row in connection.execute(
        "SELECT turn_order FROM turn_events WHERE session_id='session-1' ORDER BY turn_order"
    )] == [0, 1, 2]


def test_pending_conflict_round_trips_boolean_and_integer_candidates():
    connection, repo = repository()
    case = CaseState("case-1", "participant-1").with_attribute("flag", False, "turn-1")
    conflict = PendingConflict(
        "case-1", "personal_exposure_risk", "flag", False, 0, "turn-1", "turn-2"
    )
    events = (
        TurnEvent("turn-1", "case-1", "personal_exposure_risk", "classification",
                  classification(), ("flag",), "catalog-v1"),
        TurnEvent("turn-2", "case-1", "personal_exposure_risk", "continuation",
                  None, (), "catalog-v1"),
    )
    state = SessionState(
        "session-1", "participant-1", {"case-1": case}, "case-1",
        "personal_exposure_risk", None, conflict, events,
    )

    repo.save_session(state)
    loaded = repo.load_session("session-1")

    assert loaded.pending_conflict == conflict
    assert type(loaded.pending_conflict.old_value) is bool
    assert type(loaded.pending_conflict.candidate_value) is int


def test_same_case_field_is_one_current_row_and_history_keeps_corrections():
    connection, repo = repository()
    original = session_fixture()
    second_case = CaseState("case-2", "participant-1").with_attribute(
        "exposure_datetime", "tomorrow", "turn-4"
    )
    cross_category = TurnEvent(
        "turn-5", "case-1", "pep_post_exposure", "classification",
        IntakeClassificationResult("pep_post_exposure", 0.9, "personal_exposure_risk", 0.4,
                                   False, "model-x", "rev-7", "catalog-v1"),
        ("exposure_datetime",), "catalog-v1",
    )
    state = SessionState(
        original.session_id, original.participant_id,
        {**original.cases, "case-2": second_case}, original.active_case_id,
        original.active_category_id, original.pending_question, original.pending_conflict,
        (*original.turn_events,
         TurnEvent("turn-4", "case-2", "personal_exposure_risk", "classification",
                   classification(), ("exposure_datetime",), "catalog-v1"),
         cross_category),
    )
    repo.save_session(state)

    assert connection.execute(
        "SELECT count(*) FROM case_attributes WHERE case_id='case-1' AND field_key='exposure_datetime'"
    ).fetchone()[0] == 1
    assert connection.execute(
        "SELECT count(*) FROM attribute_history WHERE case_id='case-1' AND field_key='exposure_datetime'"
    ).fetchone()[0] == 2
    assert repo.get_case("case-1", participant_id="participant-1").attributes[
        "exposure_datetime"
    ].value == "today"
    assert repo.get_case("case-2", participant_id="participant-1").attributes[
        "exposure_datetime"
    ].value == "tomorrow"


def test_boolean_false_and_integer_zero_keep_distinct_json_types():
    connection, repo = repository()
    case = CaseState("case-1", "participant-1")
    case = case.with_attribute("is_protected", False, "turn-1")
    case = case.with_attribute("dose_count", 0, "turn-2")
    state = SessionState(
        "session-1", "participant-1", {"case-1": case}, "case-1",
        "personal_exposure_risk", turn_events=(
            TurnEvent("turn-1", "case-1", "personal_exposure_risk", "classification",
                      classification(), ("is_protected",), "catalog-v1"),
            TurnEvent("turn-2", "case-1", "personal_exposure_risk", "classification",
                      classification(), ("dose_count",), "catalog-v1"),
        ),
    )

    repo.save_session(state)
    loaded = repo.get_case("case-1", participant_id="participant-1")

    assert loaded.attributes["is_protected"].value is False
    assert type(loaded.attributes["is_protected"].value) is bool
    assert loaded.attributes["dose_count"].value == 0
    assert type(loaded.attributes["dose_count"].value) is int


def test_foreign_participant_and_session_case_links_are_rejected_by_database():
    connection, repo = repository()
    repo.save_session(session_fixture())

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO sessions(session_id, participant_id) VALUES (?, ?)",
            ("foreign-session", "missing-participant"),
        )
    connection.execute("INSERT INTO participants(participant_id) VALUES (?)", ("participant-2",))
    connection.execute(
        "INSERT INTO sessions(session_id, participant_id) VALUES (?, ?)",
        ("foreign-session", "participant-2"),
    )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "UPDATE sessions SET active_case_id=? WHERE session_id=?",
            ("case-1", "foreign-session"),
        )
        connection.commit()
    connection.rollback()


def test_failed_history_write_rolls_back_entire_session_save():
    connection, repo = repository()
    connection.execute(
        "CREATE TRIGGER reject_history BEFORE INSERT ON attribute_history "
        "BEGIN SELECT RAISE(ABORT, 'injected history failure'); END"
    )

    with pytest.raises(sqlite3.IntegrityError, match="injected history failure"):
        repo.save_session(session_fixture())

    for table in ("participants", "sessions", "case_contexts", "turn_events",
                  "case_attributes", "attribute_history"):
        assert connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0


def test_conflicting_existing_turn_id_is_rejected_and_save_rolls_back():
    connection, repo = repository()
    original = session_fixture()
    repo.save_session(original)
    event = original.turn_events[0]
    conflicting_event = TurnEvent(
        event.turn_id, "case-1", "hiv_basics", "classification",
        IntakeClassificationResult("hiv_basics", 0.9, "personal_exposure_risk", 0.4,
                                   False, "model-x", "rev-7", "catalog-v1"),
        (), "catalog-v1",
    )
    changed = SessionState(
        original.session_id, original.participant_id, original.cases,
        original.active_case_id, original.active_category_id,
        original.pending_question, original.pending_conflict,
        (conflicting_event, *original.turn_events[1:]),
    )

    with pytest.raises((sqlite3.IntegrityError, ValueError)):
        repo.save_session(changed)

    assert repo.load_session("session-1") == original


def test_conflicting_history_order_is_rejected_and_save_rolls_back():
    connection, repo = repository()
    original = session_fixture()
    repo.save_session(original)
    case = CaseState("case-1", "participant-1", {
        "exposure_datetime": AttributeValue(
            "today", "turn-3", (
                AttributeChange("add", None, "different", "turn-1"),
                AttributeChange("correct", "different", "today", "turn-3"),
            ),
        ),
    })
    changed = SessionState(
        original.session_id, original.participant_id, {"case-1": case},
        original.active_case_id, original.active_category_id,
        original.pending_question, original.pending_conflict, original.turn_events,
    )

    with pytest.raises((sqlite3.IntegrityError, ValueError)):
        repo.save_session(changed)

    assert repo.get_case("case-1", participant_id="participant-1").attributes[
        "exposure_datetime"
    ].value == "today"
    assert connection.execute(
        "SELECT count(*) FROM attribute_history WHERE case_id='case-1' AND field_key='exposure_datetime'"
    ).fetchone()[0] == 2


def test_stale_session_snapshot_cannot_overwrite_a_newer_current_attribute():
    connection, repo = repository()
    first = session_fixture()
    old_case = CaseState("case-1", "participant-1").with_attribute(
        "exposure_datetime", "yesterday", "turn-1"
    )
    first_event = first.turn_events[0]
    old_state = SessionState(
        first.session_id, first.participant_id, {"case-1": old_case}, "case-1",
        "personal_exposure_risk", None, None, (first_event,),
    )
    repo.save_session(old_state)
    repo.save_session(first)

    with pytest.raises((sqlite3.IntegrityError, ValueError)):
        repo.save_session(old_state)

    assert repo.get_case("case-1", participant_id="participant-1").attributes[
        "exposure_datetime"
    ].value == "today"


def test_delete_case_clears_references_but_preserves_turn_events():
    connection, repo = repository()
    repo.save_session(session_fixture())

    assert repo.delete_case("case-1", participant_id="participant-1") is True

    assert repo.get_case("case-1", participant_id="participant-1") is None
    assert connection.execute(
        "SELECT active_case_id, active_category_id, active_catalog_version "
        "FROM sessions WHERE session_id='session-1'"
    ).fetchone() == (None, None, None)
    assert connection.execute(
        "SELECT count(*) FROM turn_events WHERE case_id='case-1'"
    ).fetchone()[0] == 0
    assert connection.execute("SELECT count(*) FROM case_attributes").fetchone()[0] == 0
    assert connection.execute("SELECT count(*) FROM attribute_history").fetchone()[0] == 0
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert connection.execute("SELECT count(*) FROM turn_events").fetchone()[0] == 3
    loaded = repo.load_session("session-1")
    assert loaded.pending_question is None
    assert [(event.case_id, event.category_id, event.selected_fields)
            for event in loaded.turn_events] == [
        (None, "personal_exposure_risk", ()),
        (None, None, ()),
        (None, "personal_exposure_risk", ()),
    ]
    assert loaded.turn_events[0].classification == classification()
    assert repo.delete_case("missing-case", participant_id="participant-1") is False

