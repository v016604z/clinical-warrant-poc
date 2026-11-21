"""Pure values and the injected cleaning port for document preparation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Protocol

from .contracts import (
    KnowledgeBaseValidationError,
    SourceRecord,
    _choice,
    _dataset,
    _date,
    _document_id,
    _integer,
    _record_id,
    _strings,
    _text,
)


@dataclass(frozen=True)
class CleanedContent:
    title: str
    body_text: str
    flags: tuple[str, ...]
    cleaning_version: str
    review_flags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        # Empty extracted text is returned to the application for a traced rejection.
        _text(self.title, "cleaned.title", nonempty=False)
        _text(self.body_text, "cleaned.body_text", nonempty=False)
        _text(self.cleaning_version, "cleaned.cleaning_version")
        _strings(self.flags, "cleaned.flags")
        _strings(self.review_flags, "cleaned.review_flags")
        if not set(self.review_flags) <= set(self.flags):
            raise KnowledgeBaseValidationError("cleaned.review_flags must be a subset of flags")
        object.__setattr__(self, "flags", tuple(self.flags))
        object.__setattr__(self, "review_flags", tuple(self.review_flags))


class TextCleaner(Protocol):
    def __call__(self, record: SourceRecord) -> CleanedContent:
        """Return cleaned text and explicit review signals without file access."""


@dataclass(frozen=True)
class QualityPolicy:
    as_of: str
    stale_after_days: int
    require_time_sensitive_review: bool = False

    def __post_init__(self) -> None:
        _text(self.as_of, "quality_policy.as_of")
        _date(self.as_of, "quality_policy.as_of")
        _integer(self.stale_after_days, "quality_policy.stale_after_days")
        if type(self.require_time_sensitive_review) is not bool:
            raise KnowledgeBaseValidationError("quality_policy.require_time_sensitive_review must be boolean")

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class QualityIssue:
    input_locator: str
    line_number: int | None
    dataset_id: str | None
    source_record_id: str | None
    document_id: str | None
    code: str
    severity: str
    message: str

    def __post_init__(self) -> None:
        _text(self.input_locator, "issue.input_locator")
        if self.line_number is not None:
            _integer(self.line_number, "issue.line_number", 1)
        if self.dataset_id is not None:
            _dataset(self.dataset_id, "issue.dataset_id")
        if self.source_record_id is not None:
            _record_id(self.source_record_id, "issue.source_record_id")
        if self.document_id is not None:
            _document_id(self.document_id, "issue.document_id")
        _text(self.code, "issue.code")
        _choice(self.severity, {"warning", "error"}, "issue.severity")
        _text(self.message, "issue.message")

    def to_dict(self) -> dict:
        return asdict(self)
