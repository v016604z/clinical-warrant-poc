"""Filesystem and canonical-format checks for knowledge-base runs."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import subprocess

import pytest

from clinical_warrant.modules.knowledge_base.domain.contracts import (
    KnowledgeBaseValidationError,
    KnowledgeChunk,
    KnowledgeDocument,
    canonical_json_bytes,
)
from clinical_warrant.modules.knowledge_base.domain.runs import RunData, SourceInput
from clinical_warrant.modules.knowledge_base.infrastructure import run_io
from clinical_warrant.modules.knowledge_base.infrastructure.run_io import (
    RunIOError,
    publish_run,
    read_run,
    write_failure,
)


@pytest.fixture
def examples():
    schema = (Path(__file__).parents[1] / "docs" / "rag-kb-schema.md").read_text(encoding="utf-8")
    return {
        name: json.loads(body)
        for name, body in re.findall(r"<!-- example: (\w+) -->\n```json\n(.*?)\n```", schema, re.S)
    }


def run_data(examples, *, issues=(), rejected=(), reviews=()):
    document = KnowledgeDocument.from_dict(examples["document"])
    chunk = KnowledgeChunk.from_dict(examples["chunk"])
    manifest = {
        "schema_version": "1.0",
        "pipeline_version": "test-v1",
        "operation": "build",
        "adapter": "generic_jsonl",
        "source_root": "fixture",
        "inputs": [],
        "cleaning_config": {"version": "plain-v1"},
        "chunking_config": examples["chunking"]["config"],
        "chunking_fingerprint": examples["chunking"]["fingerprint"],
        "quality_policy": {"as_of": "2026-11-22", "stale_after_days": 1095},
        "strict": True,
        "counts": {},
    }
    return RunData((document,), (chunk,), tuple(issues), tuple(rejected),
                   {"schema_version": "1.0", "counts": {}}, manifest, tuple(reviews))


def test_source_input_and_run_data_are_frozen_shared_containers(examples):
    source = SourceInput("fixture.jsonl", 1, {"id": "x"}, None)
    assert source.code is None and source.error is None
    run = run_data(examples)
    with pytest.raises((AttributeError, TypeError)):
        run.documents = ()


def test_publish_round_trip_hashes_every_output_but_not_manifest(tmp_path, examples):
    run = run_data(examples)
    target = tmp_path / "run"
    called = []

    result = publish_run(target, run, validator=lambda data: called.append(data))

    assert result == target
    loaded = read_run(target)
    assert loaded.documents == run.documents
    assert loaded.chunks == run.chunks
    assert loaded.issues == () and loaded.rejected == () and loaded.reviews == ()
    assert called == [loaded]
    files = {path.name for path in target.iterdir()}
    assert files == {
        "documents.jsonl", "chunks.jsonl", "issues.jsonl", "rejected.jsonl",
        "reviews.jsonl", "quality_report.json", "manifest.json",
    }
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["complete"] is True
    assert set(manifest["output_hashes"]) == files - {"manifest.json"}
    for name, digest in manifest["output_hashes"].items():
        assert hashlib.sha256((target / name).read_bytes()).hexdigest() == digest


def test_published_record_files_are_canonical_and_stable_across_reruns(tmp_path, examples):
    run = run_data(examples)
    first = publish_run(tmp_path / "first", run, validator=lambda _: None)
    second = publish_run(tmp_path / "second", run, validator=lambda _: None)
    first_manifest = json.loads((first / "manifest.json").read_text(encoding="utf-8"))
    second_manifest = json.loads((second / "manifest.json").read_text(encoding="utf-8"))

    assert first_manifest["output_hashes"] == second_manifest["output_hashes"]
    for name in first_manifest["output_hashes"]:
        assert (first / name).read_bytes() == (second / name).read_bytes()
    assert (first / "documents.jsonl").read_bytes().endswith(b"\n")
    assert (first / "reviews.jsonl").read_bytes() == b""


def test_reviews_are_preserved_sorted_and_deduplicated_by_reference(tmp_path, examples):
    record = {
        "document_id": "example_articles:article-001",
        "document_version": examples["document"]["document_version"],
        "source_fingerprint": "a" * 64,
        "flags": [],
        "decision": "approved",
        "reviewer": "fixture-reviewer",
        "reviewed_at_utc": "2026-11-21T00:00:00Z",
        "reason": "fixture validation",
    }
    envelope = {"review_ref": "reviews/fixture.json", "record": record}
    run = run_data(examples, reviews=(envelope, envelope))
    target = publish_run(tmp_path / "reviewed", run, validator=lambda _: None)

    loaded = read_run(target)
    assert loaded.reviews == (envelope,)
    assert json.loads((target / "manifest.json").read_text(encoding="utf-8"))["output_hashes"]["reviews.jsonl"] == hashlib.sha256((target / "reviews.jsonl").read_bytes()).hexdigest()


def test_same_review_ref_with_different_record_fails_without_publishing(tmp_path, examples):
    record = {
        "document_id": "d:x", "document_version": "sha256:" + "a" * 64,
        "source_fingerprint": "b" * 64, "flags": [], "decision": "approved",
        "reviewer": "reviewer", "reviewed_at_utc": "2026-11-21T00:00:00Z", "reason": "ok",
    }
    first = {"review_ref": "review:one", "record": record}
    second = {"review_ref": "review:one", "record": {**record, "reviewer": "other"}}
    with pytest.raises(KnowledgeBaseValidationError, match="conflicting review records"):
        publish_run(tmp_path / "run", run_data(examples, reviews=(first, second)), validator=lambda _: None)
    assert not (tmp_path / "run").exists()


def test_read_run_rejects_output_tampering_and_unlisted_files(tmp_path, examples):
    target = publish_run(tmp_path / "run", run_data(examples), validator=lambda _: None)
    (target / "chunks.jsonl").write_bytes((target / "chunks.jsonl").read_bytes() + b" ")
    with pytest.raises(RunIOError, match="hash mismatch"):
        read_run(target)

    (target / "extra.json").write_text("{}", encoding="utf-8")
    with pytest.raises(RunIOError, match="required output set"):
        read_run(target)


def test_read_run_rejects_unsafe_manifest_hash_paths(tmp_path, examples):
    target = publish_run(tmp_path / "run", run_data(examples), validator=lambda _: None)
    path = target / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["output_hashes"]["../escape.json"] = "0" * 64
    path.write_bytes(canonical_json_bytes(manifest) + b"\n")

    with pytest.raises(RunIOError, match="required output set"):
        read_run(target)


def test_validator_failure_keeps_diagnostics_without_success_manifest(tmp_path, examples):
    issue = {"input_locator": "fixture.jsonl", "line_number": 1, "dataset_id": "d",
             "source_record_id": "x", "document_id": "d:x", "code": "invalid",
             "severity": "error", "message": "bad row"}

    def fail(_):
        raise ValueError("semantic check failed")

    with pytest.raises(RunIOError, match="semantic check failed") as error:
        publish_run(tmp_path / "run", run_data(examples, issues=(issue,)), validator=fail)
    diagnosis = error.value.diagnostic_path
    assert diagnosis is not None and diagnosis.is_dir()
    assert {path.name for path in diagnosis.iterdir()} == {"issues.jsonl", "rejected.jsonl", "failure.json"}
    assert "semantic check failed" in (diagnosis / "failure.json").read_text(encoding="utf-8")
    with pytest.raises(RunIOError, match="required files"):
        read_run(diagnosis)
    assert not (tmp_path / "run").exists()


def test_write_failure_publishes_only_diagnostics(tmp_path):
    target = write_failure(tmp_path / "failed", issues=(), rejected=(), error="invalid input")
    assert {path.name for path in target.iterdir()} == {"issues.jsonl", "rejected.jsonl", "failure.json"}
    assert not (target / "manifest.json").exists()
    assert (target / "issues.jsonl").read_bytes() == b""
    assert (target / "rejected.jsonl").read_bytes() == b""


@pytest.mark.parametrize("sentinel", [False, True])
def test_existing_empty_or_nonempty_output_is_never_overwritten(tmp_path, examples, sentinel):
    target = tmp_path / "existing"
    target.mkdir()
    if sentinel:
        (target / "keep.txt").write_text("keep", encoding="utf-8")
    before = {path.name: path.read_bytes() for path in target.iterdir()}

    with pytest.raises(FileExistsError):
        publish_run(target, run_data(examples), validator=lambda _: None)

    assert {path.name: path.read_bytes() for path in target.iterdir()} == before


def test_rename_race_does_not_replace_a_target_created_during_publish(tmp_path, examples, monkeypatch):
    target = tmp_path / "race"
    original_rename = run_io.os.rename

    def create_target_then_rename(source, destination):
        target.mkdir()
        (target / "keep.txt").write_text("raced", encoding="utf-8")
        return original_rename(source, destination)

    monkeypatch.setattr(run_io.os, "rename", create_target_then_rename)
    with pytest.raises(OSError):
        publish_run(target, run_data(examples), validator=lambda _: None)
    assert (target / "keep.txt").read_text(encoding="utf-8") == "raced"
    assert {path.name for path in target.iterdir()} == {"keep.txt"}


def test_read_run_rejects_links_that_escape_the_run(tmp_path, examples):
    target = publish_run(tmp_path / "run", run_data(examples), validator=lambda _: None)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.json").write_text("{}", encoding="utf-8")
    link = target / "escape"
    try:
        result = subprocess.run(
            ["cmd.exe", "/c", "mklink", "/J", str(link), str(outside)],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as error:
        pytest.skip(f"junction creation unavailable: {error}")
    if result.returncode != 0:
        pytest.skip(f"junction creation unavailable: {result.stderr or result.stdout}")
    with pytest.raises(RunIOError, match="symbolic link"):
        read_run(target)

