# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P23-08` — the Library and Mail do what they say (the browser half).

Measured on `9560d50` (`Doc1-Mechanism-report.md`, docs auditor):

* DOCS-M-1 — six Replies on one mail left six chats "Email: Q3 Board Pack –
  final (v2)" with no messages, still listed after their drafts were closed;
  the Library's Create on the welcome screen left one named for the time.
* DOCS-M-2 — Create POSTed an empty "Untitled" at once: three Creates closed
  untyped were three junk rows.
* DOCS-M-6 — a PDF whose pages this server cannot draw was found out by a 503
  from `render-pages`, under a `pip install` line.
* DOCS-M-11 — every CSV card logged "Could not find the language 'csv'".
* DOCS-M-12 — an imported `.txt` was stored as markdown.
* DOCS-M-13 — a 170-byte attachment read "0 KB".

Driven (`Law 20`): each function is cut out of the module it ships in with
`tests/helpers/js_source.js_definition` and run under node on the shared DOM
shim, with `fetch` recording what the page asked the server; the `.txt` import
runs the Library's real import door against the real routers on a loopback
socket (`B400`'s harness). Nothing greps a source file for a word.
"""

import json
import shutil
import sys
from pathlib import Path

import pytest

from tests.helpers.js_source import js_definition

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_tool_effect_surfaces_js import _DOM, _run  # noqa: E402
from test_document_folders_js import _CARD, _cut as _doclib_cut, _js as _doclib_js, sandbox  # noqa: E402,F401
from tests.test_a_file_imported_from_device_opens_readable import (  # noqa: E402,F401
    _docs, _file, _node, live,
)
from tests.test_an_uploaded_document_keeps_its_name import env  # noqa: E402,F401

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"
DOCJS = (JS / "document.js").read_text(encoding="utf-8")
INBOXJS = (JS / "emailInbox.js").read_text(encoding="utf-8")
MAILJS = (JS / "emailLibrary.js").read_text(encoding="utf-8")
DOCLIBJS = (JS / "documentLibrary.js").read_text(encoding="utf-8")


def cut(source: str, *signatures: str) -> str:
    """Each declaration as it ships, by the text it starts with."""
    return "\n".join(js_definition(source, source.index(sig)) for sig in signatures)


@pytest.fixture(scope="module")
def page(tmp_path_factory):
    d = tmp_path_factory.mktemp("p23-08")
    (d / "dom.js").write_text(_DOM)
    return d


def run(page, script: str) -> dict:
    return _run(page, "import { installDom } from './dom.js';\nconst document = installDom();\n", script)


# ── DOCS-M-1 · a chat made for a draft goes when the draft does ─────────────

_HELPERS = cut(DOCJS, "const _HELPER_CHATS_KEY", "const _HELPER_CHATS_MAX",
               "function _readHelperChats(", "function _writeHelperChats(",
               "function noteHelperChat(", "async function _leaveDeletedChat(",
               "async function _releaseHelperChat(")

_EDITOR = """
const API_BASE = '';
let activeDocId = null, _lastSessionId = '';
const docs = new Map();
const calls = [], nav = [];
let answerSession = () => ({ ok: true, status: 200, json: async () => ({ status: 'deleted' }) });
globalThis.fetch = async (url, init = {}) => {
  calls.push([(init.method || 'GET'), url]);
  if (String(url).startsWith('/api/session/')) return answerSession(url, init);
  return { ok: true, status: 200, json: async () => ({}) };
};
const sessionModule = {
  current: 'helper-1',
  list: [{ id: 'chat-a' }, { id: 'helper-1' }],
  getCurrentSessionId() { return this.current; },
  getSessions() { return this.list; },
  async selectSession(id) { nav.push(['select', id]); this.current = id; },
  async loadSessions() { nav.push(['load']); },
};
const newChat = document.createElement('button');
newChat.id = 'sidebar-new-chat-btn';
newChat.click = () => { nav.push(['new-chat']); sessionModule.current = null; };
document.body.appendChild(newChat);
const uiModule = { showToast() {} };
async function saveDocument() { calls.push(['PUT', '/api/document/' + activeDocId]); return true; }
function _syncDocIndicator() {}
function saveCurrentToMap() {}
function switchToDoc(id) { activeDocId = id; }
function closePanel() { nav.push(['closePanel']); }
function renderTabs() {}
const settle = () => new Promise((r) => setTimeout(r, 20));
const helpers = () => JSON.parse(localStorage.getItem(_HELPER_CHATS_KEY) || '{}');
""" + _HELPERS + "\n" + cut(DOCJS, "function _detachDocFromSession(", "function _closeWithoutDeleting(")

_REPLY_DRAFT = ("{ id: 'd1', sessionId: 'helper-1', language: 'email', title: 'Q3 Board Pack',"
                " content: 'To: priya@example.test\\nSubject: Re: Q3\\n---\\n\\n> the pack' }")


def test_reply_then_close_leaves_no_chat_and_goes_back(page):
    """The row's `Verify:` — Reply, then close without sending: no new chat,
    and the person is back in the chat they replied from."""
    out = run(page, _EDITOR + f"""
        noteHelperChat('helper-1', {{ returnTo: 'chat-a' }});
        docs.set('d1', {_REPLY_DRAFT}); activeDocId = 'd1';
        _closeWithoutDeleting(true);     // the draft's Close
        await settle();
        console.log(JSON.stringify({{ calls, nav, helpers: helpers(), current: sessionModule.current }}));
    """)
    assert ["DELETE", "/api/document/d1"] in out["calls"]
    assert ["DELETE", "/api/session/helper-1?only_if_empty=true"] in out["calls"]
    assert out["nav"] == [["closePanel"], ["select", "chat-a"], ["load"]]
    assert out["helpers"] == {} and out["current"] == "chat-a"


def test_closing_the_draft_s_tab_keeps_the_draft_and_lets_the_chat_go(page):
    out = run(page, _EDITOR + f"""
        noteHelperChat('helper-1', {{ returnTo: 'chat-a' }});
        docs.set('d1', {_REPLY_DRAFT}); activeDocId = 'd1';
        _detachDocFromSession('d1', {{ toast: true }});   // the tab's ×
        await settle();
        console.log(JSON.stringify({{ calls, nav }}));
    """)
    assert ["PUT", "/api/document/d1"] in out["calls"], "a typed draft is saved, not deleted"
    assert ["DELETE", "/api/document/d1"] not in out["calls"]
    assert ["DELETE", "/api/session/helper-1?only_if_empty=true"] in out["calls"]
    assert ["select", "chat-a"] in out["nav"]


def test_from_the_welcome_screen_it_goes_back_to_a_new_chat(page):
    out = run(page, _EDITOR + f"""
        noteHelperChat('helper-1');
        docs.set('d1', {_REPLY_DRAFT}); activeDocId = 'd1';
        _closeWithoutDeleting(true);
        await settle();
        console.log(JSON.stringify({{ nav }}));
    """)
    assert out["nav"] == [["closePanel"], ["new-chat"], ["load"]]


def test_a_chat_somebody_wrote_in_stays_and_is_forgotten_as_a_helper(page):
    out = run(page, _EDITOR + f"""
        answerSession = () => ({{ ok: false, status: 409, json: async () => ({{}}) }});
        noteHelperChat('helper-1', {{ returnTo: 'chat-a' }});
        docs.set('d1', {_REPLY_DRAFT}); activeDocId = 'd1';
        _closeWithoutDeleting(true);
        await settle();
        console.log(JSON.stringify({{ nav, helpers: helpers(), current: sessionModule.current }}));
    """)
    assert out["nav"] == [["closePanel"]] and out["current"] == "helper-1"
    assert out["helpers"] == {}


def test_the_person_s_own_chat_is_never_asked_about(page):
    out = run(page, _EDITOR + """
        docs.set('d1', { id: 'd1', sessionId: 'chat-a', language: 'markdown', content: 'notes' });
        activeDocId = 'd1'; sessionModule.current = 'chat-a';
        _detachDocFromSession('d1');
        await settle();
        console.log(JSON.stringify({ calls, nav }));
    """)
    assert not [c for c in out["calls"] if c[1].startswith("/api/session/")]
    assert out["nav"] == []


def test_a_chat_with_another_tab_open_is_kept_for_now(page):
    out = run(page, _EDITOR + f"""
        noteHelperChat('helper-1', {{ returnTo: 'chat-a' }});
        docs.set('d1', {_REPLY_DRAFT});
        docs.set('d2', {{ id: 'd2', sessionId: 'helper-1', language: 'markdown', content: 'more' }});
        activeDocId = 'd1';
        _closeWithoutDeleting(true);
        await settle();
        console.log(JSON.stringify({{ calls, helpers: helpers() }}));
    """)
    assert not [c for c in out["calls"] if c[1].startswith("/api/session/")]
    assert out["helpers"] == {"helper-1": "chat-a"}


def test_offline_it_is_still_a_helper_for_the_next_close(page):
    out = run(page, _EDITOR + f"""
        answerSession = () => {{ throw new TypeError('Failed to fetch'); }};
        noteHelperChat('helper-1', {{ returnTo: 'chat-a' }});
        docs.set('d1', {_REPLY_DRAFT}); activeDocId = 'd1';
        _closeWithoutDeleting(true);
        await settle();
        console.log(JSON.stringify({{ nav, helpers: helpers() }}));
    """)
    assert out["helpers"] == {"helper-1": "chat-a"}
    assert ["select", "chat-a"] not in out["nav"]


def test_a_helper_the_person_already_left_is_deleted_without_moving_them(page):
    out = run(page, _EDITOR + f"""
        noteHelperChat('helper-1', {{ returnTo: 'chat-a' }});
        sessionModule.current = 'chat-b';
        docs.set('d1', {_REPLY_DRAFT}); activeDocId = 'd1';
        _detachDocFromSession('d1');      // the minimised draft's chip ×
        await settle();
        console.log(JSON.stringify({{ calls, nav, current: sessionModule.current }}));
    """)
    assert ["DELETE", "/api/session/helper-1?only_if_empty=true"] in out["calls"]
    assert out["nav"] == [["load"]] and out["current"] == "chat-b"


_INBOX = """
const API_BASE = '';
const calls = [], noted = [];
globalThis.fetch = async (url, init = {}) => {
  calls.push([(init.method || 'GET'), url]);
  if (url === '/api/default-chat') return { ok: true, json: async () => ({ endpoint_url: 'http://m', model: 'm' }) };
  return { ok: true, status: 200, json: async () => ({ id: 'helper-9' }) };
};
const sessionModule = {
  current: 'chat-a', list: [],
  getCurrentSessionId() { return this.current; },
  getSessions() { return this.list; },
  async loadSessions() {}, async selectSession(id) { this.current = id; },
};
const _docModule = { noteHelperChat: (sid, opts) => noted.push([sid, opts]) };
""" + cut(INBOXJS, "async function _createEmailChat(")


def test_reply_marks_the_chat_it_makes_as_the_draft_s(page):
    out = run(page, _INBOX + """
        sessionModule.list = [{ id: 'chat-a', message_count: 4 }];
        const sid = await _createEmailChat({ subject: 'Q3 Board Pack' }, { forceNew: true });
        console.log(JSON.stringify({ sid, noted }));
    """)
    assert out["sid"] == "helper-9"
    assert out["noted"] == [["helper-9", {"returnTo": "chat-a"}]]


def test_compose_in_a_blank_chat_the_person_had_marks_nothing(page):
    """Compose reuses a blank chat that was already open; that chat is the
    person's, so closing the draft never deletes it."""
    out = run(page, _INBOX + """
        sessionModule.list = [{ id: 'chat-a', message_count: 0 }];
        const sid = await _createEmailChat({ subject: 'New Email' });
        console.log(JSON.stringify({ sid, noted, calls }));
    """)
    assert out["sid"] == "chat-a" and out["noted"] == []
    assert ["POST", "/api/session"] not in out["calls"]


# ── DOCS-M-2 · Create stores nothing until there is something to store ──────

_CREATE = """
globalThis.requestAnimationFrame = (fn) => setTimeout(() => fn(0), 0);
// The editor's 2 s autosave timer would hold node open; run it at once.
const realTimeout = globalThis.setTimeout;
globalThis.setTimeout = (fn, ms) => realTimeout(fn, Math.min(ms || 0, 5));
const API_BASE = '';
let activeDocId = null, _lastSessionId = '', _blankDoc = null, isOpen = false;
let _autoSaveDebounce = null, _autoCreating = false, _isEditingTabTitle = false, _diffModeActive = false;
const docs = new Map();
const calls = [], nav = [];
let made = 0;
globalThis.fetch = async (url, init = {}) => {
  const body = init.body && typeof init.body === 'string' ? JSON.parse(init.body) : null;
  calls.push([(init.method || 'GET'), url, body]);
  if (url === '/api/session') return { ok: true, status: 200, json: async () => ({ id: 'notes-chat' }) };
  if (url === '/api/document' && init.method === 'POST')
    return { ok: true, status: 200, json: async () => ({ id: 'doc-' + (++made), session_id: body.session_id, title: '', current_content: body.content }) };
  if (String(url).startsWith('/api/session/')) return { ok: true, status: 200, json: async () => ({}) };
  return { ok: true, status: 200, json: async () => ({}) };
};
const sessionModule = {
  current: 'chat-a', pending: false, list: [{ id: 'chat-a' }],
  getCurrentSessionId() { return this.current; },
  getSessions() { return this.list; },
  hasPendingChat() { return this.pending; },
  getCurrentModel() { return null; },
  setCurrentSessionId(id) { this.current = id; },
  async selectSession(id) { nav.push(['select', id]); this.current = id; },
  async loadSessions() { nav.push(['load']); },
};
const newChat = document.createElement('button');
newChat.id = 'sidebar-new-chat-btn';
newChat.click = () => { nav.push(['new-chat']); sessionModule.current = null; };
document.body.appendChild(newChat);
const uiModule = { showToast() {}, showError() {} };
for (const id of ['doc-tab-bar', 'doc-language-select', 'doc-version-badge']) {
  const n = document.createElement('div'); n.id = id; document.body.appendChild(n);
}
const ta = document.createElement('textarea'); ta.id = 'doc-editor-textarea'; ta.value = '';
let focused = 0; ta.focus = () => { focused++; };
document.body.appendChild(ta);
const saves = [];
async function saveDocument() { saves.push(activeDocId); return true; }
function saveCurrentToMap() {}
function _closeNotesForDocumentOpen() {}
function _ensureDocPaneMounted() { isOpen = true; }
function exitDiffMode() {} function clearSelection() {} function _hideEmailFields() {}
function _setMarkdownPreviewActive() {} function exitHtmlPreview() {} function _syncHeaderActions() {}
function _hideLoadingOverlay() {} function syncHighlighting() {} function _syncDocIndicator() {}
function attemptAutoDetect() {} function autoTitleFromContent() {}
function langIcon() { return ''; } function _esc(s) { return String(s); }
function updateArrowVisibility() {} function _wireSwipeDismiss() {} function initTabDragReorder() {}
function switchToDoc(id) { _blankDoc = null; activeDocId = id; }
function closePanel() { nav.push(['closePanel']); isOpen = false; _blankDoc = null; }
const settle = () => new Promise((r) => setTimeout(r, 20));
const posted = (url) => calls.filter((c) => c[0] === 'POST' && c[1] === url);
const tabs = () => document.getElementById('doc-tab-bar').innerHTML;
const helpers = () => JSON.parse(localStorage.getItem(_HELPER_CHATS_KEY) || '{}');
""" + _HELPERS + "\n" + cut(
    DOCJS, "async function newDocument(", "async function _openBlankDocument(",
    "function _dropUntouchedEmptyDoc(", "function showEmptyState(", "function renderTabs(",
    "async function _autoCreateFromInput(", "async function _autoCreateSession(",
    "function addDocToTabs(", "function _detachDocFromSession(", "async function closeTab(")


def test_three_creates_closed_untyped_store_nothing(page):
    out = run(page, _CREATE + """
        await newDocument(); await newDocument(); await newDocument();
        const ghost = tabs();
        closePanel();
        await settle();
        console.log(JSON.stringify({ calls, ghost, focused, active: activeDocId }));
    """)
    assert out["calls"] == [], out["calls"]
    assert "doc-tab-ghost" in out["ghost"] and "Untitled" in out["ghost"]
    assert out["focused"] == 3 and out["active"] is None


def test_the_first_keystroke_stores_it_in_the_chat_that_was_open(page):
    out = run(page, _CREATE + """
        await newDocument();
        ta.value = 'Packing list';
        await _autoCreateFromInput(ta.value);      // what the editor's input listener calls
        console.log(JSON.stringify({ docs: posted('/api/document').map((c) => c[2]),
          sessions: posted('/api/session').length, active: activeDocId, tabs: tabs() }));
    """)
    assert out["docs"] == [{"session_id": "chat-a", "title": "", "content": "Packing list"}]
    assert out["sessions"] == 0 and out["active"] == "doc-1"
    assert "doc-tab-ghost" not in out["tabs"]


def test_create_beside_open_documents_draws_the_blank_tab_and_saves_the_last_one(page):
    out = run(page, _CREATE + """
        docs.set('d0', { id: 'd0', sessionId: 'chat-a', title: 'Budget', content: 'numbers', language: 'markdown' });
        activeDocId = 'd0'; isOpen = true; _autoSaveDebounce = 1;
        await newDocument();
        console.log(JSON.stringify({ tabs: tabs(), saves, calls, active: activeDocId, kept: docs.has('d0') }));
    """)
    assert "doc-tab-ghost" in out["tabs"] and 'data-doc-id="d0"' in out["tabs"]
    assert out["saves"] == ["d0"], "the document being left is saved first"
    assert out["calls"] == [] and out["active"] is None and out["kept"]


def test_from_the_welcome_screen_the_chat_comes_with_the_text_and_goes_with_the_tab(page):
    """DOCS-M-1's second half: Library › Create on the welcome screen. No chat
    until the first keystroke; then one, marked as the document's, and closing
    the tab lets it go (the document stays in the Library)."""
    out = run(page, _CREATE + """
        sessionModule.current = null;
        _lastSessionId = 'chat-left-behind';   // the chat before New chat; not the one on screen
        await newDocument();
        const before = calls.length;
        ta.value = 'Packing list';
        await _autoCreateFromInput(ta.value);
        const stored = { sessions: posted('/api/session').length,
                         doc: posted('/api/document').map((c) => c[2].session_id), helpers: helpers() };
        await closeTab(activeDocId);
        await settle();
        console.log(JSON.stringify({ before, stored, calls: calls.map((c) => [c[0], c[1]]), nav }));
    """)
    assert out["before"] == 0
    assert out["stored"] == {"sessions": 1, "doc": ["notes-chat"], "helpers": {"notes-chat": ""}}
    assert ["DELETE", "/api/session/notes-chat?only_if_empty=true"] in out["calls"]
    assert ["DELETE", "/api/document/doc-1"] not in out["calls"], "typed text is kept"
    assert ["new-chat"] in out["nav"]


# ── DOCS-M-6 · a PDF this server cannot draw opens as text, asking nothing ──

_PDF = """
const API_BASE = '';
const fetched = [];
let status = 503;
globalThis.fetch = async (url) => { fetched.push(url);
  return { ok: false, status, statusText: 'x', text: async () => JSON.stringify({ detail: 'PDF viewer requires PyMuPDF.' }) }; };
const pane = document.createElement('div'); pane.id = 'doc-pdf-view'; document.body.appendChild(pane);
const docs = new Map();
let activeDocId = null;
function _wirePdfPaneProximity() {}
const note = () => (pane._walk([]).find((n) => n.className === 'doc-pdf-text-note') || {}).textContent;
""" + cut(DOCJS, "async function _pdfResponseErrorMessage(", "function _showPdfTextInstead(",
          "async function _renderPdfPane(", "function _escHtml(", "function addDocToTabs(")

_NOTE = "Shown as text. Page view needs an optional component (PyMuPDF) that an admin can install."
_PDF_ANSWER = ("{ id: 'p1', title: 'Lease', language: 'markdown', can_render_pages: false,"
               " current_content: '<!-- pdf_source upload_id=\"x\" -->\\n# Lease\\n[Page 1 text]: rent' }")


def test_the_document_answer_s_flag_means_no_render_pages_request(page):
    out = run(page, _PDF + f"""
        addDocToTabs({_PDF_ANSWER}, 'chat-a');
        activeDocId = 'p1';
        await _renderPdfPane();
        console.log(JSON.stringify({{ fetched, note: note(), flag: docs.get('p1').canRenderPages }}));
    """)
    assert out["fetched"] == []
    assert out["note"] == _NOTE and out["flag"] is False


def test_an_answer_without_the_flag_asks_once_then_remembers(page):
    out = run(page, _PDF + """
        addDocToTabs({ id: 'p1', title: 'Lease', current_content: '# Lease' }, 'chat-a');
        activeDocId = 'p1';
        await _renderPdfPane(); await _renderPdfPane();
        console.log(JSON.stringify({ fetched, note: note() }));
    """)
    assert out["fetched"] == ["/api/document/p1/render-pages"]
    assert out["note"] == _NOTE


# ── DOCS-M-11 · a CSV card asks highlight.js for nothing it lacks ───────────

_HLJS = """
const hl = { asked: [], logged: [] };
window.hljs = {
  getLanguage: (l) => (l === 'csv' ? undefined : { name: l }),
  highlight: (text, { language }) => {
    hl.asked.push(language);
    if (language === 'csv') { hl.logged.push(`Could not find the language '${language}'`); throw new Error('unknown'); }
    return { value: text };
  },
};
"""


def test_a_csv_card_is_shown_plain_without_asking(sandbox):  # noqa: F811
    body = _doclib_cut("function libraryCreateCard(", "function libraryCreateCard(doc)")
    out = _doclib_js(sandbox, _CARD.replace("__CARD__", body) + _HLJS + """
        libraryCreateCard({ id: 'c', title: 'sales', language: 'csv', preview: 'a,b\\n1,2', version_count: 1 });
        libraryCreateCard({ id: 'p', title: 'tool', language: 'python', preview: 'x = 1', version_count: 1 });
        console.log(JSON.stringify(hl));
    """)
    assert out == {"asked": ["python"], "logged": []}


def test_an_opened_csv_card_is_shown_plain_without_asking(sandbox):  # noqa: F811
    body = _doclib_cut("async function libraryExpandCard(", "async function libraryExpandCard(card, doc)")
    harness = _CARD.replace("function libraryExpandCard() {}", "").replace("__CARD__", "")
    out = _doclib_js(sandbox, harness + _HLJS + """
        function _collapseExpandedCard() {}
        let answer = { current_content: 'a,b\\n1,2', language: 'csv' };
        globalThis.fetch = async () => ({ ok: true, json: async () => answer });
        const open = async (language) => {
          answer = { current_content: 'a,b', language };
          const card = document.createElement('div'); card.dataset.spaceToggle = '1';
          const preview = document.createElement('div'); preview.className = 'doclib-card-preview';
          card.appendChild(preview);
          await libraryExpandCard(card, { id: 'c', language });
          return preview.querySelector('code').textContent;
        };
    """ + body + """
        const shown = await open('csv');
        await open('python');
        console.log(JSON.stringify({ ...hl, shown }));
    """)
    assert out["asked"] == ["python"] and out["logged"] == []
    assert out["shown"] == "a,b"


# ── DOCS-M-12 · a `.txt` is text ────────────────────────────────────────────

@pytest.mark.parametrize("name,body,language", [
    ("Shopping list.txt", b"Eggs, milk.\n", "text"),
    ("server.log", b"12:00 started\n", "text"),
    ("Meeting notes.md", b"# Meeting notes\n", "markdown"),
    ("README", b"# Read me\n\nSome words.\n", "markdown"),     # no extension: still sniffed
], ids=["txt", "log", "md", "no-extension"])
def test_the_library_import_stores_a_text_file_as_text(live, name, body, language):  # noqa: F811
    path = _file(live, name, body)
    out = _node(live.tmp, live.base, f"""
        const made = await importFileAsDocuments(fileOf({json.dumps(path)}, {json.dumps(name)}, 'text/plain'));
        console.log(JSON.stringify(made.map((d) => d.language)));
    """)
    (stored,) = _docs(live)
    assert stored["language"] == language and out == [language]


# ── DOCS-M-13 · sizes under 1 KB read in bytes ──────────────────────────────

def test_the_mail_reader_s_chips_say_bytes_under_a_kilobyte(page):
    out = run(page, """
        const state = { _libFolder: 'INBOX' };
        const _esc = (s) => String(s);
        const _isLikelySignatureImage = () => false;
        const chevronIcon = () => '';
    """ + cut(MAILJS, "function _buildAttsHtmlFor(") + """
        const html = _buildAttsHtmlFor('7', { folder: 'INBOX', attachments: [
          { index: 0, filename: 'lease.pdf', size: 170 }, { index: 1, filename: 'n.txt', size: 40 },
          { index: 2, filename: 'deck.pdf', size: 52224 }, { index: 3, filename: 'film.mp4', size: 5 * 1048576 },
          { index: 4, filename: 'unknown.bin' }] });
        console.log(JSON.stringify([...html.matchAll(/class="att-size">([^<]*)</g)].map((m) => m[1])));
    """)
    assert out == ["170 B", "40 B", "51 KB", "5.0 MB", ""]


def test_the_editor_s_chips_say_it_the_same_way(page):
    out = run(page, cut(DOCJS, "function _attachmentSizeText(") + """
        console.log(JSON.stringify([170, 40, 1023, 1024, 52224, 5 * 1048576, 0, undefined, 'x']
          .map(_attachmentSizeText)));
    """)
    assert out == ["170 B", "40 B", "1023 B", "1 KB", "51 KB", "5.0 MB", "", "", ""]
