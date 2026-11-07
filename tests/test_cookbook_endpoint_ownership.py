# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1928`. Launching a model deleted endpoints that still had a server behind them.

When the Forge registered a serve's endpoint it deleted every other Forge row
(`local-…`) with the same display name, and the display name is the repo's
short name. A second serve of the same repo on the next port (the Forge's
*Launch anyway*, which says the first serve stays), the same repo on a second
host, or another organisation's repo of the same name took the first serve's
row away while that server was still answering, and a default that named the
row was left naming nothing. A serve that crashed at start-up had its watchdog
delete the row it had been handed, which is whatever row sat at the serve's
URL: a hand-added endpoint, its API key with it, when the key made the
watchdog's probe answer 401. And an older serve's watchdog or scheduled stop
deleted the row a newer serve at the same URL had reused under the same id.

Now registering deletes nothing else. Each row records the serve that owns it
(`model_endpoints.cookbook_serve_session_id`, added by a start-up migration;
rows from before it stay NULL and are never deleted automatically). The
watchdog deletes only a `local-` row its own serve still owns, and asks again
in the DELETE itself. The scheduled stop names its serve on the DELETE, and the
route removes the row only for that owner, answering 409 and changing nothing,
settings included, for anyone else. A DELETE that names no serve is as before.

Ported from upstream Odysseus 6f2b58c8 (#6969), adapted: the stop keeps its
read of the endpoint list, the watchdog's delete stays in-process, and the
migration is the house PRAGMA shape.

Driven (`Law 20`): the real `/api/model/serve` handler, the real registration
and watchdog closures and the real endpoint routes, over a real SQLite file;
only the launch, the tmux pane and the model server's answer are stand-ins.
"""
from __future__ import annotations

import asyncio
import functools
import os
import sqlite3
import types
import urllib.error
import urllib.request

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import core.database as database
from core.database import ModelEndpoint
from routes.cookbook_helpers import ServeRequest
from tests.helpers.sqlite_db import make_temp_sqlite

CRASHED_PANE = b"Traceback (most recent call last):\n=== Process exited with code 1 ===\n"


@pytest.fixture
def forge(tmp_path, monkeypatch):
    """A Forge over a temp database; settings in a temp file. Returns the
    database's session factory."""
    import routes.model_routes as model_routes
    import routes.prefs_routes as prefs_routes
    import src.ai_interaction as ai_interaction
    import src.constants
    import src.settings

    factory, engine, tmpfile = make_temp_sqlite(database.Base.metadata)
    monkeypatch.setattr(database, "SessionLocal", factory)
    monkeypatch.setattr(model_routes, "SessionLocal", factory)
    # Nothing answers on these ports; what registration probes is not the question.
    monkeypatch.setattr(model_routes, "_probe_endpoint", lambda *a, **k: None)
    settings_file = str(tmp_path / "settings.json")
    monkeypatch.setattr(src.constants, "SETTINGS_FILE", settings_file)
    monkeypatch.setattr(src.settings, "SETTINGS_FILE", settings_file)
    src.settings._invalidate_caches()
    monkeypatch.setattr(model_routes, "COOKBOOK_STATE_FILE", str(tmp_path / "no-forge-state.json"))
    prefs: dict = {}
    monkeypatch.setattr(prefs_routes, "_load", lambda: prefs)
    monkeypatch.setattr(prefs_routes, "_save", lambda value: prefs.update(value))
    monkeypatch.setattr(ai_interaction, "get_session_manager", lambda: None)
    yield factory
    src.settings._invalidate_caches()
    engine.dispose()
    os.unlink(tmpfile.name)


@functools.lru_cache(maxsize=None)
def _cookbook_router():
    from routes.cookbook_routes import setup_cookbook_routes
    return setup_cookbook_routes()


def _closure(name):
    """A function defined inside `setup_cookbook_routes`, taken from the real
    router's handlers by the name it is closed over as."""
    for route in _cookbook_router().routes:
        fn = getattr(route, "endpoint", None)
        code = getattr(fn, "__code__", None)
        if code and name in code.co_freevars:
            return fn.__closure__[code.co_freevars.index(name)].cell_contents
    raise AssertionError(f"no handler closes over {name}")


def _register(repo_id, port, *, remote=None, serve=None):
    """Register an LLM serve's endpoint the way `model_serve` does."""
    register = _closure("_auto_register_llm_endpoint")
    req = ServeRequest(repo_id=repo_id, cmd=f"vllm serve {repo_id} --port {port}")
    ep_id = register(req, remote) if serve is None else register(req, remote, serve_session_id=serve)
    assert ep_id
    return ep_id


def _row(factory, ep_id):
    with factory() as db:
        return db.get(ModelEndpoint, ep_id)


def _ids(factory):
    with factory() as db:
        return {row.id for row in db.query(ModelEndpoint).all()}


def _add_by_hand(factory, ep_id, base_url, api_key="sk-added-by-hand"):
    """An endpoint added in Settings, with the id `POST /api/model-endpoints` mints."""
    with factory() as db:
        db.add(ModelEndpoint(id=ep_id, name="My vLLM", base_url=base_url, api_key=api_key,
                             is_enabled=True, model_type="llm"))
        db.commit()


def _unauthorized(url, *a, **k):
    raise urllib.error.HTTPError(str(url), 401, "Unauthorized", {}, None)


def _crash_world(monkeypatch, *, probe=_unauthorized):
    """The serve's tmux pane ends in a non-zero exit marker and its URL answers
    the watchdog's keyless probe with `probe`. Patched where `cookbook_routes`
    reads them, not on the `asyncio` module."""
    import routes.cookbook_routes as cookbook_routes

    class _Pane:
        returncode = 0

        async def communicate(self, *a, **k):
            return CRASHED_PANE, b""

        async def wait(self):
            return 0

    async def _capture(*argv, **kwargs):
        return _Pane()

    async def _no_wait(seconds):
        return None

    world = types.SimpleNamespace(**{k: getattr(asyncio, k) for k in dir(asyncio)
                                     if not k.startswith("__")})
    world.create_subprocess_exec = _capture
    world.sleep = _no_wait
    monkeypatch.setattr(cookbook_routes, "asyncio", world)
    monkeypatch.setattr(urllib.request, "urlopen", probe)
    return world


def _watchdog(endpoint_id, session_id):
    watchdog = _closure("_serve_crash_watchdog")
    asyncio.run(watchdog(endpoint_id=endpoint_id, session_id=session_id, remote=None,
                         ssh_port=None, is_windows=False))


# -- registration deletes nothing else -------------------------------------------

LAUNCHES = {
    "the same repo on the next port": [("Qwen/Qwen3-8B", 8001, None), ("Qwen/Qwen3-8B", 8002, None)],
    "another organisation's repo of the same name": [
        ("meta-llama/Llama-3.1-8B-Instruct", 8001, None),
        ("unsloth/Llama-3.1-8B-Instruct", 8002, None)],
    "the same repo on a second host": [("Qwen/Qwen3-8B", 8000, "gpu-a"), ("Qwen/Qwen3-8B", 8000, "gpu-b")],
}


@pytest.mark.parametrize("label", list(LAUNCHES))
def test_a_second_serve_of_the_same_name_keeps_the_first_serves_endpoint(forge, label):
    (repo_a, port_a, host_a), (repo_b, port_b, host_b) = LAUNCHES[label]
    first = _register(repo_a, port_a, remote=host_a)
    second = _register(repo_b, port_b, remote=host_b)
    assert first != second
    assert _ids(forge) == {first, second}, f"{label}: the first serve's endpoint was swept"


def test_a_relaunch_onto_a_port_another_row_has_keeps_the_running_serves_row(forge):
    """The reuse path swept too: the row at 8002 is reused for Qwen3-8B, and
    Qwen3-8B's running serve on 8001 lost its row."""
    other = _register("meta-llama/Llama-3.1-8B", 8002)
    running = _register("Qwen/Qwen3-8B", 8001)
    reused = _register("Qwen/Qwen3-8B", 8002)
    assert reused == other
    assert running in _ids(forge)


# -- the crash watchdog ----------------------------------------------------------

def _serve_through_the_route(monkeypatch, tmp_path, cmd, repo_id="org/model"):
    """`POST /api/model/serve`'s handler, with the launch replaced; returns its
    answer and the crash watchdog it scheduled, not yet run."""
    import routes.cookbook_routes as cookbook_routes
    from starlette.requests import Request

    world = _crash_world(monkeypatch)
    scheduled = []

    class _Launched:
        returncode = 0

        async def wait(self):
            return 0

    async def _launch(*a, **k):
        return _Launched()

    async def _have(*a, **k):
        return True

    world.create_subprocess_shell = _launch
    world.create_task = scheduled.append
    monkeypatch.setattr(cookbook_routes, "TMUX_LOG_DIR", tmp_path / "tmux")
    monkeypatch.setattr(cookbook_routes, "require_operator", lambda request: None)
    monkeypatch.setattr(cookbook_routes, "_binary_available", _have)
    monkeypatch.setattr(cookbook_routes, "load_stored_hf_token", lambda **k: "")
    serve = next(r.endpoint for r in _cookbook_router().routes
                 if getattr(r, "path", "") == "/api/model/serve" and "POST" in r.methods)
    request = Request({"type": "http", "method": "POST", "path": "/api/model/serve", "headers": []})
    out = asyncio.run(serve(request, ServeRequest(repo_id=repo_id, cmd=cmd)))
    assert out["ok"] is True, out
    return out, scheduled


def test_a_serve_that_crashes_on_a_hand_added_endpoints_url_leaves_it_and_its_key(
        forge, monkeypatch, tmp_path):
    """The hand-added endpoint's key makes the probe answer 401, which the
    watchdog read as "not reachable". The serve's own row still goes."""
    _add_by_hand(forge, "a1b2c3d4", "http://localhost:8001/v1")
    out, scheduled = _serve_through_the_route(monkeypatch, tmp_path, "vllm serve org/model --port 8001")
    assert out["endpoint_id"] == "a1b2c3d4"   # registration reuses the row at its URL
    [watchdog] = scheduled
    asyncio.run(watchdog)
    kept = _row(forge, "a1b2c3d4")
    assert kept is not None, "the watchdog deleted a hand-added endpoint"
    assert kept.api_key == "sk-added-by-hand"

    out, scheduled = _serve_through_the_route(monkeypatch, tmp_path, "vllm serve org/model --port 8002")
    own = out["endpoint_id"]
    assert own.startswith("local-")
    assert _row(forge, own).cookbook_serve_session_id == out["session_id"]
    [watchdog] = scheduled
    asyncio.run(watchdog)
    assert _row(forge, own) is None, "a crashed serve's own endpoint stays removed"


def test_an_older_serves_watchdog_leaves_the_row_a_newer_serve_reused(forge, monkeypatch):
    _crash_world(monkeypatch)
    old = _register("organization-a/Model-A", 8001, serve="serve-old")
    new = _register("organization-b/Model-B", 8001, serve="serve-new")
    assert old == new
    assert _row(forge, new).cookbook_serve_session_id == "serve-new"
    _watchdog(old, "serve-old")
    assert _row(forge, new) is not None
    _watchdog(new, "serve-new")
    assert _row(forge, new) is None


def test_a_serve_that_takes_the_row_over_during_the_watchdogs_probe_keeps_it(forge, monkeypatch):
    ep_id = _register("organization-a/Model-A", 8001, serve="serve-old")

    def _relaunched_meanwhile(url, *a, **k):
        assert _register("organization-b/Model-B", 8001, serve="serve-new") == ep_id
        raise urllib.error.URLError("connection refused")

    _crash_world(monkeypatch, probe=_relaunched_meanwhile)
    _watchdog(ep_id, "serve-old")
    row = _row(forge, ep_id)
    assert row is not None and row.cookbook_serve_session_id == "serve-new"


# -- the DELETE route and the scheduled stop -------------------------------------

def _endpoint_api(monkeypatch):
    import routes.model_routes as model_routes
    monkeypatch.setattr(model_routes, "require_operator", lambda request: None)
    monkeypatch.setattr(model_routes, "runs_instance", lambda request: True)
    app = FastAPI()
    app.include_router(model_routes.setup_model_routes(None))
    return app


def _default_endpoint():
    import src.settings
    return src.settings.load_settings().get("default_endpoint_id")


def _make_default(ep_id):
    import src.settings
    settings = src.settings.load_settings()
    settings["default_endpoint_id"] = ep_id
    settings["default_model"] = "organization-b/Model-B"
    src.settings.save_settings(settings)


def test_the_delete_route_removes_a_forge_row_only_for_the_serve_that_owns_it(forge, monkeypatch):
    client = TestClient(_endpoint_api(monkeypatch))
    old = _register("organization-a/Model-A", 8001, serve="serve-old")
    reused = _register("organization-b/Model-B", 8001, serve="serve-new")
    assert old == reused
    _make_default(reused)
    _add_by_hand(forge, "a1b2c3d4", "http://localhost:9000/v1")

    for owner in ("serve-old", ""):
        res = client.delete(f"/api/model-endpoints/{reused}",
                            params={"expected_cookbook_serve_session_id": owner})
        assert res.status_code == 409, (owner, res.text)
    res = client.delete("/api/model-endpoints/a1b2c3d4",
                        params={"expected_cookbook_serve_session_id": "serve-new"})
    assert res.status_code == 409, res.text
    assert _ids(forge) == {reused, "a1b2c3d4"}
    assert _default_endpoint() == reused, "a refused delete cleared the default"

    res = client.delete(f"/api/model-endpoints/{reused}",
                        params={"expected_cookbook_serve_session_id": "serve-new"})
    assert res.status_code == 200, res.text
    assert _row(forge, reused) is None and _default_endpoint() == ""

    # Naming no serve is a person's delete, as before.
    assert client.delete("/api/model-endpoints/a1b2c3d4").status_code == 200
    assert _ids(forge) == set()


def _stop_world(monkeypatch):
    """The scheduled stop's httpx client lands on the real endpoint routes;
    every request it sends is recorded."""
    import src.cookbook_serve_lifecycle as lifecycle
    transport = httpx.ASGITransport(app=_endpoint_api(monkeypatch))
    sent = []

    async def _record(request):
        sent.append((request.method, request.url.path, dict(request.url.params)))

    class _Loopback(httpx.AsyncClient):
        def __init__(self, *a, **k):
            k.pop("mounts", None)
            super().__init__(*a, transport=transport, event_hooks={"request": [_record]}, **k)

    monkeypatch.setattr(lifecycle, "httpx", types.SimpleNamespace(AsyncClient=_Loopback))
    return lifecycle, sent


def test_a_scheduled_stop_deletes_only_the_row_its_own_serve_still_owns(forge, monkeypatch):
    lifecycle, sent = _stop_world(monkeypatch)
    old = _register("organization-a/Model-A", 8001, serve="serve-old")
    reused = _register("organization-b/Model-B", 8001, serve="serve-new")
    assert old == reused
    _make_default(reused)

    asyncio.run(lifecycle._delete_endpoint_for_task(
        {"_endpointId": old, "sessionId": "serve-old", "type": "serve"}))
    assert sent == [("GET", "/api/model-endpoints", {}),
                    ("DELETE", f"/api/model-endpoints/{old}",
                     {"expected_cookbook_serve_session_id": "serve-old"})]
    assert _row(forge, reused) is not None and _default_endpoint() == reused

    sent.clear()
    asyncio.run(lifecycle._delete_endpoint_for_task(
        {"_endpointId": reused, "sessionId": "serve-new", "type": "serve"}))
    assert sent[-1] == ("DELETE", f"/api/model-endpoints/{reused}",
                        {"expected_cookbook_serve_session_id": "serve-new"})
    assert _row(forge, reused) is None and _default_endpoint() == ""


def test_a_scheduled_stop_never_deletes_a_row_no_serve_owns(forge, monkeypatch):
    """A row from before the owner column (NULL), and a task that names no
    serve: nothing is deleted, and the second sends no DELETE at all."""
    lifecycle, sent = _stop_world(monkeypatch)
    legacy = _register("organization-a/Model-A", 8003)
    assert _row(forge, legacy).cookbook_serve_session_id is None
    asyncio.run(lifecycle._delete_endpoint_for_task(
        {"_endpointId": legacy, "sessionId": "serve-old", "type": "serve"}))
    assert _row(forge, legacy) is not None

    owned = _register("organization-b/Model-B", 8004, serve="serve-current")
    sent.clear()
    asyncio.run(lifecycle._delete_endpoint_for_task({"_endpointId": owned, "type": "serve"}))
    assert [m for m, _p, _q in sent if m == "DELETE"] == []
    assert _row(forge, owned) is not None


# -- the migration ---------------------------------------------------------------

def test_an_older_database_gains_the_owner_column_once_and_its_rows_stay_unowned(tmp_path, monkeypatch):
    path = tmp_path / "before-b1928.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE model_endpoints (id VARCHAR PRIMARY KEY, name VARCHAR NOT NULL, "
                     "base_url VARCHAR NOT NULL)")
        conn.execute("INSERT INTO model_endpoints VALUES ('local-0ld0ld00', 'Qwen3-8B', "
                     "'http://localhost:8001/v1')")
    monkeypatch.setattr(database, "DATABASE_URL", f"sqlite:///{path}")
    database._migrate_add_cookbook_serve_session_id_column()
    database._migrate_add_cookbook_serve_session_id_column()
    with sqlite3.connect(path) as conn:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(model_endpoints)")]
        owners = conn.execute("SELECT cookbook_serve_session_id FROM model_endpoints").fetchall()
    assert columns.count("cookbook_serve_session_id") == 1
    assert owners == [(None,)]
