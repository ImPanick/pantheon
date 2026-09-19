# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P8-36` — the route that calls one MCP tool, and `P8-37` reaching it.

MEASURED ON THE TREE BEFORE THE CHANGE. `setup_mcp_routes` registered eleven
routes and **not one of them invoked a tool.** The MCP surface could add a
server, reconnect it, enable it, disable it, delete it, and list what it
offered — and there was no way to find out whether any of it worked short of
opening a chat and hoping the model picked the tool. `McpManager.call_tool` was
already public with a normalised `{stdout, stderr, exit_code}` envelope, so the
missing piece really was the door.

The route is the FIRST thing that would have hung, which is why `P8-37` lands
in the same change: a person pressing a button and getting nothing back forever
is the worst shape this defect has.

These tests DRIVE THE ENDPOINT (`Law 20`). None of them reads the source.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class _FakeRequest:
    """Enough of a request for `require_admin` plus a JSON body.

    Uses the documented in-process loopback header so the test does not depend
    on whether auth happens to be configured where it runs. The admin gate is
    `FORBIDDEN.md` Part 2 and is pinned elsewhere; this file is about what the
    route does after it lets you in.
    """

    def __init__(self, body=None, raw=False):
        from core.middleware import INTERNAL_TOOL_HEADER, INTERNAL_TOOL_TOKEN

        self.headers = {INTERNAL_TOOL_HEADER: INTERNAL_TOOL_TOKEN}
        self.state = SimpleNamespace(current_user="admin")
        self.app = SimpleNamespace(state=SimpleNamespace(auth_manager=None))
        self._body = body
        self._raw = raw

    async def json(self):
        if self._raw:
            raise ValueError("not json")
        return self._body


class _Manager:
    """An `McpManager` stand-in that records what the route asked it to do."""

    def __init__(self, status="connected", tools=("echo", "wipe_everything")):
        self._status = status
        self._tools = list(tools)
        self.calls = []
        self.result = {"stdout": "pong", "stderr": "", "exit_code": 0}

    def get_server_status(self, server_id):
        out = {"status": self._status, "name": "Test server", "tool_count": len(self._tools)}
        if self._status == "error":
            out["error"] = "npx: command not found"
        return out

    def get_all_tools(self, disabled_map=None):
        return [
            {"server_id": "abcd1234", "server_name": "Test server", "name": n,
             "qualified_name": f"mcp__abcd1234__{n}", "description": "", "input_schema": {},
             "is_disabled": False}
            for n in self._tools
        ] + [
            {"server_id": "other999", "server_name": "Someone else", "name": "not_mine",
             "qualified_name": "mcp__other999__not_mine", "description": "", "input_schema": {},
             "is_disabled": False}
        ]

    async def call_tool(self, qualified_name, arguments, timeout=None):
        self.calls.append((qualified_name, arguments, timeout))
        return dict(self.result)


def _db(rows=((("abcd1234", "Test server"), None),)):
    """An in-memory DB holding the given MCP server rows."""
    from core.database import Base, McpServer
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Factory = sessionmaker(bind=engine)
    db = Factory()
    try:
        for (sid, name), disabled in rows:
            db.add(McpServer(id=sid, name=name, transport="stdio", command="npx",
                             args="[]", env="{}", is_enabled=True,
                             disabled_tools=disabled))
        db.commit()
    finally:
        db.close()
    return Factory


def _endpoint(manager, path, method):
    from routes.mcp.mcp_routes import setup_mcp_routes

    for route in setup_mcp_routes(manager).routes:
        if route.path == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"{method} {path} not found")


def _call(body, manager=None, factory=None, server_id="abcd1234", raw=False):
    import unittest.mock as mock

    manager = manager or _Manager()
    factory = factory or _db()
    endpoint = _endpoint(manager, "/api/mcp/servers/{server_id}/call", "POST")
    with mock.patch("routes.mcp.mcp_routes.SessionLocal", factory):
        out = asyncio.run(endpoint(server_id=server_id, request=_FakeRequest(body, raw=raw)))
    out["_manager"] = manager
    return out


# ---------------------------------------------------------------------------
# It calls the tool
# ---------------------------------------------------------------------------


def test_the_route_actually_invokes_the_tool():
    out = _call({"tool": "echo", "arguments": {"say": "pong"}})
    mgr = out["_manager"]
    assert mgr.calls, "no tool was called"
    qualified, args, _timeout = mgr.calls[0]
    assert qualified == "mcp__abcd1234__echo"
    assert args == {"say": "pong"}
    assert out["ok"] is True
    assert out["stdout"] == "pong"
    assert out["exit_code"] == 0
    assert isinstance(out["duration_ms"], int)


def test_it_goes_through_the_same_manager_method_the_agent_uses():
    """`Law 14`. One call path, so a tool that works here works in a turn."""
    from src.mcp_manager import McpManager

    assert hasattr(McpManager, "call_tool")
    out = _call({"tool": "echo"})
    assert out["_manager"].calls[0][0].startswith("mcp__")


def test_arguments_default_to_empty():
    out = _call({"tool": "echo"})
    assert out["_manager"].calls[0][1] == {}


def test_a_tool_failure_comes_back_as_a_failure_not_an_exception():
    mgr = _Manager()
    mgr.result = {"stdout": "", "stderr": "ENOENT", "exit_code": 1, "untrusted_content": True}
    out = _call({"tool": "echo"}, manager=mgr)
    assert out["ok"] is False
    assert out["stderr"] == "ENOENT"
    assert out["timed_out"] is False


# ---------------------------------------------------------------------------
# `P8-37` reaching the route
# ---------------------------------------------------------------------------


def test_the_call_carries_a_deadline():
    """The interactive default: a person is waiting on this one."""
    out = _call({"tool": "echo"})
    _q, _a, timeout = out["_manager"].calls[0]
    assert timeout == 30.0
    assert out["timeout"] == 30.0


@pytest.mark.parametrize("asked", [0, -1, None, "", "forever", 10**9])
def test_no_body_can_ask_for_no_deadline(asked):
    """The clamp lives in `src/mcp_manager.py`; the route does not reimplement it."""
    from src.mcp_manager import MCP_CALL_TIMEOUT_MAX_SECONDS

    out = _call({"tool": "echo", "timeout": asked})
    _q, _a, timeout = out["_manager"].calls[0]
    assert timeout is not None
    assert 0 < timeout <= MCP_CALL_TIMEOUT_MAX_SECONDS


def test_a_shorter_deadline_is_honoured():
    out = _call({"tool": "echo", "timeout": 3})
    assert out["_manager"].calls[0][2] == 3.0


def test_a_timeout_is_reported_as_one():
    mgr = _Manager()
    mgr.result = {"error": "MCP tool 'echo' did not answer within 3s and was abandoned.",
                  "exit_code": 1, "timed_out": True}
    out = _call({"tool": "echo", "timeout": 3}, manager=mgr)
    assert out["timed_out"] is True
    assert out["ok"] is False
    assert "3s" in out["error"]


# ---------------------------------------------------------------------------
# `Law 15` — every refusal says which of the three things is wrong
# ---------------------------------------------------------------------------


def test_an_unknown_server_is_404():
    with pytest.raises(HTTPException) as caught:
        _call({"tool": "echo"}, server_id="nosuch")
    assert caught.value.status_code == 404
    assert "Server not found" in caught.value.detail


def test_a_server_that_is_not_connected_is_409_and_says_so():
    """Not a tool error. The server was never up."""
    with pytest.raises(HTTPException) as caught:
        _call({"tool": "echo"}, manager=_Manager(status="error"))
    assert caught.value.status_code == 409
    assert "error" in caught.value.detail
    assert "npx: command not found" in caught.value.detail


def test_an_unknown_tool_is_404_and_lists_what_there_is():
    with pytest.raises(HTTPException) as caught:
        _call({"tool": "ecoh"})
    assert caught.value.status_code == 404
    assert "ecoh" in caught.value.detail
    assert "echo" in caught.value.detail


def test_another_servers_tool_is_not_callable_through_this_server():
    with pytest.raises(HTTPException) as caught:
        _call({"tool": "not_mine"})
    assert caught.value.status_code == 404


@pytest.mark.parametrize("body", [{}, {"tool": ""}, {"tool": "   "}, {"tool": 7}, {"tool": None}])
def test_a_missing_tool_name_is_400(body):
    with pytest.raises(HTTPException) as caught:
        _call(body)
    assert caught.value.status_code == 400
    assert "tool" in caught.value.detail


def test_a_non_object_body_is_400_with_the_shape_that_works():
    with pytest.raises(HTTPException) as caught:
        _call(["echo"])
    assert caught.value.status_code == 400
    assert '"tool"' in caught.value.detail


def test_an_unparseable_body_is_400_with_the_shape_that_works():
    with pytest.raises(HTTPException) as caught:
        _call(None, raw=True)
    assert caught.value.status_code == 400
    assert '"tool"' in caught.value.detail


def test_non_object_arguments_are_400():
    with pytest.raises(HTTPException) as caught:
        _call({"tool": "echo", "arguments": ["path"]})
    assert caught.value.status_code == 400
    assert "arguments" in caught.value.detail


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


def test_a_non_admin_cannot_reach_it():
    """`require_admin`, the control `FORBIDDEN.md` Part 2 pins — not a second gate."""
    import unittest.mock as mock

    mgr = _Manager()
    endpoint = _endpoint(mgr, "/api/mcp/servers/{server_id}/call", "POST")

    class _Stranger:
        headers = {}
        state = SimpleNamespace(current_user="bob")
        app = SimpleNamespace(state=SimpleNamespace(
            auth_manager=SimpleNamespace(is_configured=True, is_admin=lambda u: False)))

        async def json(self):
            return {"tool": "echo"}

    with mock.patch("routes.mcp.mcp_routes.SessionLocal", _db()), \
            mock.patch("core.middleware.auth_disabled", return_value=False):
        with pytest.raises(HTTPException) as caught:
            asyncio.run(endpoint(server_id="abcd1234", request=_Stranger()))
    assert caught.value.status_code == 403
    assert mgr.calls == [], "the tool ran before the gate"


# ---------------------------------------------------------------------------
# A tool hidden from the agent
# ---------------------------------------------------------------------------


def test_a_tool_disabled_for_the_agent_is_still_testable_and_says_so():
    """The disabled list hides tools from the model. It is not a lock on the
    operator's own server — but a working test on a tool the agent will never
    choose is a confusing result, so the answer carries the reason."""
    factory = _db(rows=((("abcd1234", "Test server"), '["echo"]'),))
    out = _call({"tool": "echo"}, factory=factory)
    assert out["ok"] is True
    assert out["tool_is_disabled"] is True


def test_an_enabled_tool_is_not_flagged():
    out = _call({"tool": "echo"})
    assert out["tool_is_disabled"] is False
