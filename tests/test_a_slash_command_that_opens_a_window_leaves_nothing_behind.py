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
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.helpers.js_source import js_definition
from tests.helpers.source_text import blank_text
from test_tool_effect_surfaces_js import _make_sandbox, _run

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"
CHAT_JS = JS / "chat.js"
SLASH_JS = JS / "slashCommands.js"

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


@pytest.mark.parametrize("name", ["notes", "tasks", "email", "gallery", "library", "brain"])
def test_a_command_that_opens_a_window_does_not_echo_into_the_chat(tmp_path, name):
    script = """
        const out = { added: [], opened: [] };
        let _transcriptOnlyDepth = 0;
        const _persistMsg = () => {};
        const _addMessage = (role, content) => out.added.push({ role, content });
        const slashReply = () => {};
        const _makeCtx = () => ({ esc: (s) => s });
        const _fuzzyMatch = () => [];
        const _invokeSkillByName = async () => true;
        const _loadSkillSlashCatalog = async () => [];
        const _cmdToolPanel = async (tool) => { out.opened.push(tool); return true; };
        const LEGACY_ALIASES = {};
        const COMMANDS = { %s,
          help: { category: 'General', help: 'Help', handler: async () => true } };
        const _resolveCommand = (c) => (c in COMMANDS ? c : null);
        const _resolveSubcommand = () => null;
        %s
        await handleSlashCommand('/%s');
        const tool = out.added.length;
        await handleSlashCommand('/help');
        console.log(JSON.stringify({ echoed: tool, opened: out.opened, helpEchoed: out.added.length - tool }));
    """ % (_command_row(name), _dispatcher(), name)
    (tmp_path / "case.mjs").write_text(script, encoding="utf-8")
    proc = subprocess.run(["node", "case.mjs"], cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out["opened"] == [name]
    assert out["echoed"] == 0, f"/{name} echoed into the chat"
    assert out["helpEchoed"] == 1, "a command that answers in the chat still shows what was asked"
