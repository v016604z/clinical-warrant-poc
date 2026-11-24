"""Service and SQLite persistence integration checks."""

import json
import sqlite3
from itertools import count

import pytest

from clinical_warrant.modules.context_intake.application.intake import ContextIntakeService
from clinical_warrant.modules.context_intake.application.conversation_orchestrator import ConversationOrchestrator
from clinical_warrant.modules.context_intake.domain.category_registry import validate_category_registry
from clinical_warrant.modules.context_intake.domain.classification import IntakeClassificationResult
from clinical_warrant.modules.context_intake.infrastructure.sqlite_repository import (
    SQLiteContextIntakeRepository,
    initialize_database,
)
from clinical_warrant.modules.context_intake.infrastructure.openai_adapter import OpenAIAdapterError


def make_registry(extra_field=False):
    fields = {"note": {"type": "string", "description": "描述"}}
    if extra_field:
        fields["location"] = {"type": "string", "description": "地點"}
    return validate_category_registry([
        {
            "category_id": "exposure",
            "category_name": "暴露",
            "fields": fields,
        },
        {"category_id": "other", "category_name": "其他", "fields": {}},
    ])


class Classifier:
    def __init__(self, version):
        self.catalog_version = version

    def classify(self, query):
        return IntakeClassificationResult(
            "exposure", 0.9, "other", 0.1, False,
            "fake", "test", self.catalog_version,
        )


class Extractor:
    def extract(self, request):
        return json.dumps({
            "selected_fields": ["note"],
            "extracted_attributes": {"note": "已記錄"},
            "selection_reason": "內容相符",
            "clarification_question": None,
            "clarification_field_key": None,
        }, ensure_ascii=False)


class RoutedFakeClassifier:
    def __init__(self, registry, categories):
        self.registry = registry
        self.categories = iter(categories)

    def classify(self, _message):
        category_id = next(self.categories)
        top = category_id or "exposure"
        other = "other" if top != "other" else "exposure"
        return IntakeClassificationResult(
            top, 0.9 if category_id else 0.1, other, 0.1,
            category_id is None, "fake", "test", self.registry.version,
        )


class RoutedFakeRouter:
    def __init__(self, decisions):
        self.decisions = iter(decisions)
        self.calls = 0

    def route(self, _request):
        self.calls += 1
        decision = next(self.decisions)
        if isinstance(decision, Exception):
            raise decision
        return decision


class RoutedFakeExtractor:
    def extract(self, _request):
        return json.dumps({
            "selected_fields": ["note"],
            "extracted_attributes": {"note": "explicit fact"},
            "selection_reason": "user stated it",
            "clarification_question": None,
            "clarification_field_key": None,
        })


def route_json(action, evidence, question=None):
    return json.dumps({
        "action": action,
        "evidence": evidence,
        "clarification_question": question,
    })


def id_factory():
    values = count()
    return lambda: f"generated-{next(values)}"


def build_service(repository, registry):
    return ContextIntakeService(
        classifier=Classifier(registry.version), extractor=Extractor(),
        registry=registry, repository=repository,
    )


def test_service_persists_then_reloads_and_delete_evicts_sessions():
    connection = sqlite3.connect(":memory:")
    initialize_database(connection)
    repository = SQLiteContextIntakeRepository(connection)
    registry = make_registry()
    service = build_service(repository, registry)

    result = service.process_turn(
        participant_id="p1", session_id="s1", message="一次暴露", new_case=True,
    )
    case_id = result.session.active_case_id
    assert repository.load_session("s1") == result.session

    restored = build_service(repository, registry)
    next_turn = restored.process_turn(
        participant_id="p1", session_id="s1", message="再補充",
    )
    assert next_turn.session.cases[case_id].attributes["note"].value == "已記錄"

    assert restored.delete_case("p1", case_id) is True
    assert "s1" not in restored.sessions
    assert repository.get_case(case_id, "p1") is None


def test_select_and_clear_active_case_persist_atomically_and_enforce_ownership(tmp_path):
    db_path = tmp_path / "case-selection.sqlite"
    registry = make_registry()
    connection = sqlite3.connect(db_path)
    initialize_database(connection)
    repository = SQLiteContextIntakeRepository(connection)
    service = ContextIntakeService(
        classifier=Classifier(registry.version), extractor=Extractor(),
        registry=registry, repository=repository, id_factory=id_factory(),
    )
    first = service.process_turn(
        participant_id="p1", session_id="s1", message="first", new_case=True,
    )
    first_case_id = first.session.active_case_id
    second = service.process_turn(
        participant_id="p1", session_id="s1", message="second", new_case=True,
    )
    second_case_id = second.session.active_case_id
    assert second_case_id != first_case_id
    other_session = service.process_turn(
        participant_id="p1", session_id="s2", message="other session", new_case=True,
    )
    other_session_case_id = other_session.session.active_case_id

    selected = service.select_case("p1", "s1", first_case_id)
    assert selected.active_case_id == first_case_id
    assert set(selected.cases) == {first_case_id, second_case_id}
    cleared = service.clear_active_case("p1", "s1")
    assert cleared.active_case_id is None
    assert cleared.active_category_id is None
    assert set(cleared.cases) == {first_case_id, second_case_id}
    connection.close()

    reopened = sqlite3.connect(db_path)
    restored_repository = SQLiteContextIntakeRepository(reopened)
    restored = build_service(restored_repository, registry)
    persisted = restored_repository.load_session("s1")
    assert persisted.active_case_id == cleared.active_case_id
    assert persisted.active_case_id is None
    assert {first_case_id, second_case_id}.issubset(persisted.cases)
    assert persisted.cases[first_case_id] == cleared.cases[first_case_id]
    assert persisted.cases[second_case_id] == cleared.cases[second_case_id]
    before_rejected_operations = persisted

    with pytest.raises(ValueError, match="participant"):
        restored.select_case("p2", "s1", first_case_id)
    with pytest.raises(ValueError, match="case"):
        restored.select_case("p1", "s1", "case-does-not-exist")
    with pytest.raises(ValueError, match="case"):
        restored.select_case("p1", "s1", other_session_case_id)

    assert restored_repository.load_session("s1") == before_rejected_operations
    assert restored.sessions == {}

    other_session_state = restored_repository.load_session("s2")
    assert first_case_id in other_session_state.cases
    before_other_session_rejection = other_session_state
    with pytest.raises(ValueError, match="case"):
        restored.select_case("p1", "s2", first_case_id)
    assert restored_repository.load_session("s2") == before_other_session_rejection
    reopened.close()


def test_failed_save_does_not_publish_session_to_memory():
    class BrokenRepository:
        def load_session(self, session_id):
            return None

        def save_session(self, session):
            raise OSError("disk unavailable")

        def delete_case(self, case_id, participant_id):
            return False

    registry = make_registry()
    service = build_service(BrokenRepository(), registry)
    with pytest.raises(OSError, match="disk unavailable"):
        service.process_turn(
            participant_id="p1", session_id="s1", message="一次暴露", new_case=True,
        )
    assert service.sessions == {}


def test_load_rejects_active_session_from_different_registry_version():
    connection = sqlite3.connect(":memory:")
    initialize_database(connection)
    repository = SQLiteContextIntakeRepository(connection)
    original_registry = make_registry()
    original_service = build_service(repository, original_registry)
    original = original_service.process_turn(
        participant_id="p1", session_id="s1", message="一次暴露", new_case=True,
    ).session

    current_registry = make_registry(extra_field=True)
    restored = build_service(repository, current_registry)
    with pytest.raises(ValueError, match="different Category Registry version"):
        restored.process_turn(participant_id="p1", session_id="s1", message="補充")

    assert restored.sessions == {}
    assert repository.load_session("s1") == original


def test_real_orchestrator_sqlite_restart_restores_case_and_restatement_gate(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-secret-marker")
    db_path = tmp_path / "restart.sqlite"
    registry = make_registry()
    connection = sqlite3.connect(db_path)
    initialize_database(connection)
    repository = SQLiteContextIntakeRepository(connection)
    service = ContextIntakeService(
        classifier=RoutedFakeClassifier(registry, ["exposure", None]),
        extractor=RoutedFakeExtractor(), registry=registry, repository=repository,
        id_factory=id_factory(),
    )
    router = RoutedFakeRouter([
        route_json("new_case", "possible event"),
        route_json("clarify", "not sure", "Please restate the event."),
    ])
    orchestrator = ConversationOrchestrator(service, router)

    first = orchestrator.process_turn(
        participant_id="p1", session_id="s1", message="possible event",
    )
    case_id = first.session.active_case_id
    assert first.session.cases[case_id].attributes["note"].value == "explicit fact"
    clarification = orchestrator.process_turn(
        participant_id="p1", session_id="s1", message="not sure",
    )
    assert clarification.session.awaiting_case_restatement is True
    tables = [row[0] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )]
    stored_values = []
    for table in tables:
        for row in connection.execute(f'SELECT * FROM "{table}"'):
            stored_values.extend(str(value) for value in row if value is not None)
    stored_dump = "\n".join(stored_values)
    assert "possible event" not in stored_dump
    assert "not sure" not in stored_dump
    assert "sk-test-secret-marker" not in stored_dump
    persisted_before_restart = repository.load_session("s1")
    connection.close()

    reopened = sqlite3.connect(db_path)
    restored_repository = SQLiteContextIntakeRepository(reopened)
    restored_service = ContextIntakeService(
        classifier=RoutedFakeClassifier(registry, [None]),
        extractor=RoutedFakeExtractor(), registry=registry,
        repository=restored_repository,
    )
    restored_router = RoutedFakeRouter([])
    restored_orchestrator = ConversationOrchestrator(restored_service, restored_router)
    short_answer = restored_orchestrator.process_turn(
        participant_id="p1", session_id="s1", message="new",
    )

    assert short_answer.session.awaiting_case_restatement is True
    assert short_answer.session.active_case_id == case_id
    assert short_answer.session.cases[case_id].attributes["note"].value == "explicit fact"
    assert restored_router.calls == 0
    assert restored_repository.load_session("s1") == persisted_before_restart
    reopened.close()


def test_router_api_error_leaves_sqlite_session_snapshot_unchanged(tmp_path):
    db_path = tmp_path / "router-error.sqlite"
    registry = make_registry()
    connection = sqlite3.connect(db_path)
    initialize_database(connection)
    repository = SQLiteContextIntakeRepository(connection)
    service = ContextIntakeService(
        classifier=RoutedFakeClassifier(registry, ["exposure", "exposure"]),
        extractor=RoutedFakeExtractor(), registry=registry, repository=repository,
        id_factory=id_factory(),
    )
    orchestrator = ConversationOrchestrator(service, RoutedFakeRouter([
        route_json("new_case", "possible event"),
        OpenAIAdapterError("fake API failure"),
    ]))
    orchestrator.process_turn(
        participant_id="p1", session_id="s1", message="possible event",
    )
    before = repository.load_session("s1")

    with pytest.raises(OpenAIAdapterError, match="fake API failure"):
        orchestrator.process_turn(
            participant_id="p1", session_id="s1", message="another event",
        )

    assert repository.load_session("s1") == before
    connection.close()
