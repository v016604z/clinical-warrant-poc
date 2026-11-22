"""CLI-level negative checks for conflicts, immutable output, and semantic validation."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from clinical_warrant.interfaces.cli import main
from clinical_warrant.modules.knowledge_base.application.pipeline import validate_run
from clinical_warrant.modules.knowledge_base.domain.contracts import (
    KnowledgeDocument,
    canonical_json_bytes,
    canonical_sha256,
    chunking_fingerprint,
    document_version_for,
)
from clinical_warrant.modules.knowledge_base.infrastructure.run_io import publish_run, read_run


_RIGHTS = {
    "status": "recorded", "statement": "Synthetic fixture rights", "policy_locators": [],
    "intended_use": "local validation only", "usage_decision": "allowed",
}


def _build(tmp_path: Path, name: str, *, text: str = "Synthetic body for validation.",
           source_url: str | None = None, usage_decision: str = "allowed",
           include_invalid_row: bool = False) -> Path:
    rights_path = tmp_path / f"{name}-rights.json"
    rights = {**_RIGHTS, "usage_decision": usage_decision}
    rights_path.write_bytes(canonical_json_bytes(rights) + b"\n")
    input_path = tmp_path / f"{name}.jsonl"
    row = {
        "id": "shared", "title": "Synthetic article", "text": text,
        "source_name": "Synthetic publisher", "source_url": source_url or f"fixture:{name}",
        "updated_at": "2026-11-20",
    }
    input_bytes = canonical_json_bytes(row) + b"\n"
    input_path.write_bytes(input_bytes + (b"{\n" if include_invalid_row else b""))
    run_path = tmp_path / name
    assert main([
        "kb", "build", "--adapter", "generic_jsonl", "--input", str(input_path),
        "--output-dir", str(run_path), "--dataset-id", "e2e_source",
        "--attribution", "Synthetic Publisher", "--rights-config", str(rights_path),
        "--as-of", "2026-11-22", "--stale-after-days", "1095",
    ]) == 0
    return run_path


def _merge(output: Path, *runs: Path) -> int:
    return main(["kb", "merge", "--inputs", *(str(path) for path in runs), "--output-dir", str(output)])


def _write_jsonl(path: Path, records: list[dict]) -> bytes:
    encoded = b"".join(canonical_json_bytes(record) + b"\n" for record in records)
    path.write_bytes(encoded)
    return encoded


def _rehash_run_file(run_path: Path, filename: str, data: bytes) -> None:
    """Make tampering canonical and update its hash to exercise semantic checks."""
    path = run_path / filename
    path.write_bytes(data)
    manifest_path = run_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["output_hashes"][filename] = hashlib.sha256(data).hexdigest()
    manifest_path.write_bytes(canonical_json_bytes(manifest) + b"\n")


@pytest.mark.parametrize(
    ("other_text", "other_url", "expected_code"),
    [
        ("Different semantic version.", "fixture:version", "version_conflict"),
        ("Synthetic body for validation.", "fixture:changed-provenance", "metadata_conflict"),
    ],
)
def test_cli_merge_conflicts_fail_and_keep_both_candidates(tmp_path, capsys,
                                                            other_text, other_url, expected_code):
    first = _build(tmp_path, "first", source_url="fixture:first")
    second = _build(tmp_path, "second", text=other_text, source_url=other_url)
    first_doc = json.loads((first / "documents.jsonl").read_text(encoding="utf-8").splitlines()[0])
    second_doc = json.loads((second / "documents.jsonl").read_text(encoding="utf-8").splitlines()[0])
    if expected_code == "metadata_conflict":
        assert first_doc["document_version"] == second_doc["document_version"]
        assert first_doc["source"] != second_doc["source"]
    else:
        assert first_doc["document_version"] != second_doc["document_version"]

    output = tmp_path / "conflicted"
    assert _merge(output, first, second) == 2
    capsys.readouterr()
    failure = json.loads((output / "failure.json").read_text(encoding="utf-8"))
    issues = [json.loads(line) for line in (output / "issues.jsonl").read_text(encoding="utf-8").splitlines()]
    assert not (output / "manifest.json").exists()
    assert "conflict" in failure["error"]
    assert {row["code"] for row in issues} == {expected_code}
    assert {row["document_id"] for row in issues} == {"e2e_source:shared"}
    assert len(issues) == 2
    assert {row["input_locator"] for row in issues} == {"fixture:first", other_url}


def test_cli_strict_merge_rejects_errors_in_a_nonstrict_input_run(tmp_path, capsys):
    source = _build(tmp_path, "partial", include_invalid_row=True)
    report = json.loads((source / "quality_report.json").read_text(encoding="utf-8"))
    assert report["rejected_count"] == 1

    non_strict_output = tmp_path / "nonstrict-merged"
    assert _merge(non_strict_output, source) == 0
    capsys.readouterr()
    assert main(["kb", "validate", "--dataset", str(non_strict_output)]) == 0
    capsys.readouterr()

    strict_output = tmp_path / "strict-merge-diagnostics"
    assert main(["kb", "merge", "--inputs", str(source), "--output-dir", str(strict_output), "--strict"]) == 2
    capsys.readouterr()
    failure = json.loads((strict_output / "failure.json").read_text(encoding="utf-8"))
    issues = [json.loads(line) for line in (strict_output / "issues.jsonl").read_text(encoding="utf-8").splitlines()]
    rejected = [json.loads(line) for line in (strict_output / "rejected.jsonl").read_text(encoding="utf-8").splitlines()]
    assert "strict merge" in failure["error"]
    assert issues and issues[0]["code"] == "invalid_json"
    assert len(rejected) == 1
    assert not (strict_output / "manifest.json").exists()


def test_cli_merge_refuses_existing_output_without_changing_sentinel(tmp_path, capsys):
    run = _build(tmp_path, "source")
    output = tmp_path / "existing-output"
    output.mkdir()
    sentinel = output / "sentinel.txt"
    sentinel.write_text("preserve exactly", encoding="utf-8")

    assert _merge(output, run) == 1
    capsys.readouterr()
    assert sentinel.read_text(encoding="utf-8") == "preserve exactly"
    assert sorted(path.name for path in output.iterdir()) == ["sentinel.txt"]


@pytest.mark.parametrize("tamper", ["chunk_reference", "document_version", "quality_report", "chunking_config"])
def test_cli_validate_rejects_semantic_tampering_even_after_rehash(tmp_path, capsys, tamper):
    run = _build(tmp_path, "source")
    if tamper == "chunk_reference":
        path = run / "chunks.jsonl"
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        rows[0]["chunk_id"] = "chunk:" + "0" * 64
        _rehash_run_file(run, "chunks.jsonl", _write_jsonl(path, rows))
    elif tamper == "document_version":
        path = run / "documents.jsonl"
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        rows[0]["document_version"] = "sha256:" + "0" * 64
        _rehash_run_file(run, "documents.jsonl", _write_jsonl(path, rows))
    elif tamper == "quality_report":
        path = run / "quality_report.json"
        report = json.loads(path.read_text(encoding="utf-8"))
        report["source_counts"] = {"forged": 99}
        _rehash_run_file(run, "quality_report.json", canonical_json_bytes(report) + b"\n")
    else:
        manifest_path = run / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["chunking_config"].update({"max_chars": 16, "overlap_chars": 2})
        manifest["chunking_fingerprint"] = chunking_fingerprint(manifest["chunking_config"])
        manifest_path.write_bytes(canonical_json_bytes(manifest) + b"\n")

    assert main(["kb", "validate", "--dataset", str(run)]) == 2
    assert capsys.readouterr().err


def _reviewed_run(tmp_path: Path, name: str) -> tuple[Path, str]:
    from clinical_warrant.modules.knowledge_base.domain.runs import RunData

    source_path = _build(tmp_path, name)
    run = read_run(source_path)
    original = run.documents[0]
    ref = "audit:synthetic-review"
    payload = original.to_dict()
    payload["quality"] = {**payload["quality"], "review_status": "approved", "review_ref": ref}
    reviewed_document = KnowledgeDocument.from_dict(payload)
    audit = {
        "document_id": reviewed_document.document_id,
        "document_version": reviewed_document.document_version,
        "source_fingerprint": canonical_sha256(reviewed_document.source),
        "flags": list(reviewed_document.quality["flags"]),
        "decision": "approved", "reviewer": "Synthetic reviewer",
        "reviewed_at_utc": "2026-11-22T00:00:00Z", "reason": "Fixture validation only.",
    }
    reviewed_document.validate_review(audit)
    reviewed = RunData(
        (reviewed_document,), run.chunks, run.issues, run.rejected, run.quality_report,
        run.manifest, ({"review_ref": ref, "record": audit},),
    )
    reviewed_path = tmp_path / f"{name}-reviewed"
    publish_run(reviewed_path, reviewed, validator=validate_run)
    return reviewed_path, ref


def test_valid_review_evidence_survives_merge_and_is_hash_covered(tmp_path, capsys):
    reviewed_path, ref = _reviewed_run(tmp_path, "review-source")
    merged = tmp_path / "review-merged"

    assert _merge(merged, reviewed_path) == 0
    capsys.readouterr()
    review_line, = (merged / "reviews.jsonl").read_text(encoding="utf-8").splitlines()
    envelope = json.loads(review_line)
    assert envelope["review_ref"] == ref
    docs = [json.loads(line) for line in (merged / "documents.jsonl").read_text(encoding="utf-8").splitlines()]
    assert docs[0]["quality"]["review_ref"] == ref
    manifest = json.loads((merged / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["output_hashes"]["reviews.jsonl"] == hashlib.sha256((merged / "reviews.jsonl").read_bytes()).hexdigest()
    assert main(["kb", "validate", "--dataset", str(merged)]) == 0
    capsys.readouterr()


@pytest.mark.parametrize("stale_change", ["source", "version"])
def test_old_review_fails_when_source_or_document_version_changes(tmp_path, capsys, stale_change):
    run, _ = _reviewed_run(tmp_path, "review-source")
    doc_path = run / "documents.jsonl"
    rows = [json.loads(line) for line in doc_path.read_text(encoding="utf-8").splitlines()]
    if stale_change == "source":
        rows[0]["source"]["source_locator"] = "fixture:changed-source"
    else:
        rows[0]["title"] = "Changed title"
        rows[0]["content_text"] = "Changed title\nSynthetic body for validation."
        rows[0]["document_version"] = document_version_for(rows[0])
    _rehash_run_file(run, "documents.jsonl", _write_jsonl(doc_path, rows))

    assert main(["kb", "validate", "--dataset", str(run)]) == 2
    error = capsys.readouterr().err
    assert "review" in error.lower()


def test_approved_review_cannot_bypass_prohibited_rights(tmp_path, capsys):
    source_path = _build(tmp_path, "prohibited-source", usage_decision="prohibited")
    run = read_run(source_path)
    original = run.documents[0]
    ref = "audit:prohibited-attempt"
    payload = original.to_dict()
    payload["quality"] = {**payload["quality"], "review_status": "approved", "review_ref": ref}
    # It is structurally a valid Document; the attached approval must still fail policy validation.
    candidate = KnowledgeDocument.from_dict(payload)
    audit = {
        "document_id": candidate.document_id, "document_version": candidate.document_version,
        "source_fingerprint": canonical_sha256(candidate.source),
        "flags": list(candidate.quality["flags"]), "decision": "approved",
        "reviewer": "Synthetic reviewer", "reviewed_at_utc": "2026-11-22T00:00:00Z",
        "reason": "Must not override prohibited use.",
    }
    doc_path = source_path / "documents.jsonl"
    rows = [candidate.to_dict()]
    _rehash_run_file(source_path, "documents.jsonl", _write_jsonl(doc_path, rows))
    review_row = {"review_ref": ref, "record": audit}
    _rehash_run_file(source_path, "reviews.jsonl", _write_jsonl(source_path / "reviews.jsonl", [review_row]))

    assert main(["kb", "validate", "--dataset", str(source_path)]) == 2
    assert "prohibited" in capsys.readouterr().err.lower()
