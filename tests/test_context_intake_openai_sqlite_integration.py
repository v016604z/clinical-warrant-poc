"""Offline OpenAI adapter integration checks across orchestration and SQLite."""

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from itertools import count

import pytest

from clinical_warrant.modules.context_intake.application.case_router import CaseRouteError
from clinical_warrant.modules.context_intake.application.conversation_orchestrator import ConversationOrchestrator
from clinical_warrant.modules.context_intake.application.coverage import calculate_case_coverage
from clinical_warrant.modules.context_intake.application.extraction import (
    ExtractionRequest,
    parse_extraction_response,
)
from clinical_warrant.modules.context_intake.application.intake import ContextIntakeService
from clinical_warrant.modules.context_intake.domain.category_registry import validate_category_registry
from clinical_warrant.modules.context_intake.domain.classification import IntakeClassificationResult
from clinical_warrant.modules.context_intake.infrastructure.openai_adapter import OpenAIAdapterError
from clinical_warrant.modules.context_intake.infrastructure.openai_adapter import OpenAIResponsesAdapter
from clinical_warrant.modules.context_intake.infrastructure.openai_case_router import OpenAICaseRouter
from clinical_warrant.modules.context_intake.infrastructure.openai_extractor import (
    OpenAIExtractionError,
    OpenAIExtractor,
)
from clinical_warrant.modules.context_intake.infrastructure.sqlite_repository import (
    SQLiteContextIntakeRepository,
    initialize_database,
)


def _registry():
    return validate_category_registry([{
        "category_id": "personal_event",
        "category_name": "Personal event",
        "fields": {"date": {"type": "string", "description": "When the event occurred"}},
    }])


class _Classifier:
    def __init__(self, registry):
        self.version = registry.version
        self.calls = []

    def classify(self, message):
        self.calls.append(message)
        return IntakeClassificationResult(
            "personal_event", 0.9, "other", 0.1, False,
            "fake-classifier", "test", self.version,
        )


class FakeOpenAIAdapter:
    """Return queued structured outputs without importing or calling the SDK."""

    def __init__(self, *, routes=(), extractions=()):
        self.routes = list(routes)
        self.extractions = list(extractions)
        self.calls = []

    def create_structured_response(self, **kwargs):
        self.calls.append(kwargs)
        queue = self.routes if kwargs["schema_name"] == "context_intake_case_route" else self.extractions
        output = queue.pop(0)
        if isinstance(output, Exception):
            raise output
        return output


def _route(action, evidence, question=None):
    return json.dumps({
        "action": action,
        "evidence": evidence,
        "clarification_question": question,
    })


def _extraction(*, value=None, evidence=None, question=None):
    return json.dumps({
        "selected_fields": ["date"],
        "extracted_attributes": {"date": value},
        "evidence": {"date": evidence},
        "selection_reason": "Only use the explicitly stated date.",
        "clarification_question": question,
        "clarification_field_key": "date" if question else None,
    })


def _runtime(connection, registry, adapter, *, id_start=0):
    repository = SQLiteContextIntakeRepository(connection)
    classifier = _Classifier(registry)
    service = ContextIntakeService(
        classifier=classifier,
        extractor=OpenAIExtractor(adapter=adapter),
        registry=registry,
        repository=repository,
        id_factory=lambda values=count(id_start): f"id-{next(values)}",
    )
    router = OpenAICaseRouter(adapter=adapter)
    return ConversationOrchestrator(service, router), classifier, repository


def test_fake_openai_multiturn_pending_question_recovers_and_coverage_completes(tmp_path):
    db_path = tmp_path / "openai-multiturn.sqlite"
    registry = _registry()
    connection = sqlite3.connect(db_path)
    initialize_database(connection)
    adapter = FakeOpenAIAdapter(
        routes=[
            _route("new_case", "A package arrived recently"),
            _route("continue_case", "do not remember"),
            _route("continue_case", "Monday"),
        ],
        extractions=[
            _extraction(question="When did it arrive?"),
            _extraction(question="When did it arrive?"),
            _extraction(value="Monday", evidence="Monday"),
        ],
    )
    orchestrator, classifier, repository = _runtime(connection, registry, adapter)

    first = orchestrator.process_turn(
        participant_id="p1", session_id="s1", message="A package arrived recently",
    )
    case_id = first.session.active_case_id
    assert first.session.pending_question is not None
    assert first.session.cases[case_id].attributes == {}
    second = orchestrator.process_turn(
        participant_id="p1", session_id="s1", message="I do not remember",
    )
    assert second.session.pending_question == first.session.pending_question
    assert second.session.cases[case_id].attributes == {}
    checkpoint = repository.load_session("s1")
    connection.close()

    resumed_connection = sqlite3.connect(db_path)
    resumed_adapter = FakeOpenAIAdapter(
        routes=[_route("continue_case", "Monday")],
        extractions=[_extraction(value="Monday", evidence="Monday")],
    )
    resumed, resumed_classifier, resumed_repository = _runtime(
        resumed_connection, registry, resumed_adapter, id_start=3,
    )
    assert resumed_repository.load_session("s1") == checkpoint
    final = resumed.process_turn(
        participant_id="p1", session_id="s1", message="It arrived Monday",
    )

    state = resumed_repository.load_session("s1")
    assert final.session.active_case_id == case_id
    assert state.cases[case_id].attributes["date"].value == "Monday"
    assert state.pending_question is None
    assert len(state.turn_events) == 3
    assert len(adapter.calls) == 4
    assert len(resumed_adapter.calls) == 2
    assert classifier.calls == ["A package arrived recently"]
    assert resumed_classifier.calls == []
    coverage = calculate_case_coverage(
        registry, state.cases[case_id], state.turn_events, "personal_event",
    )
    assert (coverage.selected_count, coverage.known_count, coverage.coverage_rate) == (1, 1, 1.0)
    assert resumed_repository.load_session("s1") == final.session
    resumed_connection.close()


@pytest.mark.parametrize(
    ("failure_point", "failure", "expected_error"),
    [
        ("router", OpenAIAdapterError("timeout"), OpenAIAdapterError),
        ("router", OpenAIAdapterError("429 quota"), OpenAIAdapterError),
        ("extractor", OpenAIAdapterError("timeout"), OpenAIAdapterError),
        ("extractor", '{"refusal":"refused"}', OpenAIExtractionError),
        ("extractor", '{malformed json', OpenAIExtractionError),
        ("router", '{"action":"new_case","unexpected":"case-id"}', CaseRouteError),
    ],
)
def test_api_or_schema_failures_never_persist_incomplete_case(
    tmp_path, failure_point, failure, expected_error,
):
    connection = sqlite3.connect(tmp_path / f"failure-{failure_point}-{expected_error.__name__}.sqlite")
    initialize_database(connection)
    registry = _registry()
    valid_route = _route("new_case", "The visit was Monday")
    valid_extraction = _extraction(value="Monday", evidence="Monday")
    adapter = FakeOpenAIAdapter(
        routes=[failure if failure_point == "router" else valid_route],
        extractions=[failure if failure_point == "extractor" else valid_extraction],
    )
    orchestrator, _, repository = _runtime(connection, registry, adapter)

    with pytest.raises(expected_error):
        orchestrator.process_turn(
            participant_id="p1", session_id="s1", message="The visit was Monday",
        )

    assert repository.load_session("s1") is None
    assert repository.get_case("id-1", participant_id="p1") is None
    assert orchestrator.intake_service.sessions == {}
    connection.close()


def test_fake_sdk_retry_exhaustion_does_not_create_a_case(tmp_path):
    class APIError(Exception):
        pass

    class RateLimitError(APIError):
        pass

    class RetryingResponses:
        """Model the SDK client's configured retry budget without network access."""

        def __init__(self, retries):
            self.attempts = 0
            self.retries = retries

        def create(self, **_kwargs):
            for _ in range(self.retries + 1):
                self.attempts += 1
                try:
                    raise RateLimitError("private quota response")
                except RateLimitError:
                    if self.attempts > self.retries:
                        raise

    class RetryingSDKClient:
        def __init__(self):
            self.max_retries = 2
            self.responses = RetryingResponses(self.max_retries)

    connection = sqlite3.connect(tmp_path / "quota-retries.sqlite")
    initialize_database(connection)
    registry = _registry()
    client = RetryingSDKClient()
    metadata = []
    adapter = OpenAIResponsesAdapter(
        client=client, max_retries=client.max_retries, on_response=metadata.append,
    )
    orchestrator, _, repository = _runtime(connection, registry, adapter)

    with pytest.raises(OpenAIAdapterError, match="RateLimitError") as error:
        orchestrator.process_turn(
            participant_id="p1", session_id="s1", message="The visit was Monday",
        )

    assert client.responses.attempts == 3
    assert isinstance(error.value.__cause__, RateLimitError)
    assert "private quota response" not in str(error.value)
    assert metadata[0].error_type == "RateLimitError"
    assert repository.load_session("s1") is None
    assert repository.get_case("id-1", participant_id="p1") is None
    assert orchestrator.intake_service.sessions == {}
    connection.close()


@pytest.mark.skipif(
    os.environ.get("RUN_CONTEXT_INTAKE_OPENAI_E2E") != "1",
    reason="set RUN_CONTEXT_INTAKE_OPENAI_E2E=1 to make billable OpenAI routing and extraction requests",
)
def test_real_openai_orchestrator_sqlite_smoke(tmp_path):
    registry = _registry()
    connection = sqlite3.connect(tmp_path / "real-openai-e2e.sqlite")
    initialize_database(connection)
    metadata = []
    adapter = OpenAIResponsesAdapter(on_response=metadata.append)
    service = ContextIntakeService(
        classifier=_Classifier(registry),
        extractor=OpenAIExtractor(adapter=adapter),
        registry=registry,
        repository=SQLiteContextIntakeRepository(connection),
    )
    orchestrator = ConversationOrchestrator(service, OpenAICaseRouter(adapter=adapter))

    result = orchestrator.process_turn(
        participant_id="synthetic-participant",
        session_id="synthetic-session",
        message="A fictional package arrived on Monday.",
    )

    assert result.route_decision.action in {"new_case", "continue_case", "no_case", "clarify"}
    persisted = service.repository.load_session("synthetic-session")
    if result.intake_result is None:
        assert result.route_decision.action == "clarify"
        assert persisted is not None
        assert persisted.awaiting_case_restatement is True
    else:
        assert persisted == result.session
        if result.route_decision.action in {"new_case", "continue_case"}:
            assert len(metadata) == 2
        if persisted.active_case_id is not None:
            assert persisted.active_case_id in persisted.cases
    assert len(metadata) >= 1
    assert all(item.model and item.latency_ms >= 0 for item in metadata)
    connection.close()


@pytest.mark.skipif(
    os.environ.get("RUN_CONTEXT_INTAKE_OPENAI_E2E") != "1",
    reason="set RUN_CONTEXT_INTAKE_OPENAI_E2E=1 to make a billable OpenAI extraction request",
)
def test_real_openai_extractor_accepts_generic_event_schema():
    registry = _registry()
    category = registry.get("personal_event")
    metadata = []
    extractor = OpenAIExtractor(adapter=OpenAIResponsesAdapter(on_response=metadata.append))
    response = extractor.extract(ExtractionRequest(
        message="A fictional package arrived on Monday.",
        category=category,
        known_attributes={},
    ))
    parsed = parse_extraction_response(response, category)

    assert set(parsed.extracted_attributes).issubset(category.fields)
    assert set(parsed.selected_fields).issubset(category.fields)
    assert len(metadata) == 1
    assert metadata[0].model
    assert metadata[0].latency_ms >= 0


def test_synthetic_e2e_runner_cli_writes_offline_report(tmp_path):
    root = Path(__file__).parents[1]
    output_path = tmp_path / "synthetic-report.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(root / "scripts" / "run_context_intake_synthetic_e2e.py"),
            "--output",
            str(output_path),
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
    report = json.loads(output_path.read_text(encoding="utf-8"))
    metrics = report["metrics"]
    assert report["metadata"]["evaluation_type"] == "synthetic_offline_application_sqlite_e2e"
    assert metrics["passed_expected_checks"] is True
    assert metrics["turn_count"] == 5
    assert metrics["classifier_calls"] == 2
    assert metrics["fake_provider_adapter_calls"] == 10
    assert metrics["external_api_calls"] == 0
    assert metrics["session_restores_from_sqlite"] == 4
    assert metrics["repeated_clarification_count"] == 1
    assert metrics["token_usage"]["input_tokens"] is None
    assert metrics["latency"]["network_api_latency_ms"] is None
    assert all(isinstance(value, (int, float)) for value in metrics["latency"]["local_fake_adapter_ms"])
