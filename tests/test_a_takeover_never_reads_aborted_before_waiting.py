# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1138` — a workflow run the foreground takes over reads `waiting`, never
`aborted` first.

Measured by `integrate-e` (P22-00, light 1400 and dark 390): a poll of
`/api/tasks/{id}/runs` returned the run `aborted`, "Paused because Pantheon
became active", `finished_at` set — and the same run ended `success` a minute
later. The gate (`stop_background_tasks_for_foreground`) wrote the row
`aborted` before its cancel landed, so the walker and the cancel branch could
read who stopped it; the cancel branch then parked it `waiting` (`P22-11`).
Anything that read the row in between — Activity, a poll, a notification on a
terminal status — saw a stopped run.

Every status the row takes is recorded by an SQLite trigger on the real file,
so "never `aborted`" is measured over the whole life of the run, not sampled.
Driven through the real gate, the real cancel branch, the real walker and the
real sweeper (the walker harness: only the steps' far ends record).
"""

import asyncio
import sqlite3

import pytest

from src.task_scheduler import FOREGROUND_TAKEOVER, TAKEOVER_PARKED
from tests.helpers.walker_harness import (
    app_for, arrow, make_db, node, records_of, recording_scheduler, runs_of, seed_workflow, settle,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture()
def factory(monkeypatch, tmp_path):
    path = tmp_path / "takeover.db"
    f = make_db(monkeypatch, path)
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE status_log (run_id TEXT, status TEXT, finished INTEGER);
        CREATE TRIGGER log_run_insert AFTER INSERT ON task_runs BEGIN
            INSERT INTO status_log VALUES (NEW.id, NEW.status, NEW.finished_at IS NOT NULL);
        END;
        CREATE TRIGGER log_run_update AFTER UPDATE ON task_runs
            WHEN NEW.status IS NOT OLD.status OR (NEW.finished_at IS NULL) != (OLD.finished_at IS NULL) BEGIN
            INSERT INTO status_log VALUES (NEW.id, NEW.status, NEW.finished_at IS NOT NULL);
        END;
    """)
    con.commit()
    con.close()
    f.path = path
    return f


def _history(factory, run_id):
    con = sqlite3.connect(factory.path)
    try:
        return [(s, bool(fin)) for s, fin in con.execute(
            "SELECT status, finished FROM status_log WHERE run_id=? ORDER BY rowid", (run_id,))]
    finally:
        con.close()


def _digest(factory, hold, inside):
    async def post(task, run_id):
        return "posted to #ops"

    async def slow(task, run_id):
        if hold["first"]:
            hold["first"] = False
            inside.set()
            await asyncio.sleep(30)          # a person arrives while this runs
        return "fetched"

    seed_workflow(factory, [
        node("post", "Post", "action", action="tidy_sessions"),
        node("fetch", "Fetch", "action", action="tidy_documents"),
        node("brief", "Brief", "action", action="consolidate_memory"),
    ], [arrow("post", "fetch"), arrow("fetch", "brief")])
    return recording_scheduler({"Morning digest · Post": post, "Morning digest · Fetch": slow})


async def test_the_gate_parks_the_run_without_an_aborted_reading(factory, monkeypatch):
    inside, hold = asyncio.Event(), {"first": True}
    s = _digest(factory, hold, inside)
    app = app_for(factory, s, monkeypatch)
    assert await s.run_task_now("wf") is True
    await asyncio.wait_for(inside.wait(), timeout=5)
    [run] = runs_of(factory, "wf")

    assert await s.stop_background_tasks_for_foreground() >= 1
    # The moment the measured poll fell into: the gate has spoken, the cancel
    # has not landed yet. The row says the run is still going, not that it
    # stopped.
    [between] = runs_of(factory, "wf")
    assert between["status"] != "aborted" and between["finished_at"] is None, between
    from tests.helpers.walker_harness import client_for
    async with client_for(app) as client:
        polled = (await client.get("/api/tasks/wf/runs", headers={"x-test-user": "alice"})).json()
    rows = polled.get("runs", polled) if isinstance(polled, dict) else polled
    assert [r["status"] for r in rows] != ["aborted"], rows

    await settle(s)
    [parked] = runs_of(factory, "wf")
    assert parked["status"] == "waiting" and parked["result"] == TAKEOVER_PARKED
    assert parked["error"] is None and parked["finished_at"] is None
    by = {r["node_id"]: r for r in records_of(factory, run["id"])}
    assert by["post"]["status"] == "success"
    assert by["fetch"]["status"] == "waiting" and by["fetch"]["waiting"]["kind"] == "idle"

    assert await s._resume_due_waits() == 1
    await settle(s)
    [done] = runs_of(factory, "wf")
    assert done["status"] == "success", done
    history = _history(factory, run["id"])
    assert ("aborted", True) not in history and all(s_ != "aborted" for s_, _ in history), history
    assert [h for h in history if h[0] == "waiting"], history
    assert any("runs again" in (st.get("detail") or "") for st in done["steps"])


async def test_a_switched_off_workflow_still_ends_saying_why(factory):
    """`Law 1`: when the cancel branch cannot park it — the workflow was
    switched off while it ran — the run still ends `aborted` with the
    takeover's words, as it did; it is the in-between reading that is gone."""
    from core.database import ScheduledTask

    inside, hold = asyncio.Event(), {"first": True}
    s = _digest(factory, hold, inside)
    assert await s.run_task_now("wf") is True
    await asyncio.wait_for(inside.wait(), timeout=5)
    db = factory()
    db.query(ScheduledTask).filter(ScheduledTask.id == "wf").update({"status": "paused"})
    db.commit()
    db.close()
    await s.stop_background_tasks_for_foreground()
    await settle(s)
    [run] = runs_of(factory, "wf")
    assert run["status"] == "aborted" and run["error"] == FOREGROUND_TAKEOVER, run
    assert "It will not be retried" in run["result"]
    by = {r["node_id"]: r for r in records_of(factory, run["id"])}
    assert by["fetch"]["status"] == "aborted"


async def test_a_plain_task_is_still_stopped_and_requeued_as_b1060_built_it(factory):
    """Only a workflow run is parked, so only its reading changes: a task that
    is not a workflow is written `aborted` by the gate and re-queued."""
    from core.database import ScheduledTask

    inside, hold = asyncio.Event(), {"first": True}

    async def slow(task, run_id):
        if hold["first"]:
            hold["first"] = False
            inside.set()
            await asyncio.sleep(30)
        return "done"

    db = factory()
    db.add(ScheduledTask(id="plain", owner="alice", name="Plain", task_type="action",
                         action="tidy_sessions", status="active"))
    db.commit()
    db.close()
    s = recording_scheduler({"Plain": slow})
    assert await s.run_task_now("plain") is True
    await asyncio.wait_for(inside.wait(), timeout=5)
    await s.stop_background_tasks_for_foreground()
    [first] = runs_of(factory, "plain")
    assert first["status"] == "aborted" and first["error"] == FOREGROUND_TAKEOVER
    await settle(s)
    assert [r["status"] for r in runs_of(factory, "plain")] == ["aborted", "success"]


async def test_the_running_monitor_parks_the_step_too(factory, monkeypatch):
    """The other way a takeover lands: the run's own monitor sees foreground
    activity and cancels, with no gate call before it. The walker has to know
    it was a takeover to leave the step `waiting {idle}` — or the run is
    parked with a step that says `aborted`, waiting on nothing."""
    from src import interactive_gate as gate

    monkeypatch.setenv("BACKGROUND_TASK_FOREGROUND_GATE", "1")
    monkeypatch.setattr(gate, "_ACTIVE_REQUESTS", 0)
    monkeypatch.setattr(gate, "_LAST_ACTIVITY", 0.0)
    monkeypatch.setattr(gate, "_LAST_BROWSER_ACTIVITY", 0.0)
    monkeypatch.setattr(gate, "_has_active_chat_stream", lambda: False)
    inside, hold = asyncio.Event(), {"first": True}
    s = _digest(factory, hold, inside)
    assert await s.run_task_now("wf") is True
    await asyncio.wait_for(inside.wait(), timeout=5)
    [run] = runs_of(factory, "wf")
    gate._ACTIVE_REQUESTS = 1                  # someone starts using Pantheon
    for _ in range(100):
        await asyncio.sleep(0.05)
        if runs_of(factory, "wf")[0]["status"] == "waiting":
            break
    gate._ACTIVE_REQUESTS = 0
    gate._LAST_ACTIVITY = 0.0
    await settle(s)
    [parked] = runs_of(factory, "wf")
    assert parked["status"] == "waiting" and parked["result"] == TAKEOVER_PARKED, parked
    by = {r["node_id"]: r for r in records_of(factory, run["id"])}
    assert by["fetch"]["status"] == "waiting" and by["fetch"]["waiting"]["kind"] == "idle", by["fetch"]
    assert all(st != "aborted" for st, _ in _history(factory, run["id"]))

    assert await s._resume_due_waits() == 1
    await settle(s)
    assert runs_of(factory, "wf")[0]["status"] == "success"
