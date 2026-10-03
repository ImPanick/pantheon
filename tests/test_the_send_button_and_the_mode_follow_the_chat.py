# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P23-04` — CHAT-U-8 (the send button is four buttons) and CHAT-M-19 /
CHAT-U-3 (an agent chat opens with Chat selected).

**What was wrong** (measured on `9560d50`, `ux-chat.md` CHAT-U-8, `mech-chat.md`
CHAT-M-19):

  * an empty box on an open chat made the send button "+ New" — a mis-click
    while reading started a new chat — and Enter in an empty box did the same;
    while a reply streamed, typing turned Stop into "Queue", so there was no
    Stop while you had a draft, and a click on it queued instead of stopping;
  * the Agent / Chat toggle was one global preference: "Plan the launch week",
    an agent chat (`mode: agent` in `/api/sessions`), opened with Chat lit.

**What is pinned.** `.send-btn`'s states are `FORBIDDEN.md` Part 1 — the state
machine is kept and only which state an empty box takes changes: the real
`_updateSendBtnIcon` / `_updateStreamingSubmitButton` cut out of `app.js` and
the real mode lines cut out of `selectSession`, driven under node (`Law 20`).
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.helpers.js_source import js_definition
from tests.helpers.source_text import blank_text

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _cut(path: Path, anchor: str) -> str:
    src = path.read_text(encoding="utf-8")
    code = blank_text(src, "js")
    assert code.count(anchor) == 1, anchor
    return js_definition(src, code.index(anchor))


def _node(tmp_path, script):
    (tmp_path / "case.mjs").write_text(script, encoding="utf-8")
    proc = subprocess.run(["node", "case.mjs"], cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


_BUTTON = """
const classes = new Set();
const sendBtn = { dataset: {}, innerHTML: '', title: '',
  classList: { add: (...c) => c.forEach((x) => classes.add(x)), remove: (...c) => c.forEach((x) => classes.delete(x)),
               contains: (c) => classes.has(c) },
  addEventListener() {} };
const messageInput = { value: '' };
const _sendIcon = 'SEND', _micIcon = 'MIC', _stopIcon = 'STOP', _newChatIcon = 'PLUS';
const _isSttEnabled = () => false;
const _hasAttachments = () => false;
const groupModule = { isActive: () => false };
let welcome = false;
globalThis.document = { getElementById: () => ({ classList: { contains: () => welcome } }) };
globalThis.setTimeout = (f) => f();
globalThis.clearTimeout = () => {};
"""


def test_an_empty_box_is_never_new_chat(tmp_path):
    app = ROOT / "static" / "app.js"
    out = _node(tmp_path, _BUTTON + _cut(app, "function _updateStreamingSubmitButton(") + "\n"
                + _cut(app, "function _updateSendBtnIcon(") + """
        const seen = [];
        for (const w of [false, true]) {
          welcome = w;
          sendBtn.dataset.mode = 'send';
          _updateSendBtnIcon();
          seen.push({ mode: sendBtn.dataset.mode, icon: sendBtn.innerHTML, title: sendBtn.title });
        }
        console.log(JSON.stringify(seen));
    """)
    for state in out:
        assert state["mode"] != "newchat", "the send button offered a new chat"
        assert state == {"mode": "idle", "icon": "SEND", "title": "Send message"}


def test_while_a_reply_streams_the_button_stays_stop_with_a_draft(tmp_path):
    app = ROOT / "static" / "app.js"
    out = _node(tmp_path, _BUTTON + _cut(app, "function _updateStreamingSubmitButton(") + "\n"
                + _cut(app, "function _updateSendBtnIcon(") + """
        sendBtn.dataset.mode = 'streaming';
        messageInput.value = 'a draft for after';
        _updateSendBtnIcon();
        const typed = { icon: sendBtn.innerHTML, title: sendBtn.title, phase: sendBtn.dataset.phase };
        messageInput.value = '';
        _updateSendBtnIcon();
        console.log(JSON.stringify({ typed, empty: { icon: sendBtn.innerHTML, title: sendBtn.title } }));
    """)
    assert out["typed"] == {"icon": "STOP", "title": "Stop generation", "phase": "processing"}
    assert out["empty"] == {"icon": "STOP", "title": "Stop generation"}


def test_a_click_on_stop_stops_even_with_a_draft():
    """The click handler's streaming arm, read in its own scope: it no longer
    raises the queue flag, so `handleChatSubmit` takes the Stop branch."""
    src = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    code = blank_text(src, "js")
    at = code.index("sendBtn.addEventListener('click', (e) => {")
    handler = js_definition(src, code.index("(e) => {", at))
    hcode = blank_text(handler, "js")
    arm = js_definition(handler, hcode.index("if (sendBtn.dataset.mode === 'streaming') {"))
    assert "__pantheonQueueStreamingSubmit" not in blank_text(arm, "js")
    assert "handleSubmit(e)" in arm


@pytest.mark.parametrize("prev, mode, expect", [
    ("other", "agent", ["agent"]),
    ("other", "chat", ["chat"]),
    ("other", None, []),               # never sent: the person's toggle stands
    ("other", "research_pending", []),
    ("s1", "agent", []),               # re-reading the open chat
])
def test_a_chat_opens_in_the_mode_it_last_ran_in(tmp_path, prev, mode, expect):
    sessions = ROOT / "static" / "js" / "sessions.js"
    src = sessions.read_text(encoding="utf-8")
    code = blank_text(src, "js")
    start = code.index("export async function selectSession(")
    fn = js_definition(src, start)
    fcode = code[start:start + len(fn)]
    block = js_definition(fn, fcode.index("if (prevSessionId !== id && meta && (meta.mode === 'agent'"))
    out = _node(tmp_path, """
        const set = [];
        globalThis.window = { __pantheonSetChatMode: (m) => set.push(m) };
        const prevSessionId = %s, id = 's1';
        const meta = { id: 's1', mode: %s };
        %s
        console.log(JSON.stringify(set));
    """ % (json.dumps(prev), json.dumps(mode), block))
    assert out == expect
