"""Offline source mapping checks; raw snapshots are not verified in this stage."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from clinical_warrant.modules.knowledge_base.infrastructure.adapters import (
    CdcQaAdapter,
    GenericJsonlAdapter,
)
from clinical_warrant.modules.knowledge_base.domain.contracts import KnowledgeBaseValidationError


ROOT = Path(__file__).parents[1]
CDC_ROOT = ROOT / "src" / "clinical_warrant" / "data" / "tw_cdc_hiv_qa"
FIXTURE = Path(__file__).parent / "fixtures" / "kb_generic.jsonl"


@pytest.fixture
def rights():
    return {
        "status": "recorded", "statement": "Project-authored nonmedical fixture.",
        "policy_locators": [], "intended_use": "fixture_validation", "usage_decision": "allowed",
    }


@pytest.fixture
def generic_record():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture
def manifest():
    return json.loads((CDC_ROOT / "manifest.json").read_text(encoding="utf-8"))


@pytest.fixture
def cdc_record():
    return json.loads((CDC_ROOT / "qa.jsonl").read_text(encoding="utf-8").splitlines()[0])


def generic(rights, **settings):
    return GenericJsonlAdapter(dataset_id="example_articles", attribution="Example Publisher",
                              rights=rights, **settings)


def cdc(manifest, **settings):
    return CdcQaAdapter(manifest, intended_use="fixture_validation",
                        usage_decision="unknown", **settings)


def test_generic_fixture_preserves_text_and_has_no_faq_requirement(rights):
    records = list(generic(rights).read_jsonl(FIXTURE))
    assert len(records) == 1
    mapped = records[0].to_dict()
    assert mapped["source_record_id"] == "article-001"
    assert mapped["document_type"] == "plain_text"
    assert mapped["language"] == "und"
    assert mapped["title"] == "示例" and mapped["content"] == "甲乙"
    assert mapped["provenance"]["raw_content_sha256"] == hashlib.sha256("甲乙".encode()).hexdigest()
    assert mapped["provenance"]["raw_content_hash_basis"] == "text_utf8_v1"
    assert mapped["provenance"]["raw_snapshot"] is None
    assert mapped["provenance"]["collected_at_utc"] is None
    assert mapped["provenance"]["rights"] == rights


def test_generic_custom_mapping_and_unused_fields_cannot_shadow_core(rights):
    raw = {"uid": "a:1", "heading": " 原標題 ", "body": "\r\n本文\t甲乙 ",
           "author": "Fixture", "locator": "file:manual#page=2", "day": None,
           "group": "Manual", "title": "unused original key", "provenance": {"original": True},
           "extra": [1, {"preserved": "yes"}]}
    mapping = dict(zip(("id", "title", "text", "source_name", "source_url", "updated_at", "category"),
                       ("uid", "heading", "body", "author", "locator", "day", "group")))
    mapped = generic(rights, mapping=mapping, language="zh-Hant").adapt(raw).to_dict()
    assert mapped["source_record_id"] == "a:1"
    assert mapped["title"] == raw["heading"] and mapped["content"] == raw["body"]
    assert mapped["provenance"]["source_locator"] == raw["locator"]
    assert mapped["metadata"] == {"source_category": "Manual", "source_fields": {
        "title": raw["title"], "provenance": raw["provenance"], "extra": raw["extra"]}}


def test_generic_optional_fields_and_partial_mapping_defaults(rights, generic_record):
    generic_record["uid"] = generic_record.pop("id")
    del generic_record["updated_at"]
    del generic_record["category"]
    result = generic(rights, mapping={"id": "uid"}).adapt(generic_record).to_dict()
    assert result["source_record_id"] == "article-001"
    assert result["provenance"]["source_updated_at"] is None
    assert result["metadata"] == {}


def test_generic_html_requires_explicit_compatible_profile(rights, generic_record):
    with pytest.raises(KnowledgeBaseValidationError):
        generic(rights, content_type="text/html")
    generic_record["text"] = "<p>未清洗</p>"
    mapped = generic(rights, content_type="text/html", cleaning_profile="html_v1").adapt(generic_record)
    assert mapped.to_dict()["content"] == "<p>未清洗</p>"


@pytest.mark.parametrize("mapping", [[], {"unknown": "x"}, {"id": "title"}, {"id": None},
                                     {"id": ""}, {"id": "\x00"}, {"id": "\ud800"}])
def test_bad_mapping_configuration_has_clear_error(rights, mapping):
    with pytest.raises(KnowledgeBaseValidationError, match="mapping"):
        generic(rights, mapping=mapping)


@pytest.mark.parametrize("settings", [
    {"document_type": "other"}, {"language": None}, {"cleaning_profile": "guess"},
    {"collected_at_utc": "2026-11-21T00:00:00+08:00"},
])
def test_invalid_generic_settings_fail_at_construction(rights, settings):
    with pytest.raises(KnowledgeBaseValidationError):
        generic(rights, **settings)


def test_unknown_or_prohibited_rights_are_preserved_without_assuming_permission(rights, generic_record):
    for decision in ("unknown", "prohibited"):
        rights["usage_decision"] = decision
        result = generic(rights).adapt(generic_record).to_dict()
        assert result["provenance"]["rights"]["usage_decision"] == decision
    del rights["intended_use"]
    with pytest.raises(KnowledgeBaseValidationError):
        generic(rights)


@pytest.mark.parametrize("field,value", [("id", None), ("text", " "), ("title", []),
                                        ("source_name", ""), ("source_url", None),
                                        ("updated_at", "2026-02-30")])
def test_generic_bad_source_records_are_rejected(rights, generic_record, field, value):
    generic_record[field] = value
    with pytest.raises(KnowledgeBaseValidationError):
        generic(rights).adapt(generic_record)


@pytest.mark.parametrize("bad", [b"\n", b"[]\n", b"not-json\n", b"{\"x\":NaN}\n",
                                    b"{\"x\":Infinity}\n", b"{\"x\":1,\"x\":2}\n",
                                    b"{\"x\":\"\\ud800\"}\n", b"\xff\n",
                                    b"\xef\xbb\xbf{}\n", b"{}\n"])
def test_jsonl_reports_path_and_line_without_skipping_bad_records(rights, tmp_path, bad):
    source = tmp_path / "bad.jsonl"
    source.write_bytes(FIXTURE.read_bytes() + bad)
    records = generic(rights).read_jsonl(source)
    assert next(records).to_dict()["source_record_id"] == "article-001"
    with pytest.raises(KnowledgeBaseValidationError, match="line 2") as error:
        next(records)
    assert str(source) in str(error.value)


def test_missing_input_file_is_a_validation_error(rights, tmp_path):
    with pytest.raises(KnowledgeBaseValidationError, match="cannot read JSONL"):
        list(generic(rights).read_jsonl(tmp_path / "absent.jsonl"))


def test_all_119_cdc_records_map_without_mutating_sources_or_verifying_snapshots(manifest):
    paths = [CDC_ROOT / "qa.jsonl", CDC_ROOT / "manifest.json"]
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    originals = [json.loads(line) for line in paths[0].read_text(encoding="utf-8").splitlines()]
    mapped = [record.to_dict() for record in cdc(manifest).read_jsonl(paths[0])]
    assert len(mapped) == len(originals) == 119
    assert len({row["source_record_id"] for row in mapped}) == 119
    snapshots = {(p["url"], p["raw_snapshot"]): p["html_sha256"] for p in manifest["pages"]}
    for raw, row in zip(originals, mapped):
        assert row["source_record_id"] == raw["id"] and row["dataset_id"] == "tw_cdc_hiv_qa"
        assert row["title"] == raw["question"] and row["content"] == raw["answer_html"]
        assert row["document_type"] == "faq" and row["content_type"] == "text/html"
        provenance = row["provenance"]
        for source, target in [("source_url", "source_locator"), ("source_updated_at", "source_updated_at"),
                               ("collected_at_utc", "collected_at_utc"),
                               ("content_sha256", "raw_content_sha256"), ("raw_snapshot", "raw_snapshot")]:
            assert provenance[target] == raw[source]
        assert provenance["raw_content_hash_basis"] == "cdc_qa_payload_v1"
        assert provenance["raw_snapshot_sha256"] == snapshots[(raw["page_url"], raw["raw_snapshot"])]
        assert provenance["attribution"] == manifest["attribution"]
        assert provenance["rights"]["policy_locators"] == sorted(manifest["reuse_policy_urls"])
        assert provenance["rights"]["usage_decision"] == "unknown"
        for key in ("page_url", "source_anchor", "source_faq_id", "answer_text"):
            assert row["metadata"][key] == raw[key]
        assert row["metadata"]["source_category"] == raw["category"]
        assert row["metadata"]["source_attachments"] == raw["attachments"]
        assert row["metadata"]["policy_provenance"] == manifest["policy_provenance"]
        assert row["attachments"] == [{"locator": a["url"], "title": a["label"],
                                        "media_type": None, "included": False} for a in raw["attachments"]]
    assert all(hashlib.sha256(p.read_bytes()).hexdigest() == digest for p, digest in before.items())


def test_cdc_extra_fields_and_attachment_metadata_are_not_lost(manifest, cdc_record):
    cdc_record["extra"] = {"original": [1, 2]}
    cdc_record["attachments"] = [{"url": "fixture:attachment", "label": "Attachment", "extra": 3}]
    result = cdc(manifest).adapt(cdc_record).to_dict()
    assert result["metadata"]["source_fields"] == {"extra": cdc_record["extra"]}
    assert result["metadata"]["source_attachments"] == cdc_record["attachments"]
    assert result["attachments"][0]["included"] is False


@pytest.mark.parametrize("change", ["payload", "hash", "snapshot", "attachment", "label"])
def test_cdc_invalid_payload_or_snapshot_mapping_is_rejected(manifest, cdc_record, change):
    if change == "payload":
        cdc_record["answer_html"] += "changed"
    elif change == "hash":
        cdc_record["content_sha256"] = "0" * 64
    elif change == "snapshot":
        cdc_record["raw_snapshot"] = "raw/absent.html"
    elif change == "attachment":
        cdc_record["attachments"] = [None]
    else:
        cdc_record["attachments"] = [{"url": "fixture:attachment", "label": {}}]
    with pytest.raises(KnowledgeBaseValidationError):
        cdc(manifest).adapt(cdc_record)


@pytest.mark.parametrize("change", ["object", "pages", "policy", "evidence", "attribution", "hash", "path"])
def test_invalid_manifest_settings_have_validation_errors(manifest, change):
    if change == "object":
        manifest = []
    elif change == "pages":
        manifest["pages"] = None
    elif change == "policy":
        manifest["reuse_policy_urls"] = [None]
    elif change == "evidence":
        manifest["policy_provenance"] = [None]
    elif change == "attribution":
        manifest["attribution"] = None
    elif change == "hash":
        manifest["pages"][0]["html_sha256"] = "invalid"
    else:
        manifest["pages"][0]["raw_snapshot"] = "../escape.html"
    with pytest.raises(KnowledgeBaseValidationError):
        cdc(manifest)


@pytest.mark.parametrize("change_url", [False, True])
def test_conflicting_manifest_snapshot_hashes_are_rejected(manifest, change_url):
    duplicate = deepcopy(manifest["pages"][0])
    if change_url:
        duplicate["url"] = "fixture:another-page"
    duplicate["html_sha256"] = "f" * 64
    manifest["pages"].append(duplicate)
    with pytest.raises(KnowledgeBaseValidationError, match="conflicting"):
        cdc(manifest)
