from copy import deepcopy
import json
from pathlib import Path
import re

import pytest

from clinical_warrant.modules.knowledge_base import (
    KnowledgeBaseValidationError,
    KnowledgeDocument,
    chunk_id_for,
    document_version_for,
)
from clinical_warrant.modules.knowledge_base.application.chunking import chunk_document


@pytest.fixture
def example_document():
    schema = (Path(__file__).parents[1] / "docs" / "rag-kb-schema.md").read_text(encoding="utf-8")
    body = re.search(r"<!-- example: document -->\n```json\n(.*?)\n```", schema, re.S).group(1)
    return json.loads(body)


def make_document(example, body, *, kind="article", title="標題"):
    payload = deepcopy(example)
    payload.update(document_type=kind, title=title)
    payload["content_text"] = (f"問題：{title}\n回答：{body}" if kind == "faq" else f"{title}\n{body}")
    payload["document_version"] = document_version_for(payload)
    return KnowledgeDocument.from_dict(payload)


def check_coverage(document, chunks, maximum):
    assert chunks
    assert chunks[0].char_start == 0
    assert chunks[-1].char_end == len(document.content_text)
    assert all(chunk.text == document.content_text[chunk.char_start:chunk.char_end] for chunk in chunks)
    assert all(len(chunk.text) <= maximum for chunk in chunks)
    assert all(right.char_start <= left.char_end for left, right in zip(chunks, chunks[1:]))
    assert all(right.char_start > left.char_start for left, right in zip(chunks, chunks[1:]))


def config(max_chars, overlap_chars=0):
    return {"algorithm_version": "structure-v1", "max_chars": max_chars, "overlap_chars": overlap_chars}


def test_chunking_is_deterministic_and_ids_bind_to_config(example_document):
    document = make_document(example_document, "第一句。第二句。第三句。第四句。")
    chunks = chunk_document(document, config(10, 2))
    repeated = chunk_document(document, config(10, 2))
    changed = chunk_document(document, config(11, 2))

    assert [chunk.to_dict() for chunk in chunks] == [chunk.to_dict() for chunk in repeated]
    assert [chunk.chunk_id for chunk in chunks] != [chunk.chunk_id for chunk in changed]
    for chunk in chunks:
        chunk.validate_reference(document, config(10, 2))
        assert chunk.chunk_id == chunk_id_for(chunk.to_dict(), config(10, 2))
    check_coverage(document, chunks, 10)


def test_short_faq_stays_one_complete_qa_chunk(example_document):
    document = make_document(example_document, "完整回答。", kind="faq", title="問題")
    chunks = chunk_document(document, config(len(document.content_text), 0))

    assert len(chunks) == 1
    assert chunks[0].text == document.content_text
    assert chunks[0].char_start == 0
    assert chunks[0].char_end == len(document.content_text)


def test_paragraph_boundary_precedes_later_list_and_sentence_boundaries(example_document):
    body = "前段內容\n\n- 項目一。後續句子。\n- 項目二。"
    document = make_document(example_document, body)
    paragraph_end = document.content_text.index("- 項目一")
    chunks = chunk_document(document, config(len(document.content_text) - 1, 0))

    assert chunks[0].char_end == paragraph_end
    assert chunks[0].text.endswith("\n\n")
    check_coverage(document, chunks, len(document.content_text) - 1)


def test_list_item_boundary_precedes_sentence_boundary(example_document):
    body = "- 第一項沒有句號\n- 第二項文字。後續句子仍在同一清單項目。"
    document = make_document(example_document, body)
    body_start = document.content_text.index(body)
    first_item_end = body_start + body.index("\n") + 1
    chunks = chunk_document(document, config(len(document.content_text) - 1, 0))

    assert chunks[0].char_end == first_item_end
    check_coverage(document, chunks, len(document.content_text) - 1)


def test_sentence_boundary_is_used_when_no_higher_tier_fits(example_document):
    document = make_document(example_document, "第一句。第二句。第三句。")
    first_sentence_end = document.content_text.index("。") + 1
    chunks = chunk_document(document, config(first_sentence_end, 0))

    assert chunks[0].char_end == first_sentence_end
    assert chunks[0].text.endswith("。")
    check_coverage(document, chunks, first_sentence_end)


def test_heading_starts_the_next_chunk(example_document):
    body = "前言文字\n\n## 新標題\n這是標題後的內容。還有下一句。"
    document = make_document(example_document, body)
    heading_start = document.content_text.index("## 新標題")
    chunks = chunk_document(document, config(heading_start, 0))

    assert chunks[0].char_end == heading_start
    assert document.content_text[chunks[1].char_start:chunks[1].char_end].startswith("## 新標題")
    check_coverage(document, chunks, heading_start)


@pytest.mark.parametrize("overlap", [0, 11])
def test_long_list_items_and_unpunctuated_text_are_fully_covered(example_document, overlap):
    body = "- " + "甲" * 28 + "\n- " + "乙" * 25 + "\n沒有標點" + "丙" * 35
    document = make_document(example_document, body)
    chunks = chunk_document(document, config(12, overlap))

    check_coverage(document, chunks, 12)
    assert any("- " in chunk.text for chunk in chunks)


def test_offsets_count_emoji_as_one_codepoint_and_citations_match(example_document):
    document = make_document(example_document, "😀甲乙。😀丙丁。😀戊己。")
    chunks = chunk_document(document, config(8, 2))

    check_coverage(document, chunks, 8)
    assert all(chunk.text == document.content_text[chunk.char_start:chunk.char_end] for chunk in chunks)
    assert sum(len(chunk.text) for chunk in chunks) >= len(document.content_text)


def test_extreme_overlap_terminates_with_complete_coverage(example_document):
    document = make_document(example_document, "甲乙丙丁戊己庚辛壬癸。" * 60)
    chunks = chunk_document(document, config(12, 11))

    check_coverage(document, chunks, 12)


def test_max_one_covers_title_separator_and_long_whitespace(example_document):
    document = make_document(example_document, " " * 40 + "正文")
    chunks = chunk_document(document, config(1, 0))

    check_coverage(document, chunks, 1)
    assert any(chunk.text == "\n" for chunk in chunks)
    assert any(chunk.text == " " for chunk in chunks)


def test_invalid_config_is_rejected_by_chunking(example_document):
    document = make_document(example_document, "正文。")
    with pytest.raises(KnowledgeBaseValidationError, match="max_chars"):
        chunk_document(document, config(0))
