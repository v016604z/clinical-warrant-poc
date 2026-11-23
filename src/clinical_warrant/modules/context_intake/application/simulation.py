"""Deterministic, explicitly synthetic multi-turn intake evaluation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from clinical_warrant.modules.context_intake.application.extraction import ExtractionRequest
from clinical_warrant.modules.context_intake.application.intake import ContextIntakeService
from clinical_warrant.modules.context_intake.application.coverage import calculate_case_coverage
from clinical_warrant.modules.context_intake.domain.classification import IntakeClassificationResult
from clinical_warrant.modules.context_intake.domain.state import SessionState


class FixtureError(ValueError):
    """A synthetic conversation fixture is malformed."""


class FixtureClassifier:
    def __init__(self, steps: list[dict[str, Any]], registry_version: str) -> None:
        self._by_message = {step["message"]: step for step in steps}
        self.registry_version = registry_version

    def classify(self, query: str) -> IntakeClassificationResult:
        step = self._by_message.get(query)
        if step is None:
            raise FixtureError(f"no fixture classifier response for message: {query}")
        category = step.get("category_id") or "hiv_basics"
        return IntakeClassificationResult(
            category, 0.9, "window_period" if category != "window_period" else "hiv_basics",
            0.5, step.get("category_id") is None, "fixture-classifier", "fixture-v1", self.registry_version,
        )


class FixtureExtractor:
    def __init__(self, steps: list[dict[str, Any]]) -> None:
        self._by_message = {step["message"]: step for step in steps}

    def extract(self, request: ExtractionRequest) -> str:
        step = self._by_message.get(request.message)
        if step is None:
            raise FixtureError(f"no fixture extraction response for message: {request.message}")
        response = step.get("extractor_response")
        if not isinstance(response, dict):
            raise FixtureError("field-bearing steps need an extractor_response object")
        return json.dumps(response, ensure_ascii=False)


def load_conversation_fixture(path: str | Path) -> tuple[bytes, dict[str, Any]]:
    raw = Path(path).read_bytes()
    try:
        fixture = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise FixtureError(f"invalid UTF-8 JSON fixture: {error}") from error
    if not isinstance(fixture, dict) or set(fixture) != {"schema_version", "scenario_id", "steps"}:
        raise FixtureError("fixture must contain schema_version, scenario_id, and steps")
    if fixture["schema_version"] != "1.0" or not isinstance(fixture["scenario_id"], str):
        raise FixtureError("unsupported fixture version or invalid scenario_id")
    steps = fixture["steps"]
    if not isinstance(steps, list) or not steps:
        raise FixtureError("steps must be a non-empty array")
    seen = set()
    required = {"message", "category_id", "extractor_response"}
    for index, step in enumerate(steps):
        if not isinstance(step, dict) or not required <= set(step):
            raise FixtureError(f"step {index} needs message, category_id, and extractor_response")
        if not isinstance(step["message"], str) or not step["message"].strip() or step["message"] in seen:
            raise FixtureError(f"step {index} has an empty or duplicate message")
        seen.add(step["message"])
        if step["category_id"] is not None and not isinstance(step["category_id"], str):
            raise FixtureError(f"step {index} category_id must be a string or null")
        for key in ("new_case", "new_question", "clear_case", "urgent_handoff"):
            if key in step and type(step[key]) is not bool:
                raise FixtureError(f"step {index} {key} must be a boolean")
        for key in ("correct_fields", "expected_absent_attributes"):
            value = step.get(key, [])
            if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
                raise FixtureError(f"step {index} {key} must be an array of strings")
        for key in ("expected_attributes", "expected_extracted_attributes"):
            if key in step and not isinstance(step[key], dict):
                raise FixtureError(f"step {index} {key} must be an object")
        if step["extractor_response"] is not None and not isinstance(step["extractor_response"], dict):
            raise FixtureError(f"step {index} extractor_response must be an object or null")
    return raw, fixture


def replay_conversation(fixture: dict[str, Any], registry, *, on_turn=None) -> dict[str, Any]:
    steps = fixture["steps"]
    service = ContextIntakeService(
        classifier=FixtureClassifier(steps, registry.version),
        extractor=FixtureExtractor(steps), registry=registry,
        id_factory=iter((f"fixture-session-{n}" for n in range(100))).__next__,
    )
    session: SessionState | None = None
    results = []
    extraction_matches = extraction_total = 0
    state_matches = state_total = 0
    repeated_questions = 0
    asked_before: set[tuple[str, str, str]] = set()
    corrections = []
    errors = []
    for step in steps:
        result = service.process_turn(
            participant_id="synthetic-participant", message=step["message"],
            session_id=session.session_id if session else "fixture-session",
            new_case=step.get("new_case", False), new_question=step.get("new_question", False),
            clear_case=step.get("clear_case", False),
            correct_fields=tuple(step.get("correct_fields", ())),
            urgent_handoff=step.get("urgent_handoff", False),
        )
        session = result.session
        expected = step.get("expected_attributes", {})
        actual = {key: value.value for key, value in session.cases.get(session.active_case_id, {}).attributes.items()} if session.active_case_id else {}
        for key, value in expected.items():
            state_total += 1
            correct = _strict_equal(actual.get(key, _MISSING), value)
            state_matches += correct
            if not correct:
                errors.append({"turn_id": result.turn_id, "message": step["message"],
                               "error_type": "state_field_mismatch", "field_key": key,
                               "expected": value, "actual": actual.get(key)})
        for key in step.get("expected_absent_attributes", ()):
            state_total += 1
            correct = key not in actual
            state_matches += correct
            if not correct:
                errors.append({"turn_id": result.turn_id, "message": step["message"],
                               "error_type": "unexpected_state_field", "field_key": key,
                               "actual": actual[key]})
        if "expected_extracted_attributes" in step:
            extraction_total += 1
            extracted = dict(result.extraction.extracted_attributes) if result.extraction else {}
            correct = _strict_mapping_equal(
                extracted, step["expected_extracted_attributes"]
            )
            extraction_matches += correct
            if not correct:
                errors.append({"turn_id": result.turn_id, "message": step["message"],
                               "error_type": "extraction_mismatch",
                               "expected": step["expected_extracted_attributes"],
                               "actual": extracted})
        pending = session.pending_question or session.pending_conflict
        if result.clarification and pending is not None:
            asked_key = (pending.case_id, pending.category_id, pending.field_key)
            repeated_questions += asked_key in asked_before
            asked_before.add(asked_key)
        for key in step.get("correct_fields", ()):
            history = session.cases[session.active_case_id].attributes[key].history
            corrections.append({"field_key": key, "old_value": history[-1].old_value, "new_value": history[-1].new_value})
        results.append({
            "message": step["message"], "turn_id": result.turn_id,
            "category_id": result.category_id, "clarification": result.clarification,
            "attributes": actual, "handoff_required": result.handoff_required,
        })
        if on_turn is not None:
            on_turn(results[-1])
    coverage = []
    if session is not None:
        if session.active_case_id is None:
            for category_id in sorted({
                event.category_id for event in session.turn_events
                if event.case_id is None and event.category_id
            }):
                coverage.append(calculate_case_coverage(
                    registry, None, session.turn_events, category_id,
                ).__dict__)
        for case_id, case in session.cases.items():
            case_categories = {
                event.category_id for event in session.turn_events
                if event.case_id == case_id and event.category_id
            }
            for category_id in sorted(case_categories):
                coverage.append(calculate_case_coverage(
                    registry, case, session.turn_events, category_id,
                ).__dict__)
    return {
        "scenario_id": fixture["scenario_id"], "turns": results,
        "session": session,
        "extraction_exact_match": {"correct": extraction_matches, "total": extraction_total,
        "value": extraction_matches / extraction_total if extraction_total else None},
        "state_field_accuracy": {"correct": state_matches, "total": state_total,
        "value": state_matches / state_total if state_total else None},
        "repeated_question_count": repeated_questions, "corrections": corrections,
        "coverage": coverage, "errors": errors,
    }


def evaluate_fixture(raw: bytes, fixture: dict[str, Any], registry, *, on_turn=None) -> dict[str, Any]:
    replay = replay_conversation(fixture, registry, on_turn=on_turn)
    session = replay.pop("session")
    return {
        "schema_version": "1.0",
        "metadata": {
            "evaluation_type": "synthetic_offline_context_intake_simulation",
            "scenario_id": fixture["scenario_id"],
            "fixture_sha256": hashlib.sha256(raw).hexdigest(),
            "catalog_version": registry.version,
            "classifier_model_id": "fixture-classifier",
            "classifier_model_revision": "fixture-v1",
            "extractor_id": "fixture-extractor",
        },
        "metrics": {
            "turn_count": len(replay["turns"]),
            "extraction_exact_match": replay["extraction_exact_match"],
            "state_field_accuracy": replay["state_field_accuracy"],
            "repeated_question_count": replay["repeated_question_count"],
            "correction_count": len(replay["corrections"]),
            "corrections": replay["corrections"],
            "coverage": replay["coverage"],
        },
        "predictions": replay["turns"],
        "errors": replay["errors"],
        "session": {
            "session_id": session.session_id,
            "case_ids": list(session.cases),
            "turn_event_count": len(session.turn_events),
        },
    }


_MISSING = object()


def _strict_equal(left: Any, right: Any) -> bool:
    return type(left) is type(right) and left == right


def _strict_mapping_equal(left: dict[str, Any], right: Any) -> bool:
    return (isinstance(right, dict) and left.keys() == right.keys()
            and all(_strict_equal(left[key], right[key]) for key in left))
