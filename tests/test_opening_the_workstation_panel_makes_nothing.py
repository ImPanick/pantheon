# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B959` — opening the Workstation panel makes no account.

Protocol v1 answered "does my home exist" only with `ensure`, which makes it:
on the Ubuntu backend a Unix user, a home and a desktop, for a person who had
only looked. `P20-07` added the `account` route (`GET /v1/users/{account}`,
nothing made, nothing started), and the status the panel draws asks it.

Driven through the real routes on TestClient with a real `AuthManager`, the
real daemon on a port, and the real panel module under node:

  * the status and the admin's check, for a person and for an admin, make
    nothing — no account, no home, no count going up — and say `none`;
  * once the person's agent has worked there, the same look says `kept`;
  * a daemon from before the route says "cannot tell" (`unknown`) and is still
    not asked to make anything;
  * the panel puts `none` into words, and says what the machine under a
    workstation is when that changes what a person should expect (emulated,
    or still making its image).
"""
from __future__ import annotations

import asyncio
import http.client
import json
import re
import shutil

import pytest

from src import workstation_access as wa
from src.workstation_client import WorkstationClient, account_for
from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402
from tests.test_the_workstation_is_admin_controlled import (  # noqa: F401 — fixtures
    ADMIN, ALLOWED, app, as_user, auth, datadir, switch_on, ws)
from tests.test_the_workstation_panel_js import (MODULE, _PREAMBLE, _SHIM, _STUBS,
                                                 _panel_nodes)
from workstation import agentd


def run(coro):
    return asyncio.run(coro)


# ── the routes ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("who,route", [(ALLOWED, "GET status"), (ADMIN, "GET status"),
                                       (ADMIN, "POST check")])
def test_looking_makes_no_account(app, ws, who, route):  # noqa: F811 — the fixtures imported above
    switch_on(app, ws)
    method, path = route.split()
    url = "/api/workstation/" + path
    client = as_user(app, who)
    for _ in range(2):
        r = client.get(url) if method == "GET" else client.post(url)
        assert r.status_code == 200, r.text
        you = r.json()["you"]
        assert (you["home_state"], you["home"]) == (wa.HOME_NONE, None)
        assert r.json()["daemon"]["accounts"] == 0
    assert ws.system.accounts() == [], "opening the panel made an account"
    assert not (ws.root / account_for(who)).exists()


def test_after_the_agent_has_worked_there_the_same_look_says_kept(app, ws):  # noqa: F811 — the fixtures imported above
    switch_on(app, ws)
    allowed = as_user(app, ALLOWED)
    account = account_for(ALLOWED)
    run(WorkstationClient(ws.url, ws.token).exec(account, "echo hi > hello.txt"))
    you = allowed.get("/api/workstation/status").json()["you"]
    assert you["home_state"] == wa.HOME_KEPT and you["home"] == str(ws.root / account)
    assert ws.system.accounts() == [account]


def test_a_daemon_from_before_the_route_cannot_tell_and_is_not_asked_to_make(app, ws,  # noqa: F811 — the fixtures imported above
                                                                           monkeypatch):
    """Exactly the old daemon's dispatch: no bare account route, so `404`."""
    monkeypatch.setattr(agentd, "_ACCOUNT_PATH_RE", re.compile(r"(?!)"))  # matches nothing
    switch_on(app, ws)
    status = as_user(app, ALLOWED).get("/api/workstation/status").json()
    assert status["state"] == wa.STATE_UP
    assert (status["you"]["home_state"], status["you"]["home"]) == (wa.HOME_UNKNOWN, None)
    assert ws.system.accounts() == []
    seen = run(WorkstationClient(ws.url, ws.token).account(account_for(ALLOWED)))
    assert seen == {"account": account_for(ALLOWED), "exists": None, "home": None}


def test_the_route_needs_the_token_and_refuses_what_is_not_an_account(ws):  # noqa: F811 — the fixtures imported above
    with pytest.raises(Exception) as e:
        run(WorkstationClient(ws.url, "pws_wrong").account(account_for("ann")))
    assert getattr(e.value, "code", "") == "unauthorized"
    conn = http.client.HTTPConnection("127.0.0.1", int(ws.url.rsplit(":", 1)[1]))
    conn.request("GET", "/v1/users/root", headers={"Authorization": f"Bearer {ws.token}"})
    r = conn.getresponse()
    assert r.status == 400 and json.loads(r.read())["error"] == "bad_request"
    assert ws.system.accounts() == []


# ── the panel ────────────────────────────────────────────────────────────────

pytestmark_node = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    shim = _SHIM.replace("__NODES__", json.dumps(_panel_nodes()))
    return _make_sandbox(tmp_path_factory.mktemp("workstation-panel-b959"), MODULE, shim, _STUBS)


DAEMON = {"agent": "pantheon-workstation", "protocol": 1, "backend": "container",
          "version": "1.0.0", "sudo": True, "network": "full", "screen": [1280, 800],
          "accounts": 0}
UP = {"enabled": True, "is_admin": False, "may_use": True, "state": "up",
      "sentence": "The workstation is answering.", "probe": "ok", "daemon": DAEMON,
      "error": None, "you": {"account": "pw-cy-1a2b3c4d", "home": None, "home_state": "none"}}


def _read(sandbox, status) -> dict:
    lets = f"const st = {json.dumps(status)};\n"
    return _run(sandbox, _PREAMBLE + lets, """
        respond((call) => ({ status: 200, body: st }));
        await mod.open();
        console.log(JSON.stringify(read()));
    """)


@pytestmark_node
def test_a_person_with_no_home_yet_is_told_when_one_appears(sandbox):
    out = _read(sandbox, UP)
    assert out["you"] == ("Your account: pw-cy-1a2b3c4d · no home yet — it is made the first "
                          "time you or your agent work there")
    assert out["resetShown"] is True  # resetting makes the clean home, which is harmless
    kept = _read(sandbox, {**UP, "you": {"account": "pw-cy-1a2b3c4d",
                                         "home": "/home/pw-cy-1a2b3c4d", "home_state": "kept"}})
    assert kept["you"].endswith("home /home/pw-cy-1a2b3c4d (kept from before)")


@pytestmark_node
@pytest.mark.parametrize("machine,words,absent", [
    ({"virtualization": "qemu", "accel": "tcg", "image": "ready"},
     ["emulated without KVM — slow"], ["preparing", "hardware"]),
    ({"virtualization": "kvm", "accel": "kvm", "image": "preparing"},
     ["hardware-accelerated (KVM)", "preparing the machine image (first start)"], ["emulated"]),
    ({"virtualization": "qemu", "accel": "tcg", "image": "failed"},
     ["the machine image could not be prepared"], []),
    ({"virtualization": "docker", "accel": None}, [], ["KVM", "emulated", "image"]),
])
def test_the_panel_says_what_the_machine_under_it_is(sandbox, machine, words, absent):
    out = _read(sandbox, {**UP, "daemon": {**DAEMON, "backend": "vm", "machine": machine}})
    assert out["facts"].startswith("Virtual machine · protocol 1")
    for w in words:
        assert w in out["facts"], w
    for w in absent:
        assert w not in out["facts"], w


def test_the_status_passes_the_machine_through_to_the_panel(app, ws):  # noqa: F811 — the fixtures imported above
    switch_on(app, ws)
    daemon = as_user(app, ADMIN).get("/api/workstation/status").json()["daemon"]
    assert set(daemon["machine"]) == {"virtualization", "accel"}
