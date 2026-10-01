# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B968` — the composer says which machine its workspace is on, under node.

`static/js/workspace.js` runs in the sandbox pattern
`tests/test_tool_effect_surfaces_js.py` established — the DOM shim, a stub
`ui.js` carrying the shipped escaper, an in-memory `storage.js`, a recorded
`fetch` — against the routes' answers in the shapes `routes/workspace_routes.py`
gives (`tests/test_the_workspace_is_in_the_workstation.py` drives those).
`_cmdWorkspace` is cut out of `static/js/slashCommands.js` with
`tests/helpers/js_source.js_function` and run with its three collaborators.

What a person reads (`Law 15`):

  * the pill's words say where the tools work — confined here, or starting in
    the workstation — before the picker is ever opened;
  * the picker's note says the same, from the answer it is drawing;
  * a workstation that does not answer is shown in its own sentence;
  * `/workspace set` with a folder the workstation refuses says so, and does
    not send a person looking for `/app`.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402
from tests.helpers.esc_stub import esc_source, ui_default_stub
from tests.helpers.js_source import js_function

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "static" / "js" / "workspace.js"
SLASH = ROOT / "static" / "js" / "slashCommands.js"
pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_SHIM = r"""
import { installDom, Node } from './dom.js';
export const document = installDom();

// The composer's three elements and the mode button (`static/index.html`).
for (const id of ['workspace-indicator-btn', 'workspace-indicator-name',
                  'overflow-workspace-btn', 'mode-chat-btn']) {
  const node = document.body.appendChild(new Node(id === 'workspace-indicator-name' ? 'span' : 'button'));
  node.setAttribute('id', id);
}
export const byId = (id) => document.getElementById(id);

// The shim does not parse `innerHTML`. The picker builds its modal from a
// template and then reaches in by id, so an id the template carries answers
// with one node per id — and an id it does not carry answers null.
const realQS = Node.prototype.querySelector;
Node.prototype.querySelector = function (sel) {
  const found = realQS.call(this, sel);
  if (found || !sel.startsWith('#') || !this._html) return found;
  const id = sel.slice(1);
  if (!this._html.includes(`id="${id}"`)) return null;
  this._ids = this._ids || {};
  if (!this._ids[id]) { const n = new Node('div'); n.id = id; this._ids[id] = n; }
  return this._ids[id];
};

export const calls = [];
let responder = () => ({ status: 200, body: {} });
export function respond(fn) { responder = fn; }
globalThis.fetch = async (url) => {
  calls.push(url);
  const r = await responder(url);
  return { ok: r.status >= 200 && r.status < 300, status: r.status, json: async () => r.body };
};
export const settle = () => new Promise((r) => setTimeout(r, 20));
"""

_STUBS = {
    "ui.js": ui_default_stub(
        "showToast: (m) => (globalThis.__toasts = globalThis.__toasts || []).push(m),\n"
        "  showError: (m) => (globalThis.__errors = globalThis.__errors || []).push(m),"),
    "storage.js": (
        "export const KEYS = { WORKSPACE: 'pantheon-workspace' };\n"
        "const mem = (globalThis.__store = globalThis.__store || {});\n"
        "export function get(k, f) { return k in mem ? mem[k] : (f === undefined ? null : f); }\n"
        "export function set(k, v) { mem[k] = String(v); }\n"
        "export function remove(k) { delete mem[k]; }\n"
        "export default { get, set, remove, KEYS };\n"),
    "windowDrag.js": "export function makeWindowDraggable() {}\n",
}

_PREAMBLE = (
    "import { document, byId, calls, respond, settle } from './shim.js';\n"
    "const mod = await import('./workspace.js');\n"
    "const ws = mod.default;\n"
    "const pill = () => ({ title: byId('workspace-indicator-btn').title,\n"
    "  name: byId('workspace-indicator-name').textContent,\n"
    "  shown: byId('workspace-indicator-btn').style.display !== 'none' });\n"
)

HOME = "/home/pw-ann-1a2b3c4d"
WS_TITLE = (f"Workspace in your workstation: {HOME}/proj\n"
            "The agent's shell and file tools start here.\nClick to clear.")
HOST_TITLE = ("Workspace: /app/data/proj\nFile tools are confined here; shell commands start "
              "here but are not sandboxed and can reach outside it.\nClick to clear.")


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    return _make_sandbox(tmp_path_factory.mktemp("workspace-picker"), MODULE, _SHIM, _STUBS)


def _picker(sandbox, script: str) -> dict:
    return _run(sandbox, _PREAMBLE, script)


def test_a_folder_on_this_machine_is_described_as_it_was(sandbox):
    out = _picker(sandbox, """
        ws.setWorkspace('/app/data/proj');
        console.log(JSON.stringify(pill()));
    """)
    assert out == {"title": HOST_TITLE, "name": "proj", "shown": True}


def test_a_folder_vetted_in_the_workstation_says_the_tools_start_there(sandbox):
    out = _picker(sandbox, f"""
        respond((url) => ({{ status: 200, body: {{ ok: true, path: '{HOME}/proj', where: 'workstation' }} }}));
        const answer = await ws.vetAndSetWorkspace('proj');
        console.log(JSON.stringify({{ answer, pill: pill(), stored: globalThis.__store,
                                     where: ws.getWorkspaceWhere(), calls }}));
    """)
    assert out["answer"] == {"ok": True, "path": f"{HOME}/proj", "where": "workstation"}
    assert out["pill"] == {"title": WS_TITLE, "name": "proj", "shown": True}
    assert out["stored"] == {"pantheon-workspace": f"{HOME}/proj"}
    assert [c.split("/api/")[1] for c in out["calls"]] == ["workspace/vet?path=proj"]


def test_a_refused_folder_reports_which_machine_refused_it(sandbox):
    out = _picker(sandbox, """
        respond(() => ({ status: 200, body: { ok: false, path: null, where: 'workstation' } }));
        const answer = await ws.vetAndSetWorkspace('/app');
        console.log(JSON.stringify({ answer, stored: globalThis.__store || {} }));
    """)
    assert out == {"answer": {"ok": False, "path": None, "where": "workstation"}, "stored": {}}


@pytest.mark.parametrize(("body", "title"), [
    ({"ok": True, "path": f"{HOME}/proj", "where": "workstation"}, WS_TITLE),
    ({"ok": True, "path": f"{HOME}/proj"}, HOST_TITLE.replace("/app/data/proj", f"{HOME}/proj")),
])
def test_on_load_the_pill_learns_where_its_folder_is(sandbox, body, title):
    out = _picker(sandbox, f"""
        (await import('./storage.js')).set('pantheon-workspace', '{HOME}/proj');
        respond(() => ({{ status: 200, body: {json.dumps(body)} }}));
        ws.initWorkspace();
        await settle();
        console.log(JSON.stringify({{ pill: pill(), calls }}));
    """)
    assert out["pill"]["title"] == title
    assert [c.split("/api/")[1] for c in out["calls"]] == [
        f"workspace/vet?path=%2Fhome%2Fpw-ann-1a2b3c4d%2Fproj"]


def test_on_load_with_nothing_stored_nothing_is_asked(sandbox):
    out = _picker(sandbox, """
        ws.initWorkspace();
        await settle();
        console.log(JSON.stringify({ calls, pill: pill() }));
    """)
    assert out["calls"] == [] and out["pill"]["shown"] is False


_BROWSE_WS = {"path": HOME, "parent": None, "dirs": [{"name": "proj", "path": f"{HOME}/proj"}],
              "truncated": False, "selectable": True, "where": "workstation", "home": HOME}
_BROWSE_HOST = {"path": "/app/data", "parent": "/app", "dirs": [], "truncated": False,
                "selectable": True}


def test_the_picker_note_says_which_machine_it_is_showing(sandbox):
    out = _picker(sandbox, f"""
        let answer = {json.dumps(_BROWSE_WS)};
        respond(() => ({{ status: 200, body: answer }}));
        await ws.openWorkspaceBrowser();
        const modal = document.getElementById('workspace-modal');
        const first = modal.querySelector('#workspace-note').innerHTML;
        const field = modal.querySelector('#workspace-cur-path').value;
        answer = {json.dumps(_BROWSE_HOST)};
        ws.closeWorkspaceBrowser && ws.closeWorkspaceBrowser();
        await mod.openWorkspaceBrowser();
        const second = modal.querySelector('#workspace-note').innerHTML;
        console.log(JSON.stringify({{ first, field, second }}));
    """)
    assert out["field"] == HOME
    assert out["first"] == ("These folders are in <strong>your workstation</strong>. The agent's "
                            "shell and file tools start in the one you pick; it is where they "
                            "start, not a boundary.")
    assert out["second"].startswith("File tools are <strong>confined</strong> to this folder.")


def test_a_workstation_that_does_not_answer_is_shown_in_its_own_words(sandbox):
    out = _picker(sandbox, """
        respond(() => ({ status: 503, body: { detail: 'The workstation at http://workstation:7040 did not answer (ConnectError). Is it running?' } }));
        await ws.openWorkspaceBrowser();
        console.log(JSON.stringify({ errors: globalThis.__errors || [] }));
    """)
    assert out["errors"] == ["The workstation at http://workstation:7040 did not answer "
                             "(ConnectError). Is it running?"]


# ── `/workspace set` ─────────────────────────────────────────────────────────

def _slash(tmp_path, answer: dict, args: list) -> list:
    body = js_function(SLASH.read_text(encoding="utf-8"), "async function _cmdWorkspace")
    entry = tmp_path / "slash.mjs"
    entry.write_text(
        esc_source() + "\n"
        "const uiModule = { esc };\n"
        "const replies = [];\n"
        "const slashReply = (html) => replies.push(html);\n"
        "const workspaceModule = {\n"
        "  getWorkspace: () => '',\n"
        f"  vetAndSetWorkspace: async () => ({json.dumps(answer)}),\n"
        "};\n"
        f"async function _cmdWorkspace(args, ctx) {body}\n"
        f"await _cmdWorkspace({json.dumps(args)}, {{}});\n"
        "await new Promise((r) => setTimeout(r, 10));\n"
        "console.log(JSON.stringify(replies));\n")
    import subprocess
    proc = subprocess.run(["node", str(entry)], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_workspace_set_says_a_refused_folder_is_not_in_the_workstation(tmp_path):
    replies = _slash(tmp_path, {"ok": False, "path": None, "where": "workstation"},
                     ["set", "/app"])
    assert replies == ["Not a folder in your workstation home: <code>/app</code>. Use a path "
                       "inside it, or <code>/workspace pick</code>."]


def test_workspace_set_in_the_workstation_says_where_it_set_it(tmp_path):
    replies = _slash(tmp_path, {"ok": True, "path": f"{HOME}/proj", "where": "workstation"},
                     ["set", "proj"])
    assert replies == [f"Workspace set: <code>{HOME}/proj</code> (in your workstation)"]


def test_workspace_set_on_this_machine_reads_as_it_did(tmp_path):
    replies = _slash(tmp_path, {"ok": False, "path": None}, ["set", "/nope"])
    assert replies[0].startswith("Not a usable workspace folder on the Pantheon backend: "
                                 "<code>/nope</code>. If Pantheon is running in Docker")
    replies = _slash(tmp_path, {"ok": True, "path": "/app/x"}, ["set", "/app/x"])
    assert replies == ["Workspace set: <code>/app/x</code>"]
