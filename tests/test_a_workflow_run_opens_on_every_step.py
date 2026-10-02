# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P22-07`'s API half — one run, every step: what it was handed, what it made
— and `P22-05`'s dry run of a document, step by step.

**Measured before this file, on `5654cd4`:** a run's only record was its
`TaskRun` — one `result`, one `error`, one step log for the whole run (`B806`:
it cannot hold what each step was handed) — and `GET /api/workflows/{id}/runs/
{run_id}` did not exist. `POST /api/tasks/{id}/run?dry=true` answered a run and
no per-step plan.

Driven: `GET /api/workflows/{id}/runs/{run_id}` → `{run, version, version_kept,
graph, nodes, cleared}` (`C2`), with node records the engine would write
(design § 3.1) — including a truncated input, the graph of the version the run
used (and the honest fallback when that version was pruned), and a run whose
records were cleared after their window. And the dry reply's `nodes`, read
back from that run's dry node records in the shape of wave B's `chain` entries.
"""

from __future__ import annotations

import json
import uuid

from core.database import TaskRun, utcnow_naive
from tests.helpers import workflow_contract as wc
from test_a_workflow_is_kept_as_one_document import (  # noqa: F401
    TWO, admins, call, client, graph, new, save, sched, step, wf_db,
)

NODE_RECORD_KEYS = {"id", "node_id", "kind", "label", "seq", "status", "attempt", "dry", "port",
                    "workflow_version", "started_at", "finished_at", "input", "input_summary",
                    "output", "error", "steps", "model"}
PLAN_KEYS = {"node_id", "kind", "name", "when", "depth", "steps", "declined"}


def _run(factory, task_id, *, records=(), steps=None, status="error", days_ago=0, result="last words"):
    """A finished run of a workflow, and the node records the walker wrote."""
    from datetime import timedelta
    TaskRunNode = wc.models()[2]
    run_id = str(uuid.uuid4())
    at = utcnow_naive() - timedelta(days=days_ago)
    db = factory()
    try:
        db.add(TaskRun(id=run_id, task_id=task_id, status=status, started_at=at,
                       finished_at=at, result=result,
                       steps=json.dumps(steps or [])))
        db.flush()
        for seq, rec in enumerate(records, 1):
            db.add(TaskRunNode(id=str(uuid.uuid4()), run_id=run_id, seq=seq, attempt=1, dry=False,
                               started_at=utcnow_naive(), finished_at=utcnow_naive(), **rec))
        db.commit()
    finally:
        db.close()
    return run_id


def _two_records(version, *, fail=True):
    handed = {"source": "event", "event": "email_received", "at": "2026-10-01T07:00:00Z",
              "data": {"subject": "Your statement", "sender": "bank@example.com"}}
    return [
        {"node_id": "n1", "kind": "llm", "label": "Summarise my inbox", "status": "success",
         "port": "success", "workflow_version": version, "input": json.dumps(handed),
         "output": json.dumps({"text": "Three mails.", "data": None})},
        {"node_id": "n2", "kind": "llm", "label": "Send me the summary",
         "status": "error" if fail else "success", "port": None, "workflow_version": version,
         "input": json.dumps({"truncated": True, "chars": 40000, "preview": "Three…"}),
         "error": "The model did not answer." if fail else None},
    ]


def test_a_run_comes_back_with_every_step_on_the_graph_it_ran(client, wf_db):
    wf = save(client, new(client), TWO).json()["workflow"]                     # version 2
    run_id = _run(wf_db, wf["task_id"], records=_two_records(2),
                  steps=[{"kind": "node", "node": "n1"}, {"kind": "node", "node": "n2"}])
    wf = save(client, wf, graph([step("n1", label="Only this now")])).json()["workflow"]  # 3
    res = call(client, "GET", f"/api/workflows/{wf['id']}/runs/{run_id}")
    assert res.status_code == 200, res.text
    out = res.json()
    assert set(out) == {"run", "version", "version_kept", "graph", "nodes", "cleared",
                        "cleared_sentence"}
    assert (out["version"], out["version_kept"], out["cleared"]) == (2, True, False)
    assert out["cleared_sentence"] is None, "said only when the records were cleared"
    assert [n["label"] for n in out["graph"]["nodes"]] == ["Summarise my inbox", "Send me the summary"]
    assert out["run"]["id"] == run_id and out["run"]["status"] == "error"
    first, failed = out["nodes"]
    assert set(first) == NODE_RECORD_KEYS and set(failed) == NODE_RECORD_KEYS
    assert (first["seq"], first["status"], first["port"]) == (1, "success", "success")
    assert first["input"]["data"]["subject"] == "Your statement"
    assert "subject=Your statement" in first["input_summary"], "said as every trigger is said"
    assert (failed["status"], failed["error"]) == ("error", "The model did not answer.")
    assert failed["input"] == {"truncated": True, "chars": 40000, "preview": "Three…"}


def test_a_run_whose_version_was_pruned_is_drawn_on_the_current_graph_and_says_so(client, wf_db):
    WorkflowVersion = wc.models()[1]
    wf = save(client, new(client), TWO).json()["workflow"]
    run_id = _run(wf_db, wf["task_id"], records=_two_records(2))
    db = wf_db()
    try:
        db.query(WorkflowVersion).filter(WorkflowVersion.version == 2).delete()
        db.commit()
    finally:
        db.close()
    out = call(client, "GET", f"/api/workflows/{wf['id']}/runs/{run_id}").json()
    assert (out["version"], out["version_kept"]) == (2, False)


def test_a_run_whose_records_were_cleared_says_so_and_one_that_had_none_does_not(
        client, wf_db, monkeypatch):
    """"Its step details were cleared" is a claim (`Law 10`): made only for a
    run whose log says steps ran AND that ended longer ago than records are
    kept (`workflow_node_records_days`, the window the pruner reads)."""
    from src.task_scheduler import DRY_RUN_HEADLINE
    wf = save(client, new(client), TWO).json()["workflow"]
    ran = [{"kind": "trigger", "detail": "x"}, {"kind": "node", "node": "n1", "status": "success"}]
    planned = [{"kind": "dry-run", "detail": DRY_RUN_HEADLINE},
               {"kind": "dry-run", "detail": "Would run “Summarise my inbox”."}]
    old = _run(wf_db, wf["task_id"], steps=ran, days_ago=31)
    recent = _run(wf_db, wf["task_id"], steps=ran, days_ago=2)
    old_plan = _run(wf_db, wf["task_id"], steps=planned, status="skipped", days_ago=40,
                    result=DRY_RUN_HEADLINE)
    new_plan = _run(wf_db, wf["task_id"], steps=planned, status="skipped", result=DRY_RUN_HEADLINE)
    refused = _run(wf_db, wf["task_id"], steps=[{"kind": "progress", "detail": "Refused"}],
                   status="skipped", days_ago=90)

    said = {}

    def cleared(run_id):
        out = call(client, "GET", f"/api/workflows/{wf['id']}/runs/{run_id}").json()
        assert out["nodes"] == []
        said[run_id] = out["cleared_sentence"]
        assert (out["cleared_sentence"] is not None) == out["cleared"]
        return out["cleared"]
    assert [cleared(r) for r in (old, recent, old_plan, new_plan, refused)] == [
        True, False, True, False, False]
    # What a person is told is the engine's sentence, naming the window as it
    # is set (wave C merge: the panel had typed "30 days" itself).
    from src.workflow_runs import records_cleared_sentence
    assert said[old] == records_cleared_sentence(30)
    assert "after 30 days" in said[old]
    # The window is the setting's, read when asked: kept for a year, the
    # month-old run's records cannot have been cleared yet.
    import src.settings as settings
    real = settings.resolve_limit
    monkeypatch.setattr(settings, "resolve_limit", lambda key, default, **kw: (
        (365, "instance setting") if key == "workflow_node_records_days" else real(key, default, **kw)))
    assert cleared(old) is False
    # Kept for a week instead, the month-old run's were cleared — and the
    # sentence says a week, not the default.
    monkeypatch.setattr(settings, "resolve_limit", lambda key, default, **kw: (
        (7, "instance setting") if key == "workflow_node_records_days" else real(key, default, **kw)))
    assert cleared(recent) is False and cleared(old) is True
    assert "after 7 days" in said[old]


def test_a_run_of_something_else_is_not_this_workflows(client, wf_db):
    one = new(client, "One")
    two = new(client, "Two")
    run_id = _run(wf_db, two["task_id"], records=_two_records(1))
    res = call(client, "GET", f"/api/workflows/{one['id']}/runs/{run_id}")
    assert (res.status_code, res.json()) == (404, {"detail": "No such run of this workflow."})


def test_a_dry_run_of_a_workflow_answers_a_plan_per_step(client, wf_db, sched):
    branched = graph([step("n1", label="Summarise my inbox"),
                      step("n2", label="Send me the summary"),
                      step("n3", "run_task", "Run the backup", task_id="bk")],
                     [("n1", "success", "n2"), ("n1", "error", "n3")])
    from core.database import ScheduledTask
    db = wf_db()
    try:
        db.add(ScheduledTask(id="bk", owner="alice", name="Backup", task_type="action",
                             action="tidy_sessions", trigger_type="webhook", status="active"))
        db.commit()
    finally:
        db.close()
    wf = save(client, new(client), branched)
    assert wf.status_code == 200, wf.text
    wf = wf.json()["workflow"]
    res = call(client, "POST", f"/api/tasks/{wf['task_id']}/run?dry=true")
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["dry"] is True and out["run_id"] and out["run"]["id"] == out["run_id"]
    assert [sched.runs[-1][k] for k in ("dry", "started_by")] == [True, "person"]
    plans = out["nodes"]
    assert [p["node_id"] for p in plans] == ["n1", "n2", "n3"], "breadth first, entry first"
    assert [(p["when"], p["depth"]) for p in plans] == [(None, 0), ("success", 1), ("error", 1)]
    assert set(plans[0]) == PLAN_KEYS and set(plans[2]) == PLAN_KEYS | {"task_id"}
    assert plans[2]["task_id"] == "bk", "a run-task step's target, never the step's own id"
    assert plans[1]["name"] == "Send me the summary" and plans[1]["declined"] is None
    assert plans[1]["steps"][0]["kind"] == "dry-run"


def test_a_dry_plans_place_is_the_one_its_record_says(client, wf_db, sched, monkeypatch):
    """The engine's dry record carries how its walk reached each step
    (`reached_by`, `depth`); the reply reads that, and walks the graph only for
    a record without it — one answer to "how is this step reached" (`Law 7`)."""
    import pytest
    TaskRunNode = wc.models()[2]
    if not hasattr(TaskRunNode, "depth"):
        pytest.skip("this TaskRunNode keeps no dry place; the graph walk is the answer")
    wf = save(client, new(client), TWO).json()["workflow"]
    real_run = sched.run_task_now

    async def run_with_places(task_id, **kw):
        run_id = await real_run(task_id, **kw)
        db = wf_db()
        try:
            for rec in db.query(TaskRunNode).filter(TaskRunNode.run_id == run_id).all():
                # Places the graph's own walk would not give, so the test can
                # tell which was read.
                rec.reached_by, rec.depth = {"n1": (None, 0), "n2": ("error", 7)}[rec.node_id]
            db.commit()
        finally:
            db.close()
        return run_id
    monkeypatch.setattr(sched, "run_task_now", run_with_places)
    out = call(client, "POST", f"/api/tasks/{wf['task_id']}/run?dry=true").json()
    assert [(p["node_id"], p["when"], p["depth"]) for p in out["nodes"]] == [
        ("n1", None, 0), ("n2", "error", 7)]


def test_a_plain_tasks_dry_run_answers_exactly_as_before(client, wf_db):
    from core.database import ScheduledTask
    db = wf_db()
    try:
        db.add(ScheduledTask(id="plain", owner="alice", name="Plain", task_type="llm", prompt="x",
                             trigger_type="webhook", status="active"))
        db.commit()
    finally:
        db.close()
    out = call(client, "POST", "/api/tasks/plain/run?dry=true").json()
    assert "nodes" not in out
