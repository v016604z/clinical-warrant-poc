"""Backward-compatible scenario evaluation API with report publishing."""

from pathlib import Path
from typing import Any

from clinical_warrant import __version__
from clinical_warrant.infrastructure.runtime_metadata import core_dependency_versions
from clinical_warrant.modules.evaluation.application.evaluation import (
    DecisionEngine,
    EvaluationCase,
    EvaluationError,
    ExpectedResult,
    _content_hash,
    _rate,
    evaluate_cases as _evaluate_cases,
    load_evaluation_jsonl,
)
from clinical_warrant.modules.evaluation.infrastructure.report_writer import (
    ReportPublishError,
    publish_report,
)


def evaluate_cases(
    cases: tuple[EvaluationCase, ...],
    engine,
    output_dir: str | Path,
    *,
    threshold: float,
    dataset_sha256: str,
) -> dict[str, Any]:
    report = _evaluate_cases(
        cases,
        engine,
        threshold=threshold,
        dataset_sha256=dataset_sha256,
        package_version=__version__,
        core_dependencies=core_dependency_versions(),
    )
    try:
        return publish_report(report, output_dir)
    except ReportPublishError as error:
        raise EvaluationError(str(error)) from error


__all__ = [
    "DecisionEngine", "EvaluationCase", "EvaluationError", "ExpectedResult", "evaluate_cases",
    "load_evaluation_jsonl",
]
