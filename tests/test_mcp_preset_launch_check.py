# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P8-45` — what this install makes of a preset's command, asked before the
person types anything, of the rule itself.

**The premise, re-measured before this was built (`Law 3`).** The row's
decision (`D-2026-09-27-01`) says: *if a preset's command would be refused by
this install's MCP validation, the picker must say so.* Driven, that splits in
two, and the two halves disagree about every preset:

* The Settings form saves through `POST /api/mcp/servers`, the administrator's
  route, which has **no command rule at all** — `P8-47` pins that it accepts
  what the agent path refuses. So on the path the picker fills, **no preset is
  refused**: all fifteen are accepted, which the last case below drives.
* `manage_mcp add`, the assistant's path, runs `_validate_mcp_command`, and all
  fifteen presets start `npx`, which is in `_MCP_DENIED_COMMANDS` — so there
  **every preset is refused**, and `PANTHEON_MCP_ALLOWED_COMMANDS` cannot lift
  it (`FORBIDDEN.md` Part 2).

So `POST /api/mcp/check` answers the two things a person can act on: whether
the assistant could have done this for them (the rule's own sentence, asked of
`_validate_mcp_command` exactly as `P8-47`'s `refusal_on_the_agent_path` asks
it — not a copy), and whether the launcher exists on this machine at all,
which is the refusal that really bites on the form's path: a spawn that
cannot find `npx`, reported after the row was saved.

Every case calls the route or the rule (`Law 20`).
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PRESETS_JS = ROOT / "static" / "js" / "settings" / "mcpPresets.js"


class _FakeRequest:
    def __init__(self, body=None):
        from core.middleware import INTERNAL_TOOL_HEADER, INTERNAL_TOOL_TOKEN

        self.headers = {INTERNAL_TOOL_HEADER: INTERNAL_TOOL_TOKEN}
        self.state = SimpleNamespace(current_user="admin")
        # `B1175`: on the loopback `require_admin` asks about the person the
        # request names, as their own request is asked — this one names the
        # admin, so the app knows them as one.
        self.app = SimpleNamespace(state=SimpleNamespace(auth_manager=SimpleNamespace(
            is_configured=True, is_admin=lambda user: user == "admin")))
        self._body = body

    async def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


class _NoSpawnManager:
    """A manager that fails the case if anything tries to start a server."""

    started = []

    async def connect_server(self, *args, **kwargs):
        _NoSpawnManager.started.append((args, kwargs))
        return False

    def get_server_status(self, server_id):
        return {"status": "disconnected"}

    def get_all_tools(self, *a, **k):
        return []


def _endpoint(path, method, manager=None):
    from routes.mcp.mcp_routes import setup_mcp_routes

    for route in setup_mcp_routes(manager or _NoSpawnManager()).routes:
        if route.path == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"{method} {path} not found")


def _check(body):
    return asyncio.run(_endpoint("/api/mcp/check", "POST")(request=_FakeRequest(body)))


def _db():
    from core.database import Base
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


# ---------------------------------------------------------------------------
# The assistant's path: the rule's own answer
# ---------------------------------------------------------------------------


def test_the_agent_path_refuses_npx_in_the_rules_own_words(monkeypatch):
    """Not a paraphrase: the sentence is whatever `_validate_mcp_command`
    returns for the same registration, so it cannot drift from the rule."""
    from src.agent_tools.admin_tools import _validate_mcp_command

    monkeypatch.delenv("PANTHEON_MCP_ALLOWED_COMMANDS", raising=False)
    body = {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"], "env": {}}
    out = _check(body)

    assert out["assistant"]["verdict"] == "refused"
    assert out["assistant"]["reason"] == _validate_mcp_command("npx", body["args"], {})
    assert "not allowed on the agent MCP path" in out["assistant"]["reason"]
    assert out["command"] == "npx"


def test_the_answer_moves_with_the_operators_allowlist(monkeypatch):
    """`P8-47`'s property from this side: an operator who opts a launcher in
    gets "accepted", not a stale sentence."""
    monkeypatch.delenv("PANTHEON_MCP_ALLOWED_COMMANDS", raising=False)
    refused = _check({"command": "mcp-server-weather", "args": [], "env": {}})
    assert refused["assistant"]["verdict"] == "refused"
    assert "not in the MCP allowlist" in refused["assistant"]["reason"]

    monkeypatch.setenv("PANTHEON_MCP_ALLOWED_COMMANDS", "mcp-server-weather")
    accepted = _check({"command": "mcp-server-weather", "args": [], "env": {}})
    assert accepted["assistant"] == {"verdict": "accepted", "reason": None}


def test_npx_stays_refused_whatever_the_allowlist_says(monkeypatch):
    """`FORBIDDEN.md` Part 2 — the reported RCE — pinned from the picker's
    side: listing `npx` does not open the agent path to a package runner."""
    monkeypatch.setenv("PANTHEON_MCP_ALLOWED_COMMANDS", "npx,uvx")
    out = _check({"command": "npx", "args": ["-y", "pkg"], "env": {}})
    assert out["assistant"]["verdict"] == "refused"
    assert "package runners" in out["assistant"]["reason"]


def test_a_dangerous_variable_is_named_by_the_same_rule(monkeypatch):
    monkeypatch.setenv("PANTHEON_MCP_ALLOWED_COMMANDS", "mcp-server-weather")
    out = _check({"command": "mcp-server-weather", "args": [], "env": {"LD_PRELOAD": "/x.so"}})
    assert out["assistant"]["verdict"] == "refused"
    assert "LD_PRELOAD" in out["assistant"]["reason"]


# ---------------------------------------------------------------------------
# This machine: is the launcher there at all
# ---------------------------------------------------------------------------


def _executable(directory: Path, name: str) -> Path:
    path = directory / name
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(0o755)
    return path


def test_a_launcher_on_path_is_found_and_one_that_is_not_is_missing(tmp_path, monkeypatch):
    _executable(tmp_path, "pantheon-test-launcher")
    monkeypatch.setenv("PATH", str(tmp_path))
    assert _check({"command": "pantheon-test-launcher"})["launcher"] == {"verdict": "found"}
    assert _check({"command": "npx-that-is-not-here"})["launcher"] == {"verdict": "missing"}


def test_a_launcher_given_as_a_path_is_looked_for_where_it_points(tmp_path):
    real = _executable(tmp_path, "server")
    assert _check({"command": str(real)})["launcher"] == {"verdict": "found"}
    assert _check({"command": str(tmp_path / "gone")})["launcher"] == {"verdict": "missing"}
    plain = tmp_path / "not-executable"
    plain.write_text("x")
    plain.chmod(0o644)
    assert _check({"command": str(plain)})["launcher"] == {"verdict": "missing"}


# ---------------------------------------------------------------------------
# It is a question, not an act
# ---------------------------------------------------------------------------


def test_a_check_stores_nothing_and_starts_nothing(monkeypatch):
    import unittest.mock as mock
    from core.database import McpServer

    Factory = _db()
    _NoSpawnManager.started = []
    with mock.patch("routes.mcp.mcp_routes.SessionLocal", Factory):
        _check({"command": "npx", "args": ["-y", "pkg"], "env": {"TOKEN": "secret"}})
    db = Factory()
    try:
        assert db.query(McpServer).count() == 0
    finally:
        db.close()
    assert _NoSpawnManager.started == []


@pytest.mark.parametrize("body,contains", [
    ({}, "command is required"),
    ({"command": "   "}, "command is required"),
    ({"command": 5}, "command is required"),
    (["npx"], "JSON object"),
    (ValueError("not json"), "must be JSON"),
])
def test_a_body_it_cannot_read_is_refused_with_a_sentence(body, contains):
    with pytest.raises(HTTPException) as caught:
        _check(body)
    assert caught.value.status_code == 400
    assert contains in str(caught.value.detail)


def test_a_non_admin_cannot_ask():
    """`require_admin`, as on every route in this file: whether a binary
    exists on the host is the host's business."""
    import unittest.mock as mock

    class _Stranger:
        headers = {}
        state = SimpleNamespace(current_user="bob")
        app = SimpleNamespace(state=SimpleNamespace(
            auth_manager=SimpleNamespace(is_configured=True, is_admin=lambda u: False)))

        async def json(self):
            return {"command": "npx"}

    with mock.patch("core.middleware.auth_disabled", return_value=False):
        with pytest.raises(HTTPException) as caught:
            asyncio.run(_endpoint("/api/mcp/check", "POST")(request=_Stranger()))
    assert caught.value.status_code == 403


# ---------------------------------------------------------------------------
# The premise, measured over the whole catalogue
# ---------------------------------------------------------------------------


def _catalogue():
    """The fifteen presets, read from the module the browser imports."""
    if not shutil.which("node"):
        pytest.skip("node binary not on PATH")
    script = (
        f"import('{PRESETS_JS.as_uri()}').then((m) => "
        "console.log(JSON.stringify(m.MCP_PRESETS.map((p) => m.presetFields(p)))));"
    )
    proc = subprocess.run(["node", "--input-type=module", "-e", script],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_every_preset_is_accepted_by_the_forms_own_route_and_refused_on_the_agent_path(monkeypatch):
    """Why the picker says what it says. With the person's values filled in,
    `POST /api/mcp/servers` stores every one of the fifteen; asked about the
    same registration, `manage_mcp`'s rule refuses every one of them."""
    import unittest.mock as mock
    from core.database import McpServer

    monkeypatch.delenv("PANTHEON_MCP_ALLOWED_COMMANDS", raising=False)
    presets = _catalogue()
    assert len(presets) == 15

    Factory = _db()
    add = _endpoint("/api/mcp/servers", "POST")
    for fields in presets:
        args = list(fields["args"])
        for index in fields["needs"]["args"]:
            args[int(index)] = "postgresql://me:secret@db.lan:5432/app"
        env = {k: (v or "a-value-the-person-typed") for k, v in fields["env"].items()}
        with mock.patch("routes.mcp.mcp_routes.SessionLocal", Factory):
            added = asyncio.run(add(
                request=_FakeRequest(), name=fields["name"], transport="stdio",
                command=fields["command"], args=json.dumps(args), env=json.dumps(env),
                url=None, oauth_file=None, oauth_config=None,
            ))
        assert added["name"] == fields["name"], fields["name"]

        verdict = _check({"command": fields["command"], "args": args, "env": env})
        assert verdict["assistant"]["verdict"] == "refused", fields["name"]

    db = Factory()
    try:
        assert db.query(McpServer).count() == 15
    finally:
        db.close()
