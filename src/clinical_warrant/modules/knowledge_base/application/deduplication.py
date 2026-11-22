"""Exact document deduplication and identity conflict detection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal

from ..domain.contracts import KnowledgeDocument, canonical_json_bytes


@dataclass(frozen=True)
class DocumentConflict:
    reason: Literal["metadata_conflict", "version_conflict"]
    documents: tuple[KnowledgeDocument, ...]


@dataclass(frozen=True)
class DeduplicationResult:
    accepted_documents: tuple[KnowledgeDocument, ...]
    exact_duplicate_count: int
    conflict_groups: tuple[DocumentConflict, ...]
    cross_source_groups: tuple[tuple[KnowledgeDocument, ...], ...]


def deduplicate_documents(documents: Iterable[KnowledgeDocument]) -> DeduplicationResult:
    """Deduplicate identical full records and isolate every conflicting identity.

    Accepted documents exclude every document_id with a version or metadata
    conflict. Conflict groups retain each distinct canonical record (exact
    repeats are counted and collapsed); version_conflict takes precedence when
    an identity contains multiple versions. Cross-source groups contain only
    accepted documents and report shared document_version without removing
    either source or changing quality flags.
    """
    grouped: dict[str, dict[bytes, KnowledgeDocument]] = {}
    duplicate_count = 0
    for document in documents:
        if not isinstance(document, KnowledgeDocument):
            raise TypeError("documents must contain KnowledgeDocument values")
        encoded = canonical_json_bytes(document.to_dict())
        records = grouped.setdefault(document.document_id, {})
        if encoded in records:
            duplicate_count += 1
        else:
            records[encoded] = document

    accepted: list[KnowledgeDocument] = []
    conflicts: list[DocumentConflict] = []
    for document_id in sorted(grouped):
        records = grouped[document_id]
        unique = tuple(records[key] for key in sorted(records))
        versions = {document.document_version for document in unique}
        if len(versions) > 1:
            conflicts.append(DocumentConflict("version_conflict", unique))
        elif len(unique) > 1:
            conflicts.append(DocumentConflict("metadata_conflict", unique))
        else:
            accepted.append(unique[0])

    by_version: dict[str, list[KnowledgeDocument]] = {}
    for document in accepted:
        by_version.setdefault(document.document_version, []).append(document)
    cross_source = tuple(
        tuple(sorted(group, key=lambda item: item.document_id))
        for _, group in sorted(by_version.items())
        if len(group) > 1
    )
    return DeduplicationResult(tuple(accepted), duplicate_count, tuple(conflicts), cross_source)
