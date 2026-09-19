# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P8-37` — there was no timeout on the MCP call path at all.

MEASURED ON THE TREE BEFORE THE CHANGE. `McpManager._do_call` was one line:

    result = await session.call_tool(tool_name, arguments)

and the SDK's own read timeout defaults to `None` — `mcp/shared/session.py`
does `timeout = None` and then `anyio.fail_after(None)`, which is not a
deadline, it is a no-op scope. Driving the real `McpManager` from `HEAD` with a
session whose `call_tool` awaits `asyncio.sleep(3600)`, the coroutine was still
pending when an external 3-second bound gave up. There is no arrangement of
arguments that makes it return, because nothing in the path was watching a
clock.

That await is inside `execute_tool_block` (`src/tool_execution.py:1345/1360`)
and inside the scheduler's delivery path (`src/task_scheduler.py:2710/3588`),
so one hung tool hung the agent's turn and the scheduled task with it — with
nothing in the UI to explain it, because no exception was ever raised.

These tests DRIVE THE MANAGER (`Law 20`). None of them reads the source.
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.mcp_manager import (  # noqa: E402
    MCP_CALL_TIMEOUT_MAX_SECONDS,
    MCP_CALL_TIMEOUT_SECONDS,
    McpCallTimeout,
    McpManager,
    resolve_mcp_call_timeout,
)


class _Hangs:
    """A server that accepts the call and never answers.

    Deliberately does NOT accept `read_timeout_seconds`: this is the shape the
    SDK's own timer cannot help with (an older SDK, a wrapper, a session that
    stalls before the response wait), so it exercises the hard bound.
    """

    def __init__(self):
        self.calls = 0

    async def call_tool(self, name, args):
        self.calls += 1
        await asyncio.sleep(3600)


class _HangsLikeTheSdk:
    """A server that honours `read_timeout_seconds` the way the SDK does.

    On expiry the SDK raises `McpError(ErrorData(code=408, ...))` rather than
    cancelling the caller, which is what keeps the session usable afterwards.
    """

    def __init__(self):
        self.deadline_seen = None

    async def call_tool(self, name, args, read_timeout_seconds=None):
        self.deadline_seen = (
            read_timeout_seconds.total_seconds() if read_timeout_seconds else None
        )
        await asyncio.sleep(self.deadline_seen or 3600)
        raise _McpErrorLike()


class _McpErrorLike(Exception):
    """Shaped like `mcp.shared.exceptions.McpError` — `.error.code == 408`."""

    def __init__(self):
        super().__init__("Timed out while waiting for response to CallToolRequest.")
        self.error = type("ErrorData", (), {"code": 408, "message": "timeout"})()


class _Answers:
    """A well-behaved server, for the cases that must keep working."""

    def __init__(self, text="hello"):
        self.text = text
        self.calls = 0

    async def call_tool(self, name, args, read_timeout_seconds=None):
        self.calls += 1
        content = [type("C", (), {"text": self.text})()]
        return type("R", (), {"content": content, "isError": False})()


def _manager(session, server_id="abcd1234", builtin=False):
    mgr = McpManager()
    sid = "builtin_test" if builtin else server_id
    mgr._sessions[sid] = session
    mgr._connections[sid] = {"status": "connected", "name": "test"}
    return mgr, sid


# ---------------------------------------------------------------------------
# The defect
# ---------------------------------------------------------------------------


def test_a_server_that_never_answers_no_longer_hangs_the_caller():
    """The whole row. Before: pending forever. After: an answer, in time."""
    session = _Hangs()
    mgr, sid = _manager(session)

    async def go():
        started = time.monotonic()
        result = await mgr.call_tool(f"mcp__{sid}__hang", {}, timeout=1.0)
        return result, time.monotonic() - started

    result, elapsed = asyncio.run(go())
    assert result["exit_code"] == 1
    assert result["timed_out"] is True
    assert elapsed < 10, f"returned, but took {elapsed:.1f}s"
    assert session.calls == 1


def test_the_sdks_own_timeout_is_used_and_fires_first():
    """`Law 14`: the SDK already has this, so it is what gets the deadline.

    The graceful layer stops waiting on the response stream and raises 408; the
    hard bound is `deadline + grace` behind it and only exists for sessions the
    SDK's timer cannot reach. So an SDK-shaped session returns AT the deadline,
    not after the grace.
    """
    session = _HangsLikeTheSdk()
    mgr, sid = _manager(session)

    async def go():
        started = time.monotonic()
        result = await mgr.call_tool(f"mcp__{sid}__hang", {}, timeout=1.0)
        return result, time.monotonic() - started

    result, elapsed = asyncio.run(go())
    assert session.deadline_seen == 1.0, "the SDK was not given the deadline"
    assert result["timed_out"] is True
    assert elapsed < 1.9, f"the graceful layer did not fire first ({elapsed:.2f}s)"


def test_the_error_says_what_happened_and_for_how_long():
    """`Law 15`. A bare `TimeoutError` in a chat transcript explains nothing."""
    mgr, sid = _manager(_Hangs())
    result = asyncio.run(mgr.call_tool(f"mcp__{sid}__slow_thing", {}, timeout=0.5))
    assert "slow_thing" in result["error"]
    assert "0.5s" in result["error"]
    assert "hung" in result["error"] or "abandoned" in result["error"]


def test_a_timed_out_builtin_is_not_reconnected_and_retried():
    """A deadline is not a dead subprocess.

    `call_tool` tears down and relaunches a built-in whose process died, then
    retries once. Doing that for a hang spends a second full deadline learning
    the same thing — and on the agent-turn default that is four minutes of
    silence instead of two.
    """
    session = _Hangs()
    mgr, sid = _manager(session, builtin=True)
    reconnects = []

    async def _never(server_id):
        reconnects.append(server_id)
        return False

    mgr._reconnect_builtin = _never

    result = asyncio.run(mgr.call_tool(f"mcp__{sid}__hang", {}, timeout=0.5))
    assert result["timed_out"] is True
    assert reconnects == [], "a timeout must not take the crashed-server path"
    assert session.calls == 1, "the hung call was issued twice"


# ---------------------------------------------------------------------------
# The bound itself
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "requested,expected",
    [
        (None, MCP_CALL_TIMEOUT_SECONDS),
        (0, MCP_CALL_TIMEOUT_SECONDS),
        (-5, MCP_CALL_TIMEOUT_SECONDS),
        ("", MCP_CALL_TIMEOUT_SECONDS),
        ("not a number", MCP_CALL_TIMEOUT_SECONDS),
        (float("nan"), MCP_CALL_TIMEOUT_SECONDS),
        (10**9, MCP_CALL_TIMEOUT_MAX_SECONDS),
        ("30", 30.0),
        (2.5, 2.5),
    ],
)
def test_no_caller_can_spell_forever(requested, expected):
    """`0`, `-1`, `None` and a very large number all mean "bounded"."""
    assert resolve_mcp_call_timeout(requested) == expected


def test_the_default_applies_when_nobody_asks():
    """Every existing caller passes no timeout — `src/tool_execution.py:1345`
    and `:1360`, `src/task_scheduler.py:2710` and `:3588`. They are the paths
    the hang was on, so the default has to be what they get."""
    seen = {}

    class _Recording:
        async def call_tool(self, name, args, read_timeout_seconds=None):
            seen["deadline"] = read_timeout_seconds.total_seconds()
            return type("R", (), {"content": [], "isError": False})()

    mgr, sid = _manager(_Recording())
    asyncio.run(mgr.call_tool(f"mcp__{sid}__whatever", {}))
    assert seen["deadline"] == MCP_CALL_TIMEOUT_SECONDS


def test_do_call_raises_the_distinct_type():
    """The envelope is built in `call_tool`; the classification is below it."""
    mgr, _ = _manager(_Hangs())
    with pytest.raises(McpCallTimeout) as caught:
        asyncio.run(mgr._do_call(_Hangs(), "hang", {}, timeout=0.4))
    assert caught.value.timeout == 0.4
    assert caught.value.tool_name == "hang"


# ---------------------------------------------------------------------------
# `Law 1` — what must keep working
# ---------------------------------------------------------------------------


def test_a_normal_call_is_unchanged():
    session = _Answers("it worked")
    mgr, sid = _manager(session)
    result = asyncio.run(mgr.call_tool(f"mcp__{sid}__ping", {"a": 1}))
    assert result == {"stdout": "it worked", "stderr": "", "exit_code": 0}
    assert session.calls == 1


def test_a_tool_error_is_still_a_tool_error_not_a_timeout():
    class _Errors:
        async def call_tool(self, name, args, read_timeout_seconds=None):
            content = [type("C", (), {"text": "no such path"})()]
            return type("R", (), {"content": content, "isError": True})()

    mgr, sid = _manager(_Errors())
    result = asyncio.run(mgr.call_tool(f"mcp__{sid}__read", {}))
    assert result["exit_code"] == 1
    assert result["stderr"] == "no such path"
    assert result["untrusted_content"] is True
    assert "timed_out" not in result


def test_a_crashed_builtin_is_still_reconnected_and_retried():
    """The path a timeout now skips must still run for the case it is for."""

    class _Dies:
        def __init__(self):
            self.calls = 0

        async def call_tool(self, name, args, read_timeout_seconds=None):
            self.calls += 1
            if self.calls == 1:
                raise BrokenPipeError("subprocess gone")
            content = [type("C", (), {"text": "back"})()]
            return type("R", (), {"content": content, "isError": False})()

    session = _Dies()
    mgr, sid = _manager(session, builtin=True)

    async def _relaunch(server_id):
        return True

    mgr._reconnect_builtin = _relaunch
    result = asyncio.run(mgr.call_tool(f"mcp__{sid}__ping", {}))
    assert result["stdout"] == "back"
    assert session.calls == 2


def test_an_unconnected_server_still_answers_immediately():
    mgr = McpManager()
    result = asyncio.run(mgr.call_tool("mcp__nope__x", {}))
    assert result["exit_code"] == 1
    assert "not connected" in result["error"]
