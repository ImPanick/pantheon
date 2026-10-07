# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P23-02` — the Brain keeps its place: one listener, one read, real tabs, a door.

Driven under node against the real `static/js/memory.js`, inside the real
Brain markup — the slice of `static/index.html` from `#memory-modal` to the
end of the Skills window, parsed by the shim's HTML layer — with the real
`escMenuStack.js` (the menu wrapper is the thing under test for `PERF-M-3`).

Two neighbours are fakes, and say so:

  * **`modalManager.js` is a fake of C-NAV** (`/work/notes/FIX-WAVES.md`), the
    window manager `P23-01` (fx-back) builds in parallel: it records
    `register(id, { getTab, setTab, … })` and `showWindow(id, { from, tab })`,
    and `closeOpened()` plays its other half — closing a window opened *from*
    another re-raises the opener through the `setTab` it registered. When
    fx-back's half is merged, `tests/test_the_brain_keeps_its_place_in_a_browser.py`
    is the walk on the real one.
  * **`skills.js` is a recorder**: the door's whole job is the call it makes.

What each case measured on `32df791` before the fix is in its docstring.
"""

import json
import re
import shutil
from pathlib import Path

import pytest

from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402
from tests.helpers.esc_stub import ui_default_stub

ROOT = Path(__file__).resolve().parents[1]
MEMORY_JS = ROOT / "static" / "js" / "memory.js"
INDEX = ROOT / "static" / "index.html"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _brain_markup() -> str:
    html = INDEX.read_text(encoding="utf-8")
    start = html.index('<div id="memory-modal"')
    end = html.index('<div id="workbench-modal"')
    return html[start:end]


_STUBS = {
    "ui.js": ui_default_stub(
        "showToast: (m) => { calls.toasts.push(String(m)); },"
        " showError: (m) => { calls.errors.push(String(m)); },"
        " styledConfirm: async () => true, emptyStateIcon: () => '',"
        " el: (id) => document.getElementById(id), debounce: (f) => f,",
        before="export const calls = { toasts: [], errors: [] };"),
    "spinner.js": (
        "const row = (t) => { const n = globalThis.document.createElement('div');"
        " n.className = 'loading-row'; n.textContent = t; return n; };\n"
        "export function createLoadingRow(t){ return row(t); }\n"
        "export function createWhirlpool(){ return { element: globalThis.document.createElement('span'), destroy(){} }; }\n"
        "export default { createLoadingRow: row, createWhirlpool };\n"),
    "sessions.js": "export default { getCurrentSessionId: () => null };\n",
    "windowDrag.js": "export function makeWindowDraggable(){}\n",
    "tileManager.js": "export function snapModalToZone(){}\n",
    "toolWindowZOrder.js": "export function topPortalZ(){ return 5000; }\n",
    # C-NAV, faked (see the module docstring).
    "modalManager.js": """
export const nav = { registered: {}, shown: [], opener: null };
export function setBackgroundWork(){ return false; }
export function isRegistered(id){ return !!nav.registered[id]; }
export function register(id, opts = {}){ nav.registered[id] = opts; }
export function showWindow(id, opts = {}){
  nav.shown.push({ id, ...opts });
  if (opts.from) nav.opener = { id, from: opts.from, tab: opts.tab };
  return 'opened';
}
/** fx-back's other half: closing a window opened from another re-raises the
 *  opener on the tab it was on, through the opener's own `setTab`. */
export function closeOpened(){
  const o = nav.opener; nav.opener = null;
  if (!o) return null;
  const reg = nav.registered[o.from];
  if (reg && typeof reg.setTab === 'function' && o.tab != null) reg.setTab(o.tab);
  return o;
}
export default { setBackgroundWork, isRegistered, register, showWindow, closeOpened };
""",
    # The real `openSkillsWindow` hands `{from, tab}` to `showWindow` — that
    # half is `tests/test_the_skills_window_opens_from_its_opener_js.py`'s.
    "skills.js": """
import { showWindow } from '__MODALS__';
export const opened = [];
export function openSkillsWindow(view, opts){
  opened.push({ view, opts: opts || null });
  showWindow('skills-modal', opts || {});
  return true;
}
export function loadSkills(){}
export default { openSkillsWindow, loadSkills };
""",
}

_SHIM = r"""
import { installDom, installHtmlParsing, Node } from './dom.js';
export const document = installDom();
installHtmlParsing();
export { Node };
document.body.innerHTML = __MARKUP__;
for (const id of ['tool-memory-btn', 'add-memory-btn']) {
  const n = document.createElement('button'); n.setAttribute('id', id); document.body.appendChild(n);
}
export const calls = { fetch: [] };
export function mockFetch(handler) {
  globalThis.fetch = async (url, opts) => {
    const entry = { url: String(url), method: (opts && opts.method) || 'GET' };
    if (opts && typeof opts.body === 'string') { try { entry.body = JSON.parse(opts.body); } catch { entry.body = opts.body; } }
    calls.fetch.push(entry);
    return handler(String(url), opts || {});
  };
}
export function res(status, payload) {
  return { ok: status >= 200 && status < 300, status, json: async () => (payload || {}) };
}
export function fire(node, type, extra = {}) {
  node.dispatchEvent({ type, target: node, stopPropagation() {}, preventDefault() {}, ...extra });
}
export function ready() { fire(document, 'DOMContentLoaded'); }
export function byId(id) { return document.getElementById(id); }
export function tick(n = 10) {
  let p = Promise.resolve();
  for (let i = 0; i < n; i++) p = p.then(() => new Promise((r) => setTimeout(r, 0)));
  return p;
}
"""

def _modal_manager_specifier() -> str:
    """The specifier `memory.js` imports the window manager by, cache-buster
    and all: node keys a module by its whole URL, so the case has to import the
    same one to read the fake `memory.js` wrote to."""
    m = re.search(r"from '(\./modalManager\.js[^']*)'", MEMORY_JS.read_text(encoding="utf-8"))
    assert m, "memory.js no longer imports the window manager"
    return m.group(1)


_PREAMBLE = """
import { document, calls, mockFetch, res, fire, ready, byId, tick } from './shim.js';
import { nav, closeOpened } from '__MODALS__';
import { opened } from './skills.js';
import { dismissTopMenu } from './escMenuStack.js';
globalThis.window = globalThis;
globalThis.CSS = globalThis.CSS || { escape: (s) => String(s) };
if (typeof globalThis.addEventListener !== 'function') globalThis.addEventListener = () => {};
globalThis.navigator = globalThis.navigator || {};
const observers = [];
globalThis.MutationObserver = class {
  constructor(cb) { this.cb = cb; }
  observe(target) { observers.push({ target, cb: this.cb }); }
  disconnect() {}
};
const notify = (el) => observers.filter((o) => o.target === el).forEach((o) => o.cb([]));
// The parser keeps attributes; an <input type=range>'s min/max/step are
// properties in a browser, and `syncPrefSlider` reads them.
{ const s = byId('skill-confidence-slider');
  for (const k of ['min', 'max', 'step', 'value']) s[k] = s.getAttribute(k); }
const mem = await import('./memory.js');
const ROWS = [
  { id: 'a', text: 'Rowan prefers tea to coffee', category: 'preference', source: 'manual', timestamp: 1 },
  { id: 'b', text: 'The launch is on the 14th', category: 'fact', source: 'manual', timestamp: 2 },
];
let PREFS = {};
const serve = (rows = ROWS) => mockFetch((url, opts) => {
  if (/\\/api\\/memory$/.test(url)) return res(200, { memory: rows });
  if (/\\/api\\/prefs$/.test(url)) return res(200, PREFS);
  if (/\\/api\\/prefs\\//.test(url) && opts.method === 'PUT') return res(200, {});
  if (/\\/api\\/prefs\\//.test(url)) return res(200, { value: null });
  return res(200, {});
});
const openBrain = async () => {
  const m = byId('memory-modal'); m.classList.add('hidden'); notify(m);
  m.classList.remove('hidden'); notify(m); await tick();
};
const docClicks = () => (document.listeners.click || []).length;
const tabOf = () => mem.getBrainTab();
const out = (o) => console.log(JSON.stringify(o));
"""


@pytest.fixture(scope="module")
def brain(tmp_path_factory):
    shim = _SHIM.replace("__MARKUP__", json.dumps(_brain_markup()))
    stubs = {k: v.replace("__MODALS__", _modal_manager_specifier()) for k, v in _STUBS.items()}
    return _make_sandbox(tmp_path_factory.mktemp("brainplace"), MEMORY_JS, shim, stubs)


def _brain(sandbox, script):
    return _run(sandbox, _PREAMBLE.replace("__MODALS__", _modal_manager_specifier()), script)


# ── PERF-M-3 · one listener, not one per memory per render ───────────────────

def test_six_brain_opens_add_no_document_listener(brain):
    """`PERF-M-3`. Measured on `32df791` with CDP in the real app: 67 memories,
    six Brain opens → +402 `document` click listeners, all from the per-item
    `document.addEventListener` in `renderMemoryList`; never removed. Here: a
    list of 40, rendered on six opens, as the sidebar door does."""
    o = _brain(brain, """
        const rows = Array.from({ length: 40 }, (_, i) => ({ id: 'm' + i, text: 'fact ' + i, timestamp: i }));
        serve(rows); ready(); await mem.loadMemories(); await tick();
        const before = docClicks();
        for (let i = 0; i < 6; i++) { await openBrain(); mem.renderMemoryList(); }
        await tick();
        out({ before, after: docClicks(), drawn: byId('memory-list').querySelectorAll('.memory-item').length });
    """)
    assert o["drawn"] == 40
    assert o["after"] == o["before"], f"six opens added {o['after'] - o['before']} document click listeners"


def test_a_memory_menu_is_buttons_and_takes_its_listener_with_it(brain):
    """`BRAIN-U-6` + `PERF-M-3`. The menu is built on open through
    `bindMenuDismiss` — buttons with `role=menuitem`, one outside-click
    listener while it is open, none after; Escape's stack closes it too. On
    `32df791` the items were `<div>`s with no tabindex (Tab and the arrows
    never reached them) and the menu was built for every memory up front."""
    o = _brain(brain, """
        serve(); ready(); await mem.loadMemories(); await tick();
        const base = docClicks();
        const btn = byId('memory-list').querySelector('.memory-menu-btn');
        fire(btn, 'click'); await tick();
        const menu = document.body.querySelector('.memory-item-dropdown');
        const items = menu ? menu.querySelectorAll('button').map((b) => [b.getAttribute('role'), b.textContent.trim()]) : [];
        const whileOpen = docClicks();
        const expanded = btn.getAttribute('aria-expanded');
        for (const fn of (document.listeners.click || []).slice()) fn({ type: 'click', target: document.body });
        await tick();
        const closed = !document.body.querySelector('.memory-item-dropdown');
        const afterOutside = docClicks();
        fire(btn, 'click'); await tick();
        const escaped = dismissTopMenu();
        await tick();
        out({ base, whileOpen, afterOutside, items, expanded, closed, escaped,
              afterEscape: docClicks(), gone: !document.body.querySelector('.memory-item-dropdown'),
              role: menu && menu.getAttribute('role'), btnType: btn.type });
    """)
    assert o["role"] == "menu" and o["btnType"] == "button"
    assert [r for r, _t in o["items"]] == ["menuitem"] * 5
    assert [t for _r, t in o["items"]][:4] == ["Pin", "●Select", "✎ Edit", "✕ Delete"]
    assert o["expanded"] == "true"
    assert o["whileOpen"] == o["base"] + 1
    assert o["closed"] and o["afterOutside"] == o["base"]
    assert o["escaped"] is True and o["gone"] and o["afterEscape"] == o["base"]


# ── PERF-M-8 · one read of the switches ─────────────────────────────────────

def test_the_brain_reads_its_switches_in_one_request_and_keeps_a_saved_one(brain):
    """`PERF-M-8`. Measured on `32df791`: every `loadMemories()` — at load and
    2.8 s after every chat switch — read seven prefs one at a time
    (`GET /api/prefs/<key>`, each awaited), and each switch showed its default
    until its own answer came. Now one `GET /api/prefs`, once, and a switch
    saved since is not put back by the next redraw."""
    o = _brain(brain, """
        PREFS = { memory_enabled: false, auto_skills: true, skill_max_injected: 5, skill_min_confidence: 0.9 };
        serve(); ready(); await mem.loadMemories(); await tick();
        const gets = () => calls.fetch.filter((c) => c.method === 'GET' && /\\/api\\/prefs/.test(c.url)).map((c) => c.url.replace(/^.*\\/api/, '/api'));
        const first = gets();
        const state = { memory: byId('memory-enabled-header-toggle').checked, autoSkills: byId('auto-skills-toggle').checked,
                        max: byId('skill-max-input').value, conf: byId('skill-confidence-label').textContent };
        await mem.loadMemories(); await tick();
        const second = gets();
        const t = byId('auto-skills-toggle'); t.checked = false; fire(t, 'change'); await tick();
        await mem.loadMemories(); await tick();
        out({ first, second, state, keptOff: byId('auto-skills-toggle').checked,
              puts: calls.fetch.filter((c) => c.method === 'PUT').map((c) => [c.url.replace(/^.*\\/api/, '/api'), c.body.value]) });
    """)
    assert o["first"] == ["/api/prefs"], o["first"]
    assert o["second"] == ["/api/prefs"], "a second redraw read the switches again"
    assert o["state"] == {"memory": False, "autoSkills": True, "max": "5", "conf": "≥ 90%"}
    assert o["puts"] == [["/api/prefs/auto_skills", False]]
    assert o["keptOff"] is False, "a redraw put a switch back where the first read left it"


def test_a_closed_brain_marked_stale_asks_when_it_next_opens(brain):
    """`PERF-M-7` (the Brain's half). A chat switch marks a closed Brain stale
    rather than re-reading it; the next open asks once."""
    o = _brain(brain, """
        serve(); ready(); await mem.loadMemories(); await tick();
        const n = () => calls.fetch.filter((c) => /\\/api\\/memory$/.test(c.url)).length;
        const loaded = n();
        await openBrain(); const fresh = n();
        mem.markMemoriesStale();
        const marked = n();
        await openBrain(); const stale = n();
        await openBrain(); const again = n();
        out({ loaded, fresh, marked, stale, again });
    """)
    assert (o["loaded"], o["fresh"], o["marked"], o["stale"], o["again"]) == (1, 1, 1, 2, 2)


# ── BRAIN-U-8 · real tabs ───────────────────────────────────────────────────

def test_the_brains_tabs_are_tabs_with_the_tablist_keys(brain):
    """`BRAIN-U-8`. On `32df791` the strip was five buttons (`role` null) and
    ArrowRight did nothing; the Skills window's and the Workbench's are real
    tabs. Skills is a door now, outside the tablist."""
    o = _brain(brain, """
        serve(); ready(); await tick();
        const list = document.body.querySelector('[role="tablist"]');
        const tabs = byId('memory-modal').querySelectorAll('.memory-tab');
        const roles = tabs.map((t) => [t.dataset.memoryTab, t.getAttribute('role'), t.getAttribute('aria-controls')]);
        const press = (key) => { const t = byId('memory-tab-' + tabOf()); fire(t, 'keydown', { key }); return tabOf(); };
        const walk = [press('ArrowRight'), press('ArrowRight'), press('End'), press('ArrowRight'), press('ArrowLeft'), press('Home')];
        mem.showBrainTab('rag');
        const rag = { sel: byId('memory-tab-rag').getAttribute('aria-selected'), idx: byId('memory-tab-rag').tabIndex,
                      other: byId('memory-tab-browse').tabIndex, shown: !byId('memory-panel-rag').classList.contains('hidden'),
                      hidden: byId('memory-panel-browse').classList.contains('hidden') };
        out({ label: list && list.getAttribute('aria-label'), roles, walk, rag,
              focus: byId('memory-tab-rag').focused,
              doorInList: !!(list && list.querySelector('#memory-skills-door')) });
    """)
    assert o["label"] == "Brain"
    assert o["roles"] == [["browse", "tab", "memory-panel-browse"], ["rag", "tab", "memory-panel-rag"],
                          ["add", "tab", "memory-panel-add"], ["settings", "tab", "memory-panel-settings"]]
    assert o["walk"] == ["rag", "add", "settings", "browse", "settings", "browse"]
    assert o["rag"] == {"sel": "true", "idx": 0, "other": -1, "shown": True, "hidden": True}
    assert o["doorInList"] is False


# ── NAV-U-1 / NAV-M-14 · Skills is a door with the Brain as its opener ───────

def test_the_skills_door_opens_from_the_brain_and_closing_lands_on_rag(brain):
    """The owner's example: Brain → RAG → Skills, then back. On `32df791` the
    Skills tab switched the Brain to a launcher card and opened the window over
    it, with no opener: closing Skills landed on the card, and the Brain
    reopened on it. Now the door asks C-NAV for `{from: 'memory-modal', tab}`,
    the Brain's tab does not move, and closing (the fake's half of C-NAV)
    re-raises it on RAG through the `setTab` it registered."""
    o = _brain(brain, """
        serve(); ready(); await tick();
        mem.showBrainTab('rag');
        fire(byId('memory-skills-door'), 'click'); await tick();
        const afterDoor = tabOf();
        mem.showBrainTab('browse');           // anything may happen meanwhile
        const back = closeOpened();
        const afterClose = { tab: tabOf(), shown: !byId('memory-panel-rag').classList.contains('hidden') };
        mem.showBrainTab('add');
        fire(document.body.querySelector('[data-brain-skills="add"]'), 'click'); await tick();
        out({ opened, afterDoor, back, afterClose,
              reg: Object.keys(nav.registered.memory_modal || nav.registered['memory-modal'] || {}).sort(),
              launcher: !!byId('memory-modal').querySelector('[data-memory-panel="skills"]') });
    """)
    assert o["opened"][0] == {"view": "browse", "opts": {"from": "memory-modal", "tab": "rag"}}
    assert o["opened"][1] == {"view": "add", "opts": {"from": "memory-modal", "tab": "add"}}
    assert o["afterDoor"] == "rag", "the door moved the Brain off the tab it was on"
    assert o["back"] == {"id": "skills-modal", "from": "memory-modal", "tab": "rag"}
    assert o["afterClose"] == {"tab": "rag", "shown": True}
    assert {"getTab", "setTab", "sidebarBtnId", "closeFn"} <= set(o["reg"])
    assert o["launcher"] is False, "the launcher card is back"


def test_the_brain_registers_getTab_and_setTab(brain):
    """C-NAV: a window with tabs gives both, and they read and set the tab on
    show. Registered once (and again after a chip's × forgets it)."""
    o = _brain(brain, """
        serve(); ready(); await tick();
        const reg = nav.registered['memory-modal'];
        mem.showBrainTab('settings');
        const read = reg.getTab();
        reg.setTab('rag');
        const set = { tab: tabOf(), shown: !byId('memory-panel-rag').classList.contains('hidden') };
        reg.setTab('skills');                 // not a tab: ignored, not emptied
        delete nav.registered['memory-modal'];
        await openBrain();
        out({ read, set, after: tabOf(), sidebar: reg.sidebarBtnId,
              again: !!nav.registered['memory-modal'] });
    """)
    assert o["read"] == "settings"
    assert o["set"] == {"tab": "rag", "shown": True}
    assert o["after"] == "rag"
    assert o["sidebar"] == "tool-memory-btn"
    assert o["again"] is True


# ── BRAIN-U-11 · the switch dims the list, COPY-U-15 · the count said once ───

def test_switching_memories_off_dims_the_list_only(brain):
    """`BRAIN-U-11`. On `32df791` the whole `.memory-modal-body` went to 0.3 —
    the tab strip, RAG, Add and Settings with it — while the list stayed at 1."""
    o = _brain(brain, """
        PREFS = { memory_enabled: false };
        serve(); ready(); await mem.loadMemories(); await tick();
        const off = { list: byId('memory-list').style.opacity || '',
                      body: byId('memory-modal').querySelector('.memory-modal-body').style.opacity || '' };
        const t = byId('memory-enabled-header-toggle'); t.checked = true; fire(t, 'change'); await tick();
        out({ off, on: byId('memory-list').style.opacity || '' });
    """)
    assert o["off"] == {"list": "0.4", "body": ""}
    assert o["on"] == ""


def test_the_count_is_said_once_and_says_n_of_m_when_some_are_hidden(brain):
    """`COPY-U-15`. Tab *Memories 2* over header *Memories 2 memories* was the
    same number twice. The tab carries it; the header speaks only when a search
    hides some."""
    o = _brain(brain, """
        serve(); ready(); await mem.loadMemories(); await tick();
        const all = { tab: byId('memory-count').textContent, head: byId('memory-count-h2').textContent };
        byId('memory-search').value = 'tea';
        mem.renderMemoryList(); mem.updateMemoryCount();
        out({ all, some: { tab: byId('memory-count').textContent, head: byId('memory-count-h2').textContent } });
    """)
    assert o["all"] == {"tab": "2", "head": ""}
    assert o["some"] == {"tab": "2", "head": "1 of 2"}
