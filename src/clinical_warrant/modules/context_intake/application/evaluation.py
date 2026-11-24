"""Offline calibration and evaluation for the isolated 14-category classifier."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Protocol, Sequence


UNKNOWN_CATEGORY_ID = "unknown"


class ClassificationEvaluationError(ValueError):
    """Raised for invalid classification datasets or evaluation inputs."""


class ClassificationResult(Protocol):
    top1_category_id: str
    top1_similarity: float
    top2_category_id: str
    top2_similarity: float
    is_unknown: bool
    model_id: str
    model_revision: str
    catalog_version: str


@dataclass(frozen=True)
class ClassificationCase:
    case_id: str
    query: str
    expected_category_id: str
    source: str
    source_faq_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.case_id,
            "query": self.query,
            "expected_category_id": self.expected_category_id,
            "source": self.source,
        }
        if self.source_faq_id is not None:
            result["source_faq_id"] = self.source_faq_id
        return result


def load_classification_jsonl(text: str) -> tuple[ClassificationCase, ...]:
    if not isinstance(text, str) or not text.strip():
        raise ClassificationEvaluationError("classification dataset must not be empty")
    cases: list[ClassificationCase] = []
    seen: set[str] = set()
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            raise ClassificationEvaluationError(f"line {line_number}: blank lines are not allowed")
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as error:
            raise ClassificationEvaluationError(f"line {line_number}: invalid JSON") from error
        if not isinstance(raw, dict) or set(raw) not in (
            {"id", "query", "expected_category_id", "source"},
            {"id", "query", "expected_category_id", "source", "source_faq_id"},
        ):
            raise ClassificationEvaluationError(f"line {line_number}: invalid record fields")
        case_id, query = raw["id"], raw["query"]
        expected, source = raw["expected_category_id"], raw["source"]
        if not all(isinstance(value, str) and value.strip() for value in (case_id, query, expected, source)):
            raise ClassificationEvaluationError(f"line {line_number}: id, query, label, and source must be non-empty strings")
        if case_id in seen:
            raise ClassificationEvaluationError(f"line {line_number}: duplicate id {case_id!r}")
        seen.add(case_id)
        source_faq_id = raw.get("source_faq_id")
        if source == "cdc_faq":
            if not isinstance(source_faq_id, str) or not source_faq_id.strip():
                raise ClassificationEvaluationError(f"line {line_number}: CDC FAQ record needs source_faq_id")
            if source_faq_id != case_id:
                raise ClassificationEvaluationError(f"line {line_number}: CDC id must match source_faq_id")
        elif source_faq_id is not None:
            raise ClassificationEvaluationError(f"line {line_number}: only CDC records may have source_faq_id")
        if expected == UNKNOWN_CATEGORY_ID and source != "synthetic_ood":
            raise ClassificationEvaluationError(f"line {line_number}: unknown labels must be synthetic_ood records")
        if expected != UNKNOWN_CATEGORY_ID and source != "cdc_faq":
            raise ClassificationEvaluationError(f"line {line_number}: known labels must be CDC FAQ records")
        cases.append(ClassificationCase(case_id, query, expected, source, source_faq_id))
    if not cases:
        raise ClassificationEvaluationError("classification dataset must contain at least one record")
    return tuple(cases)


def validate_disjoint_splits(
    development: Sequence[ClassificationCase], test: Sequence[ClassificationCase]
) -> None:
    development_ids = {case.case_id for case in development}
    test_ids = {case.case_id for case in test}
    overlap = development_ids & test_ids
    if overlap:
        raise ClassificationEvaluationError(f"development/test IDs overlap: {sorted(overlap)!r}")
    development_faq_ids = {case.source_faq_id for case in development if case.source_faq_id}
    test_faq_ids = {case.source_faq_id for case in test if case.source_faq_id}
    faq_overlap = development_faq_ids & test_faq_ids
    if faq_overlap:
        raise ClassificationEvaluationError(f"development/test FAQ IDs overlap: {sorted(faq_overlap)!r}")
    development_queries = {_normalize_query(case.query) for case in development}
    test_queries = {_normalize_query(case.query) for case in test}
    query_overlap = development_queries & test_queries
    if query_overlap:
        raise ClassificationEvaluationError("development/test query text overlaps")


def calibrate_threshold(
    cases: Sequence[ClassificationCase],
    results: Sequence[ClassificationResult],
    category_ids: Sequence[str],
) -> dict[str, Any]:
    """Maximize 15-label dev Macro-F1; ties choose the lower, more permissive threshold."""
    _validate_inputs(cases, results, category_ids)
    labels = (*category_ids, UNKNOWN_CATEGORY_ID)
    candidates = sorted({-1.0, 1.0, *(float(result.top1_similarity) for result in results)})
    scored = []
    for threshold in candidates:
        predictions = [
            UNKNOWN_CATEGORY_ID if result.top1_similarity < threshold else result.top1_category_id
            for result in results
        ]
        metrics = _metrics(cases, predictions, labels, category_ids)
        scored.append((metrics["macro_f1_all_15"], threshold, metrics))
    best_score = max(item[0] for item in scored)
    best = min((item for item in scored if item[0] == best_score), key=lambda item: item[1])
    return {
        "threshold": best[1],
        "objective": "maximize development Macro-F1 across the 14 known categories plus unknown",
        "tie_break": "choose the lower threshold",
        "development_macro_f1_all": best[0],
        "development_metrics": best[2],
        "candidate_count": len(candidates),
    }


def evaluate_classification(
    cases: Sequence[ClassificationCase],
    results: Sequence[ClassificationResult],
    category_ids: Sequence[str],
    *,
    threshold: float,
    development_sha256: str,
    test_sha256: str,
    prototype_sha256: str | None,
) -> dict[str, Any]:
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not -1 <= threshold <= 1:
        raise ClassificationEvaluationError("threshold must be between -1 and 1")
    _validate_inputs(cases, results, category_ids)
    labels = (*category_ids, UNKNOWN_CATEGORY_ID)
    predictions = [
        UNKNOWN_CATEGORY_ID if result.top1_similarity < threshold else result.top1_category_id
        for result in results
    ]
    metrics = _metrics(cases, predictions, labels, category_ids)
    confusion = {expected: {actual: 0 for actual in labels} for expected in labels}
    rows = []
    errors = []
    for case, result, predicted in zip(cases, results, predictions):
        if result.is_unknown != (predicted == UNKNOWN_CATEGORY_ID):
            raise ClassificationEvaluationError("classifier unknown flag does not match the calibrated threshold")
        confusion[case.expected_category_id][predicted] += 1
        row = {
            **case.to_dict(),
            "actual": {
                "top1_category_id": result.top1_category_id,
                "top1_similarity": result.top1_similarity,
                "top2_category_id": result.top2_category_id,
                "top2_similarity": result.top2_similarity,
                "is_unknown": result.top1_similarity < threshold,
                "predicted_category_id": predicted,
            },
            "correct": predicted == case.expected_category_id,
        }
        rows.append(row)
        if not row["correct"]:
            errors.append(row)
    first = results[0]
    metadata = {
        "model_id": first.model_id or None,
        "model_revision": first.model_revision or None,
        "catalog_version": first.catalog_version or None,
        "prototype_sha256": prototype_sha256,
        "prototype_identity_available": bool(prototype_sha256),
        "development_dataset_sha256": development_sha256,
        "test_dataset_sha256": test_sha256,
        "threshold": threshold,
    }
    return {
        "schema_version": "1.0",
        "metadata": metadata,
        "total_cases": len(cases),
        "metrics": metrics,
        "metric_definitions": {
            "accuracy": "correct predictions divided by all test cases, including OOD unknown cases",
            "macro_f1_known_14": "unweighted mean F1 over all 14 registry categories; unsupported categories contribute zero",
            "macro_f1_all_15": "unweighted mean F1 over the 14 registry categories and unknown; unsupported labels contribute zero",
            "unknown_rate": "predicted unknown cases divided by all test cases",
            "ood_false_acceptance_rate": "expected unknown cases predicted as a known category divided by all expected unknown cases",
            "similarity": "cosine similarity, not a probability; equality to threshold is accepted",
        },
        "confusion_counts": confusion,
        "predictions": rows,
        "errors": errors,
    }


def _validate_inputs(
    cases: Sequence[ClassificationCase], results: Sequence[ClassificationResult], category_ids: Sequence[str]
) -> None:
    if not cases or len(cases) != len(results):
        raise ClassificationEvaluationError("cases and results must have the same non-zero length")
    if len(category_ids) != 14 or len(set(category_ids)) != 14 or UNKNOWN_CATEGORY_ID in category_ids:
        raise ClassificationEvaluationError("category_ids must contain exactly 14 unique known IDs")
    valid = set(category_ids) | {UNKNOWN_CATEGORY_ID}
    identity = None
    for case, result in zip(cases, results):
        if case.expected_category_id not in valid:
            raise ClassificationEvaluationError(f"unknown expected category {case.expected_category_id!r}")
        if result.top1_category_id not in category_ids or result.top2_category_id not in category_ids:
            raise ClassificationEvaluationError("classifier returned a category outside the 14-category registry")
        if not -1 <= result.top1_similarity <= 1 or not -1 <= result.top2_similarity <= 1:
            raise ClassificationEvaluationError("classifier similarities must be between -1 and 1")
        current_identity = (result.model_id, result.model_revision, result.catalog_version)
        if identity is None:
            identity = current_identity
        elif current_identity != identity:
            raise ClassificationEvaluationError("classifier model or catalog identity changed within the evaluation")


def _metrics(
    cases: Sequence[ClassificationCase], predictions: Sequence[str], labels: Sequence[str], category_ids: Sequence[str]
) -> dict[str, Any]:
    supports = {label: 0 for label in labels}
    true_positive = {label: 0 for label in labels}
    predicted_count = {label: 0 for label in labels}
    for case, predicted in zip(cases, predictions):
        supports[case.expected_category_id] += 1
        predicted_count[predicted] += 1
        if case.expected_category_id == predicted:
            true_positive[predicted] += 1
    per_class = {}
    f1s = {}
    for label in labels:
        precision = true_positive[label] / predicted_count[label] if predicted_count[label] else 0.0
        recall = true_positive[label] / supports[label] if supports[label] else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class[label] = {"precision": precision, "recall": recall, "f1": f1, "support": supports[label]}
        f1s[label] = f1
    known_macro = sum(f1s[item] for item in category_ids) / len(category_ids)
    all_macro = sum(f1s.values()) / len(labels)
    unknown_support = supports[UNKNOWN_CATEGORY_ID]
    unknown_false_accepts = sum(
        case.expected_category_id == UNKNOWN_CATEGORY_ID and predicted != UNKNOWN_CATEGORY_ID
        for case, predicted in zip(cases, predictions)
    )
    unknown_predictions = predicted_count[UNKNOWN_CATEGORY_ID]
    correct = sum(case.expected_category_id == predicted for case, predicted in zip(cases, predictions))
    return {
        "accuracy": {"numerator": correct, "denominator": len(cases), "value": correct / len(cases)},
        "macro_f1_known_14": known_macro,
        "macro_f1_all_15": all_macro,
        "per_class": per_class,
        "unknown_rate": {"numerator": unknown_predictions, "denominator": len(cases), "value": unknown_predictions / len(cases)},
        "ood_false_acceptance_rate": {
            "numerator": unknown_false_accepts,
            "denominator": unknown_support,
            "value": unknown_false_accepts / unknown_support if unknown_support else None,
        },
    }


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _normalize_query(query: str) -> str:
    return " ".join(query.split()).casefold()
