"""Prepare complete documents using an injected cleaner and explicit policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re

from ..domain.contracts import (
    KnowledgeBaseValidationError,
    KnowledgeDocument,
    SourceRecord,
    canonical_json_bytes,
    document_version_for,
)
from ..domain.policies import CleanedContent, QualityIssue, QualityPolicy, TextCleaner


QUALITY_RULES_VERSION = "quality-v1"
_TIME_TERMS = ("空窗期", "檢測時間", "篩檢時間", "用藥", "服藥", "劑量", "費用", "補助",
               "服務據點", "篩檢據點", "預防性投藥")
_ATTACHMENT_REFERENCE = re.compile(
    r"(?:詳見|請見|參見|參閱|參考|請看)\s*(?:以下|下方|上述|相關|本頁)?\s*(?:附件|附檔|下表|比較表|附表)"
    r"|(?:see|refer to)\s+(?:the\s+)?(?:attachment|attached|table below)", re.IGNORECASE,
)
_DIRECT_ATTACHMENT_REFERENCE = re.compile(
    r"(?:詳見|請見|參見|參閱|參考|請看)\s*(?:以下|下方|上述|相關|本頁)?\s*(?:附件|附檔)"
    r"|(?:see|refer to)\s+(?:the\s+)?(?:attachment|attached)", re.IGNORECASE,
)
_MESSAGES = {
    "attachment_dependency": "The text refers to an attachment or comparison table not included in the document.",
    "rights_unknown": "The source rights or intended-use decision remain unknown.",
    "rights_prohibited": "The configured intended use is prohibited; the document is excluded.",
    "source_date_missing": "The source update date is unknown; no date was invented.",
    "staleness_review": "The source date exceeds the configured age threshold; the text was retained.",
    "time_sensitive": "The text contains a configured time-sensitive topic cue; this is a review hint.",
    "snapshot_not_verified": "Snapshot path/digest were preserved; snapshot bytes were not verified at this stage.",
}


@dataclass(frozen=True)
class PreparationResult:
    document: KnowledgeDocument | None
    issues: tuple[QualityIssue, ...]
    cleaning_version: str | None
    quality_version: str = QUALITY_RULES_VERSION

    def __post_init__(self) -> None:
        if self.document is not None and not isinstance(self.document, KnowledgeDocument):
            raise KnowledgeBaseValidationError("preparation.document must be a KnowledgeDocument or null")
        if not isinstance(self.issues, (list, tuple)) or any(not isinstance(item, QualityIssue) for item in self.issues):
            raise KnowledgeBaseValidationError("preparation.issues must contain QualityIssue values")
        if self.cleaning_version is None and self.document is not None:
            raise KnowledgeBaseValidationError("preparation.cleaning_version is required for a document")
        for name in ("cleaning_version", "quality_version"):
            value = getattr(self, name)
            if name == "cleaning_version" and value is None:
                continue
            if not isinstance(value, str) or not value.strip():
                raise KnowledgeBaseValidationError(f"preparation.{name} must be a nonempty string")
            canonical_json_bytes(value)
        object.__setattr__(self, "issues", tuple(self.issues))


def prepare_document(source: SourceRecord, *, cleaner: TextCleaner, policy: QualityPolicy,
                     input_locator: str | None = None,
                     line_number: int | None = None) -> PreparationResult:
    """Map one validated source to a complete document, never a chunk or run.

    A ready result passes this stage only. It does not verify snapshot bytes,
    audit files or a published run; callers must perform those checks later.
    """
    if not isinstance(source, SourceRecord):
        raise KnowledgeBaseValidationError("source must be a validated SourceRecord")
    if not isinstance(policy, QualityPolicy):
        raise KnowledgeBaseValidationError("policy must be a QualityPolicy")
    if not callable(cleaner):
        raise KnowledgeBaseValidationError("cleaner must be callable")
    context = {
        "input_locator": source.provenance["source_locator"] if input_locator is None else input_locator,
        "line_number": line_number, "dataset_id": source.dataset_id,
        "source_record_id": source.source_record_id,
        "document_id": source.dataset_id + ":" + source.source_record_id,
    }
    # Validate tracing even when a source has no findings.
    QualityIssue(**context, code="context", severity="warning", message="context")

    def issue(code: str, severity: str = "warning", message: str | None = None) -> QualityIssue:
        return QualityIssue(**context, code=code, severity=severity,
                            message=message or _MESSAGES.get(code, f"Cleaner reported {code}."))

    try:
        cleaned = cleaner(source)
    except KnowledgeBaseValidationError as error:
        return PreparationResult(None, (issue("cleaning_failed", "error", str(error)),), None)
    if not isinstance(cleaned, CleanedContent):
        raise KnowledgeBaseValidationError("cleaner must return CleanedContent")
    errors = []
    if not cleaned.title.strip():
        errors.append(issue("empty_clean_title", "error", "The cleaned title is empty."))
    if not cleaned.body_text.strip():
        errors.append(issue("empty_clean_body", "error", "The cleaned body is empty."))
    if errors:
        findings = [issue(flag) for flag in cleaned.flags]
        return PreparationResult(None, tuple(sorted([*findings, *errors], key=lambda entry: entry.code)),
                                 cleaned.cleaning_version)

    flags = set(cleaned.flags)
    needs_review = bool(cleaned.review_flags)
    rights = source.provenance["rights"]
    if rights["usage_decision"] == "prohibited":
        flags.add("rights_prohibited")
        status = "excluded"
    else:
        status = "ready"
        if rights["status"] == "unknown" or rights["usage_decision"] == "unknown":
            flags.add("rights_unknown")
            needs_review = True

    reference_text = cleaned.title + "\n" + cleaned.body_text
    listed_dependency = (any(not item["included"] for item in source.attachments)
                         and _ATTACHMENT_REFERENCE.search(reference_text))
    missing_dependency = (not any(item["included"] for item in source.attachments)
                          and _DIRECT_ATTACHMENT_REFERENCE.search(reference_text))
    if listed_dependency or missing_dependency:
        flags.add("attachment_dependency")
        needs_review = True
    updated = source.provenance["source_updated_at"]
    if updated is None:
        flags.add("source_date_missing")
    elif (date.fromisoformat(policy.as_of) - date.fromisoformat(updated)).days > policy.stale_after_days:
        flags.add("staleness_review")
    if any(term in reference_text for term in _TIME_TERMS) or re.search(r"(?<![A-Za-z])(?:PrEP|PEP)(?![A-Za-z])", reference_text, re.IGNORECASE):
        flags.add("time_sensitive")
        needs_review = needs_review or policy.require_time_sensitive_review
    if source.provenance["raw_snapshot"] is not None:
        flags.add("snapshot_not_verified")
    if status != "excluded" and needs_review:
        status = "needs_review"

    original = source.to_dict()
    payload = {
        "schema_version": "1.0", "document_id": context["document_id"],
        "document_type": source.document_type, "title": cleaned.title,
        "content_text": (f"問題：{cleaned.title}\n回答：{cleaned.body_text}" if source.document_type == "faq"
                         else cleaned.title + "\n" + cleaned.body_text),
        "language": source.language,
        "source": {**original["provenance"], "dataset_id": source.dataset_id,
                   "source_record_id": source.source_record_id},
        "metadata": original["metadata"], "attachments": original["attachments"],
        "quality": {"status": status, "flags": sorted(flags),
                    "review_status": "unreviewed", "review_ref": None},
    }
    payload["document_version"] = document_version_for(payload)
    try:
        document = KnowledgeDocument.from_dict(payload)
    except KnowledgeBaseValidationError as error:
        return PreparationResult(None, (issue("invalid_clean_document", "error", str(error)),), cleaned.cleaning_version)
    issues = tuple(sorted((issue(flag) for flag in flags), key=lambda entry: (entry.code, entry.message)))
    return PreparationResult(document, issues, cleaned.cleaning_version)
