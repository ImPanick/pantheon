# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P22-24` — tasks and workflows join the backup (`routes/backup_routes.py`).

**Measured before this file, on `4cfb297`:** `GET /api/export` carried
memories, presets, skills, settings, features and preferences — no task and no
workflow — so a backup restored onto a fresh install brought back none of a
person's automations, and no webhook URL anyone had been given.

What holds, on two real SQLite files ("install 1" exports, "install 2"
imports) through the real backup router:

  * the export carries the person's own tasks — webhook tokens included, by
    `B958`'s logic (a restore needs what does not re-pair on its own) — and
    their workflows, and nobody else's; it says what it does not carry;
  * the import restores tasks then workflows by their own ids, so the same
    webhook URL answers on install 2;
  * a workflow install 2 refuses (its MCP server is not connected there) is
    restored with its trigger switched OFF and named with the rule's sentence;
  * a draft nobody checked comes back still waiting for a person — a backup
    round trip does not clear a mark;
  * ids install 2 already has are skipped, and versions, runs and step
    records are not carried.
"""

import json
from types import SimpleNamespace

import pytest

from core.database import ScheduledTask, TaskRun, Workflow, WorkflowVersion
from core.middleware import INTERNAL_TOOL_HEADER, INTERNAL_TOOL_TOKEN
from src import workflow_store as store
from tests.helpers.assist_harness import (
    PERSON, POST, Chat, build_world, marks_of, rows, stored, versions,
)
from tests.helpers.walker_harness import client_for, settle

pytestmark = pytest.mark.asyncio
ADMIN = {"x-test-user": "alice", INTERNAL_TOOL_HEADER: INTERNAL_TOOL_TOKEN}

CHECKED = {"v": 1, "nodes": [
    {"id": "summary", "kind": "llm", "label": "Summarise",
     "config": {"prompt": "Summarise {{ steps.start.data.body }}"}},
    {"id": "post", "kind": "mcp", "label": "Post to #dev",
     "config": {"tool": POST, "args": {"channel": "#dev", "text": "{{ steps.summary.text }}"}}}],
    "edges": [{"from": "summary", "port": "success", "to": "post"}]}
DRAFT = {"v": 1, "nodes": [{"id": "brief", "kind": "action", "label": "Daily brief",
                            "config": {"action": "daily_brief"}}], "edges": []}


class NoTools(Chat):
    def get_all_tools(self, disabled_map=None, overrides=None):
        return []


@pytest.fixture()
def settings_files(tmp_path, monkeypatch):
    import src.settings as S
    sp, fp = tmp_path / "settings.json", tmp_path / "features.json"
    sp.write_text("{}", encoding="utf-8")
    fp.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(S, "SETTINGS_FILE", str(sp))
    monkeypatch.setattr(S, "FEATURES_FILE", str(fp))
    S._invalidate_caches()
    yield
    S._invalidate_caches()


def _backup_app(w):
    from fastapi import FastAPI
    from routes.backup_routes import setup_backup_routes

    class _Mgr:
        def load(self, **k): return []
        def load_all_for_update(self): return []
        def load_all(self): return []
        def get_all(self): return {}
        def save(self, *a, **k): return None

    app = FastAPI()
    # `B1175`: `ADMIN`'s loopback names alice, and `require_admin` asks whether
    # the person it names is an admin — she is, on this install.
    app.state.auth_manager = SimpleNamespace(is_configured=True,
                                             is_admin=lambda user: user == "alice")

    @app.middleware("http")
    async def _who(request, call_next):
        request.state.current_user = request.headers.get("x-test-user")
        return await call_next(request)

    app.include_router(setup_backup_routes(_Mgr(), _Mgr(), _Mgr()))
    return app


async def _install_one(monkeypatch, tmp_path):
    w = build_world(monkeypatch, tmp_path, name="one.db")
    db = w.factory()
    try:
        db.add(ScheduledTask(id="t-report", owner="alice", name="Email me the result",
                             task_type="llm", prompt="Say it", trigger_type="schedule",
                             schedule="daily", scheduled_time="03:00", status="active"))
        db.add(ScheduledTask(id="t-hook", owner="alice", name="Deploy hook", task_type="llm",
                             prompt="Summarise the deploy", trigger_type="webhook",
                             webhook_token="tok-0123456789abcdef", status="active",
                             then_task_id="t-report", crew_member_id="crew-gone"))
        db.add(ScheduledTask(id="t-bob", owner="bob", name="Bob's own", task_type="llm",
                             prompt="x", status="active"))
        db.commit()
        made, trigger, _ = store.create_from_document(
            db, owner="alice", name="Digest", graph=json.loads(json.dumps(CHECKED)),
            trigger_fields={"trigger_type": "webhook"}, origin="drafted")
        checked_id, checked_task = made.id, trigger.id
        draft, draft_trigger, _ = store.create_from_document(
            db, owner="alice", name="Morning", graph=json.loads(json.dumps(DRAFT)),
            trigger_fields={"trigger_type": "schedule", "schedule": "daily",
                            "scheduled_time": "07:00"}, origin="drafted")
        draft_id, draft_task = draft.id, draft_trigger.id
        store.create_workflow(db, owner="bob", name="Bob's flow")
    finally:
        db.close()
    async with client_for(w.app) as client:
        assert (await client.put(f"/api/workflows/{checked_id}", headers=PERSON,
                                 json={"checked": ["summary", "post"]})).status_code == 200
        assert (await client.post(f"/api/workflows/{checked_id}/switch", headers=PERSON,
                                  json={"on": True})).status_code == 200
    await w.s._execute_task(checked_task, trigger={"source": "webhook", "event": "webhook",
                                                   "data": {"body": "deployed"}})
    await settle(w.s)
    assert [r.status for r in rows(w.factory, TaskRun, task_id=checked_task)] == ["success"]
    async with client_for(_backup_app(w)) as client:
        res = await client.get("/api/export", headers=ADMIN)
    assert res.status_code == 200, res.text
    return json.loads(res.content), {"checked": checked_id, "checked_task": checked_task,
                                     "draft": draft_id, "draft_task": draft_task}


async def test_the_backup_carries_the_owners_tasks_and_workflows_and_nobody_elses(
        monkeypatch, tmp_path, settings_files):
    data, ids = await _install_one(monkeypatch, tmp_path)
    task_ids = {t["id"] for t in data["tasks"]}
    assert task_ids == {"t-report", "t-hook", ids["checked_task"], ids["draft_task"]}
    hook = next(t for t in data["tasks"] if t["id"] == "t-hook")
    assert hook["webhook_token"] == "tok-0123456789abcdef" and hook["then_task_id"] == "t-report"
    assert {w["id"] for w in data["workflows"]} == {ids["checked"], ids["draft"]}
    assert data["not_carried"] == ("Workflow versions, task runs and their step records are not "
                                   "in a backup.")
    assert "Bob" not in json.dumps(data["tasks"]) + json.dumps(data["workflows"])
    draft = next(w for w in data["workflows"] if w["id"] == ids["draft"])
    assert marks_of(draft["graph"])["brief"]["origin"] == "drafted"


async def test_a_fresh_install_gets_them_back_and_the_same_webhook_url_answers(
        monkeypatch, tmp_path, settings_files):
    data, ids = await _install_one(monkeypatch, tmp_path)
    w = build_world(monkeypatch, tmp_path, name="two.db", chat=NoTools())
    async with client_for(_backup_app(w)) as client:
        res = await client.post("/api/import", headers=ADMIN, json=data)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["imported"][-2:] == ["4 tasks", "2 workflows"]
    hook = rows(w.factory, ScheduledTask, id="t-hook")[0]
    assert hook.owner == "alice" and hook.webhook_token == "tok-0123456789abcdef"
    assert hook.then_task_id == "t-report" and hook.crew_member_id is None
    assert rows(w.factory, ScheduledTask, owner="bob") == []
    async with client_for(w.app) as client:
        fired = await client.post("/api/tasks/t-hook/webhook/tok-0123456789abcdef",
                                  json={"note": "deployed"})
    assert fired.status_code == 200, fired.text
    await settle(w.s)
    # The workflow whose MCP server is not connected here: restored, switched off, said.
    wf, graph, trigger = stored(w.factory, ids["checked"])
    assert trigger.status == "paused" and wf.task_id == ids["checked_task"]
    off = {o["id"]: o for o in body["switched_off"]}
    async with client_for(w.app) as client:
        save = await client.put(f"/api/workflows/{ids['checked']}?check=true", headers=PERSON,
                                json={"graph": graph, "base_version": wf.version})
    assert save.status_code == 400
    assert off[ids["checked"]]["why"] == save.json()["detail"], "the sentence a save gets here"
    assert (f"“Digest” was restored switched off: {save.json()['detail'].rstrip('.')}"
            in body["message"])
    # The draft nobody checked: still waiting for a person.
    _wf, draft_graph, draft_trigger = stored(w.factory, ids["draft"])
    assert marks_of(draft_graph)["brief"]["origin"] == "drafted"
    assert draft_trigger.status == "paused"
    assert off[ids["draft"]]["why"].startswith("The model drafted 1 step nobody has checked yet")
    # Not carried: versions (one row, the current one, `restored`) and runs.
    assert [v["source"] for v in versions(w.factory, ids["checked"])] == ["restored"]
    assert [v["version"] for v in versions(w.factory, ids["checked"])] == [wf.version]
    assert rows(w.factory, TaskRun, task_id=ids["checked_task"]) == []
    assert all("unchecked" not in n for v in rows(w.factory, WorkflowVersion)
               for n in json.loads(v.graph)["nodes"])


async def test_ids_this_install_already_has_are_skipped(monkeypatch, tmp_path, settings_files):
    data, ids = await _install_one(monkeypatch, tmp_path)
    w = build_world(monkeypatch, tmp_path, name="two.db")
    async with client_for(_backup_app(w)) as client:
        first = await client.post("/api/import", headers=ADMIN, json=data)
        again = await client.post("/api/import", headers=ADMIN, json=data)
    assert first.json()["imported"][-2:] == ["4 tasks", "2 workflows"]
    assert again.json()["imported"][-2:] == ["0 tasks", "0 workflows"]
    assert len(rows(w.factory, ScheduledTask)) == 4 and len(rows(w.factory, Workflow)) == 2


async def test_a_workflow_is_never_linked_to_someone_elses_task(monkeypatch, tmp_path, settings_files):
    data, ids = await _install_one(monkeypatch, tmp_path)
    w = build_world(monkeypatch, tmp_path, name="two.db")
    db = w.factory()
    try:
        db.add(ScheduledTask(id=ids["checked_task"], owner="bob", name="Bob's, same id",
                             task_type="workflow", status="active"))
        db.commit()
    finally:
        db.close()
    async with client_for(_backup_app(w)) as client:
        res = await client.post("/api/import", headers=ADMIN, json=data)
    assert res.status_code == 200, res.text
    wf = rows(w.factory, Workflow, id=ids["checked"])[0]
    assert wf.owner == "alice" and wf.task_id is None
    assert rows(w.factory, ScheduledTask, id=ids["checked_task"])[0].owner == "bob"
    off = {o["id"]: o["why"] for o in res.json()["switched_off"]}
    assert ids["checked"] in off


async def test_an_unreadable_task_table_is_said_not_passed_off_as_none(
        monkeypatch, tmp_path, settings_files):
    """`Law 10`: a backup whose tasks could not be read leaves the two keys out
    and says so — never an empty list that reads as "there were none" — and
    the rest of the backup is still made."""
    from sqlalchemy.exc import OperationalError
    import routes.backup_routes as backup_routes
    w = build_world(monkeypatch, tmp_path, name="broken.db")

    def broken(db, user):
        raise OperationalError("SELECT", {}, Exception("no such table: scheduled_tasks"))
    monkeypatch.setattr(backup_routes, "backup_tasks", broken)
    async with client_for(_backup_app(w)) as client:
        res = await client.get("/api/export", headers=ADMIN)
    assert res.status_code == 200, res.text
    data = json.loads(res.content)
    assert "tasks" not in data and "workflows" not in data and "settings" in data
    assert data["not_carried"] == (f"{backup_routes.TASKS_UNREADABLE} "
                                   f"{backup_routes.NOT_CARRIED}")
