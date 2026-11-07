# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1935`. A document brought back from its chip came back blank, and was saved blank.

Coming back to a chat that has a document shows the document as a chip in the
dock (`loadSessionDocs` in restore mode). That bound `activeDocId` to the
document with no editor on screen. Tapping the chip opened the panel, and
`openPanel` builds a new, empty editor: no title, no text, and the language
picker on its first option, python. The open left the document bound to that
empty editor, so the `switchToDoc` meant to draw it first saved the editor into
it: the document became untitled, empty and python. The next chat message
saved '' to the server, closing its tab deleted it, and opening any other
document while the chip was up (the Library, a chat link, an attachment)
deleted it too. With a chat's document open in the panel, clicking another
chat that has documents copied the open document's text into the other
chat's document.

Now an editor `openPanel` has just built is never bound to a document: it ends
on the empty state, and every caller draws the document it opens. The chip
still names its document while no editor is on screen, so a chat message still
carries `active_doc_id`; with the panel open, `switchToDoc` binds the document
itself. `streamDocOpen`, the one caller that binds before it opens the panel,
binds again after.

Upstream Odysseus fixed the same defect in 84aa9a91 by stamping the editor
with the document it shows. That is not what this does: Pantheon also binds
`activeDocId` where no `switchToDoc` runs (typing into an empty editor, a
streamed document, an AI update), and each of those would need the stamp.

Driven (`Law 20`): the functions are cut out of `static/js/document.js` with
`tests/helpers/js_source` and run under node on the shared DOM shim, with
`fetch` recording what the page asked the server. Of `openPanel`, only the
middle that builds and wires the editor is a stand-in, made from the
template's own markup for the three fields read back; its start and its end
are the shipped text.
"""

import json
import re
import shutil
import sys
from pathlib import Path

import pytest

from tests.helpers.js_source import js_code, js_definition, js_function

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_tool_effect_surfaces_js import _DOM, _run  # noqa: E402

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

ROOT = Path(__file__).resolve().parents[1]
DOCJS = (ROOT / "static" / "js" / "document.js").read_text(encoding="utf-8")
DOCCODE = js_code(DOCJS)


def cut(*signatures: str) -> str:
    """Each declaration as it ships, found where it is code."""
    return "\n".join(js_definition(DOCJS, DOCCODE.index(sig)) + ";" for sig in signatures)


def _fresh_fields() -> str:
    """The markup of the three fields `saveCurrentToMap` reads back, as
    `openPanel`'s template writes them."""
    body = js_function(DOCJS, "export function openPanel()")
    return "".join(re.search(p, body, re.S).group(0) for p in (
        r'<input type="hidden" id="doc-title-input"[^>]*>',
        r'<select id="doc-language-select".*?</select>',
        r'<textarea id="doc-editor-textarea"[^>]*></textarea>',
    ))


def _open_panel() -> str:
    """`openPanel` as it ships, with the editor it builds reduced to the three
    fields that matter here: its start up to `isOpen = true;`, and its end from
    the last `renderTabs();` of its own body, are the real text."""
    body = js_function(DOCJS, "export function openPanel()")
    code = js_code(body)
    head_end = code.index("isOpen = true;") + len("isOpen = true;")
    tail_at = code.rindex("\n    renderTabs();\n")
    return ("function openPanel() {" + body[1:head_end] + "\n"
            "    const pane = document.createElement('div');\n"
            "    pane.id = 'doc-editor-pane';\n"
            "    pane.innerHTML = FRESH_FIELDS;\n"
            "    document.body.appendChild(pane);\n"
            + body[tail_at:])


_HARNESS = "const FRESH_FIELDS = " + json.dumps(_fresh_fields()) + ";\n" + r"""
const API_BASE = '';
let isOpen = false, activeDocId = null, _blankDoc = null, _lastSessionId = '', _minimizedDocId = null;
let _diffModeActive = false, _activeSuggestions = [], _autoSaveDebounce = null;
let _lastAutoSaveErrorAt = 0, _streamDocId = null;
const docs = new Map();
const asked = [];
let SERVER = {};
globalThis.fetch = async (url, init = {}) => {
  const method = (init.method || 'GET').toUpperCase();
  asked.push({ method, url: String(url), body: init.body ? JSON.parse(init.body) : null });
  const m = /\/api\/documents\/([^/?]+)$/.exec(String(url));
  if (method === 'GET' && m) return { ok: true, status: 200, json: async () => SERVER[m[1]] || [] };
  return { ok: true, status: 200, json: async () => ({ version_count: 4 }) };
};
globalThis.requestAnimationFrame = () => 0;
// The dock, as `modalManager` behaves for these calls: `restore` marks the
// window restored and then runs its `restoreFn`.
const dock = new Map();
const Modals = {
  isRegistered: (id) => dock.has(id),
  register: (id, fns) => dock.set(id, { ...fns, isMinimized: false }),
  unregister: (id) => dock.delete(id),
  isMinimized: (id) => dock.get(id)?.isMinimized === true,
  minimize: (id) => { const s = dock.get(id); if (s) s.isMinimized = true; },
  restore: (id) => { const s = dock.get(id); if (!s) return false; s.isMinimized = false; s.restoreFn(); return true; },
};
const noop = () => {};
const _closeNotesForDocumentOpen = noop, _hideLoadingOverlay = noop, _showLoadingOverlay = noop,
  exitDiffMode = noop, clearSelection = noop, syncHighlighting = noop, attemptAutoDetect = noop,
  toggleCsvPreview = noop, exitHtmlPreview = noop, _setMarkdownPreviewActive = noop,
  _showEmailFields = noop, _hideEmailFields = noop, renderTabs = noop, _syncHeaderActions = noop,
  _restoreSuggestionsFromStorage = noop, _syncDocIndicator = noop, _persistEmailLocalDraftSoon = noop,
  _syncStreamDocChrome = noop, _buildEmailContent = noop;
const _releaseHelperChat = async () => {};
const uiModule = { showToast: noop, showError: noop };
const sessionModule = { current: 'A', getCurrentSessionId() { return this.current; } };
const chatContainer = document.createElement('div');
chatContainer.id = 'chat-container';
document.body.appendChild(chatContainer);
const settle = (ms = 250) => new Promise((r) => setTimeout(r, ms));
const held = (id) => { const d = docs.get(id); return d ? { title: d.title, language: d.language, content: d.content } : null; };
const shown = () => document.getElementById('doc-editor-textarea')?.value ?? null;
const writes = () => asked.filter((a) => a.method !== 'GET')
  .map((a) => a.method + ' ' + a.url + (a.body ? ' <- ' + JSON.stringify(a.body.content) : ''));
SERVER = {
  A: [{ id: 'D1', is_active: true, title: 'Plan', language: 'markdown', current_content: 'the real plan',
        version_count: 3, session_id: 'A' }],
  C: [{ id: 'C1', is_active: true, title: 'Budget', language: 'markdown', current_content: 'budget body',
        version_count: 2, session_id: 'C' }],
};
"""

_FUNCTIONS = "\n".join([
    cut("const _docOpenKey", "const _docMinimizedKey", "function _markDocVisibleState(",
        "function _isFormBackedDoc(", "function showEmptyState(", "function saveCurrentToMap(",
        "function _dropUntouchedEmptyDoc(", "function switchToDoc(", "function _detachDocFromSession(",
        "async function closeTab(", "function _ensureDocChipRegistered(", "function closePanel(",
        "async function loadSessionDocs(", "function addDocToTabs(", "async function saveDocument(",
        "function streamDocOpen("),
    _open_panel(),
])


@pytest.fixture(scope="module")
def page(tmp_path_factory):
    d = tmp_path_factory.mktemp("b1935")
    (d / "dom.js").write_text(_DOM)
    return d


def run(page, script: str) -> dict:
    preamble = ("import { installDom, installHtmlParsing } from './dom.js';\n"
                "const document = installDom();\ninstallHtmlParsing();\n")
    return _run(page, preamble, _HARNESS + _FUNCTIONS + "\n" + script)


def test_a_fresh_editor_reads_as_an_untitled_empty_python_document(page):
    """What the defect copied, read off the template: the hidden title is
    empty, the text is empty, and the picker, with no option selected, reads
    as its first option."""
    fields = _fresh_fields()
    options = re.findall(r"<option([^>]*)>", fields)
    assert 'value="python"' in options[0]
    assert not any("selected" in o for o in options)
    out = run(page, """
        const pane = document.createElement('div');
        pane.innerHTML = FRESH_FIELDS;
        document.body.appendChild(pane);
        console.log(JSON.stringify({
          title: document.getElementById('doc-title-input').value,
          text: document.getElementById('doc-editor-textarea').value,
          language: document.getElementById('doc-language-select').value,
        }));
    """)
    assert out == {"title": "", "text": "", "language": "python"}


def test_a_document_restored_from_its_chip_shows_and_saves_its_own_text(page):
    """Back to a chat with a document: a chip. Tap it, then send a message
    (the send saves the open document first)."""
    out = run(page, """
        await loadSessionDocs('A', { restoreMode: true });
        const chip = { up: Modals.isMinimized('doc-panel'), names: activeDocId, editor: shown() };
        Modals.restore('doc-panel');
        const after = { doc: held('D1'), shown: shown(), bound: activeDocId };
        await saveDocument({ silent: true });
        console.log(JSON.stringify({ chip, after, writes: writes() }));
    """)
    assert out["chip"] == {"up": True, "names": "D1", "editor": None}, (
        "the chip still names its document while no editor is on screen")
    assert out["after"]["doc"] == {"title": "Plan", "language": "markdown", "content": "the real plan"}
    assert out["after"]["shown"] == "the real plan" and out["after"]["bound"] == "D1"
    assert out["writes"] == ['PUT /api/document/D1 <- "the real plan"']


def test_opening_another_document_while_the_chip_is_up_deletes_nothing(page):
    """The Library's open (and a chat link's, an attachment's): add the tab,
    open the panel, switch to it."""
    out = run(page, """
        await loadSessionDocs('A', { restoreMode: true });
        addDocToTabs({ id: 'L9', title: 'Elsewhere', language: 'markdown', current_content: 'other' }, 'Z');
        if (!isOpen) openPanel();
        switchToDoc('L9');
        await settle(20);
        console.log(JSON.stringify({ writes: writes(), d1: held('D1'), shown: shown(), bound: activeDocId }));
    """)
    assert out["writes"] == [], "opening another document deleted the chip's document"
    assert out["d1"] == {"title": "Plan", "language": "markdown", "content": "the real plan"}
    assert out["shown"] == "other" and out["bound"] == "L9"


def test_closing_the_restored_documents_tab_keeps_it(page):
    out = run(page, """
        await loadSessionDocs('A', { restoreMode: true });
        Modals.restore('doc-panel');
        await closeTab('D1');
        await settle();
        console.log(JSON.stringify({ writes: writes() }));
    """)
    assert not [w for w in out["writes"] if w.startswith("DELETE")], out["writes"]
    assert out["writes"] == ['PUT /api/document/D1 <- "the real plan"']


def test_moving_to_another_chat_does_not_copy_the_open_document_into_its_document(page):
    """Chat A's document open in the panel; the person clicks chat C, which has
    a document and no saved open state, so it comes back as a chip."""
    out = run(page, """
        docs.set('A1', { id: 'A1', title: 'Chat A notes', language: 'markdown', content: 'A body', sessionId: 'A' });
        openPanel();
        switchToDoc('A1');
        const before = shown();
        sessionModule.current = 'C';
        await loadSessionDocs('C', { restoreMode: true });
        await settle();
        const c1 = held('C1');
        Modals.restore('doc-panel');
        await saveDocument({ silent: true });
        console.log(JSON.stringify({ before, c1, shown: shown(), writes: writes() }));
    """)
    assert out["before"] == "A body"
    assert out["c1"] == {"title": "Budget", "language": "markdown", "content": "budget body"}, (
        "chat A's open document was written into chat C's")
    assert out["shown"] == "budget body"
    assert out["writes"] == ['PUT /api/document/C1 <- "budget body"']


def test_a_document_streamed_with_the_panel_closed_stays_bound(page):
    """The one caller that binds before the panel opens: what the model
    streams is the document the editor holds."""
    out = run(page, """
        streamDocOpen('Streamed', 'markdown');
        console.log(JSON.stringify({ bound: activeDocId, streaming: _streamDocId,
                                     language: document.getElementById('doc-language-select').value }));
    """)
    assert out["bound"] is not None and out["bound"] == out["streaming"]
    assert out["language"] == "markdown"
