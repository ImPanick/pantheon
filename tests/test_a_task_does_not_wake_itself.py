# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1077` — a plain task fired by an event, whose own run fires that event,
runs once.

`P22-05` closed this for a workflow (its walker marks what its steps do with
`run_origin`, and `_handle_event` leaves the run's own task out of what an
event wakes). A plain task had no mark: a Prompt task on `document_updated`
whose tools edit a document moved its own counter, `_handle_event` wrote its
`next_run = now` before `run_task_now` turned it away as already running, and
an event handled after the run's last write left it due — so the loop ran it
again, because it ran (`SLICE-B-DESIGN` § 0.7). Every run is marked now, in
`_execute_task_locked`, around its executor and its delivery.

The two marks meet in a *Run task* step, whose target runs inside the
workflow's run: the target's own mark must not un-mark the workflow (or a step
test), so a mark inside another keeps the outer one's (`RunOrigin.within`).

Driven through the real bus (`fire_event` → `_handle_event`), the real
scheduler and a real SQLite file (`Law 20`); a Prompt task's executor is the
stand-in for a model whose tool edits a document (twice), and reads the mark
from a worker thread, as a tool run through `asyncio.to_thread` would.
"""

import asyncio
import json

import pytest

from test_a_workflow_does_not_fire_itself import (  # noqa: F401
    EDIT, OWNER, _runs, _settle, _task, bus, cdb, event_bus,
)
from core.database import ScheduledTask, Workflow  # noqa: E402
from src.builtin_actions import NodeResult  # noqa: E402
from src.task_scheduler import TaskScheduler  # noqa: E402


def _seed(factory, *rows):
    db = factory()
    try:
        for row in rows:
            db.add(row)
        db.commit()
    finally:
        db.close()


def _scheduler(monkeypatch, edits):
    """The real scheduler. A Prompt task named in `edits` edits a document
    while it runs (fires `document_updated`, as the documents tool does)."""
    s = TaskScheduler(None)
    s.ran, s.origins, s.threaded = [], {}, {}

    async def llm(task, db, run_id=None):
        s.ran.append(task.name)
        s.origins[task.name] = event_bus.current_run_origin()
        # A tool run in a worker thread (`asyncio.to_thread`) sees the mark.
        s.threaded[task.name] = await asyncio.to_thread(event_bus.current_run_origin)
        if task.name in edits:
            event_bus.fire_event("document_updated", OWNER, EDIT)
            event_bus.fire_event("document_updated", OWNER, EDIT)
        return f"{task.name}: done"

    async def action(task, run_id=None):
        s.ran.append(task.name)
        return NodeResult("success", payload="done")
    s._execute_llm_task = llm
    s._execute_action = action
    s._log_to_assistant = lambda *a, **k: None

    async def deliver(*a, **k):
        return None
    s._deliver_task_result = deliver
    monkeypatch.setattr(event_bus, "_task_scheduler", s)
    return s


def _writer(**kw):
    fields = dict(id="writer", owner=OWNER, name="Doc writer", task_type="llm",
                  prompt="Tidy the document that changed.", trigger_type="event",
                  trigger_event="document_updated", trigger_count=1, status="active")
    fields.update(kw)
    return ScheduledTask(**fields)


async def _quiet(rounds=20):
    for _ in range(rounds):
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_a_prompt_task_that_edits_a_document_runs_once(bus, monkeypatch):
    """The row's `Verify:`. Its own two edits neither move its counter (every
    third edit fires it) nor leave it due; the other task on the same event
    is woken and told what caused it — the task, not "the workflow"."""
    _seed(bus, _writer(trigger_count=3))
    s = _scheduler(monkeypatch, {"Doc writer"})
    await s._execute_task("writer")
    await _settle(lambda: _runs(bus, "other")
                  and all(r[0] == "success" for r in _runs(bus, "other")))
    await _quiet()
    assert [r[0] for r in _runs(bus, "writer")] == ["success"], "it ran because it ran"
    writer = _task(bus, "writer")
    assert (writer.trigger_counter or 0) == 0, "its own edits moved its own counter"
    assert writer.next_run is None, "its own edits left it due"
    lines = [r[1][0]["detail"] for r in _runs(bus, "other")]
    assert all(ln.startswith("Triggered by document_updated (caused by the task “Doc writer”)")
               for ln in lines), lines
    assert s.threaded["Doc writer"] == s.origins["Doc writer"], "a worker thread sees the mark"
    assert event_bus.current_run_origin() is None, "the mark ends with the run"


@pytest.mark.asyncio
async def test_its_own_event_handled_after_the_run_ended_does_not_start_it_again(bus, monkeypatch):
    """`SLICE-B-DESIGN` § 0.7 for a plain task: the event the run caused,
    handled after its run let its claim go, still names the run."""
    _seed(bus, _writer(trigger_type="webhook", trigger_event=None))
    s = _scheduler(monkeypatch, set())
    await s._execute_task("writer")
    origin = s.origins["Doc writer"]
    assert (origin.task_id, origin.kind) == ("writer", "task")
    db = bus()
    try:
        db.query(ScheduledTask).filter(ScheduledTask.id == "writer").update(
            {"trigger_type": "event", "trigger_event": "document_updated"})
        db.commit()
    finally:
        db.close()
    await event_bus._handle_event("document_updated", OWNER, EDIT, origin=origin)
    await _settle(lambda: [r[0] for r in _runs(bus, "other")] == ["success"])
    await _quiet()
    assert [r[0] for r in _runs(bus, "writer")] == ["success"]
    assert _task(bus, "writer").next_run is None


def _keeper(factory, target="editor"):
    """A workflow on `document_updated` whose one step runs another task."""
    _seed(factory,
          ScheduledTask(id="editor", owner=OWNER, name="Editor", task_type="llm",
                        prompt="Edit it.", trigger_type="webhook", status="active"))
    db = factory()
    try:
        db.query(Workflow).filter(Workflow.task_id == "wf").update({"graph": json.dumps(
            {"v": 1, "nodes": [{"id": "n1", "kind": "run_task", "label": "Run the editor",
                                "config": {"task_id": target}}], "edges": []})})
        db.commit()
    finally:
        db.close()


@pytest.mark.asyncio
async def test_a_run_task_steps_target_does_not_wake_the_workflow_that_ran_it(bus, monkeypatch):
    """The target runs inside the workflow's run; its own mark keeps the
    workflow's, so its edit wakes neither of them — and does wake the rest."""
    _keeper(bus)
    s = _scheduler(monkeypatch, {"Editor"})
    await s._execute_task("wf")
    await _settle(lambda: _runs(bus, "other")
                  and all(r[0] == "success" for r in _runs(bus, "other")))
    await _quiet()
    assert [r[0] for r in _runs(bus, "wf")] == ["success"], "the workflow woke itself"
    assert [r[0] for r in _runs(bus, "editor")] == ["success"]
    assert (_task(bus, "wf").trigger_counter or 0) == 0
    origin = s.origins["Editor"]
    assert (origin.task_id, origin.kind, origin.within) == ("editor", "task", ("wf",))


@pytest.mark.asyncio
async def test_testing_a_run_task_step_still_wakes_nothing(bus, monkeypatch):
    """`P22-08`: a step test wakes no task — its target's own mark keeps it a
    test."""
    _keeper(bus)
    s = _scheduler(monkeypatch, {"Editor"})
    out = await s.test_workflow_node(
        _task(bus, "wf"), "Doc keeper",
        {"id": "n1", "kind": "run_task", "label": "Run the editor",
         "config": {"task_id": "editor"}})
    assert out["status"] == "success", out
    await _quiet()
    assert _runs(bus, "wf") == [] and _runs(bus, "other") == []
    assert (_task(bus, "other").trigger_counter or 0) == 0
    assert s.origins["Editor"].test is True
