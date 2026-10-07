# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1194` — hiding the Library takes documents, not the chat archive.

`D-2026-10-07-02` §3, the owner: *"Hiding library should guide archives."*
— "Hiding the Library takes documents away, not the chat archive: the archive
keeps a door of its own, and a hidden Library reached anyway says where
archived chats are."

Measured on `fcd559e`: the archive lives in the Library window's tabs and the
sidebar's *manage* door (under Chats) is `openLibrary('chats')`, so each of the
Library's three switches — *Document Editor* for everyone, *Document editor*
for one person, *Library* in this browser — took archived chats with it:
*manage*, `/open archive`, the URL and Research's Library link all answered
"Library is switched off …" and nothing said where the archive had gone.

Driven, not read (`Law 20`):

  * `static/js/ui_visibility.js` (the one table) is imported under node and its
    doors are asked: a kept tab opens, the Library's own doors refuse with the
    guide line and an *Open archive* button that opens the archive;
  * `sessions.js`' `openLibrary` and `slashCommands.js`' `_cmdOpen`, the
    palette's `_toolEntries` and `app.js`' window openers are cut out of their
    files with `tests/helpers/js_source` and run beside the real table;
  * `static/js/documentLibrary.js` is imported whole in the DOM shim's sandbox
    (its markup parsed into nodes) and `openLibrary` is called: switched off,
    the window has no Documents tab or panel and asks the server for no
    document;
  * `admin.js`' `_hidesLine` is cut out and run: the Settings line says what a
    switch takes and that the archive stays.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from tests.helpers.esc_stub import esc_source, ui_default_stub
from tests.helpers.js_source import js_binding, js_function

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"
UI_VIS = JS / "ui_visibility.js"
SESSIONS_JS = JS / "sessions.js"
SLASH_JS = JS / "slashCommands.js"
PALETTE_JS = JS / "search-chat.js"
ADMIN_JS = JS / "admin.js"
DOCLIB_JS = JS / "documentLibrary.js"
APP_JS = ROOT / "static" / "app.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

GUIDE = "Archived chats are under Chats → manage."
OFF_EVERYONE = ("Library is switched off for everyone. An admin can turn it back on in "
                "Settings → Agent Tools. " + GUIDE)

# The three columns of the one table, each switching the Library off.
COLUMNS = {
    "everyone": "{ features: { document_editor: false } }",
    "person": "{ privileges: { can_use_documents: false }, auth: true }",
    "browser": "{ ui: { 'tool-library': false } }",
}

# A small page: the Library's doors as nodes, a toast that keeps what it was
# handed (the sentence and the button), and the chat module's `openLibrary`
# recording the tab it was asked for.
_DOM = r"""
const nodes = {};
export function node(id, parent = null) {
  const n = { id, style: { display: '' }, parentNode: parent, clicked: 0 };
  n.click = () => click(n);
  nodes[id] = n;
  return n;
}
export const document = { getElementById: (id) => nodes[id] || null };
export const listeners = [];
export const toasts = [];
export const opened = [];
globalThis.window = {
  addEventListener: (type, fn, capture) => listeners.push({ type, fn, capture }),
  uiModule: { showToast: (text, opts) => toasts.push({ text: String(text), opts: opts === undefined ? null : opts }) },
  sessionModule: { openLibrary: (tab) => opened.push(tab === undefined ? null : tab) },
};
export function click(target) {
  const ev = { target, stopped: false, prevented: false,
    stopImmediatePropagation() { this.stopped = true; },
    preventDefault() { this.prevented = true; } };
  for (const l of listeners) if (l.type === 'click' && l.capture) l.fn(ev);
  if (!ev.stopped) target.clicked += 1;
  return ev;
}
export function shown(id) { return nodes[id].style.display !== 'none'; }
/** A toast as JSON can carry it: the sentence, and the button's label. */
export function said() {
  return toasts.map((t) => ({ text: t.text,
    button: t.opts && typeof t.opts === 'object' ? t.opts.action || null : null,
    plain: typeof t.opts === 'number' }));
}
export { nodes };
"""

_DOORS = ["tool-library-btn", "rail-archive", "overflow-doc-btn", "tool-gallery-btn", "rail-gallery"]


def _node(tmp_path: Path, script: str) -> dict:
    (tmp_path / "dom.mjs").write_text(_DOM)
    entry = tmp_path / "case.mjs"
    entry.write_text(
        "import { node, document, listeners, toasts, opened, click, shown, said, nodes } from './dom.mjs';\n"
        f"const V = await import({json.dumps(UI_VIS.as_uri())});\n"
        f"for (const id of {json.dumps(_DOORS)}) node(id);\n"
        + textwrap.dedent(script)
    )
    proc = subprocess.run(["node", str(entry)], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


# ── the table: what the switches take, what they leave ──────────────────────

@pytest.mark.parametrize("column", sorted(COLUMNS))
def test_each_switch_takes_the_documents_and_leaves_the_archive_tabs_open(tmp_path, column):
    """The window's Chats, Research and Archive tabs open with the Library
    switched off in any column; its Documents — asked for by name or as the
    Library's default — do not. With nothing switched off, every tab opens."""
    out = _node(tmp_path, f"""
        const ask = () => ['chats', 'archive', 'research', 'documents', undefined]
          .map((tab) => V.toolDoor('library', {{ tab }}));
        const before = ask();
        V.applyToolVisibility({COLUMNS[column]}, document);
        console.log(JSON.stringify({{
          before, after: ask(), row: shown('tool-library-btn'), rail: shown('rail-archive'),
          keeps: ['chats', 'archive', 'research', 'documents', null].map((t) => V.toolKeeps('library', t)),
          gallery: V.toolKeeps('gallery', 'archive'),
        }}));
    """)
    assert out["before"] == [True, True, True, True, True]
    assert out["after"] == [True, True, True, False, False], (
        "the chat archive went with the Library's documents")
    assert out["row"] is False and out["rail"] is False, "the Library's own doors stay hidden"
    assert out["keeps"] == [True, True, True, False, False]
    assert out["gallery"] is False, "only a tool whose table row keeps something keeps it"


def test_a_refused_library_door_says_where_the_archive_is_and_opens_it(tmp_path):
    """`toolRefusal`'s sentence plus the guide, in one toast whose button is
    the archive's door. Every way the Library's door is reached says it: the
    door check, the slash dispatcher's lookup, and a programmatic press of the
    hidden sidebar row (the `open_library` shortcut, the rail)."""
    out = _node(tmp_path, """
        V.installToolDoorGuard(window);
        V.applyToolVisibility({ features: { document_editor: false, gallery: false } }, document);
        const door = V.toolDoor('library');
        const slash = V.toolDoor({ slash: 'library' });
        const press = click(nodes['tool-library-btn']);
        const gallery = V.toolDoor('gallery');
        const firstButton = toasts[0].opts;
        firstButton.onAction();
        console.log(JSON.stringify({
          door, slash, pressed: [press.stopped, nodes['tool-library-btn'].clicked],
          gallery, said: said(), opened, refusal: V.toolRefusal('library'),
          guide: V.toolGuide('library') && V.toolGuide('library').label,
        }));
    """)
    assert out["door"] is False and out["slash"] is False
    assert out["pressed"] == [True, 0]
    assert out["refusal"] == OFF_EVERYONE
    assert out["said"][:3] == [{"text": OFF_EVERYONE, "button": "Open archive", "plain": False}] * 3
    assert out["opened"] == ["archive"], "the guide's button did not open the archive"
    assert out["guide"] == "Archived chats"
    # A tool that keeps nothing says its sentence alone, as before.
    assert out["gallery"] is False
    assert out["said"][3] == {"text": "Gallery is switched off for everyone. An admin can turn it "
                                      "back on in Settings → Agent Tools.",
                              "button": None, "plain": True}


def test_the_guide_follows_the_column_that_took_the_library(tmp_path):
    out = _node(tmp_path, """
        V.applyToolVisibility({ privileges: { can_use_documents: false }, auth: true }, document);
        const person = V.toolRefusal('library');
        V.applyToolVisibility({ privileges: {}, ui: { 'tool-library': false } }, document);
        console.log(JSON.stringify({ person, browser: V.toolRefusal('library') }));
    """)
    assert out["person"] == ("Library is switched off for your account. An admin can turn it back "
                             "on in Settings → Users. " + GUIDE)
    assert out["browser"] == ("Library is hidden in this browser. Turn it back on in Settings → "
                              "Appearance. " + GUIDE)


def test_a_link_to_the_archive_opens_and_a_link_to_the_library_says_where_it_is(tmp_path):
    """`P23-01` gave every window a URL and one tab below it. `/library/archive`
    (and Chats, Research) is the archive's; `/library` and `/library/documents`
    are the Library's, refused with the guide."""
    out = _node(tmp_path, """
        const went = [];
        const link = (path) => V.guardRouteOpener(path, () => went.push(path));
        V.applyToolVisibility({ features: { document_editor: false } }, document);
        V.applyToolVisibility({ privileges: {}, isAdmin: true, auth: true }, document);
        for (const p of ['/library/archive', '/library/chats', '/library/research',
                         '/library', '/library/documents', '/library/archive?x=1#chat-1']) await link(p)();
        console.log(JSON.stringify({ went, said: said() }));
    """)
    assert out["went"] == ["/library/archive", "/library/chats", "/library/research",
                           "/library/archive?x=1#chat-1"]
    assert out["said"] == [{"text": OFF_EVERYONE, "button": "Open archive", "plain": False}] * 2


# ── the Settings lines ──────────────────────────────────────────────────────

def _admin_fn(name: str) -> str:
    src = ADMIN_JS.read_text(encoding="utf-8")
    sig = f"function {name}"
    at = src.index(sig + "(") + len(sig) + 1
    return f"{sig}({src[at:src.index(')', at)]}) " + js_function(src, sig)


def test_each_settings_line_says_documents_go_and_the_archive_stays(tmp_path):
    """The visibility table says what each switch hides — documents and the
    editor, never the archive — and Settings reads it: *Switched on for
    everyone* (feature), *Can use* (privilege) through `admin.js`' own
    `_hidesLine`, *Show in this browser* (ui) through the same sentence."""
    out = _node(tmp_path, f"""
        const {{ hidesLine }} = V;
        {_admin_fn("_hidesLine")}
        console.log(JSON.stringify({{
          feature: _hidesLine({{ feature: 'document_editor' }}),
          privilege: _hidesLine({{ privilege: 'can_use_documents' }}),
          browser: hidesLine({{ ui: 'tool-library' }}),
          gallery: _hidesLine({{ feature: 'gallery' }}),
          filter: _hidesLine({{ feature: 'sensitive_filter' }}),
          hidden: V.toolsHiddenBy({{ feature: 'document_editor' }}).map((t) => [t.key, t.hides, t.keeps]),
        }}));
    """)
    both = "Off hides documents and the Document editor button. " + GUIDE
    assert out["feature"] == both
    assert out["privilege"] == both
    assert out["browser"] == "Off hides documents. " + GUIDE
    assert out["gallery"] == "Off hides Gallery."
    assert out["filter"] == ""
    assert out["hidden"] == [["library", "documents", GUIDE], ["doc", "Document editor", ""]]


# ── the doors in other modules ──────────────────────────────────────────────

def test_the_chat_modules_library_door_opens_the_archive_tabs_with_the_library_off(tmp_path):
    """`sessions.js` `openLibrary(tab)` — *manage* (`'chats'`), the guide's
    button (`'archive'`), the agent's `open_panel sessions` — delegates to the
    Library window with its tab; the Library's own (no tab) is refused."""
    body = js_function(SESSIONS_JS.read_text(encoding="utf-8"), "export function openLibrary")
    out = _node(tmp_path, f"""
        const asked = [];
        window.documentModule = {{ openLibrary: (o) => asked.push(o) }};
        globalThis.document = {{ getElementById: () => null }};
        function openLibrary(defaultTab) {body}
        V.applyToolVisibility({{ features: {{ document_editor: false }} }}, document);
        openLibrary('chats'); openLibrary('archive'); openLibrary(); openLibrary('documents');
        const off = asked.splice(0);
        V.applyToolVisibility({{ features: {{ document_editor: true }} }}, document);
        openLibrary(); openLibrary('archive');
        console.log(JSON.stringify({{ off, on: asked, said: said() }}));
    """)
    assert out["off"] == [{"tab": "chats"}, {"tab": "archive"}], (
        "*manage* and the guide's button were refused with the Library switched off")
    assert out["said"] == [{"text": OFF_EVERYONE, "button": "Open archive", "plain": False}] * 2
    assert out["on"] == [{"tab": "documents"}, {"tab": "archive"}], "the Library shown: as before"


def test_open_archive_opens_the_archive_whatever_the_library_says(tmp_path):
    """`/open archive` was mapped to the Library (it pressed the Library's row,
    which opened on Documents): with the Library off it was refused."""
    body = js_function(SLASH_JS.read_text(encoding="utf-8"), "async function _cmdOpen")
    out = _node(tmp_path, esc_source("_shippedEsc") + f"""
        window.pantheonToolDoor = V.toolDoor;
        const replies = [];
        const slashReply = (t) => replies.push(t);
        const cookbookModule = null, settingsModule = null;
        const sessionModule = window.sessionModule;
        globalThis.document = document;
        async function _cmdOpen(args, ctx) {body}
        const ctx = {{ esc: _shippedEsc }};
        V.applyToolVisibility({{ privileges: {{ can_use_documents: false }}, auth: true }}, document);
        await _cmdOpen(['archive'], ctx);
        await _cmdOpen(['library'], ctx);
        console.log(JSON.stringify({{ opened, replies, said: said(), pressed: nodes['tool-library-btn'].clicked }}));
    """)
    assert out["opened"] == ["archive"]
    assert out["pressed"] == 0
    assert out["replies"] == []
    assert [s["text"] for s in out["said"]] == [
        "Library is switched off for your account. An admin can turn it back on in "
        "Settings → Users. " + GUIDE]


def test_the_palette_offers_the_archive_where_the_library_is_switched_off(tmp_path):
    """Ctrl+K does not offer a hidden tool (`P23-03`); with the Library off,
    "library" or "archive" finds *Archived chats*, which opens the archive."""
    src = PALETTE_JS.read_text(encoding="utf-8")
    body = js_function(src, "function _toolEntries")
    # The palette's own matcher, as shipped.
    matcher = "\n".join([
        "function _norm(s) " + js_function(src, "function _norm"),
        "function _words(s) " + js_function(src, "function _words"),
        "function _wordsMatch(terms, text) " + js_function(src, "function _wordsMatch"),
    ])
    out = _node(tmp_path, matcher + f"""
        const {{ toolKeyFor, toolShown, toolGuide }} = V;
        const listWindows = () => [
          {{ id: 'doclib-modal', label: 'Library', door: true, doors: [], state: 'closed' }},
          {{ id: 'calendar-modal', label: 'Calendar', door: true, doors: [], state: 'closed' }},
        ];
        const _DOOR_FUNCTIONS = {{}}, _DOOR_SHOWN = {{}};
        const isMinimized = () => false, showWindow = () => {{}};
        const _STATE_WORDS = {{}}, _toolKey = () => '', _compareIsOn = () => '';
        function _toolEntries(terms) {body}
        const rows = (q) => _toolEntries(q).map((e) => [e.label, e.detail]);
        const shownRows = rows(['library']);
        V.applyToolVisibility({{ features: {{ document_editor: false }} }}, document);
        const off = {{ library: rows(['library']), archive: rows(['archive']), cal: rows(['cal']) }};
        _toolEntries(['archive'])[0].run();
        console.log(JSON.stringify({{ shownRows, off, opened }}));
    """)
    assert out["shownRows"] == [["Library", ""]]
    assert out["off"]["library"] == [["Archived chats", "Chats → manage"]]
    assert out["off"]["archive"] == [["Archived chats", "Chats → manage"]]
    assert out["off"]["cal"] == [["Calendar", ""]]
    assert out["opened"] == ["archive"]


# ── the window: `documentLibrary.js` imported whole ─────────────────────────

_WIN_SHIM = r"""
import { installDom, installHtmlParsing, Node } from './dom.js';
export const document = installDom();
installHtmlParsing();
export { Node };
globalThis.requestAnimationFrame = (fn) => setTimeout(() => fn(0), 0);
globalThis.innerWidth = 1280;
globalThis.innerHeight = 800;
globalThis.CSS = { escape: (s) => String(s) };
// The server, as far as the window asks it: what it asked, in order.
export const asked = [];
const ok = (body) => ({ ok: true, status: 200, json: async () => body, text: async () => JSON.stringify(body) });
globalThis.fetch = async (url) => {
  const u = String(url);
  asked.push(u.split('?')[0]);
  if (u.startsWith('/api/sessions/archived')) return ok({ sessions: [
    { id: 'old-1', name: 'Q3 plan, archived', model: 'scripted', updated_at: '2026-09-01T00:00:00Z' }] });
  if (u.startsWith('/api/sessions')) return ok([{ id: 'live-1', name: 'Today', model: 'scripted' }]);
  if (u.startsWith('/api/research/library')) return ok({ research: [] });
  if (u.startsWith('/api/documents/library')) return ok({ documents: [
    { id: 'd1', title: 'Archived doc', language: 'markdown' }], total: 1, languages: {}, session_count: 0 });
  if (u.startsWith('/api/document-folders')) return ok({ folders: [], unfiled: 0, all: 0 });
  return ok({});
};
export function tick(n = 12) {
  let p = Promise.resolve();
  for (let i = 0; i < n; i++) p = p.then(() => new Promise((r) => setTimeout(r, 0)));
  return p;
}
"""

_WIN_STUBS = {
    "ui.js": ui_default_stub(
        "showToast: (m, o) => toasts.push({ text: String(m), button: o && typeof o === 'object' ? o.action : null }),"
        " showError: (m) => toasts.push({ text: String(m), button: null }),"
        " renderEmptyState: (host, spec) => { host.textContent = spec.title || ''; },"
        " isTouchInsideModal: () => false, styledConfirm: async () => false,",
        exports="export const toasts = [];"),
    "sessions.js": "export default { selectSession() {}, getCurrentSessionId: () => null };\n",
    "spinner.js": ("export default { createLoadingRow: () => document.createElement('div'),"
                   " createWhirlpool: () => ({ element: document.createElement('div'), stop() {} }),"
                   " create: () => ({ createElement: () => document.createElement('span'), start() {}, destroy() {} }) };\n"),
    "markdown.js": "export default { render: (s) => String(s) };\n",
    "windowDrag.js": "export function makeWindowDraggable() {}\n",
    "toolWindowZOrder.js": "export function topPortalZ() { return 10; }\n",
}


@pytest.fixture(scope="module")
def window_sandbox(tmp_path_factory):
    d = _make_sandbox(tmp_path_factory.mktemp("b1194-window"), DOCLIB_JS, _WIN_SHIM, _WIN_STUBS)
    shutil.copy(UI_VIS, d / "ui_visibility.js")
    return d


_WIN_PREAMBLE = """
import { document, asked, tick } from './shim.js';
import uiModule, { toasts } from './ui.js';
window.uiModule = uiModule;   // as `app.js` hands it to the page
const V = await import('./ui_visibility.js');
const L = await import('./documentLibrary.js');
L.initLibrary({ apiBase: '', esc: (s) => String(s), getDocs: () => new Map(), isOpen: () => false });
const win = () => document.getElementById('doclib-modal');
const tabs = () => win() ? win().querySelectorAll('[data-doclib-tab]').map((b) => b.dataset.doclibTab) : null;
const panels = () => win() ? win().querySelectorAll('[data-doclib-panel]').map((p) => p.dataset.doclibPanel) : null;
const active = () => win() ? (win().querySelector('.lib-tab.active') || {}).dataset?.doclibTab || null : null;
const press = (tab) => win().querySelector('[data-doclib-tab="' + tab + '"]').dispatchEvent({ type: 'click' });
"""


@pytest.mark.parametrize("column", sorted(COLUMNS))
def test_the_library_switched_off_opens_as_the_chat_archive_without_its_documents(window_sandbox, column):
    """*manage* opens the window on Chats; it has Chats, Research and Archive,
    no Documents tab or panel, and asks the server for no document — not the
    list, not its folders, not the archived ones on the Archive tab."""
    out = _run(window_sandbox, _WIN_PREAMBLE, f"""
        V.applyToolVisibility({COLUMNS[column]}, document);
        L.openLibrary({{ tab: 'chats' }});
        await tick();
        const onChats = {{ tabs: tabs(), panels: panels(), active: active() }};
        press('archive');
        await tick();
        const archive = win().querySelector('#doclib-arc-grid').readable;
        console.log(JSON.stringify({{ onChats, active: active(), archive, asked, toasts }}));
    """)
    assert out["onChats"] == {"tabs": ["chats", "research", "archive"],
                              "panels": ["chats", "archive", "research"], "active": "chats"}
    assert out["active"] == "archive"
    assert "Q3 plan, archived" in out["archive"], "the archived chat is not on the Archive tab"
    assert not [u for u in out["asked"] if "/api/document" in u], out["asked"]
    assert "/api/sessions/archived" in out["asked"] and "/api/research/library" in out["asked"]
    assert out["toasts"] == []


def test_an_archive_that_did_not_load_says_so_with_one_source_not_asked(window_sandbox):
    """`P9-08`'s rule — every source failing is "The archive did not load.",
    not "Part of …" — holds when the archived documents are not asked for."""
    out = _run(window_sandbox, _WIN_PREAMBLE, """
        const real = globalThis.fetch;
        globalThis.fetch = async (url) => String(url).includes('/archived') || String(url).includes('/research/')
          ? { ok: false, status: 500, json: async () => ({ detail: 'down' }), text: async () => 'down' }
          : real(url);
        V.applyToolVisibility({ features: { document_editor: false } }, document);
        L.openLibrary({ tab: 'archive' });
        await tick();
        console.log(JSON.stringify({ said: win().querySelector('#doclib-arc-grid').textContent }));
    """)
    assert out["said"] == "The archive did not load."


def test_the_library_door_itself_is_refused_with_the_guide(window_sandbox):
    out = _run(window_sandbox, _WIN_PREAMBLE, """
        V.applyToolVisibility({ features: { document_editor: false } }, document);
        L.openLibrary();
        L.openLibrary({ tab: 'documents' });
        await tick();
        console.log(JSON.stringify({ open: !!win(), asked, toasts }));
    """)
    assert out["open"] is False
    assert out["asked"] == []
    assert out["toasts"] == [{"text": OFF_EVERYONE, "button": "Open archive"}] * 2


def test_the_library_shown_is_the_library_as_before(window_sandbox):
    out = _run(window_sandbox, _WIN_PREAMBLE, """
        L.openLibrary();
        await tick();
        const first = { tabs: tabs(), panels: panels(), active: active() };
        press('archive');
        await tick();
        console.log(JSON.stringify({ first, asked, toasts }));
    """)
    assert out["first"] == {"tabs": ["chats", "documents", "research", "archive"],
                            "panels": ["chats", "archive", "research", "documents"],
                            "active": "documents"}
    assert "/api/documents/library" in out["asked"]
    assert out["asked"].count("/api/documents/library") == 2, "the archived documents went missing"
    assert out["toasts"] == []


def test_the_agents_open_sessions_opens_the_chats_tab(tmp_path):
    """`ui_control open_panel sessions` — the agent asked to show the chats —
    called `openLibrary()` with no tab: the Library's Documents, refused with
    the Library switched off."""
    src = (JS / "chatStream.js").read_text(encoding="utf-8")
    body = js_function(src, "export function handleUIControl")
    (tmp_path / "sessions.js").write_text(
        "export function openLibrary(tab) { globalThis.__asked.push(tab === undefined ? null : tab); }\n")
    entry = tmp_path / "case.mjs"
    entry.write_text(textwrap.dedent(f"""
        globalThis.__asked = [];
        const uiModule = {{ esc: (s) => String(s) }};
        function handleUIControl(uiData) {body}
        handleUIControl({{ ui_event: 'open_panel', panel: 'sessions' }});
        await new Promise((r) => setTimeout(r, 50));
        console.log(JSON.stringify({{ asked: globalThis.__asked }}));
    """))
    proc = subprocess.run(["node", str(entry)], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout.strip().splitlines()[-1]) == {"asked": ["chats"]}


def test_a_reload_of_the_archive_reopens_it_on_its_tab(tmp_path):
    """`P23-01`'s back stack reopens a window through `app.js`' `_openWindow`
    with the tab its URL names; the Library's opener dropped it, so a reload
    of `/library/archive` asked for the Library (refused when it is off)."""
    binding = js_binding(APP_JS.read_text(encoding="utf-8"), "_openWindow")
    out = _node(tmp_path, f"""
        const sessionModule = window.sessionModule;
        {binding};
        _openWindow['doclib-modal']('archive');
        _openWindow['doclib-modal'](null);
        console.log(JSON.stringify({{ opened }}));
    """)
    assert out["opened"] == ["archive", None]
