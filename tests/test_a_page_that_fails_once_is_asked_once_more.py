# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1337` — `fetch_webpage_content`'s `retry_attempt` named a retry nobody wrote.

The parameter reached three log lines and nothing else: `comprehensive_web_search`
submitted every fetch with `retry_attempt=0` and never resubmitted, so a page
that timed out once was *Not fetched … NetworkError* for that search. Now a
transient failure — a transport error, a 500/502/503/504 — is asked once more
as attempt 1; a 429 (the host saying stop) and a 403 (which will not change)
are not.

Driven through the real `fetch_webpage_content` and the live search path
(`comprehensive_web_search`) with only the far end replaced: `_get_public_url`,
the one function that would open a socket, answers from a script and counts
how often it was asked. The content cache is a temp directory.
"""
from __future__ import annotations

import httpx
import pytest

from services.search import content, core
from src.outbound_fetch import _CappedFetch

_URL = "https://pages.example.test/article"
_HTML = (b"<html><head><title>Asyncio</title></head><body><article class='content'>"
         + b"An event loop runs coroutines. " * 40 + b"</article></body></html>")


def _page(status=200, body=_HTML):
    return _CappedFetch(status, {"Content-Type": "text/html"}, body, False, None, "utf-8", _URL)


@pytest.fixture
def far_end(monkeypatch, tmp_path):
    """`answers` is the script; `asked` counts the requests the page got."""
    monkeypatch.setattr(content, "CONTENT_CACHE_DIR", tmp_path)
    content.content_cache_index.clear()
    state = {"answers": [], "asked": 0}

    def _get(url, headers, timeout, **kwargs):
        state["asked"] += 1
        answer = state["answers"].pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(content, "_get_public_url", _get)
    yield state
    content.content_cache_index.clear()


def test_a_page_that_times_out_once_then_answers_yields_content(far_end):
    """The row's `Verify:`, first half."""
    far_end["answers"] = [httpx.ReadTimeout("read timed out"), _page()]
    out = content.fetch_webpage_content(_URL, 8)
    assert out["success"] is True and "event loop" in out["content"]
    assert far_end["asked"] == 2


def test_a_gateway_error_once_then_an_answer_yields_content(far_end):
    far_end["answers"] = [_page(503, b"busy"), _page()]
    out = content.fetch_webpage_content(_URL, 8)
    assert out["success"] is True
    assert far_end["asked"] == 2


def test_a_429_is_not_asked_again(far_end):
    """The row's `Verify:`, second half."""
    far_end["answers"] = [_page(429, b"slow down"), _page()]
    out = content.fetch_webpage_content(_URL, 8)
    assert out["success"] is False and "Rate limit" in out["error"]
    assert far_end["asked"] == 1


def test_a_403_is_not_asked_again(far_end):
    far_end["answers"] = [_page(403, b"no"), _page()]
    out = content.fetch_webpage_content(_URL, 8)
    assert out["success"] is False and out["error"].startswith("HTTP 403")
    assert far_end["asked"] == 1


def test_a_refused_address_is_not_asked_again(far_end):
    """The SSRF guard's refusals are a bare `RequestError`: policy, not weather."""
    far_end["answers"] = [httpx.RequestError("Blocked non-public URL: http://10.0.0.1/"), _page()]
    out = content.fetch_webpage_content(_URL, 8)
    assert out["success"] is False and "Blocked non-public" in out["error"]
    assert far_end["asked"] == 1


def test_one_retry_only(far_end):
    """Twice down is down: the second failure is the answer, said by attempt."""
    far_end["answers"] = [httpx.ConnectError("refused"), httpx.ConnectError("refused"), _page()]
    out = content.fetch_webpage_content(_URL, 8)
    assert out["success"] is False and out["error"].startswith("NetworkError")
    assert far_end["asked"] == 2


def test_the_live_search_path_gets_the_page_on_its_second_ask(far_end, monkeypatch, tmp_path):
    """Through `comprehensive_web_search`: a search whose one result timed out
    once hands the model that page, not *Not fetched … NetworkError*."""
    search_dir = tmp_path / "search"
    search_dir.mkdir()
    monkeypatch.setattr(core, "SEARCH_CACHE_DIR", search_dir, raising=False)
    monkeypatch.setattr(core, "_get_search_settings", lambda: {"search_provider": "searxng"},
                        raising=False)
    monkeypatch.setattr(core, "_get_result_count", lambda: 5, raising=False)
    monkeypatch.setattr(core, "_call_provider",
                        lambda name, q, count, time_filter=None: [
                            {"title": "Asyncio", "url": _URL, "snippet": "event loop"}])
    core.search_cache_index.clear()
    far_end["answers"] = [httpx.ConnectTimeout("connect timed out"), _page()]

    said = core.comprehensive_web_search("python asyncio event loop", max_pages=1)

    text = said if isinstance(said, str) else str(said)
    assert "An event loop runs coroutines" in text, text[:2000]
    assert "NetworkError" not in text
    core.search_cache_index.clear()
