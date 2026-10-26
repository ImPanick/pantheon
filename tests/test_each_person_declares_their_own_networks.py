# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1475`, `D-2026-10-25-04` §5 — each person's own networks, a task held to
its networks, and an admin who sees every endpoint and never a login.

The owner: *"Network scope allowable by admin — configured per user. Admin has
omni-sight. … Users can link their network endpoints with credentials stored
in vault for agent use. Admin can see the network endpoints the users
implemented but not the vault credentials, only that *something* is linked to
a login. Never the login directly."*

**Measured before this file:** `networks.scoped_to` was called only from tests
since `P16-16`, so every run was unscoped; there was one install-wide list of
networks, an admin's, and nowhere for a person to declare theirs.

Driven: a real SQLite database with the real vault, the real routes over HTTP,
the real `network` tool's listing, and the scheduler's own scope door.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from src import networks as N
from src import person_networks as PN
from src import vault as V

LAB = {"name": "lab", "cidrs": ["10.9.0.0/24"], "hosts": ["lab-gpu.lan"], "trust": "trusted"}


@pytest.fixture()
def world(tmp_path, monkeypatch):
    """A database with the vault and person-network tables, the install's
    settings in a dict, and no scope or person bound."""
    import core.database as cdb
    import src.secret_storage as ss
    import src.settings as S
    engine = create_engine(f"sqlite:///{tmp_path / 'p.db'}", connect_args={"check_same_thread": False},
                           poolclass=NullPool)
    cdb.Base.metadata.create_all(engine, tables=[cdb.VaultKey.__table__, cdb.VaultItem.__table__,
                                                 cdb.PersonNetworks.__table__])
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(cdb, "SessionLocal", factory)
    monkeypatch.setattr(ss, "_KEY_PATH", tmp_path / ".app_key")
    monkeypatch.setattr(ss, "_fernet", None)
    import src.workstation_access as wa
    monkeypatch.setattr(wa, "routes_tools", lambda owner, **kw: False)
    V._unlocked_until.clear()
    settings = {"networks": [LAB], "networks_per_person": True}
    monkeypatch.setattr(S, "get_setting", lambda key, default=None: settings.get(key, default))
    PN.forget()
    token = N._scope.set(None)
    factory.settings = settings
    factory.engine_path = tmp_path / "p.db"
    yield factory
    N._scope.reset(token)
    PN.forget()


def _as(person):
    """Bind the person a tool call acts for, as the dispatcher does."""
    from src.tool_execution import _tool_person
    return _tool_person.set(person)


def _login(s, owner, label="NAS admin", secret="Pw-nas-correct-7"):
    return V.create(s, owner, {"label": label, "addresses": "nas.home.arpa", "username": "root",
                               "secret": secret})


HOME = {"name": "home", "cidrs": ["192.168.50.0/24"], "hosts": ["nas.home.arpa"], "trust": "trusted"}


# ── a person's list ─────────────────────────────────────────────────────────

def test_a_persons_networks_are_theirs_and_direct_only_their_runs(world):
    s = world()
    item = _login(s, "ada")
    PN.save(s, "ada", [dict(HOME, login=item["id"])])
    tok = _as("ada")
    try:
        nets = {n.name: n for n in N.declared_networks()}
        assert set(nets) == {"lab", "home"} and nets["home"].person and not nets["lab"].person
        assert N.network_for("192.168.50.7") == "home"
    finally:
        from src.tool_execution import _tool_person
        _tool_person.reset(tok)
    tok = _as("bob")
    try:
        assert [n.name for n in N.declared_networks()] == ["lab"], "bob's runs never see ada's"
        assert N.network_for("192.168.50.7") is None
    finally:
        from src.tool_execution import _tool_person
        _tool_person.reset(tok)
    assert [n.name for n in N.declared_networks()] == ["lab"], "outside a run: the install's only"


def test_off_nothing_is_read_and_nothing_is_saved_but_nothing_is_lost(world):
    s = world()
    PN.save(s, "ada", [HOME])
    world.settings["networks_per_person"] = False
    PN.forget()
    assert PN.for_run("ada") == []
    with pytest.raises(PN.NetworksRefused) as e:
        PN.save(s, "ada", [])
    assert e.value.status == 403 and "admin" in e.value.sentence
    assert [n["name"] for n in PN.mine(s, "ada")["networks"]] == ["home"], "the saved list is kept"
    world.settings["networks_per_person"] = "yes"
    assert PN.enabled() is False, "only a stored true turns it on"


def test_a_list_with_anything_wrong_is_refused_whole_with_every_problem(world):
    s = world()
    bobs = _login(s, "bob", label="Bob's router")
    bad = [{"name": "lab", "cidrs": ["10.1.0.0/24"]},                    # the install's name
           {"name": "Internet", "hosts": ["x.lan"]},                     # reserved
           {"name": "theirs", "hosts": ["r.lan"], "login": bobs["id"]},  # bob's login
           {"name": "typo", "cidrs": ["10.0.0.300/24"]}]
    problems = PN.validate(s, "ada", bad)
    text = " ".join(problems)
    assert "declared for everyone" in text and "'Internet'" in text
    assert "not in your vault" in text and "not a valid CIDR" in text
    with pytest.raises(PN.NetworksRefused):
        PN.save(s, "ada", bad)
    assert PN.mine(s, "ada")["networks"] == []


def test_the_person_reads_their_links_label_and_a_removed_login_says_so(world):
    s = world()
    item = _login(s, "ada")
    PN.save(s, "ada", [dict(HOME, login=item["id"])])
    mine = PN.mine(s, "ada")["networks"][0]
    assert mine["login"] == item["id"] and mine["login_label"] == "NAS admin"
    V.remove(s, "ada", item["id"])
    mine = PN.mine(s, "ada")["networks"][0]
    assert mine["login"] == "" and mine["login_missing"] is True


# ── the admin's omni-sight ──────────────────────────────────────────────────

def test_the_admin_sees_every_endpoint_and_only_that_a_login_is_linked(world):
    s = world()
    item = _login(s, "ada", label="NAS admin (root)", secret="Pw-very-secret-99")
    PN.save(s, "ada", [dict(HOME, login=item["id"]), {"name": "lab2", "cidrs": ["10.7.0.0/24"]}])
    seen = PN.everyone(s)
    assert len(seen) == 1 and seen[0]["account"]
    nets = {n["name"]: n for n in seen[0]["networks"]}
    assert nets["home"]["cidrs"] == ["192.168.50.0/24"] and nets["home"]["hosts"] == ["nas.home.arpa"]
    assert nets["home"]["login_linked"] is True and nets["lab2"]["login_linked"] is False
    shown = json.dumps(seen)
    for never in (item["id"], "NAS admin", "root", "Pw-very-secret-99", '"login"'):
        assert never not in shown, f"the admin's view carries {never!r}"


# ── the agent ───────────────────────────────────────────────────────────────

def test_the_agent_is_told_the_login_to_sign_in_with_only_if_it_may_use_it(world):
    from src.agent_tools.network_tools import interfaces_text
    s = world()
    item = _login(s, "ada")
    PN.save(s, "ada", [dict(HOME, login=item["id"])])
    assert PN.agent_logins("ada") == {"home": "NAS admin"}
    V.update(s, "ada", item["id"], {"agents": ["helper"]})
    assert PN.agent_logins("ada") == {}, "an item not granted to the plain chat is not named to it"
    assert PN.agent_logins("ada", "helper") == {"home": "NAS admin"}
    tok = _as("ada")
    try:
        text = interfaces_text({"interfaces": []}, logins=PN.agent_logins("ada", "helper"))
    finally:
        from src.tool_execution import _tool_person
        _tool_person.reset(tok)
    assert "“home” [trusted] (the person's own)" in text
    assert "vault login “NAS admin”" in text and "Pw-nas" not in text


def test_a_persons_untrusted_network_is_never_connected_to_in_their_runs(world):
    s = world()
    PN.save(s, "ada", [dict(HOME, trust="untrusted")])
    tok = _as("ada")
    try:
        assert "untrusted" in (N.untrusted_refusal("nas.home.arpa") or "")
    finally:
        from src.tool_execution import _tool_person
        _tool_person.reset(tok)
    assert N.untrusted_refusal("nas.home.arpa") is None, "bob's run: not his network"


def test_web_fetch_carries_the_run_into_its_fetch_thread():
    """A context variable does not cross `run_in_executor`; the fetch reads the
    scope and the person's networks in the thread, so the call copies them."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "src" / "agent_tools" / "web_tools.py").read_text()
    assert "run_in_executor(None, ctx_copy.run, _fetch)" in src


# ── a task held to its networks ─────────────────────────────────────────────

def test_a_tasks_networks_are_checked_against_what_its_owner_sees(world):
    s = world()
    PN.save(s, "ada", [HOME])
    assert N.check_scope(["home", "LAB", "internet"], "ada") == (["home", "lab", "internet"], [])
    names, problems = N.check_scope(["home"], "bob")
    assert problems and "no network “home”" in problems[0] and "lab" in problems[0]
    assert N.check_scope([], "ada") == (None, []) and N.check_scope(None, "ada") == (None, [])


def test_a_stored_scope_reads_back_and_a_damaged_one_closes():
    assert N.scope_names(None) is None and N.scope_names("[]") is None
    assert N.scope_names('["lab", "internet"]') == ["lab", "internet"]
    assert N.scope_names("{not json") == [], "damage is a scope of nothing, never no scope"


def test_internet_admits_what_no_network_claims_and_nothing_another_does(world):
    world.settings["networks"] = [LAB, {"name": "prod", "cidrs": ["10.20.0.0/16"]}]
    with N.scoped_to(["lab"]):
        assert N.host_allowed("10.9.0.5") and not N.host_allowed("example.org")
        assert N.crossing("example.org") is None and N.crossing("10.20.1.1") == "prod"
    with N.scoped_to(["lab", N.OUTSIDE]):
        assert N.host_allowed("example.org") and N.host_allowed("10.9.0.5")
        assert not N.host_allowed("10.20.1.1"), "the internet is not another declared network"


def test_the_scheduler_holds_a_run_to_its_tasks_networks(monkeypatch):
    from src import task_scheduler as TS
    seen = []

    async def locked(self, task_id, run_id, **kw):
        seen.append(N.current_scope())
        return None

    monkeypatch.setattr(TS.TaskScheduler, "_execute_task_locked", locked)
    sched = TS.TaskScheduler.__new__(TS.TaskScheduler)
    scopes = {"scoped": ["lab", "internet"], "free": None}
    monkeypatch.setattr(TS.TaskScheduler, "_task_network_scope", staticmethod(lambda tid: scopes[tid]))
    asyncio.run(sched._execute_scoped("scoped", "r1"))
    asyncio.run(sched._execute_scoped("free", "r2"))
    assert seen == [{"lab", "internet"}, None]
    assert N.current_scope() is None, "the scope ends with the run"


def test_a_task_carries_its_networks_through_the_api():
    """Create and edit both take `networks` and both check it with the module
    that enforces it; a task reads them back as names."""
    from pathlib import Path
    routes = (Path(__file__).resolve().parents[1] / "routes" / "task" / "task_routes.py").read_text()
    assert routes.count("networks: Optional[List[str]] = None") == 2
    assert "check_scope(req.networks, user)" in routes
    assert routes.count("_validate_execution_settings(req, user)") == 2
    assert '"networks": _task_networks(t)' in routes


# ── over HTTP ───────────────────────────────────────────────────────────────

class _Auth:
    is_configured = True

    def is_admin(self, user):
        return user == "root"


@pytest.fixture()
def client(world, monkeypatch):
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient
    import routes.person_network_routes as R
    monkeypatch.setattr(R, "get_current_user", lambda request: request.headers.get("x-user"))
    monkeypatch.setattr(R, "request_is_a_person", lambda request: request.headers.get("x-token") is None)
    # The route module binds `SessionLocal` at import; in a full run the app has
    # imported it long before this file patched `core.database`, so the routes
    # read the real database and found no vault item (measured: 400 in the
    # suite, 200 alone). Point it at this test's database too.
    monkeypatch.setattr(R, "SessionLocal", world)

    def admin_only(request):
        if request.headers.get("x-user") != "root":
            raise HTTPException(403, "Admin only")
    monkeypatch.setattr(R, "require_admin", admin_only)
    app = FastAPI()
    app.include_router(R.setup_person_network_routes())
    return TestClient(app)


def test_the_routes_keep_each_list_its_persons_and_the_login_from_the_admin(client, world):
    s = world()
    item = _login(s, "ada")
    put = client.put("/api/networks/mine", headers={"x-user": "ada"},
                     json={"networks": [dict(HOME, login=item["id"])]})
    assert put.status_code == 200, put.text
    assert put.json()["networks"][0]["login_label"] == "NAS admin"
    assert put.json()["choices"] == ["lab", "home", "internet"]
    assert client.get("/api/networks/mine", headers={"x-user": "bob"}).json()["networks"] == []
    by_token = client.put("/api/networks/mine", headers={"x-user": "ada", "x-token": "t"},
                          json={"networks": []})
    assert by_token.status_code == 403 and "Only a person" in by_token.json()["detail"]
    bad = client.put("/api/networks/mine", headers={"x-user": "ada"},
                     json={"networks": [{"name": "lab", "hosts": ["x"]}]})
    assert bad.status_code == 400 and "declared for everyone" in bad.json()["detail"]
    probe = client.post("/api/networks/mine/check", headers={"x-user": "ada"},
                        json={"networks": [HOME], "probe": "192.168.50.9"})
    assert probe.json() == {"problems": [], "probe": "192.168.50.9", "matched": "home"}
    assert client.get("/api/networks/people", headers={"x-user": "ada"}).status_code == 403
    people = client.get("/api/networks/people", headers={"x-user": "root"})
    assert people.status_code == 200 and people.json()["enabled"] is True
    assert item["id"] not in people.text and "NAS admin" not in people.text
    assert people.json()["people"][0]["networks"][0]["login_linked"] is True


def test_the_panels_spell_every_path_and_draw_one_editor():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    mine = (root / "static" / "js" / "personNetworks.js").read_text()
    admin = (root / "static" / "js" / "networks.js").read_text()
    for path in ("/api/networks/mine", "/api/networks/mine/check", "/api/vault/mine"):
        assert path in mine
    assert "/api/networks/people" in admin and "networks_per_person" in admin
    for js in (mine, admin):
        assert "from './networkRows.js'" in js, "both lists draw rows with the one editor"
        assert "ip_network" not in js and "/\\d+$" not in js, "no CIDR rule restated in JS"
    html = (root / "static" / "index.html").read_text()
    for el in ("my-networks-list", "my-networks-add", "my-networks-save", "my-networks-off",
               "my-networks-probe", "my-networks-problems", "networks-per-person", "networks-people"):
        assert f'id="{el}"' in html, el
    assert 'data-settings-panel="my-networks"' in html
    registry = (root / "static" / "js" / "settings" / "registry.js").read_text()
    assert "id: 'my-networks'" in registry
