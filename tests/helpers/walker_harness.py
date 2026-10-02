# SPDX-License-Identifier: AGPL-3.0-or-later
"""The `wf-walker` tests' shared harness (`P22-11`, `P22-12`, `P22-17`).

Everything is real (`Law 20`): the real `TaskScheduler` from `_execute_task`
down, a real SQLite FILE (so a "restart" is a second scheduler over the same
file), the real approval store, the real gates. What is not real is what would
reach outside: a model (the executors are recorders, or the agent loop's model
call is scripted) and a tool's far end (an MCP manager that records).

Wave D's other halves (`C-R`, `C-E`) are not on this branch;
`workflow_cd_contract.install` stands in for exactly the names that are absent
and nothing else (it answers which), so the same tests drive the real halves
once they are merged.
"""

from __future__ import annotations

import asyncio
import json
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from tests.helpers.import_state import clear_fake_database_modules

clear_fake_database_modules()

import core.database as cdb  # noqa: E402
from core.database import ScheduledTask, TaskRun, Workflow  # noqa: E402
from src import workflow_runs as wr  # noqa: E402
from src.builtin_actions import NodeResult  # noqa: E402
from src.task_scheduler import TaskScheduler  # noqa: E402

OWNER = "alice"


def make_db(monkeypatch, path):
    """A real SQLite file the scheduler and the routes read through
    `core.database.SessionLocal`. Answers the session factory."""
    from tests.helpers import workflow_cd_contract

    monkeypatch.setitem(sys.modules, "core.database", cdb)
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False},
                           poolclass=NullPool)
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(cdb, "SessionLocal", factory)
    monkeypatch.setenv("BACKGROUND_TASK_FOREGROUND_GATE", "0")
    import src.task_scheduler as ts
    monkeypatch.setattr(ts, "owner_has_admin_task_privileges", lambda owner: owner == "root")
    import src.tool_index as tool_index
    monkeypatch.setattr(tool_index, "get_tool_index", lambda: None)
    workflow_cd_contract.install(monkeypatch)
    return factory


def node(node_id, label, kind="llm", **config):
    if kind in ("llm", "research") and "prompt" not in config:
        config["prompt"] = f"Do {label}."
    return {"id": node_id, "kind": kind, "label": label, "config": config}


def arrow(a, b, port="success"):
    return {"from": a, "port": port, "to": b}


def seed_workflow(factory, nodes, edges=(), *, task_id="wf", name="Morning digest",
                  status="active", owner=OWNER, version=3, **task_kw):
    db = factory()
    try:
        db.add(ScheduledTask(id=task_id, owner=owner, name=name, task_type="workflow",
                             trigger_type=task_kw.pop("trigger_type", "schedule"),
                             schedule=task_kw.pop("schedule", "daily"),
                             scheduled_time=task_kw.pop("scheduled_time", "08:00"),
                             status=status, **task_kw))
        db.add(Workflow(id=f"w-{task_id}", owner=owner, name=name, task_id=task_id,
                        graph=json.dumps({"v": 1, "nodes": list(nodes), "edges": list(edges)}),
                        version=version))
        db.commit()
    finally:
        db.close()


def runs_of(factory, task_id):
    db = factory()
    try:
        return [{"id": r.id, "status": r.status, "result": r.result, "error": r.error,
                 "model": r.model, "finished_at": r.finished_at,
                 "steps": json.loads(r.steps) if r.steps else []}
                for r in db.query(TaskRun).filter(TaskRun.task_id == task_id)
                .order_by(TaskRun.started_at, TaskRun.id).all()]
    finally:
        db.close()


def records_of(factory, run_id):
    db = factory()
    try:
        return [wr.node_record_to_dict(r) for r in wr.run_node_records(db, run_id)]
    finally:
        db.close()


def row(factory, task_id):
    db = factory()
    try:
        return db.query(ScheduledTask).filter(ScheduledTask.id == task_id).first()
    finally:
        db.close()


def recording_scheduler(outcomes=None, *, scheduler=None):
    """The real scheduler; its three executors record what they were handed and
    answer the outcome named for that stand-in (a `NodeResult`, a string, an
    exception, or an async callable)."""
    outcomes = dict(outcomes or {})
    s = scheduler or TaskScheduler(None)
    s.calls = []

    async def answer(kind, task, run_id):
        s.calls.append({"kind": kind, "name": task.name, "slot": run_id,
                        "trigger": s.run_trigger(run_id), "task": task,
                        "prompt": getattr(task, "prompt", None),
                        "slot_state": dict(s._runs().get(run_id) or {})})
        out = outcomes.get(task.name)
        if callable(out):
            out = await out(task, run_id)
        if isinstance(out, BaseException):
            raise out
        if kind == "action":
            return out if isinstance(out, NodeResult) else NodeResult(
                "success", payload=out or f"{task.name}: done")
        return out or f"{task.name}: done"

    async def llm(task, db, run_id=None):
        return await answer("llm", task, run_id)

    async def research(task, db, run_id=None):
        return await answer("research", task, run_id)

    async def action(task, run_id=None):
        return await answer("action", task, run_id)

    s._execute_llm_task = llm
    s._execute_research_task = research
    s._execute_action = action
    s._log_to_assistant = lambda *a, **k: None
    s.delivered = []

    async def deliver(task, result, db, model=None):
        s.delivered.append((task.name, result))
    s._deliver_task_result = deliver
    return s


async def settle(scheduler, *, rounds=200):
    """Let spawned runs (a resume, a webhook's run) finish: wait until nothing
    holds a claim and no task the scheduler started is pending."""
    for _ in range(rounds):
        await asyncio.sleep(0.01)
        if not scheduler._executing:
            pending = [t for t in asyncio.all_tasks()
                       if t is not asyncio.current_task() and not t.done()
                       and "_execute_task" in repr(t.get_coro())]
            if not pending:
                return
    raise AssertionError(f"runs did not settle: {scheduler._executing}")
