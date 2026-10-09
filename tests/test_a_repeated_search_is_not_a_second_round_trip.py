# SPDX-License-Identifier: AGPL-3.0-or-later
"""The search cache served a function nobody called, and the counters counted it.

Measured on `3b40a4e` with a fake provider that counts calls and sleeps 120 ms:

    comprehensive_web_search  (the live path)   run 1: 1 call, 134 ms
                                                run 2: 1 call, 122 ms
                                                run 3: 1 call, 121 ms
    searxng_search_results    (no caller)       run 1: 1 call, 122 ms
                                                run 2: 0 calls,  0.9 ms
                                                run 3: 0 calls,  0.6 ms

`services/search/core.py:167` `searxng_search_results` was the only reader and
writer of `SEARCH_CACHE_DIR` / `search_cache_index` / `cleanup_cache` /
`_cache_duration_for_query`, and measured on the merged tree it had **no
production caller anywhere**: `services/search/__init__.py` and
`src/search/__init__.py` re-export it and three test files import it, and that
is all. Everything a person touches — chat, the agent's `web_search` tool,
`POST /api/search`, the Compare pane, both research handlers — goes through
`comprehensive_web_search`, which touched the cache not at all.

So the cache ran never, and every search was a fresh round trip — while the
**content** half of the same pipeline has cached for two hours the whole time
(`content.py:195`, reached from `comprehensive_web_search`). Half the pipeline
cached and half did not, and the half that did not is the one with a provider
quota behind it.

`_record_query` (`analytics.py:98`) had exactly two call sites, both inside
that unreachable function, so `data/logs/search_analytics.json` stayed at its
defaults however much searching a person did — and `get_search_stats()`, which
reports over it, had no caller either. Two halves of one feature, each
unreachable, which is why neither had ever looked wrong.

**And the TTL contradicted itself.** `_cache_duration_for_query` returns 24
hours for a reference query, and the write path then called
``cleanup_cache(SEARCH_CACHE_DIR, search_cache_index, timedelta(hours=1))`` —
measured, a reference entry written with a 24-hour expiry was deleted by the
next search once its index entry was 90 minutes old. One hour was the real
ceiling and the news/reference split was decorative. The sweep now gets the
longest duration the TTL function can return, so the entry's own expiry — the
one in its file, checked on read — is the only thing that retires it (`Law 7`).

These drive: one cache seam used by both orchestrators, a repeated query that
costs zero provider calls, the counters moving on the path people use, and the
provider that answered surviving a cache hit.

Every case uses a fake provider that records what it was asked. Nothing here
touches the network.
"""

import json
import time
from datetime import datetime, timedelta

import pytest

from services.search import analytics, cache, core, query

from tests.test_a_search_sends_the_persons_words import (
    GOOD_RESULTS,
    OWNER_QUERY,
    _Recorder,
)


REFERENCE_QUERY = "python asyncio tutorial"
NEWS_QUERY = "latest OSRS news"


# ----------------------------------------------------------------------
# A fake provider that counts calls and costs time
# ----------------------------------------------------------------------
class _CountingProvider(_Recorder):
    """`_Recorder` plus a latency, so the win is measurable and not asserted."""

    def __init__(self, results=None, latency=0.0):
        super().__init__(results if results is not None else list(GOOD_RESULTS))
        self.latency = latency

    def install(self, monkeypatch, *, only=None):
        def _fake(provider_name, query_sent, count, time_filter=None):
            self.calls.append((provider_name, query_sent, count, time_filter))
            if self.latency:
                time.sleep(self.latency)
            if only is not None and provider_name != only:
                return []
            return [dict(r) for r in self.results]

        monkeypatch.setattr(core, "_call_provider", _fake)

    @property
    def count(self):
        return len(self.calls)


@pytest.fixture
def cached(monkeypatch, tmp_path):
    """A hermetic cache directory, a local analytics file, no network."""
    search_dir = tmp_path / "search"
    search_dir.mkdir()
    monkeypatch.setattr(core, "SEARCH_CACHE_DIR", search_dir, raising=False)
    monkeypatch.setattr(cache, "SEARCH_CACHE_DIR", search_dir, raising=False)
    monkeypatch.setattr(analytics, "ANALYTICS_FILE", tmp_path / "search_analytics.json",
                        raising=False)
    core.search_cache_index.clear()
    cache.cache_metrics.update(hits=0, misses=0, evictions=0)

    monkeypatch.setattr(core, "_get_search_settings",
                        lambda: {"search_provider": "searxng"}, raising=False)
    monkeypatch.setattr(core, "_get_result_count", lambda: 5, raising=False)
    monkeypatch.setattr(
        core, "fetch_webpage_content",
        lambda url, *a, **k: {"url": url, "title": "T", "content": "body " * 100,
                              "success": True, "error": ""},
        raising=False,
    )
    yield search_dir
    core.search_cache_index.clear()


# ----------------------------------------------------------------------
# 1. The live path caches
# ----------------------------------------------------------------------
def test_the_same_search_twice_costs_one_provider_call(cached, monkeypatch):
    rec = _CountingProvider()
    rec.install(monkeypatch)

    core.comprehensive_web_search(REFERENCE_QUERY, max_pages=2)
    assert rec.count == 1, "the first search did not reach a provider"

    core.comprehensive_web_search(REFERENCE_QUERY, max_pages=2)
    assert rec.count == 1, (
        f"the repeated search went to the provider again ({rec.count} calls) — "
        "the cache is not on the live path"
    )


def test_the_repeated_search_is_measurably_faster(cached, monkeypatch):
    rec = _CountingProvider(latency=0.08)
    rec.install(monkeypatch)

    t0 = time.perf_counter()
    core.comprehensive_web_search(REFERENCE_QUERY, max_pages=2)
    cold = time.perf_counter() - t0

    t0 = time.perf_counter()
    core.comprehensive_web_search(REFERENCE_QUERY, max_pages=2)
    warm = time.perf_counter() - t0

    assert cold >= 0.08, cold
    assert warm < cold / 2, f"cold {cold*1000:.1f} ms, warm {warm*1000:.1f} ms"


def test_the_cached_search_returns_the_same_results(cached, monkeypatch):
    rec = _CountingProvider()
    rec.install(monkeypatch)

    first = core.comprehensive_web_search(REFERENCE_QUERY, max_pages=2)
    second = core.comprehensive_web_search(REFERENCE_QUERY, max_pages=2)

    for url in (r["url"] for r in GOOD_RESULTS):
        assert url in second
    assert "SEARCH RESULTS SUMMARY" in second
    assert first.count("```sources") == second.count("```sources")


def test_a_different_query_is_a_different_entry(cached, monkeypatch):
    rec = _CountingProvider()
    rec.install(monkeypatch)
    core.comprehensive_web_search(REFERENCE_QUERY, max_pages=2)
    core.comprehensive_web_search("something else entirely", max_pages=2)
    assert rec.count == 2


def test_a_different_time_filter_is_a_different_entry(cached, monkeypatch):
    rec = _CountingProvider()
    rec.install(monkeypatch)
    core.comprehensive_web_search(NEWS_QUERY, max_pages=2)
    core.comprehensive_web_search(NEWS_QUERY, max_pages=2, time_filter="day")
    assert rec.count == 2, "the time filter is not part of the cache key"


def test_a_failed_search_is_not_cached(cached, monkeypatch):
    rec = _CountingProvider(results=[])
    rec.install(monkeypatch)
    core.comprehensive_web_search(REFERENCE_QUERY, max_pages=2)
    core.comprehensive_web_search(REFERENCE_QUERY, max_pages=2)
    # Two providers in the chain per attempt; what matters is that the second
    # search tried again rather than serving an empty cached answer.
    assert rec.count > len(core._build_provider_chain("searxng")), rec.calls


def test_invalidation_clears_the_live_paths_entry(cached, monkeypatch):
    rec = _CountingProvider()
    rec.install(monkeypatch)
    core.comprehensive_web_search(REFERENCE_QUERY, max_pages=2)
    assert rec.count == 1
    core.invalidate_search_cache(REFERENCE_QUERY)
    core.comprehensive_web_search(REFERENCE_QUERY, max_pages=2)
    assert rec.count == 2, "invalidate_search_cache did not match the live key"


def test_invalidating_everything_clears_the_live_paths_entry(cached, monkeypatch):
    rec = _CountingProvider()
    rec.install(monkeypatch)
    core.comprehensive_web_search(REFERENCE_QUERY, max_pages=2)
    core.invalidate_search_cache()
    core.comprehensive_web_search(REFERENCE_QUERY, max_pages=2)
    assert rec.count == 2


# ----------------------------------------------------------------------
# 2. One seam, not two (`Law 7`)
# ----------------------------------------------------------------------
def test_both_orchestrators_share_one_cache_entry(cached, monkeypatch):
    rec = _CountingProvider()
    rec.install(monkeypatch)

    core.searxng_search_results(REFERENCE_QUERY)
    assert rec.count == 1
    core.comprehensive_web_search(REFERENCE_QUERY, max_pages=2)
    assert rec.count == 1, (
        "the two orchestrators keep separate caches — the same search for the "
        "same count and filter must be one entry"
    )
    core.searxng_search_results(REFERENCE_QUERY)
    assert rec.count == 1, "the entry does not read back through the key it was written with"


def test_the_other_orchestrator_also_serves_its_own_repeat(cached, monkeypatch):
    """A seam both halves use is one that reads what it writes. Asserted on
    `searxng_search_results` by itself, because reading it back through the
    *other* orchestrator cannot tell a wrong read key from a right one."""
    rec = _CountingProvider()
    rec.install(monkeypatch)

    first = core.searxng_search_results(REFERENCE_QUERY)
    assert rec.count == 1
    second = core.searxng_search_results(REFERENCE_QUERY)
    assert rec.count == 1, f"the repeat went to the provider again: {rec.calls}"
    assert [r["url"] for r in second] == [r["url"] for r in first]


def test_the_key_is_derived_in_one_place(cached, monkeypatch):
    rec = _CountingProvider()
    rec.install(monkeypatch)
    core.comprehensive_web_search(REFERENCE_QUERY, max_pages=2)
    key = core._search_cache_key(REFERENCE_QUERY, 5, None)
    assert (cached / f"{key}.cache").exists(), sorted(p.name for p in cached.iterdir())


# A pair the ranker demonstrably reorders: the shop page comes back first from
# the provider and ranks second (no query terms in the title, a `.com`), the
# docs page comes back second and ranks first (every term, a `.gov`). Without a
# set the ranker moves, "the cache holds what the provider said" and "the cache
# holds what the ranker said" are the same assertion.
REORDERED = [
    {"title": "unrelated shop page", "url": "https://shop.example.com/x",
     "snippet": "buy things"},
    {"title": "python asyncio tutorial reference",
     "url": "https://docs.python.gov/asyncio",
     "snippet": "A full python asyncio tutorial reference with examples and detail."},
]


def test_ranking_is_not_frozen_into_the_cache(cached, monkeypatch):
    """A cached entry holds what the provider said, not what the ranker made of
    it — so a ranking fix applies to entries written before it."""
    rec = _CountingProvider(results=list(REORDERED))
    rec.install(monkeypatch)
    out = core.comprehensive_web_search(REFERENCE_QUERY, max_pages=2)

    provider_order = [r["url"] for r in REORDERED]
    ranked_order = [r["url"] for r in core.rank_search_results(REFERENCE_QUERY, REORDERED)]
    assert ranked_order != provider_order, "the fixture no longer exercises ranking"

    key = core._search_cache_key(REFERENCE_QUERY, 5, None)
    stored = json.loads((cached / f"{key}.cache").read_text(encoding="utf-8"))
    assert [r["url"] for r in stored["data"]] == provider_order, (
        "the cache stored the ranked order, so a ranking fix will not reach this entry"
    )

    calls = []
    real_rank = core.rank_search_results
    monkeypatch.setattr(core, "rank_search_results",
                        lambda q, r: calls.append(q) or real_rank(q, r))
    second = core.comprehensive_web_search(REFERENCE_QUERY, max_pages=2)
    assert calls == [REFERENCE_QUERY], "a cache hit skipped ranking"
    # and the served block is in ranked order, not the order on disk
    sources = [ln.strip() for ln in second.splitlines() if ln.startswith("    http")]
    assert sources == ranked_order, sources


# ----------------------------------------------------------------------
# 3. The TTL means what it says
# ----------------------------------------------------------------------
def test_a_news_query_expires_in_thirty_minutes(cached, monkeypatch):
    rec = _CountingProvider()
    rec.install(monkeypatch)
    core.comprehensive_web_search(NEWS_QUERY, max_pages=2)

    key = core._search_cache_key(NEWS_QUERY, 5, None)
    stored = json.loads((cached / f"{key}.cache").read_text(encoding="utf-8"))
    expiry = datetime.fromisoformat(stored["expiry"])
    delta = expiry - datetime.now()
    assert timedelta(minutes=25) < delta <= timedelta(minutes=30), delta


def test_a_reference_query_expires_in_a_day(cached, monkeypatch):
    rec = _CountingProvider()
    rec.install(monkeypatch)
    core.comprehensive_web_search(REFERENCE_QUERY, max_pages=2)

    key = core._search_cache_key(REFERENCE_QUERY, 5, None)
    stored = json.loads((cached / f"{key}.cache").read_text(encoding="utf-8"))
    expiry = datetime.fromisoformat(stored["expiry"])
    assert expiry - datetime.now() > timedelta(hours=23)


def test_an_expired_entry_is_not_served(cached, monkeypatch):
    rec = _CountingProvider()
    rec.install(monkeypatch)
    core.comprehensive_web_search(REFERENCE_QUERY, max_pages=2)

    key = core._search_cache_key(REFERENCE_QUERY, 5, None)
    path = cached / f"{key}.cache"
    stored = json.loads(path.read_text(encoding="utf-8"))
    stored["expiry"] = (datetime.now() - timedelta(minutes=1)).isoformat()
    path.write_text(json.dumps(stored), encoding="utf-8")

    core.comprehensive_web_search(REFERENCE_QUERY, max_pages=2)
    assert rec.count == 2


def test_the_sweep_does_not_retire_an_entry_its_own_expiry_keeps(cached, monkeypatch):
    """Measured on `3b40a4e`: a 24-hour entry was deleted by the next search
    once its index timestamp was 90 minutes old, because the sweep was given
    one hour. The entry's own expiry is the only thing that retires it."""
    rec = _CountingProvider()
    rec.install(monkeypatch)
    core.comprehensive_web_search(REFERENCE_QUERY, max_pages=2)

    key = core._search_cache_key(REFERENCE_QUERY, 5, None)
    path = cached / f"{key}.cache"
    core.search_cache_index[key] = datetime.now() - timedelta(minutes=90)

    core.comprehensive_web_search("an unrelated query", max_pages=2)
    assert path.exists(), "the one-hour sweep deleted an entry with 24 hours to live"

    core.comprehensive_web_search(REFERENCE_QUERY, max_pages=2)
    assert rec.count == 2, "the entry survived on disk but was not served"


def test_the_sweep_window_is_the_longest_ttl_the_duration_function_returns():
    assert query.MAX_CACHE_DURATION >= query._cache_duration_for_query("anything")
    assert query.MAX_CACHE_DURATION >= query._cache_duration_for_query(NEWS_QUERY)
    assert core._SEARCH_SWEEP_AGE == query.MAX_CACHE_DURATION


def test_a_corrupt_entry_is_discarded_rather_than_raised(cached, monkeypatch):
    rec = _CountingProvider()
    rec.install(monkeypatch)
    key = core._search_cache_key(REFERENCE_QUERY, 5, None)
    (cached / f"{key}.cache").write_text("{not json", encoding="utf-8")

    out = core.comprehensive_web_search(REFERENCE_QUERY, max_pages=2)
    assert rec.count == 1
    assert "SEARCH RESULTS SUMMARY" in out


# ----------------------------------------------------------------------
# 4. A cache hit still says who answered
# ----------------------------------------------------------------------
def test_the_provider_name_survives_a_cache_hit(cached, monkeypatch):
    rec = _CountingProvider()
    rec.install(monkeypatch)
    first = core.comprehensive_web_search(REFERENCE_QUERY, max_pages=2)
    assert "Provider: searxng" in first

    second = core.comprehensive_web_search(REFERENCE_QUERY, max_pages=2)
    assert "Provider: searxng" in second, (
        "a cache hit lost the provider name — the one thing the owner's export "
        "could not tell anyone"
    )


def test_a_cached_block_says_it_is_cached(cached, monkeypatch):
    rec = _CountingProvider()
    rec.install(monkeypatch)
    first = core.comprehensive_web_search(REFERENCE_QUERY, max_pages=2)
    second = core.comprehensive_web_search(REFERENCE_QUERY, max_pages=2)
    assert "cached" not in first.split("END OF WEB SEARCH")[0].lower()
    assert "cached" in second.lower(), (
        "nothing in the block says the results are not fresh"
    )


def test_a_legacy_entry_without_a_provider_still_serves(cached, monkeypatch):
    """Entries written before the provider was recorded must not break a read."""
    rec = _CountingProvider()
    rec.install(monkeypatch)
    key = core._search_cache_key(REFERENCE_QUERY, 5, None)
    (cached / f"{key}.cache").write_text(json.dumps({
        "timestamp": datetime.now().isoformat(),
        "expiry": (datetime.now() + timedelta(hours=1)).isoformat(),
        "data": [dict(r) for r in GOOD_RESULTS],
    }), encoding="utf-8")

    out = core.comprehensive_web_search(REFERENCE_QUERY, max_pages=2)
    assert rec.count == 0, "a legacy entry was ignored"
    assert "SEARCH RESULTS SUMMARY" in out


# ----------------------------------------------------------------------
# 5. The counters count the path people use
# ----------------------------------------------------------------------
def test_a_search_through_the_live_path_is_recorded(cached, monkeypatch):
    rec = _CountingProvider()
    rec.install(monkeypatch)
    before = analytics.get_search_stats()["total_queries"]

    core.comprehensive_web_search(REFERENCE_QUERY, max_pages=2)

    after = analytics.get_search_stats()
    assert after["total_queries"] == before + 1, (
        "comprehensive_web_search recorded nothing — the counters still only "
        "watch the function with no caller"
    )
    assert after["successful_queries"] == 1
    assert after["cache_misses"] == 1
    assert after["cache_hits"] == 0


def test_a_cache_hit_is_recorded_as_a_hit(cached, monkeypatch):
    rec = _CountingProvider()
    rec.install(monkeypatch)
    core.comprehensive_web_search(REFERENCE_QUERY, max_pages=2)
    core.comprehensive_web_search(REFERENCE_QUERY, max_pages=2)

    stats = analytics.get_search_stats()
    assert stats["total_queries"] == 2
    assert stats["cache_hits"] == 1
    assert stats["cache_misses"] == 1
    assert stats["cache_hit_rate"] == 0.5


def test_a_failed_search_is_recorded_as_a_failure(cached, monkeypatch):
    rec = _CountingProvider(results=[])
    rec.install(monkeypatch)
    core.comprehensive_web_search(REFERENCE_QUERY, max_pages=2)

    stats = analytics.get_search_stats()
    assert stats["failed_queries"] == 1
    assert stats["successful_queries"] == 0


def test_the_person_s_query_is_recorded_not_the_sent_string(cached, monkeypatch):
    rec = _CountingProvider()
    rec.install(monkeypatch)
    core.comprehensive_web_search(OWNER_QUERY, max_pages=2)
    assert OWNER_QUERY in analytics.get_search_stats()["most_common_queries"]


def test_the_provider_that_answered_is_recorded(cached, monkeypatch):
    """The fx6 lane could not say which provider answered the owner, because
    nothing wrote it down. This is where it is written down."""
    rec = _CountingProvider()
    rec.install(monkeypatch)
    core.comprehensive_web_search(REFERENCE_QUERY, max_pages=2)
    assert analytics.get_search_stats()["providers"] == {"searxng": 1}


def test_the_relevance_verdict_is_recorded(cached, monkeypatch):
    from tests.test_a_search_sends_the_persons_words import OWNER_RESULTS

    rec = _CountingProvider(results=list(OWNER_RESULTS))
    rec.install(monkeypatch)
    core.comprehensive_web_search(OWNER_QUERY, max_pages=2)

    verdicts = analytics.get_search_stats()["verdicts"]
    assert verdicts.get("weak") == 1, verdicts


def test_an_analytics_file_from_an_older_schema_still_records(cached, monkeypatch):
    analytics.ANALYTICS_FILE.write_text(json.dumps({"total_queries": 7}), encoding="utf-8")
    rec = _CountingProvider()
    rec.install(monkeypatch)
    core.comprehensive_web_search(REFERENCE_QUERY, max_pages=2)
    stats = analytics.get_search_stats()
    assert stats["total_queries"] == 8
    assert stats["providers"] == {"searxng": 1}


def test_an_unwritable_analytics_file_does_not_break_a_search(cached, monkeypatch):
    monkeypatch.setattr(analytics, "_save_analytics",
                        lambda data: (_ for _ in ()).throw(OSError("read-only")))
    rec = _CountingProvider()
    rec.install(monkeypatch)
    out = core.comprehensive_web_search(REFERENCE_QUERY, max_pages=2)
    assert "SEARCH RESULTS SUMMARY" in out


# ----------------------------------------------------------------------
# 6. The counters have a door (`Law 13`)
# ----------------------------------------------------------------------
def test_the_metrics_scrape_carries_the_search_counters(cached, monkeypatch):
    import src.metrics_export as mx

    rec = _CountingProvider()
    rec.install(monkeypatch)
    core.comprehensive_web_search(REFERENCE_QUERY, max_pages=2)
    core.comprehensive_web_search(REFERENCE_QUERY, max_pages=2)

    out = mx._Out()
    mx._collect_search(out)
    text = out.render()

    assert 'pantheon_search_queries{outcome="success"} 2' in text, text
    assert 'pantheon_search_cache{result="hit"} 1' in text, text
    assert 'pantheon_search_cache{result="miss"} 1' in text, text
    assert 'pantheon_search_provider_answers{provider="searxng"} 1' in text, text


def test_the_scrape_never_carries_the_query_text(cached, monkeypatch):
    import src.metrics_export as mx

    secret = "my private medical question"
    rec = _CountingProvider()
    rec.install(monkeypatch)
    core.comprehensive_web_search(secret, max_pages=2)

    out = mx._Out()
    mx._collect_search(out)
    text = out.render()
    assert secret not in text, "a person's search text reached the metrics endpoint"
    assert "medical" not in text


def test_the_search_collector_is_registered():
    import src.metrics_export as mx
    assert "search" in dict(mx._COLLECTORS)
    assert dict(mx._COLLECTORS)["search"] is mx._collect_search


def test_the_search_collector_touches_no_network(monkeypatch, tmp_path):
    import socket

    import src.metrics_export as mx

    def refuse(*a, **kw):
        raise AssertionError("the search collector opened a socket")

    monkeypatch.setattr(analytics, "ANALYTICS_FILE", tmp_path / "a.json", raising=False)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    out = mx._Out()
    mx._collect_search(out)
    assert "pantheon_search_queries" in out.render()
