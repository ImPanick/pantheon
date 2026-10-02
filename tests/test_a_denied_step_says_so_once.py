# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1110` — a step's answer is said once in the run's log and once in the
step's own.

Measured by `integrate-d` (P22-17's deny) and again here on `7a7f9b2`: after
a Deny the run's log read "Resumed: Denied by alice at 22:13: bash — it was
not done.", then "Denied by alice …" as a line of its own, then the step's
end line "Send reply — error: Denied by alice …" — the same sentence three
times. The resume line said the answer whatever it was; `_apply_resume` said
it again; the step's end line is where the run's log says how a step ended.
Now the run's log names the answer at "Resumed" only when it lets the step run
again (Allow), and a denial, a lapse or a withdrawn question is said by the
step's end line; the step's own log keeps its one line.

Driven (`Law 20`): the real scheduler, walker, agent loop (the model's words
scripted), approval store and answer route, on a real SQLite file — the
`world` of `test_a_step_that_needs_a_yes_waits_for_it`.
"""
import time
from datetime import timedelta

import pytest

from src.builtin_actions import TaskWaiting
from src.tool_approvals import tool_approval_store
from tests.helpers.walker_harness import (
    app_for, arrow, client_for, make_db, node, records_of, recording_scheduler, runs_of,
    seed_workflow, settle,
)
from tests.test_a_step_that_needs_a_yes_waits_for_it import _park, _reply_workflow, world  # noqa: F401

pytestmark = pytest.mark.asyncio


def _said(log, sentence):
    """How many lines of a log carry `sentence` (in their detail)."""
    return sum(1 for s in log or () if sentence in str(s.get("detail") or ""))


async def _answer(w, run, rec, decision):
    async with client_for(w.app) as client:
        res = await client.post(f"/api/workflows/w-wf/runs/{run['id']}/answer",
                                headers={"x-test-user": "alice"},
                                json={"node_id": "reply", "item": None,
                                      "approval_id": rec["waiting"]["approval"]["approval_id"],
                                      "decision": decision})
    assert res.status_code == 200, res.text
    await settle(w.s)
    return res.json()["sentence"]


async def test_a_denial_is_said_once_on_the_run_and_once_on_the_step(world):
    w = world
    _reply_workflow(w)
    run, rec = await _park(w)
    sentence = await _answer(w, run, rec, "deny")
    assert sentence.startswith("Denied by alice at ")
    [run] = runs_of(w.factory, "wf")
    by = {r["node_id"]: r for r in records_of(w.factory, run["id"])}
    assert _said(run["steps"], sentence) == 1, run["steps"]
    [end] = [s for s in run["steps"] if s.get("node") == "reply" and s.get("status") == "error"]
    assert end["detail"] == sentence, "the run says it on the step's end line"
    assert any(s.get("detail") == "Resumed" for s in run["steps"]), "and that the run went on"
    assert _said(by["reply"]["steps"], sentence) == 1, "the step's own log says it once"
    assert by["reply"]["error"] == sentence and by["told"]["status"] == "success"


async def test_an_allow_is_said_once_on_the_run_and_once_on_the_step(world):
    w = world
    _reply_workflow(w)
    run, rec = await _park(w)
    sentence = await _answer(w, run, rec, "approve_task")
    assert sentence.startswith("Allowed once by alice at ")
    [run] = runs_of(w.factory, "wf")
    by = {r["node_id"]: r for r in records_of(w.factory, run["id"])}
    assert _said(run["steps"], sentence) == 1, run["steps"]
    assert any(s.get("detail") == f"Resumed: {sentence}" for s in run["steps"]), \
        "an Allow lets the step run again, so the run says who allowed it"
    assert _said(by["reply"]["steps"], sentence) == 1
    assert w.executed == [("bash", "printf reply-sent")]


async def test_a_lapse_is_said_once_on_the_run(world, monkeypatch):
    import src.task_scheduler as ts
    import src.tool_approvals as ta
    w = world
    _reply_workflow(w)
    run, rec = await _park(w)
    later = time.time() + 13 * 60 * 60
    monkeypatch.setattr(ta.time, "time", lambda: later)
    real_now = ts._utcnow
    monkeypatch.setattr(ts, "_utcnow", lambda: real_now() + timedelta(hours=13))
    assert await w.s._resume_due_waits() == 1
    await settle(w.s)
    [run] = runs_of(w.factory, "wf")
    by = {r["node_id"]: r for r in records_of(w.factory, run["id"])}
    sentence = by["reply"]["error"]
    assert sentence.startswith("Nobody answered by ")
    assert _said(run["steps"], sentence) == 1, run["steps"]
    assert _said(by["reply"]["steps"], sentence) == 1


async def test_a_denied_item_is_said_once_on_the_run(monkeypatch, tmp_path):
    """A For-each's item: the run's log says the denial once (in the step's
    end line), the For-each step's log once, and the item's record carries it."""
    from src.tool_capabilities import capabilities_for_action

    factory = make_db(monkeypatch, tmp_path / "each.db")

    async def needs_a_yes(task, run_id):
        pending = tool_approval_store.create(
            owner="alice", session_id="", origin_run_id=run_id, tool_name="bash",
            content="printf one", workspace=None, external_untrusted_context_seen=True,
            capabilities=capabilities_for_action("bash", "printf one"))
        raise TaskWaiting("Waiting for your yes on bash", kind="approval",
                          approval_id=pending.approval_id, session_id="", tool="bash",
                          until=pending.expires_at, card=pending.public_payload())

    seed_workflow(factory, [
        node("fetch", "Fetch unread", "set", fields=[{"name": "emails", "value": ["one"]}]),
        node("each", "For each email", "foreach", list="{{ steps.fetch.data.emails }}",
             on_error="stop", step={"kind": "llm", "label": "Summarise",
                                    "config": {"prompt": "Summarise this email."}}),
    ], [arrow("fetch", "each")])
    s = recording_scheduler({"Morning digest · Summarise · item 1 of 1": needs_a_yes})
    await s._execute_task("wf")
    [run] = runs_of(factory, "wf")
    own = [r for r in records_of(factory, run["id"]) if r["node_id"] == "each" and r["item"] is None][0]
    async with client_for(app_for(factory, s, monkeypatch)) as client:
        res = await client.post(f"/api/workflows/w-wf/runs/{run['id']}/answer",
                                headers={"x-test-user": "alice"},
                                json={"node_id": "each", "item": 0, "decision": "deny",
                                      "approval_id": own["waiting"]["approval"]["approval_id"]})
    assert res.status_code == 200, res.text
    sentence = res.json()["sentence"]
    await settle(s)
    [run] = runs_of(factory, "wf")
    recs = records_of(factory, run["id"])
    each = [r for r in recs if r["node_id"] == "each" and r["item"] is None][0]
    [item] = [r for r in recs if r["item"] == 0]
    assert item["error"] == sentence
    assert _said(run["steps"], sentence) == 1, run["steps"]
    assert _said(each["steps"], sentence) == 1, each["steps"]
