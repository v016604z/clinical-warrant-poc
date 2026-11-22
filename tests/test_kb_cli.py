"""Focused CLI input-envelope and configuration behavior checks."""

import json
from pathlib import Path
import shutil

from clinical_warrant.modules.knowledge_base.infrastructure.adapters import GenericJsonlAdapter
from clinical_warrant.modules.knowledge_base.infrastructure.input_reader import read_inputs
from clinical_warrant.modules.knowledge_base.infrastructure.adapters import CdcQaAdapter
from clinical_warrant.interfaces.cli import build_parser, main
from clinical_warrant.bootstrap.composition import _check_kb_output
import pytest


def _adapter():
    return GenericJsonlAdapter(
        dataset_id="fixture", attribution="Fixture publisher",
        rights={"status": "recorded", "statement": "fixture rights",
                 "policy_locators": [], "intended_use": "test", "usage_decision": "allowed"},
    )


def test_input_reader_preserves_line_envelopes_and_continues_after_bad_rows(tmp_path):
    path = tmp_path / "records.jsonl"
    good = {"id": "one", "title": "Title", "text": "Body",
            "source_name": "Fixture", "source_url": "fixture:one"}
    path.write_bytes((json.dumps(good) + "\n\n{" + "\n").encode() + b"\xff\n" +
                     (json.dumps({"id": "two", "title": "Title", "text": "Body",
                                  "source_name": "Fixture", "source_url": "fixture:two"}) + "\n").encode())

    rows = list(read_inputs(path, _adapter()))

    assert [row.line_number for row in rows] == [1, 2, 3, 4, 5]
    assert rows[0].source.source_record_id == "one"
    assert rows[1].error and rows[1].code == "invalid_json"
    assert rows[2].error and rows[2].code == "invalid_json"
    assert rows[3].code == "input_decode_error"
    assert rows[3].raw_record == {"raw_bytes_base64": "/wo="}
    assert rows[4].source.source_record_id == "two"
    assert all(row.input_locator == str(path) for row in rows)


def test_adapter_config_exposes_effective_defaults_and_overrides():
    adapter = _adapter()
    config = adapter.to_config()
    assert config["mapping"] == {
        "id": "id", "title": "title", "text": "text", "source_name": "source_name",
        "source_url": "source_url", "updated_at": "updated_at", "category": "category",
    }
    assert config["settings"]["document_type"] == "plain_text"
    assert config["settings"]["language"] == "und"


def test_input_reader_rejects_blank_duplicate_nonfinite_and_nonobject_rows(tmp_path):
    for raw in (b"\n", b"[]\n", b'{"x":NaN}\n', b'{"x":1,"x":2}\n'):
        source = tmp_path / "invalid.jsonl"
        source.write_bytes(raw)
        row, = read_inputs(source, _adapter())
        assert row.source is None and row.error and row.code == "invalid_json"

    source.write_text('{"id":"missing-fields"}\n', encoding="utf-8")
    row, = read_inputs(source, _adapter())
    assert row.source is None and row.error and row.code == "input_adaptation_error"


def test_cdc_adapter_config_records_explicit_use_and_policy_evidence():
    manifest = json.loads((Path(__file__).parents[1] /
                           "datasets/tw_cdc_hiv_qa/manifest.json").read_text(encoding="utf-8"))
    config = CdcQaAdapter(manifest, intended_use="local_test", usage_decision="unknown").to_config()
    assert config["type"] == "cdc_qa"
    assert config["settings"]["cleaning_profile"] == "cdc_faq_html_v1"
    assert config["rights"]["intended_use"] == "local_test"
    assert config["rights"]["usage_decision"] == "unknown"
    assert config["policy_provenance"] == manifest["policy_provenance"]


def test_kb_parser_requires_policy_dates_and_defaults_to_non_strict():
    parser = build_parser()
    args = parser.parse_args([
        "kb", "build", "--adapter", "cdc_qa", "--input", "qa.jsonl", "--output-dir", "run",
        "--source-root", "snapshot", "--intended-use", "test", "--usage-decision", "unknown",
        "--as-of", "2026-11-22", "--stale-after-days", "1095",
    ])
    assert args.strict is False
    assert args.max_chars == 1200 and args.overlap_chars == 100
    assert args.as_of == "2026-11-22"


def test_kb_merge_parser_accepts_multiple_input_runs():
    args = build_parser().parse_args([
        "kb", "merge", "--inputs", "run-a", "run-b", "--output-dir", "merged",
    ])
    assert args.inputs == ["run-a", "run-b"]
    assert args.strict is False


def test_output_guard_rejects_input_and_source_tree_targets_and_preserves_sentinel(tmp_path):
    source_root = tmp_path / "source"
    source_root.mkdir()
    input_file = source_root / "qa.jsonl"
    input_file.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError):
        _check_kb_output(source_root / "output", (input_file, source_root))
    with pytest.raises(ValueError):
        _check_kb_output(input_file, (input_file,))

    existing = tmp_path / "existing"
    existing.mkdir()
    sentinel = existing / "sentinel.txt"
    sentinel.write_text("keep", encoding="utf-8")
    with pytest.raises(FileExistsError):
        _check_kb_output(existing, (input_file,))
    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_generic_cli_build_validate_merge_and_strict_failure(tmp_path, capsys):
    rights = {"status": "recorded", "statement": "Fixture use", "policy_locators": [],
              "intended_use": "local validation", "usage_decision": "allowed"}
    rights_path = tmp_path / "rights.json"
    rights_path.write_text(json.dumps(rights), encoding="utf-8")
    input_path = tmp_path / "rows.jsonl"
    records = [
        {"id": "one", "title": "First", "text": "Body one.", "source_name": "Fixture",
         "source_url": "fixture:one", "updated_at": "2026-11-01"},
        "{not json",
        {"id": "two", "title": "Second", "text": "Body two.", "source_name": "Fixture",
         "source_url": "fixture:two", "updated_at": "2026-11-02"},
        {"id": "three", "title": "Missing locator", "text": "Body three.", "source_name": "Fixture"},
    ]
    input_path.write_text("\n".join(item if isinstance(item, str) else json.dumps(item) for item in records) + "\n",
                          encoding="utf-8")
    common = ["--adapter", "generic_jsonl", "--input", str(input_path), "--dataset-id", "fixture",
              "--attribution", "Fixture Publisher", "--rights-config", str(rights_path),
              "--as-of", "2026-11-22", "--stale-after-days", "1095"]
    run = tmp_path / "run"
    assert main(["kb", "build", *common, "--output-dir", str(run)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["counts"]["input_count"] == 4
    assert result["counts"]["document_count"] == 2
    assert result["counts"]["rejected_count"] == 2
    assert result["counts"]["missing_source_locator_count"] == 1
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    roles = {item["role"] for item in manifest["inputs"]}
    assert {"input", "rights"} <= roles
    assert manifest["adapter"]["mapping"]["text"] == "text"
    assert (run / "reviews.jsonl").read_bytes() == b""
    assert main(["kb", "validate", "--dataset", str(run)]) == 0
    capsys.readouterr()

    merged = tmp_path / "merged"
    assert main(["kb", "merge", "--inputs", str(run), "--output-dir", str(merged)]) == 0
    assert main(["kb", "validate", "--dataset", str(merged)]) == 0
    capsys.readouterr()

    tampered = tmp_path / "tampered"
    shutil.copytree(run, tampered)
    with (tampered / "chunks.jsonl").open("ab") as stream:
        stream.write(b"{}\n")
    assert main(["kb", "validate", "--dataset", str(tampered)]) == 2
    capsys.readouterr()

    strict_output = tmp_path / "strict-failure"
    assert main(["kb", "build", *common, "--output-dir", str(strict_output), "--strict"]) == 2
    capsys.readouterr()
    assert (strict_output / "failure.json").is_file()
    assert not (strict_output / "manifest.json").exists()


def test_offline_cdc_cli_build_and_validate(tmp_path, capsys):
    root = Path(__file__).parents[1] / "datasets" / "tw_cdc_hiv_qa"
    run = tmp_path / "cdc-run"
    assert main([
        "kb", "build", "--adapter", "cdc_qa", "--source-root", str(root),
        "--input", str(root / "qa.jsonl"), "--output-dir", str(run),
        "--intended-use", "local_reference", "--usage-decision", "allowed",
        "--as-of", "2026-11-22", "--stale-after-days", "1095",
    ]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["counts"]["input_count"] == 119
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["adapter"]["rights"]["usage_decision"] == "allowed"
    assert {item["role"] for item in manifest["inputs"]} >= {"input", "source_manifest", "source_snapshot"}
    assert result["counts"]["ready_count"] > 0 and result["counts"]["chunk_count"] > 0
    assert main(["kb", "validate", "--dataset", str(run)]) == 0
    capsys.readouterr()


def test_cdc_snapshot_hash_mismatch_is_rejected_with_diagnostics(tmp_path, capsys):
    original = Path(__file__).parents[1] / "datasets" / "tw_cdc_hiv_qa"
    source_root = tmp_path / "cdc-source"
    shutil.copytree(original, source_root)
    manifest = json.loads((source_root / "manifest.json").read_text(encoding="utf-8"))
    snapshot = next(item["raw_snapshot"] for item in manifest["pages"] if item.get("raw_snapshot"))
    with (source_root / snapshot).open("ab") as stream:
        stream.write(b"tampered")
    output = tmp_path / "broken-run"
    assert main([
        "kb", "build", "--adapter", "cdc_qa", "--source-root", str(source_root),
        "--input", str(source_root / "qa.jsonl"), "--output-dir", str(output),
        "--intended-use", "local_reference", "--usage-decision", "unknown",
        "--as-of", "2026-11-22", "--stale-after-days", "1095",
    ]) == 2
    assert "diagnostics:" in capsys.readouterr().err
    failure = json.loads((output / "failure.json").read_text(encoding="utf-8"))
    assert "hash mismatch" in failure["error"]
    assert not (output / "manifest.json").exists()
