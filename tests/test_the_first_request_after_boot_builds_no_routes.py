# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1581` — the app builds its routers at start-up, so the first request after
boot is no slower than the second.

FastAPI 0.141 builds an included router's routes the first time a request has
to walk past it. `app.py` includes 54 routers and registers the page itself
(`/`, `/login`) after all of them, so the first page load built all 641 routes
on the event loop while every other request waited.

**Measured before the fix, on `f3a9150e`** (this file's own server, a loaded
2-CPU box): `/login` answered its first request in **689 ms** and its second
in 56 ms; building the 54 routers in-process took **352 ms**. After:
`/login` 65 ms then 53 ms.

Driven (`Law 20`): the real `app.py` booted out of process on a throwaway data
directory (`scripts/showcase/capture.Server`), timed from outside; and the real
FastAPI's lazy build, counted, for `build_routes` itself.
"""
from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "showcase"))

from src.app_helpers import build_routes  # noqa: E402


def _nested_app():
    """Two routers, one inside the other, and a route of the app's own after
    them — `app.py`'s shape in miniature."""
    inner = APIRouter(prefix="/inner")

    @inner.get("/x")
    def inner_x():
        return {"at": "inner"}

    outer = APIRouter(prefix="/outer")

    @outer.get("/y")
    def outer_y():
        return {"at": "outer"}

    outer.include_router(inner)
    app = FastAPI()
    app.include_router(outer)

    @app.get("/page")
    def page():
        return {"at": "page"}

    return app


def _count_builds(monkeypatch):
    from fastapi import routing

    built = []
    real = routing._IncludedRouter._build_effective_context

    def spy(self, route):
        built.append(getattr(route, "path", "?"))
        return real(self, route)

    monkeypatch.setattr(routing._IncludedRouter, "_build_effective_context", spy)
    return built


def test_without_it_the_first_request_builds_every_router_it_walks_past(monkeypatch):
    """The premise, on the FastAPI this tree pins: a request for the app's own
    page builds the routers in front of it."""
    built = _count_builds(monkeypatch)
    client = TestClient(_nested_app())
    assert client.get("/page").json() == {"at": "page"}
    assert built, "this FastAPI builds eagerly; B1581's premise no longer holds"


def test_built_at_start_up_no_request_builds_a_route(monkeypatch):
    app = _nested_app()
    built = _count_builds(monkeypatch)
    assert build_routes(app) == 2          # the outer router and the one inside it
    at_start = len(built)
    assert at_start >= 2
    client = TestClient(app)
    for path, at in (("/page", "page"), ("/outer/y", "outer"), ("/outer/inner/x", "inner")):
        assert client.get(path).json() == {"at": at}
    assert len(built) == at_start, f"a request built routes: {built[at_start:]}"


def test_a_router_with_nothing_lazy_is_walked_past():
    assert build_routes(FastAPI()) == 0
    assert build_routes(object()) == 0


@pytest.fixture(scope="module")
def booted(tmp_path_factory):
    import capture

    data = tmp_path_factory.mktemp("b1581") / "data"
    data.mkdir()
    server = capture.Server(sys.executable, data, capture._free_port(),
                            extra_env={"PANTHEON_DISABLE_MCP": "1"})
    try:
        server.start(timeout=150)
    except RuntimeError as e:
        server.stop()
        pytest.fail(f"{e}\n{server.log_path.read_text(encoding='utf-8', errors='replace')[-3000:]}")
    try:
        yield server
    finally:
        server.stop()


def test_the_first_page_after_boot_is_no_slower_than_the_second(booted):
    """`/login` is registered after all 54 routers, so its first request walks
    every one of them. `capture.Server.start` has already asked
    `/api/auth/status` (the first router) until it answered, which is what a
    browser's first request is not."""
    import httpx

    def timed(path):
        t = time.perf_counter()
        r = httpx.get(booted.base + path, timeout=30)
        assert r.status_code == 200, (path, r.status_code)
        return (time.perf_counter() - t) * 1000

    first = timed("/login")
    rest = [timed("/login") for _ in range(4)]
    typical = statistics.median(rest)
    # Not `first <= typical`: one request on a shared box varies by tens of
    # milliseconds either way. The build it no longer pays was ~600 ms here.
    assert first <= 2 * typical + 120, (
        f"the first /login took {first:.0f} ms and the next ones {typical:.0f} ms: "
        f"the first request is building what start-up should have")
