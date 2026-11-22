"""Canonical, hash-verified run persistence for the knowledge base."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
from typing import Any

from ..domain.contracts import (
    KnowledgeBaseValidationError,
    KnowledgeChunk,
    KnowledgeDocument,
    canonical_json_bytes,
    parse_json_object,
)
from ..domain.policies import QualityIssue
from ..domain.runs import RunData


_JSONL_FILES = {
    "documents.jsonl", "chunks.jsonl", "issues.jsonl", "rejected.jsonl", "reviews.jsonl",
}
_REQUIRED_FILES = _JSONL_FILES | {"quality_report.json", "manifest.json"}
_REVIEW_FIELDS = {
    "document_id", "document_version", "source_fingerprint", "flags", "decision",
    "reviewer", "reviewed_at_utc", "reason",
}
_HASH = re.compile(r"^[0-9a-f]{64}$")


class RunIOError(RuntimeError):
    """A run could not be read or safely published."""

    def __init__(self, message: str, *, diagnostic_path: Path | None = None):
        super().__init__(message)
        self.diagnostic_path = diagnostic_path


def _record_dict(record: Any) -> dict[str, Any]:
    if hasattr(record, "to_dict"):
        value = record.to_dict()
    elif isinstance(record, Mapping):
        value = dict(record)
    else:
        raise KnowledgeBaseValidationError("run record must be a mapping or contract entity")
    if not isinstance(value, dict):
        raise KnowledgeBaseValidationError("run record must serialize to an object")
    return value


def _issue_key(record: Mapping[str, Any]) -> tuple[str, int, str, bytes]:
    locator = record.get("input_locator")
    line = record.get("line_number")
    code = record.get("code")
    return (
        locator if isinstance(locator, str) else "",
        line if isinstance(line, int) and not isinstance(line, bool) else -1,
        code if isinstance(code, str) else "",
        canonical_json_bytes(record),
    )


def _document_key(record: Mapping[str, Any]) -> tuple[str, bytes]:
    return str(record.get("document_id", "")), canonical_json_bytes(record)


def _chunk_key(record: Mapping[str, Any]) -> tuple[str, int, bytes]:
    index = record.get("chunk_index")
    return (
        str(record.get("document_id", "")),
        index if isinstance(index, int) and not isinstance(index, bool) else -1,
        canonical_json_bytes(record),
    )


def _review_key(record: Mapping[str, Any]) -> tuple[str, bytes]:
    return str(record["review_ref"]), canonical_json_bytes(record["record"])


def _unique_reviews(reviews: Sequence[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    by_ref: dict[str, bytes] = {}
    unique: dict[bytes, dict[str, Any]] = {}
    for envelope in reviews:
        if not isinstance(envelope, Mapping) or set(envelope) != {"review_ref", "record"}:
            raise KnowledgeBaseValidationError("review row must contain review_ref and record")
        ref = envelope["review_ref"]
        record = envelope["record"]
        if not isinstance(ref, str) or not ref.strip() or not isinstance(record, Mapping):
            raise KnowledgeBaseValidationError("review_ref must be nonempty and record must be an object")
        if set(record) != _REVIEW_FIELDS:
            raise KnowledgeBaseValidationError("review record has missing or unknown fields")
        canonical_record = canonical_json_bytes(record)
        previous = by_ref.get(ref)
        if previous is not None and previous != canonical_record:
            raise KnowledgeBaseValidationError(f"conflicting review records for review_ref {ref!r}")
        by_ref[ref] = canonical_record
        canonical_envelope = canonical_json_bytes({"review_ref": ref, "record": record})
        unique[canonical_envelope] = {"review_ref": ref, "record": dict(record)}
    return tuple(sorted(unique.values(), key=_review_key))


def _jsonl_bytes(records: Sequence[Any], key: Callable[[Mapping[str, Any]], Any]) -> bytes:
    values = [_record_dict(record) for record in records]
    values.sort(key=key)
    return b"".join(canonical_json_bytes(value) + b"\n" for value in values)


def _issue_bytes(records: Sequence[dict[str, Any]]) -> bytes:
    validated = [QualityIssue(**_record_dict(record)).to_dict() for record in records]
    return _jsonl_bytes(validated, _issue_key)


def _rejected_bytes(records: Sequence[dict[str, Any]]) -> bytes:
    required = {"input_locator", "line_number", "dataset_id", "source_record_id", "code", "raw_record"}
    values = [_record_dict(record) for record in records]
    for record in values:
        if set(record) != required:
            raise KnowledgeBaseValidationError("rejected row has missing or unknown fields")
        if not isinstance(record["input_locator"], str) or not record["input_locator"].strip():
            raise KnowledgeBaseValidationError("rejected.input_locator must be nonempty")
        if record["line_number"] is not None and (
            not isinstance(record["line_number"], int) or isinstance(record["line_number"], bool)
            or record["line_number"] < 1
        ):
            raise KnowledgeBaseValidationError("rejected.line_number must be a positive integer or null")
        for name in ("dataset_id", "source_record_id"):
            if record[name] is not None and not isinstance(record[name], str):
                raise KnowledgeBaseValidationError(f"rejected.{name} must be a string or null")
        if not isinstance(record["code"], str) or not record["code"].strip():
            raise KnowledgeBaseValidationError("rejected.code must be nonempty")
        if record["raw_record"] is not None and not isinstance(record["raw_record"], (dict, str)):
            raise KnowledgeBaseValidationError("rejected.raw_record must be an object, string, or null")
    return _jsonl_bytes(values, _issue_key)


def _issue_records(data: bytes, *, label: str) -> tuple[dict[str, Any], ...]:
    if not data:
        return ()
    if not data.endswith(b"\n"):
        raise RunIOError(f"{label} must end with one LF per record")
    records = []
    for number, raw_line in enumerate(data.splitlines(keepends=True), 1):
        if not raw_line.endswith(b"\n"):
            raise RunIOError(f"{label} line {number} is missing LF")
        try:
            record = parse_json_object(raw_line[:-1].decode("utf-8"))
        except (UnicodeError, KnowledgeBaseValidationError) as error:
            raise RunIOError(f"{label} line {number} is invalid: {error}") from error
        if canonical_json_bytes(record) + b"\n" != raw_line:
            raise RunIOError(f"{label} line {number} is not canonical JSONL")
        records.append(record)
    return tuple(records)


def _json_bytes(value: Any, *, label: str) -> dict[str, Any]:
    try:
        record = parse_json_object(value.decode("utf-8").rstrip("\n"))
    except (UnicodeError, KnowledgeBaseValidationError) as error:
        raise RunIOError(f"{label} is invalid JSON: {error}") from error
    if value != canonical_json_bytes(record) + b"\n":
        raise RunIOError(f"{label} is not canonical JSON")
    return record


def _safe_output_path(root: Path, name: Any) -> Path:
    if not isinstance(name, str) or not name or "\\" in name or ":" in name:
        raise RunIOError("manifest.output_hashes contains an unsafe path")
    parts = name.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise RunIOError("manifest.output_hashes contains an unsafe path")
    relative = PurePosixPath(name)
    if relative.is_absolute() or name == "manifest.json":
        raise RunIOError("manifest.output_hashes contains an unsafe path")
    candidate = root.joinpath(*relative.parts)
    resolved_root = root.resolve()
    try:
        resolved_candidate = candidate.resolve(strict=True)
        resolved_candidate.relative_to(resolved_root)
    except (OSError, ValueError) as error:
        raise RunIOError(f"output path escapes run or is missing: {name}") from error
    return candidate


def _is_link(path: Path) -> bool:
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


def _actual_files(root: Path) -> set[str]:
    files: set[str] = set()
    for base, directories, names in os.walk(root, followlinks=False):
        base_path = Path(base)
        for name in tuple(directories):
            child = base_path / name
            if _is_link(child):
                raise RunIOError(f"symbolic link is not allowed in a run: {child.relative_to(root)}")
        if directories:
            raise RunIOError("nested output directories are not supported in this run format")
        for name in names:
            file_path = base_path / name
            if _is_link(file_path):
                raise RunIOError(f"symbolic link is not allowed in a run: {file_path.relative_to(root)}")
            files.add(file_path.relative_to(root).as_posix())
    return files


def _validate_manifest(manifest: dict[str, Any], actual_files: set[str]) -> None:
    if manifest.get("schema_version") != "1.0" or manifest.get("complete") is not True:
        raise RunIOError("run manifest must have schema_version 1.0 and complete=true")
    output_hashes = manifest.get("output_hashes")
    if not isinstance(output_hashes, dict):
        raise RunIOError("run manifest output_hashes must be an object")
    expected_hashes = _REQUIRED_FILES - {"manifest.json"}
    if actual_files != _REQUIRED_FILES or set(output_hashes) != expected_hashes:
        raise RunIOError("run files and manifest output_hashes do not match the required output set")
    for name, digest in output_hashes.items():
        if not isinstance(digest, str) or not _HASH.fullmatch(digest):
            raise RunIOError(f"invalid output hash for {name}")


def read_run(path: str | Path) -> RunData:
    """Read a complete run after path, canonical encoding, and file-hash checks."""
    root = Path(path).expanduser()
    if _is_link(root):
        raise RunIOError("run root must not be a symbolic link")
    if not root.is_dir():
        raise RunIOError(f"run directory does not exist: {root}")
    actual_files = _actual_files(root)
    if not _REQUIRED_FILES <= actual_files or "manifest.json" not in actual_files:
        missing = sorted(_REQUIRED_FILES - actual_files)
        raise RunIOError(f"run is missing required files: {', '.join(missing)}")

    manifest = _json_bytes((root / "manifest.json").read_bytes(), label="manifest.json")
    _validate_manifest(manifest, actual_files)
    for name, digest in manifest["output_hashes"].items():
        output = _safe_output_path(root, name)
        actual = hashlib.sha256(output.read_bytes()).hexdigest()
        if actual != digest:
            raise RunIOError(f"output hash mismatch: {name}")

    documents = []
    for index, payload in enumerate(_issue_records((root / "documents.jsonl").read_bytes(), label="documents.jsonl"), 1):
        try:
            documents.append(KnowledgeDocument.from_dict(payload))
        except KnowledgeBaseValidationError as error:
            raise RunIOError(f"documents.jsonl line {index} is invalid: {error}") from error
    if list(documents) != sorted(documents, key=lambda item: _document_key(item.to_dict())):
        raise RunIOError("documents.jsonl records are not stably sorted")

    chunks = []
    for index, payload in enumerate(_issue_records((root / "chunks.jsonl").read_bytes(), label="chunks.jsonl"), 1):
        try:
            chunks.append(KnowledgeChunk.from_dict(payload))
        except KnowledgeBaseValidationError as error:
            raise RunIOError(f"chunks.jsonl line {index} is invalid: {error}") from error
    if list(chunks) != sorted(chunks, key=lambda item: _chunk_key(item.to_dict())):
        raise RunIOError("chunks.jsonl records are not stably sorted")

    issues = _issue_records((root / "issues.jsonl").read_bytes(), label="issues.jsonl")
    try:
        issues = tuple(QualityIssue(**item).to_dict() for item in issues)
    except (TypeError, KnowledgeBaseValidationError) as error:
        raise RunIOError(f"issues.jsonl contains an invalid issue: {error}") from error
    if list(issues) != sorted(issues, key=_issue_key):
        raise RunIOError("issues.jsonl records are not stably sorted")

    rejected = _issue_records((root / "rejected.jsonl").read_bytes(), label="rejected.jsonl")
    # Reuse the writer's shape checks while preserving the already-read records.
    try:
        _rejected_bytes(rejected)
    except KnowledgeBaseValidationError as error:
        raise RunIOError(f"rejected.jsonl contains an invalid record: {error}") from error
    if list(rejected) != sorted(rejected, key=_issue_key):
        raise RunIOError("rejected.jsonl records are not stably sorted")

    reviews = _issue_records((root / "reviews.jsonl").read_bytes(), label="reviews.jsonl")
    try:
        normalized_reviews = _unique_reviews(reviews)
    except KnowledgeBaseValidationError as error:
        raise RunIOError(f"reviews.jsonl contains an invalid record: {error}") from error
    if tuple(reviews) != normalized_reviews:
        raise RunIOError("reviews.jsonl records are duplicated or not stably sorted")

    report = _json_bytes((root / "quality_report.json").read_bytes(), label="quality_report.json")
    return RunData(tuple(documents), tuple(chunks), issues, rejected, report, manifest, tuple(reviews))


def _now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_run_files(stage: Path, run: RunData) -> dict[str, bytes]:
    documents = [_record_dict(document) for document in run.documents]
    chunks = [_record_dict(chunk) for chunk in run.chunks]
    reviews = _unique_reviews(run.reviews)
    if not isinstance(run.quality_report, Mapping) or not isinstance(run.manifest, Mapping):
        raise KnowledgeBaseValidationError("quality_report and manifest must be objects")
    contents = {
        "documents.jsonl": _jsonl_bytes(documents, _document_key),
        "chunks.jsonl": _jsonl_bytes(chunks, _chunk_key),
        "issues.jsonl": _issue_bytes(run.issues),
        "rejected.jsonl": _rejected_bytes(run.rejected),
        "reviews.jsonl": _jsonl_bytes(reviews, _review_key),
        "quality_report.json": canonical_json_bytes(dict(run.quality_report)) + b"\n",
    }
    for name, data in contents.items():
        (stage / name).write_bytes(data)
    return contents


def _write_failure_contents(stage: Path, *, issues: Sequence[dict[str, Any]],
                            rejected: Sequence[dict[str, Any]], error: str) -> None:
    for child in stage.iterdir():
        if child.is_dir() and not _is_link(child):
            shutil.rmtree(child)
        else:
            child.unlink()
    (stage / "issues.jsonl").write_bytes(_issue_bytes(issues))
    (stage / "rejected.jsonl").write_bytes(_rejected_bytes(rejected))
    (stage / "failure.json").write_bytes(canonical_json_bytes({"error": str(error)}) + b"\n")


def _new_stage(target: Path) -> Path:
    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or _is_link(target):
        raise FileExistsError(f"output already exists: {target}")
    return Path(tempfile.mkdtemp(prefix=f".{target.name}.staging-", dir=parent))


def _publish_directory(stage: Path, target: Path) -> None:
    if target.exists() or _is_link(target):
        raise FileExistsError(f"output already exists: {target}")
    # On Windows os.rename is an atomic no-replace operation for an existing target.
    os.rename(stage, target)


def publish_run(output_dir: str | Path, run: RunData, *,
                validator: Callable[[RunData], None]) -> Path:
    """Write, self-validate, semantically validate, then atomically publish a run."""
    if not isinstance(run, RunData):
        raise TypeError("run must be RunData")
    if not callable(validator):
        raise TypeError("validator must be callable")
    target = Path(output_dir).expanduser()
    stage = _new_stage(target)
    try:
        contents = _write_run_files(stage, run)
        manifest = dict(run.manifest)
        now = _now_utc()
        manifest.setdefault("started_at_utc", now)
        manifest.setdefault("completed_at_utc", _now_utc())
        manifest["output_hashes"] = {
            name: hashlib.sha256(data).hexdigest() for name, data in sorted(contents.items())
        }
        manifest["complete"] = True
        (stage / "manifest.json").write_bytes(canonical_json_bytes(manifest) + b"\n")
        try:
            validated = read_run(stage)
            validator(validated)
        except Exception as error:
            _write_failure_contents(stage, issues=run.issues, rejected=run.rejected, error=str(error))
            raise RunIOError(
                f"run validation failed; diagnostics retained at {stage}: {error}",
                diagnostic_path=stage,
            ) from error
        _publish_directory(stage, target)
        return target
    except Exception:
        if stage.exists() and not _is_link(stage):
            # Keep semantic validator failures as diagnostics; clean other failed writes.
            if not (stage / "failure.json").exists():
                shutil.rmtree(stage, ignore_errors=True)
        raise


def write_failure(output_dir: str | Path, *, issues: Sequence[dict[str, Any]],
                   rejected: Sequence[dict[str, Any]], error: str) -> Path:
    """Atomically publish a diagnostic directory without a success manifest."""
    target = Path(output_dir).expanduser()
    stage = _new_stage(target)
    try:
        _write_failure_contents(stage, issues=issues, rejected=rejected, error=error)
        _publish_directory(stage, target)
        return target
    except Exception:
        if stage.exists() and not _is_link(stage):
            shutil.rmtree(stage, ignore_errors=True)
        raise
