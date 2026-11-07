# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1852` — a person can try a workflow without switching it on.

Measured before this row, on `ea80706`: *Run now* on a switched-off workflow is
recorded `skipped` — "Task no longer active (status=paused)" — so trying what
you built meant switching it on, which arms its schedule, its event or its
webhook. `POST /api/workflows/{id}/test-run` runs the SAVED version once, as
the person's run, while it is off; the run is in the Runs list marked a test
("Test run" is its cause line, `run.test` is true), its Wait goes on while it
is off, and nothing about when the workflow runs moves.

Driven through the real routes over the real scheduler (`walker_harness`):
only the far end of an Action step is a recorder.
"""

import json
from datetime import datetime, timedelta

import pytest

from core.database import ScheduledTask, TaskRun
from tests.helpers.walker_harness import (
    app_for, arrow, client_for, make_db, node, records_of, recording_scheduler, row,
    runs_of, seed_workflow, settle, skip_ahead,
)

pytestmark = pytest.mark.asyncio

ALICE = {"x-test-user": "alice"}
SET_THEN_ACT = ([node("s", "Make it", "set", fields=[{"name": "n", "value": 3}]),
                 node("a", "Tidy", "action", action="tidy_sessions")],
                [arrow("start", "s"), arrow("s", "a")])
WAIT_THEN_ACT = ([node("w", "Wait a minute", "wait", mode="for", minutes=1),
                  node("a", "Tidy", "action", action="tidy_sessions")],
                 [arrow("start", "w"), arrow("w", "a")])


@pytest.fixture()
def factory(monkeypatch, tmp_path):
    return make_db(monkeypatch, tmp_path / "test-run.db")


async def test_run_now_on_a_switched_off_workflow_is_still_skipped(factory, monkeypatch):
    """The premise, kept (`Law 1`): *Run now* honours the switch."""
    seed_workflow(factory, *SET_THEN_ACT, status="paused")
    s = recording_scheduler()
    async with client_for(app_for(factory, s, monkeypatch)) as client:
        res = await client.post("/api/tasks/wf/run", headers=ALICE)
        assert res.status_code == 200, res.text
        await settle(s)
    [run] = runs_of(factory, "wf")
    assert run["status"] == "skipped"
    assert run["error"] == "Task no longer active (status=paused)"
    assert s.calls == []


async def test_a_test_run_runs_the_switched_off_workflow_and_moves_nothing(factory, monkeypatch):
    seed_workflow(factory, *SET_THEN_ACT, status="paused")
    before = row(factory, "wf")
    s = recording_scheduler()
    async with client_for(app_for(factory, s, monkeypatch)) as client:
        res = await client.post("/api/workflows/w-wf/test-run", headers=ALICE)
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["ok"] is True and isinstance(body["run_id"], str)
        # The row is written before the reply: the page can open it at once.
        opened = await client.get(f"/api/workflows/w-wf/runs/{body['run_id']}", headers=ALICE)
        assert opened.status_code == 200, opened.text
        await settle(s)
        done = (await client.get(f"/api/workflows/w-wf/runs/{body['run_id']}",
                                 headers=ALICE)).json()
        listed = (await client.get("/api/tasks/wf/runs", headers=ALICE)).json()["runs"]
    [run] = runs_of(factory, "wf")
    assert run["id"] == body["run_id"]
    assert run["status"] == "success", run
    assert [c["name"] for c in s.calls] == ["Morning digest · Tidy"], "it ran, switched off"
    cause = run["steps"][0]
    assert cause["kind"] == "trigger" and cause["detail"] == "Test run" and cause["test_run"] is True
    assert done["run"]["test"] is True and listed[0]["test"] is True
    first = next(r for r in records_of(factory, run["id"]) if r["node_id"] == "s")
    assert first["input"]["source"] == "test" and first["input_summary"] == "Test run"
    after = row(factory, "wf")
    assert after.status == "paused", "the switch is not touched"
    assert after.next_run == before.next_run is None, "nor its next run"


async def test_a_test_run_of_a_switched_on_one_off_leaves_its_schedule_alone(factory, monkeypatch):
    """A one-off whose date has passed is `completed` by its last real run;
    a test run of it changes neither that nor the time it is set for."""
    past = datetime(2020, 1, 1, 8, 0)
    seed_workflow(factory, *SET_THEN_ACT, schedule="once", scheduled_date=past,
                  next_run=past + timedelta(days=9000))
    s = recording_scheduler()
    async with client_for(app_for(factory, s, monkeypatch)) as client:
        res = await client.post("/api/workflows/w-wf/test-run", headers=ALICE)
        assert res.status_code == 200, res.text
        await settle(s)
    assert runs_of(factory, "wf")[0]["status"] == "success"
    task = row(factory, "wf")
    assert task.status == "active", "not completed by a test"
    assert task.next_run == past + timedelta(days=9000)


async def test_a_failed_test_run_plans_no_retry_and_is_no_rung_of_the_ladder(factory, monkeypatch):
    from src.builtin_actions import NodeResult
    from src.task_scheduler import consecutive_failures
    seed_workflow(factory, *SET_THEN_ACT, trigger_type="webhook", webhook_token="tok",
                  max_retries=3, schedule=None)
    s = recording_scheduler({"Morning digest · Tidy": NodeResult("error", payload="it broke")})
    async with client_for(app_for(factory, s, monkeypatch)) as client:
        for _ in range(2):
            res = await client.post("/api/workflows/w-wf/test-run", headers=ALICE)
            assert res.status_code == 200, res.text
            await settle(s)
    runs = runs_of(factory, "wf")
    assert [r["status"] for r in runs] == ["error", "error"]
    assert not any("retrying" in (st.get("detail") or "") for r in runs for st in r["steps"])
    assert not getattr(s, "_pending_retries", None), "no retry is armed"
    db = factory()
    try:
        assert consecutive_failures(db, "wf") == 0, "a test run is not a real failure"
    finally:
        db.close()
    assert row(factory, "wf").next_run is None


async def test_a_test_runs_wait_goes_on_while_the_workflow_is_off(factory, monkeypatch):
    """The resume path ends a waiting run of a switched-off workflow "Switched
    off while it waited" — but not a test run's, which goes on as the
    person's run it is."""
    seed_workflow(factory, *WAIT_THEN_ACT, status="paused")
    s = recording_scheduler()
    async with client_for(app_for(factory, s, monkeypatch)) as client:
        res = await client.post("/api/workflows/w-wf/test-run", headers=ALICE)
        assert res.status_code == 200, res.text
        await settle(s)
        [run] = runs_of(factory, "wf")
        assert run["status"] == "waiting", run
        # One run at a time (`B674`): a second try is the person's 409 in Run
        # now's words, and writes nothing.
        again = await client.post("/api/workflows/w-wf/test-run", headers=ALICE)
        assert [r["status"] for r in runs_of(factory, "wf")] == ["waiting"], "no row"
        assert row(factory, "wf").next_run is None, "and no next time"
        run_now = await client.post("/api/tasks/wf/run", headers=ALICE)
        assert again.status_code == 409, again.text
        assert again.json()["detail"].startswith("Did not start: the ")
        assert "waiting until" in again.json()["detail"]
        assert run_now.json()["detail"] == again.json()["detail"]
    statuses = [r["status"] for r in runs_of(factory, "wf")]
    assert statuses == ["waiting", "skipped"], "the test's 409 wrote no row; Run now's did"
    resumed_as = []
    real_resume = s.resume_workflow_run

    async def watch(run_id, **kw):
        resumed_as.append(kw.get("started_by"))
        return await real_resume(run_id, **kw)
    s.resume_workflow_run = watch
    skip_ahead(monkeypatch, 61)
    assert await s._resume_due_waits() == 1
    await settle(s)
    run = runs_of(factory, "wf")[0]
    assert run["status"] == "success", run
    assert run["error"] != "Switched off while it waited"
    assert resumed_as == ["person"]
    assert [c["name"] for c in s.calls] == ["Morning digest · Tidy"]
    assert row(factory, "wf").status == "paused"


async def test_a_real_runs_wait_still_ends_when_its_workflow_is_switched_off(factory, monkeypatch):
    seed_workflow(factory, *WAIT_THEN_ACT)
    s = recording_scheduler()
    await s._execute_task("wf")
    db = factory()
    db.query(ScheduledTask).filter(ScheduledTask.id == "wf").first().status = "paused"
    db.commit()
    db.close()
    assert await s._resume_due_waits() == 1
    await settle(s)
    [run] = runs_of(factory, "wf")
    assert run["status"] == "aborted" and run["error"] == "Switched off while it waited"


async def test_a_test_run_is_owner_scoped(factory, monkeypatch):
    seed_workflow(factory, *SET_THEN_ACT, status="paused")
    s = recording_scheduler()
    async with client_for(app_for(factory, s, monkeypatch)) as client:
        res = await client.post("/api/workflows/w-wf/test-run", headers={"x-test-user": "bob"})
    assert res.status_code == 404, res.text
    db = factory()
    try:
        assert db.query(TaskRun).count() == 0
    finally:
        db.close()


def test_a_test_runs_envelope_is_nothing_anybody_wrote():
    """A model step of a test run is handed no untrusted block: the envelope
    is the server's own, with no data (`trigger_context_message`)."""
    from src.event_bus import (
        build_test_trigger, build_trigger, trigger_context_message, trigger_summary,
    )
    env = build_test_trigger()
    assert env["source"] == "test" and env["event"] == "test_run" and env["data"] == {}
    assert trigger_summary(env) == "Test run"
    assert trigger_context_message(env) is None
    # A webhook's envelope is still wrapped, whatever its body says.
    hook = build_trigger("webhook", "webhook", {"json": {"source": "test"}},
                         fields=("json",))
    assert trigger_context_message(hook) is not None


def test_workflow_api_test_run_posts_its_route(tmp_path):
    """The route's caller (`Law 13`): `testRun` sends exactly the route."""
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
  return { ok: true, status: 200, json: async () => ({ ok: true, run_id: 'r1' }) }; };
const api = createWorkflowApi({ fetch: net });
const got = await api.testRun('w 1');
console.log(JSON.stringify({ sent, got }));
""", encoding="utf-8")
    out = subprocess.run(["node", str(tmp_path / "run.mjs")], capture_output=True, text=True,
                         timeout=60, cwd=tmp_path)
    assert out.returncode == 0, out.stderr
    data = json.loads(out.stdout.strip().splitlines()[-1])
    assert data["sent"] == [["POST", "/api/workflows/w%201/test-run", None]]
    assert data["got"] == {"ok": True, "run_id": "r1"}
