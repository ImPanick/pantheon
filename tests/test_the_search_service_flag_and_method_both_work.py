# SPDX-License-Identifier: AGPL-3.0-or-later
"""`SearchService` had one name for two things, and the method lost.

Measured on `3b40a4e`:

    >>> svc = SearchService()
    >>> type(svc.fetch_content).__name__
    'bool'
    >>> asyncio.run(svc.fetch_content("https://example.com"))
    TypeError: 'bool' object is not callable

`services/search/service.py:46` sets ``self.fetch_content = fetch_content`` (a
bool, from the constructor) and `:97` defines ``async def fetch_content(self,
url)``. The instance attribute shadows the class attribute, so the method was
unreachable on **every** instance and the public `SearchService` API documented
in its own class docstring raised on call. `Law 10` — one name, one reading.

**And the method was broken underneath the shadow**, which the shadow hid.
Measured by calling the unbound method directly:

    TypeError: object dict can't be used in 'await' expression

`fetch_webpage_content` (`services/search/content.py:182`) is a plain ``def``
returning a **dict**, not a coroutine returning a string — so
``return await fetch_webpage_content(url)`` could not have worked even with the
name collision removed, and the annotation said ``Optional[str]``. Two defects
in nine lines, and nothing had ever called it: measured, `SearchService` has no
production caller in the tree — only the re-export in `services/__init__.py`
and two tests.

The flag had no consumer either (`Law 13`). `search()`'s own `fetch_content`
parameter was documented *"accepted for API compatibility"* and ignored, and
measured, `SearchService(default_depth=1).search(...)` asked
`comprehensive_web_search` for **10** pages and read **none** of them — it
keeps only the `(url, title)` source list, so every fetched page was
discarded. The flag now reaches `comprehensive_web_search`, so a caller that
does not want page content does not pay for it.

Nothing here touches the network.
"""

import asyncio
import inspect

import pytest

import services.search.service as svc_mod
from services.search import core
from services.search.service import SearchResponse, SearchService


# ----------------------------------------------------------------------
# Fakes. A recorder for the search, a recorder for the fetch.
# ----------------------------------------------------------------------
@pytest.fixture
def fake_search(monkeypatch):
    """Replace `comprehensive_web_search` and record how it was called."""
    calls = []

    def _fake(query, max_pages=3, return_sources=False, **kwargs):
        calls.append({"query": query, "max_pages": max_pages,
                      "return_sources": return_sources, **kwargs})
        sources = [{"url": "https://example.org/a", "title": "A"},
                   {"url": "https://example.org/b", "title": "B"}]
        return ("context text", sources) if return_sources else "context text"

    monkeypatch.setattr(svc_mod, "comprehensive_web_search", _fake)
    return calls


@pytest.fixture
def fake_fetch(monkeypatch):
    """Replace `fetch_webpage_content` with the dict shape it really returns."""
    calls = []
    state = {"success": True, "content": "the page body", "error": ""}

    def _fake(url, *a, **kw):
        calls.append(url)
        return {"url": url, "title": "T", "content": state["content"],
                "success": state["success"], "error": state["error"]}

    monkeypatch.setattr(svc_mod, "fetch_webpage_content", _fake)
    return calls, state


# ----------------------------------------------------------------------
# 1. The flag and the method have different names
# ----------------------------------------------------------------------
def test_the_constructor_flag_no_longer_shadows_the_method():
    svc = SearchService()
    assert callable(svc.fetch_content), (
        "the constructor flag is still shadowing the method: "
        f"svc.fetch_content is {type(svc.fetch_content).__name__}"
    )
    assert inspect.iscoroutinefunction(svc.fetch_content)


def test_the_flag_is_still_readable_under_its_own_name():
    assert SearchService().fetch_content_enabled is True
    assert SearchService(fetch_content=False).fetch_content_enabled is False
    # The constructor keyword keeps its public name.
    assert "fetch_content" in inspect.signature(SearchService.__init__).parameters


def test_a_falsy_flag_is_stored_as_a_bool():
    assert SearchService(fetch_content=0).fetch_content_enabled is False
    assert SearchService(fetch_content="yes").fetch_content_enabled is True


# ----------------------------------------------------------------------
# 2. The method works
# ----------------------------------------------------------------------
def test_fetch_content_reaches_the_fetcher_and_returns_the_text(fake_fetch):
    calls, _ = fake_fetch
    got = asyncio.run(SearchService().fetch_content("https://example.org/a"))
    assert calls == ["https://example.org/a"]
    assert got == "the page body"


def test_fetch_content_returns_none_when_the_fetch_failed(fake_fetch, caplog):
    calls, state = fake_fetch
    state.update(success=False, content="", error="HTTP 403: Forbidden")
    with caplog.at_level("WARNING"):
        got = asyncio.run(SearchService().fetch_content("https://example.org/a"))
    assert got is None
    # The reason is not dropped. `_empty_result` has carried `error` since it
    # was written and every caller threw it away.
    assert "403" in caplog.text


def test_fetch_content_returns_none_rather_than_an_empty_string(fake_fetch):
    _, state = fake_fetch
    state.update(success=True, content="", error="")
    assert asyncio.run(SearchService().fetch_content("https://example.org/a")) is None


def test_fetch_content_does_not_block_the_event_loop(fake_fetch):
    """The fetcher is synchronous, so it runs off the loop — the same way
    `search()` already runs `comprehensive_web_search`."""
    async def go():
        other = asyncio.create_task(asyncio.sleep(0))
        got = await SearchService().fetch_content("https://example.org/a")
        await other
        return got

    assert asyncio.run(go()) == "the page body"


# ----------------------------------------------------------------------
# 3. The flag has a consumer
# ----------------------------------------------------------------------
def test_search_passes_the_flag_through_to_the_search(fake_search):
    asyncio.run(SearchService(fetch_content=False).search("python asyncio"))
    assert fake_search[0]["fetch_content"] is False

    asyncio.run(SearchService(fetch_content=True).search("python asyncio"))
    assert fake_search[1]["fetch_content"] is True


def test_a_per_call_argument_overrides_the_constructor_flag(fake_search):
    svc = SearchService(fetch_content=True)
    asyncio.run(svc.search("python asyncio", fetch_content=False))
    assert fake_search[0]["fetch_content"] is False
    # and None means "use the instance default", not "off"
    asyncio.run(svc.search("python asyncio"))
    assert fake_search[1]["fetch_content"] is True


def test_search_still_returns_structured_results(fake_search):
    resp = asyncio.run(SearchService(default_depth=2).search("python asyncio"))
    assert isinstance(resp, SearchResponse)
    assert resp.total == 2
    assert [r.url for r in resp.results] == ["https://example.org/a",
                                             "https://example.org/b"]
    assert fake_search[0]["max_pages"] == 20  # 10 * depth(2)
    assert fake_search[0]["return_sources"] is True


# ----------------------------------------------------------------------
# 4. The orchestrator honours the flag — measured in provider calls
# ----------------------------------------------------------------------
@pytest.fixture
def offline_core(monkeypatch, tmp_path):
    """`comprehensive_web_search` with a fake provider and a counted fetcher."""
    fetched = []
    results = [{"title": f"R{i}", "url": f"https://e{i}.org/",
                "snippet": "a snippet about python asyncio"} for i in range(1, 6)]

    monkeypatch.setattr(core, "_get_search_settings",
                        lambda: {"search_provider": "searxng"}, raising=False)
    monkeypatch.setattr(core, "_get_result_count", lambda: 5, raising=False)
    monkeypatch.setattr(core, "_record_query", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(core, "SEARCH_CACHE_DIR", tmp_path, raising=False)
    monkeypatch.setattr(core, "_call_provider",
                        lambda p, q, c, t=None: [dict(r) for r in results],
                        raising=False)

    def _fetch(url, *a, **kw):
        fetched.append(url)
        return {"url": url, "title": "T", "content": "body " * 200,
                "success": True, "error": ""}

    monkeypatch.setattr(core, "fetch_webpage_content", _fetch, raising=False)
    return fetched


def test_fetching_off_fetches_nothing(offline_core):
    out = core.comprehensive_web_search("python asyncio", max_pages=5,
                                        fetch_content=False)
    assert offline_core == [], f"pages were fetched anyway: {offline_core}"
    assert "FETCHED PAGE CONTENT:" not in out
    # The header says so rather than reporting zero as if it were a failure.
    assert "content fetching disabled" in out
    # The results themselves still arrive.
    assert "SEARCH RESULTS SUMMARY" in out


def test_fetching_on_is_the_default_and_unchanged(offline_core):
    out = core.comprehensive_web_search("python asyncio", max_pages=3)
    assert len(offline_core) == 3
    assert "FETCHED PAGE CONTENT:" in out
    assert "fetched 3 pages" in out


def test_the_service_default_still_fetches(offline_core, monkeypatch):
    monkeypatch.setattr(svc_mod, "comprehensive_web_search",
                        core.comprehensive_web_search)
    asyncio.run(SearchService(default_depth=1).search("python asyncio"))
    assert offline_core, "the default stopped fetching page content"


def test_the_service_with_the_flag_off_pays_for_no_pages(offline_core, monkeypatch):
    """The measured waste: 10 pages fetched and 10 discarded."""
    monkeypatch.setattr(svc_mod, "comprehensive_web_search",
                        core.comprehensive_web_search)
    resp = asyncio.run(
        SearchService(default_depth=1, fetch_content=False).search("python asyncio"))
    assert offline_core == []
    assert resp.total == 5
