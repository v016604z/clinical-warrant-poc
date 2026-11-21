"""HTML rendering boundaries and preservation of the collected source text."""

from collections import Counter
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re

import pytest

from clinical_warrant.modules.knowledge_base import CdcQaAdapter, KnowledgeBaseValidationError, SourceRecord
from clinical_warrant.modules.knowledge_base.infrastructure.cleaning import CLEANING_VERSION, clean_source_record


def source(content, *, title="示例", profile="html_v1", attachments=None):
    return SourceRecord.from_dict({
        "schema_version": "1.0", "dataset_id": "fixture", "source_record_id": "item-1",
        "document_type": "faq" if profile == "cdc_faq_html_v1" else "article",
        "title": title, "content": content,
        "content_type": "text/plain" if profile == "plain_v1" else "text/html",
        "language": "zh-Hant", "cleaning_profile": profile,
        "provenance": {
            "publisher": "Fixture", "source_locator": "https://example.test/page",
            "source_updated_at": None, "collected_at_utc": None,
            "raw_content_sha256": hashlib.sha256(content.encode()).hexdigest(),
            "raw_content_hash_basis": "text_utf8_v1", "raw_snapshot": None,
            "raw_snapshot_sha256": None, "attribution": "Project-authored fixture",
            "rights": {"status": "recorded", "statement": "Project-authored fixture.",
                       "policy_locators": [], "intended_use": "fixture_validation", "usage_decision": "allowed"},
        }, "attachments": attachments or [], "metadata": {"original": {"retained": True}},
    })


def test_plain_normalization_is_nfc_without_nfkc_or_html_processing():
    record = source("  Ａ３　mg\r\n\r\n\r\n e\u0301\tX\u00a0 Y <5 ", title=" 標題\r\n A ", profile="plain_v1")
    before = record.to_dict()
    result = clean_source_record(record)
    assert result.title == "標題 A"
    assert result.body_text == "Ａ３ mg\n\né X Y <5"
    assert result.cleaning_version == CLEANING_VERSION
    assert result.flags == result.review_flags == ()
    assert record.to_dict() == before


def test_inline_comments_and_entities_are_decoded_exactly_once():
    result = clean_source_record(source("A<!--not body-->B &lt;5 &amp; &amp;lt; &amp;#65; &#x41;"))
    assert result.body_text == "AB <5 & &lt; &#65; A"
    assert result.flags == ("html_comment_removed",)
    assert not result.review_flags


def test_paragraphs_breaks_blocks_and_links_keep_the_visible_content():
    result = clean_source_record(source('<div>前言<p>段落一<br/>第二行</p><p>段落二 <a href="https://example.test/other">原連結文字</a></p>結尾</div>'))
    assert result.body_text == "前言\n\n段落一\n第二行\n\n段落二 原連結文字\n\n結尾"
    assert not result.review_flags


def test_script_and_style_bodies_are_not_mistaken_for_visible_evidence():
    result = clean_source_record(source("A<script>if(x<5){fake='999mg'}</script><style>.x{color:red}</style>B"))
    assert result.body_text == "AB"
    assert result.flags == ("html_unsafe_content_removed",)
    assert not result.review_flags


@pytest.mark.parametrize("html,expected", [
    ("<ol start='4'><li>甲</li><li value='8'>乙</li><li>丙</li></ol>", "4. 甲\n8. 乙\n9. 丙"),
    ("<ol reversed><li>甲</li><li>乙</li><li>丙</li></ol>", "3. 甲\n2. 乙\n1. 丙"),
    ("<ol reversed start='5'><li>甲</li><li value='2'>乙</li><li>丙</li></ol>", "5. 甲\n2. 乙\n1. 丙"),
    ("<ol><li>甲<ol start='2'><li>子項</li></ol></li><li>乙</li></ol>", "1. 甲\n1.2. 子項\n2. 乙"),
    ("<ul><li>甲<ul><li>子項</li></ul></li><li>乙</li></ul>", "- 甲\n- - 子項\n- 乙"),
    ("<ol><li><p>第一段</p><p>第二段</p><ul><li>子項</li></ul></li></ol>", "1. 第一段\n\n第二段\n\n1. - 子項"),
])
def test_list_labels_and_nested_structure_are_explicit_without_indent_dependence(html, expected):
    result = clean_source_record(source(html))
    assert result.body_text == expected
    assert not result.review_flags


def test_invalid_list_numbers_retain_content_and_require_review():
    result = clean_source_record(source("<ol start='unclear'><li value='also unclear'>10 mg</li></ol>"))
    assert result.body_text == "1. 10 mg"
    assert "list_structure_review" in result.review_flags
    assert set(result.review_flags) <= set(result.flags)


def test_nondecimal_ordered_list_markers_are_not_claimed_preserved_safely():
    result = clean_source_record(source("<ol type='A'><li>甲</li><li>乙</li></ol>"))
    assert "甲" in result.body_text and "乙" in result.body_text
    assert "list_structure_review" in result.review_flags


def test_tables_keep_cells_and_rows_but_are_not_silently_safe():
    result = clean_source_record(source("<table><caption>比較</caption><tr><th>條件</th><th>值</th></tr><tr><td rowspan='2'>未滿</td><td>&lt;5 mg</td></tr><tr><td>10 mg</td></tr></table>"))
    assert "條件 | 值" in result.body_text
    assert "未滿 | <5 mg" in result.body_text
    assert "\n10 mg" in result.body_text
    assert result.review_flags == ("table_structure_review",)


def test_superscripts_subscripts_and_images_keep_markers_or_alt_and_require_review():
    result = clean_source_record(source("10<sup>5</sup>，H<sub>2</sub>O <img src='fixture.png' alt='示意圖10 mg'>"))
    assert result.body_text == "10^(5)，H_(2)O 示意圖10 mg"
    assert result.review_flags == ("image_content_review", "inline_structure_review")
    assert set(result.review_flags) <= set(result.flags)


@pytest.mark.parametrize("html,flag", [
    ("<p>未關閉", "malformed_html_review"),
    ("<div><span>錯序</div></span>", "malformed_html_review"),
    ("<custom-block>未知結構</custom-block>", "unsupported_html_review"),
    ("<p class='a' class='b'>重複屬性</p>", "malformed_html_review"),
    ("<script/>self-closing HTML script boundary", "malformed_html_review"),
])
def test_malformed_or_unsupported_markup_keeps_text_and_needs_review(html, flag):
    result = clean_source_record(source(html))
    assert result.body_text
    assert flag in result.review_flags


def test_only_confirmed_cdc_attachment_ui_is_removed_and_metadata_stays_intact():
    attachment = {"locator": "https://example.test/File/comparison", "title": "比較表", "media_type": None, "included": False}
    html = '比較請詳見下表。<!--附件 start--><div class="download"><h3>附件</h3><a href="/File/comparison">比較表</a></div><!--附件 end-->'
    cdc = source(html, profile="cdc_faq_html_v1", attachments=[attachment])
    before = cdc.to_dict()
    cleaned = clean_source_record(cdc)
    assert cleaned.body_text == "比較請詳見下表。"
    assert cleaned.flags == ("cms_noise_removed",)
    assert cdc.to_dict() == before
    generic = clean_source_record(source(html, attachments=[attachment]))
    assert "比較表" in generic.body_text and "附件" in generic.body_text


def test_download_panel_with_additional_body_is_preserved_for_review():
    attachment = {"locator": "https://example.test/File/comparison", "title": "比較表", "media_type": None, "included": False}
    html = '<div class="download"><h3>附件</h3><p>Important body: 10 mg must remain.</p><a href="/File/comparison">比較表</a></div>'
    result = clean_source_record(source(html, profile="cdc_faq_html_v1", attachments=[attachment]))
    assert "Important body: 10 mg must remain." in result.body_text
    assert "比較表" in result.body_text
    assert "attachment_panel_review" in result.review_flags


def test_medical_words_and_dates_are_not_removed_by_broad_keyword_rules():
    text = "日期為2026-11-22；每3至6個月1次，不可超過10-14天；<br>費用245元(試劑200元，物流費45元)，３個方法；RT-PCR&lt;5，不表示未感染。週報表的正文保留。"
    result = clean_source_record(source(text, profile="cdc_faq_html_v1"))
    assert result.body_text == "日期為2026-11-22；每3至6個月1次，不可超過10-14天；\n費用245元(試劑200元，物流費45元)，３個方法；RT-PCR<5，不表示未感染。週報表的正文保留。"
    assert not result.flags
    residual = clean_source_record(source("<p>日期 發送處 start</p><p>正文仍保留</p>", profile="cdc_faq_html_v1"))
    assert "日期 發送處 start" in residual.body_text
    assert residual.review_flags == ("residual_cms_noise",)


def test_empty_rendered_body_is_returned_for_application_rejection():
    result = clean_source_record(source("<script>body</script><!--comment-->"))
    assert result.body_text == ""


def test_unknown_profile_fails_instead_of_falling_back():
    record = source("text")
    object.__setattr__(record, "cleaning_profile", "unknown")
    with pytest.raises(KnowledgeBaseValidationError, match="cleaning_profile"):
        clean_source_record(record)


class _Visible(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.data = []

    def handle_data(self, data):
        self.data.append(data)


def test_119_cdc_records_remove_comments_preserve_numbers_lists_and_original_sources():
    root = Path(__file__).parents[1] / "datasets" / "tw_cdc_hiv_qa"
    paths = [root / "qa.jsonl", root / "manifest.json"]
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    adapter = CdcQaAdapter(json.loads(paths[1].read_text(encoding="utf-8")), intended_use="research_reference", usage_decision="unknown")
    records = list(adapter.read_jsonl(paths[0]))
    assert len(records) == 119
    numbered = attachments = 0
    for record in records:
        original = record.to_dict()
        result = clean_source_record(record)
        assert result.title and result.body_text
        assert "cms_noise_removed" in result.flags
        assert not result.review_flags
        for marker in ("日期 發送處", "檔案列表", "週報表", "月報表", "季報表", "年報表"):
            assert marker not in result.body_text
        assert record.to_dict() == original
        # The only attachment panel is separate UI, not the missing comparison body.
        visible = _Visible()
        visible.feed(record.content.split("<!--附件 start-->", 1)[0])
        source_text = "\n".join(visible.data)
        for pattern in (r"[0-9０-９]+(?:[./-][0-9０-９]+)*", r"[A-Za-z]+(?:-[A-Za-z0-9]+)*",
                        r"不會|不是|不能|不得|不可|未|無|陰性|陽性|至少|超過|小於|大於|以上|以下"):
            expected = Counter(re.findall(pattern, source_text))
            actual = Counter(re.findall(pattern, result.body_text))
            assert all(actual[token] >= count for token, count in expected.items()), record.source_record_id
        if "<ol" in record.content:
            numbered += 1
            assert re.search(r"(?m)^1\. ", result.body_text)
            assert len(re.findall(r"(?m)^\d+\. ", result.body_text)) == record.content.count("<li")
        if record.attachments:
            attachments += 1
            assert "比較請詳見下表" in result.body_text
            assert record.attachments[0]["included"] is False
    assert numbered == 15 and attachments == 1
    assert all(hashlib.sha256(path.read_bytes()).hexdigest() == digest for path, digest in before.items())
