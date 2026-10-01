# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P22-05` — a workflow's start is a task, and every task door knows it
(`/work/notes/SLICE-B-DESIGN.md` § 0.5, § 0.12, § 5's guards).

**Measured before this file, on `5654cd4`:** nothing validated `task_type`.
`POST /api/tasks` stored `{"task_type": "workflow"}` (a start with no
document), `PUT /api/tasks/{id}` and `manage_tasks edit` wrote it over any
task's type, and once a start existed, `DELETE /api/tasks/{id}` would have
left its document with nothing to run it, and the admin wipe of "tasks" bulk-
deleted tasks and runs and nothing else — a workflow's document and versions
would have outlived it. `GET /api/tasks` carried no way from a start to its
document.

Each door, driven: the task routes through `TestClient`, `manage_tasks`
(`src.tools.system.do_manage_tasks`) called as the agent calls it, the
webhook handler, and the admin wipe's handler, all on one real SQLite file.
"""

from __future__ import annotations

import asyncio
import json

from core.database import ScheduledTask, TaskRun
from tests.helpers import workflow_contract as wc
from test_a_workflow_is_kept_as_one_document import (  # noqa: F401
    TWO, admins, call, client, graph, new, rows, save, sched, step, wf_db,
)
from src.workflow_store import WORKFLOW_MADE_IN_WORKBENCH

PLAIN = {"name": "Plain", "task_type": "llm", "prompt": "Say hi.", "trigger_type": "webhook"}


def _plain(client):
    res = call(client, "POST", "/api/tasks", json=PLAIN)
    assert res.status_code == 200, res.text
    return res.json()


def _tool(content, owner="alice"):
    from src.tools.system import do_manage_tasks
    return asyncio.run(do_manage_tasks(json.dumps(content), owner=owner))


# ── the task routes ──────────────────────────────────────────────────────────

def test_a_workflow_is_not_made_through_the_task_form(client, wf_db):
    res = call(client, "POST", "/api/tasks", json=dict(PLAIN, task_type="workflow"))
    assert (res.status_code, res.json()) == (400, {"detail": WORKFLOW_MADE_IN_WORKBENCH})
    assert rows(wf_db, ScheduledTask) == []


def test_a_task_does_not_become_a_workflows_start_by_an_edit(client):
    plain = _plain(client)
    res = call(client, "PUT", f"/api/tasks/{plain['id']}", json={"task_type": "workflow"})
    assert (res.status_code, res.json()) == (400, {"detail": WORKFLOW_MADE_IN_WORKBENCH})


def test_a_start_keeps_its_type_and_its_workflows_name_and_takes_trigger_settings(client, wf_db):
    wf = new(client, "Morning digest")
    url = f"/api/tasks/{wf['task_id']}"
    retype = call(client, "PUT", url, json={"task_type": "llm"})
    assert retype.status_code == 400
    assert retype.json()["detail"] == ("“Morning digest” starts the workflow “Morning digest”, so it "
                                       "stays a workflow's start. Change the workflow in the Workbench.")
    rename = call(client, "PUT", url, json={"name": "Something else"})
    assert rename.status_code == 400 and "Rename the workflow in the Workbench" in rename.json()["detail"]
    same = call(client, "PUT", url, json={"name": "Morning digest", "schedule": "daily",
                                          "scheduled_time": "07:30", "max_retries": 2})
    assert same.status_code == 200, same.text
    (start,) = rows(wf_db, ScheduledTask, id=wf["task_id"])
    assert (start.task_type, start.scheduled_time, start.max_retries) == ("workflow", "07:30", 2)


def test_a_start_is_deleted_with_its_workflow_and_not_alone(client, wf_db):
    wf = new(client, "Morning digest")
    res = call(client, "DELETE", f"/api/tasks/{wf['task_id']}")
    assert res.status_code == 400
    assert res.json()["detail"] == ("“Morning digest” starts the workflow “Morning digest”. Delete the "
                                    "workflow in the Workbench, and this goes with it.")
    assert len(rows(wf_db, ScheduledTask, id=wf["task_id"])) == 1
    plain = _plain(client)
    assert call(client, "DELETE", f"/api/tasks/{plain['id']}").status_code == 200


def test_every_task_row_says_which_workflow_it_starts(client):
    wf = new(client, "Morning digest")
    plain = _plain(client)
    listed = {t["id"]: t for t in call(client, "GET", "/api/tasks").json()["tasks"]}
    assert listed[wf["task_id"]]["workflow_id"] == wf["id"]
    assert listed[plain["id"]]["workflow_id"] is None
    one = call(client, "GET", f"/api/tasks/{wf['task_id']}").json()
    assert one["workflow_id"] == wf["id"]
    assert plain["workflow_id"] is None, "a create's reply has the key too"


def test_the_task_list_asks_for_workflows_once_and_not_at_all_without_one(client, wf_db, monkeypatch):
    import src.workflow_store as store
    asked = []
    real = store.workflow_ids_for
    monkeypatch.setattr(store, "workflow_ids_for", lambda db, ids: asked.append(list(ids)) or real(db, ids))
    _plain(client)
    call(client, "GET", "/api/tasks")
    assert asked == [[]], "no workflow listed, no workflow asked about"
    wf1, wf2 = new(client, "A"), new(client, "B")
    asked.clear()
    call(client, "GET", "/api/tasks")
    assert len(asked) == 1 and sorted(asked[0]) == sorted([wf1["task_id"], wf2["task_id"]])


def test_a_step_only_an_admin_may_schedule_gates_its_workflows_run(client, admins, wf_db):
    from src.task_action_policy import admin_refusal_message
    risky = graph([step("n1", "action", "Shell", action="run_local", prompt="ls")])
    admins.add("alice")
    wf = save(client, new(client), risky).json()["workflow"]
    admins.clear()
    for query in ("", "?dry=true"):
        res = call(client, "POST", f"/api/tasks/{wf['task_id']}/run{query}")
        assert (res.status_code, res.json()) == (403, {"detail": admin_refusal_message("run_local")})
    resume = call(client, "POST", f"/api/tasks/{wf['task_id']}/resume")
    assert resume.status_code == 403


def test_a_webhook_into_a_workflow_with_an_admin_only_step_is_refused_and_filed(
        client, admins, wf_db, sched):
    from src.task_action_policy import admin_refusal_message
    risky = graph([step("n1", "action", "Shell", action="run_local", prompt="ls")])
    admins.add("alice")
    wf = save(client, new(client), risky).json()["workflow"]
    db = wf_db()
    try:
        start = db.query(ScheduledTask).filter(ScheduledTask.id == wf["task_id"]).first()
        start.trigger_type, start.webhook_token, start.status = "webhook", "tok", "active"
        db.commit()
    finally:
        db.close()
    admins.clear()
    res = client.post(f"/api/tasks/{wf['task_id']}/webhook/tok", json={"x": 1})
    assert (res.status_code, res.json()) == (403, {"detail": admin_refusal_message("run_local")})
    (run,) = rows(wf_db, TaskRun, task_id=wf["task_id"])
    assert (run.status, run.error) == ("skipped", admin_refusal_message("run_local"))
    (start,) = rows(wf_db, ScheduledTask, id=wf["task_id"])
    assert start.status == "paused"
    assert sched.runs == []


# ── manage_tasks ─────────────────────────────────────────────────────────────

def test_the_agent_cannot_make_a_workflow_or_break_a_start_either(client, wf_db):
    made = _tool({"action": "create", "task_type": "workflow", "name": "X"})
    assert made == {"error": WORKFLOW_MADE_IN_WORKBENCH, "exit_code": 1}
    plain = _plain(client)
    retyped = _tool({"action": "edit", "task_id": plain["id"], "task_type": "workflow"})
    assert retyped == {"error": WORKFLOW_MADE_IN_WORKBENCH, "exit_code": 1}
    wf = new(client, "Morning digest")
    for content, words in (
        ({"action": "edit", "task_id": wf["task_id"], "task_type": "llm"}, "stays a workflow's start"),
        ({"action": "edit", "task_id": wf["task_id"], "name": "Other"}, "Rename the workflow"),
        ({"action": "delete", "task_id": wf["task_id"]}, "Delete the workflow in the Workbench"),
    ):
        out = _tool(content)
        assert out["exit_code"] == 1 and words in out["error"], content
    (start,) = rows(wf_db, ScheduledTask, id=wf["task_id"])
    assert (start.task_type, start.name) == ("workflow", "Morning digest")
    assert _tool({"action": "edit", "task_id": plain["id"], "name": "Renamed"})["exit_code"] == 0


def test_the_agents_resume_of_a_start_is_the_one_switch(client, wf_db):
    from test_a_chain_becomes_a_workflow_and_the_chain_stays import _chain
    _chain(wf_db)
    wf = call(client, "POST", "/api/workflows", json={"from_task_id": "backup"}).json()["workflow"]
    out = _tool({"action": "resume", "task_id": wf["task_id"]})
    assert out["exit_code"] == 0, out
    assert "is paused so the two do not both run" in out["response"]
    (head,) = rows(wf_db, ScheduledTask, id="backup")
    assert head.status == "paused"


# ── the admin wipe ───────────────────────────────────────────────────────────

def test_wiping_the_tasks_wipes_the_workflows_with_them(client, wf_db, monkeypatch):
    from fastapi import Request
    import routes.admin_wipe.admin_wipe_routes as wipe_routes
    Workflow, WorkflowVersion, TaskRunNode = wc.models()
    wf = save(client, new(client), TWO).json()["workflow"]
    _plain(client)
    db = wf_db()
    try:
        db.add(TaskRun(id="r1", task_id=wf["task_id"], status="success"))
        db.flush()
        db.add(TaskRunNode(id="rec", run_id="r1", node_id="n1", status="success"))
        db.commit()
    finally:
        db.close()
    monkeypatch.setattr(wipe_routes, "SessionLocal", wf_db)
    monkeypatch.setattr(wipe_routes, "require_admin", lambda request: None)
    router = wipe_routes.setup_admin_wipe_routes(session_manager=None)
    handler = next(r.endpoint for r in router.routes if r.path == "/api/admin/wipe/{kind}")
    out = handler(kind="tasks", request=Request(scope={"type": "http"}))
    assert out == {"status": "deleted", "kind": "tasks", "count": 2, "workflows": 1}
    for model in (ScheduledTask, TaskRun, Workflow, WorkflowVersion, TaskRunNode):
        assert rows(wf_db, model) == [], model.__name__
