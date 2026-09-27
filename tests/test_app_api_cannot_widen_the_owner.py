# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B896`. The agent's generic `app_api` bridge is the owner on every internal
route (loopback carries the internal-tool token, `app.py` attributes it to the
owner, `require_admin` accepts the token outright). This proves the trust
surface it must not reach is refused — through the *real* `do_app_api` executor,
against the *real* backup router and the *real* allow-rule store — and that the
door was real before the block (`Law 3`: the premise is measured, not assumed).

Not one assertion greps a source file (`Law 20`): each drives the executor and
reads a stored value or a routed request.
"""

from __future__ import annotations

import json

import httpx
import pytest

from src.tools.system import do_app_api


# ── isolate the settings/features files the backup route writes ──────────────
def _seed(settings_path, features_path, *, email_confirm=True, deep_research=False):
    settings_path.write_text(json.dumps({"agent_email_confirm": email_confirm}), encoding="utf-8")
    features_path.write_text(json.dumps({"deep_research": deep_research}), encoding="utf-8")


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Point `src.settings` at temp files so a write here moves nothing real."""
    import src.settings as S

    sp = tmp_path / "settings.json"
    fp = tmp_path / "features.json"
    _seed(sp, fp)
    monkeypatch.setattr(S, "SETTINGS_FILE", str(sp))
    monkeypatch.setattr(S, "FEATURES_FILE", str(fp))
    S._invalidate_caches()
    yield S
    S._invalidate_caches()


def _real_backup_app():
    """A FastAPI app carrying the *real* `POST /api/import` handler.

    No `AuthMiddleware`: `require_admin` accepts the internal-tool token header
    directly (`core/middleware.py`), which is the exact power `B896` is about —
    the loopback token is admin on this route with nothing else in the request.
    The body used below only touches the settings/features sections, so the
    three manager fakes are never called.
    """
    from fastapi import FastAPI
    from routes.backup_routes import setup_backup_routes

    class _Mgr:
        def load(self, **k):
            return []

        def load_all_for_update(self):
            return []

        def load_all(self):
            return []

        def get_all(self):
            return {}

        def save(self, *a, **k):
            return None

    app = FastAPI()
    app.include_router(setup_backup_routes(_Mgr(), _Mgr(), _Mgr()))
    return app


def _route_httpx_into(app, monkeypatch):
    """Make `do_app_api`'s httpx loopback land on `app` (real router) in-process."""
    real_init = httpx.AsyncClient.__init__

    def _init(self, *a, **k):
        k.pop("timeout", None)
        k["transport"] = httpx.ASGITransport(app=app)
        real_init(self, *a, **k)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", _init)


def _call(method, path, body=None):
    args = {"action": "call", "method": method, "path": path}
    if body is not None:
        args["body"] = body
    return do_app_api(json.dumps(args), owner="admin")


# ── the premise: the door is real (Law 3) ────────────────────────────────────
@pytest.mark.asyncio
async def test_the_loopback_token_really_is_admin_on_import(store, monkeypatch):
    """Directly, with the internal-tool token, `POST /api/import` moves the
    owner's restraints — `agent_email_confirm` off and a disabled feature on.
    If this ever stops being true the block below is guarding a closed door."""
    app = _real_backup_app()
    from core.middleware import INTERNAL_TOOL_HEADER, INTERNAL_TOOL_TOKEN

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://internal") as client:
        resp = await client.post(
            "/api/import",
            headers={INTERNAL_TOOL_HEADER: INTERNAL_TOOL_TOKEN},
            json={"settings": {"agent_email_confirm": False}, "features": {"deep_research": True}},
        )
    assert resp.status_code == 200, resp.text
    assert store.load_settings()["agent_email_confirm"] is False
    assert store.load_features()["deep_research"] is True


# ── the fix: the real executor refuses, and nothing moves ────────────────────
@pytest.mark.asyncio
async def test_app_api_refuses_import_and_the_restraints_do_not_move(store, monkeypatch):
    app = _real_backup_app()
    _route_httpx_into(app, monkeypatch)

    res = await _call("POST", "/api/import",
                      {"settings": {"agent_email_confirm": False}, "features": {"deep_research": True}})

    assert res["exit_code"] == 1
    low = res["error"].lower()
    assert "only the person" in low or "the person can" in low
    assert "settings" in low  # points at the UI (Law 10/Law 15)
    # The whole point: measured by the stored value, nothing moved.
    assert store.load_settings()["agent_email_confirm"] is True
    assert store.load_features()["deep_research"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("spelling", [
    "/api/x/../import",       # httpx collapses `..` before it sends
    "/api/./import",
    "/api/imp%6frt",          # percent-decoded to /api/import
    "/api/import/",           # trailing slash
    "/api/%2e%2e/api/import",
])
async def test_app_api_import_evasions_are_refused_and_nothing_moves(store, monkeypatch, spelling):
    """A raw-string `startswith` names the door and lets it be walked around;
    the normaliser closes every spelling that reaches the handler."""
    app = _real_backup_app()
    _route_httpx_into(app, monkeypatch)

    res = await _call("POST", spelling,
                      {"settings": {"agent_email_confirm": False}, "features": {"deep_research": True}})

    assert res["exit_code"] == 1
    assert store.load_settings()["agent_email_confirm"] is True
    assert store.load_features()["deep_research"] is False


# ── the allow-rule door: real store, temp DB ─────────────────────────────────
@pytest.fixture
def allow_rule_db(tmp_path, monkeypatch):
    """Rebind the allow-rule store's `SessionLocal` to a temp file DB.

    `tool_allow_rules._database()` reads `core.database.SessionLocal` live, so a
    monkeypatch here is what the real `create_rule`/`list_rules` use."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import core.database as cdb

    engine = create_engine(
        f"sqlite:///{tmp_path / 'rules.db'}",
        connect_args={"check_same_thread": False},
    )
    cdb.Base.metadata.create_all(engine, tables=[cdb.ToolAllowRule.__table__])
    monkeypatch.setattr(cdb, "SessionLocal", sessionmaker(bind=engine))
    return cdb


@pytest.mark.asyncio
async def test_the_allow_rule_store_really_writes(allow_rule_db):
    """Premise (Law 3): `create_rule` persists a standing rule, so the block is
    stopping a door that widens the assistant's reach next run."""
    from src import tool_allow_rules

    tool_allow_rules.create_rule("admin", "bash", "prefix", "git ")
    assert len(tool_allow_rules.list_rules("admin")) == 1


@pytest.mark.asyncio
async def test_app_api_refuses_the_allow_rule_and_no_rule_is_planted(allow_rule_db, monkeypatch):
    from src import tool_allow_rules

    built = []

    class _Boom:
        def __init__(self, *a, **k):
            built.append(True)
            raise RuntimeError("NETWORK_ATTEMPTED")

    monkeypatch.setattr(httpx, "AsyncClient", _Boom)

    res = await _call("POST", "/api/tool-allow-rules",
                      {"tool_name": "bash", "match_kind": "prefix", "pattern": "git "})

    assert res["exit_code"] == 1
    assert "allow rule" in res["error"].lower()
    assert "only the person can add one" in res["error"].lower()
    assert built == []                              # refused before any request
    assert tool_allow_rules.list_rules("admin") == []


# ── every trust-surface door, through the real executor, no request issued ────
_BLOCKED = [
    ("GET", "/api/export"),
    ("POST", "/api/import"),
    ("POST", "/api/tool-allow-rules"),
    ("POST", "/api/tools"),
    ("POST", "/api/mcp/servers"),
    ("PUT", "/api/mcp/servers/s1"),
    ("PATCH", "/api/mcp/servers/s1"),
    ("DELETE", "/api/mcp/servers/s1"),
    ("POST", "/api/mcp/servers/s1/call"),
    ("POST", "/api/mcp/servers/s1/reconnect"),
    # evasions
    ("POST", "/api/x/../tools"),
    ("POST", "/api/mcp/x/../servers"),
    ("POST", "/api/imp%6frt"),
    # the existing FORBIDDEN.md Part 2 shell control, now un-bypassable
    ("POST", "/api/shell/exec"),
    ("POST", "/api/x/../shell/exec"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", _BLOCKED)
async def test_blocked_doors_never_reach_the_network(monkeypatch, method, path):
    built = []

    class _Boom:
        def __init__(self, *a, **k):
            built.append((method, path))
            raise RuntimeError("NETWORK_ATTEMPTED")

    monkeypatch.setattr(httpx, "AsyncClient", _Boom)

    res = await _call(method, path, {"x": 1})
    assert res["exit_code"] == 1
    assert built == [], f"{method} {path} issued a request instead of refusing"


@pytest.mark.asyncio
async def test_an_allowed_path_still_reaches_the_network(monkeypatch):
    """The recorder is honest: a path that is NOT on the blocklist gets past the
    guard and builds the client. Otherwise every test above passes vacuously."""
    built = []

    class _Boom:
        def __init__(self, *a, **k):
            built.append(True)
            raise RuntimeError("NETWORK_ATTEMPTED")

    monkeypatch.setattr(httpx, "AsyncClient", _Boom)

    res = await _call("GET", "/api/cookbook/gpus")
    assert res["exit_code"] == 1
    assert built == [True]                          # reached the request line


@pytest.mark.asyncio
async def test_backup_export_is_refused_because_it_unmasks_secrets(monkeypatch):
    """`GET /api/export` returns `load_settings()` raw — the credential keys
    `manage_settings` masks. The refusal says so and points at the UI."""
    built = []

    class _Boom:
        def __init__(self, *a, **k):
            built.append(True)
            raise RuntimeError("NETWORK_ATTEMPTED")

    monkeypatch.setattr(httpx, "AsyncClient", _Boom)

    res = await _call("GET", "/api/export")
    assert res["exit_code"] == 1
    low = res["error"].lower()
    assert "key" in low or "secret" in low
    assert "only the person" in low
    assert built == []


@pytest.mark.asyncio
async def test_endpoint_discovery_hides_the_trust_surface(monkeypatch):
    """`endpoints` reads the same blocklist, so the agent is not even told these
    exist. Stubs the OpenAPI fetch the way the existing discovery tests do."""
    class _Resp:
        def json(self):
            return {"paths": {
                "/api/import": {"post": {"summary": "Import"}},
                "/api/tools": {"post": {"summary": "Update tools"}, "get": {"summary": "List tools"}},
                "/api/tool-allow-rules": {"post": {"summary": "Add rule"}, "get": {"summary": "List rules"}},
                "/api/mcp/servers": {"post": {"summary": "Add server"}},
                "/api/mcp/servers/{id}/call": {"post": {"summary": "Call tool"}},
                "/api/cookbook/gpus": {"get": {"summary": "GPUs"}},
            }}

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)

    res = await do_app_api(json.dumps({"action": "endpoints"}), owner="admin")
    pairs = {(e["method"], e["path"]) for e in res["endpoints"]}
    assert ("POST", "/api/import") not in pairs
    assert ("POST", "/api/tools") not in pairs
    assert ("POST", "/api/tool-allow-rules") not in pairs
    assert ("POST", "/api/mcp/servers") not in pairs
    assert ("POST", "/api/mcp/servers/{id}/call") not in pairs
    # Reads and unrelated routes still surface.
    assert ("GET", "/api/tools") in pairs
    assert ("GET", "/api/tool-allow-rules") in pairs
    assert ("GET", "/api/cookbook/gpus") in pairs


@pytest.mark.asyncio
async def test_reads_and_revocations_stay_open(monkeypatch):
    """One-directional (`P7-02`): the assistant may look and may stand itself
    down, it may not hand itself more. A GET on the trust surfaces and a DELETE
    that revokes are not blocked."""
    built = []

    class _Boom:
        def __init__(self, *a, **k):
            built.append(True)
            raise RuntimeError("NETWORK_ATTEMPTED")

    monkeypatch.setattr(httpx, "AsyncClient", _Boom)

    for method, path in [
        ("GET", "/api/tool-allow-rules"),
        ("GET", "/api/mcp/servers"),
        ("GET", "/api/tools"),
        ("DELETE", "/api/tool-allow-rules/some-id"),
    ]:
        built.clear()
        res = await _call(method, path)
        assert res["exit_code"] == 1               # the network fake raised
        assert built == [True], f"{method} {path} was refused but should be open"
