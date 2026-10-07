# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B978` — a workstation down because its network gate was recreated says the
one command that brings it back.

The workstation runs in its network gate's namespace (`P20-06`). Recreating the
gate takes the namespace with it: the workstation exits and cannot restart into
a container that no longer exists, so it stays down until `docker compose up -d`
— measured 2026-10-01 (`docker compose up -d --force-recreate workstation-net`,
then `docker compose up -d` brought it back). Fail-closed, as it should be; but
the panel said only the client's *"…did not answer (ConnectError). Is it
running?"*. Now, when nothing answers at the workstation's address and the gate
in front of it does (its open `health`), every place that sentence reached says
`GATE_UP_SENTENCE` instead: the Settings panel's status and *Check now*, and a
routed tool's result.

Driven, not read (`Law 20`): the real routes (`P20-02`'s app, real
`AuthManager`), the real dispatcher, the real daemon — started, then stopped, so
its port is closed as a stopped container's is — and a real gate (`P20-06`'s
`RunningGate`: `workstation/gate.py` behind its own HTTP layer, its `nft`
recorded). Only the one case changes: a gate that is down too, no gate, a gate
in front of another host, something else answering, or a refused token all say
what they said before.
"""
from __future__ import annotations

import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from src import workstation_access as wa
from src.workstation_client import WorkstationClient, WorkstationError
from test_the_workstation_is_admin_controlled import (  # noqa: F401 — fixtures
    ADMIN, ALLOWED, app, as_user, auth, datadir, run, switch_on, ws)
from test_the_workstation_network_is_the_one_chosen import RunningGate, _point_at_gate
from tests.helpers.workstation_daemon import running_workstation

SENTENCE = ("The workstation's network gate is running and the workstation is not. "
            "Run docker compose up -d where you start Pantheon to bring it back.")


def _closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def gate(tmp_path, monkeypatch):
    g = RunningGate(tmp_path / "gate")
    try:
        _point_at_gate(monkeypatch, tmp_path, g)
        yield g
    finally:
        g.close()


@pytest.fixture
def stopped(tmp_path):
    """A workstation that answered and then stopped: its address, its token."""
    with running_workstation(tmp_path / "gone") as station:
        url, token = station.url, station.token
        assert run(WorkstationClient(url, token).health())["agent"] == "pantheon-workstation"
    return url, token


def _status(app, who=ADMIN, check=False):
    client = as_user(app, who)
    r = client.post("/api/workstation/check") if check else client.get("/api/workstation/status")
    assert r.status_code == 200, r.text
    return r.json()


def test_the_sentence_names_the_command():
    assert wa.GATE_UP_SENTENCE == SENTENCE
    assert "docker compose up -d" in wa.GATE_UP_SENTENCE


def test_the_panel_names_the_command_when_the_gate_answers_and_the_workstation_does_not(
        app, stopped, gate):
    url, token = stopped
    switch_on_at(app, url, token)
    for who, check in ((ADMIN, False), (ADMIN, True), (ALLOWED, False)):
        got = _status(app, who, check)
        assert got["state"] == "down" and got["sentence"] == SENTENCE, got
        assert got["error"] == {"code": "unavailable", "message": SENTENCE}


def test_a_tool_says_it_too_and_nothing_runs(app, auth, stopped, gate, monkeypatch):
    import asyncio

    import core.auth
    import src.agent_tools as agent_tools
    import src.tool_execution as te
    from src.agent_tools import ToolBlock
    url, token = stopped
    switch_on_at(app, url, token)
    ran_here = []

    async def spy(content, ctx):
        ran_here.append(content)
        return {"output": "ran here", "exit_code": 0}

    monkeypatch.setitem(agent_tools.TOOL_HANDLERS, "bash", spy)
    # A tool asks with no request at hand, so through the manager it builds
    # itself (`may_use`): this module's users.
    monkeypatch.setattr(core.auth, "AuthManager", lambda *a, **k: auth)
    _, r = asyncio.run(te.execute_tool_block(ToolBlock("bash", "echo hi"), owner=ADMIN,
                                             session_id="s1",
                                             security_context=te.NO_TOOL_SECURITY_CONTEXT))
    assert r["error"] == SENTENCE and r["workstation_error"] == "unavailable", r
    assert r["ran_in"] == "workstation" and ran_here == []


def test_up_is_up(app, ws, gate):
    switch_on(app, ws)
    got = _status(app)
    assert got["state"] == "up" and got["sentence"] == "The workstation is answering."


def test_with_the_gate_down_too_it_is_the_clients_sentence_as_before(app, stopped, gate):
    url, token = stopped
    switch_on_at(app, url, token)
    gate.close()
    got = _status(app)
    assert got["state"] == "down"
    # `P23-07` (`PERF-U-7`): the client's sentence no longer carries the
    # exception's class name.
    assert got["sentence"] == (f"The workstation at {url} did not answer. "
                               "Is it running?")


def test_without_a_gate_it_is_the_clients_sentence_as_before(app, stopped):
    url, token = stopped
    switch_on_at(app, url, token)
    assert _status(app)["sentence"].endswith("did not answer. Is it running?")


def test_a_gate_in_front_of_another_host_says_nothing_about_this_one(app, tmp_path, monkeypatch):
    g = RunningGate(tmp_path / "gate")
    try:
        # The gate is at 127.0.0.1; this workstation is named `localhost`.
        _point_at_gate(monkeypatch, tmp_path, g)
        port = _closed_port()
        switch_on_at(app, f"http://localhost:{port}", "pws_token")
        assert _status(app)["sentence"].endswith("Is it running?")
    finally:
        g.close()


class _NotAWorkstation(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = b'{"ok": true, "agent": "a-router"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def test_something_else_answering_is_said_as_before(app, gate):
    server = ThreadingHTTPServer(("127.0.0.1", 0), _NotAWorkstation)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}"
        switch_on_at(app, url, "pws_token")
        assert _status(app)["sentence"] == (f"Something answered at {url}, but it is not a "
                                            "Pantheon workstation.")
    finally:
        server.shutdown()
        server.server_close()


def test_a_refused_token_is_said_as_before(app, ws, gate):
    switch_on_at(app, ws.url, "pws_not-the-token")
    got = _status(app)
    assert got["state"] == "down" and got["error"]["code"] == "unauthorized", got


def test_the_unreachable_case_is_its_own_type_and_still_unavailable():
    """Additive: every `except WorkstationError` and every `code` check reads
    it as it read the plain error."""
    from src.workstation_client import WorkstationUnreachable
    with pytest.raises(WorkstationUnreachable) as e:
        run(WorkstationClient(f"http://127.0.0.1:{_closed_port()}", "t").health())
    assert isinstance(e.value, WorkstationError) and e.value.code == "unavailable"


def switch_on_at(app, url, token):
    r = as_user(app, ADMIN).post("/api/auth/settings", json={
        "workstation_enabled": True, "workstation_url": url, "workstation_token": token})
    assert r.status_code == 200, r.text
