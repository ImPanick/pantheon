# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1061` — two more doors where a person asks for a run still started
background-gated work.

`B1047` made the task route's buttons person work (`started_by='person'`): a run
a person pressed waits only for a chat reply in progress, and the page they
pressed it on neither holds it back nor stops it. Two doors were left calling
`run_task_now` with no `started_by`, so with Pantheon open each waited for it to
be idle — while the person who asked was looking at it:

  * the assistant's check-in *Run now* (`routes/assistant_routes.py:
    run_check_in_now`, pressed in `static/js/assistant.js`);
  * `manage_tasks run` — "run my backup now", said in chat.

**`manage_tasks` is the real question** (the row's words): the tool is called
from a person's chat turn and from a scheduled run's agent alike, and only the
first is a person asking. Measured 2026-10-01 how the loop can say which:
`stream_agent_loop` already carries the answer as `workload` — the scheduler
alone passes `"background"` (`src/task_scheduler.py`, its agent runs); a
person's chat, the teacher inside it, a skill test a person pressed and the
background-job follow-up in a person's session take the default
`"foreground"` — and the local model gate (`src/llm_core._local_model_slot`)
already reads that same word to decide whose model call yields. So the loop
binds it, as `started_by`, into each tool call's own task (the two
`execute_tool_block` sites, beside `bind_run_limits`), and `manage_tasks run`
reads it (`src.interactive_gate.tool_call_started_by`). Nothing bound is
background: today's answer for every caller.

**Measured before the fix, through the code in this file:** the assistant's
*Run now* and `manage_tasks run` with Pantheon open each left the run
`queued` behind the idle gate and the executor never called while the page
stayed open.

Real `src.interactive_gate`, real `TaskScheduler` (`run_task_now` →
`_execute_task`), the real assistant handler, the real `do_manage_tasks`, the
real `stream_agent_loop`, a real SQLite file. The model executor is a recorder;
nothing waits on the wall clock (`B1047`'s file is the model for the gate's
set-up, kept here in a few lines so `B1060`'s rewrite of that file is not a
dependency).
"""

from __future__ import annotations

import asyncio
import json
import sys
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from tests.helpers.import_state import clear_fake_database_modules

clear_fake_database_modules()

import core.database as cdb  # noqa: E402
import src.interactive_gate as ig  # noqa: E402
from core.database import CrewMember, ScheduledTask, TaskRun  # noqa: E402
from src.task_scheduler import TaskScheduler  # noqa: E402


@pytest.fixture()
def task_db(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "core.database", cdb)
    engine = create_engine(f"sqlite:///{tmp_path / 'b1061.db'}",
                           connect_args={"check_same_thread": False}, poolclass=NullPool)
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(cdb, "SessionLocal", factory)
    db = factory()
    try:
        db.add(CrewMember(id="asst", owner="alice", name="Assistant", is_default_assistant=True))
        db.add(ScheduledTask(id="ci", owner="alice", name="Morning check-in", task_type="llm",
                             prompt="Check in.", crew_member_id="asst", trigger_type="schedule",
                             schedule="daily", scheduled_time="08:00", status="active",
                             output_target="session"))
        db.add(ScheduledTask(id="bk", owner="alice", name="Nightly backup", task_type="llm",
                             prompt="Back up.", trigger_type="schedule", schedule="daily",
                             scheduled_time="02:00", status="active", output_target="session"))
        db.commit()
    finally:
        db.close()
    return factory


@pytest.fixture()
def pantheon_open(monkeypatch):
    """The real gate, on, with a visible tab's heartbeat: Pantheon is open.
    The quiet window is 0 so nothing waits on the wall clock."""
    monkeypatch.delenv("BACKGROUND_TASK_FOREGROUND_GATE", raising=False)
    monkeypatch.setenv("BACKGROUND_TASK_QUIET_MS", "0")
    monkeypatch.setenv("BACKGROUND_TASK_BROWSER_ACTIVE_SECONDS", "45")
    monkeypatch.setenv("BACKGROUND_TASK_MAX_WAIT_SECONDS", "0")
    for name, value in (("_ACTIVE_REQUESTS", 0), ("_LAST_ACTIVITY", 0.0),
                        ("_LAST_BROWSER_ACTIVITY", 0.0), ("_COND", None), ("_COND_LOOP", None)):
        monkeypatch.setattr(ig, name, value)
    monkeypatch.setattr(ig, "_has_active_chat_stream", lambda: False)


@pytest.fixture()
def scheduler(monkeypatch):
    ran = []
    s = TaskScheduler(None)

    async def _llm(task, db, run_id=None):
        ran.append(task.id)
        return "done"

    async def _deliver(*a, **k):
        return None
    s._execute_llm_task = _llm
    s._deliver_task_result = _deliver
    s._log_to_assistant = lambda *a, **k: None
    s.ran = ran
    import src.event_bus as bus
    monkeypatch.setattr(bus, "_task_scheduler", s)
    return s


async def _open_tab():
    await ig.mark_browser_activity()


async def _turns(n=200):
    for _ in range(n):
        await asyncio.sleep(0)


def _statuses(factory, task_id):
    db = factory()
    try:
        return [r.status for r in db.query(TaskRun).filter(TaskRun.task_id == task_id).all()]
    finally:
        db.close()


# ── the assistant's check-in *Run now* ──────────────────────────────────────

@pytest.mark.asyncio
async def test_the_assistants_run_now_runs_while_pantheon_is_open(
        task_db, pantheon_open, scheduler, monkeypatch):
    import routes.assistant_routes as assistant_routes
    monkeypatch.setattr(assistant_routes, "SessionLocal", task_db)
    router = assistant_routes.setup_assistant_routes(scheduler)
    run_now = next(r.endpoint for r in router.routes
                   if getattr(r, "path", None) == "/api/assistant/run/{task_id}")
    await _open_tab()
    out = await run_now("ci", SimpleNamespace(state=SimpleNamespace(current_user="alice")))
    assert out == {"started": True}
    await _turns()
    assert scheduler.ran == ["ci"], "the run waited for Pantheon to be idle while its asker looked on"
    assert _statuses(task_db, "ci") == ["success"]


# ── manage_tasks run ─────────────────────────────────────────────────────────

async def _tool_in_turn(workload, content):
    """`manage_tasks`, called as the loop calls a tool: in a task of its own,
    with the loop's `workload` bound first."""
    from src.tools.system import do_manage_tasks

    async def call():
        ig.bind_tool_call_started_by(workload)
        return await do_manage_tasks(json.dumps(content), owner="alice")
    return await asyncio.create_task(call())


@pytest.mark.asyncio
async def test_run_said_in_a_persons_chat_runs_while_pantheon_is_open(
        task_db, pantheon_open, scheduler):
    await _open_tab()
    out = await _tool_in_turn("foreground", {"action": "run", "task_id": "bk"})
    assert out == {"response": "Task 'Nightly backup' triggered", "exit_code": 0}
    await _turns()
    assert scheduler.ran == ["bk"]


@pytest.mark.asyncio
async def test_run_asked_by_a_scheduled_runs_agent_still_waits_for_idle(
        task_db, pantheon_open, scheduler):
    """`Law 1`: background work keeps the gate it was built for."""
    await _open_tab()
    out = await _tool_in_turn("background", {"action": "run", "task_id": "bk"})
    assert out["exit_code"] == 0
    await _turns()
    assert scheduler.ran == [] and _statuses(task_db, "bk") == ["queued"]
    for handle in list(scheduler._task_handles.values()):
        handle.cancel()
    await _turns(20)


def test_a_call_nothing_bound_is_background_and_a_binding_ends_with_its_task():
    async def go():
        seen = {"outside": ig.tool_call_started_by()}

        async def call(workload):
            ig.bind_tool_call_started_by(workload)
            return ig.tool_call_started_by()
        seen["person"] = await asyncio.create_task(call(None))
        seen["chat"] = await asyncio.create_task(call("foreground"))
        seen["scheduled"] = await asyncio.create_task(call("background"))
        seen["after"] = ig.tool_call_started_by()
        return seen
    assert asyncio.run(go()) == {"outside": "background", "person": "person", "chat": "person",
                                 "scheduled": "background", "after": "background"}


# ── the loop says which, for every tool call it makes ───────────────────────

def _drive_loop(monkeypatch, **kwargs):
    """The real `stream_agent_loop`, a scripted model that asks for one
    `manage_tasks` call, and the tool executor replaced by a probe that reads
    who the call is for — in the call's own task, where the real one runs."""
    import src.agent_tools  # noqa: F401  (agent_tools <-> tool_parsing import order)
    import src.agent_loop as agent_loop
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: None, raising=False)
    monkeypatch.setattr(agent_loop, "estimate_tokens", lambda *a, **k: 10, raising=False)
    monkeypatch.setattr(agent_loop, "blocked_tools_for_owner", lambda owner: set(), raising=False)
    replies = iter(['```manage_tasks\n{"action":"list"}\n```'])

    async def fake_stream(*args, **kw):
        yield f"data: {json.dumps({'delta': next(replies, 'Done.')})}\n\n"
        yield "data: [DONE]\n\n"
    seen = []

    async def probe(block, *args, **kw):
        seen.append((block.tool_type, ig.tool_call_started_by()))
        return (block.tool_type, {"output": "ok", "exit_code": 0})
    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", fake_stream, raising=False)
    monkeypatch.setattr(agent_loop, "execute_tool_block", probe, raising=False)

    async def go():
        return [c async for c in agent_loop.stream_agent_loop(
            "http://x/v1", "m", [{"role": "user", "content": "run my backup"}],
            owner="alice", session_id="b1061", relevant_tools={"manage_tasks"}, **kwargs)]
    asyncio.run(go())
    return seen


@pytest.mark.parametrize("kwargs,expected", [
    ({}, "person"),                              # a person's chat turn: the default workload
    ({"workload": "background"}, "background"),  # the scheduler's own agent runs
])
def test_the_loop_says_who_each_tool_call_is_for(monkeypatch, kwargs, expected):
    assert _drive_loop(monkeypatch, **kwargs) == [("manage_tasks", expected)]
