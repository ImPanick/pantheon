# SPDX-License-Identifier: AGPL-3.0-or-later
"""One button press must not fire 260 unauthenticated requests at huggingface.co.

Before 2026-08-31, `refresh_hf_collection_models_cache` walked 13 collection
sources x 20 pages, sequentially, with no delay and no token -- while two other
call sites in this same product send a Bearer token to that same host. The 24h
TTL was the only brake and `force=True`, reachable from the UI's refresh button,
walked straight past it.

The subtlest part was the error handling. A rate limit on the first source was
swallowed by a bare `except ... continue`, which then tried the other twelve --
so being told to stop bought the host twelve more bursts.
"""
import urllib.error

import pytest

from services.hwfit import hf_discovery as hf
from src.rate_limiter import HostPolicy, OutboundHostLimiter


@pytest.fixture
def no_pacing(monkeypatch):
    """Real limiter, zero interval -- behaviour under test, not wall clock."""
    import src.rate_limiter as rl

    lim = OutboundHostLimiter({"huggingface.co": HostPolicy(min_interval=0.0, jitter=0.0)})
    monkeypatch.setattr(rl, "outbound", lim)
    monkeypatch.setattr(hf, "_hf_token", lambda: "")
    return lim


class _Resp:
    status = 200
    headers = {"Link": '<https://huggingface.co/api/collections?p=2>; rel="next"'}

    def __init__(self, seen, url):
        seen.append(url)

    def read(self, *_a):
        return b"[]"

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def seen(monkeypatch):
    """An endlessly paginating host -- the worst case the caps exist for."""
    urls = []

    def _open(req, timeout=None):
        return _Resp(urls, req.full_url)

    monkeypatch.setattr(hf.urllib.request, "urlopen", _open)
    monkeypatch.setattr(hf.json, "load", lambda _f: [])
    return urls


def test_the_worst_case_used_to_be_260(no_pacing, seen, monkeypatch, tmp_path):
    """The number this row exists for, asserted so it cannot come back."""
    assert len(hf.HF_COLLECTION_SOURCES) * 20 >= 260
    assert hf.HF_MAX_REQUESTS_PER_REFRESH < 60, (
        "the cap must sit below what an unauthenticated host will tolerate"
    )


def test_one_refresh_cannot_exceed_the_request_budget(no_pacing, seen, monkeypatch, tmp_path):
    monkeypatch.setattr(hf, "_cache_fresh", lambda _p: False)
    monkeypatch.setattr(hf, "_write_cache", lambda *a, **k: None)
    monkeypatch.setattr(hf, "load_cached_hf_collection_models", lambda: [])
    monkeypatch.setattr(hf, "_last_forced_refresh", 0.0)

    hf.refresh_hf_collection_models_cache(force=True)
    assert len(seen) <= hf.HF_MAX_REQUESTS_PER_REFRESH, (
        f"{len(seen)} requests against a budget of {hf.HF_MAX_REQUESTS_PER_REFRESH}"
    )


def test_one_deep_source_cannot_starve_the_others(no_pacing, seen):
    """Per-source page caps alone are not enough: 13 x their own limit is a burst."""
    budget = [10]
    hf.fetch_collection_models(hf.HF_COLLECTION_SOURCES[0], budget=budget)
    assert len(seen) <= 10
    assert budget[0] >= 0, "the budget went negative"


def test_a_rate_limit_stops_the_whole_refresh(no_pacing, monkeypatch):
    """The amplifier. A 429 on source one used to buy twelve more bursts."""
    calls = []

    def _open(req, timeout=None):
        calls.append(req.full_url)
        raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {}, None)

    monkeypatch.setattr(hf.urllib.request, "urlopen", _open)
    monkeypatch.setattr(hf, "_cache_fresh", lambda _p: False)
    monkeypatch.setattr(hf, "_write_cache", lambda *a, **k: None)
    monkeypatch.setattr(hf, "load_cached_hf_collection_models", lambda: [])
    monkeypatch.setattr(hf, "_last_forced_refresh", 0.0)

    hf.refresh_hf_collection_models_cache(force=True)
    assert len(calls) == 1, (
        f"a 429 on the first source produced {len(calls)} requests; it must produce exactly one"
    )


def test_the_refresh_stops_on_a_rate_limit_even_with_no_limiter(monkeypatch):
    """Two independent protections, and this one isolates the weaker-looking half.

    A mutation run showed that deleting the `break` changed nothing -- because
    the limiter's cooldown blocks the second source anyway. That is defence in
    depth working, but it means the previous test cannot tell whether the loop
    itself stops. So: a limiter that never blocks, and only the `break` left.
    """
    import src.rate_limiter as rl

    class _Deaf:
        """Records nothing, blocks nothing."""

        def acquire(self, *a, **k):
            return 0.0

        def observe(self, *a, **k):
            return None

    monkeypatch.setattr(rl, "outbound", _Deaf())
    monkeypatch.setattr(hf, "_hf_token", lambda: "")

    calls = []

    def _open(req, timeout=None):
        calls.append(req.full_url)
        raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {}, None)

    monkeypatch.setattr(hf.urllib.request, "urlopen", _open)
    monkeypatch.setattr(hf, "_cache_fresh", lambda _p: False)
    monkeypatch.setattr(hf, "_write_cache", lambda *a, **k: None)
    monkeypatch.setattr(hf, "load_cached_hf_collection_models", lambda: [])
    monkeypatch.setattr(hf, "_last_forced_refresh", 0.0)

    hf.refresh_hf_collection_models_cache(force=True)
    assert len(calls) == 1, (
        f"with the cooldown removed, a 429 produced {len(calls)} requests across "
        f"{len(hf.HF_COLLECTION_SOURCES)} sources -- the loop is not stopping on its own"
    )


def test_a_rate_limit_reaches_the_limiter(no_pacing, monkeypatch):
    def _open(req, timeout=None):
        raise urllib.error.HTTPError(
            req.full_url, 429, "Too Many Requests", {"Retry-After": "600"}, None
        )

    monkeypatch.setattr(hf.urllib.request, "urlopen", _open)
    with pytest.raises(urllib.error.HTTPError):
        hf.fetch_collection_models(hf.HF_COLLECTION_SOURCES[0], budget=[5])
    assert no_pacing.blocked_for("huggingface.co") > 500, (
        "a 429 from this path did not put the host into cooldown"
    )


def test_the_token_the_product_already_has_is_used(seen, monkeypatch):
    """Two other call sites send a Bearer token to this host. This one did not."""
    import src.rate_limiter as rl

    monkeypatch.setattr(rl, "outbound",
                        OutboundHostLimiter({"huggingface.co": HostPolicy(min_interval=0.0)}))
    monkeypatch.setattr(hf, "_hf_token", lambda: "hf_example")
    captured = {}

    def _open(req, timeout=None):
        captured.update(req.headers)
        return _Resp([], req.full_url)

    monkeypatch.setattr(hf.urllib.request, "urlopen", _open)
    monkeypatch.setattr(hf.json, "load", lambda _f: [])
    hf.fetch_collection_models(hf.HF_COLLECTION_SOURCES[0], budget=[1])
    lowered = {k.lower(): v for k, v in captured.items()}
    assert lowered.get("Authorization".lower()) == "Bearer hf_example"


def test_no_token_sends_no_authorization_header(no_pacing, seen, monkeypatch):
    captured = {}

    def _open(req, timeout=None):
        captured.update(req.headers)
        return _Resp([], req.full_url)

    monkeypatch.setattr(hf.urllib.request, "urlopen", _open)
    hf.fetch_collection_models(hf.HF_COLLECTION_SOURCES[0], budget=[1])
    assert not any(k.lower() == "authorization" for k in captured)


def test_force_does_not_bypass_the_politeness_floor(no_pacing, seen, monkeypatch):
    """`force` skips the staleness check. It does not make the button spammable."""
    import time as _t

    monkeypatch.setattr(hf, "_cache_fresh", lambda _p: False)
    monkeypatch.setattr(hf, "_write_cache", lambda *a, **k: None)
    monkeypatch.setattr(hf, "load_cached_hf_collection_models", lambda: [])
    monkeypatch.setattr(hf, "_last_forced_refresh", _t.time())

    hf.refresh_hf_collection_models_cache(force=True)
    assert seen == [], "a second forced refresh went straight back out to the host"
