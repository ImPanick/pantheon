# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P20-02` — the Workstation panel, driven under node against the real module.

`static/js/workstation.js` runs in the sandbox pattern
`tests/test_tool_effect_surfaces_js.py` established: a DOM shim, stub modules
for `ui.js` (the shipped escaper, `B874`) and `appConfig.js`, and a recorded
`fetch`. The elements are built from the panel's own markup in
`static/index.html`, so an id the module reaches for that the page does not
carry fails here rather than in a browser.

What is pinned (`Law 15` — an admin uses this without a manual — and the
row's split between who sees what):

  * a person who may use it sees their status and *Reset my workstation*, and
    nothing of the admin's;
  * a person who may not sees the sentence and no button;
  * an admin sees the settings as stored, where the address and the token came
    from, the consequence beside `sudo`, one plain sentence per network mode and
    that it is not enforced yet — and the token field is never filled;
  * every control writes its own key, then asks the workstation again;
  * a refused save is shown in the server's words and the control goes back;
  * the reset asks first, and does nothing when the answer is no;
  * down is shown in the daemon's own sentence.
"""
from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from core.auth import DEFAULT_PRIVILEGES
from test_tool_effect_surfaces_js import _DOM, _make_sandbox, _run  # noqa: E402
from tests.helpers.esc_stub import ui_default_stub
from tests.helpers.js_source import js_binding
from tests.helpers.source_text import blank_text

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "static" / "js" / "workstation.js"
INDEX = ROOT / "static" / "index.html"
pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _panel_markup() -> str:
    html = INDEX.read_text(encoding="utf-8")
    start = html.index('<div data-settings-panel="workstation"')
    end = html.index('<div data-settings-panel="system"', start)
    return html[start:end]


def _panel_nodes() -> list:
    """Every element with an id in the panel: its tag, its `type`, whether it
    starts hidden. Derived, not transcribed — the `P8` plan-window lesson."""
    markup = _panel_markup()
    nodes = []
    for m in re.finditer(r"<(\w+)\b([^>]*)\bid=\"([^\"]+)\"([^>]*)>", markup):
        attrs = m.group(2) + m.group(4)
        typ = re.search(r'\btype="([^"]+)"', attrs)
        # The text a leaf element ships with (the sentence beside `sudo`, the
        # "Checking…" before the first answer), so the sandbox page reads
        # what the real one does.
        leaf = re.match(r"([^<]*)</" + m.group(1) + r">", markup[m.end():])
        text = html.unescape(" ".join(leaf.group(1).split())) if leaf else ""
        nodes.append({"id": m.group(3), "tag": m.group(1),
                      "type": typ.group(1) if typ else "", "text": text,
                      "hidden": bool(re.search(r"\shidden(\s|$|=)", attrs))})
    assert {"ws-status", "ws-admin", "ws-reset", "ws-sudo"} <= {n["id"] for n in nodes}
    return nodes


_SHIM = r"""
import { installDom, Node } from './dom.js';
export const document = installDom();

const NODES = __NODES__;
const root = document.body.appendChild(new Node('div'));
for (const n of NODES) {
  const node = root.appendChild(new Node(n.tag));
  node.setAttribute('id', n.id);
  node.type = n.type;
  node.hidden = n.hidden;
  if (n.text) node.textContent = n.text;
  if (n.type === 'checkbox') node.checked = false;
}
export const byId = (id) => document.getElementById(id);

export const calls = [];
let responder = () => ({ status: 200, body: {} });
export function respond(fn) { responder = fn; }
globalThis.fetch = async (url, opts = {}) => {
  const call = { url, method: opts.method || 'GET', body: opts.body ? JSON.parse(opts.body) : null };
  calls.push(call);
  const r = await responder(call);
  return { ok: r.status >= 200 && r.status < 300, status: r.status, json: async () => r.body };
};
export const settle = () => new Promise((r) => setTimeout(r, 30));

/** What a person reads off the panel. */
export function read() {
  const t = (id) => (byId(id) ? byId(id).textContent : null);
  const h = (id) => (byId(id) ? byId(id).hidden : null);
  const opts = (id) => byId(id).children.map((o) => ({ value: o.value, label: o.textContent }));
  return {
    state: byId('ws-status').dataset.state,
    sentence: t('ws-status-text'),
    facts: h('ws-facts') ? null : t('ws-facts'),
    you: h('ws-you') ? null : t('ws-you'),
    resetShown: !h('ws-reset'),
    checkShown: !h('ws-check'),
    adminShown: !h('ws-admin'),
    result: h('ws-result') ? null : t('ws-result'),
    adminResult: h('ws-admin-result') ? null : t('ws-admin-result'),
    enabled: byId('ws-enabled').checked,
    sudo: byId('ws-sudo').checked,
    routeTools: byId('ws-route-tools').checked,
    url: byId('ws-url').value,
    token: byId('ws-token').value,
    backend: byId('ws-backend').value,
    network: byId('ws-network').value,
    backends: opts('ws-backend'),
    networks: opts('ws-network'),
    urlEffect: t('ws-url-effect'),
    tokenEffect: t('ws-token-effect'),
    forgetShown: !h('ws-forget-token'),
    backendEffect: t('ws-backend-effect'),
    networkEffect: t('ws-network-effect'),
    sudoWhy: t('ws-sudo-why'),
    calls,
    invalidated: globalThis.__invalidated || 0,
    confirms: globalThis.__confirms || [],
  };
}
"""

_STUBS = {
    "ui.js": ui_default_stub(
        "styledConfirm: async (message, opts) => {\n"
        "    (globalThis.__confirms = globalThis.__confirms || []).push({ message, opts });\n"
        "    return globalThis.__confirmAnswer !== false;\n"
        "  },\n"
        "  showToast: () => {}, showError: () => {},"),
    "appConfig.js": ("export function invalidateSettings() {\n"
                     "  globalThis.__invalidated = (globalThis.__invalidated || 0) + 1;\n}\n"),
}

_PREAMBLE = (
    "import { document, byId, calls, respond, settle, read } from './shim.js';\n"
    "const mod = await import('./workstation.js');\n"
)


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    shim = _SHIM.replace("__NODES__", json.dumps(_panel_nodes()))
    return _make_sandbox(tmp_path_factory.mktemp("workstation-panel"), MODULE, shim, _STUBS)


def _panel(sandbox, script: str, **fixtures) -> dict:
    lets = "".join(f"const {k} = {json.dumps(v)};\n" for k, v in fixtures.items())
    return _run(sandbox, _PREAMBLE + lets, script)


# ── what the server says, in the shapes `src/workstation_access.status_for` answers

DAEMON = {"agent": "pantheon-workstation", "protocol": 1, "backend": "container",
          "version": "1.0.0", "sudo": True, "network": "full", "screen": [1280, 800],
          "accounts": 2}
YOU = {"account": "pw-cy-1a2b3c4d", "home": "/home/pw-cy-1a2b3c4d", "home_state": "kept"}
UP = {"enabled": True, "is_admin": False, "may_use": True, "state": "up",
      "sentence": "The workstation is answering.", "probe": "ok", "daemon": DAEMON,
      "error": None, "you": YOU}
NOT_PERMITTED = {"enabled": True, "is_admin": False, "may_use": False, "state": "not_permitted",
                 "sentence": "Your account may not use the workstation. An admin can allow "
                             "it in Settings → Users.",
                 "probe": "not_checked", "daemon": None, "error": None, "you": None}
SETTINGS = {"enabled": True, "url": "http://workstation:7040", "url_source": "environment",
            "url_setting": "", "token_present": True, "token_source": "pairing",
            "backend": "container", "sudo": True, "network": "internet", "route_tools": False,
            "backends": ["container", "vm", "remote"],
            "network_modes": ["full", "internet", "none"]}
ADMIN_UP = {**UP, "is_admin": True, "settings": SETTINGS}


def _serving(status_expr: str, extra: str = "") -> str:
    """A responder: the given status for the two status routes, 200 for a
    settings write, and whatever `extra` says first."""
    return (
        "respond((call) => {\n"
        f"  {extra}\n"
        "  if (call.url === '/api/workstation/status' || call.url === '/api/workstation/check')\n"
        f"    return {{ status: 200, body: {status_expr} }};\n"
        "  return { status: 200, body: {} };\n"
        "});\n"
    )


# ── who sees what ────────────────────────────────────────────────────────────

def test_a_person_who_may_use_it_sees_their_status_and_reset_and_nothing_else(sandbox):
    out = _panel(sandbox, _serving("up") + """
        await mod.open();
        console.log(JSON.stringify(read()));
    """, up=UP)
    assert out["state"] == "up" and out["sentence"] == UP["sentence"]
    for words in ("Container beside Pantheon", "protocol 1", "daemon 1.0.0", "sudo on",
                  "network: internet and local network", "screen 1280×800", "2 accounts"):
        assert words in out["facts"], words
    assert out["you"] == ("Your account: pw-cy-1a2b3c4d · home /home/pw-cy-1a2b3c4d "
                          "(kept from before)")
    assert out["resetShown"] is True
    assert out["checkShown"] is False and out["adminShown"] is False
    assert [c["url"] for c in out["calls"]] == ["/api/workstation/status"]


def test_a_person_without_it_is_told_so_and_offered_nothing(sandbox):
    out = _panel(sandbox, _serving("np") + """
        await mod.open();
        console.log(JSON.stringify(read()));
    """, np=NOT_PERMITTED)
    assert out["state"] == "not_permitted" and "Settings → Users" in out["sentence"]
    assert (out["resetShown"], out["checkShown"], out["adminShown"]) == (False, False, False)
    assert out["facts"] is None and out["you"] is None


@pytest.mark.parametrize("state,may_use", [
    ("down", True), ("off", True), ("unconfigured", True),
    # Up, and not theirs: the server does not answer this today (a person
    # without the privilege is `not_permitted` before anything is asked), and
    # the button still needs both halves rather than trusting that it never
    # will.
    ("up", False),
])
def test_reset_is_offered_only_while_it_answers_and_only_to_whoever_may_use_it(
        sandbox, state, may_use):
    """A reset of a workstation that is down fails; a button that cannot work
    is a control left dangling."""
    status = {**UP, "state": state, "may_use": may_use,
              "sentence": "The disk the homes live on is full."}
    out = _panel(sandbox, _serving("st") + """
        await mod.open();
        console.log(JSON.stringify(read()));
    """, st=status)
    assert out["resetShown"] is False
    assert out["state"] == state


def test_down_is_shown_in_the_daemons_own_sentence(sandbox):
    status = {**UP, "state": "down", "probe": "failed", "daemon": None, "you": {**YOU, "home": None,
              "home_state": "unknown"},
              "sentence": "The workstation at http://workstation:7040 did not answer "
                          "(ConnectError). Is it running?",
              "error": {"code": "unavailable", "message": "…"}}
    out = _panel(sandbox, _serving("st") + """
        await mod.open();
        console.log(JSON.stringify(read()));
    """, st=status)
    assert out["state"] == "down"
    assert out["sentence"] == status["sentence"]
    assert out["facts"] is None, "the failure is the headline; it is not said twice"
    assert out["you"] == "Your account: pw-cy-1a2b3c4d"


def test_an_admins_check_of_a_switched_off_workstation_says_both(sandbox):
    status = {**ADMIN_UP, "enabled": False, "state": "off", "probe": "failed", "daemon": None,
              "sentence": "The workstation is off.",
              "error": {"code": "unauthorized", "message": "The workstation refused "
                        "Pantheon's token."}}
    out = _panel(sandbox, _serving("st") + """
        await mod.open();
        console.log(JSON.stringify(read()));
    """, st=status)
    assert out["sentence"] == "The workstation is off."
    assert out["facts"] == "The workstation refused Pantheon's token."


def test_pantheon_itself_not_answering_is_said(sandbox):
    out = _panel(sandbox, """
        respond(() => ({ status: 500, body: { detail: 'Internal error' } }));
        await mod.open();
        console.log(JSON.stringify(read()));
    """)
    assert out["state"] == "unknown"
    assert out["sentence"] == "Pantheon could not say how the workstation is: Internal error"


# ── the admin's card ─────────────────────────────────────────────────────────

def test_the_admin_sees_the_settings_as_stored_and_where_each_came_from(sandbox):
    out = _panel(sandbox, _serving("st") + """
        byId('ws-token').value = 'half-typed';
        await mod.open();
        console.log(JSON.stringify(read()));
    """, st=ADMIN_UP)
    assert out["adminShown"] is True and out["checkShown"] is True
    assert (out["enabled"], out["sudo"], out["routeTools"]) == (True, True, False)
    assert out["url"] == "", "the field holds what was typed here, which is nothing"
    assert out["urlEffect"] == ("In effect: http://workstation:7040 — set by the workstation "
                                "overlay (PANTHEON_WORKSTATION_URL).")
    assert out["tokenEffect"].startswith("Present — read from the pairing volume")
    assert out["forgetShown"] is False, "there is no token set here to forget"
    assert out["token"] == "half-typed", "a load wrote into the token field"
    assert out["backends"] == [
        {"value": "container", "label": "Container beside Pantheon"},
        {"value": "vm", "label": "Virtual machine"},
        {"value": "remote", "label": "Another machine"}]
    assert out["backend"] == "container" and out["network"] == "internet"
    assert out["networkEffect"].startswith("The internet, but not your local network.")
    assert "Not enforced yet" in out["networkEffect"]
    assert out["sudoWhy"] == ("With sudo on, an agent can install software — and can read "
                              "other people’s workstation homes.")


@pytest.mark.parametrize("mode,words", [
    ("full", "The internet and your local network."),
    ("internet", "The internet, but not your local network."),
    ("none", "No network at all."),
])
def test_every_network_mode_has_a_plain_sentence_and_the_honest_caveat(sandbox, mode, words):
    status = {**ADMIN_UP, "settings": {**SETTINGS, "network": mode}}
    out = _panel(sandbox, _serving("st") + """
        await mod.open();
        console.log(JSON.stringify(read()));
    """, st=status)
    assert out["networkEffect"].startswith(words)
    assert "Not enforced yet" in out["networkEffect"]


def test_a_value_the_protocol_adds_is_offered_as_itself(sandbox):
    """The choices come from the server. A mode with no words here is still a
    choice an admin can see and make."""
    status = {**ADMIN_UP, "settings": {**SETTINGS, "network_modes": ["full", "internet", "none",
                                                                     "lab-only"]}}
    out = _panel(sandbox, _serving("st") + """
        await mod.open();
        console.log(JSON.stringify(read()));
    """, st=status)
    assert {"value": "lab-only", "label": "lab-only"} in out["networks"]


def test_a_token_set_here_can_be_forgotten_and_one_from_elsewhere_cannot(sandbox):
    status = {**ADMIN_UP, "settings": {**SETTINGS, "token_source": "setting"}}
    out = _panel(sandbox, _serving("st") + """
        await mod.open();
        console.log(JSON.stringify(read()));
    """, st=status)
    assert out["forgetShown"] is True and out["tokenEffect"] == "Present — set here."
    none = {**ADMIN_UP, "settings": {**SETTINGS, "token_present": False, "token_source": "none"}}
    out = _panel(sandbox, _serving("st") + """
        await mod.open();
        console.log(JSON.stringify(read()));
    """, st=none)
    assert out["tokenEffect"].startswith("None yet.") and out["forgetShown"] is False


def test_the_daemon_disagreeing_about_what_it_is_is_said(sandbox):
    status = {**ADMIN_UP, "daemon": {**DAEMON, "backend": "vm"}}
    out = _panel(sandbox, _serving("st") + """
        await mod.open();
        console.log(JSON.stringify(read()));
    """, st=status)
    assert out["backendEffect"].endswith("The workstation that answered says it is: "
                                         "virtual machine.")


# ── the controls ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("control,key,act,value", [
    ("ws-enabled", "workstation_enabled", "node.checked = false;", False),
    ("ws-sudo", "workstation_sudo", "node.checked = false;", False),
    ("ws-route-tools", "workstation_route_tools", "node.checked = true;", True),
    ("ws-backend", "workstation_backend", "node.value = 'vm';", "vm"),
    ("ws-network", "workstation_network", "node.value = 'none';", "none"),
])
def test_each_control_writes_its_own_key_and_then_asks_again(sandbox, control, key, act, value):
    """Asking again is a *check*, not a status read: it is the call that pushes
    a changed `sudo` to the daemon."""
    out = _panel(sandbox, _serving("st") + f"""
        await mod.open();
        calls.length = 0;
        const node = byId('{control}');
        {act}
        node.dispatchEvent({{ type: 'change' }});
        await settle();
        console.log(JSON.stringify(read()));
    """, st=ADMIN_UP)
    assert [(c["method"], c["url"]) for c in out["calls"]] == [
        ("POST", "/api/auth/settings"), ("POST", "/api/workstation/check")]
    assert out["calls"][0]["body"] == {key: value}
    assert out["invalidated"] == 1 and out["adminResult"] == "Saved."


def test_a_refused_save_is_shown_in_the_servers_words_and_the_control_goes_back(sandbox):
    detail = "workstation_network is one of: full, internet, none."
    out = _panel(sandbox, _serving("st", extra=(
        "if (call.url === '/api/auth/settings') "
        f"return {{ status: 400, body: {{ detail: {json.dumps(detail)} }} }};")) + """
        await mod.open();
        calls.length = 0;
        byId('ws-network').value = 'none';
        byId('ws-network').dispatchEvent({ type: 'change' });
        await settle();
        console.log(JSON.stringify(read()));
    """, st=ADMIN_UP)
    assert out["adminResult"] == detail
    assert out["network"] == "internet", "the page kept showing a value the server refused"
    assert [c["url"] for c in out["calls"]] == ["/api/auth/settings", "/api/workstation/status"]
    assert out["invalidated"] == 0


def test_the_address_saves_with_a_token_only_when_one_was_typed(sandbox):
    out = _panel(sandbox, _serving("st") + """
        await mod.open();
        calls.length = 0;
        byId('ws-url').value = '  http://ws.lan:7040  ';
        byId('ws-save-address').dispatchEvent({ type: 'click' });
        await settle();
        const first = calls[0].body;
        calls.length = 0;
        // The check after a save puts the stored address back in the field;
        // this stub stores nothing, so the address is typed again.
        byId('ws-url').value = 'http://ws.lan:7040';
        byId('ws-token').value = ' pws_typed ';
        byId('ws-save-address').dispatchEvent({ type: 'click' });
        await settle();
        console.log(JSON.stringify({ first, second: calls[0].body, after: read() }));
    """, st=ADMIN_UP)
    assert out["first"] == {"workstation_url": "http://ws.lan:7040"}, "an empty box cleared a token"
    assert out["second"] == {"workstation_url": "http://ws.lan:7040", "workstation_token": "pws_typed"}
    assert out["after"]["token"] == "", "the token stayed in the field after it was saved"


def test_forgetting_the_token_writes_an_empty_one(sandbox):
    status = {**ADMIN_UP, "settings": {**SETTINGS, "token_source": "setting"}}
    out = _panel(sandbox, _serving("st") + """
        await mod.open();
        calls.length = 0;
        byId('ws-forget-token').dispatchEvent({ type: 'click' });
        await settle();
        console.log(JSON.stringify(read()));
    """, st=status)
    assert out["calls"][0] == {"url": "/api/auth/settings", "method": "POST",
                               "body": {"workstation_token": ""}}


def test_check_now_asks_the_check_route(sandbox):
    out = _panel(sandbox, _serving("st") + """
        await mod.open();
        calls.length = 0;
        byId('ws-check').dispatchEvent({ type: 'click' });
        await settle();
        console.log(JSON.stringify(read()));
    """, st=ADMIN_UP)
    assert [(c["method"], c["url"]) for c in out["calls"]] == [("POST", "/api/workstation/check")]


# ── reset ────────────────────────────────────────────────────────────────────

def test_reset_asks_first_and_a_no_does_nothing(sandbox):
    out = _panel(sandbox, _serving("up") + """
        globalThis.__confirmAnswer = false;
        await mod.open();
        calls.length = 0;
        byId('ws-reset').dispatchEvent({ type: 'click' });
        await settle();
        console.log(JSON.stringify(read()));
    """, up=UP)
    assert out["calls"] == [], "the reset went out without a yes"
    assert len(out["confirms"]) == 1
    asked = out["confirms"][0]
    assert asked["opts"]["danger"] is True and asked["opts"]["confirmText"] == "Reset"
    assert "Nobody else's home is touched" in asked["message"]


def test_reset_after_a_yes_resets_and_says_so(sandbox):
    out = _panel(sandbox, _serving("up", extra=(
        "if (call.url === '/api/workstation/reset') return { status: 200, body: "
        "{ ok: true, account: 'pw-cy-1a2b3c4d', sentence: 'Your workstation home is back to "
        "a clean start.' } };")) + """
        globalThis.__confirmAnswer = true;
        await mod.open();
        calls.length = 0;
        byId('ws-reset').dispatchEvent({ type: 'click' });
        await settle();
        console.log(JSON.stringify(read()));
    """, up=UP)
    assert [(c["method"], c["url"]) for c in out["calls"]] == [
        ("POST", "/api/workstation/reset"), ("GET", "/api/workstation/status")]
    assert out["calls"][0]["body"] is None, "the reset carried a body naming someone"
    assert out["result"] == "Your workstation home is back to a clean start."


def test_a_failed_reset_shows_why(sandbox):
    detail = "The workstation at http://workstation:7040 did not answer (ConnectError)."
    out = _panel(sandbox, _serving("up", extra=(
        "if (call.url === '/api/workstation/reset') "
        f"return {{ status: 503, body: {{ detail: {json.dumps(detail)} }} }};")) + """
        await mod.open();
        byId('ws-reset').dispatchEvent({ type: 'click' });
        await settle();
        console.log(JSON.stringify(read()));
    """, up=UP)
    assert out["result"] == detail


# ── the doors onto it ────────────────────────────────────────────────────────

def test_every_element_the_module_reaches_for_is_in_the_panel():
    """In the panel's own markup, not merely somewhere in the page."""
    code = blank_text(MODULE.read_text(encoding="utf-8"))
    wanted = set(re.findall(r"\$\('([a-z0-9-]+)'\)", code))
    wanted |= set(re.findall(r"onChange\('([a-z0-9-]+)'", code))
    assert len(wanted) >= 15, "the scan lost its subject"
    have = {n["id"] for n in _panel_nodes()}
    assert sorted(wanted - have) == []


def test_the_panel_is_registered_for_everyone_and_settings_opens_it(tmp_path):
    """A person an admin let use the workstation has to be able to reach their
    reset: the panel is not admin-only. Driven through the real registry."""
    registry = ROOT / "static" / "js" / "settings" / "registry.js"
    case = tmp_path / "case.mjs"
    case.write_text(
        f"import * as R from {json.dumps(registry.as_uri())};\n"
        "const p = R.getSettingsPanel('workstation');\n"
        "console.log(JSON.stringify({\n"
        "  label: p && p.label, group: p && p.group,\n"
        "  adminOnly: R.isAdminOnlySettingsTab('workstation'),\n"
        "  adminManaged: R.isAdminManagedSettingsTab('workstation'),\n"
        "  found: ['ubuntu', 'sudo', 'workstation', 'computer use'].map(\n"
        "    (q) => R.searchSettingsPanels(q, { isAdmin: false }).map((x) => x.id)),\n"
        "}));\n")
    proc = subprocess.run(["node", str(case)], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert (out["label"], out["group"]) == ("Workstation", "administration")
    assert out["adminOnly"] is False and out["adminManaged"] is False
    assert all("workstation" in ids for ids in out["found"]), out["found"]
    # `settings.js` lazy-imports the module when the tab is activated. Comments
    # blanked first, so prose naming the file cannot stand in for the import.
    code = blank_text((ROOT / "static" / "js" / "settings.js").read_text(encoding="utf-8"))
    branch = code[code.index("tab === 'workstation'"):]
    assert "import('./workstation.js')" in branch[: branch.index("}") + 60]


def test_every_privilege_an_admin_can_grant_has_a_label_in_the_users_panel(tmp_path):
    """`can_use_workstation` is granted per person in Settings → Users. The
    label map is lifted out of `admin.js` and evaluated, and every `can_*` key
    the registry declares must be in it — a privilege with no switch is one an
    admin needs a manual to grant."""
    table = js_binding((ROOT / "static" / "js" / "admin.js").read_text(encoding="utf-8"),
                       "PRIV_LABELS")
    case = tmp_path / "labels.mjs"
    case.write_text(table + ";\nconsole.log(JSON.stringify(PRIV_LABELS));\n")
    proc = subprocess.run(["node", str(case)], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    labels = json.loads(proc.stdout)
    grantable = {k for k, v in DEFAULT_PRIVILEGES.items() if k.startswith("can_")
                 and isinstance(v, bool)}
    assert sorted(grantable - set(labels)) == []
    assert "Workstation" in labels["can_use_workstation"]
