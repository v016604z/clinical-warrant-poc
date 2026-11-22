"""Deterministic, source-preserving chunk generation for KB documents."""

from __future__ import annotations

import re
from bisect import bisect_right
from collections.abc import Mapping
from typing import Any

from ..domain.contracts import (
    KnowledgeBaseValidationError,
    KnowledgeChunk,
    KnowledgeDocument,
    chunk_id_for,
    chunking_fingerprint,
)


_HEADING = re.compile(r"#{1,6}\s+")
_LIST_ITEM = re.compile(r"(?:[-*+]\s+|\d+[.)、]\s*|[一二三四五六七八九十]+[、.)]\s*)")
_SENTENCE_END = frozenset("。！？.!?；;")


def _boundaries(text: str) -> tuple[set[int], set[int], set[int]]:
    """Return heading/paragraph, list, and sentence offsets without rewriting text."""
    paragraphs: set[int] = set()
    lists: set[int] = set()
    sentences: set[int] = set()
    offset = 0
    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        content = line.rstrip("\r\n")
        next_offset = offset + len(line)
        if content.strip():
            if _HEADING.match(content.lstrip()):
                paragraphs.add(offset)
            if _LIST_ITEM.match(content.lstrip()):
                lists.add(next_offset)
        if not content.strip() and index > 0:
            # Keep blank-line separators with the preceding chunk.
            paragraphs.add(next_offset)
        offset = next_offset

    for index, char in enumerate(text):
        if char in _SENTENCE_END and (index + 1 == len(text) or text[index + 1].isspace()):
            sentences.add(index + 1)
    return paragraphs, lists, sentences


def _furthest_after(boundaries: list[int], start: int, previous_end: int, limit: int) -> int | None:
    lower = max(start, previous_end)
    after_lower = bisect_right(boundaries, lower)
    through_limit = bisect_right(boundaries, limit)
    return boundaries[through_limit - 1] if after_lower < through_limit else None


def chunk_document(document: KnowledgeDocument, config: Mapping[str, Any]) -> tuple[KnowledgeChunk, ...]:
    """Split a validated document into reproducible, citation-preserving chunks.

    structure-v1 chooses the furthest heading/paragraph boundary first, then
    a list-item boundary, then a sentence boundary. A Unicode code point limit
    guarantees progress only when none of those tiers has a usable boundary.
    Overlap may revisit prior text, but each chunk extends past the prior end.
    """
    if not isinstance(document, KnowledgeDocument):
        raise KnowledgeBaseValidationError("document must be a KnowledgeDocument")
    chunking_fingerprint(config)
    maximum = config["max_chars"]
    overlap = config["overlap_chars"]
    text = document.content_text
    if len(text) <= maximum:
        intervals = [(0, len(text))]
    else:
        paragraphs, lists, sentences = (sorted(points) for points in _boundaries(text))
        intervals: list[tuple[int, int]] = []
        start = 0
        previous_end = 0
        while start < len(text):
            limit = min(start + maximum, len(text))
            end = next((point for boundaries in (paragraphs, lists, sentences)
                        if (point := _furthest_after(boundaries, start, previous_end, limit)) is not None), limit)
            intervals.append((start, end))
            if end == len(text):
                break
            previous_end = end
            start = max(start + 1, end - overlap)

    source = document.source
    metadata = {
        "dataset_id": source["dataset_id"],
        "document_type": document.document_type,
        "language": document.language,
        "source_updated_at": source["source_updated_at"],
        "source_category": document.metadata.get("source_category"),
        "source_metadata": dict(document.metadata),
    }
    chunks = []
    for index, (start, end) in enumerate(intervals):
        payload = {
            "schema_version": "1.0",
            "document_id": document.document_id,
            "document_version": document.document_version,
            "chunk_index": index,
            "text": text[start:end],
            "char_start": start,
            "char_end": end,
            "source_locator": source["source_locator"],
            "metadata": metadata,
        }
        payload["chunk_id"] = chunk_id_for(payload, config)
        chunk = KnowledgeChunk.from_dict(payload)
        chunk.validate_reference(document, config)
        if len(chunk.text) > maximum:
            raise KnowledgeBaseValidationError("chunk.text exceeds chunking_config.max_chars")
        chunks.append(chunk)
    if not chunks or chunks[0].char_start != 0 or chunks[-1].char_end != len(text):
        raise KnowledgeBaseValidationError("chunk intervals do not cover the document")
    if any(current.char_start > previous.char_end for previous, current in zip(chunks, chunks[1:])):
        raise KnowledgeBaseValidationError("chunk intervals leave a gap in the document")
    if any(current.char_start <= previous.char_start for previous, current in zip(chunks, chunks[1:])):
        raise KnowledgeBaseValidationError("chunk overlap does not make forward progress")
    return tuple(chunks)
