# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P21-01` — the Library's folders, driven under node.

`static/js/documentFolders.js` draws the path and the folder chips, the *Move
to…* list and the removal question; `static/js/documentLibrary.js` wires them
into the Documents tab. Both are driven here against the DOM shim of
`tests/test_tool_effect_surfaces_js.py` — the real module imported, the real
functions cut out of `documentLibrary.js` with `js_function` and called
(`Law 20`) — never grepped:

  * the bar shows where you are and the folders one level down, with counts, an
    Unfiled view at the top, and a way to make a folder from wherever you are;
  * a document dropped on a chip or a crumb is filed there; a folder dropped on
    a folder moves into it; a folder dropped on itself does nothing;
  * *Move to…* offers every folder once, cannot offer where the thing already
    is, and cannot offer a folder itself or anything inside it;
  * removing a folder asks with the counts on the buttons, the safe answer is
    the one with the focus, the destructive one is drawn as destructive, and
    nothing past the dry run is sent if the person cancels;
  * every folder name is text, never markup;
  * the Documents tab asks the server for one folder or for Unfiled, lets the
    newer of two answers win, says an empty folder is an empty folder, files a
    dragged or chosen document, and puts *Move to…* and a drag on every card.
"""

import json
import shutil
from pathlib import Path

import pytest

from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402
from test_destructive_preview_js import (  # noqa: E402
    _PREAMBLE as _UI_PREAMBLE, _SHIM as _UI_SHIM, _STUBS as _UI_STUBS, UI_JS,
)
from tests.helpers.esc_stub import ui_default_stub
from tests.helpers.js_source import js_function

ROOT = Path(__file__).resolve().parents[1]
FOLDERS_JS = ROOT / "static" / "js" / "documentFolders.js"
DOCLIB_JS = ROOT / "static" / "js" / "documentLibrary.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


_SHIM = r"""
import { installDom, Node } from './dom.js';
export const document = installDom();
export { Node };
globalThis.requestAnimationFrame = (fn) => setTimeout(() => fn(0), 0);
globalThis.innerWidth = 1280;
globalThis.innerHeight = 800;
globalThis.CSS = { escape: (s) => String(s) };

/** A drag's payload, the way a browser hands it over. */
export function dataTransfer(payload) {
  const data = Object.assign({}, payload || {});
  return {
    data,
    get types() { return Object.keys(data); },
    setData(t, v) { data[t] = String(v); },
    getData(t) { return data[t] || ''; },
    effectAllowed: '', dropEffect: '',
  };
}

export function fire(node, type, extra) {
  let prevented = false;
  const ev = Object.assign({ type, target: node, currentTarget: node,
    preventDefault() { prevented = true; }, stopPropagation() {} }, extra || {});
  node.dispatchEvent(ev);
  return { prevented, ev };
}

export function texts(nodes) { return nodes.map((n) => n.textContent); }

export function tick(n = 6) {
  let p = Promise.resolve();
  for (let i = 0; i < n; i++) p = p.then(() => new Promise((r) => setTimeout(r, 0)));
  return p;
}
"""

_STUBS = {
    "ui.js": ui_default_stub(
        "showToast: (m) => toasts.push(m), showError: (m) => errors.push(m),"
        " styledConfirm: async () => false, styledPrompt: async () => null,"
        " renderEmptyState: (host, spec) => { emptyStates.push(spec); },",
        exports="export const toasts = [];\nexport const errors = [];\nexport const emptyStates = [];",
    ),
    "toolWindowZOrder.js": "export function topPortalZ(){ return 10; }\n",
}

_PREAMBLE = (
    "import { document, Node, dataTransfer, fire, texts, tick } from './shim.js';\n"
    "import uiModule, { toasts, errors, emptyStates } from './ui.js';\n"
    "import * as F from './documentFolders.js';\n"
)

_FOLDERS = json.dumps([
    {"path": "Clients", "name": "Clients", "parent": None, "depth": 0, "count": 1, "total": 3},
    {"path": "Clients/Acme", "name": "Acme", "parent": "Clients", "depth": 1, "count": 2, "total": 2},
    {"path": "Clients/Acme/Legal", "name": "Legal", "parent": "Clients/Acme", "depth": 2, "count": 0, "total": 0},
    {"path": "Personal", "name": "Personal", "parent": None, "depth": 0, "count": 0, "total": 0},
])


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    return _make_sandbox(tmp_path_factory.mktemp("docfolders"), FOLDERS_JS, _SHIM, _STUBS)


def _js(sandbox, script):
    return _run(sandbox, _PREAMBLE + f"const FOLDERS = {_FOLDERS};\n", script)


_BAR = """
    const calls = [];
    const on = {
      open: (v) => calls.push(['open', v]),
      newFolder: (p) => calls.push(['new', p]),
      folderMenu: (a, p) => calls.push(['menu', p]),
      dropDocuments: (ids, to) => calls.push(['docs', ids, to]),
      dropFolder: (p, to) => calls.push(['folder', p, to]),
    };
    const host = document.body.appendChild(new Node('div'));
    function bar(view) {
      F.renderFolderBar(host, { folders: FOLDERS, unfiled: 4, all: 7, view }, on);
      const crumbs = host.querySelectorAll('.doclib-folder-crumb');
      const chips = host.querySelectorAll('.doclib-folder-chip');
      return {
        crumbs: texts(crumbs),
        current: crumbs.filter((c) => c.getAttribute('aria-current') === 'page').map((c) => c.textContent),
        chips: texts(chips),
        targets: chips.map((c) => c.dataset.folderTarget),
        active: chips.filter((c) => c.classList.contains('active')).map((c) => c.textContent),
        add: (host.querySelector('.doclib-folder-new') || {}).textContent || null,
        menu: !!host.querySelector('.doclib-folder-actions'),
      };
    }
"""


# ── the bar ─────────────────────────────────────────────────────────────────

def test_at_the_top_the_bar_offers_unfiled_and_the_top_level_folders(sandbox):
    out = _js(sandbox, _BAR + """
        console.log(JSON.stringify(bar(F.VIEW_ALL)));
    """)
    assert out["crumbs"] == ["All documents"] and out["current"] == ["All documents"]
    assert out["chips"] == ["Unfiled(4)", "Clients(3)", "Personal(0)"], (
        "a top-level chip counts what is in its folders too, and an empty folder is listed")
    assert out["targets"] == ["", "Clients", "Personal"]
    assert out["add"] == "+ New folder" and out["menu"] is False


def test_inside_a_folder_the_bar_shows_the_path_and_the_folders_in_it(sandbox):
    out = _js(sandbox, _BAR + """
        const view = F.folderView('Clients/Acme');
        const got = bar(view);
        host.querySelector('.doclib-folder-new').dispatchEvent({ type: 'click' });
        host.querySelector('.doclib-folder-actions').dispatchEvent({ type: 'click', stopPropagation(){} });
        host.querySelectorAll('.doclib-folder-crumb')[1].dispatchEvent({ type: 'click' });
        console.log(JSON.stringify({ ...got, calls }));
    """)
    assert out["crumbs"] == ["All documents", "Clients", "Acme"]
    assert out["current"] == ["Acme"]
    assert out["chips"] == ["Legal(0)"], "only the folders directly inside are chips here"
    assert out["add"] == "+ New folder here" and out["menu"] is True
    assert out["calls"] == [["new", "Clients/Acme"], ["menu", "Clients/Acme"],
                            ["open", {"kind": "folder", "path": "Clients"}]]


def test_the_unfiled_view_is_named_and_its_chip_toggles_back(sandbox):
    out = _js(sandbox, _BAR + """
        const got = bar(F.VIEW_UNFILED);
        host.querySelectorAll('.doclib-folder-chip')[0].dispatchEvent({ type: 'click' });
        console.log(JSON.stringify({ ...got, calls }));
    """)
    assert out["crumbs"] == ["All documents", "Unfiled"] and out["current"] == ["Unfiled"]
    assert out["active"] == ["Unfiled(4)"]
    assert out["calls"] == [["open", {"kind": "all"}]]


def test_a_folder_name_is_text_and_never_markup(sandbox):
    out = _js(sandbox, """
        const host = document.body.appendChild(new Node('div'));
        const evil = '<img src=x onerror=alert(1)>';
        F.renderFolderBar(host, { folders: [{ path: evil, name: evil, parent: null, depth: 0, count: 1, total: 1 }],
          unfiled: 0, view: F.folderView(evil) }, {});
        const name = host.querySelectorAll('.doclib-folder-crumb')[1];
        console.log(JSON.stringify({ text: name.textContent, html: name.innerHTML }));
    """)
    assert out["text"] == "<img src=x onerror=alert(1)>"
    assert out["html"] == ""


# ── drag and drop ───────────────────────────────────────────────────────────

def test_documents_dropped_on_a_chip_or_a_crumb_are_filed_there(sandbox):
    out = _js(sandbox, _BAR + """
        bar(F.folderView('Clients'));
        const acme = host.querySelectorAll('.doclib-folder-chip')[0];
        const all = host.querySelectorAll('.doclib-folder-crumb')[0];
        const src = { dataTransfer: dataTransfer() };
        F.startDocumentDrag(src, ['d1', 'd2']);
        const over = fire(acme, 'dragover', { dataTransfer: src.dataTransfer });
        const lit = acme.classList.contains('doclib-folder-drop');
        fire(acme, 'drop', { dataTransfer: src.dataTransfer });
        fire(all, 'drop', { dataTransfer: src.dataTransfer });
        const stranger = fire(acme, 'dragover', { dataTransfer: dataTransfer({ 'text/plain': 'hi' }) });
        console.log(JSON.stringify({ calls, accepted: over.prevented, lit,
          unlit: !acme.classList.contains('doclib-folder-drop'),
          stranger: stranger.prevented, types: src.dataTransfer.types }));
    """)
    assert out["accepted"] is True and out["lit"] is True and out["unlit"] is True
    assert out["stranger"] is False, "a drag that carries no document must not be accepted"
    assert out["calls"] == [["docs", ["d1", "d2"], "Clients/Acme"], ["docs", ["d1", "d2"], None]]
    assert "application/x-pantheon-documents" in out["types"]


def test_a_folder_dropped_on_a_folder_moves_into_it_but_not_onto_itself(sandbox):
    out = _js(sandbox, _BAR + """
        bar(F.VIEW_ALL);
        const [unfiled, clients, personal] = host.querySelectorAll('.doclib-folder-chip');
        const src = { dataTransfer: dataTransfer() };
        fire(personal, 'dragstart', src);
        fire(clients, 'drop', { dataTransfer: src.dataTransfer });
        fire(personal, 'drop', { dataTransfer: src.dataTransfer });
        console.log(JSON.stringify({ calls, draggable: personal.draggable }));
    """)
    assert out["draggable"] is True
    assert out["calls"] == [["folder", "Personal", "Clients"]]


# ── Move to… ────────────────────────────────────────────────────────────────

def test_move_to_offers_every_folder_once_but_not_where_it_already_is(sandbox):
    out = _js(sandbox, """
        const anchor = document.body.appendChild(new Node('button'));
        const picked = [];
        const menu = F.showFolderPicker(anchor, { folders: FOLDERS, current: 'Clients/Acme',
          moving: 'documents', onPick: (p) => picked.push(p), onNew: () => picked.push('NEW') });
        const rows = menu.querySelectorAll('.dropdown-item-compact');
        const read = rows.map((r) => ({ text: r.textContent, disabled: !!r.disabled, pad: r.style.paddingLeft || '' }));
        rows[3].dispatchEvent({ type: 'click', stopPropagation(){} });
        console.log(JSON.stringify({ read, picked, open: !!menu.parentNode }));
    """)
    assert [r["text"] for r in out["read"]] == [
        "Unfiled", "Clients", "Acme (here)", "Legal", "Personal", "New folder…"]
    assert [r["disabled"] for r in out["read"]] == [False, False, True, False, False, False]
    pads = [int(r["pad"][:-2]) for r in out["read"][1:4]]
    assert pads[0] < pads[1] < pads[2], "a folder is not indented under its parent"
    assert out["picked"] == ["Clients/Acme/Legal"]
    assert out["open"] is False, "choosing a folder must close the list"


def test_a_folder_is_never_offered_itself_or_anything_inside_it(sandbox):
    out = _js(sandbox, """
        const anchor = document.body.appendChild(new Node('button'));
        const menu = F.showFolderPicker(anchor, { folders: FOLDERS, current: null,
          moving: 'folder', exclude: 'Clients', onPick: () => {} });
        console.log(JSON.stringify(texts(menu.querySelectorAll('.dropdown-item-compact'))));
    """)
    assert out == ["Top level (here)", "Personal"]


def test_the_folders_own_menu_offers_new_rename_move_remove(sandbox):
    out = _js(sandbox, """
        const anchor = document.body.appendChild(new Node('button'));
        const got = [];
        const menu = F.showFolderMenu(anchor, 'Clients/Acme', {
          newFolder: (p) => got.push(['new', p]), rename: (p) => got.push(['rename', p]),
          move: (p) => got.push(['move', p]), remove: (p) => got.push(['remove', p]) });
        const rows = menu.querySelectorAll('.dropdown-item-compact');
        const labels = texts(rows);
        const danger = rows.map((r) => r.classList.contains('dropdown-item-danger'));
        rows[3].dispatchEvent({ type: 'click', stopPropagation(){} });
        console.log(JSON.stringify({ labels, danger, got }));
    """)
    assert out["labels"] == ["New folder inside…", "Rename…", "Move to…", "Remove folder…"]
    assert out["danger"] == [False, False, False, True]
    assert out["got"] == [["remove", "Clients/Acme"]]


# ── removing a folder ───────────────────────────────────────────────────────

def test_removal_says_how_many_and_the_safe_answer_has_the_focus(sandbox):
    out = _js(sandbox, """
        console.log(JSON.stringify({
          full: F.describeRemoval({ path: 'Clients/Acme', parent: 'Clients', documents: 3, archived: 1, folders: 1 }),
          top: F.describeRemoval({ path: 'Clients', parent: null, documents: 0, folders: 2 }),
          empty: F.describeRemoval({ path: 'Old', parent: null, documents: 0, folders: 0 }),
        }));
    """)
    full = out["full"]
    assert full["message"] == "“Acme” holds 3 documents and 1 folder. What should happen to them?"
    assert full["options"]["confirmText"] == "Move up"
    assert "\u201cClients\u201d" in full["options"]["details"]["footnote"], "where is up?"
    assert full["options"].get("danger") in (None, False), "the focused answer must be the safe one"
    assert full["options"]["alternateText"] == "Delete all 3"
    assert full["options"]["alternateDanger"] is True
    assert full["choices"] == {"confirm": "move_up", "alternate": "delete"}
    assert full["options"]["details"]["items"] == [
        {"label": "3 documents", "note": "1 archived"},
        {"label": "1 folder", "note": "with what is in them"}]
    assert out["top"]["options"]["alternateText"] == "Remove both"
    one = _js(sandbox, """console.log(JSON.stringify(F.describeRemoval(
        { path: 'A', parent: null, documents: 1, folders: 3 }).options.alternateText));""")
    assert one == "Delete it"
    assert "top-level" in out["top"]["options"]["details"]["footnote"]
    assert out["empty"]["message"] == "Remove the empty folder “Old”?"
    assert out["empty"]["choices"] == {"confirm": None}


@pytest.mark.parametrize("answer, sent, outcome", [
    ("true", ["move_up"], "moved_up"),
    ("'alternate'", ["delete"], "deleted"),
    ("false", [], "cancelled"),
])
def test_the_removal_sends_what_was_chosen_and_nothing_if_cancelled(sandbox, answer, sent, outcome):
    out = _js(sandbox, f"""
        const posted = [];
        const api = {{ remove: async (path, contents, dry) => {{
          posted.push({{ path, contents, dry }});
          return dry ? {{ path, parent: null, documents: 2, folders: 0 }}
                     : {{ path, parent: null, changes: [] }};
        }} }};
        let asked = null;
        const r = await F.removeFolderFlow(api, 'Clients', async (msg, opts) => {{ asked = opts; return {answer}; }});
        console.log(JSON.stringify({{ posted, outcome: r.outcome, asked: asked.alternateText }}));
    """)
    assert out["posted"][0] == {"path": "Clients", "contents": None, "dry": True}, "no dry run first"
    assert [p["contents"] for p in out["posted"][1:]] == sent
    assert all(p["dry"] is False for p in out["posted"][1:])
    assert out["outcome"] == outcome
    assert out["asked"] == "Delete both"


def test_the_sentences_after_a_change_come_from_what_the_server_did(sandbox):
    out = _js(sandbox, """
        console.log(JSON.stringify([
          F.describeFiled({ to: 'Clients', changes: [
            { change: 'created', kind: 'folder' }, { change: 'moved', kind: 'document' },
            { change: 'moved', kind: 'document' }] }),
          F.describeFiled({ to: null, changes: [] }),
          F.describeRemovalOutcome('deleted', { path: 'A/Old', changes: [
            { change: 'deleted', kind: 'document' }, { change: 'removed', kind: 'folder' }] }),
          F.describeRemovalOutcome('moved_up', { path: 'A/Old', parent: 'A', changes: [
            { change: 'moved', kind: 'document' }, { change: 'moved', kind: 'folder' }] }),
        ]));
    """)
    assert out == ["Moved 2 documents to Clients", "Already in Unfiled",
                   "Removed “Old” and deleted 1 document",
                   "Removed “Old” — 1 document and 1 folder moved to A"]


def test_the_view_follows_a_renamed_or_removed_folder(sandbox):
    out = _js(sandbox, """
        const p = new URLSearchParams();
        F.applyViewParams(F.folderView('Clients/Acme'), p);
        const u = new URLSearchParams();
        F.applyViewParams(F.VIEW_UNFILED, u);
        const a = new URLSearchParams();
        F.applyViewParams(F.VIEW_ALL, a);
        console.log(JSON.stringify({
          folder: p.toString(), unfiled: u.toString(), all: a.toString(),
          renamed: F.viewAfterRelocate(F.folderView('Clients/Acme/Legal'), 'Clients', 'Customers'),
          removed: F.viewAfterRelocate(F.folderView('Clients/Acme'), 'Clients/Acme', null),
          removedTop: F.viewAfterRelocate(F.folderView('Clients'), 'Clients', null),
          elsewhere: F.viewAfterRelocate(F.folderView('Personal'), 'Clients', 'X'),
        }));
    """)
    assert out["folder"] == "folder=Clients%2FAcme"
    assert out["unfiled"] == "unfiled=true" and out["all"] == ""
    assert out["renamed"] == {"kind": "folder", "path": "Customers/Acme/Legal"}
    assert out["removed"] == {"kind": "folder", "path": "Clients"}
    assert out["removedTop"] == {"kind": "all"}
    assert out["elsewhere"] == {"kind": "folder", "path": "Personal"}


# ── the shared dialog: a destructive third answer looks like one ────────────

@pytest.fixture(scope="module")
def ui_sandbox(tmp_path_factory):
    return _make_sandbox(tmp_path_factory.mktemp("docfolders-ui"), UI_JS, _UI_SHIM, _UI_STUBS)


def test_the_alternate_answer_can_be_drawn_as_the_destructive_one(ui_sandbox):
    out = _run(ui_sandbox, _UI_PREAMBLE, """
        const read = () => String(document.querySelector('#styled-confirm-alt').className || '');
        const pressCancel = () => document.querySelector('#styled-confirm-cancel')
          .dispatchEvent({ type: 'click', stopPropagation(){}, preventDefault(){} });
        const p1 = styledConfirm('Remove?', { alternateText: 'Delete 3 documents', alternateDanger: true });
        const danger = read(); pressCancel(); await p1;
        const p2 = styledConfirm('Remove?', { alternateText: 'Keep both' });
        const plain = read(); pressCancel(); await p2;
        console.log(JSON.stringify({ danger, plain }));
    """)
    assert "confirm-btn-danger" in out["danger"]
    assert "confirm-btn-secondary" in out["plain"] and "danger" not in out["plain"]


# ── documentLibrary.js: the Documents tab's own wiring ──────────────────────

def _cut(signature, name_and_params):
    return name_and_params + " " + js_function(DOCLIB_JS.read_text(encoding="utf-8"), signature)


_FETCH = """
    let API_BASE = '';
    let _libraryOffset = 0, _librarySort = 'recent', _librarySearch = '', _libraryActiveLanguage = null;
    let _libraryArchivedView = false, _libraryFolderView = F.VIEW_ALL;
    let _libraryDocs = [], _docsVisibleLimit = 20, _libraryTotal = 0, _libraryLanguages = {}, _librarySessionCount = 0;
    let _libraryFetchSeq = 0;
    const applyViewParams = F.applyViewParams;
    let refreshed = 0;
    function libraryRefreshFolders() { refreshed++; }
    function libraryRenderStats() {} function libraryRenderLangChips() {}
    function libraryRenderGrid() {} function libraryRenderLoadMore() {}
    async function _readError(res) { return String(res.status); }
    const urls = [];
    const gates = [];
    globalThis.fetch = (url) => { urls.push(url); return new Promise((resolve) => gates.push(resolve)); };
    const answer = (i, docs) => gates[i]({ ok: true, status: 200,
      json: async () => ({ documents: docs, total: docs.length, languages: {}, session_count: 0 }) });
    __FETCH__
"""


def _fetch_case(sandbox, tail):
    body = _cut("async function libraryFetch(", "async function libraryFetch(append)")
    return _js(sandbox, _FETCH.replace("__FETCH__", body) + tail)


def test_the_documents_tab_asks_for_one_folder_or_for_unfiled(sandbox):
    out = _fetch_case(sandbox, """
        _libraryFolderView = F.folderView('Clients/Acme');
        const a = libraryFetch(false); answer(0, []); await a;
        _libraryFolderView = F.VIEW_UNFILED;
        const b = libraryFetch(false); answer(1, []); await b;
        _libraryFolderView = F.VIEW_ALL;
        const c = libraryFetch(true); answer(2, []); await c;
        console.log(JSON.stringify({ urls, refreshed }));
    """)
    assert "folder=Clients%2FAcme" in out["urls"][0]
    assert "unfiled=true" in out["urls"][1] and "folder=" not in out["urls"][1]
    assert "folder=" not in out["urls"][2] and "unfiled=" not in out["urls"][2]
    assert out["refreshed"] == 2, "the folder counts refresh with a fresh list, not with a page"


def test_the_newer_of_two_answers_wins(sandbox):
    """Open a folder while the last list is still loading, and the slower
    answer must not draw the folder you left under the path you opened."""
    out = _fetch_case(sandbox, """
        const first = libraryFetch(false);
        const second = libraryFetch(false);
        answer(1, [{ id: 'new' }]);
        await second;
        answer(0, [{ id: 'stale' }]);
        await first;
        console.log(JSON.stringify(_libraryDocs.map((d) => d.id)));
    """)
    assert out == ["new"]


_GRID = """
    let _libraryDocs = [], _librarySearch = '', _libraryActiveLanguage = null;
    let _libraryFolderView = F.VIEW_ALL, _docsVisibleLimit = 20, _libraryTotal = 0;
    const VIEW_ALL = F.VIEW_ALL;
    function dismissOrRemove() {}
    function _libraryClearFilters() {}
    const opened = [];
    function libraryOpenFolder(v) { opened.push(v); }
    function _maybeCascadeGrid() {}
    function libraryCreateCard() { return new Node('div'); }
    async function libraryFetch() {}
    const grid = document.body.appendChild(new Node('div'));
    grid.setAttribute('id', 'doclib-grid');
    __GRID__
"""


def test_an_empty_folder_is_not_reported_as_an_empty_library(sandbox):
    body = _cut("function libraryRenderGrid(", "function libraryRenderGrid()")
    out = _js(sandbox, _GRID.replace("__GRID__", body) + """
        _libraryFolderView = F.folderView('Clients');
        libraryRenderGrid();
        _libraryFolderView = F.VIEW_UNFILED;
        libraryRenderGrid();
        _libraryFolderView = F.VIEW_ALL;
        libraryRenderGrid();
        emptyStates[0].action.onClick();
        console.log(JSON.stringify({ titles: emptyStates.map((s) => s.title), opened }));
    """)
    assert out["titles"] == ["Nothing in this folder yet", "Nothing is unfiled", "No documents yet"]
    assert out["opened"] == [{"kind": "all"}]


_FILE = """
    const posted = [];
    let failWith = null;
    function _folderApi() {
      return { file: async (ids, to) => {
        posted.push({ ids, to });
        if (failWith) throw new Error(failWith);
        return { to, changes: ids.map((id) => ({ change: 'moved', kind: 'document', id })) };
      } };
    }
    const describeFiled = F.describeFiled;
    let _librarySelectMode = true, exited = 0, fetched = 0;
    function libraryExitSelectMode() { exited++; _librarySelectMode = false; }
    function libraryFetch() { fetched++; }
    __FILE__
"""


def test_filing_from_the_tab_posts_once_and_says_what_moved(sandbox):
    body = _cut("async function libraryFileDocuments(", "async function libraryFileDocuments(ids, to)")
    out = _js(sandbox, _FILE.replace("__FILE__", body) + """
        await libraryFileDocuments(['a', 'b', 'a'], 'Clients');
        const afterOk = fetched;
        failWith = "Document 'x' not found";
        await libraryFileDocuments(['x'], null);
        console.log(JSON.stringify({ posted, toasts, errors, exited, afterOk, fetched }));
    """)
    assert out["posted"] == [{"ids": ["a", "b"], "to": "Clients"}, {"ids": ["x"], "to": None}]
    assert out["toasts"] == ["Moved 2 documents to Clients"]
    assert out["errors"] == ["Could not move the document — Document 'x' not found"]
    assert out["afterOk"] == 1, "a move that worked must redraw the list"
    assert (out["exited"], out["fetched"]) == (1, 1), "a failed move must not redraw as if it worked"


_CARD = """
    let API_BASE = '';
    let _librarySelectMode = false;
    const _librarySelectedIds = new Set();
    let _libraryDocs = [], _librarySearch = '', _libraryArchivedView = false;
    let _libraryFolderView = F.VIEW_ALL;
    const _LIB_DD_ICONS = { folder: '<svg></svg>' };
    const startDocumentDrag = F.startDocumentDrag;
    const picks = [];
    function libraryPickFolderFor(anchor, ids, current) { picks.push({ ids, current, anchor: anchor.className }); }
    function _hlSearch(t) { return uiModule.esc(t); }
    function langIcon() { return ''; }
    function chevronIcon() { return ''; }
    function libraryRelativeTime() { return '1d ago'; }
    function _showLibDropdown(anchor, items) { mobileItems.push(...items.map((i) => i.label)); }
    const mobileItems = [];
    function topPortalZ() { return 1; }
    function registerMenuDismiss() { return () => {}; }
    function _attachLongPressMenu() {}
    function libraryToggleSelectItem() {} function libraryEnterSelectMode() {}
    function libraryUpdateBulkCount() {} function libraryRenderGrid() {}
    function libraryOpenInSession() {} function libraryOpenDocument() {} function libraryImportDocument() {}
    function libraryDeleteSingle() {} function libraryRemoveDocumentFromState() {} function libraryExpandCard() {}
    __CARD__
"""


def test_every_card_drags_and_offers_move_to(sandbox):
    body = _cut("function libraryCreateCard(", "function libraryCreateCard(doc)")
    out = _js(sandbox, _CARD.replace("__CARD__", body) + """
        const doc = { id: 'd1', title: 'Board pack', folder: 'Clients/Acme', language: 'markdown', version_count: 1 };
        const card = libraryCreateCard(doc);
        const meta = card.querySelector('.memory-item-meta').innerHTML;

        const src = { dataTransfer: dataTransfer() };
        fire(card, 'dragstart', src);
        const one = JSON.parse(src.dataTransfer.getData('application/x-pantheon-documents'));

        _librarySelectMode = true; _librarySelectedIds.add('d1'); _librarySelectedIds.add('d2');
        const src2 = { dataTransfer: dataTransfer() };
        fire(card, 'dragstart', src2);
        const many = JSON.parse(src2.dataTransfer.getData('application/x-pantheon-documents'));

        card.classList.add('doclib-card-expanded');
        const blocked = fire(card, 'dragstart', { dataTransfer: dataTransfer() }).prevented;

        const items = card.querySelectorAll('.dropdown-item-compact');
        const move = items.find((b) => b.textContent === 'Move to\\u2026');
        move.dispatchEvent({ type: 'click', stopPropagation(){} });

        _libraryFolderView = F.folderView('Clients/Acme');
        _librarySelectMode = false;
        const inside = libraryCreateCard(doc).querySelector('.memory-item-meta').innerHTML;

        globalThis.innerWidth = 400;
        card.querySelector('.memory-item-btn').dispatchEvent({ type: 'click', stopPropagation(){} });
        globalThis.innerWidth = 1280;

        console.log(JSON.stringify({ draggable: card.draggable, one, many: many.sort(), blocked,
          labels: items.map((b) => b.textContent), picks, meta, inside, mobileItems }));
    """)
    assert out["draggable"] is True
    assert out["one"] == ["d1"] and out["many"] == ["d1", "d2"]
    assert out["blocked"] is True, "an open card must not start a drag over its own preview text"
    assert "Move to…" in out["labels"]
    assert out["picks"] == [{"ids": ["d1"], "current": "Clients/Acme", "anchor": "memory-item-btn"}]
    assert "doclib-card-folder" in out["meta"] and "Clients/Acme" in out["meta"]
    assert "doclib-card-folder" not in out["inside"], "inside the folder, the card need not repeat it"
    assert "Move to…" in out["mobileItems"]
