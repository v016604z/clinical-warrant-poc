"""Scenario evaluation for the research-only Clinical Warrant PoC."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
from typing import Any, Protocol
from uuid import uuid4

from clinical_warrant import __version__
from clinical_warrant.contracts import (
    Decision,
    DecisionInput,
    DecisionResult,
    QuestionType,
    ReasonCode,
)


class EvaluationError(ValueError):
    """Raised for invalid evaluation input or report output failures."""


class DecisionEngine(Protocol):
    def decide(self, request: DecisionInput) -> DecisionResult:
        """Return one decision for an input scenario."""


@dataclass(frozen=True)
class ExpectedResult:
    category: QuestionType
    decision: Decision
    missing_fields: tuple[str, ...]
    reason_codes: tuple[ReasonCode, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category.value,
            "decision": self.decision.value,
            "missing_fields": list(self.missing_fields),
            "reason_codes": [reason.value for reason in self.reason_codes],
        }


@dataclass(frozen=True)
class EvaluationCase:
    case_id: str
    request: DecisionInput
    expected: ExpectedResult


def load_evaluation_jsonl(text: str) -> tuple[EvaluationCase, ...]:
    """Parse and validate the complete JSONL dataset before evaluation starts."""
    if not isinstance(text, str) or not text.strip():
        raise EvaluationError("evaluation dataset must not be empty")

    cases: list[EvaluationCase] = []
    seen_ids: set[str] = set()
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            raise EvaluationError(f"line {line_number}: blank lines are not allowed")
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as error:
            raise EvaluationError(f"line {line_number}: invalid JSON: {error.msg}") from error
        if not isinstance(raw, dict):
            raise EvaluationError(f"line {line_number}: record must be a JSON object")
        if set(raw) != {"id", "input", "expected"}:
            raise EvaluationError(
                f"line {line_number}: record must contain exactly id, input, expected"
            )
        case_id = raw["id"]
        if not isinstance(case_id, str) or not case_id.strip():
            raise EvaluationError(f"line {line_number}: id must be a non-empty string")
        if case_id in seen_ids:
            raise EvaluationError(f"line {line_number}: duplicate id {case_id!r}")
        seen_ids.add(case_id)
        try:
            request = DecisionInput.from_dict(raw["input"])
            expected = _parse_expected(raw["expected"])
        except (TypeError, ValueError) as error:
            raise EvaluationError(f"line {line_number}: {error}") from error
        cases.append(EvaluationCase(case_id, request, expected))

    if not cases:
        raise EvaluationError("evaluation dataset must contain at least one record")
    return tuple(cases)


def _parse_expected(value: Any) -> ExpectedResult:
    if not isinstance(value, dict) or set(value) != {
        "category", "decision", "missing_fields", "reason_codes"
    }:
        raise ValueError(
            "expected must contain exactly category, decision, missing_fields, reason_codes"
        )
    try:
        category = QuestionType(value["category"])
    except (ValueError, TypeError) as error:
        raise ValueError("expected.category is not a known question type") from error
    try:
        decision = Decision(value["decision"])
    except (ValueError, TypeError) as error:
        raise ValueError("expected.decision is not a known decision") from error
    fields = _string_array(value["missing_fields"], "expected.missing_fields")
    raw_reasons = _string_array(value["reason_codes"], "expected.reason_codes")
    try:
        reasons = tuple(ReasonCode(reason) for reason in raw_reasons)
    except ValueError as error:
        raise ValueError("expected.reason_codes contains an unknown reason code") from error
    return ExpectedResult(category, decision, fields, reasons)


def _string_array(value: Any, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ValueError(f"{name} must be an array of non-empty strings")
    if len(value) != len(set(value)):
        raise ValueError(f"{name} must not contain duplicates")
    return tuple(value)


def evaluate_cases(
    cases: tuple[EvaluationCase, ...],
    engine: DecisionEngine,
    output_dir: str | Path,
    *,
    threshold: float,
    dataset_sha256: str,
) -> dict[str, Any]:
    """Evaluate with one engine and atomically publish a unique report run."""
    classifier = getattr(engine, "classifier", None)
    actual_threshold = getattr(classifier, "threshold", None)
    if actual_threshold is not None and actual_threshold != threshold:
        raise EvaluationError(
            f"requested threshold {threshold} does not match classifier threshold {actual_threshold}"
        )
    encoder = getattr(classifier, "encoder", None)
    predictions: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    confusion = {
        expected.value: {actual.value: 0 for actual in QuestionType}
        for expected in QuestionType
    }

    for case in cases:
        try:
            result = engine.decide(case.request)
        except Exception as error:
            raise EvaluationError(f"case {case.case_id!r} failed: {error}") from error
        if not isinstance(result, DecisionResult):
            raise EvaluationError(
                f"case {case.case_id!r}: engine returned an invalid DecisionResult"
            )
        actual = {
            "category": result.classification.category.value,
            "similarity": result.classification.similarity,
            "decision": result.decision.value,
            "rule_id": result.rule_id,
            "missing_fields": list(result.missing_fields),
            "reason_codes": [reason.value for reason in result.reason_codes],
            "checks": [
                {
                    "kind": check.kind.value,
                    "status": check.status.value,
                    "reason_code": check.reason_code.value if check.reason_code else None,
                }
                for check in result.checks
            ],
        }
        expected = case.expected
        matches = {
            "category": actual["category"] == expected.category.value,
            "decision": actual["decision"] == expected.decision.value,
            "missing_fields": set(actual["missing_fields"])
            == set(expected.missing_fields),
            "reason_codes": set(actual["reason_codes"])
            == {reason.value for reason in expected.reason_codes},
        }
        confusion[expected.category.value][actual["category"]] += 1
        prediction = {
            "id": case.case_id,
            "input": case.request.to_dict(),
            "expected": expected.to_dict(),
            "actual": actual,
            "matches": matches,
        }
        predictions.append(prediction)
        mismatches = [name for name, matched in matches.items() if not matched]
        if mismatches:
            errors.append({"id": case.case_id, "mismatches": mismatches, **prediction})

    total = len(cases)
    category_correct = sum(item["matches"]["category"] for item in predictions)
    decision_correct = sum(item["matches"]["decision"] for item in predictions)
    fields_correct = sum(item["matches"]["missing_fields"] for item in predictions)
    reasons_correct = sum(item["matches"]["reason_codes"] for item in predictions)
    unknown_count = sum(
        item["actual"]["category"] == QuestionType.UNKNOWN.value for item in predictions
    )
    now = datetime.now(timezone.utc)
    run_id = f"{now.strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:10]}"
    active_prototypes = getattr(classifier, "prototypes", None)
    prototype_content = [
        {
            "category": item.category.value,
            "label_zh": item.label_zh,
            "prototypes": list(item.prototypes),
        }
        for item in active_prototypes or ()
    ]
    prototype_sha256 = (
        _content_hash(prototype_content) if active_prototypes is not None else None
    )
    active_rules = getattr(engine, "rules_by_type", None)
    rules_for_hash = tuple(active_rules.values()) if isinstance(active_rules, dict) else ()
    rule_content = [
        {
            "rule_id": item.rule_id,
            "question_type": item.question_type.value,
            "required_case_fields": list(item.required_case_fields),
            "applicability_field": item.applicability_field,
            "applicability_value": item.applicability_value,
        }
        for item in sorted(rules_for_hash, key=lambda rule: rule.rule_id)
    ]
    rule_sha256 = _content_hash(rule_content) if active_rules is not None else None
    metadata = {
        "run_id": run_id,
        "created_at_utc": now.isoformat(),
        "threshold": actual_threshold if actual_threshold is not None else threshold,
        "threshold_source": "classifier" if actual_threshold is not None else "requested_argument",
        "model_id": getattr(classifier, "model_id", getattr(encoder, "model_id", None)),
        "model_revision": getattr(
            classifier, "revision", getattr(encoder, "revision", None)
        ),
        "prototype_sha256": prototype_sha256,
        "prototype_identity_source": (
            "classifier.prototypes" if active_prototypes is not None else "unavailable_in_injected_engine"
        ),
        "rule_sha256": rule_sha256,
        "rule_identity_source": (
            "engine.rules_by_type" if active_rules is not None else "unavailable_in_injected_engine"
        ),
        "dataset_sha256": dataset_sha256,
        "unique_query_count": len({case.request.query for case in cases}),
        "encoder_type": (
            f"{type(encoder).__module__}.{type(encoder).__qualname__}"
            if encoder is not None
            else None
        ),
        "classifier_type": (
            f"{type(classifier).__module__}.{type(classifier).__qualname__}"
            if classifier is not None
            else None
        ),
        "model_identity_source": (
            "encoder_metadata"
            if getattr(encoder, "model_id", None) and getattr(encoder, "revision", None)
            else "injected_or_unavailable"
        ),
        "package_version": __version__,
        "core_dependencies": {
            "sentence-transformers": _installed_version("sentence-transformers"),
            "transformers": _installed_version("transformers"),
            "torch": _installed_version("torch"),
        },
    }
    summary = {
        "schema_version": "1.0",
        "metadata": metadata,
        "total_cases": total,
        "metrics": {
            "classification_accuracy": _rate(category_correct, total),
            "unknown_rate": _rate(unknown_count, total),
            "decision_accuracy": _rate(decision_correct, total),
            "missing_fields_accuracy": _rate(fields_correct, total),
            "reason_codes_accuracy": _rate(reasons_correct, total),
        },
        "counts": {
            "classification_correct": category_correct,
            "unknown_predictions": unknown_count,
            "decision_correct": decision_correct,
            "missing_fields_match": fields_correct,
            "reason_codes_match": reasons_correct,
            "reason_codes_mismatch": total - reasons_correct,
            "cases_with_any_mismatch": len(errors),
        },
        "confusion_counts": confusion,
        "metric_definitions": {
            "classification_accuracy": "correct categories / total cases",
            "unknown_rate": "predicted unknown categories / total cases",
            "decision_accuracy": "matching decisions / total cases",
            "missing_fields_accuracy": "exact set matches / total cases",
            "reason_codes_accuracy": "exact set matches / total cases",
            "missing_fields_and_reason_codes": "compared as unordered sets; report arrays retain their original order",
            "similarity": "cosine similarity, not a probability; null means unavailable",
        },
    }

    destination = Path(output_dir).expanduser()
    temporary: Path | None = None
    try:
        destination.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=".evaluation-", dir=destination))
        (temporary / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        (temporary / "predictions.jsonl").write_text(
            _jsonl(predictions), encoding="utf-8"
        )
        (temporary / "errors.jsonl").write_text(_jsonl(errors), encoding="utf-8")
        final = destination / f"run-{run_id}"
        temporary.replace(final)
        temporary = None
    except (OSError, TypeError, ValueError) as error:
        if temporary is not None:
            _remove_own_temporary_directory(temporary, destination)
        raise EvaluationError(f"could not publish evaluation reports: {error}") from error

    return {"run_id": run_id, "run_dir": str(final), "summary": summary}


def _rate(numerator: int, denominator: int) -> dict[str, Any]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": numerator / denominator if denominator else None,
    }


def _content_hash(content: Any) -> str:
    canonical = json.dumps(
        content, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _remove_own_temporary_directory(temporary: Path, destination: Path) -> None:
    try:
        resolved_temporary = temporary.resolve()
        resolved_destination = destination.resolve()
    except OSError:
        return
    if (
        resolved_temporary.parent == resolved_destination
        and resolved_temporary.name.startswith(".evaluation-")
    ):
        shutil.rmtree(resolved_temporary, ignore_errors=True)


def _jsonl(records: list[dict[str, Any]]) -> str:
    return "".join(
        json.dumps(record, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        + "\n"
        for record in records
    )


def _installed_version(distribution: str) -> str | None:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version(distribution)
    except PackageNotFoundError:
        return None
