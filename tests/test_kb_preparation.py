"""Document quality and provenance checks, without a run or snapshot I/O."""

from dataclasses import FrozenInstanceError
import hashlib
import json
from pathlib import Path

import pytest

from clinical_warrant.modules.knowledge_base import (
    CdcQaAdapter,
    CleanedContent,
    GenericJsonlAdapter,
    KnowledgeBaseValidationError,
    PreparationResult,
    QualityIssue,
    QualityPolicy,
    SourceRecord,
    document_version_for,
    prepare_document,
)


ROOT = Path(__file__).parents[1]


@pytest.fixture
def source():
    return GenericJsonlAdapter(
        dataset_id="fixture", attribution="Project fixture",
        rights={"status": "recorded", "statement": "Project-authored nonmedical test.",
                "policy_locators": [], "intended_use": "fixture_validation", "usage_decision": "allowed"},
    ).adapt({"id": "one", "title": "標題", "text": "甲乙正文", "source_name": "Fixture Publisher",
             "source_url": "fixture:one", "updated_at": "2026-11-01", "category": "測試",
             "original_extra": ["unchanged"]})


@pytest.fixture
def policy():
    return QualityPolicy(as_of="2026-11-22", stale_after_days=1095)


def identity_cleaner(record):
    return CleanedContent(record.title, record.content, (), "fixture-clean-v1")


def altered(source, **changes):
    payload = source.to_dict()
    payload.update(changes)
    raw = payload["title"] + "\n" + payload["content"] if payload["provenance"]["raw_content_hash_basis"] == "cdc_qa_payload_v1" else payload["content"]
    payload["provenance"]["raw_content_sha256"] = hashlib.sha256(raw.encode()).hexdigest()
    return SourceRecord.from_dict(payload)


def prepare(source, policy, **kwargs):
    return prepare_document(source, cleaner=identity_cleaner, policy=policy, **kwargs)


def test_plain_document_preserves_identity_raw_hash_evidence_and_metadata(source, policy):
    original = source.to_dict()
    result = prepare(source, policy)
    document = result.document
    assert document is not None
    assert document.document_id == "fixture:one"
    assert document.content_text == "標題\n甲乙正文"
    assert document.source == dict(source.provenance, dataset_id="fixture", source_record_id="one")
    assert document.to_dict()["metadata"] == original["metadata"]
    assert document.document_version == document_version_for(document.to_dict())
    assert document.quality == {"status": "ready", "flags": (), "review_status": "unreviewed", "review_ref": None}
    assert result.cleaning_version == "fixture-clean-v1" and result.quality_version == "quality-v1"
    assert result.issues == () and source.to_dict() == original


def test_faq_document_builds_question_answer_wrapper_once(source, policy):
    source = altered(source, document_type="faq")
    result = prepare(source, policy)
    assert result.document.content_text == "問題：標題\n回答：甲乙正文"


@pytest.mark.parametrize("decision,status,flag", [("unknown", "needs_review", "rights_unknown"),
                                                 ("prohibited", "excluded", "rights_prohibited")])
def test_usage_decision_controls_readiness_and_cannot_default_to_allowed(source, policy, decision, status, flag):
    payload = source.to_dict()
    payload["provenance"]["rights"]["usage_decision"] = decision
    result = prepare(SourceRecord.from_dict(payload), policy)
    assert result.document.quality["status"] == status
    assert flag in result.document.quality["flags"]
    assert result.document.quality["review_status"] == "unreviewed"
    assert any(issue.code == flag for issue in result.issues)


def test_unknown_rights_evidence_cannot_be_overridden_by_allowed_decision(source, policy):
    payload = source.to_dict()
    payload["provenance"]["rights"]["status"] = "unknown"
    result = prepare(SourceRecord.from_dict(payload), policy)
    assert result.document.quality["status"] == "needs_review"


@pytest.mark.parametrize("body,included,blocked", [
    ("二者的比較請詳見下表", False, True), ("詳見附件。", False, True),
    ("See the attachment for the comparison.", False, True),
    ("二者的比較請詳見下表", True, False), ("正文完整，另有附件供延伸閱讀。", False, False),
])
def test_attachment_dependency_requires_reference_and_missing_content(source, policy, body, included, blocked):
    source = altered(source, content=body, attachments=[{"locator": "fixture:attachment", "title": "比較表",
                                                      "media_type": None, "included": included}])
    result = prepare(source, policy)
    assert ("attachment_dependency" in result.document.quality["flags"]) is blocked
    assert result.document.quality["status"] == ("needs_review" if blocked else "ready")
    assert body in result.document.content_text


def test_explicit_attachment_reference_is_not_ready_when_link_metadata_is_missing(source, policy):
    missing = prepare(altered(source, content="詳見附件。", attachments=[]), policy)
    assert missing.document.quality["status"] == "needs_review"
    assert "attachment_dependency" in missing.document.quality["flags"]
    inline = prepare(altered(source, content="詳見下表：\n甲：1\n乙：2", attachments=[]), policy)
    assert "attachment_dependency" not in inline.document.quality["flags"]


def test_old_dates_add_hints_but_do_not_rewrite_or_exclude_text(source, policy):
    payload = source.to_dict()
    payload["provenance"]["source_updated_at"] = "2019-01-01"
    result = prepare(SourceRecord.from_dict(payload), policy)
    assert result.document.quality["status"] == "ready"
    assert "staleness_review" in result.document.quality["flags"]
    assert result.document.content_text == "標題\n甲乙正文"
    assert result.document.source["source_updated_at"] == "2019-01-01"
    payload["provenance"]["source_updated_at"] = None
    missing = prepare(SourceRecord.from_dict(payload), policy)
    assert missing.document.source["source_updated_at"] is None
    assert "source_date_missing" in missing.document.quality["flags"]


def test_staleness_uses_only_explicit_reference_date_and_threshold(source):
    recent = prepare(source, QualityPolicy(as_of="2026-11-22", stale_after_days=21))
    older = prepare(source, QualityPolicy(as_of="2026-11-23", stale_after_days=21))
    assert "staleness_review" not in recent.document.quality["flags"]
    assert "staleness_review" in older.document.quality["flags"]
    assert recent.document.document_version == older.document.document_version
    assert recent.document.content_text == older.document.content_text


def test_time_sensitive_cues_are_hints_until_policy_requires_review(source, policy):
    source = altered(source, content="篩檢費用與補助請依公布資訊確認。")
    hinted = prepare(source, policy)
    reviewed = prepare(source, QualityPolicy(as_of=policy.as_of, stale_after_days=1095,
                                           require_time_sensitive_review=True))
    assert "time_sensitive" in hinted.document.quality["flags"]
    assert hinted.document.quality["status"] == "ready"
    assert reviewed.document.quality["status"] == "needs_review"
    assert reviewed.document.document_version == hinted.document.document_version


def test_cleaner_review_signals_are_generic_and_information_flags_do_not_block(source, policy):
    def cleaner(record):
        return CleanedContent(record.title, record.content, ("custom_structure_review", "html_comment_removed"),
                              "fixture-v1", ("custom_structure_review",))
    result = prepare_document(source, cleaner=cleaner, policy=policy)
    assert result.document.quality["status"] == "needs_review"
    assert {issue.code for issue in result.issues} == {"custom_structure_review", "html_comment_removed"}
    informative = prepare_document(source, cleaner=lambda r: CleanedContent(r.title, r.content,
                                   ("html_comment_removed",), "fixture-v1"), policy=policy)
    assert informative.document.quality["status"] == "ready"


def test_snapshot_is_preserved_and_explicitly_not_claimed_verified(source, policy, monkeypatch):
    payload = source.to_dict()
    payload["provenance"].update(raw_snapshot="raw/not-opened.html", raw_snapshot_sha256="a" * 64)
    def forbidden(*args, **kwargs):
        pytest.fail("preparation must not read source files")
    monkeypatch.setattr(Path, "open", forbidden)
    result = prepare(SourceRecord.from_dict(payload), policy)
    assert result.document.source["raw_snapshot_sha256"] == "a" * 64
    assert "snapshot_not_verified" in result.document.quality["flags"]
    assert any(issue.code == "snapshot_not_verified" and issue.severity == "warning" for issue in result.issues)


@pytest.mark.parametrize("title,body,code", [(" ", "正文", "empty_clean_title"), ("標題", "\n", "empty_clean_body")])
def test_empty_cleaned_content_is_rejected_with_traceable_error(source, policy, title, body, code):
    result = prepare_document(source, cleaner=lambda r: CleanedContent(title, body, (), "fixture-v1"),
                              policy=policy, input_locator="fixture.jsonl", line_number=7)
    assert result.document is None
    issue = next(issue for issue in result.issues if issue.code == code)
    assert issue.to_dict() == {"input_locator": "fixture.jsonl", "line_number": 7,
                              "dataset_id": "fixture", "source_record_id": "one", "document_id": "fixture:one",
                              "code": code, "severity": "error", "message": issue.message}
    assert result.cleaning_version == "fixture-v1"


def test_cleaner_validation_failures_and_malformed_document_are_reported(source, policy):
    def fail(record):
        raise KnowledgeBaseValidationError("cannot extract safely")
    result = prepare_document(source, cleaner=fail, policy=policy)
    assert result.document is None and result.issues[0].code == "cleaning_failed"
    assert result.issues[0].input_locator == source.provenance["source_locator"]
    malformed = prepare_document(source, cleaner=lambda r: CleanedContent("two\nlines", r.content, (), "fixture-v1"), policy=policy)
    assert malformed.document is None and malformed.issues[0].code == "invalid_clean_document"


@pytest.mark.parametrize("settings", [{"as_of": None, "stale_after_days": 10},
                                      {"as_of": "2026-02-30", "stale_after_days": 10},
                                      {"as_of": "2026-11-22", "stale_after_days": True},
                                      {"as_of": "2026-11-22", "stale_after_days": -1},
                                      {"as_of": "2026-11-22", "stale_after_days": 10, "require_time_sensitive_review": 1}])
def test_quality_policy_rejects_ambiguous_or_invalid_configuration(settings):
    with pytest.raises(KnowledgeBaseValidationError):
        QualityPolicy(**settings)


def test_cleaned_content_and_result_are_immutable_and_validate_signals(source, policy):
    with pytest.raises(KnowledgeBaseValidationError, match="subset"):
        CleanedContent("title", "body", (), "v1", ("not_in_flags",))
    flags = ["info"]
    cleaned = CleanedContent("title", "body", flags, "v1")
    flags.append("mutation")
    assert cleaned.flags == ("info",)
    result = prepare(source, policy)
    with pytest.raises(FrozenInstanceError):
        result.cleaning_version = "changed"
    with pytest.raises(FrozenInstanceError):
        policy.as_of = "2000-01-01"
    with pytest.raises(KnowledgeBaseValidationError):
        PreparationResult(result.document, [], None)


def test_repeated_preparation_has_stable_content_version_issues_and_source(source, policy):
    first = prepare(source, policy, input_locator="fixture.jsonl", line_number=1)
    second = prepare(source, policy, input_locator="fixture.jsonl", line_number=1)
    assert first == second
    assert policy.to_dict() == {"as_of": "2026-11-22", "stale_after_days": 1095,
                                "require_time_sensitive_review": False}


def test_cdc_119_cleaned_documents_keep_hash_identity_and_isolate_attachment(policy):
    from clinical_warrant.modules.knowledge_base.infrastructure.cleaning import clean_source_record

    root = ROOT / "datasets" / "tw_cdc_hiv_qa"
    source_bytes = (root / "qa.jsonl").read_bytes()
    manifest_bytes = (root / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    records = list(CdcQaAdapter(manifest, intended_use="fixture_validation", usage_decision="unknown").read_jsonl(root / "qa.jsonl"))
    results = [prepare_document(record, cleaner=clean_source_record, policy=policy,
                               input_locator=str(root / "qa.jsonl"), line_number=index)
               for index, record in enumerate(records, 1)]
    assert len(results) == 119 and all(result.document is not None for result in results)
    dependencies = []
    for source, result in zip(records, results):
        document = result.document
        assert "日期 發送處" not in document.content_text
        assert document.document_id == source.dataset_id + ":" + source.source_record_id
        assert document.source["raw_content_sha256"] == source.provenance["raw_content_sha256"]
        assert document.source["source_updated_at"] == source.provenance["source_updated_at"]
        assert document.document_version == document_version_for(document.to_dict())
        assert document.quality["status"] == "needs_review"
        assert "cms_noise_removed" in document.quality["flags"]
        assert "snapshot_not_verified" in document.quality["flags"]
        assert all(issue.source_record_id == source.source_record_id and issue.document_id == document.document_id for issue in result.issues)
        if "attachment_dependency" in document.quality["flags"]:
            dependencies.append(document)
    assert len(dependencies) == 1
    assert "二者的比較請詳見下表" in dependencies[0].content_text
    assert (root / "qa.jsonl").read_bytes() == source_bytes
    assert (root / "manifest.json").read_bytes() == manifest_bytes
