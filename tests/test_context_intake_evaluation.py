import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from clinical_warrant.modules.context_intake.application.evaluation import (
    ClassificationEvaluationError,
    ClassificationCase,
    calibrate_threshold,
    evaluate_classification,
    load_classification_jsonl,
    validate_disjoint_splits,
)
from clinical_warrant.modules.context_intake import load_category_registry


DATA_DIR = Path(__file__).parents[1] / "evaluation" / "context_intake"
CATEGORY_IDS = tuple(sorted(item.category_id for item in load_category_registry().categories))


def _result(top1: str, score: float, *, is_unknown: bool = False):
    top2 = next(category for category in CATEGORY_IDS if category != top1)
    return SimpleNamespace(
        top1_category_id=top1,
        top1_similarity=score,
        top2_category_id=top2,
        top2_similarity=min(score, 0.2),
        is_unknown=is_unknown,
        model_id="test/model",
        model_revision="revision-a",
        catalog_version="catalog-a",
    )


def test_fixed_development_and_test_sets_cover_all_labels_without_faq_leakage() -> None:
    development = load_classification_jsonl((DATA_DIR / "dev.jsonl").read_text(encoding="utf-8"))
    test = load_classification_jsonl((DATA_DIR / "test.jsonl").read_text(encoding="utf-8"))
    validate_disjoint_splits(development, test)

    required = set(CATEGORY_IDS) | {"unknown"}
    for split in (development, test):
        expected = {case.expected_category_id for case in split}
        assert expected >= required
    assert len([case for case in development if case.source == "cdc_faq"]) == 63
    assert len([case for case in test if case.source == "cdc_faq"]) == 56


def test_loader_and_split_validation_reject_faq_id_overlap() -> None:
    row = {
        "id": "faq-1",
        "query": "example",
        "expected_category_id": CATEGORY_IDS[0],
        "source": "cdc_faq",
        "source_faq_id": "faq-1",
    }
    case_a = load_classification_jsonl(json.dumps(row))[0]
    case_b = ClassificationCase("different-record-id", "other query", CATEGORY_IDS[0], "cdc_faq", "faq-1")

    with pytest.raises(ClassificationEvaluationError, match="FAQ IDs overlap"):
        validate_disjoint_splits((case_a,), (case_b,))


def test_split_validation_rejects_repeated_query_text() -> None:
    left = ClassificationCase("left", "same  query", CATEGORY_IDS[0], "cdc_faq", "faq-left")
    right = ClassificationCase("right", "same query", CATEGORY_IDS[1], "cdc_faq", "faq-right")

    with pytest.raises(ClassificationEvaluationError, match="query text overlaps"):
        validate_disjoint_splits((left,), (right,))


def test_threshold_is_chosen_from_dev_macro_f1_including_unknown() -> None:
    cases = (
        ClassificationCase("known", "known query", CATEGORY_IDS[0], "cdc_faq", "faq-known"),
        ClassificationCase("ood", "non-target query", "unknown", "synthetic_ood"),
    )
    results = (_result(CATEGORY_IDS[0], 0.8), _result(CATEGORY_IDS[1], 0.4))

    calibration = calibrate_threshold(cases, results, CATEGORY_IDS)

    assert calibration["threshold"] == 0.8
    assert calibration["objective"].endswith("plus unknown")
    assert calibration["tie_break"] == "choose the lower threshold"


def test_threshold_ties_choose_the_lower_threshold() -> None:
    cases = (
        ClassificationCase("one", "one", CATEGORY_IDS[0], "cdc_faq", "faq-one"),
        ClassificationCase("two", "two", CATEGORY_IDS[1], "cdc_faq", "faq-two"),
    )
    results = (_result(CATEGORY_IDS[0], 0.6), _result(CATEGORY_IDS[1], 0.8))

    calibration = calibrate_threshold(cases, results, CATEGORY_IDS)

    assert calibration["threshold"] == -1.0


def test_test_metrics_report_confusion_f1_unknown_rate_and_ood_false_acceptance() -> None:
    cases = (
        ClassificationCase("known", "known query", CATEGORY_IDS[0], "cdc_faq", "faq-known"),
        ClassificationCase("ood-rejected", "ood one", "unknown", "synthetic_ood"),
        ClassificationCase("ood-accepted", "ood two", "unknown", "synthetic_ood"),
    )
    results = (
        _result(CATEGORY_IDS[0], 0.7),
        _result(CATEGORY_IDS[1], 0.4, is_unknown=True),
        _result(CATEGORY_IDS[1], 0.8),
    )

    report = evaluate_classification(
        cases,
        results,
        CATEGORY_IDS,
        threshold=0.5,
        development_sha256="dev-hash",
        test_sha256="test-hash",
        prototype_sha256=None,
    )

    assert report["metrics"]["accuracy"]["value"] == pytest.approx(2 / 3)
    assert report["metrics"]["macro_f1_known_14"] >= 1 / 14
    assert report["metrics"]["unknown_rate"]["value"] == pytest.approx(1 / 3)
    assert report["metrics"]["ood_false_acceptance_rate"] == {
        "numerator": 1,
        "denominator": 2,
        "value": 0.5,
    }
    assert report["confusion_counts"]["unknown"]["unknown"] == 1
    assert report["metadata"]["prototype_identity_available"] is False
    assert report["metadata"]["development_dataset_sha256"] == "dev-hash"


def test_evaluation_rejects_classifier_identity_or_unknown_flag_drift() -> None:
    case = ClassificationCase("ood", "non-target", "unknown", "synthetic_ood")
    result = _result(CATEGORY_IDS[0], 0.9, is_unknown=True)

    with pytest.raises(ClassificationEvaluationError, match="unknown flag"):
        evaluate_classification(
            (case,), (result,), CATEGORY_IDS, threshold=0.5,
            development_sha256="dev", test_sha256="test", prototype_sha256="proto",
        )

    consistent = _result(CATEGORY_IDS[0], 0.9)
    other = _result(CATEGORY_IDS[0], 0.9)
    other.model_revision = "revision-b"
    with pytest.raises(ClassificationEvaluationError, match="identity changed"):
        calibrate_threshold(
            (ClassificationCase("a", "a", CATEGORY_IDS[0], "cdc_faq", "faq-a"),
             ClassificationCase("b", "b", CATEGORY_IDS[0], "cdc_faq", "faq-b")),
            (consistent, other), CATEGORY_IDS,
        )
