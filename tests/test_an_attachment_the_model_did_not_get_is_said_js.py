# SPDX-License-Identifier: AGPL-3.0-or-later
"""fx5-vision `B1284`/`B1286` — the page says what the model did not get, once.

The owner, 2026-10-08: *"Ensure not just images reach model -- that ALL
attachments and any 'attachable' context reaches the model."*

Three halves of the page, measured in Chromium on the tree before this wave
(8761, `/tmp/scratch-fx5-vision/drive/drive2.cjs`):

* **The live bubble said nothing.** The `attachments` event arrives with each
  file's `reach_note`, but `handleChatSubmit` looked the bubble up as
  `#chat-history .msg-user:last-of-type` — `:last-of-type` is the last *div*, by
  then the reply's own holder — so the lookup answered null and its handler had
  never run. (That half is driven in Chromium by
  `tests/test_an_attached_picture_reaches_the_model_in_a_browser.py`.)
* **A reload said it twice, or in the model's words.** The saved message keeps
  the brackets the model is handed (*"[Attached file: bundle.zip — contents not
  read. No extractor covers …]"*), and the bubble drew them as text. The card
  says it now, in one sentence, and the bubble no longer repeats the bracket.
* **A Library document dropped on the chat went nowhere.** The card's drag
  carries `application/x-pantheon-documents`, not files; the chat's drop handler
  read `files`, found none and returned — no card, no word.

Driven under node: the shipped `chatRenderer.js` in `tests/test_tool_effect_surfaces_js.py`'s
card sandbox, and `attachDroppedDocuments` cut out of `static/app.js` with the
shared extractor.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from test_tool_effect_surfaces_js import _run, card_sandbox  # noqa: F401  (`card_sandbox` is a fixture)
from tests.helpers.js_source import js_definition

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "static" / "app.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_PRE = (
    "import { document, history } from './shim.js';\n"
    "const cr = await import('./chatRenderer.js');\n"
)

ZIP_NOTE = "Not read: there is no reader for .zip files, so the model was not given what is in it."
ATTS = [
    {"id": "u1.zip", "name": "bundle.zip", "mime": "application/zip", "size": 22, "reach": "not_read",
     "reach_note": ZIP_NOTE},
    {"id": "u2.txt", "name": "notes.txt", "mime": "text/plain", "size": 9},
]


def _cards(sandbox, script):
    return _run(sandbox, _PRE, script)


def test_a_card_says_under_it_what_the_model_did_not_get(card_sandbox):  # noqa: F811
    out = _cards(card_sandbox, """
        const wrap = cr.buildAttachCards(%s);
        const cards = wrap.children.map((c) => ({
          name: c.dataset.name,
          notes: c.children.filter((k) => k.className === 'attach-reach-note').map((k) => k.textContent),
          role: (c.children.find((k) => k.className === 'attach-reach-note') || { getAttribute: () => null }).getAttribute('role'),
        }));
        console.log(JSON.stringify({ cards }));
    """ % json.dumps(ATTS))
    assert out["cards"][0] == {"name": "bundle.zip", "notes": [ZIP_NOTE], "role": "note"}
    assert out["cards"][1]["notes"] == [], "a file the model read whole carries no sentence"


def test_the_live_event_marks_the_cards_the_bubble_already_drew(card_sandbox):  # noqa: F811
    """The bubble is drawn before the turn's `attachments` event; the event
    puts each sentence on the card with that file's id, once."""
    plain = [{k: v for k, v in a.items() if not k.startswith("reach")} for a in ATTS]
    out = _cards(card_sandbox, """
        const wrap = cr.buildAttachCards(%s);
        const marked = cr.markAttachmentReach(wrap, %s);
        const again = cr.markAttachmentReach(wrap, %s);
        const notes = wrap.children.map((c) => c.children.filter((k) => k.className === 'attach-reach-note').map((k) => k.textContent));
        console.log(JSON.stringify({ marked, again, notes }));
    """ % (json.dumps(plain), json.dumps(ATTS), json.dumps(ATTS)))
    assert out["marked"] == 1
    assert out["notes"] == [[ZIP_NOTE], []]
    assert out["again"] == 1 and out["notes"][0] == [ZIP_NOTE], "replaced, never stacked"


def test_a_picture_is_found_by_its_id_and_a_new_sentence_replaces_the_old(card_sandbox):  # noqa: F811
    """A picture's preview carries only its upload id (no name), so the event
    must find it by id; and a later event's sentence replaces the earlier one."""
    # `previewUrl` keeps the skeleton (and its spinner, which the shim cannot
    # walk) out of the preview; the lookup under test is the same.
    pic = {"id": "p1.jpg", "name": "cat.jpg", "mime": "image/jpeg", "size": 645, "previewUrl": "blob:x"}
    out = _cards(card_sandbox, """
        const wrap = cr.buildAttachCards([%s]);
        cr.markAttachmentReach(wrap, [Object.assign({}, %s, { reach_note: 'first' })]);
        cr.markAttachmentReach(wrap, [Object.assign({}, %s, { reach_note: 'Not seen: second.' })]);
        const el = wrap.children[0];
        console.log(JSON.stringify({ kind: el.className,
          notes: el.children.filter((k) => k.className === 'attach-reach-note').map((k) => k.textContent) }));
    """ % (json.dumps(pic), json.dumps(pic), json.dumps(pic)))
    assert out == {"kind": "attach-image-preview", "notes": ["Not seen: second."]}


def test_a_reloaded_bubble_says_it_once_not_in_the_models_words(card_sandbox):  # noqa: F811
    saved = ("What does the attachment say?\n\n[Attached file: bundle.zip — contents not read. "
             "No extractor covers this file type, so nothing from the file is in this message. "
             "The upload itself is intact and can be downloaded.]\n\n[Recording attached: voice.wav — "
             "not heard. This server turns no speech into text, so nothing from the recording is in "
             "this message.]\n\n[Document content — brief]:\n# Quarterly Report\n\nbody text")
    out = _cards(card_sandbox, """
        history.childNodes = [];
        cr.addMessage('user', %s, null, { attachments: %s });
        const bubble = history.querySelector('.msg-user') || history.childNodes[0];
        // `dataset.raw` is the text the bubble draws (and copies), after the
        // attachment brackets are taken out; `readable` is everything shown.
        console.log(JSON.stringify({ raw: bubble.dataset.raw, text: bubble.readable }));
    """ % (json.dumps(saved), json.dumps(ATTS)))
    assert out["raw"] == "What does the attachment say?", out["raw"]
    text = out["text"]
    assert "[Attached file:" not in text and "contents not read" not in text
    assert "[Recording attached:" not in text and "[Document content" not in text
    assert "Quarterly Report" not in text, "a document's text is the attachment, not the message"
    assert text.count("Not read: there is no reader for .zip files") == 1


# ── a Library document dropped on the chat (`B1286`) ──────────────────────

def _drop_source() -> str:
    src = APP.read_text(encoding="utf-8")
    return js_definition(src, src.index("async function attachDroppedDocuments("))


_DROP = r"""
const added = [], toasts = [], errors = [], fetched = [];
const API_BASE = '';
globalThis.File = class { constructor(parts, name, opts) { this.name = name; this.type = (opts || {}).type;
  this.text = parts.join(''); } };
const fileHandlerModule = { addFiles: async (files, opts) => { added.push(...files.map((f) => [f.name, f.text, !!(opts && opts.skipCrop)])); } };
const uiModule = { showToast: (m) => toasts.push(m), showError: (m) => errors.push(m) };
const DOCS = {
  d1: { id: 'd1', title: 'Launch plan', language: 'markdown', current_content: '# Launch plan\n\nThe code word is MARKLIBQ7.' },
  d2: { id: 'd2', title: 'a/b: c', language: 'python', current_content: 'print(1)' },
};
globalThis.fetch = async (url) => {
  fetched.push(url);
  const id = decodeURIComponent(String(url).split('/').pop());
  return DOCS[id] ? { ok: true, json: async () => DOCS[id] } : { ok: false, status: 404, json: async () => ({}) };
};
const dt = (types) => ({ getData: (t) => types[t] || '' });
__SOURCE__
"""


def _drop(script):
    body = _DROP.replace("__SOURCE__", _drop_source()) + script
    out = subprocess.run(["node", "--input-type=module"], input=body, capture_output=True, text=True,
                         cwd=ROOT, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_a_library_document_dropped_on_the_chat_is_attached_as_its_text():
    out = _drop("""
        const took = await attachDroppedDocuments(dt({ 'application/x-pantheon-documents': '["d1"]', 'text/plain': '1 document' }));
        console.log(JSON.stringify({ took, added, toasts, errors }));
    """)
    assert out["took"] is True
    assert out["added"] == [["Launch plan.md", "# Launch plan\n\nThe code word is MARKLIBQ7.", True]]
    assert out["toasts"] == ["Attached 1 document"] and out["errors"] == []


def test_two_documents_and_one_that_is_gone_are_said(card_sandbox):  # noqa: F811
    out = _drop("""
        const took = await attachDroppedDocuments(dt({ 'application/x-pantheon-documents': '["d1","gone","d2"]' }));
        console.log(JSON.stringify({ took, names: added.map((a) => a[0]), toasts, errors }));
    """)
    assert out["names"] == ["Launch plan.md", "a b c.py"]
    assert out["toasts"] == ["Attached 2 documents"]
    assert out["errors"] == ["1 document could not be attached."]


def test_a_drop_that_carries_no_documents_is_left_to_the_file_path():
    out = _drop("""
        const took = await attachDroppedDocuments(dt({ 'text/plain': 'just words' }));
        console.log(JSON.stringify({ took, fetched, added }));
    """)
    assert out == {"took": False, "fetched": [], "added": []}
