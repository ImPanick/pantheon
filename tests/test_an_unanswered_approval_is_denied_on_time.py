# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B560` — an unanswered approval was denied when the store was next touched.

`ToolApprovalStore._purge_expired_locked` was reached from four places —
`create`, `consume`, `peek`, `retire_for_session` — and from nothing else: no
sweeper thread, no scheduled tick. Measured on the tree before this row by
driving the real store: past its deadline, in a process where nothing else
happened, the pending approval was still in `_pending`, no events row existed,
and no listener had been called; the first `peek` afterwards produced all three
at once. On a busy install that is invisible; on an idle one the denial lagged
the deadline indefinitely, and the events row's timestamp was the sweep.

Now `ToolApprovalStore.sweep_expired` denies and announces with no other store
call, and `approval_sweep_loop` — started by `app.py` beside its other
background loops — calls it every `APPROVAL_SWEEP_SECONDS`, jittered. Driven
(`Law 20`): the real store, the real loop as an asyncio task, the real chat
listener writing `resolved: "deny"` on the card the run left behind, and a spy
that fails the test if any other store method is called after the card exists.
"""
from __future__ import annotations

import ast
import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import src.tool_approvals as ta
from src.tool_approvals import ToolApprovalStore
from src.tool_capabilities import capabilities_for_action

ROOT = Path(__file__).resolve().parent.parent
_OTHER_CALLS = ("create", "consume", "peek", "retire_for_session")


@pytest.fixture(autouse=True)
def _clean():
    ta.clear_approval_expiry_listeners()
    yield
    ta.clear_approval_expiry_listeners()


@pytest.fixture
def recorded(monkeypatch):
    rows: list[dict] = []

    def fake(kind, **kw):
        rows.append({"kind": kind, "at": time.time(), **kw})
        return True

    import src.events as events
    monkeypatch.setattr(events, "record_event", fake)
    return rows


@pytest.fixture
def transcript(monkeypatch):
    """The card a run left behind, and the real listener that marks it."""
    from routes import chat_routes

    ask_user = {"kind": "tool_approval", "approval_id": None, "session_id": "s-1"}
    metadata = {"_db_id": "m-1", "tool_events": [{"ask_user": ask_user}]}
    sess = SimpleNamespace(id="s-1", history=[SimpleNamespace(metadata=metadata)])
    db_message = SimpleNamespace(meta_data=None)

    class Column:
        def __eq__(self, value):
            return value

    class FakeDBMessage:
        id = Column()
        session_id = Column()

    class FakeDB:
        def query(self, model):
            return self

        def filter(self, *conditions):
            return self

        def first(self):
            return db_message

        def commit(self):
            pass

        def rollback(self):  # pragma: no cover
            pass

        def close(self):
            pass

    monkeypatch.setattr(chat_routes, "DBChatMessage", FakeDBMessage)
    monkeypatch.setattr(chat_routes, "SessionLocal", FakeDB)
    monkeypatch.setattr(chat_routes, "get_session_manager_instance",
                        lambda: SimpleNamespace(sessions={"s-1": sess}))
    ta.register_approval_expiry_listener(chat_routes.deny_expired_tool_approval)
    return ask_user


def _create(store):
    return store.create(
        owner="alice", session_id="s-1", origin_run_id="run-1",
        tool_name="bash", content="rm -rf /tmp/scratch", workspace=None,
        external_untrusted_context_seen=False,
        capabilities=capabilities_for_action("bash", "rm -rf /tmp/scratch"),
    )


def _forbid_other_calls(store, monkeypatch):
    def refuse(name):
        def call(*a, **k):
            raise AssertionError(f"{name} was called: the sweep must stand alone")
        return call
    for name in _OTHER_CALLS:
        monkeypatch.setattr(store, name, refuse(name))


def test_an_idle_process_denies_the_card_within_one_sweep_of_its_deadline(
        recorded, transcript, monkeypatch):
    """The row's `Verify:`."""
    store = ToolApprovalStore(ttl_seconds=1)
    pending = _create(store)
    transcript["approval_id"] = pending.approval_id
    _forbid_other_calls(store, monkeypatch)
    period = 0.2

    async def idle_process():
        sweeper = asyncio.create_task(ta.approval_sweep_loop(store, period=period))
        try:
            from src.jitter import DEFAULT_FRACTION
            deadline = pending.expires_at + period * (1 + DEFAULT_FRACTION)
            while time.time() < deadline + 0.5 and transcript.get("resolved") is None:
                await asyncio.sleep(0.05)
        finally:
            sweeper.cancel()
            await asyncio.gather(sweeper, return_exceptions=True)

    asyncio.run(idle_process())

    denials = [r for r in recorded if r["kind"] == "approval"]
    assert [r["outcome"] for r in denials] == [ta.APPROVAL_DENIED_TIMEOUT]
    # Within one sweep period (plus its jitter) of the deadline — not whenever
    # the store happened to be touched next.
    late = denials[0]["at"] - pending.expires_at
    assert late <= period * 1.1 + 0.15, late
    assert transcript["resolved"] == "deny"
    assert pending.approval_id not in store._pending


def test_a_sweep_before_the_deadline_leaves_the_card_answerable(recorded):
    store = ToolApprovalStore(ttl_seconds=600)
    pending = _create(store)
    assert store.sweep_expired() == 0
    assert recorded == []
    assert store.peek(pending.approval_id, owner="alice", session_id="s-1") is not None


def test_a_failing_sweep_does_not_end_the_loop(monkeypatch):
    """A missed sweep is caught by the next one: the loop survives an error."""
    calls = []

    class Flaky:
        def sweep_expired(self):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("database is locked")
            return 0

    async def run():
        task = asyncio.create_task(ta.approval_sweep_loop(Flaky(), period=0.02))
        while len(calls) < 3:
            await asyncio.sleep(0.01)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())
    assert len(calls) >= 3


def test_the_app_starts_the_sweeper_with_its_other_background_loops():
    """Resolved in scope (`Law 20`'s second preference): inside the function in
    `app.py` that starts `_null_owner_sweep_loop`, a task is created from
    `approval_sweep_loop()`."""
    tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))

    def created_tasks(fn):
        out = set()
        for node in ast.walk(fn):
            if (isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "create_task"
                    and node.args and isinstance(node.args[0], ast.Call)
                    and isinstance(node.args[0].func, ast.Name)):
                out.add(node.args[0].func.id)
        return out

    starters = [fn for fn in ast.walk(tree)
                if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
                and "_null_owner_sweep_loop" in created_tasks(fn)]
    assert starters, "app.py no longer starts _null_owner_sweep_loop where this looked"
    assert "approval_sweep_loop" in created_tasks(starters[0])
