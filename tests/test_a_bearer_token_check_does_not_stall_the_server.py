# SPDX-License-Identifier: AGPL-3.0-or-later
"""An API-token request does not freeze every other request on the server.

`AuthMiddleware` checked a bearer token with `bcrypt.checkpw` inline in its
`async def dispatch`. At bcrypt's default cost that is ~0.3 s of CPU on the
event loop, once per bearer-authenticated request: measured on main
(`0bf49e44`) the loop stalled 293 ms per call, so the Claude/Codex skill, the
companion and any script holding a token froze the chat for everyone while it
worked. The check now runs in a thread, and a token that already passed is
recognised by its SHA-256 without bcrypt, for as long as its row is still an
active candidate: a revoked token stops working on the next request.
"""
from __future__ import annotations

import asyncio
import logging
import secrets
import time

import bcrypt
import httpx
import pytest


@pytest.fixture()
def bearer_app(monkeypatch):
    import app as A
    from core.api_tokens import ACCEPTED_TOKEN_PREFIXES

    raw = ACCEPTED_TOKEN_PREFIXES[0] + secrets.token_urlsafe(32)
    thash = bcrypt.hashpw(raw.encode(), bcrypt.gensalt()).decode()
    monkeypatch.setattr(type(A.auth_manager), "is_configured", property(lambda self: True))
    users = dict(A.auth_manager._config.get("users", {}))
    users["alice"] = {"role": "admin"}
    monkeypatch.setitem(A.auth_manager._config, "users", users)
    saved = dict(A._token_cache)
    A._token_cache.clear()
    A._token_cache[raw[:8]] = [("tok1", thash, "alice", ["chat"])]
    A._verified_bearer.clear()
    monkeypatch.setattr(A, "_token_cache_built_version", A._token_cache_version)
    logging.disable(logging.CRITICAL)
    try:
        yield A, raw
    finally:
        logging.disable(logging.NOTSET)
        A._token_cache.clear()
        A._token_cache.update(saved)
        A._verified_bearer.clear()


async def _max_loop_stall_during(client, n, raw):
    gaps, stop = [], False

    async def ticker():
        last = time.perf_counter()
        while not stop:
            await asyncio.sleep(0.001)
            now = time.perf_counter()
            gaps.append(now - last)
            last = now

    task = asyncio.create_task(ticker())
    await asyncio.sleep(0.02)
    codes = []
    for _ in range(n):
        r = await client.get("/api/health/detail", headers={"Authorization": "Bearer " + raw})
        codes.append(r.status_code)
    stop = True
    await task
    return max(gaps), codes


def test_a_bearer_request_does_not_block_the_event_loop(bearer_app):
    A, raw = bearer_app

    async def run():
        transport = httpx.ASGITransport(app=A.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as c:
            # Warm the app (middleware stack, lazy imports) on a request that
            # does not carry the token, so only the token check is measured.
            await c.get("/api/health")
            return await _max_loop_stall_during(c, 5, raw)

    stall, codes = asyncio.run(run())
    assert 401 not in codes, codes  # every request authenticated
    assert stall < 0.1, f"event loop stalled {stall * 1000:.0f} ms during bearer auth"


def test_a_revoked_token_stops_matching_although_it_was_verified_before(bearer_app):
    A, raw = bearer_app

    async def get():
        transport = httpx.ASGITransport(app=A.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as c:
            return (await c.get("/api/health/detail",
                                headers={"Authorization": "Bearer " + raw})).status_code

    assert asyncio.run(get()) != 401
    A._token_cache[raw[:8]] = []  # what a refresh leaves after the row is revoked
    assert asyncio.run(get()) == 401


def test_one_invalidation_costs_one_rebuild_not_one_per_request(bearer_app, monkeypatch):
    """The flag this replaced lived in `app.state.__dict__`, so a refresh never
    cleared it: after one invalidation every bearer request rebuilt the map."""
    A, raw = bearer_app
    rows = list(A._token_cache[raw[:8]])
    rebuilds = []

    def fake_refresh():
        rebuilds.append(1)
        building = A._token_cache_version
        A._token_cache[raw[:8]] = rows
        A._token_cache_built_version = building

    monkeypatch.setattr(A, "_refresh_token_cache", fake_refresh)
    A._token_cache_invalidate()

    async def run():
        transport = httpx.ASGITransport(app=A.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as c:
            return [(await c.get("/api/health/detail",
                                 headers={"Authorization": "Bearer " + raw})).status_code
                    for _ in range(5)]

    codes = asyncio.run(run())
    assert 401 not in codes, codes
    assert len(rebuilds) == 1, f"{len(rebuilds)} rebuilds for 5 requests after one invalidation"
