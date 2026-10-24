# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P27-03` / `P27-06` — each person's vault, and signing in from it by name.

Driven, not read (`Law 20`): a real SQLite database and the real key wrapping
for the vault; the real routes over HTTP; and for the sign-in, the real daemon
starting a real Firefox against a sign-in form served on this machine, which
records what it was sent — so the password is seen arriving at the service
and nowhere else: not in the tool's answer, the activity the window shows, the
page text the agent reads, or the database.

**Measured before this file, on `ee381ac`:** the only vault was the server's
Bitwarden link, an admin's (`routes/vault/`). An agent that had to sign in to
a service was handed the password in the chat and typed it — into the
transcript, the activity feed and every later turn's context.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from src import vault as V

FIREFOX = shutil.which("firefox")
needs_firefox = pytest.mark.skipif(FIREFOX is None, reason="Firefox is not installed here")
PASSWORD = "Pw-correct-horse-77"


@pytest.fixture()
def db(tmp_path, monkeypatch):
    import core.database as cdb
    import src.secret_storage as ss
    engine = create_engine(f"sqlite:///{tmp_path / 'vault.db'}", connect_args={"check_same_thread": False},
                           poolclass=NullPool)
    cdb.Base.metadata.create_all(engine, tables=[cdb.VaultKey.__table__, cdb.VaultItem.__table__,
                                                 cdb.GitIdentity.__table__, cdb.GitCredential.__table__])
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(cdb, "SessionLocal", factory)
    monkeypatch.setattr(ss, "_KEY_PATH", tmp_path / ".app_key")
    monkeypatch.setattr(ss, "_fernet", None)
    import src.workstation_access as wa
    monkeypatch.setattr(wa, "routes_tools", lambda owner, **kw: False)
    V._unlocked_until.clear()
    factory.engine_path = tmp_path / "vault.db"
    return factory


def _login(s, owner="alice", **over):
    body = {"label": "Grafana (agent)", "addresses": "grafana.lan:3000", "username": "agent",
            "secret": PASSWORD}
    body.update(over)
    return V.create(s, owner, body)


# ── addresses ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,origin", [
    ("grafana.lan:3000", "http://grafana.lan:3000"),
    ("grafana.lan", "http://grafana.lan"),
    ("10.0.0.5:8080/login", "http://10.0.0.5:8080"),
    ("localhost:5173", "http://localhost:5173"),
    ("nas", "http://nas"),
    ("example.org", "https://example.org"),
    ("https://Example.org:443/sign-in?x=1", "https://example.org"),
    ("http://example.org:80", "http://example.org"),
    ("https://jellyfin.home.arpa:8920", "https://jellyfin.home.arpa:8920"),
])
def test_an_address_is_an_origin(raw, origin):
    assert V.origin_of(raw) == origin


@pytest.mark.parametrize("raw", ["", "ftp://x.org", "javascript:alert(1)", "two words", "http://"])
def test_anything_else_is_refused_in_a_sentence(raw):
    with pytest.raises(V.VaultRefused):
        V.origin_of(raw)


# ── the store ───────────────────────────────────────────────────────────────

def test_a_secret_is_sealed_with_the_persons_own_key_and_never_said_back(db):
    s = db()
    item = _login(s, totp="JBSWY3DPEHPK3PXP", notes="role: Viewer")
    assert item["has_secret"] and item["has_totp"] and item["has_notes"]
    assert item["addresses"] == ["http://grafana.lan:3000"] and item["username"] == "agent"
    assert PASSWORD not in json.dumps(item) and "JBSWY3DP" not in json.dumps(item)
    listed = V.listing(s, "alice")
    assert PASSWORD not in json.dumps(listed)
    raw = db.engine_path.read_bytes()
    assert PASSWORD.encode() not in raw and b"JBSWY3DP" not in raw and b"role: Viewer" not in raw, \
        "the database holds ciphertext only"
    from core.database import VaultKey
    key_row = s.query(VaultKey).one()
    assert key_row.wrapped.startswith("enc:"), "the person's key is wrapped by the server's"


def test_one_persons_vault_is_nobody_elses(db):
    s = db()
    item = _login(s)
    assert V.listing(s, "bob")["items"] == []
    with pytest.raises(V.VaultRefused) as nope:
        V.for_use(s, "bob", "Grafana (agent)")
    assert nope.value.status == 404 and "Grafana" not in nope.value.sentence.split("vault.")[1]
    for fn in (lambda: V.reveal(s, "bob", item["id"]), lambda: V.remove(s, "bob", item["id"]),
               lambda: V.update(s, "bob", item["id"], {"label": "mine now"})):
        with pytest.raises(V.VaultRefused) as e:
            fn()
        assert e.value.status == 404, "another person's item is not found, never forbidden"
    from core.database import VaultKey
    assert s.query(VaultKey).count() == 1, "bob asking made him no key and opened none"


def test_using_an_item_by_name_gives_the_values_once_and_records_the_use(db):
    s = db()
    _login(s, totp="JBSWY3DPEHPK3PXP")
    got = V.for_use(s, "alice", "grafana (AGENT)", by="agent_browser")
    assert got["secret"] == PASSWORD and got["origins"] == ["http://grafana.lan:3000"]
    assert len(got["otp"]) == 6 and got["otp"].isdigit(), "a one-time code is made at the moment of use"
    item = V.listing(s, "alice")["items"][0]
    assert item["last_used_by"] == "agent_browser" and item["last_used_at"]
    with pytest.raises(V.VaultRefused) as missing:
        V.for_use(s, "alice", "Gitea")
    assert "Your vault has: “Grafana (agent)”." in missing.value.sentence, "names, never values"


def test_an_edit_keeps_what_it_leaves_out(db):
    s = db()
    item = _login(s)
    V.update(s, "alice", item["id"], {"label": "Grafana", "username": "agent2"})
    got = V.for_use(s, "alice", "Grafana")
    assert got["secret"] == PASSWORD and got["username"] == "agent2"
    with pytest.raises(V.VaultRefused):
        V.update(s, "alice", item["id"], {"secret": ""})   # a login cannot lose its password
    with pytest.raises(V.VaultRefused) as dup:
        _login(s, label="grafana")
    assert dup.value.status == 409


@pytest.mark.parametrize("body,words", [
    ({"label": ""}, "Give the item a name"),
    ({"addresses": ""}, "needs the address"),
    ({"secret": ""}, "needs its password"),
    ({"totp": "not base32!"}, "one-time-code secret"),
    ({"kind": "bank"}, "“kind” is one of"),
    ({"use": "always"}, "“use” is one of"),
])
def test_a_bad_item_is_refused_in_a_sentence(db, body, words):
    with pytest.raises(V.VaultRefused) as e:
        _login(db(), **body)
    assert words in e.value.sentence


def test_a_locked_vault_refuses_the_agent_and_says_where_to_unlock(db):
    s = db()
    _login(s)
    V.set_idle(s, "alice", 15)
    assert not V.is_locked(s, "alice"), "setting a lock time does not lock you out mid-sentence"
    V.lock_now("alice")
    assert V.is_locked(s, "alice")
    with pytest.raises(V.VaultRefused) as locked:
        V.for_use(s, "alice", "Grafana (agent)")
    assert locked.value.status == 423 and "Settings → Vault" in locked.value.sentence
    assert V.listing(s, "alice")["items"][0]["username"] == "", "a locked vault shows names only"
    V.unlock(s, "alice")
    assert V.for_use(s, "alice", "Grafana (agent)")["secret"] == PASSWORD
    with pytest.raises(V.VaultRefused):
        V.set_idle(s, "alice", -1)


def test_scrub_hides_every_value_in_text_a_command_or_page_echoes():
    assert V.scrub(f"login failed for agent:{PASSWORD}", ["agent", PASSWORD]) == "login failed for ••••:••••"


# ── over HTTP ───────────────────────────────────────────────────────────────

class _Auth:
    is_configured = True

    @staticmethod
    def verify_password(user, password):
        return password == f"{user}-pw"


@pytest.fixture()
def client(db, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import routes.vault_mine_routes as R
    monkeypatch.setattr(R, "SessionLocal", db)   # bound at import: this test's database, not the first's
    monkeypatch.setattr(R, "get_current_user", lambda request: request.headers.get("x-user"))
    monkeypatch.setattr(R, "request_is_a_person", lambda request: request.headers.get("x-token") is None)
    app = FastAPI()
    app.state.auth_manager = _Auth()
    app.include_router(R.setup_vault_mine_routes())
    return TestClient(app)


def test_the_routes_answer_only_the_callers_own_and_reveal_asks_again(client):
    a = {"x-user": "alice"}
    made = client.post("/api/vault/mine/items", headers=a,
                       json={"label": "NAS", "addresses": ["nas.lan"], "username": "agent", "secret": PASSWORD})
    assert made.status_code == 200 and PASSWORD not in made.text
    iid = made.json()["id"]
    assert client.get("/api/vault/mine", headers={"x-user": "bob"}).json()["items"] == []
    assert PASSWORD not in client.get("/api/vault/mine", headers=a).text
    wrong = client.post(f"/api/vault/mine/items/{iid}/reveal", headers=a, json={"password": "nope"})
    assert wrong.status_code == 403 and "Nothing was shown" in wrong.json()["detail"]
    shown = client.post(f"/api/vault/mine/items/{iid}/reveal", headers=a, json={"password": "alice-pw"})
    assert shown.json()["secret"] == PASSWORD
    other = client.post(f"/api/vault/mine/items/{iid}/reveal", headers={"x-user": "bob"}, json={"password": "bob-pw"})
    assert other.status_code == 404
    token = client.post("/api/vault/mine/items", headers={"x-user": "alice", "x-token": "1"},
                        json={"label": "X", "addresses": "x.org", "secret": "s"})
    assert token.status_code == 403 and "Only a person" in token.json()["detail"]
    assert client.put(f"/api/vault/mine/items/{iid}", headers=a, json={"use": "allowed"}).json()["use"] == "allowed"


def test_locking_over_http_and_unlocking_asks_for_the_password(client):
    a = {"x-user": "alice"}
    client.post("/api/vault/mine/items", headers=a,
                json={"label": "NAS", "addresses": ["nas.lan"], "secret": PASSWORD})
    assert client.put("/api/vault/mine/lock", headers=a, json={"idle_minutes": 5}).json()["locked"] is False
    assert client.put("/api/vault/mine/lock", headers=a, json={"locked": True}).json()["locked"] is True
    stays = client.put("/api/vault/mine/lock", headers=a, json={"locked": False, "password": "x"})
    assert stays.status_code == 403 and "stays locked" in stays.json()["detail"]
    added = client.post("/api/vault/mine/items", headers=a, json={"label": "Y", "addresses": "y.org", "secret": "s"})
    assert added.status_code == 423, "a locked vault takes nothing new either"
    assert client.put("/api/vault/mine/lock", headers=a,
                      json={"locked": False, "password": "alice-pw"}).json()["locked"] is False


# ── signing in, with a real Firefox ─────────────────────────────────────────

FORM = b"""<html><head><title>Sign in</title></head><body><h1>Grafana</h1>
<form method=post action='/login'>
<input name=user autocomplete=username placeholder='Email or username'>
<input name=password type=password placeholder='Password'>
<button>Log in</button></form></body></html>"""

TWO_STEP = b"""<html><head><title>Who are you</title></head><body>
<form method=post action='/step2'><input name=login placeholder='Username'><button>Next</button></form></body></html>"""

STEP2 = b"""<html><head><title>Password</title></head><body>
<form method=post action='/login'><input type=password name=password><button>Sign in</button></form></body></html>"""


class _Service(BaseHTTPRequestHandler):
    posts: list = []

    def log_message(self, *a):
        pass

    def _send(self, body: bytes):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send({"/": FORM, "/two": TWO_STEP}.get(self.path, b"<title>Other</title><p>other</p>"))

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        form = {k: v[0] for k, v in parse_qs(self.rfile.read(n).decode()).items()}
        self.posts.append((self.path, form))
        if self.path == "/step2":
            self._send(STEP2)
        elif form.get("password") == PASSWORD:
            self._send(b"<title>Home</title><p>Welcome, agent</p>")
        else:
            self._send(FORM.replace(b"<h1>Grafana</h1>", b"<h1>Wrong password</h1>"))


@pytest.fixture(scope="module")
def service():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Service)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.fixture(scope="module")
def station(tmp_path_factory):
    if FIREFOX is None:
        pytest.skip("Firefox is not installed here")
    from workstation.agentd import SingleUserSystem, Workstation
    ws = Workstation(SingleUserSystem(tmp_path_factory.mktemp("vault-home")), "tok")
    yield ws
    ws.browsers.stop_all()


ACCOUNT = "pw-ann-0123abcd"


@needs_firefox
def test_the_daemon_fills_the_form_only_on_the_logins_own_origin(station, service):
    from workstation.agentd import WorkstationError
    _Service.posts.clear()
    station.browser(ACCOUNT, {"action": "open", "url": service + "/"})
    body = {"action": "login", "origins": ["http://grafana.lan:3000"], "label": "Grafana (agent)",
            "username": "agent", "secret": PASSWORD, "otp": ""}
    with pytest.raises(WorkstationError) as elsewhere:
        station.browser(ACCOUNT, body)
    assert "Nothing was filled" in elsewhere.value.message and PASSWORD not in elsewhere.value.message
    assert _Service.posts == [], "a look-alike page is sent nothing"

    body["origins"] = [service]
    got = station.browser(ACCOUNT, body)
    assert got["filled"] == ["user name", "password"] and got["title"] == "Home"
    assert got["still_asking"] is False
    assert _Service.posts == [("/login", {"user": "agent", "password": PASSWORD})]
    assert PASSWORD not in json.dumps(got)
    activity = station.browser(ACCOUNT, {"action": "frame", "since": 0})["activity"]
    assert any(a["label"] == "Signing in with “Grafana (agent)”" for a in activity)
    assert PASSWORD not in json.dumps(activity)


@needs_firefox
def test_a_two_step_sign_in_and_a_filled_password_never_read_out(station, service):
    _Service.posts.clear()
    station.browser(ACCOUNT, {"action": "open", "url": service + "/two"})
    got = station.browser(ACCOUNT, {"action": "login", "origins": [service], "label": "G",
                                    "username": "agent", "secret": PASSWORD, "otp": ""})
    assert got["filled"] == ["user name", "password"] and got["title"] == "Home"
    assert [p for p, _ in _Service.posts] == ["/step2", "/login"]

    station.browser(ACCOUNT, {"action": "open", "url": service + "/"})
    page = station.browser(ACCOUNT, {"action": "read"})
    station.browser(ACCOUNT, {"action": "type", "ref": 2, "text": PASSWORD})
    page = station.browser(ACCOUNT, {"action": "read"})
    assert PASSWORD not in json.dumps(page), "a filled password field is read as its placeholder"
    assert any(e.get("type") == "password" and e["label"] == "Password" for e in page["elements"])

    wrong = station.browser(ACCOUNT, {"action": "login", "origins": [service], "label": "G",
                                      "username": "agent", "secret": "wrong-one", "otp": ""})
    assert wrong["still_asking"] is True, "a refused sign-in is said, not assumed"


# ── the tool, through the dispatcher ────────────────────────────────────────

@pytest.fixture
def daemon_up(tmp_path, monkeypatch, db):
    if FIREFOX is None:
        pytest.skip("Firefox is not installed here")
    from tests.helpers.workstation_daemon import running_workstation
    from tests.test_the_agent_works_the_workstation_screen import configure
    with running_workstation(tmp_path) as ws:
        configure(monkeypatch, ws)
        yield ws


@needs_firefox
def test_the_agent_signs_in_by_name_and_never_sees_the_password(daemon_up, service, db):
    from src.agent_tools import ToolBlock
    from src.tool_execution import NO_TOOL_SECURITY_CONTEXT, execute_tool_block
    from tests.test_the_agent_works_the_workstation_screen import PERMITTED

    s = db()
    V.create(s, PERMITTED, {"label": "Service", "addresses": [service], "username": "agent", "secret": PASSWORD})
    s.close()

    def call(args):
        return asyncio.run(execute_tool_block(ToolBlock("agent_browser", json.dumps(args)), owner=PERMITTED,
                                              security_context=NO_TOOL_SECURITY_CONTEXT))

    try:
        _Service.posts.clear()
        call({"action": "open", "url": service + "/"})
        desc, out = call({"action": "login", "item": "Service"})
        assert desc == "agent_browser: sign in with “Service”"
        assert out["exit_code"] == 0 and "filled the user name, password" in out["output"]
        assert "Now at Home" in out["output"] and PASSWORD not in json.dumps(out)
        assert _Service.posts[-1][1]["password"] == PASSWORD, "the service got it; the model did not"
        _, missing = call({"action": "login", "item": "Nope"})
        assert missing["exit_code"] == 1 and "Your vault has: “Service”." in missing["error"]
    finally:
        daemon_up.station.browsers.stop_all()


def test_login_asks_wherever_a_push_asks():
    from src.tool_capabilities import capabilities_for_action
    assert capabilities_for_action("agent_browser", "login") == capabilities_for_action("agent_browser", "click")


# ── `P27-07`: a shell command, signed in ────────────────────────────────────

def test_a_login_reaches_a_command_as_named_variables():
    from src.agent_tools import login_shell_tools as L
    assert L.env_name("Grafana (agent)") == "GRAFANA_AGENT"
    env, names = L.environment([{"label": "Grafana (agent)", "username": "agent", "secret": PASSWORD,
                                 "otp": "", "origins": ["http://grafana.lan:3000"]}])
    assert env["LOGIN_GRAFANA_AGENT_PASSWORD"] == env["LOGIN_PASSWORD"] == PASSWORD
    assert env["LOGIN_URL"] == "http://grafana.lan:3000" and "LOGIN_OTP" not in env
    two, _ = L.environment([{"label": "A", "username": "a", "secret": "s1", "origins": []},
                            {"label": "B", "username": "b", "secret": "s2", "origins": []}])
    assert "LOGIN_PASSWORD" not in two and two["LOGIN_B_PASSWORD"] == "s2", "two logins: by name only"
    for bad in ('{"command": "ls"}', '{"logins": [], "command": "ls"}', '{"logins": ["A"]}', "ls"):
        assert L.parse_args(bad)[1]


def test_the_command_runs_with_the_values_and_says_none_of_them(db, tmp_path):
    from src.agent_tools import login_shell_tools as L
    s = db()
    _login(s, owner="root", label="Svc", addresses="127.0.0.1:9", username="agent")
    s.close()
    out = asyncio.run(L.run_with_login(json.dumps({
        "logins": ["Svc"], "command": 'printf "%s|%s|%s\\n" "$LOGIN_USER" "$LOGIN_PASSWORD" "$LOGIN_URL"; '
                                      'test "$LOGIN_PASSWORD" = "' + PASSWORD + '" && echo matched'}),
        owner="root"))
    assert out["exit_code"] == 0, out
    assert "••••|••••|http://127.0.0.1:9" in out["output"] and "matched" in out["output"]
    assert PASSWORD not in json.dumps(out), "the command had it; its answer does not"
    assert "$LOGIN_PASSWORD" in out["output"], "the answer names the variables it was given"
    missing = asyncio.run(L.run_with_login('{"logins": ["Nope"], "command": "true"}', owner="root"))
    assert missing["exit_code"] == 1 and "Your vault has: “Svc”." in missing["error"]
    other = asyncio.run(L.run_with_login('{"logins": ["Svc"], "command": "true"}', owner="bob"))
    assert other["exit_code"] == 1 and "There is no item “Svc”" in other["error"]


# ── `P27-08`: how each login may be used ────────────────────────────────────

def _gate(owner="alice", session="chat-1", **kw):
    from src.tool_capabilities import ToolRunSecurityContext
    return ToolRunSecurityContext(vault_use_lookup=lambda t, c: V.asks_before(owner, session, t, c), **kw)


SIGN_IN = json.dumps({"action": "login", "item": "Grafana (agent)"})
SHELL = json.dumps({"logins": ["Grafana (agent)"], "command": "true"})


def test_a_login_set_to_ask_asks_each_time_before_auto_and_in_a_clean_run(db):
    _login(db())
    for tool, content in (("agent_browser", SIGN_IN), ("shell_with_login", SHELL)):
        d = _gate(auto_approved=True).decision_for(tool, content)
        assert d.allowed is False and d.reason.startswith("“Grafana (agent)” is set to ask you each time")
        assert _gate().asks_for(tool, content) is True, "its card is answerable in a clean run"
    assert _gate().decision_for("agent_browser", json.dumps({"action": "read"})).allowed is True, \
        "an action that names no login is not the vault's question"
    assert _gate().decision_for("agent_browser", json.dumps({"action": "login", "item": "Nope"})).allowed, \
        "a name not in the vault asks nothing: the tool says it is not there"


def test_once_per_chat_asks_the_first_time_in_each_chat(db):
    s = db()
    item = _login(s, use="chat")
    assert _gate().decision_for("shell_with_login", SHELL).allowed is False
    asyncio.run(V.resolve(s, "alice", "Grafana (agent)", session="chat-1"))   # the approved first use
    assert _gate().decision_for("shell_with_login", SHELL).allowed is True
    assert _gate(session="chat-2").decision_for("shell_with_login", SHELL).allowed is False, "a new chat asks again"
    assert _gate(owner="bob").decision_for("shell_with_login", SHELL).allowed is True, \
        "bob has no such login; his call is refused by the tool, not asked about"
    V.update(s, "alice", item["id"], {"use": "allowed"})
    assert _gate(session="chat-3").decision_for("shell_with_login", SHELL).allowed is True, \
        "allowed adds no question of its own; the rung's still apply"


def test_a_bitwarden_item_always_asks_and_is_an_admins_only(db, monkeypatch):
    assert "asks each time" in _gate().decision_for("shell_with_login",
                                                    json.dumps({"logins": ["bw:abc123"], "command": "true"})).reason
    import src.tool_security as ts
    monkeypatch.setattr(ts, "blocked_tools_for_owner", lambda owner: {"vault_get"})
    with pytest.raises(V.VaultRefused) as nope:
        asyncio.run(V.resolve(db(), "bob", "bw:abc123"))
    assert "an admin's" in nope.value.sentence


def test_vault_get_says_a_password_is_set_and_never_what_it_is(monkeypatch):
    import src.tools.vault as T

    async def item(item_id):
        return {"id": item_id, "name": "Router", "notes": "pin 4321",
                "login": {"username": "admin", "password": "hunter2-secret", "totp": "JBSWY3DPEHPK3PXP",
                          "uris": [{"uri": "http://192.168.1.1"}]}}
    monkeypatch.setattr(T, "bw_item", item)
    out = asyncio.run(T.do_vault_get(json.dumps({"item_id": "abc123", "reason": "check the router"})))
    text = out["output"]
    assert "hunter2-secret" not in text and "JBSWY3DP" not in text and "4321" not in text
    assert "Password: set" in text and 'item "bw:abc123"' in text


def test_the_loop_shows_a_card_for_a_login_set_to_ask_and_runs_one_allowed(db, monkeypatch):
    from tests.test_an_ai_step_uses_only_its_tools import _base, _drive
    from src.tool_policy import ToolPolicy
    s = db()
    item = _login(s, owner="local")
    _base(monkeypatch)
    executed: list = []
    events, _ = _drive(monkeypatch, [[("shell_with_login", {"logins": ["Grafana (agent)"], "command": "true"})],
                                     "Done."], policy=ToolPolicy(), executed=executed, message="Check grafana")
    assert executed == [], "set to ask: the call waited"
    assert "is set to ask you each time an agent signs in with it" in json.dumps(events)
    V.update(s, "local", item["id"], {"use": "allowed"})
    executed.clear()
    _drive(monkeypatch, [[("shell_with_login", {"logins": ["Grafana (agent)"], "command": "true"})], "Done."],
           policy=ToolPolicy(), executed=executed, message="Check grafana")
    assert executed == ["shell_with_login"]


def test_every_use_is_recorded_without_its_value(db, monkeypatch):
    import src.events as ev
    seen = []
    monkeypatch.setattr(ev, "record_event", lambda kind, **kw: seen.append((kind, kw)) or True)
    _login(db())
    asyncio.run(V.resolve(db(), "alice", "Grafana (agent)", by="agent_browser", session="chat-9"))
    [(kind, kw)] = seen
    assert kind == "vault_use" and kw["name"] == "Grafana (agent)" and kw["session_id"] == "chat-9"
    assert kw["detail"]["by"] == "agent_browser" and PASSWORD not in json.dumps(kw)


# ── `P27-09`: which agents may use a login, and the agent's own list ────────

def test_a_login_granted_to_some_agents_is_invisible_to_the_rest(db):
    s = db()
    _login(s, agents=["competitor-tracker"])
    _login(s, label="Shared", addresses="nas.lan")
    got = asyncio.run(V.resolve(s, "alice", "Grafana (agent)", agent="competitor-tracker"))
    assert got["secret"] == PASSWORD
    for agent in (None, "inbox-triage"):
        with pytest.raises(V.VaultRefused) as nope:
            asyncio.run(V.resolve(s, "alice", "Grafana (agent)", agent=agent))
        assert nope.value.status == 404 and "Grafana" not in nope.value.sentence.split("vault.")[1]
        assert "“Shared”" in nope.value.sentence
    assert V.asks_before("alice", "c", "shell_with_login", SHELL, agent="inbox-triage") is None, \
        "not asked about: the tool refuses it as not there"
    V.update(s, "alice", V.listing(s, "alice")["items"][0]["id"], {"agents": ["chat"]})
    assert asyncio.run(V.resolve(s, "alice", "Grafana (agent)"))["secret"] == PASSWORD, "chat is the plain chat"
    with pytest.raises(V.VaultRefused):
        V.update(s, "alice", V.listing(s, "alice")["items"][0]["id"], {"agents": ["Not An Id!"]})


def test_the_connections_tool_lists_names_never_values_and_tests_an_address(db, tmp_path, monkeypatch):
    import threading
    import src.tool_security as ts
    monkeypatch.setattr(ts, "blocked_tools_for_owner", lambda owner: set())   # an admin, on this machine
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from src.agent_tools import connections_tools as C

    class _Ok(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            self.send_response(204)
            self.end_headers()

    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Ok)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        s = db()
        _login(s, owner="root", addresses=f"127.0.0.1:{srv.server_address[1]}", totp="JBSWY3DPEHPK3PXP",
               agent_account=True, use="chat")
        _login(s, owner="root", label="Other agent's", addresses="x.lan", agents=["someone-else"])
        s.close()
        listed = asyncio.run(C.run_connections('{"action": "list"}', owner="root"))
        out = listed["output"]
        assert "“Grafana (agent)” (login) — http://127.0.0.1:" in out
        assert "asks once per chat; an account made for the agent; one-time codes" in out
        assert "Other agent's" not in out and PASSWORD not in out and "JBSWY3DP" not in out
        tested = asyncio.run(C.run_connections('{"action": "test", "name": "Grafana (agent)"}', owner="root"))
        assert tested["exit_code"] == 0 and "answered HTTP 204" in tested["output"], tested
        hidden = asyncio.run(C.run_connections('{"action": "test", "name": "Other agent\'s"}', owner="root"))
        assert hidden["exit_code"] == 1 and "There is no login" in hidden["error"]
        monkeypatch.setattr(ts, "blocked_tools_for_owner", lambda owner: {"bash"})
        refused = asyncio.run(C.run_connections('{"action": "test", "name": "Grafana (agent)"}', owner="root"))
        assert "runs from your workstation" in refused["error"], "a non-admin's test never runs on the server"
    finally:
        srv.shutdown()


def test_connections_list_only_reads_and_a_test_reaches():
    from src.tool_capabilities import capabilities_for_action
    assert {e.value for e in capabilities_for_action("connections", '{"action": "list"}').effects} == {"read_private"}
    assert {e.value for e in capabilities_for_action("connections", '{"action": "test", "name": "x"}').effects} \
        == {"network_egress"}


# ── `P27-05`: an account made for the agent ────────────────────────────────

class _Grafana:
    """A Grafana admin API, as far as making a user and setting its role."""
    def __init__(self):
        import base64
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        seen = self.seen = []
        good = "Basic " + base64.b64encode(f"admin:{PASSWORD}".encode()).decode()

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _reply(self, code, obj):
                b = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def _do(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}") if n else {}
                seen.append((self.command, self.path, body))
                if self.headers.get("Authorization") != good:
                    return self._reply(401, {"message": "invalid username or password"})
                if self.command == "POST" and self.path == "/api/admin/users":
                    return self._reply(200, {"id": 7, "message": "User created"})
                if self.command == "GET" and self.path.startswith("/api/users/lookup"):
                    return self._reply(200, {"id": 7, "login": "pantheon-agent"})
                if self.command == "PATCH" and self.path == "/api/org/users/7":
                    return self._reply(200, {"message": "Organization user updated"})
                return self._reply(404, {"message": "not found"})

            do_GET = do_POST = do_PATCH = _do

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"127.0.0.1:{self.srv.server_address[1]}"


@pytest.mark.skipif(not shutil.which("curl"), reason="curl is not installed here")
def test_an_agent_account_is_made_with_its_role_and_kept_unseen(db, monkeypatch):
    import src.tool_security as ts
    from src import agent_accounts as A
    monkeypatch.setattr(ts, "blocked_tools_for_owner", lambda owner: set())
    g = _Grafana()
    try:
        s = db()
        admin = _login(s, owner="root", label="Grafana admin", addresses=g.url, username="admin")
        made = asyncio.run(A.set_up(s, "root", admin["id"], {"template": "grafana", "role": "Viewer",
                                                              "username": "pantheon-agent"}))
        assert made["label"] == "Grafana (pantheon-agent)" and made["agent_account"] and made["use"] == "chat"
        assert made["addresses"] == [f"http://{g.url}"]
        created = [b for m, p, b in g.seen if m == "POST"][0]
        assert created["login"] == "pantheon-agent" and len(created["password"]) >= 24
        assert ("PATCH", "/api/org/users/7", {"role": "Viewer"}) in g.seen, "the role the person picked"
        kept = asyncio.run(V.resolve(s, "root", "Grafana (pantheon-agent)"))
        assert kept["secret"] == created["password"], "the vault holds what the service was given"
        assert created["password"] not in json.dumps(made), "and the answer never shows it"

        V.update(s, "root", admin["id"], {"secret": "wrong-admin-password"})
        with pytest.raises(A.AccountRefused) as refused:
            asyncio.run(A.set_up(s, "root", admin["id"], {"template": "grafana", "role": "Editor",
                                                          "username": "second-agent"}))
        assert "refused step 1 of 2 (made nothing)" in refused.value.sentence
        assert "wrong-admin-password" not in refused.value.sentence
        assert "Grafana (second-agent)" not in V.labels(s, "root"), "nothing kept for an account not made"
    finally:
        g.srv.shutdown()


@pytest.mark.parametrize("body,words", [
    ({"template": "jellyfin", "role": "User", "username": "a-agent"}, "is not a service"),
    ({"template": "grafana", "role": "Owner", "username": "a-agent"}, "roles are Viewer, Editor, Admin"),
    ({"template": "gitea", "role": "User", "username": "A B"}, "The user name is"),
])
def test_a_bad_request_is_refused_before_anything_is_called(db, body, words):
    from src import agent_accounts as A
    s = db()
    admin = _login(s)
    with pytest.raises(A.AccountRefused) as e:
        asyncio.run(A.set_up(s, "alice", admin["id"], body))
    assert words in e.value.sentence


def test_a_summoned_agents_turn_carries_its_id_to_the_vault():
    from src.agents.summon import Summoned
    from src.tool_policy import ToolPolicy
    turn = Summoned("competitor-tracker", "Competitor Tracker", ["agent_browser"], frozenset(), frozenset())
    assert turn.policy(ToolPolicy()).agent_id == "competitor-tracker"
    assert ToolPolicy().agent_id is None, "the plain chat is no agent"
