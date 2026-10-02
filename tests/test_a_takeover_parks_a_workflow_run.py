# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P22-11` (`SLICE-CD-DESIGN` § 1.4) — a foreground takeover PARKS a workflow
run instead of re-queueing it.

`B1060` re-queues a stopped background run with its trigger, which for a
workflow meant a NEW run that started again from step one — so a step that had
already posted something posted it twice. Now the step the takeover stopped is
`waiting {kind: idle}`, the finished steps are kept, and only the interrupted
step runs again once Pantheon is idle: one durable mechanism, the same records.
Driven through the real gate (`stop_background_tasks_for_foreground`) and the
real sweeper.
"""

import asyncio

import pytest

from src.task_scheduler import TAKEOVER_PARKED
from tests.helpers.walker_harness import (
    arrow, make_db, node, records_of, recording_scheduler, runs_of, seed_workflow, settle,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture()
def factory(monkeypatch, tmp_path):
    return make_db(monkeypatch, tmp_path / "takeover.db")


async def test_a_takeover_parks_the_run_and_only_the_interrupted_step_runs_again(factory):
    inside = asyncio.Event()
    hold = {"first": True}

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
    s = recording_scheduler({"Morning digest · Post": post, "Morning digest · Fetch": slow})
    assert await s.run_task_now("wf") is True
    await asyncio.wait_for(inside.wait(), timeout=5)
    assert await s.stop_background_tasks_for_foreground() >= 1
    await settle(s)

    runs = runs_of(factory, "wf")
    assert len(runs) == 1, "parked, not a second run started from step one"
    run = runs[0]
    assert run["status"] == "waiting" and run["result"] == TAKEOVER_PARKED
    by = {r["node_id"]: r for r in records_of(factory, run["id"])}
    assert by["post"]["status"] == "success"
    assert by["fetch"]["status"] == "waiting" and by["fetch"]["waiting"]["kind"] == "idle"
    assert "brief" not in by

    # Pantheon is idle again: the sweeper goes on from the interrupted step.
    assert await s._resume_due_waits() == 1
    await settle(s)
    [run] = runs_of(factory, "wf")
    assert run["status"] == "success", run
    names = [c["name"] for c in s.calls]
    assert names.count("Morning digest · Post") == 1, "the finished post was not sent twice"
    assert names.count("Morning digest · Fetch") == 2, "only the interrupted step ran again"
    assert names.count("Morning digest · Brief") == 1
    by = {r["node_id"]: r for r in records_of(factory, run["id"])}
    assert by["fetch"]["attempt"] == 2 and by["fetch"]["status"] == "success"
    assert any("runs again" in (st.get("detail") or "") for st in run["steps"])


async def test_a_plain_task_keeps_b1060s_requeue(factory):
    """`Law 1`: a task that is not a workflow is still re-queued with its
    trigger, exactly as `B1060` built it."""
    from core.database import ScheduledTask
    inside = asyncio.Event()
    hold = {"first": True}

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
    await settle(s)
    statuses = [r["status"] for r in runs_of(factory, "plain")]
    assert statuses == ["aborted", "success"], statuses
