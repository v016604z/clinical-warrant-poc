"""Offline CLI acceptance for mixed sources, quarantine, duplicates, and stable merge."""

import hashlib
import json
from pathlib import Path

from clinical_warrant.interfaces.cli import main


ROOT = Path(__file__).parents[1]
CDC_ROOT = ROOT / "datasets" / "tw_cdc_hiv_qa"
AS_OF = "2026-11-22"
STALE_AFTER_DAYS = "10000"
CHUNK_FILES = (
    "documents.jsonl", "chunks.jsonl", "issues.jsonl", "rejected.jsonl", "reviews.jsonl",
)
RUN_FILES = (*CHUNK_FILES, "quality_report.json")


def _call_cli(args, capsys):
    status = main(args)
    captured = capsys.readouterr()
    assert status == 0, captured.err
    return json.loads(captured.out)


def _rights(*, decision="allowed", status="recorded"):
    return {
        "status": status,
        "statement": "Simulated policy for local pipeline tests only; not an external permission claim.",
        "policy_locators": [],
        "intended_use": "simulated_pipeline_test_only",
        "usage_decision": decision,
    }


def _write_generic_input(path: Path, *, record_id: str, locator: str, title: str, text: str) -> None:
    row = {
        "id": record_id, "title": title, "text": text,
        "source_name": "Project authored fixture", "source_url": locator,
        "updated_at": "2026-11-21", "category": "integration-test",
    }
    path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")


def _create_generic(tmp_path: Path, capsys, *, name: str, dataset_id: str, record_id: str,
                    locator: str, title: str, text: str, rights: dict | None = None) -> Path:
    input_path = tmp_path / f"{name}.jsonl"
    rights_path = tmp_path / f"{name}-rights.json"
    output = tmp_path / f"{name}-run"
    _write_generic_input(input_path, record_id=record_id, locator=locator, title=title, text=text)
    rights_path.write_text(json.dumps(rights or _rights(), ensure_ascii=False), encoding="utf-8")
    _call_cli([
        "kb", "build", "--adapter", "generic_jsonl", "--input", str(input_path),
        "--output-dir", str(output), "--dataset-id", dataset_id,
        "--attribution", "Project authored fixture", "--rights-config", str(rights_path),
        "--as-of", AS_OF, "--stale-after-days", STALE_AFTER_DAYS,
    ], capsys)
    return output


def _build_cdc(tmp_path: Path, capsys) -> Path:
    output = tmp_path / "cdc-run"
    _call_cli([
        "kb", "build", "--adapter", "cdc_qa", "--source-root", str(CDC_ROOT),
        "--input", str(CDC_ROOT / "qa.jsonl"), "--output-dir", str(output),
        "--intended-use", "simulated_pipeline_test_only", "--usage-decision", "allowed",
        "--as-of", AS_OF, "--stale-after-days", STALE_AFTER_DAYS,
    ], capsys)
    return output


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _validate_run(path: Path, capsys) -> None:
    result = _call_cli(["kb", "validate", "--dataset", str(path)], capsys)
    assert result == {"dataset": str(path.resolve()), "valid": True}


def test_cdc_and_project_authored_generic_merge_with_rights_quarantine(tmp_path, capsys):
    cdc_run = _build_cdc(tmp_path, capsys)
    cdc_report = json.loads((cdc_run / "quality_report.json").read_text(encoding="utf-8"))
    assert (cdc_report["input_count"], cdc_report["document_count"], cdc_report["ready_count"],
            cdc_report["needs_review_count"], cdc_report["chunk_count"]) == (119, 119, 118, 1, 118)
    generic_run = _create_generic(
        tmp_path, capsys, name="project", dataset_id="project_articles", record_id="manual-1",
        locator="fixture:project/manual-1", title="Project fixture", text="A project-authored answer.",
    )
    unknown_run = _create_generic(
        tmp_path, capsys, name="unknown", dataset_id="unknown_articles", record_id="unknown-1",
        locator="fixture:unknown/unknown-1", title="Unknown rights", text="This must be quarantined.",
        rights=_rights(decision="unknown", status="unknown"),
    )
    unknown_document, = _read_jsonl(unknown_run / "documents.jsonl")
    assert unknown_document["source"]["rights"]["usage_decision"] == "unknown"
    assert unknown_document["quality"]["status"] == "needs_review"
    assert _read_jsonl(unknown_run / "chunks.jsonl") == []
    merged = tmp_path / "mixed-run"
    _call_cli([
        "kb", "merge", "--inputs", str(cdc_run), str(generic_run), str(unknown_run),
        "--output-dir", str(merged),
    ], capsys)
    _validate_run(merged, capsys)

    report = json.loads((merged / "quality_report.json").read_text(encoding="utf-8"))
    assert report["input_count"] == report["input_document_count"] == 121
    assert report["input_chunk_count"] == 119
    assert report["input_ready_count"] == 119
    assert report["input_needs_review_count"] == 2
    assert report["input_excluded_count"] == 0
    assert report["document_count"] == report["ready_count"] == 119
    assert report["needs_review_count"] == report["excluded_count"] == 0
    assert report["rejected_count"] == report["duplicate_count"] == 0
    assert report["upstream_duplicate_count"] == 0
    assert report["chunk_count"] == 119
    assert report["quarantine_count"] == 2
    assert report["quarantine_reasons"] == {"needs_review": 1, "rights_not_approved": 1}
    assert report["source_counts"] == {"project_articles": 1, "tw_cdc_hiv_qa": 118}
    assert report["attachment_dependency_count"] == 0

    documents = _read_jsonl(merged / "documents.jsonl")
    chunks = _read_jsonl(merged / "chunks.jsonl")
    quarantined = report["quarantined_documents"]
    assert len(documents) == len(chunks) == 119
    assert {doc["source"]["dataset_id"] for doc in documents} == {"project_articles", "tw_cdc_hiv_qa"}
    assert all(doc["quality"]["status"] == "ready" for doc in documents)
    assert all(doc["source"]["rights"]["usage_decision"] == "allowed" for doc in documents)
    assert {item["reason"] for item in quarantined} == {"needs_review", "rights_not_approved"}
    assert all(item["document_id"] not in {doc["document_id"] for doc in documents} for item in quarantined)

    docs_by_id = {doc["document_id"]: doc for doc in documents}
    chunks_by_id: dict[str, list[dict]] = {}
    for chunk in chunks:
        chunks_by_id.setdefault(chunk["document_id"], []).append(chunk)
        doc = docs_by_id[chunk["document_id"]]
        assert chunk["document_version"] == doc["document_version"]
        assert chunk["source_locator"] == doc["source"]["source_locator"]
        assert chunk["text"] == doc["content_text"][chunk["char_start"]:chunk["char_end"]]
    assert set(chunks_by_id) == set(docs_by_id)
    assert all(chunks_by_id[document_id] for document_id in docs_by_id)

    manifest = json.loads((merged / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["complete"] is True
    assert manifest["operation"] == "merge"
    assert {item["type"] for item in manifest["adapter"]["inputs"]} >= {"cdc_qa", "generic_jsonl"}
    assert manifest["chunking_config"] == {
        "algorithm_version": "structure-v1", "max_chars": 1200, "overlap_chars": 100,
    }
    assert manifest["chunking_fingerprint"]
    assert manifest["quality_policy"]["input_run_policies"]
    assert {item["role"] for item in manifest["inputs"]} >= {
        "input", "rights", "source_manifest", "source_snapshot", "input_run_file",
    }
    assert set(manifest["output_hashes"]) == set(RUN_FILES)
    for name in RUN_FILES:
        assert hashlib.sha256((merged / name).read_bytes()).hexdigest() == manifest["output_hashes"][name]


def test_identical_content_from_different_datasets_is_preserved_and_merge_order_is_stable(
    tmp_path, capsys,
):
    shared = {"title": "Same source text", "text": "Identical normalized body across datasets."}
    alpha = _create_generic(
        tmp_path, capsys, name="alpha", dataset_id="source_alpha", record_id="alpha-1",
        locator="fixture:alpha/alpha-1", **shared,
    )
    alpha_repeat = _create_generic(
        tmp_path, capsys, name="alpha-repeat", dataset_id="source_alpha", record_id="alpha-1",
        locator="fixture:alpha/alpha-1", **shared,
    )
    beta = _create_generic(
        tmp_path, capsys, name="beta", dataset_id="source_beta", record_id="beta-1",
        locator="fixture:beta/beta-1", **shared,
    )

    for name in CHUNK_FILES:
        assert (alpha / name).read_bytes() == (alpha_repeat / name).read_bytes()
    assert (alpha / "quality_report.json").read_bytes() == (alpha_repeat / "quality_report.json").read_bytes()
    alpha_manifest = json.loads((alpha / "manifest.json").read_text(encoding="utf-8"))
    repeat_manifest = json.loads((alpha_repeat / "manifest.json").read_text(encoding="utf-8"))
    assert alpha_manifest["output_hashes"] == repeat_manifest["output_hashes"]

    forward = tmp_path / "forward-merge"
    reverse = tmp_path / "reverse-merge"
    _call_cli(["kb", "merge", "--inputs", str(alpha), str(beta), "--output-dir", str(forward)], capsys)
    _call_cli(["kb", "merge", "--inputs", str(beta), str(alpha), "--output-dir", str(reverse)], capsys)
    _validate_run(forward, capsys)
    _validate_run(reverse, capsys)

    forward_report_bytes = (forward / "quality_report.json").read_bytes()
    reverse_report_bytes = (reverse / "quality_report.json").read_bytes()
    assert forward_report_bytes == reverse_report_bytes
    for name in RUN_FILES:
        assert (forward / name).read_bytes() == (reverse / name).read_bytes()

    report = json.loads(forward_report_bytes)
    assert report["input_count"] == report["input_document_count"] == 2
    assert report["input_chunk_count"] == report["chunk_count"] == 2
    assert report["document_count"] == report["ready_count"] == 2
    assert report["duplicate_count"] == report["upstream_duplicate_count"] == 0
    assert report["quarantine_count"] == 0
    assert report["source_counts"] == {"source_alpha": 1, "source_beta": 1}
    assert report["cross_source_duplicate_group_count"] == 1
    assert report["cross_source_duplicate_document_count"] == 2
    group, = report["cross_source_duplicate_groups"]
    assert group["document_ids"] == ["source_alpha:alpha-1", "source_beta:beta-1"]

    documents = _read_jsonl(forward / "documents.jsonl")
    chunks = _read_jsonl(forward / "chunks.jsonl")
    assert len({doc["document_version"] for doc in documents}) == 1
    assert len({doc["document_id"] for doc in documents}) == 2
    assert {doc["source"]["source_locator"] for doc in documents} == {
        "fixture:alpha/alpha-1", "fixture:beta/beta-1",
    }
    assert {chunk["document_id"] for chunk in chunks} == {doc["document_id"] for doc in documents}
    assert {chunk["source_locator"] for chunk in chunks} == {
        "fixture:alpha/alpha-1", "fixture:beta/beta-1",
    }

    first_manifest = json.loads((forward / "manifest.json").read_text(encoding="utf-8"))
    second_manifest = json.loads((reverse / "manifest.json").read_text(encoding="utf-8"))
    stable_fields = (
        "schema_version", "pipeline_version", "operation", "adapter", "source_root", "inputs",
        "input_runs", "cleaning_config", "chunking_config", "chunking_fingerprint",
        "quality_policy", "strict", "output_hashes", "counts", "complete",
    )
    for field in stable_fields:
        assert first_manifest[field] == second_manifest[field], field
    for manifest in (first_manifest, second_manifest):
        manifest.pop("started_at_utc", None)
        manifest.pop("completed_at_utc", None)
    assert first_manifest == second_manifest
