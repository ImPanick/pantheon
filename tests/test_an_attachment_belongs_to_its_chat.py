# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B893` — a file picked in one chat was still attached, counted and sent in the next.

Reported by the owner 2026-09-20, from a screenshot of a **new, empty chat**
whose context bar read *"No attachments in this message"* directly above *"One
text or code attachment was reduced to fit it."* Two sentences about two
different messages, and the second one was the truth about a conversation the
person had left.

**What it was.** `static/js/fileHandler.js` held `pendingFiles`, `uploaded`,
`_lastUploadedMeta`, `_contextBudget` and `_contextMeasuredIds` at module scope.
The only function that cleared any of them was `clearPending`, whose only caller
was the strip's own `×`. `static/js/sessions.js` does not import the file
handler at all, and `selectSession` restores a character preset and nothing
else. So switching chats reset nothing — and `chat.js` uploads with
`{sessionId: getCurrentSessionId()}` at **send** time, which means the file went
wherever you happened to be standing when you pressed the button.

Three costs, and the owner named all three: the attachment rides into the wrong
conversation; its characters are spent out of that conversation's budget,
displacing what the message actually needed; and the model is handed a document
from a conversation it is not having.

**What it is.** A binding, not a clear. Emptying the list on a switch would
silently bin a file somebody had picked; the pending set belongs to the chat it
was picked under, comes back when that chat does, and is refused if a send names
a different one. A new chat has no attachments because it has its own empty set.

Every case here drives the real module under node. None reads the source.
"""

import json
import shutil
from pathlib import Path

import pytest

from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402
from tests.helpers.esc_stub import ui_default_stub  # B874

ROOT = Path(__file__).resolve().parents[1]
FILE_HANDLER = ROOT / "static" / "js" / "fileHandler.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


_SHIM = r"""
// A DOM small enough to draw the strip and the meter into, and a session id
// the test moves the way a person switches chats.
let _session = '';
export function setSession(id) { _session = id || ''; }
export function getSession() { return _session; }

export const posted = [];
export const asked = [];

function _el(tag) {
  const node = {
    tagName: String(tag).toUpperCase(), children: [], className: '', style: {},
    dataset: {}, attributes: {}, hidden: false, _text: '', title: '',
    appendChild(c) { this.children.push(c); c.parentNode = this; return c; },
    removeChild(c) { this.children = this.children.filter((x) => x !== c); return c; },
    remove() { if (this.parentNode) this.parentNode.removeChild(this); },
    setAttribute(k, v) { this.attributes[k] = String(v); },
    getAttribute(k) { return this.attributes[k]; },
    addEventListener() {}, removeEventListener() {},
    querySelector() { return null; },
    querySelectorAll() { return []; },
    get firstChild() { return this.children[0] || null; },
    set textContent(v) { this._text = String(v); this.children = []; },
    get textContent() {
      return this._text + this.children.map((c) => c.textContent).join('');
    },
    set innerHTML(v) { this._text = String(v); this.children = []; },
    get innerHTML() { return this._text; },
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
  };
  return node;
}

const _byId = {};
for (const id of ['attach-strip', 'context-meter', 'file-input']) _byId[id] = _el('div');

export const document = {
  getElementById: (id) => _byId[id] || null,
  createElement: _el,
  querySelector: () => null,
  querySelectorAll: () => [],
  addEventListener() {},
  body: _el('body'),
};
export const strip = _byId['attach-strip'];
export const meter = _byId['context-meter'];

globalThis.document = document;
globalThis.window = {
  matchMedia: () => ({ matches: false }),
  addEventListener() {},
  location: { origin: 'http://localhost' },
};
globalThis.URL = { createObjectURL: () => 'blob:x', revokeObjectURL() {} };
globalThis.FormData = class { append() {} };

let _uploadReply = { files: [], rejected: [] };
export function replyWith(r) { _uploadReply = r; }

globalThis.fetch = async (url, opts) => {
  const u = String(url);
  if (u.includes('/api/upload/context-budget')) {
    asked.push(u);
    return { ok: true, json: async () => _budget };
  }
  posted.push({ url: u, method: (opts && opts.method) || 'GET' });
  return { ok: true, json: async () => _uploadReply };
};

let _budget = null;
export function serveBudget(b) { _budget = b; }

export function tick() { return new Promise((r) => setTimeout(r, 0)); }

// A stand-in for a picked file. `addFiles` only ever reads name/type/size here.
export function aFile(name) {
  return { name, type: 'text/plain', size: 12, slice() { return this; } };
}
"""

_STUBS = {
    "ui.js": ui_default_stub(
        "showToast: () => {}, showError: () => {},\n"
        "  showUploadRejections: () => {}, el: (id) => document.getElementById(id),"
    ),
    "spinner.js": """
export function createWhirlpool(){ return { element: { style: {} }, destroy(){} }; }
export default {
  create: () => ({ createElement: () => document.createElement('span'),
                   start(){}, stop(){} }),
};
""",
}

_PREAMBLE = (
    "import { document, strip, meter, posted, asked, setSession, getSession,"
    " serveBudget, replyWith, tick, aFile } from './shim.js';\n"
    "const fh = await import('./fileHandler.js');\n"
    "fh.init('');\n"
    "fh.setSessionResolver(getSession);\n"
)


def _report(chars=24000, items=None):
    return {
        "budgets": [{"name": "attachment", "chars": chars, "is_ceiling": True,
                     "source": "default", "measured": True}],
        "items": items if items is not None else [],
    }


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    return _make_sandbox(
        tmp_path_factory.mktemp("attachbucket"), FILE_HANDLER, _SHIM, _STUBS
    )


def _drive(sandbox, script):
    return _run(sandbox, _PREAMBLE, script)


# ── the pending set follows the chat ─────────────────────────────────────────

def test_a_file_picked_in_one_chat_is_not_attached_in_the_next(sandbox):
    """The report, reduced to its first clause."""
    out = _drive(sandbox, """
        setSession('chat-a');
        await fh.addFiles([aFile('notes.txt')]);
        const inA = fh.getPendingCount();
        setSession('chat-b');
        const inB = fh.getPendingCount();
        console.log(JSON.stringify({ inA, inB }));
    """)
    assert out["inA"] == 1, "the file never landed in the chat it was picked in"
    assert out["inB"] == 0, (
        "a file picked in chat A is still attached in chat B — this is the "
        "defect, and it is what put someone else's document in front of the model"
    )


def test_the_file_comes_back_when_its_chat_does(sandbox):
    """A binding, not a clear. Switching away must not bin what you picked."""
    out = _drive(sandbox, """
        setSession('chat-a');
        await fh.addFiles([aFile('notes.txt')]);
        setSession('chat-b');
        const away = fh.getPendingCount();
        setSession('chat-a');
        const back = fh.getPendingInfo().map((f) => f.name);
        console.log(JSON.stringify({ away, back }));
    """)
    assert out["away"] == 0
    assert out["back"] == ["notes.txt"], (
        "the file was discarded rather than kept with its chat; a clear loses "
        "work the person did on purpose"
    )


def test_two_chats_hold_their_own_files(sandbox):
    out = _drive(sandbox, """
        setSession('chat-a');
        await fh.addFiles([aFile('a.txt')]);
        setSession('chat-b');
        await fh.addFiles([aFile('b1.txt')]);
        await fh.addFiles([aFile('b2.txt')]);
        setSession('chat-a');
        const a = fh.getPendingInfo().map((f) => f.name);
        setSession('chat-b');
        const b = fh.getPendingInfo().map((f) => f.name);
        console.log(JSON.stringify({ a, b }));
    """)
    assert out["a"] == ["a.txt"]
    assert out["b"] == ["b1.txt", "b2.txt"]


def test_a_new_chat_starts_empty_without_anything_being_wiped(sandbox):
    """`''` is its own bucket — the composer before a session exists."""
    out = _drive(sandbox, """
        setSession('');
        await fh.addFiles([aFile('draft.txt')]);
        const fresh = fh.getPendingCount();
        setSession('chat-a');
        const inChat = fh.getPendingCount();
        setSession('');
        const backOnTheNewOne = fh.getPendingCount();
        console.log(JSON.stringify({ fresh, inChat, backOnTheNewOne }));
    """)
    assert (out["fresh"], out["inChat"], out["backOnTheNewOne"]) == (1, 0, 1)


# ── the report follows the chat ──────────────────────────────────────────────

def test_the_context_report_does_not_follow_you_into_another_chat(sandbox):
    """The sentence in the owner's screenshot, pinned.

    `"One text or code attachment was reduced to fit it"` was a true statement
    about a chat the person had left, printed under `"No attachments in this
    message"` about the one they were in.
    """
    out = _drive(sandbox, """
        setSession('chat-a');
        fh.noteContextBudget(%s, ['u1']);
        const a = !!fh.getContextBudget();
        const aIds = fh.getContextMeasuredIds();
        setSession('chat-b');
        const b = !!fh.getContextBudget();
        const bIds = fh.getContextMeasuredIds();
        console.log(JSON.stringify({ a, aIds, b, bIds }));
    """ % json.dumps(_report(items=[{"name": "big.txt", "chars": 24000,
                                     "state": "truncated"}])))
    assert out["a"] is True and out["aIds"] == ["u1"]
    assert out["b"] is False, (
        "chat B is showing chat A's context report — the two sentences in the "
        "owner's screenshot are this"
    )
    assert out["bIds"] == []


def test_the_meter_is_redrawn_when_the_chat_changes(sandbox):
    """`syncSession()` is what makes the swap visible rather than merely true."""
    out = _drive(sandbox, """
        setSession('chat-a');
        fh.noteContextBudget(%s, ['u1']);
        const drawnInA = !meter.hidden;
        setSession('chat-b');
        const changed = fh.syncSession();
        console.log(JSON.stringify({ drawnInA, changed, hiddenInB: meter.hidden }));
    """ % json.dumps(_report()))
    assert out["drawnInA"] is True
    assert out["changed"] is True, "syncSession did not notice the chat had changed"
    assert out["hiddenInB"] is True, (
        "the meter kept the previous chat's bar on screen"
    )


# ── and the send is refused rather than guessed ──────────────────────────────

def test_a_send_for_a_different_chat_uploads_nothing(sandbox):
    """The half a binding alone does not give.

    `chat.js` passes the id it is sending to. If that is not the chat these
    files were picked under, the upload would put them somewhere nobody chose.
    An attachment that does not arrive is recoverable; an attachment in the
    wrong conversation is not.
    """
    out = _drive(sandbox, """
        setSession('chat-a');
        await fh.addFiles([aFile('notes.txt')]);
        const ids = await fh.uploadPending({ sessionId: 'chat-b' });
        console.log(JSON.stringify({
          ids, uploads: posted.filter((p) => p.url.includes('/api/upload')).length,
          stillPending: fh.getPendingCount(),
        }));
    """)
    assert out["ids"] == []
    assert out["uploads"] == 0, (
        "the file was uploaded into a chat it did not belong to"
    )
    assert out["stillPending"] == 1, "and the person's file was thrown away as well"


def test_a_send_for_the_right_chat_still_uploads(sandbox):
    """The guard is a guard, not a wall: the ordinary path is untouched."""
    out = _drive(sandbox, """
        setSession('chat-a');
        replyWith({ files: [{ id: 'f1', name: 'notes.txt' }], rejected: [] });
        await fh.addFiles([aFile('notes.txt')]);
        const ids = await fh.uploadPending({ sessionId: 'chat-a' });
        console.log(JSON.stringify({
          ids, uploads: posted.filter((p) => p.url.includes('/api/upload')).length,
        }));
    """)
    assert out["uploads"] >= 1, "the ordinary send stopped uploading"
    assert out["ids"] == ["f1"]


def test_a_send_that_names_no_chat_is_left_alone(sandbox):
    """Callers that pass no `sessionId` keep working — the guard reads the key
    it was given, and an absent key is not a mismatch."""
    out = _drive(sandbox, """
        setSession('chat-a');
        replyWith({ files: [{ id: 'f1', name: 'notes.txt' }], rejected: [] });
        await fh.addFiles([aFile('notes.txt')]);
        const ids = await fh.uploadPending({});
        console.log(JSON.stringify({ ids }));
    """)
    assert out["ids"] == ["f1"]
