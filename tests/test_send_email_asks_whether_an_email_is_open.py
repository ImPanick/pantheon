# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B-NEW` (f-import) — ``_sendEmail()`` sends only an email.

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
"""
import json
import shutil

import pytest

from tests.helpers.js_source import js_binding, js_definition
from tests.test_a_file_imported_from_device_opens_readable import DOCJS, _run_js

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
async function _confirmMissingAttachment() { return true; }
const docs = new Map();
let activeDocId = null;
let _emailSendInFlight = false;
"""


def _run(tmp_path, body: str) -> dict:
    return _run_js(tmp_path / "send", _PAGE + _lifted() + "\n" + body)


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
