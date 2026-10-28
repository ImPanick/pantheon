# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B880` — the stack is entered and exited by one task, so shutdown is silent.

MEASURED ON THE TREE BEFORE THE CHANGE by driving a REAL stdio MCP server
subprocess, not a stub: anyio's cancel scopes are the thing under test and a
fake transport does not have one.

    connect_all_enabled()  (connects inside asyncio.create_task children)
    disconnect_all()       (closes from the parent)
      → WARNING Error closing MCP server s1: Attempted to exit cancel scope in
        a different task than it was entered in

and instrumenting the two callbacks on that `AsyncExitStack` showed BOTH of
them raising rather than completing:

    same task   ['enter#1:ClientSession', 'done#1:ClientSession',
                 'enter#0:_AsyncGeneratorContextManager', 'done#0:...']
    child task  ['enter#1:ClientSession', 'raise#1:RuntimeError',
                 'enter#0:_AsyncGeneratorContextManager', 'raise#0:RuntimeError']

so `stdio_client`'s ordered terminate → wait → kill teardown never finished.
The subprocess still died (1 process while connected, 0 after), which is why
this was a warning rather than a leak — and the warning fired on EVERY
shutdown, which is how a real one gets missed.

A worse shape of the same defect was found while fixing it and is pinned below:
when the stack was entered in a task that is still RUNNING and closed from a
child task — a connection opened during startup and deleted from a request —
anyio delivered the cancel scope's cancellation to the entering task, and the
caller died with `CancelledError: Cancelled via cancel scope ...`. That is the
lifespan task in `app.py`.

`asyncio.timeout` in place of `asyncio.wait_for`, the fix `P8-47` used for
`src/mcp_scaffold.py`'s single inline probe, was measured here and did NOT fix
it: child task + `asyncio.timeout` logged the same warning. `create_task` is
the task that matters, so the stack had to be owned. See `McpManager._open_owned`.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

pytest.importorskip("mcp")

import src.mcp_manager as mcp_manager  # noqa: E402
from src.mcp_manager import McpManager  # noqa: E402

# `B621`: written against mcp 2.x's low-level server, which takes its handlers
# in the constructor — 1.x's `@app.list_tools()` decorator is gone.
SERVER_SOURCE = '''\
import asyncio
from mcp.server import Server
from mcp.server.stdio import stdio_server
import mcp.types as types


async def list_tools(ctx, params):
    return types.ListToolsResult(
        tools=[types.Tool(name="echo", description="echo", inputSchema={"type": "object"})])


app = Server("probe", on_list_tools=list_tools)


async def main():
    async with stdio_server() as (r, w):
        await app.run(r, w, app.create_initialization_options())


asyncio.run(main())
'''


@pytest.fixture(scope="module")
def server_path(tmp_path_factory):
    path = tmp_path_factory.mktemp("b880") / "probe_server.py"
    path.write_text(SERVER_SOURCE)
    return str(path)


class _Captured(logging.Handler):
    def __init__(self):
        super().__init__()
        self.rows: list[tuple[str, str]] = []

    def emit(self, record):  # pragma: no cover - trivial
        self.rows.append((record.levelname, record.getMessage()))

    @property
    def loud(self):
        return [m for lvl, m in self.rows if lvl in ("WARNING", "ERROR", "CRITICAL")]


@pytest.fixture()
def captured():
    handler = _Captured()
    mcp_manager.logger.addHandler(handler)
    previous = mcp_manager.logger.level
    mcp_manager.logger.setLevel(logging.DEBUG)
    try:
        yield handler
    finally:
        mcp_manager.logger.removeHandler(handler)
        mcp_manager.logger.setLevel(previous)


class _Row:
    """One enabled `McpServer` row, as `connect_all_enabled` reads it."""

    def __init__(self, sid, path):
        self.id = self.name = sid
        self.transport = "stdio"
        self.command = sys.executable
        self.args = json.dumps([path])
        self.env = json.dumps({})
        self.url = None
        self.is_enabled = True


class _Db:
    def __init__(self, rows):
        self.rows = rows

    def query(self, *a, **k):
        return self

    def filter(self, *a, **k):
        return self

    def all(self):
        return self.rows

    def close(self):
        pass


def _connect_inline(manager, sid, path):
    return manager.connect_server(
        server_id=sid, name=sid, transport="stdio",
        command=sys.executable, args=[path], env={},
    )


def _instrument(stack, trace):
    """Wrap each exit callback so the teardown records what really happened."""
    wrapped = []
    for i, (is_sync, cb) in enumerate(list(stack._exit_callbacks)):
        label = getattr(getattr(cb, "__self__", None), "__class__", type(cb)).__name__

        def make(cb=cb, i=i, label=label):
            async def run(*a, **k):
                try:
                    result = await cb(*a, **k)
                except BaseException as exc:
                    trace.append(f"raise#{i}:{type(exc).__name__}")
                    raise
                trace.append(f"done#{i}:{label}")
                return result

            return run

        wrapped.append((is_sync, make()))
    stack._exit_callbacks.clear()
    stack._exit_callbacks.extend(wrapped)


# ---------------------------------------------------------------------------
# The defect itself
# ---------------------------------------------------------------------------


def test_startup_connect_then_parent_shutdown_logs_nothing(server_path, captured, monkeypatch):
    """`connect_all_enabled` in child tasks, `disconnect_all` in the parent."""
    monkeypatch.setattr(mcp_manager, "SessionLocal", lambda: _Db([_Row("s1", server_path)]))
    manager = McpManager()

    async def scenario():
        await manager.connect_all_enabled()
        assert manager.get_server_status("s1")["status"] == "connected"
        await manager.disconnect_all()

    asyncio.run(scenario())

    assert captured.loud == [], captured.loud
    assert manager._sessions == {} and manager._owners == {}


def test_every_cleanup_on_the_stack_runs_to_completion(server_path, captured, monkeypatch):
    """Both stack callbacks used to raise RuntimeError. They complete now."""
    monkeypatch.setattr(mcp_manager, "SessionLocal", lambda: _Db([_Row("s1", server_path)]))
    manager = McpManager()
    trace: list[str] = []

    async def scenario():
        await manager.connect_all_enabled()
        _instrument(manager._stacks["s1"], trace)
        await manager.disconnect_all()

    asyncio.run(scenario())

    assert len(trace) == 2, trace
    assert all(step.startswith("done#") for step in trace), trace
    assert captured.loud == []


def test_closing_from_another_task_does_not_cancel_the_caller(server_path, captured):
    """The worse shape: startup connects, a request deletes, lifespan dies."""
    manager = McpManager()

    async def scenario():
        # Entered in THIS task, which stays alive — the lifespan task.
        await _connect_inline(manager, "s1", server_path)
        # Closed from a request task.
        await asyncio.create_task(manager.disconnect_server("s1"))
        # Reached only if the cancel scope did not cancel us on the way out.
        await asyncio.sleep(0)
        return "survived"

    assert asyncio.run(scenario()) == "survived"
    assert captured.loud == []


@pytest.mark.parametrize("connect_in_task,disconnect_in_task", [
    (False, False), (True, False), (False, True), (True, True),
])
def test_no_pairing_of_tasks_makes_a_noisy_close(server_path, captured,
                                                 connect_in_task, disconnect_in_task):
    """All four task pairings. Three of them warned before this row."""
    manager = McpManager()

    async def scenario():
        opener = _connect_inline(manager, "s1", server_path)
        await (asyncio.create_task(opener) if connect_in_task else opener)
        closer = manager.disconnect_server("s1")
        await (asyncio.create_task(closer) if disconnect_in_task else closer)

    asyncio.run(scenario())
    assert captured.loud == []


def test_the_owner_task_is_finished_and_forgotten_after_a_close(server_path):
    """The machinery itself: one task per connection, and it ends."""
    manager = McpManager()
    seen = {}

    async def scenario():
        await _connect_inline(manager, "s1", server_path)
        assert "s1" in manager._owners, manager._owners
        seen["task"] = manager._owners["s1"][1]
        assert not seen["task"].done()
        await manager.disconnect_server("s1")

    asyncio.run(scenario())

    assert seen["task"].done() and not seen["task"].cancelled()
    assert seen["task"].exception() is None
    assert manager._owners == {} and manager._stacks == {}


def test_a_failed_connect_leaves_no_task_parked(server_path, captured):
    """A connect that never comes up must not strand an owner on the event."""
    manager = McpManager()

    async def scenario():
        ok = await manager.connect_server(
            server_id="dead", name="dead", transport="stdio",
            command=sys.executable, args=["-c", "raise SystemExit(3)"], env={},
        )
        assert ok is False
        assert manager.get_server_status("dead")["status"] == "error"
        return dict(manager._owners)

    assert asyncio.run(scenario()) == {}


def test_a_dead_server_at_boot_is_one_problem_in_the_log(captured, monkeypatch):
    """`B1392`. A stdio server whose command exits during the handshake used to
    log its real error and then, from `_open_owned`'s teardown, `Error closing
    MCP server dead: unhandled errors in a TaskGroup (1 sub-exception)` at
    WARNING — the same failure seen twice, the second time in anyio's words.
    Driven through `connect_all_enabled`, as boot runs it, with the row's own
    command, `false`. (A Python that exits does not reproduce it: it starts too
    slowly to fail inside the handshake the same way — measured.)"""
    import shutil

    false = shutil.which("false")
    if not false:
        pytest.skip("no `false` on PATH")

    class _Dead(_Row):
        def __init__(self):
            super().__init__("dead", "")
            self.command = false
            self.args = json.dumps([])

    monkeypatch.setattr(mcp_manager, "SessionLocal", lambda: _Db([_Dead()]))
    manager = McpManager()

    asyncio.run(manager.connect_all_enabled())

    assert manager.get_server_status("dead")["status"] == "error"
    assert not [m for m in captured.loud if m.startswith("Error closing")], captured.loud
    assert len(captured.loud) == 1, captured.loud      # the connect's own error


def _closing_raises(stack):
    async def boom(*_exc):
        raise RuntimeError("unhandled errors in a TaskGroup (1 sub-exception)")
    stack.push_async_exit(boom)


def test_the_teardown_of_a_failed_connect_is_not_a_second_warning(captured):
    """`B1392`, the mechanism without the race: whether the real transport's
    close raises depends on how far the handshake got, so the test above cannot
    always reproduce it. Here the close always raises after a failed setup."""
    manager = McpManager()

    async def setup(stack):
        _closing_raises(stack)
        raise ConnectionError("the server stopped during the handshake")

    async def scenario():
        with pytest.raises(ConnectionError):
            await manager._open_owned("dead", setup)

    asyncio.run(scenario())
    assert captured.loud == [], captured.loud
    assert any("failed connect" in m for lvl, m in captured.rows if lvl == "DEBUG")


def test_a_close_that_fails_after_a_good_connect_still_warns(captured):
    """The case worth keeping loud: a connection that worked and then would not
    close is a real fact about a real teardown."""
    manager = McpManager()

    async def setup(stack):
        _closing_raises(stack)
        return "session"

    async def scenario():
        assert await manager._open_owned("s1", setup) == "session"
        await manager._close_owned("s1")

    asyncio.run(scenario())
    assert any(m.startswith("Error closing MCP server s1") for m in captured.loud), captured.loud


# ---------------------------------------------------------------------------
# The control: this file can still see a bad close when there is one.
# ---------------------------------------------------------------------------


def test_the_capture_would_have_seen_the_warning(captured):
    """Without this, every `captured.loud == []` above is vacuously true."""
    manager = McpManager()

    class _Exploding:
        async def aclose(self):
            raise RuntimeError(
                "Attempted to exit cancel scope in a different task than it "
                "was entered in"
            )

    manager._sessions["s1"] = object()
    manager._stacks["s1"] = _Exploding()

    asyncio.run(manager.disconnect_all())

    assert len(captured.loud) == 1, captured.loud
    assert "Error closing MCP server s1" in captured.loud[0]
