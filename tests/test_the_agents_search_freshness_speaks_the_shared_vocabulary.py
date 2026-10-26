# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1335` — the agent's web search had a fourth "is this news" vocabulary.

`src/agent_tools/web_tools.py` chose a `time_filter` from its own term lists,
matched as SUBSTRINGS — `currently` → day, `" news"` → week — and
`providers._searxng_params` sends any query with a `time_filter` to SearXNG's
news category. So the orthography `fx7-search2` stopped deciding the category
(`tests/test_one_definition_of_a_news_query.py`) came back through this door:
*"currently reading list"* was a day-filtered news search, and so was
*"todays-menu at the Blue Moon Inn"*.

The ladder is kept — it answers *how fresh*, not *is it news* (`Law 1`) — and
moved beside `NEWS_TERMS` as `services.search.query.freshness_for`, whole-token,
citing the shared set. Driven through the real tool with the search itself
replaced by a recorder, and through the real category switch (`Law 20`).
"""
from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from services.search import providers, query, ranking


def _searched_with(monkeypatch, text):
    """What `web_search` hands the search engine for `text`."""
    import src.search as search
    from src.agent_tools.web_tools import WebSearchTool

    seen = {}

    def fake_search(q, max_pages=5, time_filter=None, return_sources=False):
        seen["query"], seen["time_filter"] = q, time_filter
        return ("", [])

    monkeypatch.setattr(search, "comprehensive_web_search", fake_search)
    asyncio.run(WebSearchTool().execute(text, {}))
    return seen["time_filter"]


@pytest.mark.parametrize("text", [
    "currently reading list for book club",
    "todays-menu at the Blue Moon Inn",
    "breakingbad filming locations",
    "Newsom California policy",
    "current mortgage rates",          # a freshness word, not a news one: named
])
def test_a_word_that_only_contains_a_news_word_is_not_a_news_search(monkeypatch, text):
    """The row's `Verify:` — *"currently reading"* does not become a
    day-filtered news search — and the rest of the substring family."""
    time_filter = _searched_with(monkeypatch, text)
    assert time_filter is None, (text, time_filter)
    assert providers._searxng_params(text, time_filter=time_filter)["categories"] == "general"


@pytest.mark.parametrize("text,rung", [
    ("latest on the election", "day"),
    ("Canada news today", "day"),
    ("breaking: storm in Bergen", "day"),
    ("what is open right now in Paris", "day"),
    ("markets this morning", "day"),
    ("what happened this week in AI", "week"),
    ("rain over the last few days", "week"),
    ("tech news", "week"),
    ("headlines from Oslo", "week"),
    ("this month in open source", "month"),
    ("python release notes", None),
])
def test_the_ladder_keeps_its_rungs(monkeypatch, text, rung):
    assert _searched_with(monkeypatch, text) == rung


def test_a_rung_the_model_chose_is_kept(monkeypatch):
    import json
    assert _searched_with(
        monkeypatch, json.dumps({"query": "python release notes", "time_filter": "month"})
    ) == "month"


def test_a_term_added_to_the_shared_set_changes_all_four_behaviours(monkeypatch):
    """The other half of the row's `Verify:`. A word nothing knows about, then
    the same word added to `NEWS_TERMS` (and so to `FRESH_TERMS`, which is built
    from it): the SearXNG category, the ranker's news question, the cache
    duration and this ladder all move together."""
    text = "dagens nyheder"

    def four():
        return (
            providers._searxng_params(text, time_filter=None)["categories"],
            ranking.is_news_query(text),
            query._cache_duration_for_query(text),
            query.freshness_for(text),
        )

    assert four() == ("general", False, timedelta(hours=24), None)
    monkeypatch.setattr(query, "NEWS_TERMS", query.NEWS_TERMS | {"nyheder"})
    monkeypatch.setattr(query, "FRESH_TERMS", query.FRESH_TERMS | {"nyheder"})
    assert four() == ("news", True, timedelta(minutes=30), "week")


def test_every_now_word_is_a_news_word():
    """The day rung's words are a named subset of the shared set, not a list of
    their own."""
    assert query._NOW_TERMS <= query.NEWS_TERMS
