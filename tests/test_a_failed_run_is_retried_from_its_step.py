# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1854` — a failed run is retried from the step it failed on.

Measured before this row, on `ea80706`: the only way to try a failed run
again was *Run now*, which ran every step again — a step that had worked and
sent its mail sent it twice. `POST /api/workflows/{id}/runs/{run_id}/retry`
makes a NEW run of the version the failed run ran, keeps what it finished
before and beside the step (copied, each "Kept from the run at 10:42",
`kept_from` on its record), and runs that step and every step after it. Built
on the records the walker already reads as a run's state.

Driven through the real routes over the real scheduler (`walker_harness`):
only a step's far end is a recorder.
"""

import json

import pytest

from core.database import TaskRun, TaskRunNode
from tests.helpers.walker_harness import (
    app_for, arrow, client_for, make_db, node, recording_scheduler, records_of, row,
    runs_of, seed_workflow, settle,
)

ALICE = {"x-test-user": "alice"}


@pytest.fixture()
def factory(monkeypatch, tmp_path):
    return make_db(monkeypatch, tmp_path / "retry.db")


def _flaky(times=1, *, answer="Tidied."):
    """A far end that fails its first `times` calls, then works."""
    from src.builtin_actions import NodeResult
    calls = {"n": 0}

    async def far_end(task, run_id):
        calls["n"] += 1
        if calls["n"] <= times:
            return NodeResult("error", payload="The provider answered 503.")
        return NodeResult("success", payload=answer)
    return far_end


#  start → s (Set) → a (Tidy, flaky) → b (Tidy documents)
#  start → c (Mail it: a side effect on a branch beside it)
GRAPH = ([node("s", "Make it", "set", fields=[{"name": "n", "value": 3}]),
          node("a", "Tidy", "action", action="tidy_sessions"),
          node("b", "File it", "action", action="tidy_documents"),
          node("c", "Mail it", "action", action="tidy_research")],
         [arrow("start", "s"), arrow("s", "a"), arrow("a", "b"), arrow("start", "c")])


async def _failed_run(factory, s):
    await s._execute_task("wf")
    [run] = runs_of(factory, "wf")
    assert run["status"] == "error", run
    return run


@pytest.mark.asyncio
async def test_a_retry_runs_from_the_failed_step_and_keeps_what_worked(factory, monkeypatch):
    seed_workflow(factory, *GRAPH)
    s = recording_scheduler({"Morning digest · Tidy": _flaky()})
    failed = await _failed_run(factory, s)
    assert sorted(c["name"] for c in s.calls) == ["Morning digest · Mail it",
                                                  "Morning digest · Tidy"]
    s.calls.clear()
    async with client_for(app_for(factory, s, monkeypatch)) as client:
        res = await client.post(f"/api/workflows/w-wf/runs/{failed['id']}/retry", headers=ALICE)
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["ok"] is True and body["run_id"] != failed["id"]
        await settle(s)
        listed = (await client.get("/api/tasks/wf/runs", headers=ALICE)).json()["runs"]
        opened = (await client.get(f"/api/workflows/w-wf/runs/{body['run_id']}",
                                   headers=ALICE)).json()
    runs = {r["id"]: r for r in runs_of(factory, "wf")}
    again = runs[body["run_id"]]
    assert again["status"] == "success", again
    assert [c["name"] for c in s.calls] == ["Morning digest · Tidy", "Morning digest · File it"], (
        "only the failed step and the one after it ran; “Mail it” did not mail again")
    by = {r["node_id"]: r for r in records_of(factory, again["id"])}
    assert by["s"]["kept_from"] == failed["id"] and by["c"]["kept_from"] == failed["id"]
    assert by["s"]["output"]["data"] == {"n": 3}
    assert by["s"]["steps"][0]["detail"].startswith("Kept from the run at ")
    assert by["a"]["kept_from"] is None and by["a"]["status"] == "success"
    assert by["b"]["kept_from"] is None and by["b"]["status"] == "success"
    line = next(st for st in again["steps"] if st.get("retry_of"))
    assert line["retry_of"] == failed["id"] and line["retry_from"] == "a"
    assert line["detail"].startswith("Retry of the run at ") and line["detail"].endswith(
        "from “Tidy”")
    mine = next(r for r in listed if r["id"] == again["id"])
    assert mine["retry_of"] == failed["id"]
    assert next(r for r in listed if r["id"] == failed["id"])["retry_of"] is None
    assert {n["node_id"]: n["kept_from"] for n in opened["nodes"]}["c"] == failed["id"]
    # The failed run is as it was.
    assert runs[failed["id"]]["status"] == "error"


@pytest.mark.asyncio
async def test_a_retry_from_a_named_step_runs_it_and_what_follows(factory, monkeypatch):
    seed_workflow(factory, *GRAPH)
    s = recording_scheduler({"Morning digest · Tidy": _flaky()})
    failed = await _failed_run(factory, s)
    s.calls.clear()
    async with client_for(app_for(factory, s, monkeypatch)) as client:
        res = await client.post(f"/api/workflows/w-wf/runs/{failed['id']}/retry",
                                headers=ALICE, json={"node_id": "s"})
        assert res.status_code == 200, res.text
        await settle(s)
    again = next(r for r in runs_of(factory, "wf") if r["id"] == res.json()["run_id"])
    by = {r["node_id"]: r for r in records_of(factory, again["id"])}
    assert by["s"]["kept_from"] is None and by["c"]["kept_from"] == failed["id"]
    assert [c["name"] for c in s.calls] == ["Morning digest · Tidy", "Morning digest · File it"]


@pytest.mark.asyncio
async def test_a_retry_is_refused_with_why(factory, monkeypatch):
    seed_workflow(factory, *GRAPH)
    s = recording_scheduler({"Morning digest · Tidy": _flaky(times=99)})
    failed = await _failed_run(factory, s)
    s2 = recording_scheduler()
    async with client_for(app_for(factory, s2, monkeypatch)) as client:
        url = f"/api/workflows/w-wf/runs/{failed['id']}/retry"
        nowhere = await client.post(url, headers=ALICE, json={"node_id": "zz"})
        assert nowhere.status_code == 400
        assert nowhere.json()["detail"] == "“zz” is not a step of the version this run ran."
        bob = await client.post(url, headers={"x-test-user": "bob"})
        assert bob.status_code == 404
        await client.post("/api/tasks/wf/run", headers=ALICE)        # a run that works
        await settle(s2)
        worked = next(r for r in runs_of(factory, "wf") if r["status"] == "success")
        ok = await client.post(f"/api/workflows/w-wf/runs/{worked['id']}/retry", headers=ALICE)
        assert ok.status_code == 400
        assert ok.json()["detail"] == "This run did not fail, so there is nothing to retry."
        # The version it ran is gone: a retry never runs an edit made since.
        db = factory()
        for rec in db.query(TaskRunNode).filter(TaskRunNode.run_id == failed["id"]).all():
            rec.workflow_version = 2
        db.commit()
        db.close()
        gone = await client.post(url, headers=ALICE)
        assert gone.status_code == 400
        assert gone.json()["detail"] == (
            "This run ran version 2 of the workflow, which is no longer kept, so it cannot be "
            "retried from a step. Run the workflow again instead.")
    assert len(runs_of(factory, "wf")) == 2, "no refusal wrote a run"


@pytest.mark.asyncio
async def test_a_retry_waits_its_turn_and_writes_nothing_when_it_cannot_start(
        factory, monkeypatch):
    seed_workflow(factory, [
        node("a", "Tidy", "action", action="tidy_sessions"),
        node("w", "Wait a minute", "wait", mode="for", minutes=1),
    ], [arrow("start", "a"), arrow("start", "w")])
    s = recording_scheduler({"Morning digest · Tidy": _flaky()})
    await s._execute_task("wf")
    [parked] = runs_of(factory, "wf")
    assert parked["status"] == "waiting"
    db = factory()
    db.query(TaskRun).filter(TaskRun.id == parked["id"]).first().status = "waiting"
    db.commit()
    db.close()
    # A second, failed run of the same workflow, to retry while the first waits.
    db = factory()
    db.add(TaskRun(id="old", task_id="wf", status="error", error="Tidy failed",
                   steps=json.dumps([])))
    db.commit()
    db.close()
    from src import workflow_runs as wr
    db = factory()
    rec = wr.record_node_start(db, run_id="old", node={"id": "a", "kind": "action",
                                                       "label": "Tidy"}, seq=1,
                               input_envelope=None, workflow_version=3)
    wr.record_node_end(db, rec, status="error", text="Down.", error="Down.", port="error")
    db.close()
    async with client_for(app_for(factory, s, monkeypatch)) as client:
        res = await client.post("/api/workflows/w-wf/runs/old/retry", headers=ALICE)
    assert res.status_code == 409, res.text
    assert res.json()["detail"].startswith("Did not start: the ")
    assert len(runs_of(factory, "wf")) == 2, "no row"


@pytest.mark.asyncio
async def test_a_switched_off_workflows_run_is_not_retried_but_a_test_run_is(
        factory, monkeypatch):
    seed_workflow(factory, *GRAPH, status="paused")
    s = recording_scheduler({"Morning digest · Tidy": _flaky()})
    async with client_for(app_for(factory, s, monkeypatch)) as client:
        tried = await client.post("/api/workflows/w-wf/test-run", headers=ALICE)
        await settle(s)
        test_run = tried.json()["run_id"]
        assert next(r for r in runs_of(factory, "wf") if r["id"] == test_run)["status"] == "error"
        res = await client.post(f"/api/workflows/w-wf/runs/{test_run}/retry", headers=ALICE)
        assert res.status_code == 200, res.text
        await settle(s)
        listed = (await client.get("/api/tasks/wf/runs", headers=ALICE)).json()["runs"]
        # A real failed run of the workflow while it is off is not retried.
        db = factory()
        db.add(TaskRun(id="real", task_id="wf", status="error", steps=json.dumps([])))
        db.commit()
        db.close()
        off = await client.post("/api/workflows/w-wf/runs/real/retry", headers=ALICE)
    retried = next(r for r in listed if r["id"] == res.json()["run_id"])
    assert retried["status"] == "success" and retried["test"] is True
    assert retried["retry_of"] == test_run
    assert row(factory, "wf").status == "paused" and row(factory, "wf").next_run is None
    assert off.status_code == 409
    assert off.json()["detail"] == ("The workflow is switched off, so this run is not "
                                    "retried. Switch it on, or use Test run.")


@pytest.mark.asyncio
async def test_a_webhooks_retry_is_handed_what_started_the_failed_run(factory, monkeypatch):
    seed_workflow(factory, [node("a", "Tidy", "action", action="tidy_sessions")],
                  [arrow("start", "a")], trigger_type="webhook", webhook_token="tok",
                  schedule=None)
    s = recording_scheduler({"Morning digest · Tidy": _flaky()})
    async with client_for(app_for(factory, s, monkeypatch)) as client:
        hook = await client.post("/api/tasks/wf/webhook/tok", json={"issue": 7})
        await settle(s)
        res = await client.post(f"/api/workflows/w-wf/runs/{hook.json()['run_id']}/retry",
                                headers=ALICE)
        assert res.status_code == 200, res.text
        await settle(s)
    first, second = s.calls[0]["trigger"], s.calls[-1]["trigger"]
    assert len(s.calls) == 2 and second["data"] == first["data"]
    assert second["data"]["json"] == {"issue": 7}


@pytest.mark.asyncio
async def test_a_for_each_retried_keeps_the_items_that_worked(factory, monkeypatch):
    tries = {}

    async def far_end(task, run_id):
        tries[task.name] = tries.get(task.name, 0) + 1
        if "item 2 of 3" in task.name and tries[task.name] == 1:
            raise RuntimeError("the model refused")
        return "done"
    seed_workflow(factory, [
        node("fetch", "Fetch", "set", fields=[{"name": "items", "value": [1, 2, 3]}]),
        node("each", "For each", "foreach", list="{{ steps.fetch.data.items }}",
             step={"kind": "llm", "label": "Summarise", "config": {"prompt": "Sum."}}),
    ], [arrow("start", "fetch"), arrow("fetch", "each")])
    s = recording_scheduler({f"Morning digest · Summarise · item {i} of 3": far_end
                             for i in (1, 2, 3)})
    failed = await _failed_run(factory, s)
    s.calls.clear()
    async with client_for(app_for(factory, s, monkeypatch)) as client:
        res = await client.post(f"/api/workflows/w-wf/runs/{failed['id']}/retry", headers=ALICE)
        assert res.status_code == 200, res.text
        await settle(s)
    again = next(r for r in runs_of(factory, "wf") if r["id"] == res.json()["run_id"])
    assert again["status"] == "success", again
    assert [c["name"] for c in s.calls] == ["Morning digest · Summarise · item 2 of 3"]
    items = {r["item"]: r for r in records_of(factory, again["id"]) if r["item"] is not None}
    assert items[0]["kept_from"] == failed["id"] and items[2]["kept_from"] == failed["id"]
    assert items[1]["kept_from"] is None and items[1]["status"] == "success"


def test_workflow_api_retry_run_posts_its_route(tmp_path):
    """The route's caller (`Law 13`): `retryRun` sends exactly the route."""
    import shutil
    import subprocess
    from pathlib import Path
    if not shutil.which("node"):
        pytest.skip("node binary not on PATH")
    js = Path(__file__).resolve().parents[1] / "static" / "js" / "workbench"
    for name in ("workflowApi.js", "refusal.js"):
        shutil.copy(js / name, tmp_path / name)
    (tmp_path / "run.mjs").write_text("""
const { createWorkflowApi } = await import('./workflowApi.js');
const sent = [];
const net = async (url, init) => { sent.push([init.method, url, init.body ?? null]);
  return { ok: true, status: 200, json: async () => ({ ok: true, run_id: 'r2' }) }; };
const api = createWorkflowApi({ fetch: net });
await api.retryRun('w 1', 'r 1');
const got = await api.retryRun('w1', 'r1', 'send-it');
console.log(JSON.stringify({ sent, got }));
""", encoding="utf-8")
    out = subprocess.run(["node", str(tmp_path / "run.mjs")], capture_output=True, text=True,
                         timeout=60, cwd=tmp_path)
    assert out.returncode == 0, out.stderr
    data = json.loads(out.stdout.strip().splitlines()[-1])
    assert data["sent"] == [["POST", "/api/workflows/w%201/runs/r%201/retry", None],
                            ["POST", "/api/workflows/w1/runs/r1/retry",
                             json.dumps({"node_id": "send-it"}, separators=(",", ":"))]]
    assert data["got"] == {"ok": True, "run_id": "r2"}
