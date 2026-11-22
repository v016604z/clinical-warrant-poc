"""Collect the explicitly scoped Taiwan CDC HIV knowledge and prevention pages.

This is a research data collector, not part of the clinical-warrant runtime.
Run with ``pip install -e '.[collect]'`` and pass an explicit output directory.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from copy import deepcopy
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen
from urllib.robotparser import RobotFileParser

try:
    from bs4 import BeautifulSoup, NavigableString, Tag
except ImportError as error:  # pragma: no cover - exercised by CLI smoke test
    raise SystemExit("Install the collector extra: python -m pip install -e '.[collect]'") from error


BASE_URL = "https://www.cdc.gov.tw"
ROOT_LIST = f"{BASE_URL}/Category/List/qTp6DeK3rmOlqcVc7diAkA"
ROBOTS_URL = f"{BASE_URL}/robots.txt"
OPEN_DATA_URL = f"{BASE_URL}/Category/FPage/TxkBIR9agw_IBRRmvn9TcQ"
COPYRIGHT_URL = f"{BASE_URL}/Category/FPage/rvmij-b1qdDYyX_Olv67VQ"
POLICY_URLS = (OPEN_DATA_URL, COPYRIGHT_URL)
USER_AGENT = "clinical-warrant-poc-research-collector/1.0"
MIN_REQUEST_INTERVAL = 2.0
REQUEST_TIMEOUT = 20.0
MAX_RETRIES = 3
MAX_RETRY_AFTER = 60.0
ATTACHMENT_EXTENSIONS = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip"}


@dataclass(frozen=True)
class Route:
    path: str
    label: str
    kind: str

    @property
    def url(self) -> str:
        return f"{BASE_URL}{self.path}"


# Fixed routes prevent following the site's shared navigation/sidebar into sibling topics.
ROUTES = (
    Route("/Category/List/qTp6DeK3rmOlqcVc7diAkA", "愛滋知識與預防篇", "category"),
    Route("/Category/List/1FuOwO6RRWN2gq9ULJ1Srw", "認識愛滋", "category"),
    Route("/Category/QAPage/SpEUrQI64Q_EV_DI8NsYTw", "認識愛滋／愛滋病毒與愛滋病", "qa"),
    Route("/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA", "認識愛滋／傳染途徑", "qa"),
    Route("/Category/QAPage/tN3OCfprezBUk9jVnWC8Yg", "認識愛滋／不會傳染的途徑", "qa"),
    Route("/Category/QAPage/My0uZvjAFs11NWjujWXvBg", "認識愛滋／空窗期", "qa"),
    Route("/Category/QAPage/fV5yD36S7dZuzHVcqFgQ-Q", "認識愛滋／可能感染的症狀", "qa"),
    Route("/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ", "愛滋篩檢服務", "qa"),
    Route("/Category/QAPage/qcdRrymODh9YF69ewsA5Qw", "預防母子垂直感染", "qa"),
    Route("/Category/QAPage/NmDr6gAiK-xPxaejvJ-Lqw", "藥癮愛滋減害", "qa"),
    Route("/Category/QAPage/PGwKHMNjHuzGO9hgvJKK4w", "PrEP／認識PrEP", "qa"),
    Route("/Category/QAPage/pzjkJa4dgVjdk6emQjM-3g", "PrEP／PrEP計畫服務", "qa"),
    Route("/Category/QAPage/JQc1_rTZWlHX9-hw4U_4yg", "PEP／暴露後預防性投藥", "qa"),
)
ALLOWED_PATHS = {route.path for route in ROUTES} | {urlsplit(url).path for url in POLICY_URLS}


class CrawlError(RuntimeError):
    """Raised when collection cannot be completed safely or reliably."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_page_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname != "www.cdc.gov.tw":
        raise CrawlError(f"URL is outside the approved HTTPS host: {url}")
    path = parts.path.rstrip("/") or "/"
    if path.startswith(("/File/", "/Uploads/")) or path not in ALLOWED_PATHS:
        raise CrawlError(f"URL is outside the approved page scope: {url}")
    return urlunsplit(("https", "www.cdc.gov.tw", path, "", ""))


def _record_id(page_url: str, question: str) -> str:
    normalized = " ".join(question.split()).casefold()
    return _sha256(f"{page_url}\n{normalized}".encode("utf-8"))


def _source_date(node: Tag | None) -> str | None:
    if node is None:
        return None
    match = re.search(r"(?:最後更新日期|更新日期)\s*[:：]?\s*(\d{4})/(\d{1,2})/(\d{1,2})", node.get_text(" ", strip=True))
    if not match:
        return None
    year, month, day = (int(part) for part in match.groups())
    return f"{year:04d}-{month:02d}-{day:02d}"


def _text_with_structure(node: Tag) -> str:
    """Render HTML text while retaining list and table row/cell boundaries."""

    def render(child: Tag | NavigableString) -> str:
        if isinstance(child, NavigableString):
            return str(child)
        if not isinstance(child, Tag):
            return ""
        name = child.name.lower()
        if name in {"script", "style", "noscript"}:
            return ""
        content = "".join(render(part) for part in child.children)
        if name == "br":
            return "\n"
        if name == "li":
            return f"\n- {content.strip()}"
        if name in {"td", "th"}:
            return f"\t{content.strip()}"
        if name == "tr":
            return f"\n{content.strip()}"
        if name in {"p", "div", "section", "ul", "ol", "h1", "h2", "h3", "h4"}:
            return f"\n{content}\n"
        return content

    text = render(node)
    lines = [re.sub(r"[ \xa0]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def _attachments(body: Tag, page_url: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for link in body.select("a[href]"):
        href = urljoin(page_url, str(link.get("href", "")))
        parts = urlsplit(href)
        if parts.hostname != "www.cdc.gov.tw":
            continue
        if parts.path.startswith(("/File/", "/Uploads/")) or Path(parts.path).suffix.lower() in ATTACHMENT_EXTENSIONS:
            items.append({"label": link.get_text(" ", strip=True), "url": href})
    return items


def parse_page(html: bytes | str, route: Route, *, collected_at: str | None = None) -> dict:
    """Parse one approved page; fail closed when its expected main content is absent."""
    page_url = _canonical_page_url(route.url)
    soup = BeautifulSoup(html, "html.parser")
    accordion = soup.select_one("#accordion")
    if accordion is None:
        if route.kind == "category" and soup.select_one(".con-title") is not None:
            raw = html.encode("utf-8") if isinstance(html, str) else html
            return {"page_url": page_url, "html_sha256": _sha256(raw), "records": [], "duplicates_skipped": 0}
        raise CrawlError(f"missing #accordion main content: {route.url}")

    cards = accordion.select(":scope > .card.card-default")
    records: list[dict] = []
    seen_questions: set[str] = set()
    duplicates_skipped = 0
    global_date = next((node for node in soup.select(".date") if node.find_parent(class_="card") is None), None)
    page_updated_at = _source_date(global_date)

    for card in cards:
        heading = card.select_one('.card-heading[id^="heading"]')
        question_node = card.select_one("h3.card-title .word") or card.select_one("h3.card-title")
        body = card.select_one('.card-collapse[id^="collapse"] .card-body') or card.select_one(".card-body")
        if question_node is None or body is None:
            raise CrawlError(f"incomplete QA card on {route.url}")
        question = question_node.get_text(" ", strip=True)
        answer_body = deepcopy(body)
        for date_node in answer_body.select(".date"):
            date_node.decompose()
        answer_text = _text_with_structure(answer_body)
        if not question or not answer_text:
            raise CrawlError(f"empty question or answer on {route.url}")
        record_id = _record_id(page_url, question)
        if record_id in seen_questions:
            duplicates_skipped += 1
            continue
        seen_questions.add(record_id)
        anchor = str(heading.get("id", "")) if heading else ""
        collapse = card.select_one('.card-collapse[id^="collapse"]')
        faq_id = str(collapse.get("id", "")) if collapse else ""
        answer_html = answer_body.decode_contents().strip()
        source_updated_at = _source_date(card.select_one(".date")) or page_updated_at
        content_hash = _sha256((question + "\n" + answer_html).encode("utf-8"))
        source_url = f"{page_url}#{anchor}" if anchor else page_url
        records.append(
            {
                "id": record_id,
                "question": question,
                "answer_text": answer_text,
                "answer_html": answer_html,
                "source_url": source_url,
                "page_url": page_url,
                "category": route.label,
                "source_updated_at": source_updated_at,
                "collected_at_utc": collected_at or _utc_now(),
                "content_sha256": content_hash,
                "source_anchor": anchor or None,
                "source_faq_id": faq_id or None,
                "attachments": _attachments(body, page_url),
            }
        )

    if route.kind == "qa" and not records:
        raise CrawlError(f"expected Q&A content but parsed zero records: {route.url}")
    return {
        "page_url": page_url,
        "html_sha256": _sha256(html.encode("utf-8") if isinstance(html, str) else html),
        "records": records,
        "duplicates_skipped": duplicates_skipped,
    }


class HttpClient:
    """Single sequential HTTP client with politeness delay and bounded retries."""

    def __init__(self, *, opener: Callable | None = None, sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic):
        self._opener = opener or build_opener(ScopedRedirectHandler()).open
        self._sleep = sleep
        self._clock = clock
        self._last_request_at: float | None = None

    def _pace(self) -> None:
        if self._last_request_at is not None:
            delay = MIN_REQUEST_INTERVAL - (self._clock() - self._last_request_at)
            if delay > 0:
                self._sleep(delay)
        self._last_request_at = self._clock()

    def get(self, url: str) -> tuple[int, dict[str, str], bytes]:
        for attempt in range(MAX_RETRIES + 1):
            self._pace()
            request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.8"})
            try:
                response = self._opener(request, timeout=REQUEST_TIMEOUT)
                with response:
                    final_url = response.geturl()
                    if final_url != url:
                        if url == ROBOTS_URL or _canonical_page_url(final_url) != _canonical_page_url(url):
                            raise CrawlError(f"redirect changed the requested source URL: {url} -> {final_url}")
                    return response.status, dict(response.headers.items()), response.read()
            except HTTPError as error:
                if error.code == 429:
                    wait = self._retry_after(error.headers.get("Retry-After"))
                elif error.code in {500, 502, 503, 504}:
                    wait = min(2**attempt, MAX_RETRY_AFTER)
                else:
                    raise CrawlError(f"HTTP {error.code} for {url}") from error
                if attempt >= MAX_RETRIES:
                    raise CrawlError(f"retry limit reached after HTTP {error.code}: {url}") from error
                self._sleep(wait)
            except (TimeoutError, URLError) as error:
                if attempt >= MAX_RETRIES:
                    raise CrawlError(f"request failed after retries: {url}: {error}") from error
                self._sleep(min(2**attempt, MAX_RETRY_AFTER))
        raise AssertionError("unreachable")

    @staticmethod
    def _retry_after(value: str | None) -> float:
        if value is None:
            return 1.0
        try:
            seconds = float(value)
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(value)
                seconds = (retry_at - datetime.now(timezone.utc)).total_seconds()
            except (TypeError, ValueError, OverflowError) as error:
                raise CrawlError(f"invalid Retry-After value: {value}") from error
        seconds = max(0.0, seconds)
        if seconds > MAX_RETRY_AFTER:
            raise CrawlError(f"Retry-After exceeds configured maximum ({MAX_RETRY_AFTER:g}s)")
        return seconds


def _check_robots(client: HttpClient) -> tuple[RobotFileParser, dict]:
    status, headers, raw = client.get(ROBOTS_URL)
    if status != 200:
        raise CrawlError(f"could not verify robots.txt (HTTP {status})")
    text = raw.decode("utf-8-sig", errors="replace")
    parser = RobotFileParser(ROBOTS_URL)
    parser.parse(text.splitlines())
    if any(not parser.can_fetch(USER_AGENT, url) for url in [route.url for route in ROUTES] + list(POLICY_URLS)):
        raise CrawlError("robots.txt disallows an approved route; refusing to crawl")
    return parser, {"url": ROBOTS_URL, "status": status, "sha256": _sha256(raw), "etag": headers.get("ETag"), "last_modified": headers.get("Last-Modified")}


class ScopedRedirectHandler(HTTPRedirectHandler):
    """Validate redirect targets before urllib sends a follow-up request."""

    def redirect_request(self, request, response, code, message, headers, new_url):
        target = urljoin(request.full_url, new_url)
        if request.full_url == ROBOTS_URL:
            if target != ROBOTS_URL:
                raise CrawlError(f"robots.txt redirect changed source URL: {request.full_url} -> {target}")
        elif _canonical_page_url(target) != _canonical_page_url(request.full_url):
            raise CrawlError(f"redirect changed the requested source URL: {request.full_url} -> {target}")
        return super().redirect_request(request, response, code, message, headers, target)


def _write_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _write_text(path: Path, text: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def _upsert_entry(entries: list[dict], entry: dict, key: str) -> None:
    for index, current in enumerate(entries):
        if current.get(key) == entry.get(key):
            entries[index] = entry
            return
    entries.append(entry)


def _prepare_output(output_dir: Path, resume: bool) -> tuple[Path, Path, dict, dict[str, dict]]:
    if output_dir.exists():
        if not resume:
            raise CrawlError(f"output directory already exists; use --resume or choose a new snapshot path: {output_dir}")
        manifest_path = output_dir / "manifest.json"
        qa_path = output_dir / "qa.jsonl"
        if not manifest_path.is_file() or not qa_path.is_file():
            raise CrawlError("--resume requires an existing manifest.json and qa.jsonl")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        old_records = [json.loads(line) for line in qa_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        by_page = {route.url: [] for route in ROUTES}
        for record in old_records:
            by_page.setdefault(record["page_url"], []).append(record)
        return manifest_path, qa_path, manifest, by_page
    output_dir.mkdir(parents=True)
    (output_dir / "raw").mkdir()
    (output_dir / "qa.jsonl").write_text("", encoding="utf-8")
    return output_dir / "manifest.json", output_dir / "qa.jsonl", {}, {route.url: [] for route in ROUTES}


def collect(output_dir: Path, *, resume: bool = False, client: HttpClient | None = None) -> dict:
    client = client or HttpClient()
    output_dir = output_dir.resolve()
    manifest_path, qa_path, previous, prior_by_page = _prepare_output(output_dir, resume)
    raw_dir = output_dir / "raw"
    raw_dir.mkdir(exist_ok=True)
    started_at = _utc_now()
    manifest = {
        "schema_version": 1,
        "source": "Taiwan CDC HIV knowledge and prevention pages",
        "scope_root": ROOT_LIST,
        "scope_routes": [asdict(route) | {"url": route.url} for route in ROUTES],
        "robots": None,
        "reuse_policy_urls": list(POLICY_URLS),
        "attribution": "Source: Taiwan Centers for Disease Control (CDC Taiwan); see each source_url.",
        "started_at_utc": started_at,
        "completed_at_utc": None,
        "complete": False,
        "pages": list(previous.get("pages", [])),
        "page_hashes": dict(previous.get("page_hashes", {})),
        "policy_provenance": list(previous.get("policy_provenance", [])),
        "duplicates_skipped": 0,
        "errors": [],
    }
    if previous:
        manifest["previous_snapshot_started_at_utc"] = previous.get("started_at_utc")
    records_by_id: dict[str, dict] = {
        record["id"]: record
        for records in prior_by_page.values()
        for record in records
    }
    previous_pages = {page["url"]: page for page in previous.get("pages", [])}

    try:
        _, robots = _check_robots(client)
        manifest["robots"] = robots
        _write_json(manifest_path, manifest)
        # Preserve the two agency policy pages used to document reuse constraints.
        old_policy = {entry["url"]: entry for entry in manifest["policy_provenance"]}
        for policy_url in POLICY_URLS:
            entry = old_policy.get(policy_url)
            cached_path = output_dir / entry["raw_snapshot"] if entry and entry.get("raw_snapshot") else None
            if resume and cached_path and cached_path.is_file() and _sha256(cached_path.read_bytes()) == entry.get("html_sha256"):
                _upsert_entry(manifest["policy_provenance"], entry | {"resumed_from_cache": True}, "url")
                _write_json(manifest_path, manifest)
                continue
            try:
                status, headers, raw = client.get(policy_url)
                content_type = headers.get("Content-Type", "")
                if status != 200 or "text/html" not in content_type.lower():
                    raise CrawlError(f"could not snapshot reuse policy page: {policy_url} (HTTP {status}, {content_type})")
                digest = _sha256(raw)
                snapshot_name = f"policy-{_sha256(policy_url.encode())[:12]}-{digest[:16]}.html"
                snapshot_path = raw_dir / snapshot_name
                if not snapshot_path.exists():
                    with snapshot_path.open("xb") as snapshot:
                        snapshot.write(raw)
                policy_entry = {"url": policy_url, "status": status, "fetched_at_utc": _utc_now(), "html_sha256": digest, "raw_snapshot": f"raw/{snapshot_name}", "etag": headers.get("ETag"), "last_modified": headers.get("Last-Modified")}
                _upsert_entry(manifest["policy_provenance"], policy_entry, "url")
                _write_json(manifest_path, manifest)
            except Exception as error:
                manifest["errors"].append({"url": policy_url, "error": str(error)})
                _write_json(manifest_path, manifest)
                raise

        for route in ROUTES:
            fetched_at = _utc_now()
            page_entry = {"url": route.url, "kind": route.kind, "category": route.label, "status": None, "fetched_at_utc": fetched_at, "qa_count": 0}
            try:
                allowed_url = _canonical_page_url(route.url)
                cached_entry = previous_pages.get(route.url)
                cached_snapshot = output_dir / cached_entry["raw_snapshot"] if cached_entry and cached_entry.get("raw_snapshot") else None
                cached_raw = cached_snapshot.read_bytes() if resume and cached_snapshot and cached_snapshot.is_file() else None
                if cached_raw is not None and _sha256(cached_raw) == cached_entry.get("html_sha256"):
                    status = cached_entry.get("status", 200)
                    headers = {"ETag": cached_entry.get("etag"), "Last-Modified": cached_entry.get("last_modified"), "Content-Type": "text/html; charset=utf-8"}
                    raw = cached_raw
                    page_entry["resumed_from_cache"] = True
                else:
                    status, headers, raw = client.get(allowed_url)
                page_entry.update({"status": status, "etag": headers.get("ETag"), "last_modified": headers.get("Last-Modified"), "html_sha256": _sha256(raw)})
                if status != 200:
                    raise CrawlError(f"expected HTTP 200, received HTTP {status}")
                content_type = headers.get("Content-Type", "")
                if "text/html" not in content_type.lower():
                    raise CrawlError(f"expected text/html, received {content_type or 'no content type'}")
                snapshot_name = f"{_sha256(allowed_url.encode())[:16]}-{page_entry['html_sha256'][:16]}.html"
                snapshot_path = raw_dir / snapshot_name
                if not snapshot_path.exists():
                    with snapshot_path.open("xb") as snapshot:
                        snapshot.write(raw)
                parsed = parse_page(raw, route, collected_at=fetched_at)
                manifest["duplicates_skipped"] += parsed["duplicates_skipped"]
                page_entry.update({"raw_snapshot": f"raw/{snapshot_name}", "qa_count": len(parsed["records"])})
                old_page_records = prior_by_page.get(route.url, [])
                if not page_entry.get("resumed_from_cache"):
                    for old_record in old_page_records:
                        records_by_id.pop(old_record["id"], None)
                    for record in parsed["records"]:
                        record["raw_snapshot"] = page_entry["raw_snapshot"]
                        records_by_id[record["id"]] = record
                _upsert_entry(manifest["pages"], page_entry, "url")
            except Exception as error:
                manifest["errors"].append({"url": route.url, "error": str(error)})
                if not any(page.get("url") == route.url for page in manifest["pages"]):
                    page_entry["error"] = str(error)
                    _upsert_entry(manifest["pages"], page_entry, "url")
                _write_json(manifest_path, manifest)
                raise
            manifest["page_hashes"] = {page["url"]: page["html_sha256"] for page in manifest["pages"] if page.get("html_sha256")}
            _write_text(qa_path, "\n".join(json.dumps(record, ensure_ascii=False, sort_keys=True) for record in records_by_id.values()) + ("\n" if records_by_id else ""))
            _write_json(manifest_path, manifest)
    except Exception as error:
        if not manifest["errors"]:
            failed_url = ROBOTS_URL if manifest["robots"] is None else "collection"
            manifest["errors"].append({"url": failed_url, "error": str(error)})
        manifest["completed_at_utc"] = _utc_now()
        manifest["complete"] = False
        _write_json(manifest_path, manifest)
        raise

    manifest["completed_at_utc"] = _utc_now()
    manifest["complete"] = len(manifest["pages"]) == len(ROUTES) and not manifest["errors"]
    manifest["qa_count"] = len(records_by_id)
    manifest["page_hashes"] = {page["url"]: page["html_sha256"] for page in manifest["pages"] if page.get("html_sha256")}
    _write_text(qa_path, "\n".join(json.dumps(record, ensure_ascii=False, sort_keys=True) for record in records_by_id.values()) + ("\n" if records_by_id else ""))
    _write_json(manifest_path, manifest)
    return manifest


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect the Taiwan CDC HIV knowledge and prevention pages.")
    parser.add_argument("--output-dir", type=Path, required=True, help="new snapshot directory (for example src/clinical_warrant/data/tw_cdc_hiv_qa_new)")
    parser.add_argument("--resume", action="store_true", help="reuse hash-verified raw pages and fetch only missing pages; use a new output directory for a fresh snapshot")
    args = parser.parse_args(argv)
    try:
        manifest = collect(args.output_dir, resume=args.resume)
    except (CrawlError, OSError, json.JSONDecodeError) as error:
        print(f"crawl failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"output_dir": str(args.output_dir), "complete": manifest["complete"], "qa_count": manifest.get("qa_count", 0)}, ensure_ascii=False))
    return 0 if manifest["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
