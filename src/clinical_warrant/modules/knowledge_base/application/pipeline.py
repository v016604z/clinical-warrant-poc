"""Build, merge, and semantically validate complete KB runs."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from copy import deepcopy
from datetime import date, datetime
from typing import Any

from clinical_warrant import __version__

from ..domain.contracts import (
    KnowledgeBaseValidationError,
    KnowledgeChunk,
    KnowledgeDocument,
    canonical_json_bytes,
    canonical_sha256,
    chunking_fingerprint,
)
from ..domain.policies import QualityIssue, QualityPolicy
from ..domain.runs import RunData, SourceInput
from .chunking import chunk_document
from .deduplication import DeduplicationResult, deduplicate_documents
from .preparation import prepare_document


class PipelineFailure(ValueError):
    """A build or merge failure with rows suitable for a diagnostic run."""

    def __init__(self, message: str, *, issues=(), rejected=()):
        super().__init__(message)
        self.issues = tuple(dict(item) for item in issues)
        self.rejected = tuple(dict(item) for item in rejected)


_REPORT_NOTICE = "Quality flags describe source and data integrity; they are not clinical judgments."
_BUILD_COUNT_KEYS = (
    "input_count", "document_count", "rejected_count", "duplicate_count", "ready_count",
    "needs_review_count", "excluded_count", "chunk_count", "issue_count",
)


def _issue(input_locator: str, line_number: int | None, *, code: str, message: str,
           source: SourceInput | None = None, document: KnowledgeDocument | None = None) -> dict[str, Any]:
    record = source.source if source is not None else None
    dataset_id = record.dataset_id if record is not None else None
    source_record_id = record.source_record_id if record is not None else None
    document_id = document.document_id if document is not None else (
        f"{dataset_id}:{source_record_id}" if dataset_id and source_record_id else None
    )
    return QualityIssue(
        input_locator=input_locator, line_number=line_number, dataset_id=dataset_id,
        source_record_id=source_record_id, document_id=document_id, code=code,
        severity="error", message=message,
    ).to_dict()


def _safe_raw(value: Any) -> Any:
    try:
        canonical_json_bytes(value)
        return value
    except (KnowledgeBaseValidationError, TypeError, ValueError):
        # Keep malformed source evidence serializable without altering its meaning.
        import json
        return json.dumps(value, ensure_ascii=True, allow_nan=False, default=repr)


def _rejected(source: SourceInput, code: str, message: str) -> dict[str, Any]:
    record = source.source
    return {
        "input_locator": source.input_locator,
        "line_number": source.line_number,
        "dataset_id": record.dataset_id if record is not None else None,
        "source_record_id": record.source_record_id if record is not None else None,
        "code": code,
        "raw_record": _safe_raw(source.raw_record),
    }


def _sort_records(records: Iterable[Mapping[str, Any]]) -> tuple[dict[str, Any], ...]:
    return tuple(sorted((dict(record) for record in records), key=lambda item: (
        item.get("input_locator", ""), -1 if item.get("line_number") is None else item["line_number"],
        item.get("code", ""), canonical_json_bytes(item),
    )))


def _sort_documents(documents: Iterable[KnowledgeDocument]) -> tuple[KnowledgeDocument, ...]:
    return tuple(sorted(documents, key=lambda item: item.document_id))


def _is_indexable(document: KnowledgeDocument) -> bool:
    rights = document.source["rights"]
    quality = document.quality
    return (
        quality["status"] == "ready"
        and quality["review_status"] != "rejected"
        and rights["status"] == "recorded"
        and rights["usage_decision"] == "allowed"
    )


def _report_counts(documents: tuple[KnowledgeDocument, ...], chunks: tuple[KnowledgeChunk, ...],
                   issues: tuple[dict, ...], rejected: tuple[dict, ...]) -> dict[str, Any]:
    statuses = Counter(document.quality["status"] for document in documents)
    flags = Counter(flag for document in documents for flag in document.quality["flags"])
    sources = Counter(document.source["dataset_id"] for document in documents)
    dates = Counter(document.source["source_updated_at"] or "unknown" for document in documents)
    return {
        "document_count": len(documents),
        "rejected_count": len(rejected),
        "ready_count": statuses["ready"],
        "needs_review_count": statuses["needs_review"],
        "excluded_count": statuses["excluded"],
        "chunk_count": len(chunks),
        "issue_count": len(issues),
        "flag_counts": dict(sorted(flags.items())),
        "source_counts": dict(sorted(sources.items())),
        "source_date_counts": dict(sorted(dates.items())),
        "missing_source_date_count": sum(document.source["source_updated_at"] is None for document in documents),
        "attachment_dependency_count": flags["attachment_dependency"],
        "missing_source_locator_count": sum(item.get("code") == "missing_source_locator" for item in rejected),
    }


def _cross_source_summary(result: DeduplicationResult) -> tuple[list[dict[str, Any]], int]:
    groups = [
        {"document_version": group[0].document_version,
         "document_ids": sorted(document.document_id for document in group)}
        for group in result.cross_source_groups
    ]
    groups.sort(key=lambda item: (item["document_version"], item["document_ids"]))
    return groups, sum(len(group["document_ids"]) for group in groups)


def _build_report(input_count: int, documents: tuple[KnowledgeDocument, ...],
                  chunks: tuple[KnowledgeChunk, ...], issues: tuple[dict, ...],
                  rejected: tuple[dict, ...], deduplication: DeduplicationResult) -> dict[str, Any]:
    # Cross-source counts describe the output corpus. Quarantined inputs are
    # represented separately with their input-run provenance below.
    cross_groups, cross_documents = _cross_source_summary(deduplicate_documents(documents))
    report = {
        "schema_version": "1.0", "operation": "build", "input_count": input_count,
        "duplicate_count": deduplication.exact_duplicate_count,
        "conflict_count": len(deduplication.conflict_groups),
        "cross_source_duplicate_group_count": len(cross_groups),
        "cross_source_duplicate_document_count": cross_documents,
        "cross_source_duplicate_groups": cross_groups,
        "clinical_judgment": False, "notice": _REPORT_NOTICE,
    }
    report.update(_report_counts(documents, chunks, issues, rejected))
    return report


def _count_projection(report: Mapping[str, Any]) -> dict[str, int]:
    return {key: int(report[key]) for key in _BUILD_COUNT_KEYS}


def _make_manifest(seed: Mapping[str, Any], *, operation: str, chunking_config: Mapping[str, Any],
                   policy_data: Any, strict: bool, report: Mapping[str, Any],
                   cleaning_config: Mapping[str, Any]) -> dict[str, Any]:
    manifest = dict(seed)
    manifest.update({
        "schema_version": "1.0", "pipeline_version": __version__, "operation": operation,
        "cleaning_config": deepcopy(dict(cleaning_config)),
        "chunking_config": deepcopy(dict(chunking_config)),
        "chunking_fingerprint": chunking_fingerprint(chunking_config),
        "quality_policy": deepcopy(policy_data), "strict": strict,
        "counts": _count_projection(report),
        "output_hashes": dict(seed.get("output_hashes", {})),
    })
    return manifest


def build_run(inputs: Iterable[SourceInput], *, cleaner, policy: QualityPolicy,
              chunking_config: Mapping[str, Any], strict: bool,
              run_metadata: dict) -> RunData:
    """Prepare source rows and return a complete, unpublished build run."""
    if not isinstance(policy, QualityPolicy):
        raise KnowledgeBaseValidationError("policy must be a QualityPolicy")
    if type(strict) is not bool:
        raise KnowledgeBaseValidationError("strict must be boolean")
    fingerprint = chunking_fingerprint(chunking_config)
    documents: list[KnowledgeDocument] = []
    issues: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    contexts: dict[bytes, list[SourceInput]] = defaultdict(list)
    cleaning_versions: set[str] = set()
    cleaning_profiles: set[str] = set()
    input_count = 0

    for source_input in inputs:
        input_count += 1
        if not isinstance(source_input, SourceInput):
            raise KnowledgeBaseValidationError("inputs must contain SourceInput values")
        if source_input.error is not None or source_input.source is None:
            code = source_input.code or "invalid_source_record"
            message = source_input.error or "The input row did not produce a source record."
            issues.append(_issue(source_input.input_locator, source_input.line_number,
                                 code=code, message=message, source=source_input))
            rejected.append(_rejected(source_input, code, message))
            continue
        cleaning_profiles.add(source_input.source.cleaning_profile)
        result = prepare_document(
            source_input.source, cleaner=cleaner, policy=policy,
            input_locator=source_input.input_locator, line_number=source_input.line_number,
        )
        issues.extend(issue.to_dict() for issue in result.issues)
        if result.cleaning_version is not None:
            cleaning_versions.add(result.cleaning_version)
        if result.document is None:
            errors = [issue for issue in result.issues if issue.severity == "error"]
            code = errors[0].code if errors else "document_preparation_failed"
            message = "; ".join(issue.message for issue in errors) or "Document preparation failed."
            rejected.append(_rejected(source_input, code, message))
            continue
        documents.append(result.document)
        contexts[canonical_json_bytes(result.document.to_dict())].append(source_input)

    sorted_issues = _sort_records(issues)
    sorted_rejected = _sort_records(rejected)
    if strict and any(item["severity"] == "error" for item in sorted_issues):
        raise PipelineFailure("strict build rejected one or more input records",
                              issues=sorted_issues, rejected=sorted_rejected)

    deduplicated = deduplicate_documents(documents)
    if deduplicated.conflict_groups:
        conflict_issues = list(sorted_issues)
        for group in deduplicated.conflict_groups:
            versions = sorted({document.document_version for document in group.documents})
            for document in group.documents:
                rows = contexts.get(canonical_json_bytes(document.to_dict()), [])
                for source_input in rows or [None]:
                    conflict_issues.append(_issue(
                        source_input.input_locator if source_input else document.source["source_locator"],
                        source_input.line_number if source_input else None,
                        code=group.reason,
                        message=f"Conflicting records for {document.document_id}; versions: {', '.join(versions)}.",
                        source=source_input, document=document,
                    ))
        raise PipelineFailure("document identity conflicts prevent publishing this build",
                              issues=_sort_records(conflict_issues), rejected=sorted_rejected)

    ordered_documents = _sort_documents(deduplicated.accepted_documents)
    chunks: list[KnowledgeChunk] = []
    for document in ordered_documents:
        if _is_indexable(document):
            chunks.extend(chunk_document(document, chunking_config))
    ordered_chunks = tuple(sorted(chunks, key=lambda item: (item.document_id, item.chunk_index)))
    ordered_issues = _sort_records(sorted_issues)
    report = _build_report(input_count, ordered_documents, ordered_chunks, ordered_issues,
                           sorted_rejected, deduplicated)
    report["duplicate_count"] = deduplicated.exact_duplicate_count
    report["input_count"] = input_count
    if report["input_count"] != report["document_count"] + report["rejected_count"] + report["duplicate_count"]:
        raise PipelineFailure("build counts do not reconcile", issues=ordered_issues, rejected=sorted_rejected)

    cleaning_config = {
        "profiles": sorted(cleaning_profiles), "versions": sorted(cleaning_versions),
    }
    manifest = _make_manifest(run_metadata, operation="build", chunking_config=chunking_config,
                              policy_data=policy.to_dict(), strict=strict,
                              report=report, cleaning_config=cleaning_config)
    run = RunData(ordered_documents, ordered_chunks, ordered_issues, sorted_rejected, report, manifest)
    validate_run(run)
    return run


def _run_identity(run: RunData) -> str:
    manifest = run.manifest
    identity = manifest.get("run_id") or manifest.get("run_identity")
    if isinstance(identity, str) and identity:
        return identity
    hashes = manifest.get("output_hashes", {})
    if isinstance(hashes, Mapping) and hashes:
        return "run:" + canonical_sha256(hashes)
    return "run:" + canonical_sha256({
        "manifest": manifest,
        "documents": [item.to_dict() for item in run.documents],
        "chunks": [item.to_dict() for item in run.chunks],
        "issues": list(run.issues), "rejected": list(run.rejected),
    })


def _run_sort_key(run: RunData) -> tuple[str, bytes]:
    return _run_identity(run), canonical_json_bytes({
        "manifest": run.manifest,
        "documents": [item.to_dict() for item in run.documents],
        "chunks": [item.to_dict() for item in run.chunks],
        "issues": list(run.issues), "rejected": list(run.rejected),
        "reviews": list(getattr(run, "reviews", ())),
    })


def _quarantine_reason(document: KnowledgeDocument) -> str:
    quality = document.quality
    rights = document.source["rights"]
    if quality["review_status"] == "rejected":
        return "review_rejected"
    if rights["status"] != "recorded" or rights["usage_decision"] != "allowed":
        return "rights_not_approved"
    return quality["status"]


def _merge_report(input_runs: list[str], runs: list[RunData], documents: tuple[KnowledgeDocument, ...],
                  chunks: tuple[KnowledgeChunk, ...], issues: tuple[dict, ...],
                  rejected: tuple[dict, ...], deduplication: DeduplicationResult,
                  quarantine: list[dict[str, Any]]) -> dict[str, Any]:
    cross_groups, cross_documents = _cross_source_summary(deduplicate_documents(documents))
    counts = _report_counts(documents, chunks, issues, rejected)
    all_input_documents = [document for run in runs for document in run.documents]
    input_status = Counter(document.quality["status"] for document in all_input_documents)
    input_summaries = []
    for run_id, run in sorted(zip(input_runs, runs), key=lambda item: item[0]):
        statuses = Counter(document.quality["status"] for document in run.documents)
        quarantine_rows = [{
            "input_run": run_id, "document_id": document.document_id,
            "document_version": document.document_version,
            "reason": _quarantine_reason(document), "count": 1,
        } for document in run.documents if not _is_indexable(document)]
        input_summaries.append({
            "input_run": run_id, "document_count": len(run.documents),
            "chunk_count": len(run.chunks), "ready_count": statuses["ready"],
            "needs_review_count": statuses["needs_review"], "excluded_count": statuses["excluded"],
            "rejected_count": len(run.rejected), "issue_count": len(run.issues),
        "duplicate_count": (run.quality_report.get("duplicate_count", 0)
                            + run.quality_report.get("upstream_duplicate_count", 0)),
            "quarantined_documents": sorted(quarantine_rows, key=lambda item: (
                item["input_run"], item["document_id"], item["document_version"], item["reason"]
            )),
        })
    counts.update({
        "schema_version": "1.0", "operation": "merge",
        "input_count": len(all_input_documents), "input_document_count": len(all_input_documents),
        "input_chunk_count": sum(len(run.chunks) for run in runs),
        "input_ready_count": input_status["ready"],
        "input_needs_review_count": input_status["needs_review"],
        "input_excluded_count": input_status["excluded"],
        "duplicate_count": deduplication.exact_duplicate_count,
        "upstream_duplicate_count": sum(
            run.quality_report.get("duplicate_count", 0) + run.quality_report.get("upstream_duplicate_count", 0)
            for run in runs
        ),
        "conflict_count": len(deduplication.conflict_groups),
        "cross_source_duplicate_group_count": len(cross_groups),
        "cross_source_duplicate_document_count": cross_documents,
        "cross_source_duplicate_groups": cross_groups,
        "input_runs": sorted(input_runs),
        "input_summaries": input_summaries,
        "quarantine_count": len(quarantine),
        "quarantine_reasons": dict(sorted(Counter(item["reason"] for item in quarantine).items())),
        "quarantined_documents": sorted(quarantine, key=lambda item: (
            item["input_run"], item["document_id"], item["document_version"], item["reason"]
        )),
        "clinical_judgment": False, "notice": _REPORT_NOTICE,
    })
    return counts


def merge_runs(runs: Iterable[RunData], *, strict: bool = False,
               run_metadata: dict | None = None) -> RunData:
    """Merge validated runs without losing input-run provenance or review evidence."""
    ordered_runs = sorted(runs, key=_run_sort_key)
    if not ordered_runs:
        raise KnowledgeBaseValidationError("merge requires at least one input run")
    if type(strict) is not bool:
        raise KnowledgeBaseValidationError("strict must be boolean")
    for run in ordered_runs:
        validate_run(run)
    if strict and any(
        record.get("severity") == "error" for run in ordered_runs for record in run.issues
    ) or strict and any(run.rejected for run in ordered_runs):
        raise PipelineFailure(
            "strict merge cannot include input errors or rejected rows",
            issues=_sort_records(record for run in ordered_runs for record in run.issues),
            rejected=_sort_records(record for run in ordered_runs for record in run.rejected),
        )

    fingerprints = {run.manifest.get("chunking_fingerprint") for run in ordered_runs}
    configs = {canonical_json_bytes(run.manifest.get("chunking_config")) for run in ordered_runs}
    if len(fingerprints) != 1 or len(configs) != 1:
        raise PipelineFailure("input runs use different chunking configurations")
    config = ordered_runs[0].manifest["chunking_config"]

    deduplicated = deduplicate_documents(document for run in ordered_runs for document in run.documents)
    if deduplicated.conflict_groups:
        conflicts = []
        for group in deduplicated.conflict_groups:
            versions = sorted({document.document_version for document in group.documents})
            conflicts.extend(_issue(
                document.source["source_locator"], None, code=group.reason,
                message=f"Conflicting records for {document.document_id}; versions: {', '.join(versions)}.",
                document=document,
            ) for document in group.documents)
        raise PipelineFailure("document identity conflicts prevent merging these runs", issues=_sort_records(conflicts))

    run_ids = [_run_identity(run) for run in ordered_runs]
    quarantine: list[dict[str, Any]] = []
    eligible: list[KnowledgeDocument] = []
    for run_id, run in zip(run_ids, ordered_runs):
        for document in run.documents:
            if _is_indexable(document):
                continue
            quarantine.append({
                "input_run": run_id, "document_id": document.document_id,
                "document_version": document.document_version,
                "reason": _quarantine_reason(document), "count": 1,
            })
    eligible = list(deduplicated.accepted_documents)
    eligible = [document for document in eligible if _is_indexable(document)]
    documents = _sort_documents(eligible)
    chunks = tuple(chunk for document in documents for chunk in chunk_document(document, config))

    issue_rows = _sort_records(record for run in ordered_runs for record in run.issues)
    rejected_rows = _sort_records(record for run in ordered_runs for record in run.rejected)
    reviews_by_ref: dict[str, dict[str, Any]] = {}
    for run in ordered_runs:
        for envelope in getattr(run, "reviews", ()):
            ref = envelope["review_ref"]
            encoded = canonical_json_bytes(envelope["record"])
            previous = reviews_by_ref.get(ref)
            if previous is not None and canonical_json_bytes(previous["record"]) != encoded:
                raise PipelineFailure(f"conflicting review records for reference {ref}")
            reviews_by_ref[ref] = dict(envelope)
    needed_refs = {document.quality["review_ref"] for document in documents
                   if document.quality["review_ref"] is not None}
    reviews = tuple(reviews_by_ref[ref] for ref in sorted(needed_refs))

    report = _merge_report(run_ids, ordered_runs, documents, chunks, issue_rows,
                           rejected_rows, deduplicated, quarantine)
    policies = [
        {"input_run": run_id, "quality_policy": deepcopy(run.manifest.get("quality_policy")),
         "strict": run.manifest.get("strict"), "cleaning_config": deepcopy(run.manifest.get("cleaning_config"))}
        for run_id, run in sorted(zip(run_ids, ordered_runs), key=lambda item: item[0])
    ]
    seed = dict(run_metadata or {})
    seed["input_runs"] = sorted(run_ids)
    input_summaries = []
    for run_id, run in sorted(zip(run_ids, ordered_runs), key=lambda item: item[0]):
        statuses = Counter(document.quality["status"] for document in run.documents)
        quarantine_rows = [{
            "input_run": run_id, "document_id": document.document_id,
            "document_version": document.document_version,
            "reason": _quarantine_reason(document), "count": 1,
        } for document in run.documents if not _is_indexable(document)]
        input_summaries.append({
            "input_run": run_id, "document_count": len(run.documents),
            "chunk_count": len(run.chunks), "ready_count": statuses["ready"],
            "needs_review_count": statuses["needs_review"], "excluded_count": statuses["excluded"],
            "rejected_count": len(run.rejected), "issue_count": len(run.issues),
            "duplicate_count": run.quality_report.get("duplicate_count", 0),
            "quarantined_documents": sorted(quarantine_rows, key=lambda item: (
                item["input_run"], item["document_id"], item["document_version"], item["reason"]
            )),
        })
    seed["input_summaries"] = input_summaries
    manifest = dict(seed)
    manifest.update({
        "schema_version": "1.0", "pipeline_version": __version__, "operation": "merge",
        "chunking_config": deepcopy(dict(config)), "chunking_fingerprint": chunking_fingerprint(config),
        "cleaning_config": {"input_run_configs": policies}, "quality_policy": {"input_run_policies": policies},
        "strict": strict, "counts": {key: report[key] for key in (
            "input_count", "input_document_count", "input_chunk_count", "document_count",
            "rejected_count", "duplicate_count", "chunk_count", "issue_count", "quarantine_count",
        )},
        "output_hashes": dict(seed.get("output_hashes", {})),
    })
    result = RunData(documents, chunks, issue_rows, rejected_rows, report, manifest, reviews)
    validate_run(result)
    return result


def _validate_reviews(run: RunData) -> None:
    records: dict[str, dict[str, Any]] = {}
    for envelope in getattr(run, "reviews", ()):
        if not isinstance(envelope, Mapping) or set(envelope) != {"review_ref", "record"}:
            raise KnowledgeBaseValidationError("review rows must contain review_ref and record")
        ref, record = envelope["review_ref"], envelope["record"]
        if not isinstance(ref, str) or not ref.strip() or not isinstance(record, Mapping):
            raise KnowledgeBaseValidationError("review_ref must be nonempty and record must be an object")
        encoded = canonical_json_bytes(record)
        if ref in records and canonical_json_bytes(records[ref]["record"]) != encoded:
            raise KnowledgeBaseValidationError(f"conflicting review records for reference {ref}")
        records[ref] = dict(envelope)
    used: set[str] = set()
    for document in run.documents:
        review = document.quality["review_ref"]
        if review is None:
            if document.quality["review_status"] != "unreviewed":
                raise KnowledgeBaseValidationError("reviewed document is missing review_ref")
            continue
        if review not in records:
            raise KnowledgeBaseValidationError(f"missing audit record for review_ref {review}")
        document.validate_review(records[review]["record"])
        used.add(review)
    if used != set(records):
        raise KnowledgeBaseValidationError("run contains an unreferenced review record")


def _actual_cross_groups(documents: tuple[KnowledgeDocument, ...]) -> list[dict[str, Any]]:
    return _cross_source_summary(deduplicate_documents(documents))[0]


def _validate_manifest(manifest: Mapping[str, Any], report: Mapping[str, Any]) -> None:
    core = {"schema_version", "pipeline_version", "operation", "cleaning_config", "chunking_config",
            "chunking_fingerprint", "quality_policy", "strict", "counts", "output_hashes"}
    if not core <= manifest.keys():
        raise KnowledgeBaseValidationError("manifest is missing required application fields")
    if (manifest.get("schema_version") != "1.0" or not isinstance(manifest.get("pipeline_version"), str)
            or not manifest.get("pipeline_version", "").strip()):
        raise KnowledgeBaseValidationError("manifest schema/pipeline version is invalid")
    if type(manifest.get("strict")) is not bool:
        raise KnowledgeBaseValidationError("manifest strict must be boolean")
    for key in ("cleaning_config", "chunking_config", "quality_policy", "counts", "output_hashes"):
        if not isinstance(manifest.get(key), Mapping):
            raise KnowledgeBaseValidationError(f"manifest.{key} must be an object")
    if manifest.get("complete") is not True:
        return

    required = {"adapter", "source_root", "inputs", "started_at_utc", "completed_at_utc"}
    if not required <= manifest.keys():
        raise KnowledgeBaseValidationError("complete manifest is missing required provenance fields")
    if not isinstance(manifest["adapter"], Mapping):
        raise KnowledgeBaseValidationError("manifest.adapter must be an object")
    adapter_type = manifest["adapter"].get("type")
    if manifest["operation"] == "build":
        if adapter_type == "generic_jsonl":
            if (not all(isinstance(manifest["adapter"].get(key), Mapping)
                        for key in ("mapping", "settings", "provenance"))
                    or not manifest["adapter"]["mapping"] or not manifest["adapter"]["settings"]
                    or not manifest["adapter"]["provenance"]):
                raise KnowledgeBaseValidationError("generic_jsonl adapter config is incomplete")
        elif adapter_type == "cdc_qa":
            if (not all(isinstance(manifest["adapter"].get(key), Mapping)
                        for key in ("mapping", "settings", "rights"))
                    or not manifest["adapter"]["mapping"] or not manifest["adapter"]["settings"]
                    or not manifest["adapter"]["rights"]
                    or not isinstance(manifest["adapter"].get("policy_provenance"), list)
                    or not isinstance(manifest["adapter"].get("attribution"), str)
                    or not manifest["adapter"]["attribution"].strip()):
                raise KnowledgeBaseValidationError("cdc_qa adapter config is incomplete")
        else:
            raise KnowledgeBaseValidationError("unsupported build adapter type")
    elif adapter_type != "merge" or not isinstance(manifest["adapter"].get("inputs"), list):
        raise KnowledgeBaseValidationError("merge adapter config is incomplete")
    if manifest["source_root"] is not None and not isinstance(manifest["source_root"], str):
        raise KnowledgeBaseValidationError("manifest.source_root must be a string or null")
    if not isinstance(manifest["inputs"], list):
        raise KnowledgeBaseValidationError("manifest.inputs must be a list")
    for evidence in manifest["inputs"]:
        if (not isinstance(evidence, Mapping) or set(evidence) != {"path", "sha256", "role"}
                or not isinstance(evidence["path"], str) or not evidence["path"]
                or not isinstance(evidence["role"], str) or not evidence["role"]
                or not isinstance(evidence["sha256"], str) or len(evidence["sha256"]) != 64
                or any(char not in "0123456789abcdef" for char in evidence["sha256"])):
            raise KnowledgeBaseValidationError("manifest input evidence row is malformed")
    for digest in manifest["output_hashes"].values():
        if (not isinstance(digest, str) or len(digest) != 64
                or any(char not in "0123456789abcdef" for char in digest)):
            raise KnowledgeBaseValidationError("manifest output hash must be a lowercase SHA-256 hex digest")
    parsed_times = []
    for key in ("started_at_utc", "completed_at_utc"):
        value = manifest[key]
        if not isinstance(value, str) or "T" not in value or not value.endswith("Z"):
            raise KnowledgeBaseValidationError(f"manifest.{key} must be a UTC timestamp ending in Z")
        try:
            parsed_times.append(datetime.fromisoformat(value[:-1]))
        except ValueError as error:
            raise KnowledgeBaseValidationError(f"manifest.{key} is not a valid timestamp") from error
    if parsed_times[1] < parsed_times[0]:
        raise KnowledgeBaseValidationError("manifest completion time precedes start time")
    if manifest["operation"] == "build":
        policy = manifest["quality_policy"]
        if (not isinstance(policy.get("as_of"), str) or not policy.get("as_of")
                or type(policy.get("stale_after_days")) is not int
                or type(policy.get("require_time_sensitive_review")) is not bool):
            raise KnowledgeBaseValidationError("build manifest quality_policy is incomplete")
        try:
            if date.fromisoformat(policy["as_of"]).isoformat() != policy["as_of"]:
                raise ValueError
        except ValueError as error:
            raise KnowledgeBaseValidationError("build manifest quality_policy.as_of is invalid") from error
        if "type" not in manifest["adapter"]:
            raise KnowledgeBaseValidationError("build manifest adapter type is missing")
    elif manifest["operation"] == "merge":
        if not isinstance(manifest.get("input_runs"), list) or not isinstance(manifest.get("input_summaries"), list):
            raise KnowledgeBaseValidationError("merge manifest requires input_runs and input_summaries")
        if not isinstance(manifest["quality_policy"].get("input_run_policies"), list):
            raise KnowledgeBaseValidationError("merge manifest must preserve input run policies")
        policies = manifest["quality_policy"]["input_run_policies"]
        if [item.get("input_run") for item in policies if isinstance(item, Mapping)] != manifest["input_runs"]:
            raise KnowledgeBaseValidationError("merge manifest input policies are not aligned with input_runs")
        configs = manifest["cleaning_config"].get("input_run_configs")
        if (not isinstance(configs, list)
                or [item.get("input_run") for item in configs if isinstance(item, Mapping)] != manifest["input_runs"]):
            raise KnowledgeBaseValidationError("merge manifest input cleaning configs are not aligned")
    else:
        raise KnowledgeBaseValidationError("manifest operation must be build or merge")


def _validate_merge_report(run: RunData, report: Mapping[str, Any], manifest: Mapping[str, Any]) -> None:
    input_runs = report.get("input_runs")
    summaries = manifest.get("input_summaries")
    if (not isinstance(input_runs, list) or input_runs != sorted(input_runs)
            or manifest.get("input_runs") != input_runs):
        raise KnowledgeBaseValidationError("manifest/report input_runs do not match")
    if not isinstance(summaries, list) or report.get("input_summaries") != summaries:
        raise KnowledgeBaseValidationError("manifest/report input_summaries do not match")

    totals: Counter[str] = Counter()
    expected_quarantine = []
    summary_keys = {"input_run", "document_count", "chunk_count", "ready_count", "needs_review_count",
                    "excluded_count", "rejected_count", "issue_count", "duplicate_count",
                    "quarantined_documents"}
    quarantine_keys = {"input_run", "document_id", "document_version", "reason", "count"}
    for summary in summaries:
        if not isinstance(summary, Mapping) or set(summary) != summary_keys:
            raise KnowledgeBaseValidationError("merge input summary is malformed")
        if summary["input_run"] not in input_runs:
            raise KnowledgeBaseValidationError("merge input summary references unknown run")
        for key in summary_keys - {"input_run", "quarantined_documents"}:
            if type(summary[key]) is not int or summary[key] < 0:
                raise KnowledgeBaseValidationError(f"merge input summary {key} must be nonnegative")
            totals[key] += summary[key]
        if (summary["ready_count"] + summary["needs_review_count"] + summary["excluded_count"]
                != summary["document_count"]):
            raise KnowledgeBaseValidationError("merge input summary status counts do not reconcile")
        rows = summary["quarantined_documents"]
        if not isinstance(rows, list):
            raise KnowledgeBaseValidationError("merge input summary quarantine must be a list")
        for row in rows:
            if (not isinstance(row, Mapping) or set(row) != quarantine_keys
                    or row["input_run"] != summary["input_run"] or row["count"] != 1
                    or row["reason"] not in {"review_rejected", "rights_not_approved", "needs_review", "excluded"}):
                raise KnowledgeBaseValidationError("merge input summary quarantine row is malformed")
            expected_quarantine.append(row)
    if [summary["input_run"] for summary in summaries] != input_runs:
        raise KnowledgeBaseValidationError("merge input summaries are not aligned with input_runs")

    quarantine = report.get("quarantined_documents")
    if not isinstance(quarantine, list):
        raise KnowledgeBaseValidationError("merge report must include quarantined_documents")
    for row in (*expected_quarantine, *quarantine):
        if not isinstance(row, Mapping) or set(row) != quarantine_keys:
            raise KnowledgeBaseValidationError("merge quarantine row is malformed")
    row_key = lambda row: (row["input_run"], row["document_id"], row["document_version"],
                           row["reason"], row["count"])
    if sorted(map(row_key, expected_quarantine)) != sorted(map(row_key, quarantine)):
        raise KnowledgeBaseValidationError("merge quarantine rows do not match input summaries")
    for row in quarantine:
        if (not isinstance(row, Mapping) or set(row) != quarantine_keys
                or row["input_run"] not in input_runs or row["count"] != 1
                or row["reason"] not in {"review_rejected", "rights_not_approved", "needs_review", "excluded"}):
            raise KnowledgeBaseValidationError("merge quarantine row is malformed")
    if report.get("quarantine_count") != len(quarantine):
        raise KnowledgeBaseValidationError("merge quarantine_count does not match rows")
    if report.get("quarantine_reasons") != dict(sorted(Counter(row["reason"] for row in quarantine).items())):
        raise KnowledgeBaseValidationError("merge quarantine_reasons do not match rows")

    expected_totals = {
        "input_document_count": totals["document_count"], "input_count": totals["document_count"],
        "input_chunk_count": totals["chunk_count"], "input_ready_count": totals["ready_count"],
        "input_needs_review_count": totals["needs_review_count"], "input_excluded_count": totals["excluded_count"],
        "rejected_count": totals["rejected_count"], "issue_count": totals["issue_count"],
        "upstream_duplicate_count": totals["duplicate_count"],
    }
    if any(report.get(key) != value for key, value in expected_totals.items()):
        raise KnowledgeBaseValidationError("merge input summaries do not reconcile with report")
    unique_quarantine = {(row["document_id"], row["document_version"], row["reason"]) for row in quarantine}
    duplicate_count = report.get("duplicate_count")
    if (type(duplicate_count) is not int or duplicate_count < 0
            or totals["document_count"] != len(run.documents) + len(unique_quarantine) + duplicate_count):
        raise KnowledgeBaseValidationError("merge input/output/quarantine/duplicate counts do not reconcile")
    if report.get("conflict_count") != 0:
        raise KnowledgeBaseValidationError("merge report cannot contain unresolved conflicts")
    cross = _actual_cross_groups(run.documents)
    cross_count = sum(len(group["document_ids"]) for group in cross)
    if (report.get("cross_source_duplicate_groups") != cross
            or report.get("cross_source_duplicate_group_count") != len(cross)
            or report.get("cross_source_duplicate_document_count") != cross_count):
        raise KnowledgeBaseValidationError("merge cross-source statistics do not match output documents")
    if report.get("notice") != _REPORT_NOTICE:
        raise KnowledgeBaseValidationError("merge report notice does not match schema")
    expected_counts = {key: report.get(key) for key in (
        "input_count", "input_document_count", "input_chunk_count", "document_count", "rejected_count",
        "duplicate_count", "chunk_count", "issue_count", "quarantine_count")}
    if manifest.get("counts") != expected_counts:
        raise KnowledgeBaseValidationError("manifest counts do not match merge report")


def validate_run(run: RunData) -> None:
    """Recompute run semantics, chunk references, admission, and report counts."""
    if not isinstance(run, RunData):
        raise KnowledgeBaseValidationError("run must be RunData")
    manifest = run.manifest
    if not isinstance(manifest, Mapping):
        raise KnowledgeBaseValidationError("manifest must be an object")
    if not isinstance(run.quality_report, Mapping):
        raise KnowledgeBaseValidationError("quality_report must be an object")
    _validate_manifest(manifest, run.quality_report)
    config = manifest.get("chunking_config")
    fingerprint = chunking_fingerprint(config)
    if manifest.get("chunking_fingerprint") != fingerprint:
        raise KnowledgeBaseValidationError("manifest chunking_fingerprint does not match config")
    if not isinstance(run.documents, tuple) or not all(isinstance(doc, KnowledgeDocument) for doc in run.documents):
        raise KnowledgeBaseValidationError("run.documents must contain KnowledgeDocument values")
    if not isinstance(run.chunks, tuple) or not all(isinstance(chunk, KnowledgeChunk) for chunk in run.chunks):
        raise KnowledgeBaseValidationError("run.chunks must contain KnowledgeChunk values")
    if tuple(run.documents) != _sort_documents(run.documents):
        raise KnowledgeBaseValidationError("run documents are not in canonical order")
    if tuple(run.chunks) != tuple(sorted(run.chunks, key=lambda item: (item.document_id, item.chunk_index))):
        raise KnowledgeBaseValidationError("run chunks are not in canonical order")
    _validate_reviews(run)

    dedup = deduplicate_documents(run.documents)
    if dedup.exact_duplicate_count or dedup.conflict_groups:
        raise KnowledgeBaseValidationError("run documents contain duplicate or conflicting identities")
    docs_by_id = {doc.document_id: doc for doc in run.documents}
    chunks_by_doc: dict[str, list[KnowledgeChunk]] = defaultdict(list)
    for chunk in run.chunks:
        if chunk.document_id not in docs_by_id:
            raise KnowledgeBaseValidationError(f"chunk references missing document {chunk.document_id}")
        chunks_by_doc[chunk.document_id].append(chunk)
    for document in run.documents:
        actual = tuple(chunks_by_doc.get(document.document_id, ()))
        if _is_indexable(document):
            expected = chunk_document(document, config)
            if tuple(chunk.to_dict() for chunk in actual) != tuple(chunk.to_dict() for chunk in expected):
                raise KnowledgeBaseValidationError(f"chunks do not match document/config for {document.document_id}")
        elif actual:
            raise KnowledgeBaseValidationError(f"non-indexable document has chunks: {document.document_id}")

    for record in (*run.issues, *run.rejected):
        canonical_json_bytes(record)
    report = run.quality_report
    if not isinstance(report, Mapping):
        raise KnowledgeBaseValidationError("quality_report must be an object")
    operation = manifest.get("operation")
    base = _report_counts(run.documents, run.chunks, run.issues, run.rejected)
    for key, value in base.items():
        if report.get(key) != value:
            raise KnowledgeBaseValidationError(f"quality_report.{key} does not match run contents")
    if report.get("schema_version") != "1.0" or report.get("operation") != operation:
        raise KnowledgeBaseValidationError("quality_report schema_version/operation does not match manifest")
    if report.get("clinical_judgment") is not False:
        raise KnowledgeBaseValidationError("quality_report must not imply clinical judgment")
    if report.get("flag_counts") != base["flag_counts"]:
        raise KnowledgeBaseValidationError("quality_report.flag_counts does not match documents")
    if report.get("source_counts") != base["source_counts"]:
        raise KnowledgeBaseValidationError("quality_report.source_counts does not match documents")
    if report.get("source_date_counts") != base["source_date_counts"]:
        raise KnowledgeBaseValidationError("quality_report.source_date_counts does not match documents")
    if operation == "build":
        if manifest.get("strict") is True and (
            run.rejected or any(item.get("severity") == "error" for item in run.issues)
        ):
            raise KnowledgeBaseValidationError("strict build run cannot contain input errors or rejected rows")
        input_count = report.get("input_count")
        duplicate_count = report.get("duplicate_count")
        if type(input_count) is not int or type(duplicate_count) is not int:
            raise KnowledgeBaseValidationError("build report requires integer input/duplicate counts")
        if input_count != len(run.documents) + len(run.rejected) + duplicate_count:
            raise KnowledgeBaseValidationError("build report counts do not reconcile")
        if manifest.get("counts") != _count_projection(report):
            raise KnowledgeBaseValidationError("manifest counts do not match build report")
        expected_cross = _actual_cross_groups(run.documents)
        if report.get("cross_source_duplicate_groups") != expected_cross:
            raise KnowledgeBaseValidationError("quality_report cross-source groups do not match documents")
        if (report.get("cross_source_duplicate_group_count") != len(expected_cross)
                or report.get("cross_source_duplicate_document_count")
                != sum(len(group["document_ids"]) for group in expected_cross)
                or report.get("conflict_count") != 0 or report.get("notice") != _REPORT_NOTICE):
            raise KnowledgeBaseValidationError("build report derived fields do not match documents")
    elif operation == "merge":
        if report.get("document_count") != sum(_is_indexable(doc) for doc in run.documents):
            raise KnowledgeBaseValidationError("merged document_count must include only indexable documents")
        if any(not _is_indexable(doc) for doc in run.documents):
            raise KnowledgeBaseValidationError("merge run contains non-indexable documents")
        if manifest.get("strict") is True and (
            run.rejected or any(item.get("severity") == "error" for item in run.issues)
        ):
            raise KnowledgeBaseValidationError("strict merge run cannot contain input errors or rejected rows")
        _validate_merge_report(run, report, manifest)
    else:
        raise KnowledgeBaseValidationError("manifest operation must be build or merge")
