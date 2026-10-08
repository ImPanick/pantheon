# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P20-02` — Pantheon knows whether there is a workstation, and an admin
decides who may use it.

The owner, 2026-09-30: *"Configurable in settings, admin controlled."* Every
test here drives the shipped code: the real settings route and the real
workstation routes on a FastAPI app with a real `AuthManager` over a temporary
auth file, talking to the real daemon (`workstation/agentd.py`) on a local port
through the real client (`tests/helpers/workstation_daemon.py`). Nothing reads a
source file to decide whether a rule holds (`Law 20`), with one exception at
the bottom — that `app.py` mounts the router — resolved through the AST.

What is pinned, and why each is a defect if it breaks:

  * **the keys ship off and empty**, and a destination ships empty
    (`check-destinations.py`'s rule, and the overlay's variable stays reachable);
  * **only an admin writes them**, a bad value is refused at the door with a
    sentence, and the address is stored as the origin the client will call;
  * **the token never reaches a browser**, an admin's included, on any route;
  * **the agent may not move them** — each is a wall it would be moving from
    inside (`_SELF_RESTRAINT_KEYS`);
  * **the privilege**: admins hold it, nobody else does until granted, a role
    can grant it, and a person without it is refused by the routes and by the
    question the tools ask;
  * **a down workstation is reported down with the reason** — its own
    sentence, or the client's when nothing answered;
  * **the admin's `sudo` reaches the daemon**, in both directions;
  * **reset resets only the caller's home**, whatever the request body says;
  * **one person is one account** in no-login mode, whichever spelling of the
    owner arrives.
"""
from __future__ import annotations

import ast
import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import bcrypt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import core.auth
from core.auth import ADMIN_PRIVILEGES, DEFAULT_PRIVILEGES, AuthManager
from src import workstation_access as wa
from src.workstation_client import WorkstationClient, WorkstationError, account_for
from tests.helpers.workstation_daemon import running_workstation
from workstation import protocol as P

ROOT = Path(__file__).resolve().parents[1]
PASSWORD = "correct-horse-battery"
# Five people. `ada` is the admin; `bob` has nothing; `cy` and `dee` were
# granted the workstation by an admin; `eve` gets it from a role.
ADMIN, PLAIN, ALLOWED, ALSO, ROLED = "ada", "bob", "cy", "dee", "eve"


@pytest.fixture(scope="module")
def auth(tmp_path_factory):
    """One auth file for the module. bcrypt at its cheapest cost, because what
    is under test is who may do what, not how a password is hashed."""
    path = tmp_path_factory.mktemp("ws-auth") / "auth.json"
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(core.auth, "_hash_password",
                   lambda pw: bcrypt.hashpw(pw.encode(), bcrypt.gensalt(4)).decode())
        mgr = AuthManager(str(path))
        assert mgr.setup(ADMIN, PASSWORD)
        for name in (PLAIN, ALLOWED, ALSO, ROLED):
            assert mgr.create_user(name, PASSWORD)
    assert mgr.set_privileges(ALLOWED, {wa.PRIVILEGE: True})
    assert mgr.set_privileges(ALSO, {wa.PRIVILEGE: True})
    mgr.define_role("builders", {wa.PRIVILEGE: True})
    assert mgr.set_user_role(ROLED, "builders")
    mgr.tokens = {name: mgr.create_session_trusted(name)
                  for name in (ADMIN, PLAIN, ALLOWED, ALSO, ROLED)}
    return mgr


@pytest.fixture
def datadir(tmp_path, monkeypatch):
    """Settings of our own, by rebinding the names that matter rather than
    reloading the modules that hold them (`B130`); no workstation variable
    from the shell running this; a pairing folder that is empty until a test
    writes a token into it."""
    import src.constants
    import src.settings

    settings_file = str(tmp_path / "settings.json")
    features_file = str(tmp_path / "features.json")
    monkeypatch.setenv("PANTHEON_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(src.constants, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(src.constants, "SETTINGS_FILE", settings_file)
    monkeypatch.setattr(src.constants, "FEATURES_FILE", features_file)
    monkeypatch.setattr(src.settings, "SETTINGS_FILE", settings_file)
    monkeypatch.setattr(src.settings, "FEATURES_FILE", features_file)
    monkeypatch.setenv("AUTH_ENABLED", "true")
    for name in (P.URL_ENV, P.TOKEN_ENV):
        monkeypatch.delenv(name, raising=False)
    pairing = tmp_path / "pairing"
    pairing.mkdir()
    monkeypatch.setenv(P.PAIRING_DIR_ENV, str(pairing))
    src.settings._invalidate_caches()
    yield tmp_path
    src.settings._invalidate_caches()


@pytest.fixture
def app(auth, datadir):
    """The settings routes and the workstation routes, behind the smallest
    stand-in for `AuthMiddleware` there is: the session cookie, resolved by the
    real auth manager. An `X-Test-Bearer` header makes the request what the
    middleware stamps for an API-token caller, so a test can be one."""
    from routes.auth_routes import SESSION_COOKIE, setup_auth_routes
    from routes.workstation_routes import setup_workstation_routes

    application = FastAPI()
    application.state.auth_manager = auth

    @application.middleware("http")
    async def _authenticate(request, call_next):
        request.state.current_user = auth.get_username_for_token(
            request.cookies.get(SESSION_COOKIE))
        bearer = request.headers.get("X-Test-Bearer")
        request.state.api_token = bool(bearer)
        request.state.api_token_owner = bearer or None
        return await call_next(request)

    application.include_router(setup_auth_routes(auth))
    application.include_router(setup_workstation_routes())
    application.cookie_name = SESSION_COOKIE
    return application


def as_user(app, name):
    client = TestClient(app)
    if name:
        client.cookies.set(app.cookie_name, app.state.auth_manager.tokens[name])
    return client


@pytest.fixture
def ws(tmp_path):
    """The real daemon. It starts with `sudo` off; the setting ships on."""
    with running_workstation(tmp_path) as station:
        yield station


def switch_on(app, ws, **extra):
    body = {"workstation_enabled": True, "workstation_url": ws.url,
            "workstation_token": ws.token, **extra}
    r = as_user(app, ADMIN).post("/api/auth/settings", json=body)
    assert r.status_code == 200, r.text
    return r


def stored(key):
    from src.settings import get_setting
    return get_setting(key)


def run(coro):
    return asyncio.run(coro)


# ── the keys ─────────────────────────────────────────────────────────────────

def test_the_keys_ship_off_and_the_destination_ships_empty():
    from src.settings import DEFAULT_SETTINGS
    assert {k: DEFAULT_SETTINGS[k] for k in wa.SETTING_KEYS} == {
        "workstation_enabled": False,
        "workstation_url": "",
        "workstation_token": "",
        "workstation_tls_pin": "",            # `B980`: empty, the environment's beneath it
        "workstation_backend": "container",
        "workstation_sudo": True,
        "workstation_network": "full",
        "workstation_route_tools": True,
    }
    assert DEFAULT_SETTINGS["workstation_backend"] in P.BACKENDS
    assert DEFAULT_SETTINGS["workstation_network"] in P.NETWORK_MODES
    # The fallback `workstation_access` answers with when the settings module
    # cannot be read is a copy; this is what keeps it the same copy.
    assert wa._DEFAULTS == {k: DEFAULT_SETTINGS[k] for k in wa._DEFAULTS}


@pytest.mark.parametrize("who", [PLAIN, ALLOWED, None])
def test_only_an_admin_writes_a_workstation_setting(app, who):
    """`cy` may USE the workstation and still may not configure it. `None` is
    nobody signed in — the settings path is auth-exempt, so the handler's own
    check is the only thing standing here."""
    r = as_user(app, who).post("/api/auth/settings", json={
        "workstation_enabled": True, "workstation_sudo": False,
        "workstation_url": "http://evil.example:7040"})
    assert r.status_code == 403
    assert stored("workstation_enabled") is False
    assert stored("workstation_sudo") is True
    assert stored("workstation_url") == ""


def test_an_admin_writes_them_and_the_address_is_stored_as_the_one_called(app):
    r = as_user(app, ADMIN).post("/api/auth/settings", json={
        "workstation_enabled": True, "workstation_url": "  http://Workstation.lan:7040/  ",
        "workstation_backend": "VM", "workstation_network": "internet",
        "workstation_sudo": False, "workstation_route_tools": False})
    assert r.status_code == 200, r.text
    assert stored("workstation_url") == "http://Workstation.lan:7040"
    assert stored("workstation_backend") == "vm"
    assert stored("workstation_network") == "internet"
    assert (stored("workstation_enabled"), stored("workstation_sudo"),
            stored("workstation_route_tools")) == (True, False, False)


@pytest.mark.parametrize("key,value,words", [
    ("workstation_url", "http://ws:7040/v1/exec", "no path"),
    ("workstation_url", "http://ws:7040/?x=1", "no path"),
    ("workstation_url", "http://user:pw@ws:7040", "no credentials"),
    ("workstation_url", "file:///etc/passwd", "plain http(s)"),
    ("workstation_url", "ws:7040", "plain http(s)"),
    ("workstation_url", 7040, "is text"),
    ("workstation_enabled", "yes", "true or false"),
    ("workstation_sudo", 1, "true or false"),
    ("workstation_route_tools", None, "true or false"),
    ("workstation_backend", "kvm", "container, vm, remote"),
    ("workstation_network", "lan", "full, internet, none"),
    ("workstation_token", "pws_one\nX-Evil: 1", "one line"),
    ("workstation_token", "two words", "no spaces"),
    ("workstation_token", "x" * 513, "at most 512"),
])
def test_a_bad_value_is_refused_at_the_door_with_a_sentence(app, key, value, words):
    """`P17-09`'s lesson: stored and silently ignored is the defect. Nothing of
    the request is stored — the good key beside the bad one included."""
    r = as_user(app, ADMIN).post("/api/auth/settings",
                                 json={"workstation_enabled": True, key: value})
    assert r.status_code == 400
    assert words in r.json()["detail"]
    assert stored("workstation_enabled") is False


def test_an_empty_address_and_an_empty_token_mean_the_next_layer(app):
    as_user(app, ADMIN).post("/api/auth/settings", json={
        "workstation_url": "http://ws:7040", "workstation_token": "pws_abc"})
    r = as_user(app, ADMIN).post("/api/auth/settings", json={
        "workstation_url": "   ", "workstation_token": ""})
    assert r.status_code == 200
    assert stored("workstation_url") == "" and stored("workstation_token") == ""


# ── the token ────────────────────────────────────────────────────────────────

def test_the_token_never_reaches_a_browser_not_even_an_admins(app, ws, datadir, monkeypatch):
    """Every route a page can call, as every kind of caller, with the token
    arriving from each layer in turn — and a wrong token, so the refusal
    sentence is on the list too."""
    secret = ws.token
    texts = []
    admin, allowed, plain = (as_user(app, n) for n in (ADMIN, ALLOWED, PLAIN))

    texts.append(switch_on(app, ws).text)
    for client in (admin, allowed, plain):
        texts.append(client.get("/api/auth/settings").text)
        texts.append(client.get("/api/workstation/status").text)
    texts.append(admin.post("/api/workstation/check").text)
    texts.append(allowed.post("/api/workstation/reset").text)

    # From the environment and from the pairing volume.
    admin.post("/api/auth/settings", json={"workstation_token": ""})
    monkeypatch.setenv(P.TOKEN_ENV, secret)
    texts.append(admin.post("/api/workstation/check").text)
    monkeypatch.delenv(P.TOKEN_ENV)
    (datadir / "pairing" / P.TOKEN_FILENAME).write_text(secret + "\n")
    texts.append(admin.post("/api/workstation/check").text)
    texts.append(admin.get("/api/auth/settings").text)

    # A token the daemon refuses, set by hand: the sentence names the variable.
    wrong = "pws_not-the-token-the-daemon-holds"
    texts.append(admin.post("/api/auth/settings", json={"workstation_token": wrong}).text)
    refused = admin.post("/api/workstation/check")
    texts.append(refused.text)
    texts.append(allowed.post("/api/workstation/reset").text)

    assert refused.json()["error"]["code"] == "unauthorized"
    for text in texts:
        assert secret not in text
        assert wrong not in text
        answer = json.loads(text)
        assert "workstation_token" not in answer, "the key itself came back"
    # And the panel still knows what it needs to.
    view = admin.post("/api/workstation/check").json()["settings"]
    assert view["token_present"] is True and view["token_source"] == "setting"


def test_the_panel_is_told_where_the_address_and_the_token_came_from(app, ws, datadir,
                                                                     monkeypatch):
    admin = as_user(app, ADMIN)
    view = admin.get("/api/workstation/status").json()["settings"]
    assert (view["url"], view["url_source"]) == ("", "none")
    assert (view["token_present"], view["token_source"]) == (False, "none")

    monkeypatch.setenv(P.URL_ENV, ws.url)
    (datadir / "pairing" / P.TOKEN_FILENAME).write_text(ws.token)
    view = admin.get("/api/workstation/status").json()["settings"]
    assert (view["url"], view["url_source"], view["url_setting"]) == (ws.url, "environment", "")
    assert (view["token_present"], view["token_source"]) == (True, "pairing")

    monkeypatch.setenv(P.TOKEN_ENV, "pws_from-the-environment")
    assert admin.get("/api/workstation/status").json()["settings"]["token_source"] == "environment"

    admin.post("/api/auth/settings", json={"workstation_url": "http://elsewhere.lan:7040",
                                           "workstation_token": "pws_typed-here"})
    view = admin.get("/api/workstation/status").json()["settings"]
    assert (view["url"], view["url_source"]) == ("http://elsewhere.lan:7040", "setting")
    assert view["token_source"] == "setting"


# ── the agent ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("key,value", [
    ("workstation_enabled", True),
    ("workstation_route_tools", False),
    ("workstation_url", "http://attacker.example:7040"),
    ("workstation_sudo", False),
    ("workstation_network", "none"),
    ("workstation_backend", "remote"),
    ("workstation_token", "pws_planted"),
])
def test_the_agent_may_read_them_and_may_not_move_them(datadir, key, value):
    """Asserted on the stored value, not the exit code: these refusals answer
    `exit_code: 0` with a sentence (`B42`'s measurement). Both directions: a
    `set` away from the shipped value, and a `reset` back to it from a value an
    admin stored — either is the agent moving the admin's wall."""
    import src.settings as S
    from src.agent_tools.admin_tools import do_manage_settings

    def agent(**args):
        answer = run(do_manage_settings(json.dumps(args)))
        S._invalidate_caches()
        return answer

    shipped = S.get_setting(key)
    assert shipped != value, "precondition: the value has to differ to prove anything"
    answer = agent(action="set", key=key, value=value)
    assert S.get_setting(key) == shipped, f"the agent set {key}"
    assert "Settings" in str(answer.get("response", ""))

    S.save_settings({**S.load_settings(), key: value})   # what an admin chose
    S._invalidate_caches()
    agent(action="reset", key=key)
    assert S.get_setting(key) == value, f"the agent reset {key}"

    read = agent(action="get", key=key)
    assert read.get("exit_code") == 0 and key in read["response"]
    if key == "workstation_token":
        assert value not in json.dumps(read), "the agent was handed the token"


# ── the privilege ────────────────────────────────────────────────────────────

def test_admins_hold_the_privilege_and_nobody_else_does_until_granted(auth):
    assert DEFAULT_PRIVILEGES[wa.PRIVILEGE] is False
    assert ADMIN_PRIVILEGES[wa.PRIVILEGE] is True
    assert wa.may_use(ADMIN, auth_manager=auth) is True
    assert wa.may_use(PLAIN, auth_manager=auth) is False
    assert wa.may_use(ALLOWED, auth_manager=auth) is True
    assert wa.may_use(ROLED, auth_manager=auth) is True, "a role cannot grant it"
    assert wa.may_use(None, auth_manager=auth) is False
    assert wa.may_use("nobody-by-that-name", auth_manager=auth) is False


def test_a_role_offers_it_because_the_registry_declares_it():
    """`P11-02`: a role may override exactly the keys `DEFAULT_PRIVILEGES`
    declares. No role screen exists yet (`P11-11`); the API it will sit on
    accepts this key already, with nothing written for it."""
    from src.roles import privilege_keys, validate_overrides
    assert wa.PRIVILEGE in privilege_keys()
    assert validate_overrides({wa.PRIVILEGE: True}) == {wa.PRIVILEGE: True}


def test_a_person_without_the_privilege_is_refused_and_nothing_is_asked(app, ws):
    switch_on(app, ws)
    plain = as_user(app, PLAIN)
    status = plain.get("/api/workstation/status").json()
    assert status["state"] == wa.STATE_NOT_PERMITTED
    assert status["sentence"] == wa.NOT_PERMITTED_SENTENCE
    assert status["probe"] == wa.PROBE_NOT_CHECKED and status["daemon"] is None
    assert status["you"] is None and "settings" not in status
    r = plain.post("/api/workstation/reset")
    assert r.status_code == 403 and r.json()["detail"] == wa.NOT_PERMITTED_SENTENCE
    assert plain.post("/api/workstation/check").status_code == 403
    # The tools ask the same question and get the same answer.
    with pytest.raises(WorkstationError) as e:
        wa.workstation_for(PLAIN, auth_manager=app.state.auth_manager)
    assert e.value.code == "not_permitted"
    assert wa.routes_tools(PLAIN, auth_manager=app.state.auth_manager) is False
    # Nothing was made for them on the workstation.
    assert account_for(PLAIN) not in ws.system.accounts()


def test_a_person_with_it_is_let_in_and_sees_only_their_own(app, ws):
    switch_on(app, ws)
    allowed = as_user(app, ALLOWED)
    first = allowed.get("/api/workstation/status").json()
    assert first["state"] == wa.STATE_UP and first["probe"] == wa.PROBE_OK
    assert first["may_use"] is True and first["is_admin"] is False
    assert "settings" not in first, "a non-admin was shown the admin's settings"
    assert first["you"]["account"] == account_for(ALLOWED)
    # `B959` (`P20-07`): looking makes nothing. The home is not there until
    # the person or their agent works there, and the panel says so.
    assert first["you"]["home_state"] == wa.HOME_NONE and first["you"]["home"] is None
    assert account_for(ALLOWED) not in ws.system.accounts()
    daemon = first["daemon"]
    assert (daemon["agent"], daemon["protocol"], daemon["backend"]) == (
        P.AGENT_NAME, P.PROTOCOL_VERSION, "container")
    assert daemon["screen"] == [P.SCREEN_WIDTH, P.SCREEN_HEIGHT]
    asyncio.run(wa.ensure_ready(ALLOWED, auth_manager=app.state.auth_manager))
    kept = allowed.get("/api/workstation/status").json()["you"]
    assert kept["home_state"] == wa.HOME_KEPT
    assert Path(kept["home"]) == ws.root / account_for(ALLOWED)
    assert allowed.post("/api/workstation/check").status_code == 403
    assert wa.routes_tools(ALLOWED, auth_manager=app.state.auth_manager) is True
    client, account = wa.workstation_for(ALLOWED, auth_manager=app.state.auth_manager)
    assert account == account_for(ALLOWED) and client.base == ws.url


def test_routing_is_the_admins_switch_and_off_is_the_default_answer(app, ws, auth):
    assert wa.routes_tools(ALLOWED, auth_manager=auth) is False, "off must route nothing"
    switch_on(app, ws, workstation_route_tools=False)
    assert wa.routes_tools(ALLOWED, auth_manager=auth) is False
    as_user(app, ADMIN).post("/api/auth/settings", json={"workstation_route_tools": True})
    assert wa.routes_tools(ALLOWED, auth_manager=auth) is True


def test_an_api_token_does_not_inherit_its_owners_workstation(app, ws):
    """`B70`: every bearer token resolves to the admin who minted it, and a
    credential handed to a third party is not that admin at the keyboard."""
    switch_on(app, ws)
    bearer = TestClient(app, headers={"X-Test-Bearer": ADMIN})
    assert bearer.get("/api/workstation/status").status_code == 403
    assert bearer.post("/api/workstation/reset").status_code == 403


# ── up, down, off ────────────────────────────────────────────────────────────

def test_off_is_said_and_nothing_is_called(app, ws):
    as_user(app, ADMIN).post("/api/auth/settings", json={
        "workstation_url": ws.url, "workstation_token": ws.token})
    status = as_user(app, ALLOWED).get("/api/workstation/status").json()
    assert (status["state"], status["sentence"], status["probe"]) == (
        wa.STATE_OFF, wa.OFF_SENTENCE, wa.PROBE_NOT_CHECKED)
    admin_view = as_user(app, ADMIN).get("/api/workstation/status").json()
    assert admin_view["sentence"] == wa.ADMIN_OFF_SENTENCE
    assert ws.system.accounts() == []
    assert as_user(app, ALLOWED).post("/api/workstation/reset").status_code == 409


def test_the_admin_is_told_what_off_costs_once(app, ws):
    """`B-NEW-5` (P23 round 2). Settings → Workstation said what off costs
    twice, 40 px apart (measured on `a936b5c`): the status card's *The
    workstation is off. Nothing calls it, and the agent's shell, Python and file
    tools run inside Pantheon as they always have.* above the switch's own line
    *Off: the agent's shell, Python and files run inside Pantheon.* Doc 2 § 5:
    once, under the switch. The status says the state; the switch says the
    rest."""
    import html
    import re

    admin_view = as_user(app, ADMIN).get("/api/workstation/status").json()
    assert admin_view["state"] == wa.STATE_OFF
    assert admin_view["sentence"] == "The workstation is off."
    markup = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    under_switch = re.search(r'id="ws-enabled-why">([^<]*)<', markup)
    assert under_switch, "the switch's own line moved"
    why = html.unescape(under_switch.group(1)).strip()
    assert why == "Off: the agent’s shell, Python and files run inside Pantheon."
    assert "inside Pantheon" not in admin_view["sentence"]


def test_check_now_asks_a_workstation_that_is_switched_off(app, ws):
    """So an admin can start the overlay, check it, and then turn it on."""
    as_user(app, ADMIN).post("/api/auth/settings", json={
        "workstation_url": ws.url, "workstation_token": ws.token})
    status = as_user(app, ADMIN).post("/api/workstation/check").json()
    assert status["state"] == wa.STATE_OFF and status["probe"] == wa.PROBE_OK
    assert status["daemon"]["agent"] == P.AGENT_NAME
    assert status["you"]["home_state"] == wa.HOME_UNKNOWN, "an account was made while off"


def test_on_without_an_address_says_so(app):
    as_user(app, ADMIN).post("/api/auth/settings", json={"workstation_enabled": True})
    status = as_user(app, ALLOWED).get("/api/workstation/status").json()
    assert (status["state"], status["sentence"]) == (wa.STATE_UNCONFIGURED,
                                                     wa.UNCONFIGURED_SENTENCE)


class _NotAWorkstation(BaseHTTPRequestHandler):
    """The most likely other listener on a port: something that answers 200."""

    def do_GET(self):  # noqa: N802
        body = b'{"ok": true, "name": "a router admin page"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def stranger():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _NotAWorkstation)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield "http://127.0.0.1:%d" % server.server_address[1]
    server.shutdown()
    server.server_close()


@pytest.mark.parametrize("case", ["nothing_listens", "wrong_token", "not_a_workstation"])
def test_a_down_workstation_is_reported_down_with_the_reason(app, ws, stranger, case):
    url, token, code, words = {
        "nothing_listens": ("http://127.0.0.1:9", ws.token, "unavailable", "did not answer"),
        "wrong_token": (ws.url, "pws_wrong", "unauthorized", "refused Pantheon's token"),
        "not_a_workstation": (stranger, ws.token, "unavailable",
                              "not a Pantheon workstation"),
    }[case]
    as_user(app, ADMIN).post("/api/auth/settings", json={
        "workstation_enabled": True, "workstation_url": url, "workstation_token": token})
    for who in (ALLOWED, ADMIN):
        status = as_user(app, who).get("/api/workstation/status").json()
        assert status["state"] == wa.STATE_DOWN, who
        assert status["probe"] == wa.PROBE_FAILED
        assert status["error"]["code"] == code
        assert words in status["sentence"], status["sentence"]
        assert status["sentence"] == status["error"]["message"]
    r = as_user(app, ALLOWED).post("/api/workstation/reset")
    assert r.status_code in (502, 503) and words in r.json()["detail"]


def test_the_daemons_own_sentence_is_the_one_shown(app, ws):
    """Down for a reason only the daemon knows — here, the home could not be
    looked at — is shown in the daemon's words, not a paraphrase. (`B959`,
    `P20-07`: the status asks `account` now, never `ensure`, so that is the
    answer that fails.)"""
    switch_on(app, ws)

    def refuse(account):
        from workstation.agentd import WorkstationError as DaemonError
        raise DaemonError("unavailable", "The disk the homes live on is full.")

    ws.system.has_home = refuse
    status = as_user(app, ALLOWED).get("/api/workstation/status").json()
    assert status["state"] == wa.STATE_DOWN
    assert status["sentence"] == "The disk the homes live on is full."


# ── sudo ─────────────────────────────────────────────────────────────────────

def test_the_admins_sudo_reaches_the_daemon_both_ways(app, ws):
    assert ws.system.sudo is False, "precondition: the daemon starts with sudo off"
    switch_on(app, ws)
    status = as_user(app, ALLOWED).get("/api/workstation/status").json()
    assert ws.system.sudo is True, "the shipped `sudo` on never reached the daemon"
    assert status["daemon"]["sudo"] is True

    admin = as_user(app, ADMIN)
    admin.post("/api/auth/settings", json={"workstation_sudo": False})
    assert admin.post("/api/workstation/check").json()["daemon"]["sudo"] is False
    assert ws.system.sudo is False
    # And a daemon that restarted — forgetting what it was told — is told again.
    ws.system.set_sudo(True)
    run(wa.ensure_ready(ALLOWED, auth_manager=app.state.auth_manager))
    assert ws.system.sudo is False


def test_ensure_ready_makes_the_account_and_hands_back_what_the_tools_need(app, ws):
    switch_on(app, ws)
    ready = run(wa.ensure_ready(ALSO, auth_manager=app.state.auth_manager))
    assert ready.account == account_for(ALSO)
    assert isinstance(ready.client, WorkstationClient) and ready.client.base == ws.url
    assert ready.home["created"] is True and ready.daemon["sudo"] is True
    assert account_for(ALSO) in ws.system.accounts()
    with pytest.raises(WorkstationError) as e:
        run(wa.ensure_ready(PLAIN, auth_manager=app.state.auth_manager))
    assert e.value.code == "not_permitted"


# ── reset ────────────────────────────────────────────────────────────────────

def test_reset_resets_the_callers_home_and_nobody_elses(app, ws):
    switch_on(app, ws)
    client = WorkstationClient(ws.url, ws.token)
    mine, theirs = account_for(ALLOWED), account_for(ALSO)
    run(client.write(mine, "notes/mine.txt", "cy's work"))
    run(client.write(theirs, "notes/theirs.txt", "dee's work"))

    # The body names dee's account and the route does not read it: there is
    # no parameter through which a caller can say whose home.
    r = as_user(app, ALLOWED).post("/api/workstation/reset", json={"account": theirs,
                                                                   "owner": ALSO})
    assert r.status_code == 200, r.text
    assert r.json()["account"] == mine
    assert run(client.list(mine))["entries"] == []
    assert run(client.read(theirs, "notes/theirs.txt"))["data"] == b"dee's work"


# ── one person, one account ──────────────────────────────────────────────────

def test_auth_enabled_false_is_no_login_mode_any_more(app, ws, monkeypatch):
    """`AUTH_ENABLED=false` was no-login mode: every spelling of nobody — and
    `ada` too — was one account, the single-user owner's, and a request with
    nobody on it was the admin. There is always authentication now
    (`D-2026-10-07-02` §2): with the variable still set, ada is her own account,
    nobody is still the nobody account (never a person's), and a request with
    nobody on it is refused the workstation."""
    from src.owner_identity import DEFAULT_LOCAL_OWNER
    monkeypatch.setenv("AUTH_ENABLED", "false")
    nobody = {wa.account_of(o) for o in (None, "", "  ", DEFAULT_LOCAL_OWNER)}
    assert nobody == {account_for(None)}
    assert wa.account_of(ADMIN) != account_for(None)
    switch_on(app, ws)
    assert as_user(app, None).get("/api/workstation/status").status_code == 401
    status = as_user(app, ADMIN).get("/api/workstation/status").json()
    assert status["is_admin"] is True and status["may_use"] is True
    assert status["you"]["account"] == wa.account_of(ADMIN)
    assert status["state"] == wa.STATE_UP


def test_with_auth_on_two_people_are_two_accounts(monkeypatch):
    from src.owner_identity import DEFAULT_LOCAL_OWNER
    monkeypatch.setenv("AUTH_ENABLED", "true")
    assert wa.account_of(ALLOWED) != wa.account_of(ALSO)
    assert wa.account_of(" cy ") == wa.account_of(ALLOWED)
    # The reserved local bucket was no login's (`RESERVED_AUTH_USERNAMES`), so
    # it is the nobody account, never an account of its own that a person
    # could be handed.
    assert wa.account_of(DEFAULT_LOCAL_OWNER) == account_for(None)


# ── the agent's generic bridge ───────────────────────────────────────────────

@pytest.mark.parametrize("path", ["/api/workstation/reset", "/api/workstation/check",
                                  "/api/x/../workstation/reset", "/api/workstati%6fn/reset"])
def test_the_agents_bridge_cannot_reset_or_check(monkeypatch, path):
    """The bridge is the owner on every route it is not refused (`B896`). A
    reset through it erases a person's home with nobody at the confirmation."""
    import httpx

    from src.tools.system import do_app_api

    def _no_request(*a, **k):
        raise AssertionError("a request was made")

    monkeypatch.setattr(httpx.AsyncClient, "__init__", _no_request)
    answer = run(do_app_api(json.dumps({"action": "call", "method": "POST", "path": path}),
                            owner=ADMIN))
    assert answer["exit_code"] == 1
    assert "Settings → Workstation" in answer["error"]


# ── the mount ────────────────────────────────────────────────────────────────

def test_the_app_mounts_the_router():
    """Importing `app.py` builds the whole product, so the one structural fact
    is read out of its AST: a call to `include_router` whose argument is a call
    to `setup_workstation_routes` — at module scope, where the others are."""
    tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
    found = [
        node for node in tree.body
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
        and getattr(node.value.func, "attr", None) == "include_router"
        and node.value.args and isinstance(node.value.args[0], ast.Call)
        and getattr(node.value.args[0].func, "id", None) == "setup_workstation_routes"
    ]
    assert len(found) == 1
