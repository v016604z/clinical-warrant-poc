"""Offline end-to-end acceptance for the checked-in CDC source snapshot."""

import hashlib
import json
from pathlib import Path

from clinical_warrant.interfaces.cli import main
from clinical_warrant.modules.knowledge_base.infrastructure.adapters import CdcQaAdapter
from clinical_warrant.modules.knowledge_base.infrastructure.run_io import read_run


ROOT = Path(__file__).parents[1]
CDC_ROOT = ROOT / "src" / "clinical_warrant" / "data" / "tw_cdc_hiv_qa"


def _tree_hashes(root: Path) -> dict[str, str]:
    paths = [root / "qa.jsonl", root / "manifest.json", *sorted((root / "raw").rglob("*"))]
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in paths if path.is_file()
    }


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_checked_in_cdc_snapshot_build_validates_with_traceable_chunks(tmp_path):
    """Use explicit test-only rights approval; this does not assert real reuse permission."""
    source_hashes_before = _tree_hashes(CDC_ROOT)
    raw_records = _jsonl(CDC_ROOT / "qa.jsonl")
    source_manifest = json.loads((CDC_ROOT / "manifest.json").read_text(encoding="utf-8"))
    adapter = CdcQaAdapter(
        source_manifest, intended_use="e2e_test_only", usage_decision="allowed"
    )
    source_records = {record.source_record_id: record for record in map(adapter.adapt, raw_records)}
    output = tmp_path / "cdc-run"

    assert main([
        "kb", "build", "--adapter", "cdc_qa", "--source-root", str(CDC_ROOT),
        "--input", str(CDC_ROOT / "qa.jsonl"), "--output-dir", str(output),
        "--intended-use", "e2e_test_only", "--usage-decision", "allowed",
        "--as-of", "2026-11-22", "--stale-after-days", "10000",
    ]) == 0
    assert main(["kb", "validate", "--dataset", str(output)]) == 0

    run = read_run(output)
    report = run.quality_report
    documents = {document.source["source_record_id"]: document for document in run.documents}
    assert report["input_count"] == 119
    assert len(raw_records) == len(source_records) == len(documents) == 119
    assert len({record["id"] for record in raw_records}) == 119
    assert report["rejected_count"] == len(run.rejected) == 0
    assert report["duplicate_count"] == 0
    assert report["input_count"] == (
        report["document_count"] + report["rejected_count"] + report["duplicate_count"]
    )
    assert report["document_count"] == 119
    assert (report["ready_count"], report["needs_review_count"], report["excluded_count"]) == (118, 1, 0)

    raw_by_id = {record["id"]: record for record in raw_records}
    for source_id, document in documents.items():
        source = source_records[source_id]
        raw = raw_by_id[source_id]
        assert document.document_id == f"tw_cdc_hiv_qa:{source_id}"
        expected_source = {
            **source.to_dict()["provenance"], "dataset_id": source.dataset_id,
            "source_record_id": source_id,
        }
        assert document.to_dict()["source"] == expected_source
        assert document.to_dict()["metadata"] == source.to_dict()["metadata"]
        assert document.document_type == "faq"
        assert document.title == " ".join(source.title.split())
        assert document.source["source_locator"] == raw["source_url"]
        assert document.source["source_updated_at"] == raw["source_updated_at"]
        assert document.source["raw_content_sha256"] == raw["content_sha256"]
        assert document.source["raw_content_hash_basis"] == "cdc_qa_payload_v1"
        assert document.source["raw_snapshot"] == raw["raw_snapshot"]
        assert document.metadata["source_category"] == raw["category"]
        assert document.to_dict()["metadata"]["source_attachments"] == raw["attachments"]
        assert document.metadata["source_anchor"] == raw["source_anchor"]
        assert document.metadata["source_faq_id"] == raw["source_faq_id"]
        assert document.source["rights"]["intended_use"] == "e2e_test_only"
        assert document.source["rights"]["usage_decision"] == "allowed"

    attached = next(record for record in raw_records if record["attachments"])
    attached_document = documents[attached["id"]]
    assert attached_document.quality["status"] == "needs_review"
    assert "attachment_dependency" in attached_document.quality["flags"]
    assert "二者的比較請詳見下表" in attached_document.content_text
    assert attached_document.document_id not in {chunk.document_id for chunk in run.chunks}

    # Check visible source content directly for representative clinical numbers and lists.
    numeric_record = next(record for record in raw_records if "50-90%" in record["answer_text"])
    assert "50-90%" in documents[numeric_record["id"]].content_text
    list_records = [record for record in raw_records
                    if "<ol" in record["answer_html"].lower() or "<ul" in record["answer_html"].lower()]
    assert len(list_records) == 15
    list_record = next(record for record in list_records
                       if "至少進行1次" in record["answer_text"] and "每3至6個月" in record["answer_text"])
    list_document = documents[list_record["id"]]
    assert "至少進行1次" in list_document.content_text
    assert "每3至6個月" in list_document.content_text
    assert "1次愛滋篩檢" in list_document.content_text

    documents_by_id = {document.document_id: document for document in run.documents}
    chunks_by_document: dict[str, list] = {}
    for chunk in run.chunks:
        document = documents_by_id[chunk.document_id]
        chunk.validate_reference(document, run.manifest["chunking_config"])
        assert chunk.source_locator == document.source["source_locator"]
        assert chunk.metadata["dataset_id"] == document.source["dataset_id"]
        assert chunk.metadata["source_metadata"] == dict(document.metadata)
        assert chunk.text == document.content_text[chunk.char_start:chunk.char_end]
        assert chunk.char_end - chunk.char_start <= run.manifest["chunking_config"]["max_chars"]
        chunks_by_document.setdefault(chunk.document_id, []).append(chunk)
    for document in run.documents:
        chunks = chunks_by_document.get(document.document_id, [])
        if document.quality["status"] != "ready":
            assert chunks == []
            continue
        assert chunks
        assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
        assert chunks[0].char_start == 0
        assert chunks[-1].char_end == len(document.content_text)
        assert all(current.char_start <= previous.char_end
                   for previous, current in zip(chunks, chunks[1:]))
        assert all(current.char_start > previous.char_start
                   for previous, current in zip(chunks, chunks[1:]))

    manifest = run.manifest
    evidence = manifest["inputs"]
    assert {row["role"] for row in evidence} >= {
        "input", "source_manifest", "source_snapshot", "policy_snapshot"
    }
    for row in evidence:
        assert hashlib.sha256(Path(row["path"]).read_bytes()).hexdigest() == row["sha256"]
    for relative, digest in manifest["output_hashes"].items():
        assert hashlib.sha256((output / relative).read_bytes()).hexdigest() == digest

    assert _tree_hashes(CDC_ROOT) == source_hashes_before
