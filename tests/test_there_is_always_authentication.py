# SPDX-License-Identifier: AGPL-3.0-or-later
"""There is always authentication; what an admin toggles is registration.

`D-2026-10-07-02` §2 — the owner, verbatim: *"there is always authentication.
What's toggleable is registration. We keep it this way."*

Until 2026-10-07 three variables let Pantheon answer without a sign-in, measured
on `fcd559e` before this change:

  * `AUTH_ENABLED=false` (or `0`/`no`/`off`, `B96`) — `app.py` never installed
    `AuthMiddleware`, `/login` redirected to `/`, `require_user` answered
    ``""``, `require_admin` returned for everyone, and some twenty route and
    policy helpers waved their nobody through as the owner;
  * `LOCALHOST_BYPASS=true` — the middleware let a direct loopback request in
    with nobody on it, and `require_user` answered ``""`` to it;
  * `PANTHEON_SINGLE_USER` (on by default) — an anonymous calendar request was
    filed under `PANTHEON_FALLBACK_OWNER`, whenever `require_user` answered
    ``""``.

Now each is ignored and said once at start (`warn_ignored_auth_switches`), the
middleware is always there, and every gate asks for a person. Driven two ways
(`Law 20`): the real app booted out of process with each old door set
(`tests/helpers/gated_app.py`), and the gates themselves handed a request with
nobody on it under every old door at once. Registration — `signup_enabled`,
off on a new install — is the one switch, driven off, on and off again through
the real routes; an admin creates accounts whichever way it is set.
"""
from __future__ import annotations

import logging

import pytest
from fastapi import HTTPException

from tests.helpers.gated_app import ADMIN, MEMBER, PASSWORD, gated_app_probe
from tests.helpers.signed_in import PersonRequest, people

# Every old door, opened at once: the old code answered a request with nobody
# on it under any one of these. Each spelling is one the old code honoured.
EVERY_OLD_DOOR = {
    "AUTH_ENABLED": "false",
    "LOCALHOST_BYPASS": "true",
    "PANTHEON_SINGLE_USER": "1",
}
RULING = "D-2026-10-07-02"


# ── the real app, out of process ─────────────────────────────────────────────

_ANONYMOUS = '''
from fastapi.testclient import TestClient
from src import log_once as _log_once

def ask(c, method, path, **kw):
    r = c.request(method, path, follow_redirects=False, **kw)
    return {"status": r.status_code, "location": r.headers.get("location"),
            "page": "authForm" in r.text if r.headers.get("content-type", "").startswith("text/html") else None}

RESULT["said_at_start"] = sorted(k for k in _log_once._said if k.startswith("auth-switch-ignored:"))
'''

_FRESH = _ANONYMOUS + '''
# A stranger and the machine itself, before any account exists.
for label, kw in (("stranger", {}), ("this machine", {"client": ("127.0.0.1", 50000)})):
    c = TestClient(app_module.app, **kw)
    RESULT[label] = {
        "/": ask(c, "GET", "/"),
        "/login": ask(c, "GET", "/login"),
        "/api/sessions": ask(c, "GET", "/api/sessions"),
        "/api/auth/status": c.get("/api/auth/status").json(),
        "/api/health": ask(c, "GET", "/api/health"),
    }
# The first run asks for the admin account, and that account signs in.
c = TestClient(app_module.app)
RESULT["setup"] = c.post("/api/auth/setup", json={"username": "ada", "password": %(pw)r}).status_code
RESULT["login"] = c.post("/api/auth/login", json={"username": "ada", "password": %(pw)r}).status_code
RESULT["signed in"] = {"/api/sessions": ask(c, "GET", "/api/sessions"), "/": ask(c, "GET", "/"),
                       "status": c.get("/api/auth/status").json()}
''' % {"pw": PASSWORD}

_BYPASS = _ANONYMOUS + '''
loop = {"client": ("127.0.0.1", 50000)}
RESULT["this machine, nobody"] = {p: ask(client(None, **loop), "GET", p)
                                  for p in ("/", "/api/sessions", "/api/mcp/servers")}
RESULT["this machine, ada"] = {p: ask(client(ADMIN, **loop), "GET", p)
                               for p in ("/", "/api/sessions", "/api/mcp/servers")}
'''

_AUTH_OFF = _ANONYMOUS + '''
import json
from core.database import ScheduledTask, SessionLocal
from core.middleware import INTERNAL_TOOL_HEADER, INTERNAL_TOOL_TOKEN
import routes.shell_routes as shell_routes

RESULT["nobody"] = {p: ask(client(None), "GET", p) for p in (
    "/", "/api/sessions", "/api/mcp/servers", "/api/calendar/events", "/api/models")}
RESULT["nobody"]["POST /api/shell/exec"] = ask(client(None), "POST", "/api/shell/exec",
                                               json={"command": "true"})
for who in (MEMBER, ADMIN):
    RESULT[who] = {p: ask(client(who), "GET", p) for p in ("/api/sessions", "/api/mcp/servers")}

# `B1181`'s question, asked of an install that has a sign-in: the Forge's
# command route for a signed-in admin, for the loopback acting for her, for the
# lifecycle loop's loopback (naming nobody), and refused to bob. Nothing runs.
ran = []
async def _exec(cmd, timeout=None, **kw):
    ran.append(cmd)
    return {"stdout": "", "stderr": "", "exit_code": 0}
shell_routes._exec_shell = _exec
def loopback(owner):
    h = {INTERNAL_TOOL_HEADER: INTERNAL_TOOL_TOKEN}
    if owner:
        h["X-Pantheon-Owner"] = owner
    c = TestClient(app_module.app, client=("127.0.0.1", 50000))
    return c.post("/api/shell/exec", headers=h, json={"command": "tmux kill-session -t qwen"}).status_code
RESULT["shell"] = {
    "ada": client(ADMIN).post("/api/shell/exec", json={"command": "tmux ls"}).status_code,
    "bob": client(MEMBER).post("/api/shell/exec", json={"command": "tmux ls"}).status_code,
    "ada's loopback": loopback(ADMIN), "nobody's loopback": loopback(None),
    "bob's loopback": loopback(MEMBER), "ran": len(ran),
}
import asyncio
import src.cookbook_serve_lifecycle as lifecycle
import httpx
_real = httpx.AsyncClient
class _Loop(_real):
    def __init__(self, *a, **kw):
        kw.pop("mounts", None)
        kw["transport"] = httpx.ASGITransport(app=app_module.app, client=("127.0.0.1", 50000))
        super().__init__(*a, **kw)
lifecycle.httpx.AsyncClient = _Loop
RESULT["lifecycle stop"] = asyncio.run(lifecycle._stop_serve("qwen"))
RESULT["shell"]["ran"] = len(ran)

# A webhook carries its own credential, and still answers with it.
db = SessionLocal()
db.add(ScheduledTask(id="hook", owner=ADMIN, name="Hook", task_type="llm", prompt="hi",
                     status="active", webhook_token="the-token"))
db.commit(); db.close()
async def _run_now(task_id, trigger=None):
    return True
app_module.task_scheduler.run_task_now = _run_now
RESULT["webhook"] = {"right token": ask(client(None), "POST", "/api/tasks/hook/webhook/the-token"),
                     "wrong token": ask(client(None), "POST", "/api/tasks/hook/webhook/nope")}

# Registration: off on a new install, then on, then off — and an admin adds
# people whichever way it is set.
def signup(name):
    r = client(None).post("/api/auth/signup", json={"username": name, "password": %(pw)r})
    return {"status": r.status_code, "detail": r.json().get("detail")}
def offered():
    return client(None).get("/api/auth/status").json().get("signup_enabled")
def toggle(who, on):
    return client(who).put("/api/auth/open-signup", json={"enabled": on}).status_code
reg = {"new install": {"offered": offered(), "signup": signup("cy")}}
reg["bob turns it on"] = toggle(MEMBER, True)
reg["ada turns it on"] = toggle(ADMIN, True)
reg["on"] = {"offered": offered(), "signup": signup("dee"), "dee signs in": client(None).post(
    "/api/auth/login", json={"username": "dee", "password": %(pw)r}).status_code}
reg["ada turns it off"] = toggle(ADMIN, False)
reg["off again"] = {"offered": offered(), "signup": signup("eve")}
reg["ada adds fay"] = client(ADMIN).post("/api/auth/users", json={
    "username": "fay", "password": %(pw)r}).status_code
reg["accounts"] = sorted(app_module.auth_manager.users)
RESULT["registration"] = reg
''' % {"pw": PASSWORD}


@pytest.fixture(scope="module")
def fresh(tmp_path_factory):
    """A new install with `AUTH_ENABLED=false` set and no account yet."""
    return gated_app_probe(tmp_path_factory.mktemp("fresh"), _FRESH,
                           env_overrides={"AUTH_ENABLED": "false"}, accounts=False)


@pytest.fixture(scope="module")
def bypass(tmp_path_factory):
    return gated_app_probe(tmp_path_factory.mktemp("bypass"), _BYPASS,
                           env_overrides={"LOCALHOST_BYPASS": "true"})


@pytest.fixture(scope="module")
def auth_off(tmp_path_factory):
    return gated_app_probe(tmp_path_factory.mktemp("off"), _AUTH_OFF,
                           env_overrides={"AUTH_ENABLED": "0", "PANTHEON_SINGLE_USER": "on"})


def test_a_fresh_install_with_auth_off_asks_for_the_admin_account(fresh):
    """`AUTH_ENABLED=false` on an install with no account: the stranger and the
    machine itself both get the sign-in page in its first-run shape, and
    nothing else — not the app, not its API."""
    for label in ("stranger", "this machine"):
        got = fresh[label]
        assert got["/"] == {"status": 302, "location": "/login", "page": None}, (label, got)
        assert got["/login"] == {"status": 200, "location": None, "page": True}, (label, got)
        assert got["/api/sessions"]["status"] == 401, (label, got)
        assert got["/api/auth/status"]["configured"] is False, (label, got)
        assert got["/api/health"]["status"] == 200, (label, got)
    assert fresh["said_at_start"] == ["auth-switch-ignored:AUTH_ENABLED"]


def test_the_first_run_account_is_the_admin_and_signs_in(fresh):
    assert (fresh["setup"], fresh["login"]) == (200, 200)
    signed = fresh["signed in"]
    assert signed["/api/sessions"]["status"] == 200
    assert signed["/"]["status"] == 200
    assert signed["status"]["is_admin"] is True and signed["status"]["username"] == "ada"
    assert signed["status"]["signup_enabled"] is False, "registration is off on a new install"


def test_localhost_bypass_lets_nothing_in_from_this_machine(bypass):
    """A direct loopback request — the one `LOCALHOST_BYPASS=true` waved through —
    is a stranger's: the sign-in page and 401s. The same machine signed in as
    ada gets the app."""
    nobody = bypass["this machine, nobody"]
    assert nobody["/"]["status"] == 302 and nobody["/"]["location"] == "/login", nobody
    assert nobody["/api/sessions"]["status"] == 401, nobody
    assert nobody["/api/mcp/servers"]["status"] == 401, nobody
    ada = bypass["this machine, ada"]
    assert {p: v["status"] for p, v in ada.items()} == {
        "/": 200, "/api/sessions": 200, "/api/mcp/servers": 200}, ada
    assert bypass["said_at_start"] == ["auth-switch-ignored:LOCALHOST_BYPASS"]


def test_auth_off_and_single_user_leave_nobody_signed_in(auth_off):
    """`AUTH_ENABLED=0` with `PANTHEON_SINGLE_USER=on`: a caller with no session
    is refused the app, the API, the calendar the single-user owner once caught,
    the model list and the shell; bob is himself and ada is the admin."""
    nobody = auth_off["nobody"]
    assert nobody["/"]["status"] == 302, nobody
    for path, got in nobody.items():
        if path != "/":
            assert got["status"] == 401, (path, got)
    assert auth_off[MEMBER] == {"/api/sessions": {"status": 200, "location": None, "page": None},
                                "/api/mcp/servers": {"status": 403, "location": None, "page": None}}
    assert {p: v["status"] for p, v in auth_off[ADMIN].items()} == {
        "/api/sessions": 200, "/api/mcp/servers": 200}
    assert auth_off["said_at_start"] == ["auth-switch-ignored:AUTH_ENABLED",
                                         "auth-switch-ignored:PANTHEON_SINGLE_USER"]


def test_the_forge_reaches_its_shell_for_an_admin_and_for_whoever_acts_for_her(auth_off):
    """`B1181`'s premise is withdrawn — there is no no-login install — and what it
    asked for holds where there is a sign-in: the command route answers ada,
    her assistant's loopback and the Forge lifecycle loop's (which names
    nobody, and whose window-end stop succeeds), and refuses bob both ways."""
    shell = auth_off["shell"]
    assert {k: shell[k] for k in ("ada", "ada's loopback", "nobody's loopback")} == {
        "ada": 200, "ada's loopback": 200, "nobody's loopback": 200}, shell
    assert (shell["bob"], shell["bob's loopback"]) == (403, 403), shell
    assert auth_off["lifecycle stop"] is True
    assert shell["ran"] == 4, "ada, her loopback, nobody's, and the lifecycle stop — bob ran nothing"


def test_a_webhook_answers_with_its_own_token_and_only_with_it(auth_off):
    hook = auth_off["webhook"]
    assert hook["right token"]["status"] == 200, hook
    assert hook["wrong token"]["status"] == 404, hook


def test_registration_is_off_then_on_then_off_and_an_admin_always_adds_people(auth_off):
    reg = auth_off["registration"]
    refused = {"status": 403, "detail": "Registration is disabled. Ask an admin for an account."}
    assert reg["new install"] == {"offered": False, "signup": refused}
    assert (reg["bob turns it on"], reg["ada turns it on"]) == (403, 200)
    assert reg["on"] == {"offered": True, "signup": {"status": 200, "detail": None},
                         "dee signs in": 200}
    assert reg["ada turns it off"] == 200
    assert reg["off again"] == {"offered": False, "signup": refused}
    assert reg["ada adds fay"] == 200
    assert reg["accounts"] == ["ada", "bob", "dee", "fay"]


# ── the switches, said once ──────────────────────────────────────────────────

@pytest.mark.parametrize("name, raw, named", [
    *[("AUTH_ENABLED", v, True) for v in ("false", "0", "no", "off", " FALSE ")],
    *[("AUTH_ENABLED", v, False) for v in ("true", "1", "", "maybe")],
    *[("LOCALHOST_BYPASS", v, True) for v in ("true", "1", "yes", "on")],
    *[("LOCALHOST_BYPASS", v, False) for v in ("false", "0", "")],
    *[("PANTHEON_SINGLE_USER", v, True) for v in ("1", "true", "on")],
    *[("PANTHEON_SINGLE_USER", v, False) for v in ("0", "off", "")],
])
def test_each_old_door_is_named_when_it_is_set(monkeypatch, name, raw, named):
    from src.owner_identity import ignored_auth_switches
    for other in EVERY_OLD_DOOR:
        monkeypatch.delenv(other, raising=False)
    monkeypatch.setenv(name, raw)
    assert ignored_auth_switches() == ({name: raw} if named else {})


def test_the_warning_is_said_once_and_cites_the_ruling(monkeypatch, caplog):
    import src.log_once as log_once
    from src.owner_identity import warn_ignored_auth_switches
    for name, raw in EVERY_OLD_DOOR.items():
        monkeypatch.setenv(name, raw)
    for name in EVERY_OLD_DOOR:
        log_once.clear(f"auth-switch-ignored:{name}")
    log = logging.getLogger("test.auth-switches")
    with caplog.at_level(logging.DEBUG, logger="test.auth-switches"):
        assert warn_ignored_auth_switches(log) == EVERY_OLD_DOOR
        assert warn_ignored_auth_switches(log) == EVERY_OLD_DOOR
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 3
    for record, name in zip(warnings, EVERY_OLD_DOOR):
        text = record.getMessage()
        assert text.startswith(f"{name}=") and "is ignored" in text and RULING in text, text
        assert "Settings > Users" in text, text
    assert sum(r.levelno == logging.DEBUG for r in caplog.records) == 3


# ── every gate, handed nobody under every old door ───────────────────────────

@pytest.fixture
def every_door_open(monkeypatch, tmp_path):
    """All three old doors set, the request from this machine, and an auth
    manager with accounts — the conditions under which each gate below
    answered nobody before 2026-10-07. Returns the manager."""
    for name, raw in EVERY_OLD_DOOR.items():
        monkeypatch.setenv(name, raw)
    import core.auth
    manager = people(tmp_path / "auth")
    monkeypatch.setattr(core.auth, "_SHARED_AUTH_MANAGER", manager)
    return manager


def _nobody(manager, host="127.0.0.1"):
    return PersonRequest(None, manager, host=host)


def _refused(call):
    with pytest.raises(HTTPException) as caught:
        call()
    return caught.value.status_code


def test_require_user_wants_a_person(every_door_open):
    from src.auth_helpers import require_privilege, require_user
    assert _refused(lambda: require_user(_nobody(every_door_open))) == 401
    assert _refused(lambda: require_privilege(_nobody(every_door_open), "can_use_documents")) == 401
    assert require_user(PersonRequest(MEMBER, every_door_open)) == MEMBER


def test_before_the_first_account_this_machine_is_nobody_too(monkeypatch, tmp_path):
    """The first-run loopback answer `require_user` and the mail gate gave."""
    from core.auth import AuthManager
    from routes.email_helpers import _require_auth
    from src.auth_helpers import require_user
    for name, raw in EVERY_OLD_DOOR.items():
        monkeypatch.setenv(name, raw)
    blank = AuthManager(auth_path=str(tmp_path / "auth.json"))
    assert blank.is_configured is False
    assert _refused(lambda: require_user(_nobody(blank))) == 401
    assert _refused(lambda: _require_auth(_nobody(blank))) == 401


def test_before_the_first_account_nobody_has_an_admins_tasks(monkeypatch, tmp_path):
    """`owner_has_admin_task_privileges` answered every owner — nobody included —
    as an admin until the first account existed, so an install that had run
    without a sign-in kept running its owner-less shell, SSH and serve tasks, and
    a task webhook could start one. Nobody is an admin before setup now, as
    `owner_is_admin_or_single_user` already answered."""
    import core.auth
    from core.auth import AuthManager
    from src.task_action_policy import owner_has_admin_task_privileges
    from src.tool_security import owner_is_admin_or_single_user
    for name, raw in EVERY_OLD_DOOR.items():
        monkeypatch.setenv(name, raw)
    blank = AuthManager(auth_path=str(tmp_path / "auth.json"))
    monkeypatch.setattr(core.auth, "_SHARED_AUTH_MANAGER", blank)
    assert blank.is_configured is False
    for owner in (None, "", ADMIN, "internal-tool-ish"):
        assert owner_has_admin_task_privileges(owner) is False, owner
        assert owner_is_admin_or_single_user(owner) is False, owner


def test_require_admin_wants_an_admin(every_door_open):
    from core.middleware import require_admin
    assert _refused(lambda: require_admin(_nobody(every_door_open))) == 403
    assert _refused(lambda: require_admin(PersonRequest(MEMBER, every_door_open))) == 403
    assert require_admin(PersonRequest(ADMIN, every_door_open)) is None


def test_the_shells_own_gate_wants_an_admin_and_an_auth_manager(every_door_open):
    from routes.shell_routes import _require_admin
    assert _refused(lambda: _require_admin(_nobody(every_door_open))) == 403
    assert _refused(lambda: _require_admin(PersonRequest(ADMIN, None))) == 403
    assert _require_admin(PersonRequest(ADMIN, every_door_open)) is None


@pytest.mark.parametrize("gate, status", [
    ("routes.calendar_routes:_require_user", 401),
    ("routes.email_helpers:_require_auth", 401),
    ("routes.image_proxy_routes:_require_session", 401),
])
def test_each_route_gate_refuses_nobody(every_door_open, gate, status):
    import importlib
    module, name = gate.split(":")
    fn = getattr(importlib.import_module(module), name)
    assert _refused(lambda: fn(_nobody(every_door_open))) == status


def test_a_chat_is_nobodys_to_open(every_door_open):
    from routes.session_routes import _verify_session_owner
    assert _refused(lambda: _verify_session_owner(_nobody(every_door_open), "any-chat")) == 401


def test_a_document_is_nobodys_to_open(every_door_open):
    from types import SimpleNamespace
    from routes.document.document_helpers import _verify_doc_owner
    doc = SimpleNamespace(owner=ADMIN, session_id=None)
    assert _refused(lambda: _verify_doc_owner(None, doc, None)) == 403


def test_the_gallery_shows_nobody_nothing(every_door_open):
    from routes.gallery.gallery_helpers import _owner_filter

    class Query:
        def __init__(self):
            self.filters = []

        def filter(self, *clauses):
            self.filters.append(clauses)
            return self
    q = _owner_filter(Query(), None)
    assert q.filters == [(False,)], "nobody's gallery query is filtered to nothing, not left whole"


def test_the_agent_policies_answer_nobody_no(every_door_open):
    from src import workstation_access
    from src.owner_identity import DEFAULT_LOCAL_OWNER, effective_storage_owner
    from src.task_action_policy import owner_has_admin_task_privileges
    from src.tool_security import blocked_tools_for_owner, owner_is_admin_or_single_user
    assert owner_is_admin_or_single_user(None) is False
    assert blocked_tools_for_owner(None) != set()
    assert owner_has_admin_task_privileges(None) is False
    assert workstation_access.may_use(None) is False
    assert effective_storage_owner(None) is None
    assert effective_storage_owner(DEFAULT_LOCAL_OWNER) == DEFAULT_LOCAL_OWNER
    # And the admin is still the admin.
    assert owner_is_admin_or_single_user(ADMIN) is True
    assert blocked_tools_for_owner(ADMIN) == set()
    assert owner_has_admin_task_privileges(ADMIN) is True
    assert owner_is_admin_or_single_user(MEMBER) is False
