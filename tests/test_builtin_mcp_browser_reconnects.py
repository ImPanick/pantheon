# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P8-43` — the built-in that could not be restarted.

MEASURED ON THE TREE BEFORE THE CHANGE.

`McpManager.call_tool` catches a failed call, asks `is_builtin(server_id)`, and
on True hands the server to `_reconnect_builtin` and retries once. `is_builtin`
says True for anything starting `builtin_` (`src/mcp_manager.py:812-830` at
`HEAD`), so `builtin_browser` takes that branch. `_reconnect_builtin` then
opened with

    if server_id not in _BUILTIN_SERVERS:
        return False

and `_BUILTIN_SERVERS` is the **Python-script** map — `image_gen`, `rag`,
`email`. Three entries, not the four the row claimed; `memory` was removed by
`B67` and the count was never re-measured. The browser lives in a different map
(`_BUILTIN_NPX_SERVERS`), so a crashed Playwright subprocess answered every
later call with *"MCP server crashed and reconnect failed: builtin_browser"*
and stayed dead until somebody opened Settings and pressed Reconnect.

The cause was that "how does this built-in start" had two answers and only one
of them was a function: boot built the browser's launch line inline inside
`register_builtin_servers`, and the restart path could not see it.
`builtin_connect_spec` is now the single answer and both callers ask it.

Driven, never grepped (`Law 20`).
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.builtin_mcp import _BUILTIN_SERVERS, builtin_connect_spec  # noqa: E402
from src.mcp_manager import McpManager  # noqa: E402


class _Recorder(McpManager):
    """A manager whose connect succeeds without spawning anything."""

    def __init__(self, succeed=True):
        super().__init__()
        self.connects = []
        self._succeed = succeed

    async def connect_server(self, **kwargs):
        self.connects.append(kwargs)
        if self._succeed:
            self._sessions[kwargs["server_id"]] = _Healthy()
        return self._succeed


class _Healthy:
    async def call_tool(self, name, arguments, **kw):
        class _R:
            content = [type("T", (), {"text": "navigated"})()]
            isError = False
        return _R()


class _Crashed:
    def __init__(self):
        self.calls = 0

    async def call_tool(self, name, arguments, **kw):
        self.calls += 1
        raise BrokenPipeError("server subprocess is gone")


def test_the_browser_is_a_builtin_the_old_map_did_not_hold():
    """The gap itself: the test `_reconnect_builtin` used to run said no."""
    manager = McpManager()
    assert manager.is_builtin("builtin_browser") is True
    assert "builtin_browser" not in _BUILTIN_SERVERS
    assert len(_BUILTIN_SERVERS) == 3, sorted(_BUILTIN_SERVERS)


def test_a_crashed_browser_reconnects_and_the_call_is_retried():
    """The row's whole point, driven through the public entry point."""
    manager = _Recorder()
    manager._tools["builtin_browser"] = [{"name": "browser_navigate",
                                          "description": "", "input_schema": {},
                                          "annotations": None}]
    crashed = _Crashed()
    manager._sessions["builtin_browser"] = crashed

    result = asyncio.run(manager.call_tool(
        "mcp__builtin_browser__browser_navigate", {"url": "https://example.com"}))

    assert crashed.calls == 1
    assert len(manager.connects) == 1, "reconnect was never attempted"
    assert result["exit_code"] == 0
    assert result["stdout"] == "navigated"


def test_the_restart_uses_the_same_launch_line_as_the_start():
    """`Law 14`, pinned by behaviour rather than by a comment.

    A change to how the browser starts — its flags, its cache directory, the
    npx binary — now reaches the restart too, because both read one spec.
    """
    manager = _Recorder()
    assert asyncio.run(manager._reconnect_builtin("builtin_browser")) is True
    got = manager.connects[0]
    spec = builtin_connect_spec("builtin_browser")

    assert got["command"] == spec["command"]
    assert got["args"] == spec["args"]
    assert got["env"] == spec["env"]
    assert got["name"] == spec["name"] == "Built-in: Browser"
    assert got["transport"] == "stdio"
    # The two browser-specific things the old path could not have known.
    assert "@playwright/mcp@latest" in got["args"]
    assert set(got["env"]) == {"XDG_CACHE_HOME", "PLAYWRIGHT_BROWSERS_PATH"}


def test_boot_and_restart_agree_because_they_ask_the_same_function(monkeypatch):
    """Drive the real boot path and compare its connect call with the restart's."""
    import src.builtin_mcp as builtin_mcp

    monkeypatch.setattr(builtin_mcp, "BROWSER_MCP_REQUIRE_CACHE", False)

    real_sleep = asyncio.sleep
    async def _no_wait(seconds, *a, **k):
        return await real_sleep(0)
    monkeypatch.setattr(builtin_mcp.asyncio, "sleep", _no_wait)

    async def drive():
        booted = _Recorder()
        await builtin_mcp.register_builtin_servers(booted)
        pending = [t for t in builtin_mcp._BG_TASKS if not t.done()]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        restarted = _Recorder()
        await restarted._reconnect_builtin("builtin_browser")
        return booted, restarted

    booted, restarted = asyncio.run(drive())
    boot_call = [c for c in booted.connects if c["server_id"] == "builtin_browser"]
    assert boot_call, "the browser never started at boot"
    assert boot_call[0] == restarted.connects[0]


@pytest.mark.parametrize("server_id", sorted(_BUILTIN_SERVERS))
def test_the_python_builtins_still_reconnect(server_id):
    """The three that always worked must keep working."""
    manager = _Recorder()
    assert asyncio.run(manager._reconnect_builtin(server_id)) is True
    got = manager.connects[0]

    assert got["server_id"] == server_id
    assert got["command"] == sys.executable
    assert got["args"][0].endswith(".py")
    assert os.path.exists(got["args"][0])
    assert "PYTHONPATH" in got["env"]


def test_a_stranger_is_still_refused():
    """A server the operator registered is not ours to relaunch from a map."""
    manager = _Recorder()
    assert asyncio.run(manager._reconnect_builtin("a1b2c3d4")) is False
    assert manager.connects == []
    assert builtin_connect_spec("a1b2c3d4") is None


def test_a_missing_script_refuses_rather_than_spawning_nothing(monkeypatch):
    """Boot skips a built-in whose script is gone; so does the restart now."""
    import src.builtin_mcp as builtin_mcp

    monkeypatch.setitem(builtin_mcp._BUILTIN_SERVERS, "rag",
                        ("mcp_servers/does_not_exist.py", "Built-in: RAG"))
    manager = _Recorder()
    assert asyncio.run(manager._reconnect_builtin("rag")) is False
    assert manager.connects == []


def test_a_reconnect_that_fails_is_reported_as_a_failure():
    manager = _Recorder(succeed=False)
    manager._tools["builtin_browser"] = [{"name": "browser_navigate",
                                          "description": "", "input_schema": {},
                                          "annotations": None}]
    manager._sessions["builtin_browser"] = _Crashed()

    result = asyncio.run(manager.call_tool("mcp__builtin_browser__browser_navigate", {}))
    assert result["exit_code"] == 1
    assert "reconnect failed" in result["error"]
