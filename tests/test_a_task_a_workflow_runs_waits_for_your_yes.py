# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1173` — a plain task that a workflow's *Run task* step runs waits for the
person's yes on its card, as the same task run by itself does (`B1102`), and
the answer resumes the task and then the workflow, once.

**Measured before this file** (`test_a_plain_task_run_by_a_workflow_step_
still_pauses_safely`, which pinned it): the target ran awaited
(`register_handle=False` → `may_wait=False`), so its card was consumed as a
denial on the spot — "Scheduled task paused safely: bash needs a person to
approve its next action" — the step read that as a finished run and the
workflow went on as if it had worked. Nothing was offered to the person.

Now the target's run parks, HELD by the workflow run (its waiting record says
which, so it asks nobody, the sweeper leaves it to its holder, and the task's
own answer door sends the person to the workflow); the *Run task* step parks
on the same card, so the person is asked once — by the workflow, from its
notification; Allow resumes the step, which resumes the target's parked run
with the answer (the sealed action runs once), and the workflow goes on. Deny,
a lapse, a restart, a Stop or a switch-off end the target's held run with the
step, in the same words.

Everything that decides is real (`Law 20`): the real scheduler and walker, the
real agent loop (only the model's words are scripted), the real gate and
approval store, the real routes over httpx's ASGI transport; the far end of a
tool is the one recorder. The world is `test_a_plain_task_waits_for_your_yes`'s.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.task_scheduler import STOPPED_BY_USER, TaskScheduler  # noqa: E402
from src.tool_approvals import tool_approval_store  # noqa: E402
from tests.helpers.walker_harness import (  # noqa: E402
    client_for, node, records_of, runs_of, seed_workflow, settle,
)
from test_a_plain_task_waits_for_your_yes import (  # noqa: E402,F401
    ALICE, _plain_task, _webhook, world,
)

pytestmark = pytest.mark.asyncio


async def _park(w):
    """A workflow ("Morning digest") whose one step runs the plain task
    "Morning replies", whose model's first move is a gated `bash`."""
    _plain_task(w)
    seed_workflow(w.factory, [node("go", "Run replies", "run_task", task_id="plain")])
    w.script.append("```bash\nprintf reply-sent\n```")
    await w.s._execute_task("wf", trigger=_webhook())
    [outer] = runs_of(w.factory, "wf")
    [inner] = runs_of(w.factory, "plain")
    by = {r["node_id"]: r for r in records_of(w.factory, outer["id"])}
    [held] = records_of(w.factory, inner["id"])
    return outer, inner, by["go"], held


def _answer(outer, step, decision):
    return (f"/api/workflows/w-wf/runs/{outer['id']}/answer",
            {"node_id": "go", "approval_id": step["waiting"]["approval"]["approval_id"],
             "decision": decision})


async def test_the_step_parks_on_its_tasks_card_and_allow_resumes_both_once(world):
    """The row's `Verify:` — the workflow parks, the person answers from the
    notification, and Allow resumes the task and then the workflow, once."""
    w = world
    outer, inner, step, held = await _park(w)
    assert inner["status"] == "waiting", inner
    assert not inner["result"].startswith("Scheduled task paused safely"), "denied on the spot"
    assert outer["status"] == "waiting", outer
    assert step["status"] == "waiting" and step["waiting"]["kind"] == "approval"
    card = step["waiting"]["approval"]
    assert card["action"]["tool"] == "bash" and card["gate"]["tainted"] is True
    assert held["waiting"]["approval"]["approval_id"] == card["approval_id"], "one card, two records"
    assert tool_approval_store.peek(card["approval_id"]) is not None
    assert w.executed == [], "nothing ran before the yes"
    # Asked once, by the workflow — not a second time by the task it ran.
    asked = [n for n in w.s.pop_notifications() if n["status"] == "waiting"]
    assert [n["review"]["kind"] for n in asked] == ["workflow_approval"], asked
    assert asked[0]["review"]["node_id"] == "go" and asked[0]["review"]["approval"] == card

    async with client_for(w.app) as client:
        assert (await client.get("/api/tasks/waiting", headers=ALICE)).json()["waiting"] == [], \
            "the task's own list offered the workflow's question"
        by_task = await client.post(f"/api/tasks/plain/runs/{inner['id']}/answer", headers=ALICE,
                                    json={"approval_id": card["approval_id"],
                                          "decision": "approve_task"})
        assert by_task.status_code == 409
        assert "Morning digest" in by_task.json()["detail"], by_task.json()
        assert tool_approval_store.peek(card["approval_id"]) is not None, "…and consumed nothing"
        url, body = _answer(outer, step, "approve_task")
        res = await client.post(url, headers=ALICE, json=body)
        assert res.status_code == 200, res.text
        assert res.json()["outcome"] == "resumed"
        await settle(w.s)

    assert w.executed == [("bash", "printf reply-sent")], "the sealed action ran exactly once"
    [inner] = runs_of(w.factory, "plain")
    assert inner["status"] == "success", inner
    [outer] = runs_of(w.factory, "wf")
    assert outer["status"] == "success", outer
    by = {r["node_id"]: r for r in records_of(w.factory, outer["id"])}
    assert by["go"]["status"] == "success" and by["go"]["attempt"] == 2
    assert tool_approval_store.peek(card["approval_id"]) is None, "single use"


async def test_deny_takes_the_steps_failure_path_and_ends_the_task_saying_so(world):
    w = world
    outer, inner, step, _held = await _park(w)
    async with client_for(w.app) as client:
        url, body = _answer(outer, step, "deny")
        res = await client.post(url, headers=ALICE, json=body)
        assert res.status_code == 200 and res.json()["outcome"] == "denied"
        await settle(w.s)
    assert w.executed == []
    [outer] = runs_of(w.factory, "wf")
    assert outer["status"] == "error"
    by = {r["node_id"]: r for r in records_of(w.factory, outer["id"])}
    assert by["go"]["status"] == "error" and by["go"]["port"] == "error"
    [inner] = runs_of(w.factory, "plain")
    assert inner["status"] == "error", "the task's held run waited on for ever"
    assert inner["error"].startswith("Denied by alice at ") and inner["error"] == by["go"]["error"]


async def test_stop_on_the_workflow_ends_the_task_it_was_waiting_on(world):
    w = world
    outer, inner, step, _held = await _park(w)
    approval_id = step["waiting"]["approval"]["approval_id"]
    assert await w.s.stop_task("wf") is True
    [outer] = runs_of(w.factory, "wf")
    assert (outer["status"], outer["error"]) == ("aborted", STOPPED_BY_USER)
    [inner] = runs_of(w.factory, "plain")
    assert inner["status"] == "aborted"
    assert inner["error"] == "Stopped: the workflow “Morning digest” that was waiting on it ended"
    assert tool_approval_store.peek(approval_id) is None


async def test_after_a_restart_the_workflow_says_so_and_the_task_ends_with_it(world):
    """The sweeper leaves the held run to its holder: only the workflow is
    resumed, and its step's verdict ends the task's run too."""
    w = world
    await _park(w)
    tool_approval_store._pending.clear()          # the old process's memory
    second = TaskScheduler(None)
    second._log_to_assistant = lambda *a, **k: None
    second._sweep_runs_left_by_a_restart()
    assert await second._resume_due_waits() == 1, "the held run was resumed on its own"
    await settle(second)
    [outer] = runs_of(w.factory, "wf")
    assert outer["status"] == "error"
    [inner] = runs_of(w.factory, "plain")
    assert inner["status"] == "error"
    assert inner["error"] == "Pantheon restarted before you answered — bash was not done."
    assert w.executed == []


async def test_testing_the_step_still_cannot_wait(world):
    """A step test never parks (`P22-08`): the task it runs keeps the card
    denied on the spot, and the test says what it did."""
    w = world
    _plain_task(w)
    seed_workflow(w.factory, [node("go", "Run replies", "run_task", task_id="plain")])
    w.script.append("```bash\nprintf nested\n```")
    from core.database import ScheduledTask
    db = w.factory()
    trigger = db.query(ScheduledTask).filter(ScheduledTask.id == "wf").first()
    db.close()
    out = await w.s.test_workflow_node(trigger, "Morning digest",
                                       node("go", "Run replies", "run_task", task_id="plain"),
                                       input_envelope=_webhook())
    assert out["status"] == "success", out
    [inner] = runs_of(w.factory, "plain")
    assert inner["status"] == "success"
    assert inner["result"].startswith("Scheduled task paused safely: bash needs a person")
    assert not tool_approval_store._pending and w.executed == []
    assert json.dumps(runs_of(w.factory, "wf")) == "[]"
