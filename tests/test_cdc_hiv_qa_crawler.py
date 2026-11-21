from __future__ import annotations

from email.message import Message
import importlib.util
import json
from pathlib import Path
import sys
from urllib.error import HTTPError
from urllib.request import Request

import pytest

pytest.importorskip("bs4", reason="install the optional collector extra to run crawler tests")

SCRIPT = Path(__file__).parents[1] / "tools" / "crawl_cdc_hiv_qa.py"
SPEC = importlib.util.spec_from_file_location("cdc_hiv_qa_crawler", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
crawler = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = crawler
SPEC.loader.exec_module(crawler)


def qa_html(question: str = "如何檢查？", *, answer: str | None = None) -> bytes:
    answer = answer or '<div class="date">最後更新日期：2025/2/3</div><p>第一段 &amp; 說明</p><ul><li>項目一</li><li>項目二</li></ul><table><tr><th>項目</th><th>時間</th></tr><tr><td>抽血</td><td>30天</td></tr></table><a href="/File/test.pdf">附件</a>'
    return f'''<!doctype html><html lang="zh-Hant-TW"><div id="accordion">
      <div class="card card-default"><div class="card-heading" id="heading5511"><h3 class="card-title"><span class="word">{question}</span></h3></div>
      <div class="card-collapse" id="collapse5511"><div class="card-body">{answer}</div></div></div>
      <div class="card card-default"><div class="card-heading" id="heading5510"><h3 class="card-title"><span class="word">第二題？</span></h3></div>
      <div class="card-collapse" id="collapse5510"><div class="card-body"><div class="date">最後更新日期：2019/7/28</div><p>第二個答覆。</p></div></div></div>
      </div></html>'''.encode()


def test_parser_keeps_qas_structure_and_uses_question_based_identity() -> None:
    route = crawler.ROUTES[2]
    parsed = crawler.parse_page(qa_html(), route, collected_at="2026-11-21T00:00:00Z")

    assert len(parsed["records"]) == 2
    first = parsed["records"][0]
    assert first["question"] == "如何檢查？"
    assert "項目一" in first["answer_text"]
    assert "項目\t時間" in first["answer_text"]
    assert "抽血\t30天" in first["answer_text"]
    assert "抽血" in first["answer_html"]
    assert first["source_updated_at"] == "2025-02-03"
    assert "最後更新日期" not in first["answer_text"]
    assert first["source_anchor"] == "heading5511"
    assert first["source_faq_id"] == "collapse5511"
    assert first["attachments"] == [{"label": "附件", "url": "https://www.cdc.gov.tw/File/test.pdf"}]
    assert first["id"] == crawler._record_id(route.url, "如何檢查？")
    assert first["collected_at_utc"] == "2026-11-21T00:00:00Z"
    assert parsed["records"][1]["source_updated_at"] == "2019-07-28"
    assert "最後更新日期" not in parsed["records"][1]["answer_html"]


def test_parser_fails_closed_on_missing_main_content_and_zero_qa() -> None:
    with pytest.raises(crawler.CrawlError, match="missing #accordion"):
        crawler.parse_page("<html></html>", crawler.ROUTES[2])
    with pytest.raises(crawler.CrawlError, match="zero records"):
        crawler.parse_page('<html><div id="accordion"></div></html>', crawler.ROUTES[2])


def test_url_scope_rejects_siblings_files_and_external_hosts() -> None:
    for url in (
        "https://www.cdc.gov.tw/Category/QAPage/mQ0KAkiP28-g8WS_TPcEsw",
        "https://www.cdc.gov.tw/File/a.pdf",
        "https://example.org/Category/QAPage/SpEUrQI64Q_EV_DI8NsYTw",
    ):
        with pytest.raises(crawler.CrawlError):
            crawler._canonical_page_url(url)
    assert crawler._canonical_page_url(crawler.ROOT_LIST + "?utm_source=x#heading") == crawler.ROOT_LIST


def test_robots_and_retry_after_policies_are_enforced() -> None:
    assert crawler.HttpClient._retry_after("3") == 3
    with pytest.raises(crawler.CrawlError, match="exceeds configured maximum"):
        crawler.HttpClient._retry_after("1000")

    calls = []
    sleeps = []
    headers = Message()
    headers["Retry-After"] = "4"
    success_headers = {"Content-Type": "text/html"}

    class Response:
        status = 200
        headers = success_headers

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b"ok"

        def geturl(self):
            return crawler.ROOT_LIST

    def opener(request, timeout):
        calls.append(request.full_url)
        if len(calls) == 1:
            raise HTTPError(request.full_url, 429, "limited", headers, None)
        return Response()

    now = [10.0]

    def sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds

    client = crawler.HttpClient(opener=opener, sleep=sleep, clock=lambda: now[0])
    status, result_headers, body = client.get(crawler.ROOT_LIST)
    assert (status, result_headers, body) == (200, success_headers, b"ok")
    assert calls == [crawler.ROOT_LIST, crawler.ROOT_LIST]
    assert sleeps == [4.0]


def test_redirect_target_is_rejected_before_following() -> None:
    with pytest.raises(crawler.CrawlError, match="outside the approved HTTPS host"):
        crawler.ScopedRedirectHandler().redirect_request(
            Request(crawler.ROOT_LIST), None, 302, "Found", {}, "https://example.org/collect"
        )
    with pytest.raises(crawler.CrawlError, match="changed the requested source URL"):
        crawler.ScopedRedirectHandler().redirect_request(
            Request(crawler.ROOT_LIST), None, 302, "Found", {}, crawler.ROUTES[2].url
        )


class FakeClient:
    def __init__(self, *, fail_url: str | None = None):
        self.fail_url = fail_url
        self.calls: list[str] = []

    def get(self, url: str):
        self.calls.append(url)
        if url == self.fail_url:
            raise crawler.CrawlError("fixture network failure")
        if url == crawler.ROBOTS_URL:
            return 200, {"Content-Type": "text/plain"}, b"User-agent: *\nAllow: /*\nDisallow: /File/\nDisallow: /Uploads/\n"
        if url.endswith("/Category/List/qTp6DeK3rmOlqcVc7diAkA") or url.endswith("/Category/List/1FuOwO6RRWN2gq9ULJ1Srw"):
            body = b'<html><div id="accordion"></div></html>'
        else:
            body = qa_html(question=f"{url.rsplit('/', 1)[-1]} question")
        return 200, {"Content-Type": "text/html; charset=utf-8", "ETag": '"fixture"'}, body


def test_collect_resume_uses_snapshot_hash_without_duplicate_records(tmp_path: Path) -> None:
    output = tmp_path / "snapshot"
    first = crawler.collect(output, client=FakeClient())
    qa_path = output / "qa.jsonl"
    original_records = [json.loads(line) for line in qa_path.read_text(encoding="utf-8").splitlines()]
    assert first["complete"] is True
    assert len(original_records) == 22

    resumed = crawler.collect(output, resume=True, client=FakeClient())
    records = [json.loads(line) for line in qa_path.read_text(encoding="utf-8").splitlines()]
    assert resumed["complete"] is True
    assert len(records) == len(original_records)
    assert all(page.get("resumed_from_cache") for page in resumed["pages"] if page["kind"] == "qa")
    assert len(list((output / "raw").glob("*.html"))) == len(crawler.ROUTES) + len(crawler.POLICY_URLS)


def test_failed_policy_resume_preserves_page_cache_for_next_attempt(tmp_path: Path) -> None:
    output = tmp_path / "snapshot"
    crawler.collect(output, client=FakeClient())
    qa_path = output / "qa.jsonl"
    original_qa = qa_path.read_text(encoding="utf-8")
    original_manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))

    second_policy = crawler.POLICY_URLS[1]
    second_policy_entry = next(item for item in original_manifest["policy_provenance"] if item["url"] == second_policy)
    (output / second_policy_entry["raw_snapshot"]).unlink()
    with pytest.raises(crawler.CrawlError, match="fixture network failure"):
        crawler.collect(output, resume=True, client=FakeClient(fail_url=second_policy))

    interrupted = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert interrupted["errors"][0]["url"] == second_policy
    assert {page["url"] for page in interrupted["pages"]} == {route.url for route in crawler.ROUTES}
    assert qa_path.read_text(encoding="utf-8") == original_qa

    retry_client = FakeClient()
    final = crawler.collect(output, resume=True, client=retry_client)
    assert final["complete"] is True
    assert qa_path.read_text(encoding="utf-8") == original_qa
    assert retry_client.calls == [crawler.ROBOTS_URL, second_policy]


def test_collect_failure_keeps_partial_manifest_and_exit_state(tmp_path: Path) -> None:
    output = tmp_path / "partial"
    failure_url = crawler.ROUTES[2].url
    with pytest.raises(crawler.CrawlError, match="fixture network failure"):
        crawler.collect(output, client=FakeClient(fail_url=failure_url))
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["complete"] is False
    assert manifest["errors"][0]["url"] == failure_url
    assert (output / "qa.jsonl").is_file()


def test_robots_failure_is_persisted_as_incomplete_manifest(tmp_path: Path) -> None:
    output = tmp_path / "robots-failure"

    class DisallowedClient(FakeClient):
        def get(self, url: str):
            if url == crawler.ROBOTS_URL:
                return 200, {"Content-Type": "text/plain"}, b"User-agent: *\nDisallow: /Category/\n"
            return super().get(url)

    with pytest.raises(crawler.CrawlError, match="robots.txt disallows"):
        crawler.collect(output, client=DisallowedClient())
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["complete"] is False
    assert manifest["errors"][0]["url"] == crawler.ROBOTS_URL


def test_existing_snapshot_requires_explicit_resume_or_new_path(tmp_path: Path) -> None:
    output = tmp_path / "snapshot"
    crawler.collect(output, client=FakeClient())
    with pytest.raises(crawler.CrawlError, match="already exists"):
        crawler.collect(output, client=FakeClient())
