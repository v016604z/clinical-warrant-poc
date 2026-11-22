"""Exact deduplication preserves conflicting and cross-source evidence."""

from copy import deepcopy
import json
from pathlib import Path
import re

import pytest

from clinical_warrant.modules.knowledge_base.application.deduplication import deduplicate_documents
from clinical_warrant.modules.knowledge_base.domain.contracts import (
    KnowledgeDocument,
    document_version_for,
)


@pytest.fixture
def example():
    text = (Path(__file__).parents[1] / "docs" / "rag-kb-schema.md").read_text(encoding="utf-8")
    return json.loads(re.search(r"<!-- example: document -->\n```json\n(.*?)\n```", text, re.S).group(1))


def make_document(example, *, dataset="example_articles", record="article-001", title=None):
    payload = deepcopy(example)
    payload["document_id"] = f"{dataset}:{record}"
    payload["source"].update(
        dataset_id=dataset,
        source_record_id=record,
        source_locator=f"fixture:{dataset}/{record}",
    )
    if title is not None:
        payload["title"] = title
        payload["content_text"] = f"{title}\n甲乙"
        payload["document_version"] = document_version_for(payload)
    return KnowledgeDocument.from_dict(payload)


def vary(example, field):
    payload = deepcopy(example)
    if field == "metadata":
        payload["metadata"]["source_category"] = "另一分類"
    elif field == "source":
        payload["source"]["publisher"] = "Another Publisher"
    elif field == "rights":
        payload["source"]["rights"]["statement"] += " Changed."
    elif field == "quality":
        payload["quality"]["flags"] = ["staleness_review"]
    elif field == "review":
        payload["quality"].update(review_status="rejected", review_ref="audit:rejected")
    return KnowledgeDocument.from_dict(payload)


def test_only_identical_full_documents_are_exact_duplicates(example):
    document = make_document(example)
    result = deduplicate_documents([document, document])
    assert result.accepted_documents == (document,)
    assert result.exact_duplicate_count == 1
    assert result.conflict_groups == ()


@pytest.mark.parametrize("field", ["metadata", "source", "rights", "quality", "review"])
def test_same_identity_version_but_any_full_record_difference_is_conflict(example, field):
    original = make_document(example)
    changed = vary(example, field)
    result = deduplicate_documents([changed, original])
    assert result.accepted_documents == ()
    assert result.exact_duplicate_count == 0
    assert len(result.conflict_groups) == 1
    conflict = result.conflict_groups[0]
    assert conflict.reason == "metadata_conflict"
    assert {doc.to_json() for doc in conflict.documents} == {original.to_json(), changed.to_json()}


def test_exact_repeats_inside_a_conflict_group_are_counted_and_collapsed(example):
    original = make_document(example)
    variant = vary(example, "metadata")
    other = make_document(example, dataset="other_source", record="item-1")
    result = deduplicate_documents([original, variant, original, other])
    assert result.exact_duplicate_count == 1
    assert result.accepted_documents == (other,)
    assert len(result.conflict_groups) == 1
    assert result.conflict_groups[0].reason == "metadata_conflict"
    assert {doc.to_json() for doc in result.conflict_groups[0].documents} == {
        original.to_json(), variant.to_json()
    }


def test_version_conflict_keeps_all_versions_and_takes_precedence(example):
    first = make_document(example)
    second = make_document(example, title="另一標題")
    metadata_variant = vary(example, "source")
    result = deduplicate_documents([metadata_variant, second, first])
    assert result.accepted_documents == ()
    assert len(result.conflict_groups) == 1
    assert result.conflict_groups[0].reason == "version_conflict"
    assert {doc.to_json() for doc in result.conflict_groups[0].documents} == {
        metadata_variant.to_json(), second.to_json(), first.to_json()
    }


def test_cross_source_same_clean_hash_is_reported_without_removing_sources(example):
    first = make_document(example)
    second = make_document(example, dataset="other_source", record="item-1")
    result = deduplicate_documents([second, first])
    assert result.accepted_documents == (first, second)
    assert result.conflict_groups == ()
    assert result.cross_source_groups == ((first, second),)
    assert [doc.source["source_locator"] for doc in result.cross_source_groups[0]] == [
        first.source["source_locator"], second.source["source_locator"]
    ]


def test_results_are_deterministic_for_reordered_input_and_exclude_conflicts_from_cross_source(example):
    conflict_a = make_document(example)
    conflict_b = vary(example, "source")
    same_content_other_source = make_document(example, dataset="other_source", record="item-1")
    rows = [conflict_b, same_content_other_source, conflict_a, same_content_other_source]
    first = deduplicate_documents(rows)
    second = deduplicate_documents(reversed(rows))
    assert first == second
    assert first.exact_duplicate_count == 1
    assert first.accepted_documents == (same_content_other_source,)
    assert first.cross_source_groups == ()
    assert first.conflict_groups[0].documents == tuple(sorted(
        first.conflict_groups[0].documents, key=lambda doc: doc.to_json().encode("utf-8")
    ))

