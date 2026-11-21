"""Executable schema examples and boundaries at the KB domain interface."""

from copy import deepcopy
from dataclasses import FrozenInstanceError
import hashlib
import json
from pathlib import Path
import re

import pytest

from clinical_warrant.modules.knowledge_base import (
    KnowledgeBaseValidationError,
    KnowledgeChunk,
    KnowledgeDocument,
    SourceRecord,
    canonical_json_bytes,
    canonical_sha256,
    chunk_id_for,
    chunking_fingerprint,
    document_version_for,
    parse_json_object,
)


@pytest.fixture(scope="module")
def examples():
    text = (Path(__file__).parents[1] / "docs" / "rag-kb-schema.md").read_text(encoding="utf-8")
    return {
        name: json.loads(body)
        for name, body in re.findall(r"<!-- example: (\w+) -->\n```json\n(.*?)\n```", text, re.S)
    }


@pytest.mark.parametrize("name,model", [("source_record", SourceRecord), ("document", KnowledgeDocument), ("chunk", KnowledgeChunk)])
def test_schema_examples_round_trip_without_content_changes(examples, name, model):
    payload = examples[name]
    instance = model.from_dict(payload)
    assert instance.to_dict() == payload
    assert model.from_json(instance.to_json()) == instance


def test_schema_hashes_offsets_and_citation_are_exact(examples):
    document = KnowledgeDocument.from_dict(examples["document"])
    chunk = KnowledgeChunk.from_dict(examples["chunk"])
    config = examples["chunking"]["config"]
    assert document_version_for(document.to_dict()) == document.document_version
    assert chunking_fingerprint(config) == examples["chunking"]["fingerprint"]
    assert chunk_id_for(chunk.to_dict(), config) == chunk.chunk_id
    assert chunk.text == document.content_text[0:5]
    chunk.validate_reference(document, config)
    assert canonical_json_bytes({"乙": 2, "甲": [True, None]}) == '{"乙":2,"甲":[true,null]}'.encode("utf-8")


@pytest.mark.parametrize("text,path", [
    ('{"nested":{"x":1,"x":2}}', "$.nested.x"),
    ('{"nested":[NaN]}', "$.nested[0]"),
    ('{"n":Infinity}', "$.n"),
    ('{"n":-Infinity}', "$.n"),
    ('{"nested":{"bad":"\\ud800"}}', "$.nested.bad"),
    ('{"nested":{"bad":"\\u0000"}}', "$.nested.bad"),
    ('\ufeff{"x":1}', "$"),
    ('[]', "$"),
    ('{"x":', "$"),
    ('{"n":1e999}', "$.n"),
])
def test_json_parser_rejects_nonstandard_or_unrepresentable_json(text, path):
    with pytest.raises(KnowledgeBaseValidationError) as caught:
        parse_json_object(text)
    assert path in str(caught.value)


def test_source_defaults_are_only_for_missing_optional_fields(examples):
    payload = deepcopy(examples["source_record"])
    for key in ("language", "cleaning_profile", "metadata", "attachments"):
        del payload[key]
    source = SourceRecord.from_dict(payload)
    assert source.language == "und"
    assert source.cleaning_profile == "plain_v1"
    assert source.to_dict()["metadata"] == {}
    assert source.to_dict()["attachments"] == []
    assert source.provenance["collected_at_utc"] is None


@pytest.mark.parametrize("field,value", [
    ("schema_version", 1), ("schema_version", "2.0"),
    ("dataset_id", "space:collision"), ("dataset_id", "UPPER"),
    ("source_record_id", "\tbad"), ("source_record_id", " "),
    ("document_type", "new_type"), ("title", ""), ("content", []),
    ("language", None), ("metadata", None), ("metadata", {"bad": float("nan")}),
    ("metadata", {"bad": object()}), ("metadata", {1: "not a JSON key"}),
    ("metadata", {"nested": {"bad": "\ud800"}}),
    ("attachments", None), ("cleaning_profile", "unknown"),
    ("cleaning_profile", "html_v1"),
])
def test_source_rejects_invalid_fields_with_a_field_path(examples, field, value):
    payload = deepcopy(examples["source_record"])
    payload[field] = value
    with pytest.raises(KnowledgeBaseValidationError) as caught:
        SourceRecord.from_dict(payload)
    assert field in str(caught.value)


@pytest.mark.parametrize("field,value", [
    ("source_updated_at", "2026-02-30"), ("source_updated_at", "2026-1-1"),
    ("collected_at_utc", "2026-11-21T01:00:00+00:00"),
    ("collected_at_utc", "2026-11-21T25:00:00Z"),
    ("publisher", " "), ("source_locator", None),
    ("raw_content_sha256", "a" * 64), ("raw_content_sha256", "F" * 64),
    ("raw_content_hash_basis", "unknown"),
    ("rights", {"status": "recorded"}),
])
def test_provenance_requires_real_dates_and_explicit_evidence(examples, field, value):
    payload = deepcopy(examples["source_record"])
    payload["provenance"][field] = value
    with pytest.raises(KnowledgeBaseValidationError) as caught:
        SourceRecord.from_dict(payload)
    assert "provenance" in str(caught.value)


@pytest.mark.parametrize("path", ["../secret.html", "/raw/file", "C:/raw/file", "raw\\file", "raw/../file", "raw//file", "raw/./file"])
def test_snapshot_paths_cannot_escape_or_ambiguously_name_source_root(examples, path):
    payload = deepcopy(examples["source_record"])
    payload["provenance"].update(raw_snapshot=path, raw_snapshot_sha256="a" * 64)
    with pytest.raises(KnowledgeBaseValidationError, match="raw_snapshot"):
        SourceRecord.from_dict(payload)


def test_snapshot_pair_validates_shape_without_reading_a_file(examples):
    payload = deepcopy(examples["source_record"])
    payload["provenance"]["raw_snapshot"] = "raw/not-read.html"
    with pytest.raises(KnowledgeBaseValidationError, match="both"):
        SourceRecord.from_dict(payload)
    payload["provenance"]["raw_snapshot_sha256"] = "a" * 64
    assert SourceRecord.from_dict(payload).provenance["raw_snapshot"] == "raw/not-read.html"


def test_cdc_payload_hash_uses_original_question_newline_and_html(examples):
    payload = deepcopy(examples["source_record"])
    payload.update(document_type="faq", content_type="text/html", cleaning_profile="cdc_faq_html_v1", content="<p>回答</p>\r\n")
    payload["provenance"].update(raw_content_hash_basis="cdc_qa_payload_v1", raw_content_sha256=hashlib.sha256((payload["title"] + "\n" + payload["content"]).encode()).hexdigest())
    source = SourceRecord.from_dict(payload)
    assert source.content.endswith("\r\n")
    payload["content"] = payload["content"].replace("\r\n", "\n")
    with pytest.raises(KnowledgeBaseValidationError, match="payload"):
        SourceRecord.from_dict(payload)


def test_nested_data_is_immutable_and_does_not_alias_input_or_output(examples):
    payload = deepcopy(examples["source_record"])
    payload["metadata"]["nested"] = {"items": ["original"]}
    source = SourceRecord.from_dict(payload)
    payload["metadata"]["nested"]["items"].append("mutation")
    assert source.to_dict()["metadata"]["nested"]["items"] == ["original"]
    exported = source.to_dict()
    exported["provenance"]["rights"]["usage_decision"] = "prohibited"
    assert source.provenance["rights"]["usage_decision"] == "allowed"
    with pytest.raises(TypeError):
        source.metadata["nested"]["other"] = "mutation"
    with pytest.raises(FrozenInstanceError):
        source.title = "mutation"


def test_unknown_fields_and_missing_fields_fail_without_silent_discard(examples):
    payload = deepcopy(examples["source_record"])
    payload["misspelled"] = 1
    with pytest.raises(KnowledgeBaseValidationError, match="misspelled"):
        SourceRecord.from_dict(payload)
    del payload["misspelled"]
    del payload["provenance"]["rights"]["intended_use"]
    with pytest.raises(KnowledgeBaseValidationError, match="intended_use"):
        SourceRecord.from_dict(payload)


def test_cyclic_python_metadata_is_a_contract_error(examples):
    payload = deepcopy(examples["source_record"])
    payload["metadata"]["cycle"] = payload["metadata"]
    with pytest.raises(KnowledgeBaseValidationError, match="cyclic or too deep"):
        SourceRecord.from_dict(payload)


@pytest.mark.parametrize("kind,text", [
    ("article", "沒有標題前綴的正文"), ("article", "示例\n   "),
    ("faq", "示例\n正文"), ("faq", "問題：示例\n回答："),
])
def test_document_format_rejects_missing_title_or_empty_body_even_with_valid_hash(examples, kind, text):
    payload = deepcopy(examples["document"])
    payload.update(document_type=kind, content_text=text)
    payload["document_version"] = document_version_for(payload)
    with pytest.raises(KnowledgeBaseValidationError, match="content_text"):
        KnowledgeDocument.from_dict(payload)


def test_document_version_tracks_content_but_excludes_evidence_and_reviews(examples):
    payload = deepcopy(examples["document"])
    original = payload["document_version"]
    payload["source"]["collected_at_utc"] = "2026-11-21T00:00:00Z"
    payload["metadata"]["extra"] = {"score": 0.5}
    assert document_version_for(payload) == original
    assert KnowledgeDocument.from_dict(payload).document_version == original
    payload["content_text"] += "新段落"
    with pytest.raises(KnowledgeBaseValidationError, match="document_version"):
        KnowledgeDocument.from_dict(payload)
    payload["document_version"] = document_version_for(payload)
    assert payload["document_version"] != original
    KnowledgeDocument.from_dict(payload)


@pytest.mark.parametrize("decision,status,flag", [("unknown", "needs_review", "rights_unknown"), ("prohibited", "excluded", "rights_prohibited")])
def test_rights_gate_cannot_be_bypassed_by_recorded_status(examples, decision, status, flag):
    payload = deepcopy(examples["document"])
    payload["source"]["rights"]["usage_decision"] = decision
    with pytest.raises(KnowledgeBaseValidationError, match="quality"):
        KnowledgeDocument.from_dict(payload)
    payload["quality"].update(status=status, flags=[flag])
    KnowledgeDocument.from_dict(payload)


def test_reviews_bind_content_source_use_and_current_decision(examples):
    payload = deepcopy(examples["document"])
    payload["quality"].update(review_status="approved", review_ref="reviews/fixture.json")
    document = KnowledgeDocument.from_dict(payload)
    review = {"document_id": document.document_id, "document_version": document.document_version,
              "source_fingerprint": canonical_sha256(document.source), "flags": [], "decision": "approved",
              "reviewer": "fixture-reviewer", "reviewed_at_utc": "2026-11-21T00:00:00Z", "reason": "fixture validation"}
    document.validate_review(review)
    payload["source"]["rights"]["intended_use"] = "changed-purpose"
    changed = KnowledgeDocument.from_dict(payload)
    assert changed.document_version == document.document_version
    with pytest.raises(KnowledgeBaseValidationError, match="source_fingerprint"):
        changed.validate_review(review)
    payload["quality"]["flags"] = ["attachment_dependency"]
    changed = KnowledgeDocument.from_dict(payload)
    review["source_fingerprint"] = canonical_sha256(changed.source)
    with pytest.raises(KnowledgeBaseValidationError, match="review.flags"):
        changed.validate_review(review)


@pytest.mark.parametrize("field", ["chunk_index", "char_start", "char_end"])
def test_chunk_integer_fields_reject_boolean(examples, field):
    payload = deepcopy(examples["chunk"])
    payload[field] = True
    with pytest.raises(KnowledgeBaseValidationError, match=field):
        KnowledgeChunk.from_dict(payload)


@pytest.mark.parametrize("field,value", [("max_chars", True), ("max_chars", 0), ("overlap_chars", -1), ("overlap_chars", 1200), ("algorithm_version", "unknown")])
def test_effective_chunking_configuration_is_validated(examples, field, value):
    config = deepcopy(examples["chunking"]["config"])
    config[field] = value
    with pytest.raises(KnowledgeBaseValidationError, match=field):
        chunking_fingerprint(config)


def test_chunk_reference_validation_checks_text_citation_metadata_and_config(examples):
    document = KnowledgeDocument.from_dict(examples["document"])
    original = examples["chunk"]
    config = examples["chunking"]["config"]
    for key, value, expected in [("text", "abcde", "text"), ("source_locator", "fixture:other", "source_locator"), ("chunk_id", "chunk:" + "a" * 64, "chunk_id")]:
        payload = deepcopy(original)
        payload[key] = value
        with pytest.raises(KnowledgeBaseValidationError, match=expected):
            KnowledgeChunk.from_dict(payload).validate_reference(document, config)
    payload = deepcopy(original)
    payload["metadata"]["language"] = "und"
    with pytest.raises(KnowledgeBaseValidationError, match="metadata.language"):
        KnowledgeChunk.from_dict(payload).validate_reference(document, config)
    changed = deepcopy(examples["document"])
    changed["quality"].update(status="needs_review", flags=["staleness_review"])
    with pytest.raises(KnowledgeBaseValidationError, match="eligible"):
        KnowledgeChunk.from_dict(original).validate_reference(KnowledgeDocument.from_dict(changed), config)


def test_non_bmp_offsets_count_code_points_instead_of_utf16_or_bytes(examples):
    payload = deepcopy(examples["document"])
    payload.update(title="a", content_text="a\n😀")
    payload["document_version"] = document_version_for(payload)
    document = KnowledgeDocument.from_dict(payload)
    chunk = deepcopy(examples["chunk"])
    chunk.update(document_version=document.document_version, text=document.content_text, char_end=3)
    chunk["chunk_id"] = chunk_id_for(chunk, examples["chunking"]["config"])
    KnowledgeChunk.from_dict(chunk).validate_reference(document, examples["chunking"]["config"])
    assert len(document.content_text.encode("utf-8")) == 6
