# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1938`. An AI reply that arrived late overwrote the draft typed meanwhile, or landed in another one.

The mail composer's AI Reply (`_aiReply` in `static/js/document.js`) checks
that the draft has no text of its own, asks `/api/email/ai-reply`, which
takes seconds, and then wrote the answer into the editor a few characters a
frame (`_streamEmailBodyText`). Only the button was disabled meanwhile, and
nothing was checked again when the answer came. So what the person typed
while it was generating was wiped and replaced, under a toast saying the AI
draft was inserted. A person who moved to another draft tab got the answer,
with the first mail's quoted thread under it, in place of that draft's own
text: one correspondent's reply, ready to send to another.

Now the answer goes in only if the draft is the one it was asked for, as it
was: the same document, the same editor, the same text. Otherwise nothing is
written and the toast says the reply is ready but the draft was edited. The
check and the write are one step, so the answer is written at once; the
letter-by-letter reveal is gone from this one place (it stays for
`replaceEmailReplyBody`), because keeping it safe would mean locking the
composer for its frames. The button comes back as `B1212` left it.

Upstream Odysseus fixed the same defect in 84aa9a91; its other half, in
`replaceEmailReplyBody`, does not apply here, because Pantheon's rich mail
body writes every keystroke into the document that check reads.

Driven (`Law 20`): `_aiReply` and the body helpers it calls are cut out of
`static/js/document.js` with `tests/helpers/js_source` and run under node on
the shared DOM shim, with the AI request held open until the case lets it
answer.
"""

import shutil
import sys
from pathlib import Path

import pytest

from tests.helpers.js_source import js_code, js_definition

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_tool_effect_surfaces_js import _DOM, _run  # noqa: E402

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

ROOT = Path(__file__).resolve().parents[1]
DOCJS = (ROOT / "static" / "js" / "document.js").read_text(encoding="utf-8")
DOCCODE = js_code(DOCJS)


def cut(*signatures: str) -> str:
    return "\n".join(js_definition(DOCJS, DOCCODE.index(sig)) + ";" for sig in signatures)


_HARNESS = r"""
const API_BASE = '';
let activeDocId = null;
let _emailAiReplyGeneration = 0;
const docs = new Map([['D1', { id: 'D1', language: 'email' }], ['D2', { id: 'D2', language: 'email' }]]);
const toasts = [];
const uiModule = { showToast: (m) => toasts.push(String(m)), showError: (m) => toasts.push('error: ' + m) };
const sessionModule = { getCurrentModel: () => 'm', getCurrentSessionId: () => 'S' };
const noop = () => {};
const syncHighlighting = noop, _persistEmailLocalDraftSoon = noop, _clearDocAiReplyContext = noop,
  _syncEmailAiButton = noop;
const _docAiReplyContextKey = () => 'k';
const _emailBodyToHtml = (t) => '<p>' + t + '</p>';
globalThis.requestAnimationFrame = (cb) => setTimeout(cb, 0);
// The AI request, held open until the case answers it.
let answer = null;
globalThis.fetch = () => new Promise((resolve) => {
  answer = () => resolve({ ok: true, status: 200,
    json: async () => ({ success: true, reply: 'AI wrote this reply', model_used: 'm' }) });
});
const Q1 = '---------- Previous message ----------\nBob: can we meet on Friday?';
const Q2 = '---------- Previous message ----------\nAlice: the contract terms';
// A reply draft on screen: its editor (the rich body and its textarea mirror)
// and the envelope fields `_aiReply` reads.
function openDraft(id, body) {
  document.getElementById('doc-editor-pane')?.remove();
  const pane = document.createElement('div');
  pane.id = 'doc-editor-pane';
  const field = (tag, fid, props) => { const n = document.createElement(tag); n.id = fid; Object.assign(n, props); pane.appendChild(n); };
  field('textarea', 'doc-editor-textarea', { value: body });
  field('div', 'doc-email-richbody', { innerHTML: _emailBodyToHtml(body) });
  field('input', 'doc-email-to', { value: 'bob@example.test' });
  field('input', 'doc-email-subject', { value: 'Re: Friday' });
  field('input', 'doc-email-in-reply-to', { value: '<m1@example.test>' });
  field('button', 'doc-email-ai-reply-btn', {});
  document.body.appendChild(pane);
  activeDocId = id;
}
// What the rich body's input listener does on a keystroke (`_syncEmailRichbody`).
function type(text, quote) {
  document.getElementById('doc-email-richbody').innerHTML = '<p>' + text + '</p>';
  document.getElementById('doc-editor-textarea').value = text + '\n\n' + quote;
}
const tick = () => new Promise((r) => setTimeout(r, 0));
async function settle() { for (let i = 0; i < 300; i += 1) await tick(); }
const editor = () => ({ text: document.getElementById('doc-editor-textarea').value,
                        rich: document.getElementById('doc-email-richbody').innerHTML });
"""

_FUNCTIONS = cut("function _emailRichbodyActive(", "function _emailQuoteStartIndex(",
                 "function _emailQuoteStartOffset(", "function _splitEmailReplyQuote(",
                 "function _setEmailBodyText(", "async function _streamEmailBodyText(",
                 "async function _aiReply(")


@pytest.fixture(scope="module")
def page(tmp_path_factory):
    d = tmp_path_factory.mktemp("b1938")
    (d / "dom.js").write_text(_DOM)
    return d


def run(page, script: str) -> dict:
    preamble = "import { installDom } from './dom.js';\nconst document = installDom();\n"
    return _run(page, preamble, _HARNESS + _FUNCTIONS + "\n" + script)


def test_what_you_type_while_it_generates_is_kept(page):
    out = run(page, """
        openDraft('D1', '\\n\\n' + Q1);
        const asked = _aiReply({});
        await tick();
        type('Hi Bob, I will call you at 3', Q1);
        answer(); await asked; await settle();
        console.log(JSON.stringify({ editor: editor(), toasts }));
    """)
    assert out["editor"] == {"text": "Hi Bob, I will call you at 3\n\n"
                                     "---------- Previous message ----------\nBob: can we meet on Friday?",
                             "rich": "<p>Hi Bob, I will call you at 3</p>"}
    assert out["toasts"] == ["AI reply ready, but draft was edited"]


def test_a_reply_asked_for_one_draft_does_not_land_in_another(page):
    """The person moved to another draft tab: the same editor now shows it."""
    out = run(page, """
        openDraft('D1', '\\n\\n' + Q1);
        const asked = _aiReply({});
        await tick();
        activeDocId = 'D2';
        document.getElementById('doc-editor-textarea').value = 'My own reply to Alice\\n\\n' + Q2;
        document.getElementById('doc-email-richbody').innerHTML = '<p>My own reply to Alice</p>';
        answer(); await asked; await settle();
        console.log(JSON.stringify({ editor: editor(), toasts }));
    """)
    assert out["editor"]["text"] == ("My own reply to Alice\n\n"
                                     "---------- Previous message ----------\nAlice: the contract terms")
    assert "Bob" not in out["editor"]["rich"] and "AI wrote" not in out["editor"]["rich"]
    assert out["toasts"] == ["AI reply ready, but draft was edited"]


def test_a_reply_is_not_said_to_be_inserted_into_an_editor_that_was_rebuilt(page):
    """The panel closed and opened again on the same draft while it generated:
    the editor the request began in is gone."""
    out = run(page, """
        openDraft('D1', '\\n\\n' + Q1);
        const asked = _aiReply({});
        await tick();
        openDraft('D1', '\\n\\n' + Q1);
        answer(); await asked; await settle();
        console.log(JSON.stringify({ editor: editor(), toasts }));
    """)
    assert out["editor"]["text"] == "\n\n---------- Previous message ----------\nBob: can we meet on Friday?"
    assert out["toasts"] == ["AI reply ready, but draft was edited"]


def test_an_untouched_draft_gets_the_reply_over_its_quote(page):
    out = run(page, """
        openDraft('D1', '\\n\\n' + Q1);
        const asked = _aiReply({});
        await tick();
        answer(); await asked; await settle();
        console.log(JSON.stringify({ editor: editor(), toasts }));
    """)
    assert out["editor"]["text"] == ("AI wrote this reply\n\n"
                                     "---------- Previous message ----------\nBob: can we meet on Friday?")
    assert out["toasts"] == ["AI draft inserted (m)"]
