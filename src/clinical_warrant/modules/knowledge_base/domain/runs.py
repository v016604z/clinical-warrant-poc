"""Shared immutable containers for knowledge-base pipeline runs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .contracts import KnowledgeChunk, KnowledgeDocument, SourceRecord


@dataclass(frozen=True)
class SourceInput:
    input_locator: str
    line_number: int
    raw_record: Any
    source: SourceRecord | None
    error: str | None = None
    code: str | None = None


@dataclass(frozen=True)
class RunData:
    documents: tuple[KnowledgeDocument, ...]
    chunks: tuple[KnowledgeChunk, ...]
    issues: tuple[dict, ...]
    rejected: tuple[dict, ...]
    quality_report: dict
    manifest: dict
    reviews: tuple[dict, ...] = ()
