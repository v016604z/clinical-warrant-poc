"""Composition root wiring module use cases to infrastructure adapters."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

from clinical_warrant import __version__
from clinical_warrant.infrastructure.catalog import load_research_catalog
from clinical_warrant.infrastructure.runtime_metadata import core_dependency_versions
from clinical_warrant.modules.classification import TextEncoder
from clinical_warrant.modules.classification.application.classifier import (
    DEFAULT_THRESHOLD,
    QuestionClassifier,
    _validate_threshold,
)
from clinical_warrant.modules.classification.infrastructure.model_encoder import SentenceTransformerEncoder
from clinical_warrant.modules.classification.infrastructure.prototype_cache import (
    FilePrototypeVectorCache,
    default_cache_dir,
)
from clinical_warrant.modules.context_intake import load_category_registry
from clinical_warrant.modules.context_intake.application.classifier import IntakeQuestionClassifier
from clinical_warrant.modules.context_intake.infrastructure.prototype_catalog import load_intake_prototype_catalog
from clinical_warrant.modules.decision.application.warrant import WarrantEngine
from clinical_warrant.modules.evaluation.application.evaluation import EvaluationCase, EvaluationError, evaluate_cases
from clinical_warrant.modules.evaluation.infrastructure.report_writer import ReportPublishError, publish_report
from clinical_warrant.modules.knowledge_base.application.chunking import chunking_fingerprint
from clinical_warrant.modules.knowledge_base.domain.policies import QualityPolicy
from clinical_warrant.modules.knowledge_base.infrastructure.adapters import CdcQaAdapter, GenericJsonlAdapter
from clinical_warrant.modules.knowledge_base.infrastructure.cleaning import CLEANING_VERSION, clean_source_record
from clinical_warrant.modules.knowledge_base.infrastructure.input_reader import read_inputs
from clinical_warrant.modules.knowledge_base.infrastructure.run_io import read_run, publish_run, write_failure
from clinical_warrant.modules.knowledge_base.domain.contracts import canonical_json_bytes


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


def build_intake_question_classifier(
    *, threshold: float, encoder: TextEncoder | None = None
) -> IntakeQuestionClassifier:
    """Build the isolated 14-category classifier; threshold must be calibrated explicitly."""
    registry = load_category_registry()
    return IntakeQuestionClassifier(
        encoder if encoder is not None else SentenceTransformerEncoder(), registry=registry,
        prototypes=load_intake_prototype_catalog(), threshold=threshold,
        cache=FilePrototypeVectorCache(default_cache_dir() / "context-intake"),
    )


def build_context_intake_service(
    *,
    extractor,
    threshold: float | None = None,
    encoder: TextEncoder | None = None,
    classifier=None,
    registry=None,
    repository=None,
):
    """Compose intake; persistence is opt-in and receives a session repository."""
    from clinical_warrant.modules.context_intake import ContextIntakeService, load_category_registry

    if registry is not None and classifier is None:
        raise ValueError("a custom registry requires an injected classifier built for that registry")
    active_registry = registry if registry is not None else load_category_registry()
    if classifier is None:
        if threshold is None:
            raise ValueError("threshold is required when a classifier is not injected")
        classifier = build_intake_question_classifier(threshold=threshold, encoder=encoder)
    classifier_version = getattr(classifier, "catalog_version", None)
    if classifier_version is not None and classifier_version != active_registry.version:
        raise ValueError("classifier catalog_version does not match the Category Registry")
    return ContextIntakeService(
        classifier=classifier, extractor=extractor, registry=active_registry,
        repository=repository,
    )


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


def kb_build(args) -> dict[str, Any]:
    from clinical_warrant.modules.knowledge_base.application.pipeline import build_run, validate_run
    source = Path(args.input).resolve()
    output = Path(args.output_dir).resolve()
    source_root = Path(args.source_root).resolve() if args.adapter == "cdc_qa" else None
    _check_kb_output(output, (source, source_root))
    try:
        return _kb_build_impl(args, source, output, source_root, build_run, validate_run)
    except Exception as error:
        if not output.exists():
            write_failure(output, issues=getattr(error, "issues", ()),
                          rejected=getattr(error, "rejected", ()), error=str(error))
        raise


def _kb_build_impl(args, source: Path, output: Path, source_root: Path | None,
                   build_run, validate_run) -> dict[str, Any]:
    evidence: list[dict[str, str]] = []

    def add_evidence(path: Path, role: str) -> bytes:
        resolved = path.resolve()
        raw = resolved.read_bytes()
        evidence.append({"path": str(resolved), "sha256": hashlib.sha256(raw).hexdigest(), "role": role})
        return raw

    input_raw = add_evidence(source, "input")
    mapping = _read_config(args.mapping, "mapping", add_evidence) if args.mapping else None
    if args.adapter == "cdc_qa":
        manifest_path = source_root / "manifest.json"
        manifest = _parse_json_object(add_evidence(manifest_path, "source_manifest"), "CDC manifest")
        adapter = CdcQaAdapter(manifest, intended_use=args.intended_use, usage_decision=args.usage_decision)
        for entry, role, expected_digest in _cdc_evidence_paths(manifest):
            snapshot_path = (source_root / urlsplit(entry).path).resolve()
            if snapshot_path != source_root and not snapshot_path.is_relative_to(source_root):
                raise ValueError(f"manifest evidence path escapes source root: {entry}")
            snapshot_bytes = add_evidence(snapshot_path, role)
            actual_digest = hashlib.sha256(snapshot_bytes).hexdigest()
            if actual_digest != expected_digest:
                raise ValueError(f"CDC source evidence hash mismatch: {entry}")
        source_root_value = str(source_root)
    else:
        rights = _read_config(args.rights_config, "rights", add_evidence)
        adapter = GenericJsonlAdapter(dataset_id=args.dataset_id, attribution=args.attribution,
                                      rights=rights, mapping=mapping)
        source_root_value = None

    policy = QualityPolicy(args.as_of, args.stale_after_days, args.require_time_sensitive_review)
    chunking = {"algorithm_version": "structure-v1", "max_chars": args.max_chars,
                "overlap_chars": args.overlap_chars}
    config = {"version": CLEANING_VERSION, "profiles": sorted({adapter.to_config()["settings"]["cleaning_profile"]})}
    evidence.sort(key=lambda item: (item["role"], item["path"], item["sha256"]))
    metadata = {
        "schema_version": "1.0", "pipeline_version": __version__, "operation": "build",
        "adapter": adapter.to_config(), "source_root": source_root_value,
        "inputs": evidence, "cleaning_config": config, "chunking_config": chunking,
        "chunking_fingerprint": chunking_fingerprint(chunking),
        "quality_policy": policy.to_dict(), "strict": args.strict,
        "started_at_utc": _now_utc(), "completed_at_utc": None, "output_hashes": {},
        "counts": {}, "complete": False,
    }
    run = build_run(read_inputs(source, adapter, raw_bytes=input_raw), cleaner=clean_source_record, policy=policy,
                    chunking_config=chunking, strict=args.strict, run_metadata=metadata)
    run = _with_run_metadata(run, completed_at_utc=_now_utc())
    published = publish_run(output, run, validator=validate_run)
    return {"run_dir": str(published), "counts": run.quality_report}


def kb_merge(args) -> dict[str, Any]:
    from clinical_warrant.modules.knowledge_base.application.pipeline import merge_runs, validate_run
    paths = [Path(path).resolve() for path in args.inputs]
    output = Path(args.output_dir).resolve()
    _check_kb_output(output, paths)
    try:
        return _kb_merge_impl(args, paths, output, merge_runs, validate_run)
    except Exception as error:
        if not output.exists():
            write_failure(output, issues=getattr(error, "issues", ()),
                          rejected=getattr(error, "rejected", ()), error=str(error))
        raise


def _kb_merge_impl(args, paths: list[Path], output: Path, merge_runs, validate_run) -> dict[str, Any]:
    runs = [read_run(path) for path in paths]
    input_evidence = []
    for path, run in zip(paths, runs):
        input_evidence.extend({"path": item["path"], "sha256": item["sha256"], "role": item["role"]}
                              for item in run.manifest.get("inputs", []))
        manifest_bytes = (path / "manifest.json").read_bytes()
        if manifest_bytes != canonical_json_bytes(run.manifest) + b"\n":
            raise ValueError(f"input run changed while it was being read: {path}")
        input_evidence.append({"path": str(path / "manifest.json"),
                               "sha256": hashlib.sha256(manifest_bytes).hexdigest(),
                               "role": "input_run_manifest"})
        for name, expected in run.manifest["output_hashes"].items():
            file = path / name
            raw = file.read_bytes()
            actual = hashlib.sha256(raw).hexdigest()
            if actual != expected:
                raise ValueError(f"input run changed while it was being read: {file}")
            input_evidence.append({"path": str(file), "sha256": actual, "role": "input_run_file"})
    input_evidence.sort(key=lambda item: (item["role"], item["path"], item["sha256"]))
    metadata = {"schema_version": "1.0", "pipeline_version": __version__, "operation": "merge",
                "adapter": {"type": "merge", "inputs": sorted(
                    (run.manifest.get("adapter") for run in runs), key=canonical_json_bytes)},
                "source_root": None, "inputs": input_evidence,
                "input_runs": [str(path) for path in paths],
                "cleaning_config": runs[0].manifest["cleaning_config"],
                "chunking_config": runs[0].manifest["chunking_config"],
                "chunking_fingerprint": runs[0].manifest["chunking_fingerprint"],
                "quality_policy": runs[0].manifest["quality_policy"], "strict": args.strict,
                "started_at_utc": _now_utc(), "completed_at_utc": None, "output_hashes": {},
                "counts": {}, "complete": False}
    run = merge_runs(runs, strict=args.strict, run_metadata=metadata)
    run = _with_run_metadata(run, completed_at_utc=_now_utc())
    published = publish_run(output, run, validator=validate_run)
    return {"run_dir": str(published), "counts": run.quality_report}


def kb_validate(args) -> dict[str, Any]:
    from clinical_warrant.modules.knowledge_base.application.pipeline import validate_run
    run = read_run(Path(args.dataset))
    validate_run(run)
    return {"dataset": str(Path(args.dataset).resolve()), "valid": True}


def _read_config(path: str, label: str, add_evidence) -> dict[str, Any]:
    raw = add_evidence(Path(path), label)
    return _parse_json_object(raw, label)


def _parse_json_object(raw: bytes, label: str) -> dict[str, Any]:
    from clinical_warrant.modules.knowledge_base.domain.contracts import parse_json_object
    try:
        return parse_json_object(raw.decode("utf-8"))
    except (UnicodeError, ValueError) as error:
        raise ValueError(f"{label} must be a UTF-8 JSON object: {error}") from error


def _cdc_evidence_paths(manifest: dict[str, Any]) -> list[tuple[str, str, str]]:
    paths: dict[str, tuple[str, str]] = {}
    for page in manifest.get("pages", []):
        snapshot = page.get("raw_snapshot") if isinstance(page, dict) else None
        if snapshot:
            paths[str(snapshot)] = ("source_snapshot", page.get("html_sha256"))
    for item in manifest.get("policy_provenance", []):
        snapshot = item.get("raw_snapshot") if isinstance(item, dict) else None
        if snapshot:
            paths[str(snapshot)] = ("policy_snapshot", item.get("html_sha256"))
    return [(path, role, digest) for path, (role, digest) in sorted(paths.items())]


def _check_kb_output(output: Path, protected: tuple[Path | None, ...]) -> None:
    for path in protected:
        if path is None:
            continue
        if output == path or output.is_relative_to(path):
            raise ValueError(f"output directory must not equal or be inside source: {path}")
    if output.exists():
        raise FileExistsError(f"output directory already exists: {output}")


def _now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _with_run_metadata(run, **updates):
    manifest = dict(run.manifest)
    manifest.update(updates)
    return replace(run, manifest=manifest)
