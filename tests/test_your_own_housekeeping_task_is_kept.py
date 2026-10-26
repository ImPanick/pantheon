# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1063` — a task a person makes with a housekeeping action is theirs: the
built-ins' reconcile does not delete it, rewrite it, or stop it being chained.
`B1215` — the built-in *Chat Sessions Tidy* is *Chats Tidy*, and an install's
stored row under the old name is still the built-in.

**Measured before this file** (`B1063`, on `46f6ce8`, and again here through the
real route and the real reconcile): `POST /api/tasks {"name": "Tidy memories",
"task_type": "action", "action": "consolidate_memory", "trigger_type":
"webhook"}` answered 200 with an id; the next reconcile (`ensure_defaults` — at
boot, for a person new to this process, and on `POST /api/tasks/onboarding`)
kept one task per housekeeping action per owner and `db.delete`d the rest, so
the person's task was gone with no word, and `GET/PUT /api/tasks/<id>` answered
404. A person whose own task was the only one for its action kept it — with
its webhook trigger forced back to the built-in's "every 5 memories".

Driven (`Law 20`): the real task routes over a real SQLite file, the real
`TaskScheduler.ensure_defaults`, and the real scheduler running the chain (the
two actions' far ends recorded — what a memory consolidation does is not what
is under test).
"""
from __future__ import annotations

import asyncio
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from tests.helpers.import_state import clear_fake_database_modules

clear_fake_database_modules()

import core.database as cdb  # noqa: E402
import src.builtin_actions as ba  # noqa: E402
from core.database import ScheduledTask, TaskRun  # noqa: E402
from src.task_scheduler import HOUSEKEEPING_DEFAULTS, TaskScheduler  # noqa: E402

OWNER = "alice"


@pytest.fixture()
def world(monkeypatch, tmp_path):
    import routes.task.task_routes as task_routes
    from tests.helpers.signed_in import signed_in

    monkeypatch.setitem(sys.modules, "core.database", cdb)
    engine = create_engine(f"sqlite:///{tmp_path / 'tasks.db'}",
                           connect_args={"check_same_thread": False}, poolclass=NullPool)
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(cdb, "SessionLocal", factory)
    monkeypatch.setattr(task_routes, "SessionLocal", factory)
    monkeypatch.setenv("BACKGROUND_TASK_FOREGROUND_GATE", "0")
    signed_in(monkeypatch, tmp_path / "auth", admin=OWNER, members=())
    ran = []
    for action in ("consolidate_memory", "audit_skills"):
        async def _done(_action=action, **kwargs):
            ran.append(_action)
            return f"{_action}: done", True
        monkeypatch.setitem(ba.BUILTIN_ACTIONS, action, _done)
    s = TaskScheduler(None)
    s._log_to_assistant = lambda *a, **k: None

    async def _no_assistant(owner):
        return None
    s.ensure_assistant_defaults = _no_assistant   # its own rows; not under test
    app = FastAPI()

    @app.middleware("http")
    async def _who(request, call_next):
        request.state.current_user = OWNER
        return await call_next(request)

    app.include_router(task_routes.setup_task_routes(s))
    return factory, s, TestClient(app), ran


def _rows(factory):
    db = factory()
    try:
        return {t.id: t for t in db.query(ScheduledTask).filter(ScheduledTask.owner == OWNER).all()}
    finally:
        db.close()


def _reconcile(s):
    """What boot, a person new to this process, and the onboarding route run."""
    asyncio.run(s.ensure_defaults(OWNER))


def _mine(client, name, action):
    r = client.post("/api/tasks", json={"name": name, "task_type": "action", "action": action,
                                         "trigger_type": "webhook"})
    assert r.status_code == 200, r.text
    return r.json()["task"]["id"] if "task" in r.json() else r.json()["id"]


def test_a_task_made_with_a_housekeeping_action_survives_the_reconcile_and_can_be_chained(world):
    factory, s, client, ran = world
    _reconcile(s)                                    # the built-ins exist first
    builtin = {t.action: t for t in _rows(factory).values()}["consolidate_memory"]
    assert builtin.name == "Memory Tidy"

    tidy = _mine(client, "Tidy memories", "consolidate_memory")
    audit = _mine(client, "My skills check", "audit_skills")
    r = client.put(f"/api/tasks/{tidy}", json={"then_task_id": audit})
    assert r.status_code == 200, r.text

    _reconcile(s)                                    # a restart
    r = client.post("/api/tasks/onboarding", json={"enabled": True})   # and the onboarding door
    assert r.status_code == 200, r.text

    listed = {t["id"]: t for t in client.get("/api/tasks").json()["tasks"]}
    assert tidy in listed and audit in listed, "the person's tasks were deleted"
    assert client.get(f"/api/tasks/{tidy}").status_code == 200
    mine = _rows(factory)[tidy]
    assert (mine.name, mine.trigger_type, mine.trigger_event) == ("Tidy memories", "webhook", None), \
        "the person's own trigger was rewritten to the built-in's"
    assert mine.then_task_id == audit
    assert listed[tidy]["edges"] == [{"from": tidy, "to": audit, "when": "success"}]
    # The built-in is still there beside it, once.
    actions = [t.action for t in _rows(factory).values()]
    assert actions.count("consolidate_memory") == 2 and actions.count("audit_skills") == 2

    # …and the chain runs through both: P22-04's own `Verify:` shape.
    async def chain():
        await s._execute_task(tidy)
        for _ in range(300):
            await asyncio.sleep(0.01)
            if ran == ["consolidate_memory", "audit_skills"] and not s._executing:
                return
    asyncio.run(chain())
    assert ran == ["consolidate_memory", "audit_skills"]
    db = factory()
    try:
        statuses = {r.task_id: r.status for r in db.query(TaskRun).all()}
    finally:
        db.close()
    assert statuses == {tidy: "success", audit: "success"}


def test_true_duplicates_of_a_built_in_are_still_collapsed(world):
    """`Law 1`: copies the defaults made — the built-in's own name, or a
    legacy one — are still reduced to one, and the one kept is normalised."""
    factory, s, client, ran = world
    _reconcile(s)
    defs = HOUSEKEEPING_DEFAULTS["consolidate_memory"]
    db = factory()
    try:
        db.add(ScheduledTask(id="dup1", owner=OWNER, name=defs["name"], task_type="action",
                             action="consolidate_memory", trigger_type="event",
                             trigger_event=defs["trigger_event"], trigger_count=5, status="active"))
        db.add(ScheduledTask(id="dup2", owner=OWNER, name=defs["legacy_names"][0],
                             task_type="action", action="consolidate_memory",
                             trigger_type="webhook", status="active"))
        db.commit()
    finally:
        db.close()
    _reconcile(s)
    left = [t for t in _rows(factory).values() if t.action == "consolidate_memory"]
    assert len(left) == 1 and left[0].name == defs["name"]


def test_a_persons_only_task_for_an_action_is_left_as_they_made_it(world):
    """No built-in of that action at all (deleted): the reconcile neither
    seeds a second one beside it nor reshapes theirs into the built-in."""
    factory, s, client, ran = world
    _reconcile(s)
    db = factory()
    try:
        db.query(ScheduledTask).filter(ScheduledTask.action == "audit_skills").delete()
        db.commit()
    finally:
        db.close()
    audit = _mine(client, "My skills check", "audit_skills")
    _reconcile(s)
    rows = [t for t in _rows(factory).values() if t.action == "audit_skills"]
    assert [(t.id, t.name, t.trigger_type) for t in rows] == [(audit, "My skills check", "webhook")]


# ── `B1215` ─────────────────────────────────────────────────────────────────

def test_chats_tidy_is_the_built_ins_name_and_an_old_row_is_renamed(world):
    factory, s, client, ran = world
    assert HOUSEKEEPING_DEFAULTS["tidy_sessions"]["name"] == "Chats Tidy"
    # An install from before: the built-in stored under its old name.
    db = factory()
    try:
        db.add(ScheduledTask(id="old", owner=OWNER, name="Chat Sessions Tidy", task_type="action",
                             action="tidy_sessions", trigger_type="event",
                             trigger_event="session_created", trigger_count=5, status="active"))
        db.commit()
    finally:
        db.close()
    listed = {t["id"]: t for t in client.get("/api/tasks").json()["tasks"]}
    assert listed["old"]["name"] == "Chats Tidy", "read old: shown under its new name at once"
    assert listed["old"]["is_builtin"] is True and listed["old"]["is_modified"] is False
    _reconcile(s)
    rows = [t for t in _rows(factory).values() if t.action == "tidy_sessions"]
    assert [(t.id, t.name) for t in rows] == [("old", "Chats Tidy")], "one, renamed, not seeded twice"


def test_its_chat_stays_hidden_under_either_name(world, monkeypatch):
    """The sidebar's list (`GET /api/sessions`, the real route over the real
    `SessionManager.list_page`): the built-in's chat is hidden under its new
    name, and an install's existing one under the old name stays hidden."""
    import uuid

    import core.session_manager as sm_mod
    import routes.session_routes as session_routes
    from core.database import ChatMessage, Session as DbSession
    from src.task_scheduler import task_chat_name

    factory = world[0]
    monkeypatch.setattr(sm_mod, "SessionLocal", factory)
    monkeypatch.setattr(session_routes, "SessionLocal", factory)
    monkeypatch.setattr(session_routes, "effective_user", lambda request: OWNER)
    builtin = type("T", (), {"name": HOUSEKEEPING_DEFAULTS["tidy_sessions"]["name"]})()
    names = [task_chat_name(builtin), "[Task] Chat Sessions Tidy", "My own chat"]
    assert names[0] == "[Task] Chats Tidy"
    db = factory()
    try:
        for name in names:
            sid = str(uuid.uuid4())
            db.add(DbSession(id=sid, owner=OWNER, name=name, endpoint_url="http://x", model="m"))
            db.add(ChatMessage(id=str(uuid.uuid4()), session_id=sid, role="user", content="hi"))
        db.commit()
    finally:
        db.close()
    app = FastAPI()
    app.include_router(session_routes.setup_session_routes(sm_mod.SessionManager(), {}))
    listed = [c["name"] for c in TestClient(app).get("/api/sessions").json()]
    assert listed == ["My own chat"], listed
