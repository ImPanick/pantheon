# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1533` — the search providers go through the outbound limiter, and one 429 is one step.

Measured on the tree this row started from: `services/search/providers.py`
called Brave, Google PSE, Tavily and Serper through module-level `httpx`, so
nothing paced them (`check-outbound`'s inventory listed all four), a provider
the limiter was holding was called anyway, and each provider swallowed its own
429 and answered `[]` — so the chain retried the provider that had just said
stop, and the limiter never heard of it. Where a 429 did reach
`core._note_provider_rate_limited`, it was the second report of one
`paced_http` had already counted, and a 60 s first cooldown became 120 s.

Now each provider's request goes through `paced_http` (pace, refuse a host in
cooldown before sending, observe the answer once) and a 429 is a
`RateLimitError` the chain moves past without retrying. And, found on the way:
an empty `search_fallback_chain` — its shipped value since `Law 16` emptied it —
no longer means DuckDuckGo.

Driven through the real `searxng_search_results`, providers, `paced_http` and a
fresh `OutboundHostLimiter`; only the socket is replaced (`httpx.Client.request`).
"""
import httpx
import pytest

import src.rate_limiter as rate_limiter
from services.search import core, providers
from services.search.analytics import RateLimitError

HOSTS = {
    "brave": "api.search.brave.com",
    "google_pse": "www.googleapis.com",
    "tavily": "api.tavily.com",
    "serper": "google.serper.dev",
}
CALLS = {
    "brave": providers.brave_search,
    "google_pse": providers.google_pse_search,
    "tavily": providers.tavily_search,
    "serper": providers.serper_search,
}


@pytest.fixture
def limiter(monkeypatch, tmp_path):
    import src.constants as constants

    monkeypatch.setattr(constants, "OUTBOUND_STATE_FILE", str(tmp_path / "outbound.json"))
    fresh = rate_limiter.OutboundHostLimiter()
    monkeypatch.setattr(rate_limiter, "outbound", fresh)
    return fresh


@pytest.fixture
def wire(monkeypatch):
    """Every request that reached a socket, answered with `wire.status`."""
    sent = []

    def request(self, method, url, **kwargs):
        sent.append((method, str(url)))
        body = {"web": {"results": []}, "items": [], "results": [], "organic": []}
        return httpx.Response(wire.status, json=body,
                              request=httpx.Request(method, str(url)))

    monkeypatch.setattr(httpx.Client, "request", request)
    wire.sent = sent
    wire.status = 200
    return wire


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setattr(providers, "_get_search_settings", lambda: {}, raising=False)
    monkeypatch.setattr(providers, "_safesearch_for", lambda *_a, **_k: None, raising=False)
    for var in ("DATA_BRAVE_API_KEY", "GOOGLE_API_KEY", "TAVILY_API_KEY", "SERPER_API_KEY"):
        monkeypatch.setenv(var, "k")
    monkeypatch.setenv("GOOGLE_PSE_CX", "cx")


@pytest.fixture
def search(monkeypatch, tmp_path, keys):
    """`searxng_search_results` with one provider and no fallback configured."""
    cache_dir = tmp_path / "search-cache"
    cache_dir.mkdir()
    monkeypatch.setattr(core, "SEARCH_CACHE_DIR", cache_dir, raising=False)
    core.search_cache_index.clear()
    monkeypatch.setattr(core, "_get_result_count", lambda: 5, raising=False)
    monkeypatch.setattr(core, "_record_query", lambda *a, **k: None, raising=False)

    def run(provider, query):
        monkeypatch.setattr(core, "_get_search_settings",
                            lambda: {"search_provider": provider}, raising=False)
        return core.searxng_search_results(query, count=5)
    return run


@pytest.mark.parametrize("provider", sorted(HOSTS))
def test_each_provider_goes_through_the_limiter(limiter, wire, keys, provider):
    CALLS[provider]("tide tables", 5)

    assert [url.split("/")[2] for _m, url in wire.sent] == [HOSTS[provider]]
    assert limiter._st(HOSTS[provider]).total_requests == 1


@pytest.mark.parametrize("provider", sorted(HOSTS))
def test_a_provider_in_cooldown_is_not_called(limiter, wire, keys, provider):
    limiter.observe(HOSTS[provider], 429, {"Retry-After": "600"})

    with pytest.raises(RateLimitError):
        CALLS[provider]("tide tables", 5)

    assert wire.sent == []


@pytest.mark.parametrize("provider", sorted(HOSTS))
def test_one_429_through_the_chain_sets_one_cooldown_step(limiter, wire, search, provider):
    wire.status = 429

    assert search(provider, "tide tables") == []

    state = limiter._st(HOSTS[provider])
    assert state.consecutive_429 == 1
    # No Retry-After: the limiter's first geometric step, 60 s — not 120.
    assert 55 <= limiter.blocked_for(HOSTS[provider]) <= 60
    # And the provider that said stop was not asked again in the same search.
    assert len(wire.sent) == 1


def test_the_next_search_does_not_call_a_provider_in_cooldown(limiter, wire, search):
    wire.status = 429
    search("brave", "tide tables")
    wire.status = 200

    assert search("brave", "tide tables near me") == []

    assert len(wire.sent) == 1
    assert limiter._st(HOSTS["brave"]).consecutive_429 == 1


def test_an_empty_fallback_chain_sends_nothing_to_duckduckgo(monkeypatch):
    """Found on the way: `search_fallback_chain` ships empty (`Law 16`), and
    `_FALLBACK_ORDER` filled the emptiness with DuckDuckGo."""
    monkeypatch.setattr(core, "_get_search_settings", lambda: {}, raising=False)
    assert core._build_provider_chain("searxng") == ["searxng"]
    monkeypatch.setattr(core, "_get_search_settings",
                        lambda: {"search_fallback_chain": ["duckduckgo"]}, raising=False)
    assert core._build_provider_chain("searxng") == ["searxng", "duckduckgo"]
