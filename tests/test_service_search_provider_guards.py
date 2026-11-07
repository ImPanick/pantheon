# SPDX-License-Identifier: AGPL-3.0-or-later
"""Regression tests for the canonical services.search provider implementation.

The old src.search provider path aliases this module; these tests pin the
behavior at the single implementation point.
"""

import sys

import pytest

from services.search import providers


def test_service_safesearch_values_match_provider_contract(monkeypatch):
    monkeypatch.setattr(providers, "_get_search_settings", lambda: {"search_safesearch": "strict"})
    assert providers._safesearch_for("searxng") == "2"
    assert providers._safesearch_for("brave") == "strict"
    assert providers._safesearch_for("duckduckgo_lib") == "on"
    assert providers._safesearch_for("duckduckgo_html") == "1"
    assert providers._safesearch_for("google_pse") == "active"
    assert providers._safesearch_for("serper") == "active"

    monkeypatch.setattr(providers, "_get_search_settings", lambda: {"search_safesearch": "off"})
    assert providers._safesearch_for("searxng") == "0"
    assert providers._safesearch_for("brave") == "off"
    assert providers._safesearch_for("duckduckgo_lib") == "off"
    assert providers._safesearch_for("duckduckgo_html") == "-2"
    assert providers._safesearch_for("google_pse") is None
    assert providers._safesearch_for("serper") is None


def test_service_searxng_json_sends_safesearch(monkeypatch):
    seen = {}

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "results": [
                    {"title": "Result", "url": "https://example.com", "content": "Snippet"}
                ]
            }

    def fake_get(url, **kwargs):
        seen["url"] = url
        seen["params"] = kwargs["params"]
        return _Response()

    monkeypatch.setattr(providers, "_get_search_instance", lambda: "http://searx.test")
    monkeypatch.setattr(providers, "_get_search_settings", lambda: {"search_safesearch": "moderate"})
    # `B1533`: SearXNG is called through `paced_http` too (paced at zero for
    # the operator's own instance), so the transport is replaced there.
    from src import paced_http
    monkeypatch.setattr(paced_http, "get_sync", fake_get)

    results = providers.searxng_search_api("pantheon", count=1)

    assert results
    assert seen["url"] == "http://searx.test/search"
    assert seen["params"]["safesearch"] == "1"


def test_service_ddg_redirect_ignores_lookalike_hosts():
    for host in ("duckduckgo.com.evil.com", "notduckduckgo.com"):
        url = f"https://{host}/l/?uddg=https%3A%2F%2Fexample.com"
        assert providers._resolve_ddg_redirect(url) == url

    assert providers._resolve_ddg_redirect(
        "https://duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com"
    ) == "https://example.com"


def test_service_ddg_html_fallback_sends_safesearch(monkeypatch):
    seen = {}
    html = """
    <html><body>
      <div class="result">
        <a class="result__a" href="https://notduckduckgo.com/l/?uddg=https%3A%2F%2Fevil.example">
          Lookalike
        </a>
        <a class="result__snippet">Snippet</a>
      </div>
    </body></html>
    """

    class _Response:
        text = html

        def raise_for_status(self):
            return None

    def fake_get(url, **kwargs):
        seen["params"] = kwargs["params"]
        return _Response()

    monkeypatch.setattr(providers, "_get_search_settings", lambda: {"search_safesearch": "off"})
    monkeypatch.setitem(sys.modules, "ddgs", None)
    # `P15-06` moved this call onto `paced_http.get_sync`, which is the seam the
    # limiter lives behind. Stubbing `providers.httpx.get` now stubs a function
    # nothing calls, so the test would have passed against a transport it was no
    # longer exercising — patch where the request is actually made.
    from src import paced_http
    monkeypatch.setattr(paced_http, "get_sync", fake_get)

    results = providers.duckduckgo_search("pantheon", count=1)

    assert seen["params"]["kp"] == "-2"
    assert results[0]["url"].startswith("https://notduckduckgo.com/")


# `B1809`. When SearXNG's JSON request failed (a stock SearXNG serves html only
# and refuses `format=json` with a 403; a bad answer or a 5xx on the bundled
# one), `searxng_search_api` fell back to `searxng_search`, which sent the
# query alone: a news search lost `categories=news` and its `time_range`,
# every search lost the English pin, and a general one lost the engines that
# answer. The HTML request now carries the constraints the JSON one was sent
# with, minus `format`, still through `paced_http` (`B1533`). After upstream
# Odysseus 90dcdc62, whose case this is, stubbed where Pantheon sends.
_ONE_HTML_RESULT = ('<article class="result"><h3><a href="https://example.org/report">Report</a>'
                    '</h3><p class="content">Evidence</p></article>')


def _json_fails_then_html_answers(monkeypatch, failure):
    import httpx
    from src import paced_http

    seen = []

    class _Refused:
        status_code = 403

        def raise_for_status(self):
            raise httpx.HTTPStatusError(
                "403 Forbidden", request=httpx.Request("GET", "http://searx.test/search"),
                response=httpx.Response(403))

    class _BadJson:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            raise ValueError("Expecting value: line 1 column 1 (char 0)")

    class _Html:
        is_success = True
        text = _ONE_HTML_RESULT

    def fake_get(url, params=None, headers=None, timeout=None, **kw):
        seen.append(dict(params or {}))
        if len(seen) == 1:
            return {"403": _Refused, "bad-json": _BadJson}[failure]()
        return _Html()

    monkeypatch.setattr(providers, "_get_search_instance", lambda: "http://searx.test")
    monkeypatch.setattr(providers, "_get_search_settings", lambda: {"search_safesearch": "strict"})
    monkeypatch.setattr(paced_http, "get_sync", fake_get)
    return seen


@pytest.mark.parametrize("failure", ["403", "bad-json"])
def test_the_html_fallback_keeps_a_news_searchs_category_and_date(monkeypatch, failure):
    seen = _json_fails_then_html_answers(monkeypatch, failure)

    results = providers.searxng_search_api("AI news", time_filter="week")

    assert [r["url"] for r in results] == ["https://example.org/report"]
    assert len(seen) == 2
    assert seen[1] == {k: v for k, v in seen[0].items() if k != "format"}
    assert (seen[1]["categories"], seen[1]["time_range"], seen[1]["language"]) == ("news", "week", "en")
    assert seen[1]["safesearch"] == "2"


def test_the_html_fallback_keeps_a_general_searchs_engines(monkeypatch):
    seen = _json_fails_then_html_answers(monkeypatch, "403")

    results = providers.searxng_search_api("python packaging guide")

    assert len(results) == 1 and len(seen) == 2
    assert seen[1]["categories"] == "general"
    assert seen[1]["engines"] == providers._GENERAL_ENGINES
    assert "format" not in seen[1]
