# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1573` — a member owns a service connection, and only their agent uses it.

`P27-02` made each connection its owner's, but only an admin could add one:
`api_call` runs on the server, so it is in `NON_ADMIN_BLOCKED_TOOLS`, and a
member's own record would have been a key nothing of theirs could use.
**Measured on `2760dbe1`:** a member's `POST /api/auth/integrations` was 403
*Admin only*, their list was 403, and their agent's `api_call` was refused.

Now a member adds, changes, removes and tests their own; their agent's
`api_call` finds exactly those and calls them **from their workstation**, by
`curl` in their own account (`P27-09`'s pattern) — the key handed to curl on
its standard input, never in its command line. The server makes no request
for a member's record: not the agent's call, not *Test*, not a reminder or a
brief. Nobody else's agent finds it, and a member neither shares one nor
reaches a shared one with their agent (its key would be in their workstation).

Driven (`Law 20`): the real routes (`routes/auth_routes.py`), the real
dispatcher (`tool_execution.execute_tool_block`), the real workstation daemon
(`tests/helpers/workstation_daemon.py` runs `workstation/agentd.py`) with the
real `WorkstationClient` spied on and called through, real `curl`, and a real
HTTP service on a local port that records what reached it. The server's own
request path (`paced_http.request`) is spied on, to show it is never taken.
"""
from __future__ import annotations

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import src.integrations as I
import src.tool_execution as te
from src.agent_tools import ToolBlock
from src.workstation_client import WorkstationClient, account_for
from tests.helpers.signed_in import as_person
from tests.helpers.workstation_daemon import running_workstation

ANN_KEY = "ANN-OWN-gitea-token-7"
BOSS_KEY = "BOSS-SHARED-key-3"

_USERS: Dict[str, Dict[str, Any]] = {
    "boss": {"admin": True, "privs": {}},
    # Members with a workstation, and one without.
    "ann": {"admin": False, "privs": {"can_use_workstation": True}},
    "cat": {"admin": False, "privs": {"can_use_workstation": True}},
    "bob": {"admin": False, "privs": {"can_use_workstation": False}},
}


class _Auth:
    """`core.auth.AuthManager`, answering for `_USERS` — the real
    `owner_is_admin`, `blocked_tools_for_owner` and `may_use` run on top."""

    is_configured = True

    def is_admin(self, username):
        return bool(_USERS.get(username, {}).get("admin"))

    def get_privileges(self, username):
        if self.is_admin(username):
            from core.auth import ADMIN_PRIVILEGES
            return dict(ADMIN_PRIVILEGES)
        return dict(_USERS.get(username, {}).get("privs", {}))

    def list_users(self):
        return [{"username": u, "is_admin": v["admin"]} for u, v in _USERS.items()]


class _Service(BaseHTTPRequestHandler):
    seen: list = []

    def _answer(self):
        size = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(size).decode() if size else ""
        _Service.seen.append({"method": self.command, "path": self.path,
                              "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body})
        out = json.dumps({"ok": True, "path": self.path}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    do_GET = do_POST = do_PUT = do_DELETE = _answer

    def log_message(self, *a):
        pass


@pytest.fixture
def world(tmp_path, monkeypatch):
    import core.auth
    import src.paced_http as paced
    import src.settings as S
    from routes import auth_routes
    from workstation import protocol as P

    monkeypatch.setattr(core.auth, "AuthManager", _Auth)
    monkeypatch.setattr(core.auth, "_SHARED_AUTH_MANAGER", None, raising=False)
    monkeypatch.setattr(I, "DATA_FILE", str(tmp_path / "integrations.json"))
    monkeypatch.setattr(auth_routes, "migrate_from_settings", lambda: None)
    monkeypatch.delenv(P.URL_ENV, raising=False)
    monkeypatch.delenv(P.TOKEN_ENV, raising=False)
    values: Dict[str, Any] = {}
    real = S.get_setting
    monkeypatch.setattr(S, "get_setting",
                        lambda key, default=None: values[key] if key in values else real(key, default))

    server_requests = []
    real_request = paced.request

    async def spy_request(method, url, **kw):
        server_requests.append((method, url))
        return await real_request(method, url, **kw)

    monkeypatch.setattr(paced, "request", spy_request)

    execs = []
    real_exec = WorkstationClient.exec

    async def exec_spy(self, account, command, **kw):
        execs.append({"account": account, "command": command, **kw})
        return await real_exec(self, account, command, **kw)

    monkeypatch.setattr(WorkstationClient, "exec", exec_spy)

    _Service.seen = []
    service = ThreadingHTTPServer(("127.0.0.1", 0), _Service)
    threading.Thread(target=service.serve_forever, daemon=True).start()
    with running_workstation(tmp_path) as ws:
        values.update({"workstation_enabled": True, "workstation_url": ws.url,
                       "workstation_token": ws.token, "workstation_sudo": False})

        def client(person):
            app = FastAPI()
            app.include_router(auth_routes.setup_auth_routes(_Auth()))
            return TestClient(as_person(app, person, auth_manager=_Auth()))

        base = f"http://127.0.0.1:{service.server_port}"
        yield type("World", (), {
            "client": staticmethod(client), "base": base, "execs": execs, "settings": values,
            # What this machine asked of the service itself — the workstation
            # client's own requests to the daemon go through the same door.
            "server_requests": property(lambda self: [u for _m, u in server_requests if u.startswith(base)]),
        })()
    service.shutdown()


def _agent(tool_input: Dict[str, Any], owner: str) -> Dict[str, Any]:
    _desc, result = asyncio.run(te.execute_tool_block(
        ToolBlock("api_call", json.dumps(tool_input)), session_id="s1", owner=owner,
        security_context=te.NO_TOOL_SECURITY_CONTEXT))
    return result


def _add(client, base, **body):
    r = client.post("/api/auth/integrations", json={"base_url": base, **body})
    assert r.status_code == 200, r.text
    return r.json()["integration"]


def test_a_member_adds_their_own_and_it_is_called_from_their_workstation(world):
    ann = world.client("ann")
    made = _add(ann, world.base, name="Ann's Gitea", preset="gitea", auth_type="bearer", api_key=ANN_KEY)
    assert (made["mine"], made["shared"], made["read_only"]) == (True, False, False)
    assert (made["called_from"], made["your_agents"]) == ("workstation", True)
    listed = ann.get("/api/auth/integrations").json()
    assert listed["may_share"] is False
    assert [i["name"] for i in listed["integrations"]] == ["Ann's Gitea"]


def test_their_agent_calls_it_from_the_workstation_and_the_server_makes_no_request(world):
    ann = world.client("ann")
    _add(ann, world.base, name="Ann's Gitea", auth_type="bearer", api_key=ANN_KEY)
    got = _agent({"integration": "Ann's Gitea", "method": "POST", "path": "/api/v1/issues",
                  "params": {"draft": True}, "body": {"title": "From the agent", "n": 2}}, "ann")
    assert got["exit_code"] == 0, got
    assert got["output"].startswith("HTTP 200\n") and '"path": "/api/v1/issues?draft=true"' in got["output"]
    assert (got["ran_in"], got["account"]) == ("workstation", account_for("ann"))

    (hit,) = _Service.seen
    assert (hit["method"], hit["path"]) == ("POST", "/api/v1/issues?draft=true")
    assert hit["headers"]["authorization"] == f"Bearer {ANN_KEY}"
    assert hit["headers"]["content-type"] == "application/json"
    assert json.loads(hit["body"]) == {"title": "From the agent", "n": 2}
    assert hit["headers"]["user-agent"].startswith("curl/"), "made by curl, in the workstation"

    assert world.server_requests == [], "the server made no request for a member's connection"
    (run,) = world.execs
    assert run["account"] == account_for("ann")
    assert ANN_KEY not in run["command"] and ANN_KEY not in json.dumps(run.get("env") or {}), \
        "the key is not in the command line, nor in the environment"
    assert ANN_KEY in run["stdin"], "it reaches curl on its standard input"


def test_a_json_answer_and_a_missing_service_read_as_the_servers_do(world):
    ann = world.client("ann")
    _add(ann, world.base, name="Ann's Gitea", auth_type="bearer", api_key=ANN_KEY)
    got = _agent({"integration": "Ann's Gitea", "path": "/x", "structured": True}, "ann")
    assert (got["http_status"], got["body_json"]) == (200, {"ok": True, "path": "/x"})
    _add(ann, "http://127.0.0.1:9", name="Nothing there", auth_type="none")
    gone = _agent({"integration": "Nothing there", "path": "/"}, "ann")
    assert gone["exit_code"] == 1 and gone["error"].startswith("Request failed: "), gone
    assert world.server_requests == []


def test_an_admins_own_is_still_called_by_the_server(world):
    """The control for every `server_requests == []` here: the spy sees the
    server's request when there is one."""
    boss = world.client("boss")
    made = _add(boss, world.base, name="Boss's API", auth_type="bearer", api_key=BOSS_KEY)
    assert made["called_from"] == "server"
    got = _agent({"integration": "Boss's API", "path": "/y"}, "boss")
    assert got["exit_code"] == 0 and "ran_in" not in got, got
    assert world.server_requests == [f"{world.base}/y"] and world.execs == []


def test_nobody_elses_agent_finds_it(world):
    ann, cat, boss = world.client("ann"), world.client("cat"), world.client("boss")
    made = _add(ann, world.base, name="Ann's Gitea", auth_type="bearer", api_key=ANN_KEY)
    for person, client in (("cat", cat), ("boss", boss)):
        assert "Ann's Gitea" not in client.get("/api/auth/integrations").text
        assert client.post(f"/api/auth/integrations/{made['id']}/test").status_code == 404
        assert "Ann's Gitea" not in I.get_integrations_prompt(person)
        got = _agent({"integration": "Ann's Gitea", "path": "/"}, person)
        assert got["exit_code"] == 1 and "No integration matching 'Ann's Gitea'" in got["error"], got
        assert asyncio.run(I.execute_api_call(made["id"], "GET", "/", owner=person))["error"] == \
            f"Integration not found: {made['id']}"
    assert "Ann's Gitea" in I.get_integrations_prompt("ann")
    assert _Service.seen == [] and world.server_requests == []


def test_a_member_may_not_share_one_nor_reach_a_shared_one_with_their_agent(world):
    ann, boss = world.client("ann"), world.client("boss")
    refused = ann.post("/api/auth/integrations", json={"name": "Mine for all", "base_url": world.base,
                                                       "shared": True})
    assert refused.status_code == 403
    assert refused.json()["detail"] == ("A shared connection is called by the server for everyone, so "
                                        "only an admin shares one. Yours stays yours: your agents call it "
                                        "from your workstation.")
    own = _add(ann, world.base, name="Ann's Gitea", auth_type="bearer", api_key=ANN_KEY)
    assert ann.put(f"/api/auth/integrations/{own['id']}", json={"shared": True}).status_code == 403
    assert I.get_integration(own["id"], "ann")["shared"] is False

    house = _add(boss, world.base, name="House API", auth_type="bearer", api_key=BOSS_KEY, shared=True)
    seen = {i["name"]: i for i in ann.get("/api/auth/integrations").json()["integrations"]}
    assert (seen["House API"]["read_only"], seen["House API"]["your_agents"],
            seen["House API"]["api_key"]) == (True, False, "")
    got = _agent({"integration": "House API", "path": "/"}, "ann")
    assert got["error"] == "No integration matching 'House API'. Available: Ann's Gitea"
    test = ann.post(f"/api/auth/integrations/{house['id']}/test")
    assert test.status_code == 403 and "testing it is its owner's or an admin's" in test.json()["detail"]
    assert _Service.seen == [] and world.server_requests == []
    assert BOSS_KEY not in json.dumps(world.execs), "a shared key never went to a member's workstation"


def test_testing_a_members_own_asks_from_their_workstation(world):
    ann = world.client("ann")
    own = _add(ann, world.base, name="Ann's ntfy", preset="ntfy", auth_type="bearer", api_key=ANN_KEY)
    r = ann.post(f"/api/auth/integrations/{own['id']}/test")
    assert r.json() == {"ok": True, "message": "Connection successful"}
    (hit,) = _Service.seen
    assert (hit["method"], hit["path"]) == ("GET", "/"), "the reachability GET, not the server's ntfy post"
    assert world.server_requests == [] and len(world.execs) == 1


def test_without_a_workstation_it_is_said_and_nothing_is_called(world):
    bob = world.client("bob")
    own = _add(bob, world.base, name="Bob's Gitea", auth_type="bearer", api_key="BOB-KEY")
    assert (own["called_from"], own["your_agents"]) == ("workstation", False)
    refused = _agent({"integration": "Bob's Gitea", "path": "/"}, "bob")
    assert refused["exit_code"] == 1 and "restricted to admin users" in refused["error"]
    test = bob.post(f"/api/auth/integrations/{own['id']}/test").json()
    assert test["ok"] is False and "has none turned on" in test["message"], test
    assert I.get_integrations_prompt("bob") == ""
    assert _Service.seen == [] and world.server_requests == [] and world.execs == []


def test_the_server_never_calls_a_members_own_for_a_reminder_or_a_brief(world):
    ann, boss = world.client("ann"), world.client("boss")
    own = _add(ann, world.base, name="Ann's ntfy", preset="ntfy", auth_type="none")
    house = _add(boss, world.base, name="House ntfy", preset="ntfy", auth_type="none", shared=True)
    assert [i["id"] for i in I.integrations_for("ann")] == [own["id"], house["id"]]
    assert [i["id"] for i in I.server_integrations_for("ann")] == [house["id"]]


def test_an_unowned_record_and_a_former_admins_shared_one_are_not_a_members_to_change(world, monkeypatch):
    boss, ann = world.client("boss"), world.client("ann")
    # Written after the routes' setup ran the one-time migration, so it is
    # still a record from before `P27-02`: nobody's, shared.
    I.save_integrations(I.load_integrations() + [{"id": "old1", "name": "Miniflux", "base_url": world.base}])
    for r in (ann.put("/api/auth/integrations/old1", json={"base_url": "http://elsewhere.lan"}),
              ann.delete("/api/auth/integrations/old1")):
        assert r.status_code == 403, r.text
        assert r.json()["detail"] == ("“Miniflux” is an admin's, shared with everyone to use; "
                                      "only an admin can change or remove it.")
    house = _add(boss, world.base, name="House API", auth_type="bearer", api_key=BOSS_KEY, shared=True)
    monkeypatch.setitem(_USERS, "boss", {"admin": False, "privs": {"can_use_workstation": True}})
    moved = boss.put(f"/api/auth/integrations/{house['id']}", json={"base_url": "http://elsewhere.lan"})
    assert moved.status_code == 403 and "only an admin changes it" in moved.json()["detail"]
    assert boss.put(f"/api/auth/integrations/{house['id']}", json={"shared": False}).status_code == 200
    now = I.get_integration(house["id"], "boss")
    assert now["base_url"] == world.base and I.calls_from_server(now) is False
