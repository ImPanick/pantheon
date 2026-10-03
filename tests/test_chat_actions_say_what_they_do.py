# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P23-04` — CHAT-M-6, CHAT-M-9, CHAT-M-10 and CHAT-U-22: archiving, editing
and deleting say what they do, and do it.

**What was wrong** (measured on `9560d50`):

  * **CHAT-M-6.** Archive on the chat you are in took its row out of the list
    and left it on screen, live: you went on typing into an archived chat, and
    the next list refresh blanked the model label (`sessions.js:979-991`).
  * **CHAT-M-9.** ✎ → Send on a user message starts the chat again from
    there (`/truncate`), so every later message went, without a word.
  * **CHAT-M-10 / CHAT-U-22.** "Delete this message?" under a title "Confirm"
    deleted the reply with it; "Delete this session?" — the product's word is
    *chat*. A chat emptied by deleting was a blank page.

Driven under node (`Law 20`): the real handlers cut out of `sessions.js` and
`chat.js`, over the DOM shim `test_tool_effect_surfaces_js.py` provides.
"""

import json
import shutil
from pathlib import Path

import pytest

from tests.helpers.js_source import js_definition
from tests.helpers.source_text import blank_text
from test_tool_effect_surfaces_js import _make_sandbox, _run

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _cut(path: Path, anchor: str, *, export_to_plain=True) -> str:
    src = path.read_text(encoding="utf-8")
    code = blank_text(src, "js")
    assert code.count(anchor) == 1, anchor
    out = js_definition(src, code.index(anchor))
    return out.replace("export async function", "async function", 1).replace("export function", "function", 1) \
        if export_to_plain else out


_SHIM = r"""
import { installDom, Node } from './dom.js';
export const document = installDom();
export { Node };
globalThis.history = { replaceState() {} };
globalThis.window = globalThis;
"""


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    d = tmp_path_factory.mktemp("chatactions")
    (d / "noop.js").write_text("export default {};\n")
    return _make_sandbox(d, JS / "agentStops.js", _SHIM, {})


_PRE = "import { document, Node } from './shim.js';\n"


# ── CHAT-M-6 ────────────────────────────────────────────────────────────────

def _archive_listener() -> str:
    src = (JS / "sessions.js").read_text(encoding="utf-8")
    code = blank_text(src, "js")
    at = code.index("archiveItem.addEventListener('click', async () => {")
    start = code.index("async () => {", at)
    return js_definition(src, start)


@pytest.mark.parametrize("open_chat, expect_left", [("s1", True), ("s2", False)])
def test_archiving_the_open_chat_leaves_it(sandbox, open_chat, expect_left):
    out = _run(sandbox, _PRE, """
        const calls = { detached: [], toasts: [], welcome: 0, loads: 0 };
        const box = document.createElement('div'); box.id = 'chat-history'; document.body.appendChild(box);
        const meta = document.createElement('div'); meta.id = 'current-meta'; document.body.appendChild(meta);
        box.innerHTML = '<div class="msg msg-user">hi</div>';
        let currentSessionId = %s;
        const s = { id: 's1' };
        const API_BASE = '';
        const dropdown = { style: {} };
        const Storage = { remove() {} };
        const uiModule = { el: (id) => document.getElementById(id), showToast: (m) => calls.toasts.push(m), showError: (m) => calls.toasts.push('E:' + m) };
        globalThis.fetch = async () => ({ ok: true });
        globalThis.chatModule = { detachCurrentStream: (id) => calls.detached.push(id), showWelcomeScreen: () => { calls.welcome += 1; } };
        const _forceSidebarOpen = () => {};
        const loadSessions = async () => { calls.loads += 1; };
        %s
        const handler = %s;
        await handler();
        console.log(JSON.stringify(Object.assign(calls, { current: currentSessionId, history: box.innerHTML })));
    """ % (json.dumps(open_chat), _cut(JS / "sessions.js", "function _deselectCurrentSession("), _archive_listener()))
    assert out["toasts"] == ["Chat archived"]
    assert out["loads"] == 1
    if expect_left:
        assert out["current"] is None and out["detached"] == ["s1"]
        assert out["welcome"] == 1 and out["history"] == ""
    else:
        assert out["current"] == "s2" and out["detached"] == [] and out["welcome"] == 0


# ── CHAT-M-9 ────────────────────────────────────────────────────────────────

def test_an_edit_says_what_sending_it_removes(sandbox):
    out = _run(sandbox, _PRE, """
        %s
        const msg = (cls) => { const n = document.createElement('div'); n.className = 'msg ' + cls; return n; };
        console.log(JSON.stringify([
          editRemovesNote([]),
          editRemovesNote([msg('msg-ai')]),
          editRemovesNote([msg('msg-ai'), msg('msg-ai msg-continuation')]),
          editRemovesNote([msg('msg-user')]),
          editRemovesNote([msg('msg-ai'), msg('msg-user'), msg('msg-ai'), msg('msg-system')]),
        ]));
    """ % _cut(JS / "chat.js", "export function editRemovesNote("))
    assert out == ["", "Sending removes the reply below.", "Sending removes the reply below.",
                   "Sending removes the message below.", "Sending removes the 3 messages below."]


# ── CHAT-M-10, CHAT-U-22 ────────────────────────────────────────────────────

@pytest.mark.parametrize("click, shape, question", [
    ("user", ["msg-user", "msg-ai"], "Delete this message and its reply?"),
    ("ai", ["msg-user", "msg-ai"], "Delete this reply and the message it answers?"),
    ("user", ["msg-user"], "Delete this message?"),
])
def test_a_delete_asks_about_what_it_deletes(sandbox, click, shape, question):
    out = _run(sandbox, _PRE, """
        const asked = [];
        const box = document.createElement('div'); box.id = 'chat-history'; document.body.appendChild(box);
        const nodes = %s.map((cls) => { const n = document.createElement('div'); n.className = 'msg ' + cls; box.appendChild(n); return n; });
        const uiModule = { styledConfirm: async (q, o) => { asked.push([q, o.title]); return false; } };
        const sessionModule = { getCurrentSessionId: () => 's1' };
        const chatRenderer = {};
        const API_BASE = '';
        const readRefusal = async () => ({ sentence: '' });
        %s
        await deleteMessage(nodes[%s]);
        console.log(JSON.stringify({ asked, left: box.querySelectorAll('.msg').length }));
    """ % (json.dumps(shape), _cut(JS / "chat.js", "export async function deleteMessage("),
           "0" if click == "user" else "nodes.length - 1"))
    assert out["asked"] == [[question, "Delete"]]
    assert out["left"] == len(shape), "a cancelled delete removed something"


def test_deleting_a_chat_says_chat():
    """The sessions list's own confirm, read where it is built."""
    src = (JS / "sessions.js").read_text(encoding="utf-8")
    code = blank_text(src, "js")
    at = code.index("deleteItem.addEventListener('click', async () => {")
    listener = js_definition(src, code.index("async () => {", at))
    # Scope first (`Law 20`): the listener's own confirm call, not the file.
    assert "styledConfirm('Delete this chat?', { title: 'Delete'" in listener
    assert "session" not in listener.split("styledConfirm(", 1)[1].split(")", 1)[0]
