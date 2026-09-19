# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B865` and `P8-44` — the two things nobody checked before spawning.

MEASURED ON THE TREE BEFORE THE CHANGE, by driving the route and the manager.

`B865`. `_parsed_json_field` (`routes/mcp/mcp_routes.py:206-216` at `HEAD`)
asserted the CONTAINER type and nothing about what was in it, so
`env={"PORT": 3000}` was stored and the connect then failed with

    1 validation error for StdioServerParameters
    env.PORT
      Input should be a valid string [type=string_type, input_value=3000, ...]
      For further information visit https://errors.pydantic.dev/2.11/v/string_type

— a library's internal message, naming a class the operator has never heard
of, ending in a link to that library's documentation, and presented as *this
server's connection error*. It arrived after the row was saved, so the form
appeared to have worked.

`P8-44`. `qualified_name.split("__", 2)` in `call_tool` was the sole parse of
`mcp__<server>__<tool>` and nothing held the invariant that makes it correct.
A server id containing `__` does not fail, it MISROUTES: id `a__b` + tool `t`
qualifies to exactly the same string as id `a` + tool `b__t`, and the call
lands in whichever session `a` is. Unreachable while ids are `uuid4[:8]`,
which is why it is worth pinning now rather than after `P8-47` lets people
name their servers.

Driven, never grepped (`Law 20`).
"""
from __future__ import annotations

import asyncio
import json
import sys
import unittest.mock as mock
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.mcp_manager import (  # noqa: E402
    McpManager,
    qualify_mcp_tool_name,
    split_mcp_tool_name,
    validate_mcp_server_id,
)


class _FakeRequest:
    def __init__(self):
        from core.middleware import INTERNAL_TOOL_HEADER, INTERNAL_TOOL_TOKEN

        self.headers = {INTERNAL_TOOL_HEADER: INTERNAL_TOOL_TOKEN}
        self.state = SimpleNamespace(current_user="admin")
        self.app = SimpleNamespace(state=SimpleNamespace(auth_manager=None))


class _RecordingManager:
    """Records what it was asked to launch, and never launches it."""

    def __init__(self):
        self.calls = []

    async def connect_server(self, **kwargs):
        self.calls.append(kwargs)
        return False

    def get_server_status(self, server_id):
        return {"status": "disconnected", "tool_count": 0, "error": None}


def _endpoint(manager):
    from routes.mcp.mcp_routes import setup_mcp_routes

    router = setup_mcp_routes(manager)
    for route in router.routes:
        if route.path == "/api/mcp/servers" and "POST" in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError("add_server route not found")


def _post(**kwargs):
    """POST /api/mcp/servers against a throwaway DB. Returns (result, rows, mgr)."""
    from core.database import Base, McpServer
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine("sqlite:///:memory:",
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Factory = sessionmaker(bind=engine)

    fields = {"name": "srv", "transport": "stdio", "command": "npx", "args": "[]",
              "env": "{}", "url": "", "oauth_file": "", "oauth_config": ""}
    fields.update(kwargs)
    manager = _RecordingManager()
    endpoint = _endpoint(manager)
    error = None
    result = None
    with mock.patch("routes.mcp.mcp_routes.SessionLocal", Factory):
        try:
            result = asyncio.run(endpoint(request=_FakeRequest(), **fields))
        except HTTPException as exc:
            error = exc
        rows = Factory().query(McpServer).all()
    return SimpleNamespace(result=result, error=error, rows=rows, manager=manager)


# --------------------------------------------------------------------------
# `B865` — the entry types
# --------------------------------------------------------------------------


@pytest.mark.parametrize("field,raw,needle", [
    ("env", '{"PORT": 3000}', 'env["PORT"]'),
    ("env", '{"DEBUG": true}', 'env["DEBUG"]'),
    ("env", '{"TOKEN": null}', 'env["TOKEN"]'),
    ("env", '{"NESTED": {"a": 1}}', 'env["NESTED"]'),
    ("args", '["-y", 3000]', "args[1]"),
    ("args", '["-y", ["nested"]]', "args[1]"),
])
def test_a_non_string_entry_is_refused_by_name_before_anything_is_stored(field, raw, needle):
    out = _post(**{field: raw})

    assert out.error is not None, "the row was accepted"
    assert out.error.status_code == 400
    assert needle in out.error.detail, out.error.detail
    assert "must be a string" in out.error.detail
    # The sentence tells them what would have worked.
    assert "quote it" in out.error.detail
    # Nothing stored, nothing spawned — the two things that used to happen.
    assert out.rows == []
    assert out.manager.calls == []


def test_no_pydantic_message_reaches_the_operator():
    """The row's second `Verify:` clause, stated as the absence it is about."""
    out = _post(env='{"PORT": 3000}')
    detail = out.error.detail

    for leak in ("pydantic", "StdioServerParameters", "validation error",
                 "type=string_type", "https://errors."):
        assert leak not in detail, f"{leak!r} leaked into an operator-facing message"


def test_a_good_value_is_still_accepted():
    """The guard must not be a wall. Strings of every awkward shape go through."""
    out = _post(env='{"API_KEY": "sk-1", "EMPTY": "", "N": "3000"}',
                args='["-y", "@scope/pkg@1.2.3", "--flag=value"]')

    assert out.error is None
    assert len(out.rows) == 1
    assert json.loads(out.rows[0].env)["N"] == "3000"
    assert out.manager.calls[0]["args"] == ["-y", "@scope/pkg@1.2.3", "--flag=value"]


@pytest.fixture()
def no_spawn(monkeypatch):
    """Fail loudly if anything reaches the transport.

    Both invariants below are supposed to refuse *before* a subprocess exists.
    Without this the pre-fix behaviour is an `npx` download rather than a
    failing assertion, which is a slow way to learn the same thing.
    """
    spawned = []

    def _never(*args, **kwargs):
        spawned.append(args)
        raise AssertionError("a transport was opened for a server that must be refused")

    monkeypatch.setattr("mcp.client.stdio.stdio_client", _never, raising=True)
    monkeypatch.setattr("mcp.client.sse.sse_client", _never, raising=True)
    return spawned


def test_the_manager_refuses_it_too_so_a_stored_row_cannot_traceback(no_spawn):
    """The route is the door; `connect_server` is the invariant.

    A row that got in before this landed — or through any client that does not
    go through the route — still gets a sentence rather than a pydantic dump,
    and never reaches the spawn.
    """
    manager = McpManager()
    ok = asyncio.run(manager.connect_server(
        server_id="legacy", name="Legacy", transport="stdio",
        command="npx", args=["-y", "pkg"], env={"PORT": 3000},
    ))

    assert ok is False
    assert no_spawn == []
    status = manager.get_server_status("legacy")
    assert status["status"] == "error"
    assert 'env["PORT"] must be a string' in status["error"]
    assert "pydantic" not in status["error"]


def test_the_agent_path_refuses_the_same_value_with_the_same_sentence(monkeypatch):
    """`manage_mcp add` is a third client and checked env entries not at all.

    The command allowlist is empty by default and runs first, so an allowlisted
    binary is the only way to reach the field checks at all — which is the
    right order and is asserted below rather than worked around.
    """
    from src.agent_tools.admin_tools import _validate_mcp_command

    # Security first: with nothing allowlisted, nothing gets as far as env.
    assert "not in the MCP allowlist" in _validate_mcp_command(
        "my-mcp-server", [], {"API_KEY": "x"})
    monkeypatch.setenv("PANTHEON_MCP_ALLOWED_COMMANDS", "my-mcp-server")

    assert 'env["PORT"] must be a string' in _validate_mcp_command(
        "my-mcp-server", [], {"PORT": 3000})
    assert "args[1] must be a string" in _validate_mcp_command(
        "my-mcp-server", ["-y", 3000], {})
    assert _validate_mcp_command("my-mcp-server", ["-y", "pkg"], {"API_KEY": "x"}) is None

    # `FORBIDDEN.md` Part 2: every control this function already had still
    # fires, and none of them was relaxed to make room for the new rule.
    assert _validate_mcp_command("python", ["x"], {}) is not None
    assert _validate_mcp_command("my-mcp-server", ["-e", "code"], {}) is not None
    assert _validate_mcp_command("my-mcp-server", ["--eval=x"], {}) is not None
    assert _validate_mcp_command("my-mcp-server", ["http://x/y"], {}) is not None
    assert _validate_mcp_command("my-mcp-server", ["a;b"], {}) is not None
    assert _validate_mcp_command("/bin/my-mcp-server", [], {}) is not None
    assert _validate_mcp_command("my-mcp-server", [], {"LD_PRELOAD": "/x.so"}) is not None


# --------------------------------------------------------------------------
# `P8-44` — the server id
# --------------------------------------------------------------------------


def test_two_different_servers_can_qualify_to_one_name():
    """The collision itself, shown rather than asserted about.

    This is why the id needs a rule: the namespaced name is ambiguous the
    moment an id may contain the separator, and the parse cannot recover it.
    """
    collide = qualify_mcp_tool_name("a__b", "t")
    assert collide == qualify_mcp_tool_name("a", "b__t") == "mcp__a__b__t"
    # And the sole parse resolves it to the *other* server, every time.
    assert split_mcp_tool_name(collide) == ("a", "b__t")


def test_an_id_that_would_misroute_is_refused_at_registration(no_spawn):
    manager = McpManager()
    ok = asyncio.run(manager.connect_server(
        server_id="a__b", name="Ambiguous", transport="stdio", command="npx",
    ))

    assert ok is False
    assert no_spawn == []
    error = manager.get_server_status("a__b")["error"]
    assert "'__'" in error
    assert "mcp__<server>__<tool>" in error
    assert "single underscore" in error
    assert manager._sessions == {}


@pytest.mark.parametrize("bad", [
    "a__b", "__lead", "trail__", "", "   ", " pad ", "-starts-with-dash",
    "has space", "has/slash", "x" * 65,
])
def test_the_rule_names_what_is_wrong(bad):
    assert validate_mcp_server_id(bad) is not None


@pytest.mark.parametrize("good", [
    "a1b2c3d4", "builtin_browser", "image_gen", "rag", "email",
    "my.server-1", "A_B", "0",
])
def test_every_id_the_product_actually_mints_is_accepted(good):
    """Including the four built-ins and the `uuid4[:8]` shape, so this rule
    cannot quietly break a live install."""
    assert validate_mcp_server_id(good) is None


def test_uuid_ids_keep_passing():
    import uuid

    for _ in range(200):
        assert validate_mcp_server_id(str(uuid.uuid4())[:8]) is None


@pytest.mark.parametrize("bad", [
    "read_file", "mcp__srv", "mcp__srv__", "mcp____tool", "notmcp__srv__tool",
    "", None, 5,
])
def test_a_name_that_is_not_a_qualified_mcp_name_is_refused_not_guessed(bad):
    assert split_mcp_tool_name(bad) is None
    if isinstance(bad, str):
        result = asyncio.run(McpManager().call_tool(bad, {}))
        assert "Invalid MCP tool name" in result["error"]


def test_a_tool_name_containing_the_separator_still_works():
    """`maxsplit=2` is load-bearing in the other direction: the SERVER may not
    hold the separator, the TOOL still may, and a third-party server is free to
    name a tool `files__read`."""
    assert split_mcp_tool_name("mcp__srv__files__read") == ("srv", "files__read")
