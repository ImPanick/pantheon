# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1191`, the owner's call (`D-2026-10-26-01` §5) — *"a tool switched off for
a person is hidden, its routes refused, and that person's background work for
it paused with a sentence saying why; nothing is deleted."*

**Measured before this file:** Assistant, Calendar, Compare, Email, Notes,
Tasks, Theme and Workbench had *Show in this browser* and nothing an admin
could set for one person. Each has a switch now; this drives what each takes —
the door, the routes, the agent's tools, and the work that runs without the
window — and that turning one back on is all it takes.
"""

from __future__ import annotations

import asyncio
import re
import types
from pathlib import Path

import pytest

from src import tool_privileges as TP

ROOT = Path(__file__).resolve().parents[1]
KEYS = ("can_use_assistant", "can_use_calendar", "can_use_compare", "can_use_email",
        "can_use_notes", "can_use_tasks", "can_use_theme", "can_use_workbench")


class _Auth:
    """ada is an admin; bob has whatever `off` names switched off."""
    is_configured = True

    def __init__(self, off=()):
        self.off = set(off)
        self.users = {"ada": {"is_admin": True}, "bob": {}}

    def is_admin(self, name):
        return name == "ada"

    def get_privileges(self, name):
        from core.auth import ADMIN_PRIVILEGES, DEFAULT_PRIVILEGES
        if name == "ada":
            return dict(ADMIN_PRIVILEGES)
        return {**DEFAULT_PRIVILEGES, **{k: False for k in self.off}}


@pytest.fixture()
def auth(monkeypatch):
    holder = {"mgr": _Auth()}

    def use(*off):
        holder["mgr"] = _Auth(off)
        return holder["mgr"]

    monkeypatch.setattr(TP, "_auth_manager", lambda: holder["mgr"])
    return use


# ── the switch exists, once, for each ───────────────────────────────────────

def test_each_tools_entry_has_its_switch_on_by_default():
    from core.auth import DEFAULT_PRIVILEGES
    assert tuple(sorted(TP.TOOL_PRIVILEGES)) == KEYS
    for key in KEYS:
        assert DEFAULT_PRIVILEGES[key] is True, "on: nothing changes until an admin turns one off"
    vis = (ROOT / "static" / "js" / "ui_visibility.js").read_text(encoding="utf-8")
    admin = (ROOT / "static" / "js" / "admin.js").read_text(encoding="utf-8")
    for key in KEYS:
        assert f"privilege: '{key}'" in vis, f"the door does not read {key}"
        assert re.search(rf"^\s*{key}: '{TP.label(key)}',", admin, re.M), f"the Users panel offers no {key}"


# ── the routes ──────────────────────────────────────────────────────────────

def _app(mgr, dependency):
    from fastapi import APIRouter, Depends, FastAPI
    from fastapi.testclient import TestClient
    router = APIRouter(prefix="/api/x", dependencies=[Depends(dependency)])

    @router.get("/thing")
    def thing():
        return {"ok": True}

    app = FastAPI()
    app.state.auth_manager = mgr

    @app.middleware("http")
    async def _who(request, call_next):
        who = request.headers.get("x-user")
        if who:
            request.state.current_user = who
        if request.headers.get("x-token"):
            request.state.api_token = True
            request.state.api_token_owner = request.headers.get("x-token")
            request.state.current_user = "api"
        return await call_next(request)

    app.include_router(router)
    return TestClient(app)


def test_a_route_is_refused_in_the_doors_words_and_only_for_that_person(auth):
    client = _app(auth("can_use_calendar"), TP.tool_privilege("can_use_calendar"))
    r = client.get("/api/x/thing", headers={"x-user": "bob"})
    assert r.status_code == 403
    assert r.json()["detail"] == ("Calendar is switched off for your account. An admin can turn it "
                                  "back on in Settings → Users.")
    assert client.get("/api/x/thing", headers={"x-user": "ada"}).status_code == 200
    assert client.get("/api/x/thing", headers={"x-token": "bob"}).status_code == 403, \
        "a token answers for the person who minted it"
    assert client.get("/api/x/thing").status_code == 200, "naming nobody is the route's own question"
    client = _app(auth(), TP.tool_privilege("can_use_calendar"))
    assert client.get("/api/x/thing", headers={"x-user": "bob"}).status_code == 200, "back on: all it takes"


@pytest.mark.parametrize("module, setup, key", [
    ("routes.calendar_routes", "setup_calendar_routes", "can_use_calendar"),
    ("routes.note.note_routes", "setup_note_routes", "can_use_notes"),
    ("routes.compare.compare_routes", "setup_compare_routes", "can_use_compare"),
    ("routes.assistant_routes", "setup_assistant_routes", "can_use_assistant"),
    ("routes.workflow.workflow_routes", "setup_workflow_routes", "can_use_workbench"),
])
def test_each_tools_router_carries_its_switch(module, setup, key):
    import importlib
    import inspect
    mod = importlib.import_module(module)
    src = inspect.getsource(getattr(mod, setup))
    assert f'_tool_privilege("{key}")' in src


def test_the_email_router_carries_its_switch():
    src = (ROOT / "routes" / "email_routes.py").read_text(encoding="utf-8")
    assert 'router = APIRouter(prefix="/api/email", tags=["email"],' in src
    assert '_tool_privilege("can_use_email")' in src


def test_task_data_opens_to_either_switch_and_the_notifications_poll_to_everyone(auth):
    from routes.task.task_routes import _tasks_gate
    client = _app(auth("can_use_tasks"), _tasks_gate)
    assert client.get("/api/x/thing", headers={"x-user": "bob"}).status_code == 200, \
        "the Workbench's Automations room still reads the task data"
    client = _app(auth("can_use_tasks", "can_use_workbench"), _tasks_gate)
    r = client.get("/api/x/thing", headers={"x-user": "bob"})
    assert r.status_code == 403 and r.json()["detail"].startswith("Tasks is switched off")


# ── the agent ───────────────────────────────────────────────────────────────

def test_the_agent_loses_the_tools_and_only_those(auth):
    auth("can_use_calendar", "can_use_email", "can_use_compare")
    off = TP.withheld_for_owner("bob")
    assert "manage_calendar" in off and "send_email" in off and "read_email" in off
    assert "manage_notes" not in off and "manage_tasks" not in off
    assert TP.withheld_for_owner("ada") == set()
    loop = (ROOT / "src" / "agent_loop.py").read_text(encoding="utf-8")
    assert "_tools_switched_off(owner)" in loop and "because=WITHHELD_BY_PRIVILEGE" in loop


# ── background work ─────────────────────────────────────────────────────────

def _task(**kw):
    base = dict(id="t1", owner="bob", task_type="llm", action=None, crew_member_id=None, name="nightly")
    base.update(kw)
    return types.SimpleNamespace(**base)


def test_which_switch_holds_which_work(auth):
    auth("can_use_tasks")
    assert TP.held_by_switch(None, _task()) == "can_use_tasks"
    assert TP.held_by_switch(None, _task(task_type="workflow")) is None, "a workflow is the Workbench's"
    auth("can_use_workbench")
    assert TP.held_by_switch(None, _task(task_type="workflow")) == "can_use_workbench"
    auth("can_use_email")
    assert TP.held_by_switch(None, _task(task_type="action", action="summarize_emails")) == "can_use_email"
    assert TP.held_by_switch(None, _task(task_type="action", action="tidy_sessions")) is None
    assert TP.held_by_switch(None, _task(owner="ada", task_type="action", action="summarize_emails")) is None


def test_a_held_task_says_why_once_and_keeps_its_schedule(tmp_path, monkeypatch, auth):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import core.database as cdb
    from src import task_scheduler as TS
    engine = create_engine(f"sqlite:///{tmp_path / 't.db'}")
    cdb.Base.metadata.create_all(engine, tables=[cdb.Session.__table__, cdb.ScheduledTask.__table__,
                                                 cdb.TaskRun.__table__])
    db = sessionmaker(bind=engine)()
    task = cdb.ScheduledTask(id="t1", owner="bob", name="nightly", status="active")
    db.add(task)
    db.add_all([cdb.TaskRun(id="r1", task_id="t1", status="queued"),
                cdb.TaskRun(id="r2", task_id="t1", status="queued")])
    db.commit()
    told = []
    sched = TS.TaskScheduler.__new__(TS.TaskScheduler)
    monkeypatch.setattr(TS.TaskScheduler, "_notify_run_outcome",
                        lambda self, task, status, body=None, task_id=None, **k: told.append((status, body)))
    # `B1540`: the finished run's next time is set by `_set_next_run_after` now.
    monkeypatch.setattr(TS.TaskScheduler, "_set_next_run_after",
                        lambda self, db, task: setattr(task, "next_run", None))
    sched._skip_switched_off(db, task, "r1", "can_use_tasks")
    sched._skip_switched_off(db, task, "r2", "can_use_tasks")
    runs = {r.id: r for r in db.query(cdb.TaskRun).all()}
    assert runs["r1"].status == runs["r2"].status == "skipped"
    assert runs["r1"].result == TP.paused_sentence("can_use_tasks")
    assert "Nothing was deleted" in runs["r1"].result
    assert told == [("skipped", TP.paused_sentence("can_use_tasks"))], "told once, not every occurrence"
    assert db.get(cdb.ScheduledTask, "t1").status == "active", "its settings and status are kept"


def test_the_scheduler_asks_before_any_step_runs():
    src = (ROOT / "src" / "task_scheduler.py").read_text(encoding="utf-8")
    i = src.index("_held = _held_by_switch(db, task)")
    j = src.index("_admin_action = admin_only_action_of(db, task)")
    assert i < j


def test_the_inbox_check_holds_that_persons_mail(auth, monkeypatch):
    import routes.email_pollers as EP
    auth("can_use_email")
    monkeypatch.setattr(EP, "_inbox_accounts", lambda: [{"account_id": "a1", "owner": "bob", "host": "imap"},
                                                       {"account_id": "a2", "owner": "ada", "host": "imap"}])
    checked = []

    async def check(account):
        checked.append(account["account_id"])
        return "ok"

    async def quiet(*a, **k):
        return None

    monkeypatch.setattr(EP, "_check_inbox", check)
    monkeypatch.setattr("src.interactive_gate.wait_for_interactive_quiet", quiet)
    out = asyncio.run(EP._inbox_check_pass())
    assert checked == ["a2"]
    assert out["a1"] == TP.paused_sentence("can_use_email")


def test_note_reminders_and_scheduled_mail_wait_rather_than_vanish():
    actions = (ROOT / "src" / "builtin_actions.py").read_text(encoding="utf-8")
    i = actions.index('_may_use_tool(n.owner or owner or "", "can_use_notes")')
    assert "cache[n.id] = now.isoformat()" in actions[i:], "a held reminder is not marked as sent"
    pollers = (ROOT / "routes" / "email_pollers.py").read_text(encoding="utf-8")
    assert 'if r[11] and not _may_use_tool(r[11], "can_use_email"):\n                continue' in pollers


def test_the_codex_bridge_honours_the_switch(auth):
    from fastapi import HTTPException
    from routes import codex_routes as CR
    auth("can_use_notes")
    req = types.SimpleNamespace(state=types.SimpleNamespace(api_token=True, api_token_scopes=["todos:read"],
                                                            api_token_owner="bob"))
    with pytest.raises(HTTPException) as e:
        CR._scope_owner(req, CR.TODO_READ_SCOPES)
    assert e.value.status_code == 403 and e.value.detail.startswith("Notes is switched off")
    req.state.api_token_scopes = ["calendar:read"]
    assert CR._scope_owner(req, CR.CALENDAR_READ_SCOPES) == "bob"


def test_an_unreadable_store_holds_the_work(monkeypatch):
    class Broken(_Auth):
        def get_privileges(self, name):
            raise OSError("auth.json")

    monkeypatch.setattr(TP, "_auth_manager", lambda: Broken())
    assert TP.may_use_tool("bob", "can_use_tasks") is False
    assert TP.may_use_tool(None, "can_use_tasks") is True, "Pantheon's own work names nobody"
