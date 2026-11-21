"""Composition root wiring module use cases to infrastructure adapters."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Callable

from clinical_warrant import __version__
from clinical_warrant.infrastructure.catalog import load_research_catalog
from clinical_warrant.infrastructure.runtime_metadata import core_dependency_versions
from clinical_warrant.modules.classification.application.classifier import (
    DEFAULT_THRESHOLD,
    QuestionClassifier,
    _validate_threshold,
)
from clinical_warrant.modules.classification.infrastructure.model_encoder import SentenceTransformerEncoder
from clinical_warrant.modules.classification.infrastructure.prototype_cache import FilePrototypeVectorCache
from clinical_warrant.modules.decision.application.warrant import WarrantEngine
from clinical_warrant.modules.evaluation.application.evaluation import EvaluationCase, EvaluationError, evaluate_cases
from clinical_warrant.modules.evaluation.infrastructure.report_writer import ReportPublishError, publish_report


def build_warrant_engine(
    *,
    threshold: float = DEFAULT_THRESHOLD,
    classifier_factory: Callable[..., Any] | None = None,
) -> WarrantEngine:
    threshold = _validate_threshold(threshold)
    catalog = load_research_catalog()
    if classifier_factory is None:
        classifier = QuestionClassifier(
            SentenceTransformerEncoder(),
            threshold=threshold,
            prototypes=catalog.prototypes,
            cache=FilePrototypeVectorCache(),
        )
    else:
        classifier = classifier_factory(threshold=threshold)
    return WarrantEngine(classifier, rules=catalog.rules)


def evaluate_scenarios(
    cases: tuple[EvaluationCase, ...],
    engine: WarrantEngine,
    output_dir: str | Path,
    *,
    threshold: float,
    dataset_sha256: str,
) -> dict[str, Any]:
    report = evaluate_cases(
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


def hash_dataset(raw: bytes) -> str:
    """Return the source dataset identity for evaluation metadata."""
    return hashlib.sha256(raw).hexdigest()
