# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P22-22` — an MCP server is built, checked and tried in its author's own
workstation from the browser, and once an admin registers it through the
existing admin route it runs there through a relay (`D-2026-10-02-02` §3).

Driven, not read (`Law 20`): the real scaffold routes through `TestClient`, the
real workstation daemon (`tests/helpers/workstation_daemon.py` runs
`workstation/agentd.py` on a free port), and the relay started as a real
subprocess through `McpManager.connect_server` with exactly the fields the
admin route would store. A spy on the daemon's own `exec` — the side the relay
cannot lie to — says which account every call ran in and what program it ran.

The adversaries (design § 5.5, `Law 17`): a hostile server name, tool name or
argument; a tool call trying to move the relay to another account or folder;
the assistant trying to register the relay itself. Each control has a case.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.auth import AuthManager as _RealAuthManager  # before any fixture swaps it
from src import workstation_mcp as wm
from src.workstation_access import (NOT_PERMITTED_SENTENCE, OFF_SENTENCE, account_of)
from tests.helpers.workstation_daemon import running_workstation

_PASSWORD = "a-long-test-password-1"
_USERS = {
    "admin": {"admin": True, "privs": {}},
    "ann": {"admin": False, "privs": {"can_use_workstation": True}},
    "bob": {"admin": False, "privs": {"can_use_workstation": False}},
}

RECORDER = '''import json, os, sys
sys.stdout = sys.stderr

def answer(message):
    if "id" not in message:
        return None
    method = message.get("method")
    params = message.get("params") or {}
    if method == "initialize":
        result = {"protocolVersion": params.get("protocolVersion"), "capabilities": {"tools": {}},
                  "serverInfo": {"name": "recorder", "version": "1"}}
    elif method == "tools/list":
        result = {"tools": [{"name": "record", "description": "Says back what it was handed.",
                             "inputSchema": {"type": "object"}}]}
    elif method == "tools/call":
        args = params.get("arguments")
        print("recorded a call", file=sys.stderr)
        text = json.dumps({"arguments": args, "home": os.path.expanduser("~"),
                           "secret": os.environ.get("PANTHEON_PROBE_SECRET", "absent")},
                          sort_keys=True)
        result = {"content": [{"type": "text", "text": text}], "isError": False}
    else:
        return {"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32601, "message": "no"}}
    return {"jsonrpc": "2.0", "id": message["id"], "result": result}

for raw in iter(sys.stdin.buffer.readline, b""):
    out = answer(json.loads(raw))
    if out is not None:
        sys.__stdout__.write(json.dumps(out) + "\\n")
        sys.__stdout__.flush()
'''


class _Auth:
    is_configured = True

    def is_admin(self, username):
        return bool(_USERS.get(username, {}).get("admin"))

    def get_privileges(self, username):
        user = _USERS.get(username, {})
        if user.get("admin"):
            from core.auth import ADMIN_PRIVILEGES
            return dict(ADMIN_PRIVILEGES)
        return dict(user.get("privs", {}))


@pytest.fixture
def station(tmp_path, monkeypatch):
    import core.auth
    import src.auth_helpers
    import src.settings as S
    from workstation import protocol as P

    monkeypatch.setattr(src.auth_helpers, "_auth_disabled", lambda: False)
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setattr(core.auth, "AuthManager", _Auth)
    monkeypatch.delenv(P.URL_ENV, raising=False)
    monkeypatch.delenv(P.TOKEN_ENV, raising=False)
    values: Dict[str, Any] = {}
    real = S.get_setting
    monkeypatch.setattr(S, "get_setting",
                        lambda key, default=None: values[key] if key in values else real(key, default))
    wm._LAST_CHECK.clear()
    with running_workstation(tmp_path) as ws:
        execs: List[Dict[str, Any]] = []
        real_exec = ws.station.exec

        def exec_spy(account, body, *a, **kw):
            execs.append({"account": account, "body": dict(body)})
            return real_exec(account, body, *a, **kw)

        ws.station.exec = exec_spy
        values.update({"workstation_enabled": True, "workstation_url": ws.url,
                       "workstation_token": ws.token, "workstation_sudo": False})
        yield type("Station", (), {"ws": ws, "settings": values, "execs": execs,
                                   "tmp": tmp_path})


@pytest.fixture
def rows(monkeypatch):
    """A real SQLite `mcp_servers` table holding one server, behind both
    names a route could reach it by."""
    import core.database as cdb
    from core.database import Base, McpServer
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(cdb, "SessionLocal", factory)
    monkeypatch.setattr("routes.mcp.mcp_routes.SessionLocal", factory)
    db = factory()
    db.add(McpServer(id="pre1", name="already-here", transport="stdio", command="npx",
                     args="[]", env="{}", is_enabled=False))
    db.commit()
    db.close()

    def count():
        session = factory()
        try:
            return session.query(McpServer).count()
        finally:
            session.close()

    return type("Rows", (), {"factory": factory, "count": staticmethod(count)})


class _RecordingManager:
    def __init__(self):
        self.spawned: List[Dict[str, Any]] = []

    async def connect_server(self, **kwargs):
        self.spawned.append(kwargs)
        return False

    async def disconnect_server(self, server_id):
        return None

    def get_server_status(self, server_id):
        return {"status": "disconnected", "tool_count": 0, "error": None}

    def get_all_tools(self, *a, **k):
        return []


@pytest.fixture
def client(station, rows):
    from routes.mcp.mcp_routes import setup_mcp_routes

    manager = _RecordingManager()
    app = FastAPI()
    app.state.auth_manager = _Auth()

    @app.middleware("http")
    async def _who(request, call_next):
        request.state.current_user = request.headers.get("x-test-user")
        if request.headers.get("x-test-token"):
            request.state.api_token = True
        return await call_next(request)

    app.include_router(setup_mcp_routes(manager))
    c = TestClient(app)
    c.manager = manager
    return c


def _as(user):
    return {"x-test-user": user}


def _home(station, user) -> Path:
    return station.ws.root / account_of(user)


def _make(client, user="ann", **body):
    payload = {"name": "weather", "tools": ["get_forecast"], "description": "Forecasts"}
    payload.update(body)
    return client.post("/api/mcp/scaffold", json=payload, headers=_as(user))


# ── it is made in the author's own home, and it starts there ─────────────────

def test_the_files_land_in_the_authors_own_workstation_home(client, station):
    r = _make(client, owner="bob")  # a body cannot name whose home
    assert r.status_code == 200, r.text
    made = r.json()
    folder = _home(station, "ann") / "mcp-servers" / "weather"
    assert (folder / "server.py").is_file() and (folder / "README.md").is_file()
    assert not _home(station, "bob").exists()
    assert made["check"]["started"] is True, made["check"]
    assert made["check"]["tools"] == ["get_forecast"]
    reg = made["registration"]
    assert reg["transport"] == "stdio" and reg["command"] == sys.executable and reg["env"] == {}
    assert reg["args"] == [wm.RELAY_PATH, "--owner", "ann", "--server", "weather"]
    assert os.path.basename(reg["args"][0]) == "workstation_mcp.py"
    # every exec ran the one fixed program, as ann, with the job on stdin
    assert station.execs and all(e["account"] == account_of("ann") for e in station.execs)
    assert all(e["body"]["command"] == wm.PROBE_HARNESS for e in station.execs)
    assert all(e["body"]["shell"] == "python" for e in station.execs)


def test_check_then_try_answers_from_the_workstation(client, station):
    _make(client)
    checked = client.post("/api/mcp/scaffold/weather/check", headers=_as("ann")).json()
    assert checked["started"] is True and checked["error"] is None
    assert checked["tools"] == ["get_forecast"]
    offer, = checked["offers"]
    assert offer["input_schema"]["required"] == ["text"]
    tried = client.post("/api/mcp/scaffold/weather/try", headers=_as("ann"),
                        json={"tool": "get_forecast", "arguments": {"text": "Oslo"}}).json()
    assert tried["ok"] is True and tried["exit_code"] == 0, tried
    assert tried["stdout"] == "get_forecast has not been written yet. It was called with text='Oslo'"
    assert isinstance(tried["duration_ms"], int) and tried["stderr"] == ""
    job = json.loads(station.execs[-1]["body"]["stdin"])
    assert job == {"slug": "weather", "action": "call", "tool": "get_forecast",
                   "arguments": {"text": "Oslo"}, "timeout": wm.CALL_TIMEOUT_S}


def test_the_list_says_what_the_last_check_found_and_when_it_went_stale(client, station):
    assert client.get("/api/mcp/scaffold", headers=_as("ann")).json() == {
        "servers": [], "workstation": {"available": True, "why": None}}
    _make(client)
    listed = client.get("/api/mcp/scaffold", headers=_as("ann")).json()
    entry, = listed["servers"]
    assert (entry["name"], entry["tools"], entry["checked"]) == ("weather", ["get_forecast"], "works")
    source = client.get("/api/mcp/scaffold/weather", headers=_as("ann")).json()["source"]
    os.utime(_home(station, "ann") / "mcp-servers/weather/server.py", None)
    assert client.put("/api/mcp/scaffold/weather", headers=_as("ann"),
                      json={"source": source + "\n# mine\n"}).json() == {"saved": True}
    entry, = client.get("/api/mcp/scaffold", headers=_as("ann")).json()["servers"]
    assert entry["checked"] == "changed"


def test_a_broken_server_is_reported_with_what_it_printed(client, station):
    _make(client)
    assert client.put("/api/mcp/scaffold/weather", headers=_as("ann"),
                      json={"source": "this is not python(\n"}).status_code == 200
    checked = client.post("/api/mcp/scaffold/weather/check", headers=_as("ann")).json()
    assert checked["started"] is False
    assert checked["error"] == "It stopped before it answered."
    assert "SyntaxError" in checked["stderr"]
    entry, = client.get("/api/mcp/scaffold", headers=_as("ann")).json()["servers"]
    assert entry["checked"] == "broken"


def test_it_never_overwrites_a_server_somebody_wrote(client, station):
    _make(client)
    path = _home(station, "ann") / "mcp-servers/weather/server.py"
    mine = path.read_text() + "\n# the afternoon I spent on this\n"
    path.write_text(mine)
    again = _make(client)
    assert again.status_code == 400 and "already exists" in again.json()["detail"]
    assert path.read_text() == mine


# ── § 5.5: what a hostile name, tool or argument can reach ───────────────────

def test_a_hostile_tool_name_is_refused_and_nothing_is_written(client, station):
    r = _make(client, tools=['x"; import os#'])
    assert r.status_code == 400
    assert "does not work as a tool name" in r.json()["detail"]
    assert not (_home(station, "ann") / "mcp-servers").exists()
    assert station.execs == []


@pytest.mark.parametrize("hostile", ["../../etc", "weather/../../x", "..", "a b; rm -rf ~"])
def test_a_hostile_server_name_stays_in_the_servers_folder(client, station, hostile):
    r = _make(client, name=hostile)
    home = _home(station, "ann")
    if r.status_code == 200:
        slug = r.json()["name"]
        assert (home / "mcp-servers" / slug / "server.py").is_file()
        assert r.json()["registration"]["args"][-1] == slug
    else:
        assert r.status_code == 400
    made = sorted(str(p.relative_to(home)) for p in home.rglob("*") if p.is_file()) \
        if home.exists() else []
    assert all(p.startswith("mcp-servers/") for p in made), made


def test_the_harness_checks_the_folder_name_again_itself(station):
    """The harness is handed JSON and trusts none of it: a folder name that
    the Python side would never send is refused inside the workstation."""
    from src.workstation_client import WorkstationClient
    client = WorkstationClient(station.ws.url, station.ws.token)
    account = account_of("ann")
    for slug in ("../x", "a/b", "", "X", 7):
        answer = asyncio.run(wm._probe(client, account, {"slug": slug, "action": "list"}, 5))
        assert answer["started"] is False
        assert answer["error"] == "That is not a server's folder name."


def test_arguments_arrive_byte_for_byte(client, station):
    _make(client)
    assert client.put("/api/mcp/scaffold/weather", headers=_as("ann"),
                      json={"source": RECORDER}).status_code == 200
    hostile = {"text": 'a "quote" {{ steps.x.data }}\nline two "}', "n": [1, {"k": '"}'}],
               "owner": "bob", "--owner": "bob", "slug": "../x"}
    tried = client.post("/api/mcp/scaffold/weather/try", headers=_as("ann"),
                        json={"tool": "record", "arguments": hostile}).json()
    assert tried["ok"] is True, tried
    said = json.loads(tried["stdout"])
    assert said["arguments"] == hostile
    assert said["home"] == str(_home(station, "ann"))
    assert tried["printed"].strip() == "recorded a call"


# ── who may, and what nothing here may do ────────────────────────────────────

def test_workstation_off_or_not_permitted_says_the_sentence(client, station):
    station.settings["workstation_enabled"] = False
    listed = client.get("/api/mcp/scaffold", headers=_as("ann")).json()
    assert listed == {"servers": [], "workstation": {"available": False, "why": OFF_SENTENCE}}
    off = _make(client)
    assert off.status_code == 409 and off.json()["detail"] == OFF_SENTENCE
    station.settings["workstation_enabled"] = True
    listed = client.get("/api/mcp/scaffold", headers=_as("bob")).json()
    assert listed["workstation"] == {"available": False, "why": NOT_PERMITTED_SENTENCE}
    refused = _make(client, user="bob")
    assert refused.status_code == 403 and refused.json()["detail"] == NOT_PERMITTED_SENTENCE
    assert station.execs == []


def test_a_bearer_token_is_not_a_person_building_a_server(client, station):
    r = client.post("/api/mcp/scaffold", json={"name": "weather"},
                    headers={"x-test-user": "ann", "x-test-token": "1"})
    assert r.status_code == 403
    assert station.execs == []


def test_no_scaffold_route_writes_an_mcp_server_row(client, station, rows):
    assert rows.count() == 1
    calls = [
        ("post", "/api/mcp/scaffold", {"name": "weather", "tools": ["get_forecast"]}),
        ("get", "/api/mcp/scaffold", None),
        ("get", "/api/mcp/scaffold/weather", None),
        ("put", "/api/mcp/scaffold/weather", {"source": RECORDER}),
        ("post", "/api/mcp/scaffold/weather/check", None),
        ("post", "/api/mcp/scaffold/weather/try", {"tool": "record", "arguments": {}}),
    ]
    for method, path, body in calls:
        kwargs = {"headers": _as("ann")}
        if body is not None:
            kwargs["json"] = body
        r = getattr(client, method)(path, **kwargs)
        assert r.status_code == 200, (path, r.text)
        assert rows.count() == 1, path
    assert client.manager.spawned == []  # and nothing was started as Pantheon


def test_the_assistant_cannot_register_it_and_the_admin_route_can(client, station, rows,
                                                                   monkeypatch):
    """Both sides of `FORBIDDEN.md` Part 2's rule, for the relay's fields: the
    agent's `manage_mcp` refuses them with the sentence the README quotes, the
    `app_api` loopback is refused before a request is built, and the admin
    route — `require_admin` — accepts them and spawns exactly that argv."""
    import httpx

    import src.agent_tools.admin_tools as admin_tools
    from src.tools.system import do_app_api

    reg = _make(client).json()["registration"]
    monkeypatch.setattr(admin_tools, "get_mcp_manager", lambda: client.manager)
    said = asyncio.run(admin_tools.do_manage_mcp(json.dumps({
        "action": "add", "name": reg["name"], "command": reg["command"],
        "args": reg["args"], "env": reg["env"]})))
    assert said["exit_code"] == 1
    assert said["error"] == wm.agent_refusal(reg)
    assert said["error"].startswith("manage_mcp: refused unsafe server registration:")
    assert rows.count() == 1 and client.manager.spawned == []

    built = []

    class _Boom:
        def __init__(self, *a, **k):
            built.append(True)
            raise RuntimeError("NETWORK_ATTEMPTED")

    with monkeypatch.context() as scoped:
        scoped.setattr(httpx, "AsyncClient", _Boom)
        via_bridge = asyncio.run(do_app_api(json.dumps({
            "action": "call", "method": "POST", "path": "/api/mcp/servers",
            "body": {"name": reg["name"], "transport": "stdio", "command": reg["command"],
                     "args": json.dumps(reg["args"]), "env": "{}"}}), owner="ann"))
    assert via_bridge["exit_code"] == 1 and built == []
    assert "command check" in via_bridge["error"]

    form = {"name": reg["name"], "transport": "stdio", "command": reg["command"],
            "args": json.dumps(reg["args"]), "env": json.dumps(reg["env"])}
    assert client.post("/api/mcp/servers", data=form, headers=_as("ann")).status_code == 403
    assert rows.count() == 1
    saved = client.post("/api/mcp/servers", data=form, headers=_as("admin"))
    assert saved.status_code == 200, saved.text
    assert rows.count() == 2
    spawned, = client.manager.spawned
    assert (spawned["command"], spawned["args"], spawned["env"]) == (
        reg["command"], reg["args"], {})


def test_an_edit_keeps_the_admin_routes_own_env_rule(client, rows):
    """The manage view's *Edit* saves through the unchanged `PUT` (`P8-35`),
    whose `_parsed_json_field` rule still refuses a number for a variable."""
    r = client.put("/api/mcp/servers/pre1", data={"env": json.dumps({"PORT": 3000})},
                   headers=_as("admin"))
    assert r.status_code == 400
    assert "PORT" in r.json()["detail"] and "e.g." in r.json()["detail"]


# ── the relay, started as an admin's registration starts it ──────────────────

def _relay_world(station, monkeypatch):
    """A data directory the relay's own process reads: the workstation's
    settings and a real auth file in which ann may use the workstation."""
    data = station.tmp / "pantheon-data"
    data.mkdir()
    (data / "settings.json").write_text(json.dumps({
        "workstation_enabled": True, "workstation_url": station.ws.url,
        "workstation_token": station.ws.token, "workstation_sudo": False}))
    auth = _RealAuthManager(str(data / "auth.json"))
    assert auth.setup("admin", _PASSWORD)
    for name in ("ann", "bob"):
        assert auth.create_user(name, _PASSWORD)
    assert auth.set_privileges("ann", {"can_use_workstation": True})
    monkeypatch.setenv("PANTHEON_DATA_DIR", str(data))
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("PANTHEON_PROBE_SECRET", "pantheon-side-only")
    return data


def _through_the_manager(reg, calls):
    from src.mcp_manager import McpManager

    async def go():
        manager = McpManager()
        started = await manager.connect_server(
            server_id="relay1", name=reg["name"], transport="stdio",
            command=reg["command"], args=reg["args"], env=reg["env"])
        status = manager.get_server_status("relay1")
        tools = sorted(t["name"] for t in manager.get_all_tools() if t["server_id"] == "relay1")
        out = []
        try:
            for name, arguments in calls:
                out.append(await manager.call_tool(f"mcp__relay1__{name}", arguments))
        finally:
            await manager.disconnect_server("relay1")
        return started, status, tools, out

    return asyncio.run(go())


def test_the_relay_runs_each_call_in_the_authors_account(client, station, monkeypatch):
    reg = _make(client).json()["registration"]
    _relay_world(station, monkeypatch)
    before = len(station.execs)
    started, status, tools, out = _through_the_manager(
        reg, [("get_forecast", {"text": "Oslo"})])
    assert started is True, status
    assert tools == ["get_forecast"]
    assert out == [{"stdout": "get_forecast has not been written yet. It was called with "
                              "text='Oslo'", "stderr": "", "exit_code": 0}]
    relayed = station.execs[before:]
    assert [json.loads(e["body"]["stdin"])["action"] for e in relayed] == ["list", "call"]
    assert {e["account"] for e in relayed} == {account_of("ann")}
    assert all(e["body"]["command"] == wm.PROBE_HARNESS for e in relayed)


def test_a_call_cannot_move_the_relay_and_pantheons_environment_stays_home(
        client, station, monkeypatch):
    _make(client)
    client.put("/api/mcp/scaffold/weather", headers=_as("ann"), json={"source": RECORDER})
    reg = client.get("/api/mcp/scaffold/weather", headers=_as("ann")).json()["registration"]
    _relay_world(station, monkeypatch)
    before = len(station.execs)
    forged = {"owner": "bob", "--owner": "bob", "server": "other", "--server": "../x",
              "slug": "../x", "account": account_of("bob")}
    _started, _status, _tools, (said,) = _through_the_manager(reg, [("record", forged)])
    told = json.loads(said["stdout"])
    assert told["arguments"] == forged
    assert told["home"] == str(_home(station, "ann"))
    assert told["secret"] == "absent"  # the relay inherits it; it is never sent on
    relayed = station.execs[before:]
    assert {e["account"] for e in relayed} == {account_of("ann")}
    assert {json.loads(e["body"]["stdin"])["slug"] for e in relayed} == {"weather"}
    assert all("env" not in e["body"] for e in relayed)
    assert not _home(station, "bob").exists()


@pytest.mark.parametrize("argv", [
    ["--owner", "ann", "--server", "../x"],
    ["--owner", "ann", "--server", ""],
    ["--owner", "", "--server", "weather"],
    ["--owner", "ann"],
    ["--server", "weather"],
])
def test_the_relay_refuses_flags_that_do_not_name_one_folder_and_one_person(argv, capsys):
    with pytest.raises(SystemExit) as stopped:
        wm._relay_args(argv)
    assert stopped.value.code == 2


def test_a_workstation_switched_off_answers_with_its_sentence_through_the_relay(
        client, station, monkeypatch):
    reg = _make(client).json()["registration"]
    data = _relay_world(station, monkeypatch)
    settings = json.loads((data / "settings.json").read_text())
    settings["workstation_enabled"] = False
    (data / "settings.json").write_text(json.dumps(settings))
    started, status, tools, _out = _through_the_manager(reg, [])
    assert started is False and tools == []
    assert OFF_SENTENCE in str(status.get("error"))
