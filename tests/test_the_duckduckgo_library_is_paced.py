# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1541` — DuckDuckGo's library path goes through the outbound limiter.

`providers.duckduckgo_search` called `ddgs.DDGS().text(…)`, whose HTTP is the
library's own: it bypassed `paced_http` — sent while DuckDuckGo cooled down,
unpaced, its rate limit never told the limiter — and `check-outbound`, which
saw no `httpx` in it. Now the call runs inside `paced_http.call_sync` on the
HTML fallback's host, a library rate limit is one cooldown step and a
`RateLimitError` the chain moves past, and `check-outbound` sees a `ddgs` call.

Driven through the real `duckduckgo_search`, `paced_http` and a fresh
`OutboundHostLimiter`. The library itself is not installed in this
environment (it is an optional extra, `requirements-optional.txt`), so a
stand-in `ddgs` module records what it is asked; the HTML fallback's socket is
replaced as `B1533`'s test replaces it (`httpx.Client.request`).
"""
import ast
import importlib.util
import sys
import types
from pathlib import Path

import httpx
import pytest

import src.rate_limiter as rate_limiter
from services.search import providers
from services.search.analytics import RateLimitError

ROOT = Path(__file__).resolve().parents[1]
HOST = "html.duckduckgo.com"


class _LibraryRateLimited(Exception):
    """What `ddgs.exceptions.RatelimitException` is to the code under test."""


@pytest.fixture
def limiter(monkeypatch, tmp_path):
    import src.constants as constants

    monkeypatch.setattr(constants, "OUTBOUND_STATE_FILE", str(tmp_path / "outbound.json"))
    fresh = rate_limiter.OutboundHostLimiter()
    monkeypatch.setattr(rate_limiter, "outbound", fresh)
    return fresh


@pytest.fixture
def library(monkeypatch):
    """A stand-in `ddgs`: `DDGS().text` records its call and answers
    `library.answer` (a list, or an exception to raise)."""
    calls = []

    class DDGS:
        def text(self, query, **kwargs):
            calls.append((query, kwargs))
            if isinstance(library.answer, Exception):
                raise library.answer
            return library.answer

    pkg = types.ModuleType("ddgs")
    pkg.DDGS = DDGS
    exceptions = types.ModuleType("ddgs.exceptions")
    exceptions.RatelimitException = _LibraryRateLimited
    pkg.exceptions = exceptions
    monkeypatch.setitem(sys.modules, "ddgs", pkg)
    monkeypatch.setitem(sys.modules, "ddgs.exceptions", exceptions)
    monkeypatch.setattr(providers, "_safesearch_for", lambda *_a, **_k: "moderate", raising=False)
    library.calls = calls
    library.answer = [{"title": "Tides", "href": "https://example.org/tides", "body": "Low at 4"}]
    return library


@pytest.fixture
def wire(monkeypatch):
    sent = []

    def request(self, method, url, **kwargs):
        sent.append((method, str(url)))
        return httpx.Response(200, text="<html></html>", request=httpx.Request(method, str(url)))

    monkeypatch.setattr(httpx.Client, "request", request)
    return sent


def test_with_duckduckgo_cooling_down_a_search_sends_no_request(limiter, library, wire):
    limiter.observe(HOST, 429, {"Retry-After": "600"})

    with pytest.raises(RateLimitError):
        providers.duckduckgo_search("tide tables", 5)

    assert library.calls == [], "the library was asked while DuckDuckGo cools down"
    assert wire == [], "the HTML fallback was asked while DuckDuckGo cools down"


def test_the_library_call_is_paced_and_asks_duckduckgo_only(limiter, library, wire):
    out = providers.duckduckgo_search("tide tables", 5)

    assert out == [{"title": "Tides", "url": "https://example.org/tides", "snippet": "Low at 4"}]
    assert limiter._st(HOST).total_requests == 1, "the call did not pass the limiter"
    (query, kwargs), = library.calls
    assert kwargs["backend"] == "duckduckgo", "the person chose DuckDuckGo, not a metasearch"
    assert wire == []


def test_a_library_rate_limit_is_one_cooldown_step_and_the_chain_moves_on(limiter, library, wire):
    library.answer = _LibraryRateLimited("202 Ratelimit")

    with pytest.raises(RateLimitError):
        providers.duckduckgo_search("tide tables", 5)

    assert limiter._st(HOST).consecutive_429 == 1
    assert 55 <= limiter.blocked_for(HOST) <= 60
    assert wire == [], "the same service's HTML page was asked straight after it said stop"


def test_a_library_failure_that_is_not_a_limit_still_falls_back(limiter, library, wire):
    library.answer = RuntimeError("unexpected markup")
    assert providers.duckduckgo_search("tide tables", 5) == []
    assert [u.split("?")[0] for _m, u in wire] == ["https://html.duckduckgo.com/html/"]


# ── check-outbound sees it ──────────────────────────────────────────────────

def _checker():
    spec = importlib.util.spec_from_file_location("_check_outbound_b1541",
                                                  ROOT / ".pantheon" / "check-outbound.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_check_outbound_counts_a_bare_library_call_and_not_a_paced_one(tmp_path, monkeypatch):
    co = _checker()
    bare = tmp_path / "bare.py"
    bare.write_text(
        "def duckduckgo_search(query):\n"
        "    fallback = 'https://html.duckduckgo.com/html/'\n"
        "    from ddgs import DDGS\n"
        "    ddgs = DDGS()\n"
        "    return ddgs.text(query, max_results=5)\n", encoding="utf-8")
    paced = tmp_path / "paced.py"
    paced.write_text(
        "def duckduckgo_search(query):\n"
        "    fallback = 'https://html.duckduckgo.com/html/'\n"
        "    from ddgs import DDGS\n"
        "    return paced_http.call_sync('html.duckduckgo.com', DDGS().text, query)\n",
        encoding="utf-8")
    monkeypatch.setattr(co, "ROOT", tmp_path)
    monkeypatch.setattr(co, "_files", lambda: iter([bare, paced]))
    unpaced, policed = co.scan()
    assert [(rel, label) for rel, _w, _l, label in unpaced] == [("bare.py", "ddgs.text")]
    assert [entry[0] for entry in policed] == ["bare.py"], "DuckDuckGo carries a policy: no budget"
    # And the `DDGS().text` shape, whose root is all capitals.
    call = ast.parse("DDGS().text('q')").body[0].value
    assert co._outbound_label(call) == "DDGS.text"


def test_the_tree_has_no_unpaced_library_call():
    co = _checker()
    unpaced, policed = co.scan()
    assert not [e for e in unpaced if "ddgs" in e[3].lower()], unpaced
    assert policed == []
