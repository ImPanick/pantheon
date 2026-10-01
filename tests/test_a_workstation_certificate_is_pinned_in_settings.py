# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B980`. Settings → Workstation let an admin type a remote workstation's
address and paste its token, but the certificate `workstation/install.py` makes
could be pinned only with `PANTHEON_WORKSTATION_CERT_SHA256` — so an admin who
pointed the panel at `https://` got *"presented a certificate Pantheon cannot
verify … set PANTHEON_WORKSTATION_CERT_SHA256"*, and had to edit `.env` and
restart. Now `workstation_tls_pin` sits beside the token: admin-only, refused
to the agent, validated by `workstation_client.normalise_pin`, resolved setting
→ environment by one function (`resolve_pin`), shown as the fingerprint the
installer prints, and never a way to turn verification off.

Driven: the real settings route and status route (the app the
`P20-02` tests build), a real daemon serving TLS with the installer's own
certificate, Pantheon's real client, the agent's real settings tool, and the
panel module under node. Nothing reads a source file (`Law 20`).
"""
from __future__ import annotations

import asyncio
import json
import shutil
import threading

import pytest

import src.settings as S
from src import workstation_access as wa
from src import workstation_client as wc
from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402
from tests.test_the_workstation_is_admin_controlled import (  # noqa: F401 — fixtures
    ADMIN, ALLOWED, PLAIN, app, as_user, auth, datadir, stored)
from tests.test_the_workstation_panel_js import (MODULE, _PREAMBLE, _SHIM, _STUBS,
                                                 _panel_nodes)
from workstation import install
from workstation import protocol as P
from workstation.agentd import SingleUserSystem, make_server, server_context

TOKEN = "pws_b980-the-remote-workstations-token"


def run(coro):
    return asyncio.run(coro)


def _cert(tmp_path, name):
    plan = install.Plan(dry_run=False, root=tmp_path / name)
    pin = install.make_certificate(plan, ["127.0.0.2"])
    return (plan.path(install.TLS_DIR / "cert.pem"), plan.path(install.TLS_DIR / "key.pem"), pin)


@pytest.fixture
def remote(tmp_path, monkeypatch):
    """A workstation elsewhere, as `install.py` sets one up: TLS with the
    certificate it made. `(url, fingerprint as printed, another certificate's)`."""
    for var in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(var, "127.0.0.2")
    monkeypatch.delenv(P.TLS_PIN_ENV, raising=False)
    cert, key, pin = _cert(tmp_path, "this")
    _, _, other = _cert(tmp_path, "other")
    system = SingleUserSystem(tmp_path / "homes", backend="remote")
    server = make_server(system, TOKEN, bind="127.0.0.2", port=0, tls=server_context(cert, key))
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05},
                     daemon=True).start()
    try:
        yield f"https://127.0.0.2:{server.server_address[1]}", pin, other
    finally:
        server.shutdown()
        server.server_close()


def _point_at(app, url, **extra):
    body = {"workstation_enabled": True, "workstation_url": url, "workstation_token": TOKEN,
            **extra}
    return as_user(app, ADMIN).post("/api/auth/settings", json=body)


# ── the row's `Verify:` ──────────────────────────────────────────────────────

def test_an_admin_pastes_the_printed_fingerprint_and_the_workstation_answers(app, remote):
    url, printed, _ = remote
    assert printed.count(":") == 31, "premise: the installer prints AB:CD:… — what is pasted"
    r = _point_at(app, url)
    assert r.status_code == 200, r.text
    before = as_user(app, ADMIN).get("/api/workstation/status").json()
    assert before["state"] == wa.STATE_DOWN and "cannot verify" in before["sentence"]
    assert "Settings → Workstation" in before["sentence"], "the sentence names the field"
    r = as_user(app, ADMIN).post("/api/auth/settings", json={"workstation_tls_pin": printed})
    assert r.status_code == 200, r.text
    assert stored("workstation_tls_pin") == wc.normalise_pin(printed)
    status = as_user(app, ADMIN).get("/api/workstation/status").json()
    assert status["state"] == wa.STATE_UP, status["sentence"]
    view = status["settings"]
    assert (view["tls_pin"], view["tls_pin_source"]) == (printed.upper(), wc.SOURCE_SETTING)


def test_a_wrong_fingerprint_says_which_certificate_was_presented(app, remote):
    url, printed, other = remote
    _point_at(app, url, workstation_tls_pin=other)
    status = as_user(app, ADMIN).get("/api/workstation/status").json()
    assert status["state"] == wa.STATE_DOWN
    assert wc.normalise_pin(printed) in status["sentence"], "which certificate was presented"
    assert "Settings → Workstation" in status["sentence"] and "sent nothing" in status["sentence"]


# ── one source of truth, setting then environment ────────────────────────────

def test_the_setting_beats_the_environment_and_empty_falls_back_to_it(app, remote, monkeypatch):
    url, printed, other = remote
    monkeypatch.setenv(P.TLS_PIN_ENV, printed)
    _point_at(app, url)
    admin = as_user(app, ADMIN)
    status = admin.get("/api/workstation/status").json()
    assert status["state"] == wa.STATE_UP
    assert status["settings"]["tls_pin_source"] == wc.SOURCE_ENVIRONMENT
    admin.post("/api/auth/settings", json={"workstation_tls_pin": other})
    assert admin.get("/api/workstation/status").json()["state"] == wa.STATE_DOWN
    admin.post("/api/auth/settings", json={"workstation_tls_pin": ""})
    status = admin.get("/api/workstation/status").json()
    assert status["state"] == wa.STATE_UP and status["settings"]["tls_pin_source"] == "environment"


def test_a_stored_value_that_is_not_a_fingerprint_refuses_rather_than_trusts_less(
        app, remote, monkeypatch):
    """A hand-edited file: the setting is there and unreadable. It is not
    skipped for the environment's pin or the trust store — it is refused."""
    url, printed, _ = remote
    monkeypatch.setenv(P.TLS_PIN_ENV, printed)
    _point_at(app, url)
    S.save_settings({**S.load_settings(), "workstation_tls_pin": "not-a-fingerprint"})
    S._invalidate_caches()
    status = as_user(app, ADMIN).get("/api/workstation/status").json()
    assert status["state"] == wa.STATE_DOWN
    assert "Settings → Workstation" in status["sentence"] and "64 hex" in status["sentence"]


@pytest.mark.parametrize("value,expected", [
    ("sha256 Fingerprint=" + ":".join(["AB"] * 32), "ab" * 32),   # what openssl prints
    (":".join(["ab"] * 32), "ab" * 32),
    ("AB" * 32, "ab" * 32),
    (" " + " ".join(["Cd"] * 32) + " ", "cd" * 32),
    ("", ""),
    (None, ""),
])
def test_what_is_stored_is_the_fingerprint(value, expected):
    assert wa.validate_setting("workstation_tls_pin", value) == expected


@pytest.mark.parametrize("value", ["ab" * 31, "zz" * 32, "ab" * 33, 1234, ["ab" * 32],
                                   "ab" * 32 + "\nX-Evil: 1"])
def test_anything_else_is_refused_at_the_door(app, value):
    r = as_user(app, ADMIN).post("/api/auth/settings", json={"workstation_tls_pin": value})
    assert r.status_code == 400, r.text
    assert "workstation_tls_pin" in r.json()["detail"]
    assert stored("workstation_tls_pin") == ""


@pytest.mark.parametrize("who", [PLAIN, ALLOWED, None])
def test_only_an_admin_pins_a_certificate(app, who):
    r = as_user(app, who).post("/api/auth/settings", json={"workstation_tls_pin": "ab" * 32})
    assert r.status_code in (401, 403), r.text
    assert stored("workstation_tls_pin") == ""


def test_the_agent_may_not_pin_one(datadir):
    from src.agent_tools.admin_tools import do_manage_settings

    def agent(**args):
        answer = run(do_manage_settings(json.dumps(args)))
        S._invalidate_caches()
        return answer

    answer = agent(action="set", key="workstation_tls_pin", value="ab" * 32)
    assert S.get_setting("workstation_tls_pin") == ""
    assert "Settings" in str(answer.get("response", ""))
    S.save_settings({**S.load_settings(), "workstation_tls_pin": "cd" * 32})
    S._invalidate_caches()
    agent(action="reset", key="workstation_tls_pin")
    assert S.get_setting("workstation_tls_pin") == "cd" * 32


def test_it_ships_empty_and_is_one_of_the_workstation_keys():
    from src.settings import DEFAULT_SETTINGS
    assert DEFAULT_SETTINGS["workstation_tls_pin"] == ""
    assert "workstation_tls_pin" in wa.SETTING_KEYS


# ── the panel ────────────────────────────────────────────────────────────────

pytestmark_node = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    shim = _SHIM.replace("__NODES__", json.dumps(_panel_nodes()))
    return _make_sandbox(tmp_path_factory.mktemp("workstation-panel-b980"), MODULE, shim, _STUBS)


PIN = ":".join(["AB", "CD"] * 16)
SETTINGS = {"enabled": True, "url": "https://ws.lan:7040", "url_source": "setting",
            "url_setting": "https://ws.lan:7040", "token_present": True, "token_source": "setting",
            "backend": "remote", "sudo": True, "network": "full", "route_tools": True,
            "backends": ["container", "vm", "remote"], "network_modes": ["full", "internet", "none"],
            "recreate_command": "docker compose up -d --force-recreate workstation"}
STATUS = {"enabled": True, "is_admin": True, "may_use": True, "state": "up",
          "sentence": "The workstation is answering.", "probe": "ok", "daemon": None,
          "error": None, "you": None, "settings": SETTINGS}


def _panel(sandbox, settings, script):
    lets = f"const st = {json.dumps({**STATUS, 'settings': settings})};\n"
    return _run(sandbox, _PREAMBLE + lets, """
        respond((call) => (call.url === '/api/auth/settings' ? { status: 200, body: {} }
                                                             : { status: 200, body: st }));
        await mod.open();
    """ + script)


@pytestmark_node
@pytest.mark.parametrize("source,pin,setting,words", [
    ("setting", PIN, PIN, f"Pinned: {PIN} — set here."),
    ("environment", PIN, "", f"Pinned: {PIN} — from PANTHEON_WORKSTATION_CERT_SHA256."),
    ("none", "", "", "None: an https:// address is checked against the system's trusted "
                     "certificates. For one workstation/install.py set up, paste the "
                     "fingerprint it printed."),
])
def test_the_panel_shows_the_fingerprint_and_where_it_came_from(sandbox, source, pin, setting,
                                                               words):
    settings = {**SETTINGS, "tls_pin": pin, "tls_pin_source": source, "tls_pin_setting": setting}
    out = _panel(sandbox, settings, """
        console.log(JSON.stringify({
          value: document.getElementById('ws-tls-pin').value,
          effect: document.getElementById('ws-tls-pin-effect').textContent,
        }));
    """)
    assert out == {"value": setting, "effect": words}


@pytestmark_node
def test_saving_the_address_sends_the_pin_only_when_it_changed(sandbox):
    """Not secret, so the field shows what is stored — and an untouched field
    writes nothing, so saving an address never rewrites a pin by accident."""
    settings = {**SETTINGS, "tls_pin": PIN, "tls_pin_source": "setting", "tls_pin_setting": PIN}
    out = _panel(sandbox, settings, f"""
        calls.length = 0;
        byId('ws-save-address').dispatchEvent({{ type: 'click' }});
        await settle();
        const untouched = calls[0].body;
        calls.length = 0;
        byId('ws-tls-pin').value = '  {PIN.lower()}  ';
        byId('ws-save-address').dispatchEvent({{ type: 'click' }});
        await settle();
        const changed = calls[0].body;
        calls.length = 0;
        byId('ws-tls-pin').value = '';
        byId('ws-save-address').dispatchEvent({{ type: 'click' }});
        await settle();
        console.log(JSON.stringify({{ untouched, changed, cleared: calls[0].body }}));
    """)
    assert out["untouched"] == {"workstation_url": "https://ws.lan:7040"}
    assert out["changed"] == {"workstation_url": "https://ws.lan:7040",
                              "workstation_tls_pin": PIN.lower()}
    assert out["cleared"] == {"workstation_url": "https://ws.lan:7040", "workstation_tls_pin": ""}
