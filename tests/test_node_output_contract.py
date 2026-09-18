# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P8-24` — a node says what it produced and how it went, not `(text, bool)`.

A boolean is enough for a chain whose only conditional is "did it work". It is
not enough for a branch node (`P8-28`), which has to ask **why** it did not, and
it is not enough for data mapping (`P8-29`), which wants the thing a step
produced rather than the sentence about it.

Two things this file is here to hold:

  * **`Law 14` — no third vocabulary.** The engine already encodes skip
    (`TaskNoop`) and retry (`TaskDeferred`). `skipped` and `deferred` ARE those
    two, converted, and the scheduler's existing handlers stay the code that
    acts on them. A status outside the four is refused at construction.
  * **`Law 13` — the adapter does not become a second output shape.** It runs
    one way: whatever a node returned becomes a `NodeResult`. The eighteen
    shipped actions are read, never rewritten.

`B600` lands here too, because it is the same defect one layer up: the agent
loop's `tool_output` carried `exit_code` for two tools and nothing for the other
~70, so a step log said `ok` beside a `web_fetch` that 404'd.
"""

import ast
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from tests.helpers.import_state import clear_fake_database_modules

clear_fake_database_modules()

import core.database as cdb  # noqa: E402
import src.builtin_actions as ba  # noqa: E402
from core.database import ScheduledTask, TaskRun  # noqa: E402
from src.task_scheduler import TaskScheduler  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

_REAL_DATABASE_ATTRS = {
    "Base": cdb.Base,
    "SessionLocal": cdb.SessionLocal,
    "ScheduledTask": ScheduledTask,
    "TaskRun": TaskRun,
}


@pytest.fixture()
def task_db(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "core.database", cdb)
    for attr, value in _REAL_DATABASE_ATTRS.items():
        monkeypatch.setattr(cdb, attr, value, raising=False)
    engine = create_engine(
        f"sqlite:///{tmp_path / 'nodes.db'}",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(cdb, "SessionLocal", factory)
    return factory


def _seed(factory):
    db = factory()
    try:
        db.add(ScheduledTask(
            id="t1", owner=None, name="Node task", prompt="",
            task_type="action", action="tidy_sessions", trigger_type="schedule",
            schedule="daily", scheduled_time="03:00",
            status="active", output_target="session",
        ))
        db.add(TaskRun(id="r1", task_id="t1", status="queued"))
        db.commit()
    finally:
        db.close()


def _scheduler():
    s = TaskScheduler.__new__(TaskScheduler)
    s._task_handles = {}
    s._task_defer_counts = {}
    s._session_manager = None
    s._notify_run_outcome = MagicMock(return_value=True)
    s.add_notification = MagicMock()
    s._log_to_assistant = MagicMock()
    return s


def _run_row(factory, run_id="r1"):
    db = factory()
    try:
        return db.query(TaskRun).filter(TaskRun.id == run_id).first()
    finally:
        db.close()


# ── the count the row asks for ─────────────────────────────────────────────

def test_the_registry_still_holds_eighteen_actions():
    """`P8-24` says "a back-compat adapter for the 18 existing actions" and
    `AGENTS.md` says re-measure every number you cite. Counted from the
    registry's own keys, not from the row."""
    assert len(ba.BUILTIN_ACTIONS) == 18, sorted(ba.BUILTIN_ACTIONS)
    # And the adapter has to cover every one of them, which means every one is
    # readable by it. `BUILTIN_ACTION_META` is the palette's half of the same
    # registry and `P8-22` holds the two equal.
    assert set(ba.BUILTIN_ACTIONS) == set(ba.BUILTIN_ACTION_META)


# ── the vocabulary ─────────────────────────────────────────────────────────

def test_a_status_outside_the_four_is_refused():
    """`Law 14`. The failure mode this prevents is somebody adding a fifth word
    in a branch nobody reads until a run has it."""
    for good in ba.NODE_STATUSES:
        assert ba.NodeResult(good).status == good
    for bad in ("ok", "failed", "aborted", "queued", "", None, True):
        with pytest.raises(ValueError):
            ba.NodeResult(bad)


def test_the_old_pair_reads_as_the_new_contract():
    """The adapter, in the direction it actually runs."""
    ok = ba.coerce_node_result(("tidied 3 sessions", True))
    assert (ok.status, ok.text, ok.ok) == ("success", "tidied 3 sessions", True)

    bad = ba.coerce_node_result(("the tidy action exited 1", False))
    assert (bad.status, bad.failed) == ("error", True)

    # And back, for a caller not yet widened. Round-tripping is what makes this
    # an adapter rather than a rewrite.
    assert bad.as_legacy() == ("the tidy action exited 1", False)
    assert ok.as_legacy() == ("tidied 3 sessions", True)


def test_a_node_can_return_something_that_is_not_a_sentence():
    """The widening. `P8-29` maps data between nodes and cannot do it through
    a string that happens to describe the data."""
    node = ba.coerce_node_result(
        ba.NodeResult("success", payload={"document_id": "d1", "words": 412}))
    assert node.payload["document_id"] == "d1"
    # `result` on the row is still text, and it is derived here rather than by
    # whichever caller happens to write the row.
    assert json.loads(node.text)["words"] == 412


def test_skip_and_retry_are_the_signals_the_engine_already_had():
    """`Law 14`, stated as a round trip: the status IS the exception."""
    noop = ba.NodeResult.from_signal(ba.TaskNoop("no new emails"))
    assert noop.status == "skipped"
    again = noop.as_signal()
    assert isinstance(again, ba.TaskNoop) and str(again) == "no new emails"

    defer = ba.NodeResult.from_signal(ba.TaskDeferred("busy", delay_seconds=90))
    assert (defer.status, defer.retry_after) == ("deferred", 90)
    again = defer.as_signal()
    assert isinstance(again, ba.TaskDeferred) and again.delay_seconds == 90

    # A plain outcome is not a signal, which is what stops `as_signal` becoming
    # a second way to end a run.
    assert ba.NodeResult("success", "done").as_signal() is None
    assert ba.NodeResult("error", "broke").as_signal() is None


# ── driven through the engine ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_an_action_that_reports_nothing_to_do_is_a_skipped_run(task_db, monkeypatch):
    """The exception still ends the run as `skipped` — but it now travels as a
    status the whole way, so a branch node can read it."""
    _seed(task_db)

    async def fake_action(owner=None, task_name="", progress_cb=None, **kwargs):
        raise ba.TaskNoop("no new emails since watermark")

    monkeypatch.setitem(ba.BUILTIN_ACTIONS, "tidy_sessions", fake_action)
    sched = _scheduler()

    node = await sched._execute_action(
        SimpleNamespace(action="tidy_sessions", owner=None, name="n", prompt=None),
        run_id="r1")
    assert node.status == "skipped"

    await sched._execute_task_locked(
        "t1", "r1", gate_foreground=False, release_executing=False)
    row = _run_row(task_db)
    assert row.status == "skipped"
    assert "watermark" in (row.result or "")


@pytest.mark.asyncio
async def test_an_action_that_defers_keeps_its_own_backoff(task_db, monkeypatch):
    """`deferred` carries the delay the action asked for. Losing it would make
    every defer the scheduler's default and the action's number decorative."""
    _seed(task_db)

    async def fake_action(owner=None, task_name="", progress_cb=None, **kwargs):
        raise ba.TaskDeferred("the mailbox is busy", delay_seconds=300)

    monkeypatch.setitem(ba.BUILTIN_ACTIONS, "tidy_sessions", fake_action)
    sched = _scheduler()
    node = await sched._execute_action(
        SimpleNamespace(action="tidy_sessions", owner=None, name="n", prompt=None),
        run_id="r1")
    assert (node.status, node.retry_after) == ("deferred", 300)

    await sched._execute_task_locked(
        "t1", "r1", gate_foreground=False, release_executing=False)
    # A deferred run deletes its row and pushes `next_run` — unchanged by this
    # row, and asserted so the widening cannot quietly start writing rows.
    assert _run_row(task_db) is None


@pytest.mark.asyncio
async def test_an_unknown_action_is_an_error_node(task_db):
    sched = _scheduler()
    node = await sched._execute_action(
        SimpleNamespace(action="no_such_action", owner=None, name="n", prompt=None),
        run_id="r1")
    assert node.status == "error"
    assert "no_such_action" in node.text


@pytest.mark.asyncio
async def test_a_shipped_action_still_ends_a_run_the_same_way(task_db, monkeypatch):
    """`Law 1`. The eighteen return `(text, bool)` and nothing about the run
    they produce changes."""
    _seed(task_db)

    async def fake_action(owner=None, task_name="", progress_cb=None, **kwargs):
        return "Removed 1 session", True

    monkeypatch.setitem(ba.BUILTIN_ACTIONS, "tidy_sessions", fake_action)
    sched = _scheduler()
    await sched._execute_task_locked(
        "t1", "r1", gate_foreground=False, release_executing=False)
    row = _run_row(task_db)
    assert (row.status, row.result, row.error) == ("success", "Removed 1 session", None)


# ── `B600` — the tool outcome one layer up ─────────────────────────────────

def test_a_tool_that_never_sets_an_exit_code_can_still_report_failure():
    from src.agent_loop import tool_outcome

    # The two that always had it.
    assert tool_outcome({"exit_code": 0, "output": "ok"}) == "ok"
    assert tool_outcome({"exit_code": 1, "output": "boom"}) == "error"
    # The ~70 that never did. Each of these read `ok` before `B600`.
    assert tool_outcome({"error": "404 Not Found"}) == "error"
    # The file tools' own shape: `success` is the verdict and `error` can be
    # empty, so the boolean has to be read on its own rather than only as a
    # companion to a message.
    assert tool_outcome({"success": False}) == "error"
    assert tool_outcome({"success": False, "error": ""}) == "error"
    assert tool_outcome({"success": False, "error": "refused"}) == "error"
    assert tool_outcome({"success": True, "path": "notes.md"}) == "ok"
    assert tool_outcome({"results": "three results"}) == "ok"
    # An empty error string is not a failure — several tools set the key
    # unconditionally, and reading its presence as a verdict is the same
    # mistake in the other direction.
    assert tool_outcome({"error": "", "output": "fine"}) == "ok"
    assert tool_outcome(None) == "ok"


def test_the_event_carries_the_outcome_it_is_read_for():
    """The producer side, asserted on the SHAPE of the dict that is yielded
    rather than on a substring (`Law 20`): the `tool_output` payload has a
    `status` key and its value is a call to `tool_outcome`.

    A grep would pass on the sentence in a comment two functions away, which is
    exactly the failure `Law 20` was written for."""
    tree = ast.parse((ROOT / "src" / "agent_loop.py").read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if "tool_output_data" not in targets or not isinstance(node.value, ast.Dict):
            continue
        for key, value in zip(node.value.keys, node.value.values):
            if isinstance(key, ast.Constant) and key.value == "status":
                found.append(
                    isinstance(value, ast.Call)
                    and getattr(value.func, "id", None) == "tool_outcome"
                )
    assert found, "the tool_output event does not build a `status` at all"
    assert all(found), "a `status` on tool_output that is not `tool_outcome(result)`"


@pytest.mark.asyncio
async def test_the_step_log_says_error_for_a_tool_that_ran_no_shell(monkeypatch):
    """`B600`'s own Verify line. Driven through the agent-loop reader."""
    events = [
        'data: {"type": "tool_start", "tool": "web_fetch", "round": 1, '
        '"command": "https://example.invalid"}\n\n',
        'data: {"type": "tool_output", "tool": "web_fetch", "round": 1, '
        '"output": "404 Not Found", "status": "error"}\n\n',
        'data: {"delta": "I could not reach it."}\n\n',
        "data: [DONE]\n\n",
    ]

    async def fake_stream(**kwargs):
        for e in events:
            yield e

    import src.agent_loop as agent_loop
    monkeypatch.setattr(agent_loop, "stream_agent_loop", fake_stream, raising=False)

    sched = _scheduler()
    task = SimpleNamespace(id="t1", name="Fetcher", prompt="fetch it",
                           owner=None, max_steps=None)
    await sched._run_agent_loop("http://e", "m", task, "sess-1", run_id="r1")

    (step,) = sched.run_steps("r1")
    assert (step["tool"], step["status"]) == ("web_fetch", "error")


@pytest.mark.asyncio
async def test_an_event_written_before_the_outcome_existed_still_reads(monkeypatch):
    """Every `tool_output` a running process already has in flight, and every
    saved stream. No `status`, `exit_code` 0 — that is a success and must not
    become an error for lacking a field it predates."""
    events = [
        'data: {"type": "tool_start", "tool": "bash", "round": 1, "command": "ls"}\n\n',
        'data: {"type": "tool_output", "tool": "bash", "round": 1, '
        '"output": "a\\nb", "exit_code": 0}\n\n',
        "data: [DONE]\n\n",
    ]

    async def fake_stream(**kwargs):
        for e in events:
            yield e

    import src.agent_loop as agent_loop
    monkeypatch.setattr(agent_loop, "stream_agent_loop", fake_stream, raising=False)

    sched = _scheduler()
    task = SimpleNamespace(id="t1", name="Sheller", prompt="ls", owner=None,
                           max_steps=None)
    await sched._run_agent_loop("http://e", "m", task, "sess-1", run_id="r2")
    (step,) = sched.run_steps("r2")
    assert step["status"] == "ok"
