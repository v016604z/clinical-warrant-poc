"""Service and SQLite persistence integration checks."""

import json
import sqlite3

import pytest

from clinical_warrant.modules.context_intake.application.intake import ContextIntakeService
from clinical_warrant.modules.context_intake.domain.category_registry import validate_category_registry
from clinical_warrant.modules.context_intake.domain.classification import IntakeClassificationResult
from clinical_warrant.modules.context_intake.infrastructure.sqlite_repository import (
    SQLiteContextIntakeRepository,
    initialize_database,
)


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
