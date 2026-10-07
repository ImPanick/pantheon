# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P23-04` (SET-M-22) — `/notes` + Enter opens Notes and leaves nothing
behind: no "/notes " in the message box, no "You: /notes" bubble.

**What was wrong** (measured on `9560d50`, and on this branch's base in
Chromium before the change: composer `'/notes '`, one `.msg-user` "/notes"):

  * **The box.** Enter reaches two `keydown` listeners on `#message`: the
    composer's, which submits, and the command popup's (`slashAutocomplete.js`),
    registered after it. Between the two the browser runs microtasks, so
    `handleChatSubmit` had already run the command and emptied the box when the
    popup's listener ran; it saw an empty box, found no exact match, and
    inserted the highlighted command — `"/notes "` — back in. Traced by
    wrapping the textarea's `value` setter: `''` from `handleChatSubmit`, then
    `'/notes '` from `insertSlashToken`.
  * **The bubble.** The dispatcher echoes every command as a user message
    unless its row says `noUserBubble`. A command whose whole answer is a
    window opening echoed "You: /notes" into the chat and saved it.

**What changed.** The slash branch says the box is empty (an `input` event),
so the popup closes before its Enter listener runs; the nine commands that open
a tool window carry the table's own `noUserBubble` flag.

Driven under node (`Law 20`): the real popup (`slashAutocomplete.js`) on a DOM
shim, with the real slash branch cut out of `handleChatSubmit`; and the real
dispatcher with the real `notes` row cut out of the command table.

**Round 2 (`fx2-doors`).** `P23-03` put the tool-visibility door in front of
every command (`window.pantheonToolDoor`, set by `ui_visibility.js`), and on
the merged tree (`a936b5c`) the dispatcher cases here failed with
`ReferenceError: window is not defined` — the harness ran the dispatcher
without the global it now reads. The product was right (a page always has a
`window`; the acceptance drive saw `/notes` open and `/gallery` refused); the
harness now loads the real `ui_visibility.js` beside the dispatcher. And
`B-NEW-2`: a command for a tool switched off said its refusal through
`slashReply`, which saved it into the chat as an assistant message on every
try; it now says it once in the door's toast, and the chat keeps nothing — no
echo, no reply, nothing saved (`test_a_refused_command_leaves_nothing_in_the_chat`).
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.helpers.esc_stub import esc_source
from tests.helpers.js_source import js_definition
from tests.helpers.source_text import blank_text
from test_tool_effect_surfaces_js import _make_sandbox, _run

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"
CHAT_JS = JS / "chat.js"
SLASH_JS = JS / "slashCommands.js"
UI_VIS = JS / "ui_visibility.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _slash_branch() -> str:
    """`handleChatSubmit`'s slash-command branch, braces and all."""
    src = CHAT_JS.read_text(encoding="utf-8")
    code = blank_text(src, "js")
    start = code.index("export async function handleChatSubmit(")
    handler = js_definition(src, start)
    hcode = code[start:start + len(handler)]
    return js_definition(handler, hcode.index("if (!approvalForSend && isCommand(msg.trim())) {"))


_SHIM = r"""
import { installDom } from './dom.js';
export const document = installDom();
globalThis.window = globalThis;
globalThis.addEventListener = globalThis.addEventListener || (() => {});
globalThis.Event = class Event { constructor(type, init) { this.type = type; Object.assign(this, init || {}); } };
globalThis.getComputedStyle = () => ({ lineHeight: '20px', paddingTop: '0', fontSize: '14px' });
globalThis.requestAnimationFrame = (f) => f();
"""

_SLASH_STUB = """
export const COMMANDS = {
  notes: { category: 'Tools', help: 'Open Notes', usage: '/notes', handler: () => true },
  note: { category: 'Notes', help: 'Add a note', usage: '/note', handler: () => true },
};
export const LEGACY_ALIASES = {};
export default { COMMANDS };
"""


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    return _make_sandbox(tmp_path_factory.mktemp("slashbox"), JS / "slashAutocomplete.js", _SHIM,
                         {"slashCommands.js": _SLASH_STUB})


def test_enter_on_a_typed_command_leaves_the_box_empty(sandbox):
    out = _run(sandbox, "import { document } from './shim.js';\n", """
        const ac = await import('./slashAutocomplete.js');
        const ta = document.createElement('textarea');
        ta.id = 'message';
        document.body.appendChild(ta);
        ta.getBoundingClientRect = () => ({ top: 500, left: 10, width: 600, height: 40, bottom: 540, right: 610 });
        ta.selectionStart = 0;
        ta.setSelectionRange = () => {};
        ta.focus = () => {};
        // The composer's own Enter listener, registered first, as `app.js`'s
        // is: it submits, and the submit runs the slash branch.
        const el = (id) => (id === 'message' ? ta : null);
        const uiModule = { el, autoResize() {} };
        const approvalForSend = null;
        const isCommand = (s) => s.startsWith('/');
        const handleSlashCommand = async () => true;
        const _releaseSendFlag = () => {};
        async function slashBranch(msg) {
          %s
        }
        ta.addEventListener('keydown', (e) => { if (e.key === 'Enter') slashBranch(ta.value); });
        ac.initSlashAutocomplete(ta);
        ta.value = '/notes';
        ta.dispatchEvent(new Event('input', { bubbles: true }));
        // Enter: the composer's listener, then the microtasks, then the popup's.
        const enter = { type: 'keydown', key: 'Enter', shiftKey: false, preventDefault() {}, stopPropagation() {} };
        const listeners = (ta.listeners && ta.listeners.keydown) || [];
        for (const fn of listeners) { fn.call(ta, enter); await Promise.resolve(); await Promise.resolve(); }
        console.log(JSON.stringify({ value: ta.value, n: listeners.length }));
    """ % _slash_branch().replace("const el = uiModule.el;", ""))
    assert out["n"] == 2, "the two Enter listeners were not both reached"
    assert out["value"] == "", "the command came back into the box after it ran"


def _command_row(name: str) -> str:
    """The real row for `name` in the command table, cut from the source."""
    src = SLASH_JS.read_text(encoding="utf-8")
    table = src.index("const COMMANDS")
    m = re.compile(r"\n  %s: \{\n" % re.escape(name)).search(src, table)
    assert m, name
    return name + ": " + js_definition(src, m.end() - 2)


def _dispatcher() -> str:
    src = SLASH_JS.read_text(encoding="utf-8")
    code = blank_text(src, "js")
    return js_definition(src, code.index("async function handleSlashCommand("))


def _cmd_open() -> str:
    """`_cmdOpen`, the handler of the real `open` row, cut from the source."""
    src = SLASH_JS.read_text(encoding="utf-8")
    code = blank_text(src, "js")
    return js_definition(src, code.index("async function _cmdOpen("))


# The real dispatcher, the real rows, and the real door: `ui_visibility.js`
# sets `window.pantheonToolDoor` when it loads, and says a refusal through
# `window.uiModule.showToast` unless it is handed something else to say it with.
# `slashReply` is stubbed the way the real one ends — in `_persistMsg`.
_DISPATCH = """
    const out = { added: [], persisted: [], replies: [], opened: [], toasts: [] };
    globalThis.window = { uiModule: { showToast: (m) => out.toasts.push(String(m)) } };
    const V = await import(__UI_VIS__);
    let _transcriptOnlyDepth = 0;
    const _persistMsg = (role, content) => { out.persisted.push({ role, content }); };
    const _addMessage = (role, content) => out.added.push({ role, content });
    const slashReply = (text) => { out.replies.push(text); _persistMsg('assistant', text, { source: 'slash' }); };
    __ESC__
    const _makeCtx = () => ({ esc: _shippedEsc });
    const _fuzzyMatch = () => [];
    const _invokeSkillByName = async () => true;
    const _loadSkillSlashCatalog = async () => [];
    const _cmdToolPanel = async (tool) => { out.opened.push(tool); return true; };
    let cookbookModule = null, settingsModule = null;
    const document = { getElementById: (id) => ({ click: () => out.opened.push(id) }) };
    const LEGACY_ALIASES = {};
    const COMMANDS = { __ROWS__,
      help: { category: 'General', help: 'Help', handler: async () => true } };
    const _resolveCommand = (c) => (c in COMMANDS ? c : null);
    const _resolveSubcommand = () => null;
    __DISPATCHER__
    __EXTRA__
    __BODY__
    console.log(JSON.stringify(out));
"""


def _dispatch(tmp_path, rows, body, extra="") -> dict:
    script = (_DISPATCH
              .replace("__UI_VIS__", json.dumps(UI_VIS.as_uri()))
              .replace("__ESC__", esc_source("_shippedEsc"))
              .replace("__ROWS__", ",\n".join(rows))
              .replace("__DISPATCHER__", _dispatcher())
              .replace("__EXTRA__", extra)
              .replace("__BODY__", body))
    (tmp_path / "case.mjs").write_text(script, encoding="utf-8")
    proc = subprocess.run(["node", "case.mjs"], cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("name", ["notes", "tasks", "email", "gallery", "library", "brain"])
def test_a_command_that_opens_a_window_does_not_echo_into_the_chat(tmp_path, name):
    out = _dispatch(tmp_path, [_command_row(name)], """
        await handleSlashCommand('/%s');
        out.echoed = out.added.length;
        await handleSlashCommand('/help');
        out.helpEchoed = out.added.length - out.echoed;
    """ % name)
    assert out["opened"] == [name]
    assert out["echoed"] == 0, f"/{name} echoed into the chat"
    assert out["helpEchoed"] == 1, "a command that answers in the chat still shows what was asked"
    assert out["toasts"] == [], "nothing is switched off, so the door says nothing"


# Each command's tool switched off in one of the three columns (`P23-03`).
_OFF = {
    "gallery": "{ features: { gallery: false } }",                         # for everyone
    "brain": "{ features: { memory: false } }",                            # for everyone
    "library": "{ privileges: { can_use_documents: false }, auth: true }", # for this person
    "notes": "{ ui: { 'tool-notes': false } }",                            # in this browser
    "tasks": "{ ui: { 'tool-tasks': false } }",                            # in this browser
    "email": "{ ui: { 'email-section': false } }",                         # in this browser
}


@pytest.mark.parametrize("name", sorted(_OFF))
def test_a_refused_command_leaves_nothing_in_the_chat(tmp_path, name):
    """`B-NEW-2`. Measured on `a936b5c`: with Gallery off, `/gallery` + Enter
    said *Gallery is switched off for everyone…* through `slashReply`, which
    saved it; six tries left six assistant rows in the chat's history."""
    out = _dispatch(tmp_path, [_command_row(name)], """
        V.applyToolVisibility(%s, null);
        out.sentence = V.toolRefusal(V.toolKeyFor({ slash: '%s' }));
        out.handled = await handleSlashCommand('/%s');
    """ % (_OFF[name], name, name))
    assert out["handled"] is True, "a refused command is still the slash path's, never sent to the model"
    assert out["opened"] == [], f"/{name} opened a window that is switched off"
    assert out["sentence"], "the table has no refusal for this tool"
    assert out["toasts"] == [out["sentence"]], "the refusal is said once, in the door's toast"
    assert out["replies"] == [], "the refusal became a reply in the chat"
    assert out["added"] == [], f"/{name} was echoed into the chat"
    assert out["persisted"] == [], "something about a refused command was saved into the chat"
    if name == "gallery":
        assert out["sentence"] == ("Gallery is switched off for everyone. An admin can turn it "
                                   "back on in Settings → Agent Tools.")


def test_settings_opens_without_an_echo_or_a_chat_to_hold_it(tmp_path):
    """Found driving `B-NEW-2` at `:8732`: `/settings tools` echoed and was
    saved into the chat, and a guest on the welcome screen got a new chat in
    the sidebar for each `/settings appearance` (0 → 1 → 2). The real
    `settings` row and `_cmdSettings` behind the real dispatcher: Settings
    opens on the tab asked for, and nothing reaches the chat."""
    src = SLASH_JS.read_text(encoding="utf-8")
    handler = js_definition(src, blank_text(src, "js").index("async function _cmdSettings("))
    out = _dispatch(tmp_path, [_command_row("settings")], """
        settingsModule = { open: (tab) => out.opened.push('settings:' + (tab || '')) };
        await handleSlashCommand('/settings appearance');
    """, extra=handler)
    assert out["opened"] == ["settings:appearance"]
    assert out["added"] == [] and out["persisted"] == [] and out["replies"] == []


def test_open_by_name_opens_without_an_echo_and_refuses_without_a_trace(tmp_path):
    """`/open notes` is a window opening like `/notes` (`SET-M-22`), and
    `/open gallery` with Gallery off is refused like `/gallery` (`B-NEW-2`):
    the real `open` row and its real handler behind the real dispatcher."""
    out = _dispatch(tmp_path, [_command_row("open")], """
        await handleSlashCommand('/open notes');
        out.afterNotes = { opened: out.opened.slice(), added: out.added.length, persisted: out.persisted.length };
        V.applyToolVisibility({ features: { gallery: false } }, null);
        await handleSlashCommand('/open gallery');
    """, extra=_cmd_open())
    assert out["afterNotes"] == {"opened": ["tool-notes-btn"], "added": 0, "persisted": 0}
    assert out["opened"] == ["tool-notes-btn"], "/open gallery pressed the Gallery's hidden door"
    assert out["toasts"] == ["Gallery is switched off for everyone. An admin can turn it back on "
                             "in Settings → Agent Tools."]
    assert out["replies"] == [] and out["added"] == [] and out["persisted"] == []
