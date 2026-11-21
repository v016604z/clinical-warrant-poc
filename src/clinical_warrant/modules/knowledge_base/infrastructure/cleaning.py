"""Profile-based text rendering without source changes or filesystem access."""

from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
import re
import unicodedata
from urllib.parse import urljoin

from ..domain.contracts import KnowledgeBaseValidationError, SourceRecord
from ..domain.policies import CleanedContent


CLEANING_VERSION = "text-cleaning-v1"
_CMS_MARKERS = {
    f"{label} {boundary}"
    for label in ("日期 發送處", "檔案列表", "週報表", "月報表", "季報表", "年報表", "附件")
    for boundary in ("start", "end")
}
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
_BLOCK = {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "section", "article", "main", "header", "footer", "nav", "pre", "dl", "dt", "dd", "figure", "figcaption"}
_INLINE = {"a", "span", "strong", "b", "em", "i", "u", "s", "small", "sup", "sub", "code", "q", "abbr", "cite", "time", "font", "label", "strike"}
_KNOWN = _VOID | _BLOCK | _INLINE | {"ol", "ul", "li", "table", "thead", "tbody", "tfoot", "tr", "th", "td", "caption", "script", "style", "html", "body"}


def _normalize(text: str, *, title: bool = False) -> str:
    text = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    if title:
        text = text.replace("\n", " ")
    text = re.sub(r"[^\S\n]+", " ", text)
    lines = [line.strip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip("\n")


@dataclass
class _Node:
    tag: str
    attrs: dict[str, str | None] = field(default_factory=dict)
    children: list = field(default_factory=list)


class _Renderer(HTMLParser):
    def __init__(self, source: SourceRecord):
        super().__init__(convert_charrefs=True)
        self.source = source
        self.root = _Node("root")
        self.stack = [self.root]
        self.flags: set[str] = set()
        self.review_flags: set[str] = set()

    def _review(self, flag: str) -> None:
        self.flags.add(flag)
        self.review_flags.add(flag)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if len({name for name, _ in attrs}) != len(attrs):
            self._review("malformed_html_review")
        node = _Node(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag not in _KNOWN:
            self._review("unsupported_html_review")
        if tag not in _VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self._review("malformed_html_review")
            self.stack.pop()

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                if index != len(self.stack) - 1:
                    self._review("malformed_html_review")
                del self.stack[index:]
                return
        self._review("malformed_html_review")

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(data)

    def handle_comment(self, data: str) -> None:
        marker = " ".join(data.split())
        known_cms = self.source.cleaning_profile == "cdc_faq_html_v1" and marker in _CMS_MARKERS
        self.flags.add("cms_noise_removed" if known_cms else "html_comment_removed")

    def _download_ui(self, node: _Node) -> bool:
        if self.source.cleaning_profile != "cdc_faq_html_v1" or node.tag != "div":
            return False
        if "download" not in (node.attrs.get("class") or "").split():
            return False
        attachments = {(item["locator"], _normalize(item["title"]))
                       for item in self.source.attachments if item["title"] is not None}
        headings = links = 0
        for child in node.children:
            if isinstance(child, str):
                if not child.strip():
                    continue
            elif child.tag == "br":
                continue
            elif all(isinstance(part, str) for part in child.children):
                visible = _normalize("".join(child.children))
                if child.tag == "h3" and visible == "附件":
                    headings += 1
                    continue
                if child.tag == "i" and not visible and "fa-paperclip" in (child.attrs.get("class") or "").split():
                    continue
                locator = urljoin(self.source.provenance["source_locator"], child.attrs.get("href") or "")
                if child.tag == "a" and (locator, visible) in attachments:
                    links += 1
                    continue
            # A download class alone cannot prove that every descendant is UI.
            self._review("attachment_panel_review")
            return False
        if headings == 1 and links > 0:
            return True
        self._review("attachment_panel_review")
        return False

    def _children(self, node: _Node, path: tuple[str, ...] = ()) -> str:
        return "".join(child if isinstance(child, str) else self._render(child, path) for child in node.children)

    def _number(self, text: str | None, default: int) -> int:
        if text is None or not re.fullmatch(r"[+-]?[0-9]+", text.strip()):
            self._review("list_structure_review")
            return default
        try:
            return int(text)
        except ValueError:
            self._review("list_structure_review")
            return default

    @staticmethod
    def _marker(path: tuple[str, ...]) -> str:
        if "-" not in path:
            return ".".join(path) + ". "
        return " ".join(part + "." if part != "-" else "-" for part in path) + " "

    def _list(self, node: _Node, path: tuple[str, ...]) -> str:
        if node.tag == "ol" and node.attrs.get("type", "1") != "1":
            self._review("list_structure_review")
        items = [child for child in node.children if isinstance(child, _Node) and child.tag == "li"]
        reversed_order = "reversed" in node.attrs and node.tag == "ol"
        number = len(items) if reversed_order else 1
        if "start" in node.attrs:
            number = self._number(node.attrs["start"], number)
        step = -1 if reversed_order else 1
        output = []
        for child in node.children:
            if isinstance(child, str):
                if child.strip():
                    self._review("list_structure_review")
                    output.append(child + "\n")
                continue
            if child.tag != "li":
                self._review("list_structure_review")
                output.append(self._render(child, path))
                continue
            if node.tag == "ol" and "value" in child.attrs:
                number = self._number(child.attrs["value"], number)
            item_path = path + (str(number) if node.tag == "ol" else "-",)
            body = _normalize(self._children(child, item_path))
            output.append(self._marker(item_path) + body + "\n")
            number += step
        return "\n" + "".join(output) + "\n"

    def _render(self, node: _Node, path: tuple[str, ...] = ()) -> str:
        if node.tag in {"script", "style"}:
            self.flags.add("html_unsafe_content_removed")
            return ""
        if self._download_ui(node):
            self.flags.add("cms_noise_removed")
            return ""
        if node.tag in {"ol", "ul"}:
            return self._list(node, path)
        if node.tag == "table":
            self._review("table_structure_review")
            return "\n" + self._children(node, path) + "\n"
        if node.tag == "tr":
            self._review("table_structure_review")
            cells = []
            for child in node.children:
                if isinstance(child, _Node) and child.tag in {"td", "th"}:
                    cells.append(_normalize(self._children(child, path)).replace("\n", " / "))
                elif isinstance(child, _Node) or child.strip():
                    self._review("malformed_html_review")
                    cells.append(child if isinstance(child, str) else self._render(child, path))
            return "\n" + " | ".join(cells) + "\n"
        if node.tag == "img":
            self._review("image_content_review")
            return node.attrs.get("alt") or ""
        if node.tag == "br":
            return "\n"
        if node.tag == "hr":
            return "\n\n"
        if node.tag in _VOID - {"br", "hr", "wbr"}:
            self._review("unsupported_html_review")
        content = self._children(node, path)
        if node.tag in {"sup", "sub"}:
            self._review("inline_structure_review")
            return ("^(" if node.tag == "sup" else "_(") + content + ")"
        if node.tag == "li":
            self._review("list_structure_review")
            return "\n- " + content + "\n"
        if node.tag in _BLOCK or node.tag == "caption":
            return "\n\n" + content + "\n\n"
        return content

    def render(self, html: str) -> str:
        try:
            self.feed(html)
            self.close()
            if len(self.stack) != 1 or self.rawdata:
                self._review("malformed_html_review")
            return _normalize(self._children(self.root))
        except RecursionError as error:
            raise KnowledgeBaseValidationError("content: HTML nesting is too deep to render safely") from error


def clean_source_record(source: SourceRecord) -> CleanedContent:
    """Return new title/body text and flags; never alter or verify source bytes."""
    if not isinstance(source, SourceRecord):
        raise KnowledgeBaseValidationError("source: must be a SourceRecord")
    title = _normalize(source.title, title=True)
    if source.cleaning_profile == "plain_v1":
        return CleanedContent(title, _normalize(source.content), (), CLEANING_VERSION)
    if source.cleaning_profile not in {"html_v1", "cdc_faq_html_v1"}:
        raise KnowledgeBaseValidationError("cleaning_profile: unsupported profile")
    renderer = _Renderer(source)
    body = renderer.render(source.content)
    if source.cleaning_profile == "cdc_faq_html_v1" and any(" ".join(line.split()) in _CMS_MARKERS for line in body.splitlines()):
        renderer._review("residual_cms_noise")
    return CleanedContent(title, body, tuple(sorted(renderer.flags)), CLEANING_VERSION,
                          review_flags=tuple(sorted(renderer.review_flags)))
