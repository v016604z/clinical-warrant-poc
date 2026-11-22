"""Calibrate the 14-category classifier on dev data and evaluate held-out test data."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from clinical_warrant.bootstrap.composition import build_intake_question_classifier
from clinical_warrant.modules.context_intake import load_category_registry
from clinical_warrant.modules.context_intake.application.evaluation import (
    UNKNOWN_CATEGORY_ID,
    calibrate_threshold,
    evaluate_classification,
    load_classification_jsonl,
    sha256_bytes,
    validate_disjoint_splits,
)
from clinical_warrant.modules.evaluation.infrastructure.report_writer import publish_report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "evaluation-runs" / "context-intake",
        help="directory for immutable run reports",
    )
    args = parser.parse_args()

    data_dir = ROOT / "evaluation" / "context_intake"
    dev_bytes = (data_dir / "dev.jsonl").read_bytes()
    test_bytes = (data_dir / "test.jsonl").read_bytes()
    development = load_classification_jsonl(dev_bytes.decode("utf-8"))
    test = load_classification_jsonl(test_bytes.decode("utf-8"))
    validate_disjoint_splits(development, test)
    registry = load_category_registry()
    category_ids = tuple(sorted(item.category_id for item in registry.categories))
    _require_all_labels(development, category_ids, "development")
    _require_all_labels(test, category_ids, "test")

    # The provisional threshold only exposes raw Top-1 scores; calibration ignores its unknown flag.
    provisional = build_intake_question_classifier(threshold=0.0)
    development_results = tuple(provisional.classify(case.query) for case in development)
    calibration = calibrate_threshold(development, development_results, category_ids)

    classifier = build_intake_question_classifier(
        threshold=calibration["threshold"], encoder=provisional.encoder
    )
    test_results = tuple(classifier.classify(case.query) for case in test)
    report = evaluate_classification(
        test,
        test_results,
        category_ids,
        threshold=calibration["threshold"],
        development_sha256=sha256_bytes(dev_bytes),
        test_sha256=sha256_bytes(test_bytes),
        prototype_sha256=getattr(classifier, "prototype_sha256", None),
    )
    report["calibration"] = {
        key: value for key, value in calibration.items() if key != "development_metrics"
    }
    report["metadata"].update(
        {
            "development_cases": len(development),
            "test_cases": len(test),
            "prototype_identity_source": (
                "classifier.prototype_sha256"
                if report["metadata"]["prototype_identity_available"]
                else "unavailable"
            ),
        }
    )
    now = datetime.now(timezone.utc)
    run_id = f"{now.strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:10]}"
    report["metadata"]["run_id"] = run_id
    summary = {key: value for key, value in report.items() if key not in {"predictions", "errors"}}
    published = publish_report(
        {
            "run_id": run_id,
            "summary": summary,
            "predictions": report["predictions"],
            "errors": report["errors"],
        },
        args.output,
    )
    print(json.dumps(published, ensure_ascii=False, indent=2))


def _require_all_labels(cases, category_ids: tuple[str, ...], split_name: str) -> None:
    supported = {case.expected_category_id for case in cases}
    missing = (set(category_ids) | {UNKNOWN_CATEGORY_ID}) - supported
    if missing:
        raise ValueError(f"{split_name} split is missing labels: {sorted(missing)}")


if __name__ == "__main__":
    main()
