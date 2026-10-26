# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1488`, the owner's ruling — the eight Tools entries `B1191` gave a person's
switch get a switch for everyone too.

**Measured before this file:** Assistant, Calendar, Compare, Email, Notes,
Tasks, Theme and Workbench could be switched off for one person
(`src/tool_privileges.py`) and not for the whole install, as Brain, Deep
Research, Gallery and the Library can (`DEFAULT_FEATURES`, `require_feature`,
Settings → Agent Tools). `DEFAULT_FEATURES` had no key for any of them, so
`POST /api/auth/features` dropped one sent to it, and nothing read one.

The shape is the existing one: a feature key per entry
(`tool_privileges.TOOL_FEATURES`), on by default; `require_feature` beside
`tool_privilege` on each router (`everyone_switch`); the agent's tools in
`tool_security._FEATURE_TOOLS`, read from the person's column's own list; every
background hold asks it first (`may_use_tool`), and says the switch that holds
it; the door reads it (`TOOL_VISIBILITY`'s `feature:`) and Settings → Agent
Tools offers it. The row's `Verify:` is Calendar: switched off for everyone it
is gone from every door, its routes refuse everyone, and no one's calendar work
runs — and switched back on, it all comes back. Nothing is deleted.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import types
from pathlib import Path

import pytest

from src import tool_privileges as TP

ROOT = Path(__file__).resolve().parents[1]
UI_VIS = ROOT / "static" / "js" / "ui_visibility.js"
KEYS = ("can_use_assistant", "can_use_calendar", "can_use_compare", "can_use_email",
        "can_use_notes", "can_use_tasks", "can_use_theme", "can_use_workbench")
OFF_FOR_EVERYONE = ("Calendar is switched off for everyone. An admin can turn it back on in "
                    "Settings → Agent Tools.")


class _Auth:
    """ada is an admin; bob is not. Every person switch is on."""
    is_configured = True

    def __init__(self):
        self.users = {"ada": {"is_admin": True}, "bob": {}}

    def is_admin(self, name):
        return name == "ada"

    def get_privileges(self, name):
        from core.auth import ADMIN_PRIVILEGES, DEFAULT_PRIVILEGES
        return dict(ADMIN_PRIVILEGES if name == "ada" else DEFAULT_PRIVILEGES)


@pytest.fixture()
def switches(monkeypatch):
    """`switches(calendar=False, …)`: what the features file says from now on.
    Read where every feature reader reads it (`src.settings.load_features`)."""
    import src.settings as settings_mod
    state = {"features": dict(settings_mod.DEFAULT_FEATURES)}
    monkeypatch.setattr(settings_mod, "load_features", lambda: dict(state["features"]))
    monkeypatch.setattr(TP, "_auth_manager", lambda: _Auth())

    def set_(**flags):
        state["features"] = {**settings_mod.DEFAULT_FEATURES, **flags}
    return set_


# ── the switch exists, once, for each, on ───────────────────────────────────

def test_each_tools_entry_has_a_switch_for_everyone_and_it_ships_on():
    from src.settings import DEFAULT_FEATURES
    assert tuple(sorted(TP.TOOL_FEATURES)) == KEYS == tuple(sorted(TP.TOOL_PRIVILEGES))
    for key, feature in TP.TOOL_FEATURES.items():
        assert DEFAULT_FEATURES[feature] is True, f"{feature} must ship on: nothing changes until an admin says so"


def test_the_features_route_takes_the_new_switch(monkeypatch, tmp_path, request):
    """`POST /api/auth/features` keeps only keys `DEFAULT_FEATURES` has; before
    this row `{"calendar": false}` was dropped and the answer said nothing."""
    import src.settings as settings_mod
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import routes.auth_routes as auth_routes
    from tests.helpers.signed_in import with_session_stamp

    monkeypatch.setattr(settings_mod, "FEATURES_FILE", str(tmp_path / "features.json"))
    settings_mod._invalidate_caches()
    request.addfinalizer(settings_mod._invalidate_caches)   # no cached `calendar: false` outlives this
    monkeypatch.setattr(auth_routes, "migrate_from_settings", lambda: None)

    class _Manager:
        is_configured = True

        def get_username_for_token(self, token):
            return {"admin-session": "ada"}.get(token)

        def is_admin(self, name):
            return name == "ada"

    manager = _Manager()
    app = with_session_stamp(FastAPI(), manager)
    app.include_router(auth_routes.setup_auth_routes(manager))
    client = TestClient(app)
    client.cookies.set(auth_routes.SESSION_COOKIE, "admin-session")
    r = client.post("/api/auth/features", json={"calendar": False})
    assert r.status_code == 200 and r.json()["calendar"] is False, r.text
    settings_mod._invalidate_caches()
    assert settings_mod.load_features()["calendar"] is False
    assert client.get("/api/auth/features").json()["calendar"] is False


# ── the routes refuse everyone ──────────────────────────────────────────────

def _app(dependencies):
    from fastapi import APIRouter, Depends, FastAPI
    from fastapi.testclient import TestClient
    router = APIRouter(prefix="/api/x", dependencies=[Depends(d) for d in dependencies])

    @router.get("/thing")
    def thing():
        return {"ok": True}

    app = FastAPI()
    app.state.auth_manager = _Auth()

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


def test_off_for_everyone_the_route_refuses_everyone_in_the_doors_words(switches):
    switches(calendar=False)
    client = _app([TP.everyone_switch("can_use_calendar"), TP.tool_privilege("can_use_calendar")])
    for headers in ({"x-user": "ada"}, {"x-user": "bob"}, {"x-token": "ada"}, {}):
        r = client.get("/api/x/thing", headers=headers)
        assert r.status_code == 403, headers
        assert r.json()["detail"] == OFF_FOR_EVERYONE, headers
    switches()
    for headers in ({"x-user": "ada"}, {"x-user": "bob"}, {}):
        assert client.get("/api/x/thing", headers=headers).status_code == 200, "back on: all it takes"


def _deps(router) -> list:
    return [d.dependency.__name__ for d in router.dependencies]


@pytest.mark.parametrize("module, setup, args, key", [
    ("routes.calendar_routes", "setup_calendar_routes", (), "can_use_calendar"),
    ("routes.note.note_routes", "setup_note_routes", (), "can_use_notes"),
    ("routes.compare.compare_routes", "setup_compare_routes", (object(),), "can_use_compare"),
    ("routes.assistant_routes", "setup_assistant_routes", (None,), "can_use_assistant"),
    ("routes.workflow.workflow_routes", "setup_workflow_routes", (None,), "can_use_workbench"),
])
def test_each_tools_router_carries_the_switch_for_everyone_first(module, setup, args, key):
    """Built, not read: the router's own dependencies, in the order they run."""
    import importlib
    router = getattr(importlib.import_module(module), setup)(*args)
    feature = TP.TOOL_FEATURES[key]
    assert _deps(router)[:2] == [f"require_feature_{feature}", f"require_{key}"], _deps(router)


def test_the_email_router_carries_it_too():
    """`setup_email_routes` starts the mail poller, so it is read here, as
    `B1191`'s test reads it — inside the one call that builds the router."""
    src = (ROOT / "routes" / "email_routes.py").read_text(encoding="utf-8")
    call = src[src.index('router = APIRouter(prefix="/api/email"'):]
    call = call[:call.index("])") + 2]
    assert '_everyone_switch("can_use_email")' in call and '_tool_privilege("can_use_email")' in call
    assert call.index("_everyone_switch") < call.index("_tool_privilege")


def test_task_data_follows_both_columns_of_both_doors(switches):
    from routes.task.task_routes import _tasks_gate
    client = _app([_tasks_gate])
    switches(tasks=False)
    assert client.get("/api/x/thing", headers={"x-user": "bob"}).status_code == 200, \
        "the Workbench's Automations room still reads the task data"
    switches(tasks=False, workbench=False)
    r = client.get("/api/x/thing", headers={"x-user": "ada"})
    assert r.status_code == 403
    assert r.json()["detail"] == ("Tasks is switched off for everyone. An admin can turn it back on in "
                                  "Settings → Agent Tools.")


# ── the agent's tools go ────────────────────────────────────────────────────

def test_the_agent_loses_the_same_tools_the_persons_switch_takes():
    from src.tool_security import feature_disabled_tools
    for key, feature in TP.TOOL_FEATURES.items():
        assert feature_disabled_tools({feature: False}) == set(TP.TOOL_PRIVILEGES[key][1]), feature
    assert feature_disabled_tools({"calendar": False}) == {"manage_calendar"}


def test_the_switch_for_everyone_is_withheld_as_a_feature_not_as_the_persons(switches):
    switches(calendar=False)
    assert TP.withheld_for_owner("bob") == set(), "the person's column did not take it"
    from src.tool_security import feature_disabled_tools
    assert "manage_calendar" in feature_disabled_tools()


# ── no one's work runs, and it says why ─────────────────────────────────────

def _task(**kw):
    base = dict(id="t1", owner="bob", task_type="llm", action=None, crew_member_id=None, name="nightly")
    base.update(kw)
    return types.SimpleNamespace(**base)


def test_no_ones_calendar_work_runs(switches):
    switches(calendar=False)
    for owner in ("bob", "ada", None, ""):
        assert TP.may_use_tool(owner, "can_use_calendar") is False, owner
        assert TP.held_by_switch(None, _task(owner=owner, task_type="action",
                                             action="classify_events")) == "can_use_calendar", owner
    assert TP.held_by_switch(None, _task(task_type="action", action="tidy_sessions")) is None
    switches()
    assert TP.held_by_switch(None, _task(owner="bob", task_type="action", action="classify_events")) is None


def test_a_held_run_names_the_switch_for_everyone(switches):
    switches(tasks=False)
    assert TP.held_by_switch(None, _task(owner="ada")) == "can_use_tasks"
    said = TP.paused_sentence("can_use_tasks")
    assert said == ("Paused: Tasks is switched off for everyone. Nothing was deleted; an admin can turn "
                    "it back on in Settings → Agent Tools, and it runs again from then.")
    switches()
    assert "for this account" in TP.paused_sentence("can_use_tasks")


def test_the_scheduler_records_the_sentence_and_keeps_the_task(tmp_path, monkeypatch, switches):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import core.database as cdb
    from src import task_scheduler as TS
    switches(tasks=False)
    engine = create_engine(f"sqlite:///{tmp_path / 't.db'}")
    cdb.Base.metadata.create_all(engine, tables=[cdb.Session.__table__, cdb.ScheduledTask.__table__,
                                                 cdb.TaskRun.__table__])
    db = sessionmaker(bind=engine)()
    task = cdb.ScheduledTask(id="t1", owner="ada", name="nightly", status="active")
    db.add(task)
    db.add(cdb.TaskRun(id="r1", task_id="t1", status="queued"))
    db.commit()
    told = []
    sched = TS.TaskScheduler.__new__(TS.TaskScheduler)
    monkeypatch.setattr(TS.TaskScheduler, "_notify_run_outcome",
                        lambda self, task, status, body=None, task_id=None, **k: told.append(body))
    # `B1540`: the finished run's next time is set by `_set_next_run_after` now.
    monkeypatch.setattr(TS.TaskScheduler, "_set_next_run_after",
                        lambda self, db, task: setattr(task, "next_run", None))
    sched._skip_switched_off(db, task, "r1", TP.held_by_switch(db, task))
    run = db.get(cdb.TaskRun, "r1")
    assert run.status == "skipped" and "switched off for everyone" in run.result
    assert told and "Settings → Agent Tools" in told[0]
    assert db.get(cdb.ScheduledTask, "t1").status == "active", "nothing is deleted or switched off"


def test_the_inbox_check_holds_everyones_mail(switches, monkeypatch):
    import routes.email_pollers as EP
    switches(email=False)
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
    assert checked == []
    assert out["a1"] == out["a2"] == TP.paused_sentence("can_use_email")
    assert "for everyone" in out["a1"]


def test_the_codex_bridge_refuses_in_the_everyone_words(switches):
    from fastapi import HTTPException
    from routes import codex_routes as CR
    switches(calendar=False)
    req = types.SimpleNamespace(state=types.SimpleNamespace(api_token=True, api_token_scopes=["calendar:read"],
                                                            api_token_owner="ada"))
    with pytest.raises(HTTPException) as e:
        CR._scope_owner(req, CR.CALENDAR_READ_SCOPES)
    assert e.value.status_code == 403 and e.value.detail == OFF_FOR_EVERYONE


# ── the door goes, and Settings → Agent Tools offers it ─────────────────────

def _node(script: str) -> dict:
    harness = (
        "const nodes = {};\n"
        "for (const id of ['tool-calendar-btn', 'rail-calendar', 'tool-notes-btn', 'rail-notes'])"
        " nodes[id] = { id, style: { display: '' }, parentNode: null };\n"
        "const document = { getElementById: (id) => nodes[id] || null };\n"
        "const toasts = [];\n"
        "globalThis.window = { addEventListener() {}, uiModule: { showToast: (m) => toasts.push(String(m)) } };\n"
        f"const V = await import({json.dumps(UI_VIS.as_uri())});\n"
        "const shown = (id) => nodes[id].style.display !== 'none';\n"
        + script
    )
    proc = subprocess.run(["node", "--input-type=module", "-e", harness], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")
def test_calendar_off_for_everyone_is_gone_from_every_door_and_comes_back():
    out = _node("""
        const features = {};
        for (const [k, d] of Object.entries(V.TOOL_VISIBILITY)) if (d.privilege && typeof d.privilege === 'string'
            && /^can_use_(assistant|calendar|compare|email|notes|tasks|theme|workbench)$/.test(d.privilege)) features[k] = d.feature;
        V.applyToolVisibility({ features: { calendar: false }, privileges: { can_use_calendar: true }, auth: true }, document);
        const off = { button: shown('tool-calendar-btn'), rail: shown('rail-calendar'), notes: shown('tool-notes-btn'),
          slash: V.toolDoor({ slash: 'event' }), url: V.toolDoor({ route: '/calendar' }),
          shortcut: V.toolDoor({ shortcut: 'open_calendar' }), window: V.toolDoor({ window: 'calendar-modal' }),
          column: V.toolOff('calendar'), said: V.toolRefusal('calendar') };
        V.applyToolVisibility({ features: { calendar: true } }, document);
        const on = { button: shown('tool-calendar-btn'), rail: shown('rail-calendar'), door: V.toolDoor('calendar') };
        console.log(JSON.stringify({ features, off, on, toasts }));
    """)
    assert out["features"] == {"assistant": "assistant", "calendar": "calendar", "compare": "compare",
                               "email": "email", "notes": "notes", "tasks": "tasks", "theme": "theme",
                               "workbench": "workbench"}
    off = out["off"]
    assert off["button"] is False and off["rail"] is False and off["notes"] is True
    assert off["slash"] is off["url"] is off["shortcut"] is off["window"] is False
    assert off["column"] == "everyone" and off["said"] == OFF_FOR_EVERYONE
    assert out["toasts"] and set(out["toasts"]) == {OFF_FOR_EVERYONE}
    assert out["on"] == {"button": True, "rail": True, "door": True}


@pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")
def test_settings_agent_tools_offers_each_switch_and_says_what_it_holds(tmp_path_factory):
    from test_tool_effect_surfaces_js import _make_sandbox, _run
    from test_the_workshop_surfaces_js import _index_ids
    from test_the_admin_panels_that_never_rendered import (
        ADMIN_JS, _ADMIN_SHIM, _ADMIN_STUBS, _PREAMBLE, _wh_event_values,
    )
    from src.settings import DEFAULT_FEATURES
    shim = (_ADMIN_SHIM.replace("__IDS__", json.dumps(_index_ids()))
            .replace("__WH_EVENTS__", json.dumps(_wh_event_values())))
    box = _make_sandbox(tmp_path_factory.mktemp("b1488-admin"), ADMIN_JS, shim, _ADMIN_STUBS)
    features = {**DEFAULT_FEATURES, "calendar": False}
    out = _run(box, _PREAMBLE, """
        mockAdminFetch((url) => url.includes('/api/auth/features') ? res(200, %s) : res(200, {}));
        await adminModule._initData();
        await tick();
        console.log(JSON.stringify({ toggles: html('adm-featureToggles') }));
    """ % json.dumps(features))
    body = out["toggles"]
    for key, feature in TP.TOOL_FEATURES.items():
        assert f'data-adm-feature="{feature}"' in body, feature
    row = body[body.index('data-adm-feature="calendar"') - 600:body.index('data-adm-feature="calendar"') + 40]
    assert "Off hides Calendar." in row
    assert 'data-adm-feature="calendar" ' in body and 'data-adm-feature="calendar" checked' not in body, \
        "the stored state reaches the switch"
    assert "Off also holds every scheduled task" in body
