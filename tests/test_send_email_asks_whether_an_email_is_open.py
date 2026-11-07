# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1158` (f-import) — ``_sendEmail()`` sends only an email.

The Documents panel's email footer — Send, the To/Cc/Subject inputs — is in the
panel for every document and only hidden for the others, and
``_hideEmailFields`` hides the inputs without emptying them, so the next
document opened after an email draft still has the draft's ``To`` behind it.
``_sendEmail()`` read those inputs and the editor's text without asking what was
open: run on the tree before this row with a markdown document active and a
``To`` left from a draft, it posted the markdown document's text to
``/api/email/send`` — measured below (``test_…_sends_nothing_and_says_nothing``
is red there). Before `B400` a stray click reached it with any document open.

``_sendEmail`` and the question it now asks are cut out of ``document.js`` with
``js_source`` and run under node as they ship, with the panel's inputs, its
documents and ``fetch`` as the page has them (`Law 20`): what is asserted is
what was sent and what the person was told. Stand-ins at boundaries this row
did not change: the outgoing-body sanitiser and the reply-quote stripper return
their input; the account resolver answers ``null``.

`B1941`: one press on Send reaches ``_sendEmail`` once for each of
pointerdown, pointerup and click (the capture handlers mark each event, not the
press), and ``_emailSendInFlight`` is set only after "No attachments found" is
answered. So a body that said "see attached" with nothing attached put the
question up three times, and "Send anyway" on each sent the email three times.
The last two tests run the real question and the real capture handler.
"""
import json
import re
import shutil

import pytest

from tests.helpers.js_source import js_binding, js_definition
from tests.test_a_file_imported_from_device_opens_readable import DOCJS, JS, _run_js

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _cut(signature: str) -> str:
    return js_definition(DOCJS, DOCJS.index(signature))


def _lifted() -> str:
    parts = [js_binding(DOCJS, "_ATTACH_RE"),
             _cut("function _emailRichbodyActive("),
             _cut("function _bodyMentionsAttachment(")]
    if "function _activeDocIsEmail(" in DOCJS:
        parts.append(_cut("function _activeDocIsEmail("))
    parts.append(_cut("async function _sendEmail("))
    return "\n".join(parts)


_PAGE = r"""
globalThis.window = globalThis;
const API_BASE = '';
const told = { toasts: [], errors: [] };
const uiModule = { showToast: (m) => told.toasts.push(m), showError: (m) => told.errors.push(m) };
const posted = [];
globalThis.fetch = async (url, init = {}) => {
  posted.push({ url, method: init.method || 'GET', body: init.body ? JSON.parse(init.body) : null });
  return { ok: true, status: 200, json: async () => ({ success: false, error: 'stopped here' }) };
};
const el = (props) => ({ style: {}, value: '', disabled: false, innerHTML: '', ...props,
  appendChild() {}, classList: { add() {}, remove() {} } });
const inputs = {
  'doc-email-to': el({}), 'doc-email-cc': el({}), 'doc-email-bcc': el({}),
  'doc-email-subject': el({}), 'doc-email-in-reply-to': el({}), 'doc-email-references': el({}),
  'doc-email-source-uid': el({}), 'doc-email-source-folder': el({}),
  'doc-editor-textarea': el({}), 'doc-language-select': el({}),
  // The WYSIWYG body is hidden unless an email shows it.
  'doc-email-richbody': el({ style: { display: 'none' } }),
  'doc-email-send-btn': el({ offsetParent: null }),
};
const document = {
  getElementById: (id) => inputs[id] || null,
  querySelectorAll: (sel) => sel === '#doc-email-send-btn' ? [inputs['doc-email-send-btn']] : [],
  createTextNode: (t) => t,
};
const spinnerModule = { createWhirlpool: () => ({ element: { style: {} }, destroy() {} }) };
const _sanitizeOutgoingEmailBody = (s) => s;
const _emailReplyOwnText = (s) => s;
const _emailBodyToHtml = (s) => s;
const _syncEmailRichbody = () => {};
async function _resolveComposeSendAccountId() { return null; }
const docs = new Map();
let activeDocId = null;
let _emailSendInFlight = false;
let _emailSendConfirming = false;
"""

# "No attachments found", answered "Send anyway" at once: these tests are not
# about the question.
_SEND_ANYWAY = "async function _confirmMissingAttachment() { return true; }\n"


def _run(tmp_path, body: str) -> dict:
    return _run_js(tmp_path / "send", _PAGE + _SEND_ANYWAY + _lifted() + "\n" + body)


# The panel after an email draft was open: its To/Subject are still in the
# hidden inputs, and the document now in front is somebody's notes.
_STALE = r"""
inputs['doc-email-to'].value = 'board@northwind.example.com';
inputs['doc-email-subject'].value = 'Re: Q3';
docs.set('draft-1', { id: 'draft-1', language: 'email' });
docs.set('notes-1', { id: 'notes-1', language: 'markdown' });
"""


def test_with_another_document_open_it_sends_nothing_and_says_nothing(tmp_path):
    out = _run(tmp_path, _STALE + r"""
        activeDocId = 'notes-1';
        inputs['doc-language-select'].value = 'markdown';
        inputs['doc-editor-textarea'].value = 'Private notes: salaries for 2027 NOTESSENTINEL';
        await _sendEmail();
        console.log(JSON.stringify({ posted, told }));
    """)
    assert out == {"posted": [], "told": {"toasts": [], "errors": []}}


def test_with_nothing_open_it_sends_nothing_and_says_nothing(tmp_path):
    out = _run(tmp_path, _STALE + r"""
        activeDocId = null;
        await _sendEmail();
        console.log(JSON.stringify({ posted, told }));
    """)
    assert out == {"posted": [], "told": {"toasts": [], "errors": []}}


def test_an_email_open_is_still_sent(tmp_path):
    out = _run(tmp_path, _STALE + r"""
        activeDocId = 'draft-1';
        inputs['doc-language-select'].value = 'email';
        inputs['doc-editor-textarea'].value = 'Numbers attached below. EMAILSENTINEL';
        await _sendEmail();
        console.log(JSON.stringify({ posted, told }));
    """)
    assert [p["url"] for p in out["posted"]] == ["/api/email/send"]
    sent = out["posted"][0]["body"]
    assert sent["to"] == "board@northwind.example.com" and "EMAILSENTINEL" in sent["body"]
    assert out["told"]["errors"] == ["stopped here"]


def test_a_document_just_switched_to_email_is_sent(tmp_path):
    """The type picker says Email and shows Send before `updateLanguage`'s
    PATCH has answered and the document's own language follows."""
    out = _run(tmp_path, _STALE + r"""
        activeDocId = 'notes-1';
        inputs['doc-language-select'].value = 'email';
        inputs['doc-editor-textarea'].value = 'Turned into a mail. SWITCHSENTINEL';
        await _sendEmail();
        console.log(JSON.stringify({ posted }));
    """)
    assert [p["url"] for p in out["posted"]] == ["/api/email/send"]
    assert "SWITCHSENTINEL" in out["posted"][0]["body"]["body"]


def test_an_email_with_no_recipient_is_still_refused_in_words(tmp_path):
    out = _run(tmp_path, r"""
        docs.set('draft-2', { id: 'draft-2', language: 'email' });
        activeDocId = 'draft-2';
        inputs['doc-language-select'].value = 'email';
        inputs['doc-editor-textarea'].value = 'Hello';
        await _sendEmail();
        console.log(JSON.stringify({ posted, told }));
    """)
    assert out["posted"] == [] and out["told"]["errors"] == ["To and body are required"]


def test_the_documents_own_language_is_enough(tmp_path):
    """An email whose type picker has not been drawn (no select in the panel)
    is still an email: the picker only widens the answer, never narrows it."""
    out = _run(tmp_path, _STALE + r"""
        delete inputs['doc-language-select'];
        activeDocId = 'draft-1';
        inputs['doc-editor-textarea'].value = 'No picker yet. PICKERSENTINEL';
        await _sendEmail();
        console.log(JSON.stringify({ posted }));
    """)
    assert [p["url"] for p in out["posted"]] == ["/api/email/send"]


# What Escape does to the top window (`ui.js`, the Escape arbiter): it presses
# the window's own close control, and hides a window that has none.
_ESCAPE_PRESSES = re.search(r"const closeBtn = topModal\.querySelector\('([^']+)'\)",
                            (JS / "ui.js").read_text(encoding="utf-8")).group(1)

# The real question and the real capture handler, in a page that has them:
# the question's markup read into elements that answer `querySelector` and
# `click()`, `document.body` holding what is open, and Send 80x30 in the footer.
_QUESTION = r"""
const Node = { TEXT_NODE: 3 };
const open = [];
const capture = [handleSendIntent, handleSendIntent];   // on window and on document
function dispatch(target, type, x, y) {
  const e = { type, target, clientX: x, clientY: y, defaultPrevented: false, stopped: false,
              preventDefault() { this.defaultPrevented = true; }, stopPropagation() { this.stopped = true; } };
  for (const listener of capture) if (!e.stopped) listener(e);
  if (e.stopped) return e;
  for (let n = target; n; n = n.parentNode) for (const fn of (n.listeners[type] || [])) fn(e);
  return e;
}
function one(n, s) {
  if (s[0] === '#') return n.id === s.slice(1);
  if (s[0] === '.') return n.classList.contains(s.slice(1));
  const a = /^\[([\w-]+)="([^"]*)"\]$/.exec(s);
  if (a) return n.attrs[a[1]] === a[2];
  return n.tagName === s.toUpperCase();
}
class Box {
  constructor(tag, attrs = {}) {
    this.tagName = tag.toUpperCase(); this.nodeType = 1; this.attrs = attrs; this.id = attrs.id || '';
    this.cls = new Set((attrs.class || '').split(/\s+/).filter(Boolean));
    this.classList = { add: (c) => this.cls.add(c), remove: (c) => this.cls.delete(c), contains: (c) => this.cls.has(c) };
    this.style = {}; this.listeners = {}; this.kids = []; this.parentNode = null;
  }
  set className(v) { this.cls = new Set(String(v).split(/\s+/).filter(Boolean)); }
  set innerHTML(html) {
    for (const m of String(html).matchAll(/<([a-z0-9]+)([^>]*)>/gi)) {
      const attrs = Object.fromEntries([...m[2].matchAll(/([\w-]+)="([^"]*)"/g)].map((a) => [a[1], a[2]]));
      const kid = new Box(m[1], attrs);
      kid.parentNode = this;
      this.kids.push(kid);
    }
  }
  matches(sel) { return sel.split(',').some((s) => one(this, s.trim())); }
  querySelector(sel) { return this.kids.find((k) => k.matches(sel)) || null; }
  closest(sel) { for (let n = this; n; n = n.parentNode) if (n.matches(sel)) return n; return null; }
  addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); }
  remove() { const i = open.indexOf(this); if (i >= 0) open.splice(i, 1); }
  click() { dispatch(this, 'click', 500, 400); }
}
document.createElement = (tag) => new Box(tag);
document.body = { appendChild: (n) => { open.push(n); return n; } };
const send = Object.assign(inputs['doc-email-send-btn'], {
  nodeType: 1, listeners: {}, parentNode: null,
  closest: (sel) => (sel === '#doc-email-send-btn' ? send : null),
  getBoundingClientRect: () => ({ left: 900, top: 820, right: 980, bottom: 850, width: 80, height: 30 }),
});
// A press on Send: a cancelled pointerdown suppresses mousedown, not click.
const press = () => { for (const type of ['pointerdown', 'pointerup', 'click']) dispatch(send, type, 930, 835); };
const asking = () => open.filter((w) => !w.classList.contains('hidden'));
const answer = (w, id) => w.querySelector(id).click();
const escape = (escapePresses) => {
  const top = asking().pop();
  const own = top.querySelector(escapePresses);
  if (own) own.click(); else top.classList.add('hidden');
};
const sends = () => posted.filter((p) => p.url === '/api/email/send').length;
const settle = () => new Promise((r) => setTimeout(r, 0));
docs.set('mail-1', { id: 'mail-1', language: 'email' });
activeDocId = 'mail-1';
inputs['doc-language-select'].value = 'email';
inputs['doc-email-to'].value = 'board@northwind.example.com';
inputs['doc-editor-textarea'].value = 'The figures for the board, see attached.';
"""


def _ask(tmp_path, body: str) -> dict:
    page = "\n".join((_PAGE, _cut("function _confirmMissingAttachment("), _lifted(),
                      js_binding(DOCJS, "_eventInsideElement"), js_binding(DOCJS, "handleSendIntent"),
                      _QUESTION, body))
    return _run_js(tmp_path / "ask", page)


def test_one_press_on_send_asks_once_and_sends_once(tmp_path):
    """A body that says "see attached" with nothing attached, and one press on
    Send. Before, the press put "No attachments found" up three times, and
    "Send anyway" on each question sent the email three times."""
    out = _ask(tmp_path, r"""
        press();
        const asked = asking().length;
        for (const w of asking()) answer(w, '#att-warn-send');
        await settle();
        console.log(JSON.stringify({ asked, sent: sends(), left: asking().length }));
    """)
    assert out == {"asked": 1, "sent": 1, "left": 0}, (
        "one press on Send must ask once, and Send anyway must send the email once")


def test_after_go_back_or_escape_the_next_press_asks_again(tmp_path):
    """While the question is open a press on Send is the same send, so the
    question has to close with an answer: Go back, and Escape, which presses
    Go back, leave nothing sent and let the next press ask again."""
    out = _ask(tmp_path, r"""
        press();
        const first = asking().length;
        answer(asking()[0], '#att-warn-cancel');
        await settle();
        const goneBack = { asking: asking().length, sent: sends() };
        press();
        const second = asking().length;
        escape(%s);
        await settle();
        const escaped = { asking: asking().length, sent: sends() };
        press();
        const third = asking().length;
        if (third) answer(asking()[0], '#att-warn-send');
        await settle();
        console.log(JSON.stringify({ first, goneBack, second, escaped, third, sent: sends() }));
    """ % json.dumps(_ESCAPE_PRESSES))
    assert out == {"first": 1, "goneBack": {"asking": 0, "sent": 0}, "second": 1,
                   "escaped": {"asking": 0, "sent": 0}, "third": 1, "sent": 1}
