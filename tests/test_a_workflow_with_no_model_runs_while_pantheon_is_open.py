# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1864` — the "Pantheon is busy" gate holds back model work, not a workflow
that uses no model, and machine traffic is not somebody using Pantheon.

Every background run waited for Pantheon to be idle before it started and was
parked by a takeover while it ran (`_execute_task`'s non-model branch still
waited, with the foreground monitor armed) — even a workflow of If, Set and
housekeeping steps that takes no model slot. And what counted as "somebody is
here" was any request not on a short passive list: an inbound webhook POST,
and the Workbench's own `GET /api/workflows` poll every 4 s while a run is in
flight — so an open Workbench held the run it was showing.

Now (a) a workflow whose document drives no model neither waits for idle nor
is stopped by foreground activity, and (b) the webhook route and the
Workbench's reads are passive. A run that uses a model keeps the gate exactly
as it was, and so does a task that is not a workflow (`Law 1`).

Driven through the real gate (`src.interactive_gate`, on, quiet window 0), the
real `TaskScheduler` from `run_task_now` down and a real SQLite file; the
middleware's two calls are made in its order (`_page_request`).
"""

import asyncio

import pytest

import src.interactive_gate as ig
from core.database import ScheduledTask
from src.task_scheduler import TAKEOVER_PARKED
from tests.helpers.walker_harness import (
    arrow, make_db, node, recording_scheduler, runs_of, seed_workflow,
)

IDLE_WAIT = "Queued — waiting for Pantheon to be idle…"


@pytest.fixture()
def factory(monkeypatch, tmp_path):
    return make_db(monkeypatch, tmp_path / "busy.db")


@pytest.fixture()
def gate(factory, monkeypatch):
    """The real gate, on (after `make_db` switched it off), from a clean slate."""
    monkeypatch.delenv("BACKGROUND_TASK_FOREGROUND_GATE", raising=False)
    monkeypatch.setenv("BACKGROUND_TASK_QUIET_MS", "0")
    monkeypatch.setenv("BACKGROUND_TASK_BROWSER_ACTIVE_SECONDS", "45")
    monkeypatch.setenv("BACKGROUND_TASK_MAX_WAIT_SECONDS", "0")
    for name, value in (("_ACTIVE_REQUESTS", 0), ("_LAST_ACTIVITY", 0.0),
                        ("_LAST_BROWSER_ACTIVITY", 0.0), ("_COND", None),
                        ("_COND_LOOP", None)):
        monkeypatch.setattr(ig, name, value)
    monkeypatch.setattr(ig, "_has_active_chat_stream", lambda: False)


async def _someone_is_here():
    """A person's heartbeat: a visible tab, a key, a pointer."""
    await ig.mark_browser_activity()


async def _page_request(scheduler, path="/api/email/accounts", method="GET"):
    """One request, as `_InteractiveActivityMiddleware` handles it: a
    tracked one stops background work and is tracked; a passive one is not."""
    if not ig.should_track_interactive_request(path, method):
        return False
    stop = asyncio.create_task(scheduler.stop_background_tasks_for_foreground(
        reason=f"foreground request {method} {path}"))
    async with ig.track_interactive_request(path, method):
        await asyncio.sleep(0)
    return await stop


async def _tab_closes():
    ig._LAST_BROWSER_ACTIVITY = 0.0
    async with ig.track_interactive_request("/api/x", "GET"):
        pass


async def _until(predicate, what, limit=400):
    for _ in range(limit):
        if predicate():
            return
        await asyncio.sleep(0.005)
    raise AssertionError(f"never happened: {what}")


def _held():
    inside, release = asyncio.Event(), asyncio.Event()

    async def step(task, run_id):
        inside.set()
        await asyncio.wait_for(release.wait(), timeout=5)
        return "tidied"
    return inside, release, step


NO_MODEL = ([node("route", "Is it big?", "if", join="all", conditions=[
                {"left": "{{ steps.start.data.json.n }}", "op": "greater_than", "right": "3"}]),
             node("tidy", "Tidy", "action", action="tidy_sessions")],
            [arrow("start", "route"), arrow("route", "tidy", "then"),
             arrow("route", "tidy", "otherwise")])


# ── (a) a workflow that uses no model ──────────────────────────────────────

@pytest.mark.asyncio
async def test_a_workflow_with_no_model_starts_at_once_while_somebody_is_here(factory, gate):
    seed_workflow(factory, *NO_MODEL, trigger_type="webhook")
    s = recording_scheduler()
    await _someone_is_here()
    assert ig.has_foreground_activity(), "the gate sees somebody"
    assert await s.run_task_now("wf") is True
    try:
        await _until(lambda: [r["status"] for r in runs_of(factory, "wf")] == ["success"],
                     "the workflow ran while Pantheon was in use")
    finally:
        await _tab_closes()
    [run] = runs_of(factory, "wf")
    assert not any("for Pantheon to be idle" in (st.get("detail") or "") for st in run["steps"])
    assert [c["name"] for c in s.calls] == ["Morning digest · Tidy"]


@pytest.mark.asyncio
async def test_somebody_arriving_does_not_stop_a_workflow_with_no_model(factory, gate):
    inside, release, step = _held()
    seed_workflow(factory, *NO_MODEL, trigger_type="webhook")
    s = recording_scheduler({"Morning digest · Tidy": step})
    assert await s.run_task_now("wf") is True
    await asyncio.wait_for(inside.wait(), timeout=5)
    assert await _page_request(s) == 0, "a person's request stopped nothing"
    await _someone_is_here()
    assert await s.stop_background_tasks_for_foreground(reason="browser heartbeat") == 0
    release.set()
    try:
        await _until(lambda: [r["status"] for r in runs_of(factory, "wf")] == ["success"],
                     "the run finished where it was")
    finally:
        await _tab_closes()
    assert [c["name"] for c in s.calls] == ["Morning digest · Tidy"], "the step ran once"


# ── the gate, exactly as it was, for everything else (`Law 1`) ─────────────

@pytest.mark.asyncio
async def test_a_workflow_with_a_model_step_still_waits_and_is_still_parked(factory, gate):
    inside, release, step = _held()
    seed_workflow(factory, [node("brief", "Brief me"),
                            node("tidy", "Tidy", "action", action="tidy_sessions")],
                  [arrow("start", "brief"), arrow("brief", "tidy")])
    s = recording_scheduler({"Morning digest · Brief me": step})
    await _someone_is_here()
    assert await s.run_task_now("wf") is True
    await _until(lambda: [r["result"] for r in runs_of(factory, "wf")] == [IDLE_WAIT],
                 "the run says it waits for Pantheon to be idle")
    await asyncio.sleep(0.05)
    assert s.calls == [], "nothing ran while somebody was here"
    await _tab_closes()
    await asyncio.wait_for(inside.wait(), timeout=5)
    assert await _page_request(s) >= 1, "somebody arriving stops a run that uses a model"
    await _until(lambda: [r["status"] for r in runs_of(factory, "wf")] == ["waiting"],
                 "the run was parked")
    assert runs_of(factory, "wf")[0]["result"] == TAKEOVER_PARKED
    release.set()
    await _tab_closes()


@pytest.mark.asyncio
async def test_a_housekeeping_task_that_is_not_a_workflow_still_waits(factory, gate):
    db = factory()
    db.add(ScheduledTask(id="tidy", owner="alice", name="Tidy", task_type="action",
                         action="tidy_sessions", trigger_type="webhook", status="active"))
    db.commit()
    db.close()
    s = recording_scheduler()
    await _someone_is_here()
    assert await s.run_task_now("tidy") is True
    await _until(lambda: [r["result"] for r in runs_of(factory, "tidy")] == [IDLE_WAIT],
                 "the task waits for Pantheon to be idle, as it always has")
    await asyncio.sleep(0.05)
    assert s.calls == []
    await _tab_closes()
    await _until(lambda: [r["status"] for r in runs_of(factory, "tidy")] == ["success"],
                 "it ran once Pantheon was idle")


# ── (b) machine traffic and the Workbench's reads ──────────────────────────

PASSIVE = [
    ("POST", "/api/tasks/t-1/webhook/tok-abc"),
    ("GET", "/api/workflows"),
    ("GET", "/api/workflows/w-1"),
    ("GET", "/api/workflows/w-1/runs/r-1"),
    ("GET", "/api/tasks/t-1/runs"),
]
A_PERSON = [
    ("POST", "/api/tasks/t-1/webhook-regenerate"),
    ("POST", "/api/workflows"),
    ("PUT", "/api/workflows/w-1"),
    ("DELETE", "/api/workflows/w-1"),
    ("POST", "/api/workflows/w-1/runs/r-1/answer"),
    ("POST", "/api/tasks/t-1/run"),
    ("GET", "/api/tasks"),
    ("GET", "/api/email/accounts"),
]


@pytest.mark.parametrize("method, path", PASSIVE)
def test_machine_traffic_and_the_workbenchs_reads_are_not_somebody(gate, method, path):
    assert ig.should_track_interactive_request(path, method) is False


@pytest.mark.parametrize("method, path", A_PERSON)
def test_a_persons_requests_still_are(gate, method, path):
    assert ig.should_track_interactive_request(path, method) is True


@pytest.mark.asyncio
async def test_an_inbound_webhook_or_a_workbench_poll_stops_nothing(factory, gate):
    """The middleware's own order, for a run that uses a model: a webhook POST
    and the Workbench's poll leave it running; a person's request stops it."""
    inside, release, step = _held()
    seed_workflow(factory, [node("brief", "Brief me")], [arrow("start", "brief")])
    s = recording_scheduler({"Morning digest · Brief me": step})
    assert await s.run_task_now("wf") is True
    await asyncio.wait_for(inside.wait(), timeout=5)
    assert await _page_request(s, "/api/tasks/other/webhook/tok", "POST") is False
    assert await _page_request(s, "/api/workflows", "GET") is False
    assert not ig.has_foreground_activity()
    assert [r["status"] for r in runs_of(factory, "wf")] == ["running"]
    assert await _page_request(s, "/api/email/accounts", "GET") >= 1
    await _until(lambda: [r["status"] for r in runs_of(factory, "wf")] == ["waiting"],
                 "a person's request still parks it")
    release.set()
    await _tab_closes()
