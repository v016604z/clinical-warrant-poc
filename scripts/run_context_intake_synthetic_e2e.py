"""Run the fixed synthetic Context Intake conversation through SQLite offline."""

from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from clinical_warrant.modules.context_intake import load_category_registry
from clinical_warrant.modules.context_intake.application.conversation_orchestrator import (
    ConversationOrchestrator,
)
from clinical_warrant.modules.context_intake.application.coverage import calculate_case_coverage
from clinical_warrant.modules.context_intake.application.intake import ContextIntakeService
from clinical_warrant.modules.context_intake.domain.classification import IntakeClassificationResult
from clinical_warrant.modules.context_intake.infrastructure.openai_case_router import OpenAICaseRouter
from clinical_warrant.modules.context_intake.infrastructure.openai_extractor import OpenAIExtractor
from clinical_warrant.modules.context_intake.infrastructure.sqlite_repository import (
    SQLiteContextIntakeRepository,
    initialize_database,
)


DEFAULT_FIXTURE = ROOT / "evaluation" / "context_intake" / "synthetic_e2e_multiturn.json"
DEFAULT_REPORT = ROOT / "evaluation" / "context_intake" / "synthetic_e2e_report.json"


class FakeClassifier:
    def __init__(self, fixture: dict, catalog_version: str, calls: list[str]) -> None:
        self.by_message = {step["message"]: step for step in fixture["steps"]}
        self.catalog_version = catalog_version
        self.calls = calls

    def classify(self, query: str) -> IntakeClassificationResult:
        self.calls.append(query)
        step = self.by_message.get(query)
        expected = step.get("classification") if step else None
        if not isinstance(expected, dict):
            raise ValueError("synthetic fixture has no classifier output for this message")
        category_id = expected["category_id"]
        top2 = "hiv_basics" if category_id != "hiv_basics" else "window_period"
        return IntakeClassificationResult(
            category_id, 0.91, top2, 0.58, False,
            "synthetic-fake-classifier", "fixture-1", self.catalog_version,
        )


class FakeResponsesAdapter:
    """Responses adapter double; timings are local fake work, not API latency."""

    def __init__(self, fixture: dict) -> None:
        self.by_message = {step["message"]: step for step in fixture["steps"]}
        self.calls: list[dict] = []

    def create_structured_response(self, *, input: str, schema_name: str, **_kwargs) -> str:
        started = perf_counter()
        request = json.loads(input)
        message = request["message"]
        step = self.by_message.get(message)
        if step is None:
            raise ValueError("synthetic fixture has no adapter response for this message")
        if schema_name == "context_intake_case_route":
            output = step.get("route_response")
            if not isinstance(output, dict):
                raise ValueError("synthetic fixture has no route response for this message")
        elif schema_name == "context_intake_extraction":
            output = self._extractor_output(step, request)
        else:
            raise ValueError(f"unsupported fake schema: {schema_name}")
        raw = json.dumps(output, ensure_ascii=False, separators=(",", ":"))
        self.calls.append({
            "schema_name": schema_name,
            "local_fake_latency_ms": round((perf_counter() - started) * 1000, 3),
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
        })
        return raw

    @staticmethod
    def _extractor_output(step: dict, request: dict) -> dict:
        response = step.get("extractor_response")
        if not isinstance(response, dict):
            raise ValueError("synthetic fixture has no extractor response for this message")
        fields = request["category"]["fields"]
        attributes = {key: None for key in fields}
        evidence = {key: None for key in fields}
        for key, value in response.get("extracted_attributes", {}).items():
            if key not in fields:
                raise ValueError(f"fixture uses an unregistered field: {key}")
            attributes[key] = value
        for key, value in response.get("evidence", {}).items():
            if key not in fields:
                raise ValueError(f"fixture uses evidence for an unregistered field: {key}")
            evidence[key] = value
        return {
            "selected_fields": response["selected_fields"],
            "extracted_attributes": attributes,
            "evidence": evidence,
            "selection_reason": response["selection_reason"],
            "clarification_question": response["clarification_question"],
            "clarification_field_key": response["clarification_field_key"],
        }


class DeterministicIds:
    def __init__(self) -> None:
        self.next_id = 0

    def __call__(self) -> str:
        value = f"synthetic-id-{self.next_id:04d}"
        self.next_id += 1
        return value


def run(fixture_path: Path) -> dict:
    raw = fixture_path.read_bytes()
    fixture = json.loads(raw.decode("utf-8"))
    _validate_fixture(fixture)
    registry = load_category_registry()
    adapter = FakeResponsesAdapter(fixture)
    classifier_calls: list[str] = []
    id_factory = DeterministicIds()
    errors: list[dict] = []
    predictions: list[dict] = []
    seen_clarifications: set[tuple[str, str, str]] = set()
    repeated_clarification_count = 0
    restore_count = 0

    with TemporaryDirectory(prefix="context-intake-e2e-") as temp_dir:
        db_path = Path(temp_dir) / "session.sqlite3"
        for step_index, step in enumerate(fixture["steps"]):
            connection = sqlite3.connect(db_path)
            try:
                initialize_database(connection)
                repository = SQLiteContextIntakeRepository(connection)
                restored = repository.load_session(fixture["session_id"])
                if restored is not None:
                    restore_count += 1
                classifier = FakeClassifier(fixture, registry.version, classifier_calls)
                service = ContextIntakeService(
                    classifier=classifier,
                    extractor=OpenAIExtractor(adapter=adapter),
                    registry=registry,
                    repository=repository,
                    id_factory=id_factory,
                )
                orchestrator = ConversationOrchestrator(
                    service, OpenAICaseRouter(adapter=adapter),
                )
                classifier_calls_before = len(classifier_calls)
                repeated_before = repeated_clarification_count
                result = orchestrator.process_turn(
                    participant_id=fixture["participant_id"],
                    session_id=fixture["session_id"],
                    message=step["message"],
                )
                session = result.session
                event = session.turn_events[-1]
                classification_called = len(classifier_calls) > classifier_calls_before
                current_case_id = session.active_case_id
                active_attributes = _attributes(session, current_case_id)
                case_ids = list(session.cases)
                case_attributes = [
                    {key: value.value for key, value in session.cases[case_id].attributes.items()}
                    for case_id in case_ids
                ]
                pending_field = session.pending_question.field_key if session.pending_question else None
                if result.clarification and session.pending_question is not None:
                    pending = session.pending_question
                    clarification_key = (pending.case_id, pending.category_id, pending.field_key)
                    if clarification_key in seen_clarifications:
                        repeated_clarification_count += 1
                    seen_clarifications.add(clarification_key)
                extraction = result.intake_result.extraction if result.intake_result else None
                selected_fields = list(extraction.selected_fields) if extraction else []
                accepted_attributes = dict(extraction.extracted_attributes) if extraction else {}
                actual = {
                    "category_id": result.category_id,
                    "route_action": result.route_decision.action if result.route_decision else None,
                    "selected_fields": selected_fields,
                    "extracted_attributes": accepted_attributes,
                    "active_case_index": case_ids.index(current_case_id) if current_case_id else None,
                    "cases": case_attributes,
                    "pending_field": pending_field,
                    "repeated_clarification_count": repeated_clarification_count - repeated_before,
                }
                expected = step["expected"]
                for key, value in expected.items():
                    if actual.get(key) != value:
                        errors.append({"turn_id": step["turn_id"], "check": key,
                                       "expected": value, "actual": actual.get(key)})
                if classification_called != (step["classification"] is not None):
                    errors.append({
                        "turn_id": step["turn_id"], "check": "classification_call",
                        "expected": step["classification"] is not None,
                        "actual": classification_called,
                    })
                if step_index > 0 and restored is None:
                    errors.append({"turn_id": step["turn_id"], "check": "sqlite_session_restore",
                                   "expected": True, "actual": False})

                classification = event.classification
                predictions.append({
                    "turn_id": step["turn_id"],
                    "classification_called": classification_called,
                    "classification": ({
                        "category_id": classification.top1_category_id,
                        "top1_similarity": classification.top1_similarity,
                        "is_unknown": classification.is_unknown,
                    } if classification else None),
                    **actual,
                    "active_case_attributes": active_attributes,
                    "sqlite_session_restored": restored is not None,
                })
            finally:
                connection.close()
        final_connection = sqlite3.connect(db_path)
        try:
            final_repository = SQLiteContextIntakeRepository(final_connection)
            final_session = final_repository.load_session(fixture["session_id"])
        finally:
            final_connection.close()
    if final_session is None:
        raise RuntimeError("SQLite session disappeared before final report")
    coverage = []
    for case_id, case in final_session.cases.items():
        categories = sorted({
            event.category_id for event in final_session.turn_events
            if event.case_id == case_id and event.category_id is not None
        })
        for category_id in categories:
            item = calculate_case_coverage(registry, case, final_session.turn_events, category_id)
            coverage.append({
                "case_index": list(final_session.cases).index(case_id),
                "category_id": item.category_id,
                "catalog_count": item.catalog_count,
                "selected_count": item.selected_count,
                "known_count": item.known_count,
                "selected_known_count": item.selected_known_count,
                "coverage_rate": item.coverage_rate,
            })

    schema_counts = Counter(call["schema_name"] for call in adapter.calls)
    latencies = [call["local_fake_latency_ms"] for call in adapter.calls]
    return {
        "schema_version": "1.0",
        "metadata": {
            "evaluation_type": "synthetic_offline_application_sqlite_e2e",
            "scenario_id": fixture["scenario_id"],
            "fixture_sha256": sha256(raw).hexdigest(),
            "catalog_version": registry.version,
            "classifier_id": "synthetic-fake-classifier",
            "router_id": "OpenAICaseRouter with FakeResponsesAdapter",
            "extractor_id": "OpenAIExtractor with FakeResponsesAdapter",
            "storage": "temporary SQLite file, reopened before each turn",
            "real_model_or_clinical_performance": False,
        },
        "metrics": {
            "turn_count": len(predictions),
            "passed_expected_checks": not errors,
            "classifier_calls": len(classifier_calls),
            "fake_provider_adapter_calls": len(adapter.calls),
            "fake_adapter_calls_by_schema": dict(sorted(schema_counts.items())),
            "external_api_calls": 0,
            "session_restores_from_sqlite": restore_count,
            "repeated_clarification_count": repeated_clarification_count,
            "coverage": coverage,
            "token_usage": {
                "input_tokens": None,
                "output_tokens": None,
                "total_tokens": None,
                "status": "unavailable; fake adapter does not return provider usage",
            },
            "latency": {
                "local_fake_adapter_ms": latencies,
                "local_fake_adapter_total_ms": round(sum(latencies), 3),
                "network_api_latency_ms": None,
                "note": "Measured fake adapter execution only; not model or network latency.",
            },
            "estimated_model_cost_usd": None,
            "actual_external_api_cost_usd": 0.0,
            "cost_note": "No external API calls were made; model cost is not estimated without real token usage.",
        },
        "predictions": predictions,
        "errors": errors,
        "session": {
            "restored_at_end": True,
            "case_count": len(final_session.cases),
            "turn_event_count": len(final_session.turn_events),
            "active_case_index": (
                list(final_session.cases).index(final_session.active_case_id)
                if final_session.active_case_id is not None else None
            ),
        },
        "limitations": [
            "All messages, classifications, route decisions, and extraction outputs are synthetic fixtures.",
            "Passing checks validate application wiring and SQLite behavior only; they do not measure model or clinical performance.",
        ],
    }


def _attributes(session, case_id: str | None) -> dict:
    if case_id is None:
        return {}
    return {key: value.value for key, value in session.cases[case_id].attributes.items()}


def _validate_fixture(fixture: object) -> None:
    if not isinstance(fixture, dict) or set(fixture) != {
        "schema_version", "scenario_id", "participant_id", "session_id", "steps",
    }:
        raise ValueError("fixture must have schema_version, scenario_id, participant_id, session_id, and steps")
    if fixture["schema_version"] != "1.0" or not all(
        isinstance(fixture[key], str) and fixture[key].strip()
        for key in ("scenario_id", "participant_id", "session_id")
    ):
        raise ValueError("fixture version and identifiers are invalid")
    if not isinstance(fixture["steps"], list) or len(fixture["steps"]) < 3:
        raise ValueError("fixture needs at least three steps")
    seen: set[str] = set()
    for index, step in enumerate(fixture["steps"]):
        if not isinstance(step, dict) or set(step) != {
            "turn_id", "message", "classification", "route_response", "extractor_response", "expected",
        }:
            raise ValueError(f"step {index} has invalid keys")
        if not all(isinstance(step[key], str) and step[key].strip() for key in ("turn_id", "message")):
            raise ValueError(f"step {index} identifiers/message must be non-empty strings")
        if step["message"] in seen:
            raise ValueError(f"step {index} duplicates a message")
        seen.add(step["message"])
        if step["classification"] is not None and not isinstance(step["classification"], dict):
            raise ValueError(f"step {index} classification must be an object or null")
        if not isinstance(step["route_response"], dict) or not isinstance(step["extractor_response"], dict):
            raise ValueError(f"step {index} needs route and extractor responses")
        if not isinstance(step["expected"], dict):
            raise ValueError(f"step {index} expected must be an object")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    report = run(args.fixture)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(args.output.name + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.output)
    print(json.dumps({
        "report": str(args.output),
        "passed_expected_checks": report["metrics"]["passed_expected_checks"],
        "errors": len(report["errors"]),
        "fake_provider_adapter_calls": report["metrics"]["fake_provider_adapter_calls"],
        "external_api_calls": report["metrics"]["external_api_calls"],
    }, ensure_ascii=False, indent=2))
    return 0 if report["metrics"]["passed_expected_checks"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
