# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B956` — turning `sudo` off does not take back a machine an agent already had
root on, and the Settings switch says so.

With `sudo` on, an agent is root in the workstation container and can leave a
setuid shell, a cron entry or a root process outside the homes. *Reset to
clean* wipes a home, not the container; switching `sudo` off rewrites the rule
from then on. What gives a clean system back is a new container on the same
volumes, which keeps every home and account (`P20-01`'s end-to-end test) — and
Pantheon holds no Docker socket, so it cannot do that itself.

Pinned, through the real routes (with `P20-02`'s fixtures) and the real panel
module under node (with `P20-02`'s shim, built from the panel's own markup):

  * the admin's status answer carries the command, and it names the service the
    shipped overlay defines (the compose file, parsed);
  * beside the switch: that turning it off applies from now on; for the
    container, *Recreate the workstation* — homes kept — with the command and a
    Copy button that copies exactly it; for another machine, a sentence and no
    command that would not work there.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

from src import workstation_access as wa
from test_the_workstation_is_admin_controlled import (  # noqa: F401 — fixtures
    ADMIN, ALLOWED, app, as_user, auth, datadir, switch_on, ws)
from test_the_workstation_panel_js import (  # noqa: E402
    ADMIN_UP, DAEMON, SETTINGS, _PREAMBLE, _SHIM, _panel_nodes, _serving)
from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402
from tests.helpers.esc_stub import ui_default_stub
from workstation import protocol as P

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "static" / "js" / "workstation.js"
COMMAND = "docker compose up -d --force-recreate workstation"
node_only = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


# ── the server's half ────────────────────────────────────────────────────────

def test_the_command_is_the_overlays_own_service():
    assert wa.RECREATE_COMMAND == COMMAND
    overlay = yaml.safe_load((ROOT / "docker" / "workstation.yml").read_text(encoding="utf-8"))
    assert P.DEFAULT_HOST in overlay["services"], "the command names a service nothing defines"
    assert "--force-recreate" in wa.RECREATE_COMMAND.split()


def test_an_admin_is_told_the_command_and_nobody_else_is(app, ws):
    switch_on(app, ws)
    admin = as_user(app, ADMIN).get("/api/workstation/status").json()
    assert admin["settings"]["recreate_command"] == COMMAND
    assert as_user(app, ADMIN).post("/api/workstation/check").json()["settings"][
        "recreate_command"] == COMMAND
    person = as_user(app, ALLOWED).get("/api/workstation/status").json()
    assert "settings" not in person and COMMAND not in json.dumps(person)


# ── the panel ────────────────────────────────────────────────────────────────

_STUBS = {
    "ui.js": ui_default_stub(
        "styledConfirm: async () => true,\n"
        "  copyToClipboard: (t) => { (globalThis.__copied = globalThis.__copied || []).push(t); },\n"
        "  showToast: () => {}, showError: () => {},"),
    "appConfig.js": "export function invalidateSettings() {}\n",
}

_READ = """
const t = (id) => byId(id).textContent;
const shown = (id) => !byId(id).hidden;
const panel = () => ({
  after: t('ws-sudo-after'), recreate: shown('ws-recreate'), why: t('ws-recreate-why'),
  row: shown('ws-recreate-row'), cmd: t('ws-recreate-cmd'),
  copied: globalThis.__copied || [],
});
"""


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    shim = _SHIM.replace("__NODES__", json.dumps(_panel_nodes()))
    return _make_sandbox(tmp_path_factory.mktemp("sudo-switch"), MODULE, shim, _STUBS)


def _panel(sandbox, script, **fixtures):
    lets = "".join(f"const {k} = {json.dumps(v)};\n" for k, v in fixtures.items())
    return _run(sandbox, _PREAMBLE + _READ + lets, script)


ADMIN_STATUS = {**ADMIN_UP, "settings": {**SETTINGS, "recreate_command": COMMAND}}


@node_only
def test_beside_the_switch_off_applies_from_now_on_and_recreating_is_offered(sandbox):
    out = _panel(sandbox, _serving("st") + """
        await mod.open();
        byId('ws-recreate-copy').dispatchEvent({ type: 'click' });
        console.log(JSON.stringify(panel()));
    """, st=ADMIN_STATUS)
    assert out["after"] == ("Turning it off applies from now on. It cannot take back what an "
                            "agent already did as root.")
    assert out["recreate"] and out["row"]
    assert out["why"].startswith("Recreate the workstation for a clean system")
    assert "every home and account is kept" in out["why"]
    assert "Pantheon cannot do this itself" in out["why"]
    assert out["cmd"] == COMMAND
    assert out["copied"] == [COMMAND]


@node_only
@pytest.mark.parametrize("daemon_backend,setting", [("remote", "container"), (None, "vm")])
def test_another_kind_of_machine_gets_a_sentence_and_no_command(sandbox, daemon_backend, setting):
    """The daemon says what it is; while it has not said, the setting does."""
    daemon = {**DAEMON, "backend": daemon_backend} if daemon_backend else None
    status = {**ADMIN_STATUS, "daemon": daemon,
              "settings": {**ADMIN_STATUS["settings"], "backend": setting}}
    out = _panel(sandbox, _serving("st") + """
        await mod.open();
        console.log(JSON.stringify(panel()));
    """, st=status)
    assert out["recreate"] and not out["row"] and out["cmd"] == ""
    assert out["why"].startswith("For a clean system, rebuild that machine")


@node_only
def test_a_status_without_the_command_offers_none(sandbox):
    """An older server, or one that left it out: nothing to copy is shown."""
    status = {**ADMIN_UP, "settings": dict(SETTINGS)}
    out = _panel(sandbox, _serving("st") + """
        await mod.open();
        console.log(JSON.stringify(panel()));
    """, st=status)
    assert not out["row"] and out["cmd"] == ""
