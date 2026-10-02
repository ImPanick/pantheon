# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P22-05` — a workflow's own writes carry where they came from, so a workflow
fired by `document_updated` that edits a document does not fire itself.

Without it: a workflow's step writes a document, the write fires
`document_updated`, and the event bus wakes every active task on that event —
the workflow included. In-process the run's `_executing` claim usually turns
the second start away, but `_handle_event` has already moved the counter and
written `next_run`, and an event handled just after the run's claim is released
starts it again: a workflow that runs because it ran. Across processes nothing
held at all: the email MCP server is a subprocess with no scheduler, and its
branch writes `next_run = now` for the main process's loop to pick up.

Driven through the real bus (`fire_event` → `_handle_event`), the real
scheduler and a real SQLite file (`Law 20`).
"""

import asyncio
import json
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from tests.helpers.import_state import clear_fake_database_modules

clear_fake_database_modules()

import core.database as cdb  # noqa: E402
import src.event_bus as event_bus  # noqa: E402
from core.database import ScheduledTask, TaskRun, Workflow  # noqa: E402
from src.builtin_actions import NodeResult  # noqa: E402
from src.task_scheduler import TaskScheduler  # noqa: E402

OWNER = "alice"
EDIT = {"document_id": "d1", "title": "Shopping list"}


@pytest.fixture()
def bus(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "core.database", cdb)
    engine = create_engine(f"sqlite:///{tmp_path / 'bus.db'}",
                           connect_args={"check_same_thread": False}, poolclass=NullPool)
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(cdb, "SessionLocal", factory)
    monkeypatch.setenv("BACKGROUND_TASK_FOREGROUND_GATE", "0")
    # Wave D's C-R / C-E halves are the real ones (`integrate-d`): this fails
    # naming a missing half and stands nothing in.
    from tests.helpers import workflow_contract
    workflow_contract.install(monkeypatch)
    db = factory()
    try:
        db.add(ScheduledTask(id="wf", owner=OWNER, name="Doc keeper", task_type="workflow",
                             trigger_type="event", trigger_event="document_updated",
                             trigger_count=1, status="active"))
        db.add(Workflow(id="w1", owner=OWNER, name="Doc keeper", task_id="wf", version=1,
                        graph=json.dumps({"v": 1, "nodes": [
                            {"id": "n1", "kind": "action", "label": "Tidy the list",
                             "config": {"action": "tidy_documents"}}], "edges": []})))
        db.add(ScheduledTask(id="other", owner=OWNER, name="Change log", task_type="llm",
                             prompt="Note the change.", trigger_type="event",
                             trigger_event="document_updated", trigger_count=1,
                             status="active"))
        db.commit()
    finally:
        db.close()
    return factory


def _scheduler(monkeypatch, step):
    s = TaskScheduler(None)
    s.ran = []

    async def action(task, run_id=None):
        s.ran.append((task.name, s.run_trigger(run_id)))
        return await step(task, run_id)

    async def llm(task, db, run_id=None):
        s.ran.append((task.name, s.run_trigger(run_id)))
        return "noted"
    s._execute_action = action
    s._execute_llm_task = llm
    s._log_to_assistant = lambda *a, **k: None

    async def deliver(*a, **k):
        return None
    s._deliver_task_result = deliver
    monkeypatch.setattr(event_bus, "_task_scheduler", s)
    return s


def _runs(factory, task_id):
    db = factory()
    try:
        return [(r.status, json.loads(r.steps or "[]"))
                for r in db.query(TaskRun).filter(TaskRun.task_id == task_id)
                .order_by(TaskRun.started_at).all()]
    finally:
        db.close()


def _task(factory, task_id):
    db = factory()
    try:
        return db.query(ScheduledTask).filter(ScheduledTask.id == task_id).first()
    finally:
        db.close()


async def _settle(predicate, limit=400):
    for _ in range(limit):
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("timed out waiting")


@pytest.mark.asyncio
async def test_a_workflow_that_edits_a_document_does_not_wake_itself(bus, monkeypatch):
    """The step edits a document (fires `document_updated`, as the documents
    tool does). The workflow's own counter does not move and it is not woken;
    the other task on the same event is, and is told what caused it."""
    async def edit(task, run_id):
        event_bus.fire_event("document_updated", OWNER, EDIT)
        return NodeResult("success", payload="Tidied.")
    s = _scheduler(monkeypatch, edit)
    db = bus()
    try:
        db.query(ScheduledTask).filter(ScheduledTask.id == "wf").update({"trigger_count": 3})
        db.commit()
    finally:
        db.close()

    await s._execute_task("wf")
    await _settle(lambda: [r[0] for r in _runs(bus, "other")] == ["success"])
    assert [r[0] for r in _runs(bus, "wf")] == ["success"]
    wf = _task(bus, "wf")
    assert (wf.trigger_counter or 0) == 0, "its own write moved its own counter"
    assert wf.next_run is None
    first_line = _runs(bus, "other")[0][1][0]["detail"]
    assert first_line.startswith("Triggered by document_updated (caused by the workflow “Doc keeper”)")
    other_trigger = [t for name, t in s.ran if name == "Change log"][0]
    assert other_trigger["origin"] == {"task_id": "wf", "task": "Doc keeper",
                                       "run_id": other_trigger["origin"]["run_id"]}
    assert event_bus.current_run_origin() is None, "the mark ends with the run"


@pytest.mark.asyncio
async def test_its_own_event_handled_after_the_run_ended_does_not_start_it_again(bus, monkeypatch):
    """`SLICE-B-DESIGN` § 0.7: an event the run caused, handled after the run
    let its claim go, started it again. The event still names its run."""
    caused = {}

    async def edit(task, run_id):
        caused["origin"] = event_bus.current_run_origin()
        return NodeResult("success", payload="Tidied.")
    s = _scheduler(monkeypatch, edit)
    await s._execute_task("wf")
    assert caused["origin"].task_id == "wf"
    await event_bus._handle_event("document_updated", OWNER, EDIT, origin=caused["origin"])
    await _settle(lambda: [r[0] for r in _runs(bus, "other")] == ["success"])
    await asyncio.sleep(0.05)
    assert [r[0] for r in _runs(bus, "wf")] == ["success"], "it ran because it ran"


@pytest.mark.asyncio
async def test_a_person_s_edit_still_starts_the_workflow(bus, monkeypatch):
    """`Law 1`. No origin — a person's edit — wakes it exactly as before."""
    async def edit(task, run_id):
        return NodeResult("success", payload="Tidied.")
    s = _scheduler(monkeypatch, edit)
    await event_bus._handle_event("document_updated", OWNER, EDIT)
    await _settle(lambda: [r[0] for r in _runs(bus, "wf")] == ["success"]
                  and [r[0] for r in _runs(bus, "other")] == ["success"])
    assert s.ran[0][1]["data"] == EDIT and "origin" not in s.ran[0][1]


@pytest.mark.asyncio
async def test_testing_a_step_wakes_no_task_at_all(bus, monkeypatch):
    """`P22-08`: *"nothing else ran"*."""
    async def edit(task, run_id):
        event_bus.fire_event("document_updated", OWNER, EDIT)
        return NodeResult("success", payload="Tidied.")
    s = _scheduler(monkeypatch, edit)
    out = await s.test_workflow_node(
        _task(bus, "wf"), "Doc keeper",
        {"id": "n1", "kind": "action", "label": "Tidy the list",
         "config": {"action": "tidy_documents"}})
    assert out["status"] == "success"
    for _ in range(10):
        await asyncio.sleep(0.01)
    assert _runs(bus, "wf") == [] and _runs(bus, "other") == []
    assert (_task(bus, "other").trigger_counter or 0) == 0
    assert [name for name, _t in s.ran] == ["Doc keeper · Tidy the list"]


@pytest.mark.asyncio
async def test_the_email_subprocess_does_not_queue_a_workflow_that_is_running(bus, monkeypatch):
    """The process with no scheduler (the email MCP server) cannot see the
    run's context. It asks the run rows instead: a workflow with a run in
    flight is not queued again; anything else is queued as before."""
    monkeypatch.setattr(event_bus, "_task_scheduler", None)
    db = bus()
    try:
        db.add(TaskRun(id="r1", task_id="wf", status="running", result="Step 1: Tidy…"))
        db.commit()
    finally:
        db.close()
    await event_bus._handle_event("document_updated", OWNER, EDIT)
    assert _task(bus, "wf").next_run is None
    assert (_task(bus, "wf").trigger_counter or 0) == 0
    assert _task(bus, "other").next_run is not None, "a plain task is queued as before"

    db = bus()
    try:
        db.query(TaskRun).filter(TaskRun.id == "r1").update({"status": "success"})
        db.commit()
    finally:
        db.close()
    await event_bus._handle_event("document_updated", OWNER, EDIT)
    assert _task(bus, "wf").next_run is not None, "not running: queued, as before (`Law 1`)"
