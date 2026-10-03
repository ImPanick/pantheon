# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P23-01` — one back stack: Back = Escape = `←`, and the URL names the top window.

Measured on `9560d50` (the audit's NAV-M-1, CHAT-M-7, SET-M-24, NAV-M-8/9):
`grep pushState static/` found nothing and nothing listened to `popstate`, so
the browser's Back left the app from every screen — Brain open, Back,
`about:blank` — opening a window never wrote the URL, so a reload forgot it,
and three chats visited left `history.length` at 2.

Driven here, not read: the real `static/js/backStack.js` under node, against a
session history that behaves like a browser's — entries and an index;
`pushState` drops the forward entries; `replaceState` rewrites the current one;
`back()` moves a task later and only then fires `popstate`, and never for a push
or a replace; going back past the first entry leaves the page. The windows are
shim elements whose classes say whether they are up, as the real ones do
(`.hidden`, `.modal-minimized`, a `.modal-content.modal-closing`). The hooks
`modalManager.js` gives the module in the page — close a window the way its ×
does, raise it, draw its `← <opener>`, its tab — are recorded here; what they
do in the page is driven by `tests/test_the_dock_chip_and_the_way_back_js.py`.

**The adversary is the browser's own Back button** (`Law 17`): a person on a
phone presses it to close what they opened, and it left the app.
"""

import json
import shutil
from pathlib import Path

import pytest

from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
BACK_JS = ROOT / "static" / "js" / "backStack.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_SHIM = r"""
import { installDom, Node } from './dom.js';
export const document = installDom();
export { Node };

// ── a session history like a browser's ───────────────────────────────────────
const clone = (v) => (v == null ? v : JSON.parse(JSON.stringify(v)));
export const H = { entries: [{ state: null, url: '/#chatA' }], i: 0, left: false, backs: 0 };
const listeners = {};
globalThis.addEventListener = (t, fn) => { (listeners[t] = listeners[t] || []).push(fn); };
globalThis.removeEventListener = () => {};
function setLoc(url) {
  const u = new URL(url, 'http://t.local');
  Object.assign(globalThis.location, { pathname: u.pathname, search: u.search, hash: u.hash, href: u.href });
}
Object.defineProperty(globalThis, 'location', { value: { origin: 'http://t.local' }, writable: true, configurable: true });
setLoc('/#chatA');
export const history = {
  get state() { return H.entries[H.i].state; },
  get length() { return H.entries.length; },
  pushState(state, _t, url) {
    H.entries.splice(H.i + 1);
    H.entries.push({ state: clone(state), url: url == null ? H.entries[H.i].url : String(url) });
    H.i += 1;
    setLoc(H.entries[H.i].url);
  },
  replaceState(state, _t, url) {
    H.entries[H.i] = { state: clone(state), url: url == null ? H.entries[H.i].url : String(url) };
    setLoc(H.entries[H.i].url);
  },
  back() { H.backs += 1; this.go(-1); },
  go(d) {
    setTimeout(() => {
      const j = H.i + d;
      if (j < 0) { H.left = true; return; }
      H.i = j;
      setLoc(H.entries[j].url);
      const ev = { type: 'popstate', state: clone(H.entries[j].state) };
      (listeners.popstate || []).forEach((f) => f(ev));
    }, 0);
  },
};
Object.defineProperty(globalThis, 'history', { value: history, writable: true, configurable: true });

/** The person presses the browser's Back. */
export const pressBack = () => history.go(-1);
export const pressForward = () => history.go(1);
export const settle = (ms = 30) => new Promise((r) => setTimeout(r, ms));

// ── windows ────────────────────────────────────────────────────────────────
let _z = 1000;
export function makeWin(id) {
  const m = document.body.appendChild(new Node('div'));
  m.setAttribute('id', id);
  m.className = 'modal hidden';
  const c = m.appendChild(new Node('div'));
  c.className = 'modal-content';
  const h = c.appendChild(new Node('div'));
  h.className = 'modal-header';
  return m;
}
export const up = (id) => { const m = document.getElementById(id); m.classList.remove('hidden'); m.style.zIndex = String(++_z); };
export const down = (id) => document.getElementById(id).classList.add('hidden');
export const isUp = (id) => !document.getElementById(id).classList.contains('hidden');
export const top = () => ({ url: location.pathname + location.hash, i: H.i, n: H.entries.length,
  state: history.state && { wins: history.state.wins.map((w) => w.id), opened: history.state.opened } });
"""

_PREAMBLE = (
    "import { document, Node, H, history, pressBack, pressForward, settle, makeWin, up, down, isUp, top }"
    " from './shim.js';\n"
    "const B = await import('./backStack.js');\n"
    "const log = [];\n"
    "const drawn = [];\n"
    "const tabs = {};\n"
    "let menus = 0;\n"
    "let asks = new Set();\n"
    "B.configure({\n"
    "  labelOf: (id) => id,\n"
    "  tabHooks: (id) => tabs[id] || null,\n"
    "  closeWindow: (id) => { log.push('close ' + id); if (!asks.has(id)) down(id); },\n"
    "  raise: (id) => log.push('raise ' + id),\n"
    "  drawBack: (id, from) => drawn.push(id + ' ' + from),\n"
    "  dismissTopMenu: () => { if (menus > 0) { menus -= 1; log.push('menu'); return true; } return false; },\n"
    "});\n"
    "for (const id of ['memory-modal', 'skills-modal', 'tasks-modal', 'settings-modal', 'calendar-modal'])"
    " makeWin(id);\n"
    "const step = async () => { B.sync(); await settle(); };\n"
    "const out = (o) => console.log(JSON.stringify(o));\n"
)


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    return _make_sandbox(tmp_path_factory.mktemp("backstack"), BACK_JS, _SHIM, {})


def _case(box, script, boot=True):
    pre = _PREAMBLE + ("B.init(); B.ready(); await settle();\n" if boot else "")
    return _run(box, pre, script)


def test_a_window_that_opens_pushes_one_entry_named_for_it(box):
    o = _case(box, """
        const first = top();
        up('memory-modal'); await step();
        out({ first, opened: top() });
    """)
    assert o["first"] == {"url": "/#chatA", "i": 0, "n": 1,
                          "state": {"wins": [], "opened": None}}
    assert o["opened"] == {"url": "/brain#chatA", "i": 1, "n": 2,
                           "state": {"wins": ["memory-modal"], "opened": "memory-modal"}}


def test_back_closes_the_top_window_and_only_it(box):
    """Back twice closes the two windows, top first, each through its own close
    path; a third Back is the browser's — the app never took it."""
    o = _case(box, """
        up('tasks-modal'); await step();
        up('memory-modal'); await step();
        const both = top();
        pressBack(); await settle(); await step();
        const one = { ...top(), tasks: isUp('tasks-modal'), brain: isUp('memory-modal') };
        pressBack(); await settle(); await step();
        const none = { ...top(), tasks: isUp('tasks-modal') };
        pressBack(); await settle();
        out({ both, one, none, left: H.left, ourBacks: H.backs, log });
    """)
    assert o["both"]["url"] == "/brain#chatA" and o["both"]["n"] == 3
    assert o["one"] == {"url": "/tasks#chatA", "i": 1, "n": 3, "tasks": True, "brain": False,
                        "state": {"wins": ["tasks-modal"], "opened": "tasks-modal"}}
    assert o["none"]["url"] == "/#chatA" and o["none"]["tasks"] is False
    assert o["log"] == ["close memory-modal", "close tasks-modal"]
    assert o["left"] is True, "the last Back leaves the page, as the browser's Back does"
    assert o["ourBacks"] == 0, "the module made no history.back() of its own"


def test_a_window_closed_in_the_app_takes_its_entry_back_off(box):
    """×, Escape and `←` close the window in the page; the entry its opening
    pushed goes with it, so Back is not left pointing at a closed window."""
    o = _case(box, """
        up('memory-modal'); await step();
        down('memory-modal'); await step(); await settle();
        out({ ...top(), ourBacks: H.backs, log });
    """)
    assert o == {"url": "/#chatA", "i": 0, "n": 2, "state": {"wins": [], "opened": None},
                 "ourBacks": 1, "log": []}


def test_closing_the_window_behind_rewrites_the_entry_and_back_skips_what_is_gone(box):
    o = _case(box, """
        up('tasks-modal'); await step();
        up('memory-modal'); await step();
        down('tasks-modal'); await step();
        const rewritten = top();
        down('memory-modal'); await step(); await settle(); await settle();
        out({ rewritten, after: top(), ourBacks: H.backs, left: H.left });
    """)
    assert o["rewritten"] == {"url": "/brain#chatA", "i": 2, "n": 3,
                              "state": {"wins": ["memory-modal"], "opened": "memory-modal"}}
    # Closing the Brain took its entry off and then the stale Tasks entry under
    # it, which held a window that is no longer there — and stopped at the first.
    assert o["after"]["url"] == "/#chatA" and o["after"]["i"] == 0
    assert o["ourBacks"] == 2 and o["left"] is False


def test_back_peels_a_menu_first_and_the_window_and_its_entry_stay(box):
    """One Back peels one layer, as Escape does: a menu on the Escape stack
    goes, the window stays, and the entry is put back for the next Back."""
    o = _case(box, """
        up('memory-modal'); await step();
        menus = 1;
        pressBack(); await settle(); await step();
        const peeled = { ...top(), brain: isUp('memory-modal') };
        pressBack(); await settle(); await step();
        out({ peeled, then: { ...top(), brain: isUp('memory-modal') }, log });
    """)
    assert o["peeled"] == {"url": "/brain#chatA", "i": 1, "n": 2, "brain": True,
                           "state": {"wins": ["memory-modal"], "opened": "memory-modal"}}
    assert o["then"]["brain"] is False and o["then"]["url"] == "/#chatA"
    assert o["log"] == ["menu", "close memory-modal"]


def test_a_window_that_asks_before_closing_keeps_its_entry(box):
    """`B1052`'s question, on Back: the Workbench asks *Save / Discard / Keep
    editing* and stays; the entry stays with it."""
    o = _case(box, """
        up('memory-modal'); await step();
        asks.add('memory-modal');
        pressBack(); await settle(); await step();
        out({ ...top(), brain: isUp('memory-modal'), log });
    """)
    assert o == {"url": "/brain#chatA", "i": 1, "n": 2, "brain": True, "log": ["close memory-modal"],
                 "state": {"wins": ["memory-modal"], "opened": "memory-modal"}}


def test_a_window_opened_from_another_says_so_and_closing_it_lands_on_the_tab(box):
    """C-NAV and the owner's walk: Brain → RAG → Skills shows `← Brain`;
    closing Skills raises the Brain on RAG even if its tab moved meanwhile."""
    o = _case(box, """
        let brainTab = 'rag';
        const set = [];
        tabs['memory-modal'] = { getTab: () => brainTab, setTab: (t) => { set.push(t); brainTab = t; } };
        up('memory-modal'); await step();
        B.noteOpener('skills-modal', 'memory-modal');
        up('skills-modal'); await step();
        const opened = history.state.wins;
        brainTab = 'browse';
        pressBack(); await settle(); await step();
        out({ opened, url: top().url, set, log, drawn, brain: isUp('memory-modal') });
    """)
    assert o["opened"] == [
        {"id": "memory-modal", "from": None, "tab": "rag", "fromTab": None},
        {"id": "skills-modal", "from": "memory-modal", "tab": None, "fromTab": "rag"},
    ]
    assert o["log"] == ["close skills-modal", "raise memory-modal"]
    # `← memory-modal` drawn on Skills when it came up, and taken down when it went.
    assert "skills-modal memory-modal" in o["drawn"]
    assert o["drawn"][-1] in ("skills-modal null", "memory-modal null")
    assert "skills-modal null" in o["drawn"][o["drawn"].index("skills-modal memory-modal"):]
    assert o["set"] == ["rag"] and o["brain"] is True
    assert o["url"] == "/brain/rag#chatA"


def test_the_url_names_the_top_window_and_its_tab(box):
    o = _case(box, """
        tabs['settings-modal'] = { getTab: () => 'shortcuts', setTab: () => {} };
        up('settings-modal'); await step();
        const settings = top().url;
        const paths = ['/', '/brain', '/memory', '/forge', '/cookbook', '/settings/shortcuts',
                       '/workbench/integrations', '/nope', '/brain/rag'].map((p) => [p, B.windowForPath(p)]);
        out({ settings, paths, built: B.pathFor([{ id: 'memory-modal', tab: 'rag' }, { id: 'custom-preset-modal' }]) });
    """)
    assert o["settings"] == "/settings/shortcuts#chatA"
    assert dict((p, w) for p, w in o["paths"]) == {
        "/": None, "/brain": {"id": "memory-modal", "tab": None},
        "/memory": {"id": "memory-modal", "tab": None},
        "/forge": {"id": "cookbook-modal", "tab": None}, "/cookbook": {"id": "cookbook-modal", "tab": None},
        "/settings/shortcuts": {"id": "settings-modal", "tab": "shortcuts"},
        "/workbench/integrations": {"id": "workbench-modal", "tab": "integrations"},
        "/nope": None, "/brain/rag": {"id": "memory-modal", "tab": "rag"},
    }
    # A window with no URL of its own over the Brain: the URL stays the Brain's.
    assert o["built"] == "/brain/rag"


def test_a_reload_reopens_what_the_entry_holds_with_its_opener_and_tabs(box):
    o = _case(box, """
        history.replaceState({ pn: 1, doc: 'earlier', idx: 2, opened: 'skills-modal', wins: [
          { id: 'memory-modal', from: null, tab: 'rag', fromTab: null },
          { id: 'skills-modal', from: 'memory-modal', tab: null, fromTab: 'rag' } ] }, '', '/skills#chatA');
        const opened = [];
        let brainTab = 'browse';
        tabs['memory-modal'] = { getTab: () => brainTab, setTab: (t) => { brainTab = t; } };
        B.setOpeners({
          'memory-modal': (tab) => { opened.push(['memory-modal', tab]); up('memory-modal'); },
          'skills-modal': (tab) => { opened.push(['skills-modal', tab]); up('skills-modal'); },
        });
        B.init();
        const restored = B.restoreFromHistory();
        B.ready();
        await settle(200);
        const stack = B.stack();
        down('skills-modal'); await step(); await settle();
        out({ restored, opened, stack, brainTab, url: top().url, ourBacks: H.backs, drawn });
    """, boot=False)
    assert o["restored"] is True
    assert o["opened"] == [["memory-modal", "rag"], ["skills-modal", None]]
    assert o["stack"] == [{"id": "memory-modal", "from": None, "tab": None},
                          {"id": "skills-modal", "from": "memory-modal", "tab": "rag"}]
    assert "skills-modal memory-modal" in o["drawn"], "the reloaded Skills says `← Brain` again"
    # Closing it after the reload lands on RAG — and the entry an earlier
    # document pushed is rewritten, never taken back (that would reload).
    assert o["brainTab"] == "rag" and o["url"] == "/brain/rag#chatA" and o["ourBacks"] == 0


def test_a_chat_switch_is_an_entry_and_back_is_the_previous_chat(box):
    o = _case(box, """
        B.chatSwitched('chatB', { push: true });
        const pushed = top();
        B.chatSwitched('chatC', { push: false });
        const replaced = top();
        pressBack(); await settle();
        out({ pushed, replaced, back: top().url });
    """)
    assert o["pushed"]["url"] == "/#chatB" and o["pushed"]["n"] == 2
    assert o["replaced"]["url"] == "/#chatC" and o["replaced"]["n"] == 2
    assert o["back"] == "/#chatA"


def test_a_url_rewrite_that_passes_null_keeps_the_stack(box):
    """Six callers drop a hash or a query with `replaceState(null, …)`; the
    stack the entry holds survives them."""
    o = _case(box, """
        up('memory-modal'); await step();
        history.replaceState(null, '', '/brain');
        out(top());
    """)
    assert o == {"url": "/brain", "i": 1, "n": 2, "state": {"wins": ["memory-modal"], "opened": "memory-modal"}}


def test_the_phone_drawer_is_a_layer_back_closes(box):
    o = _case(box, """
        const sb = document.body.appendChild(new Node('div')); sb.setAttribute('id', 'sidebar'); sb.className = 'sidebar hidden';
        const bd = document.body.appendChild(new Node('div')); bd.setAttribute('id', 'sidebar-backdrop');
        sb.classList.remove('hidden'); bd.classList.add('visible'); await step();
        const open = top();
        log.length = 0;
        B.configure({ closeWindow: (id) => { log.push('close ' + id); sb.classList.add('hidden'); bd.classList.remove('visible'); } });
        pressBack(); await settle(); await step();
        out({ open, after: top(), log });
    """)
    assert o["open"]["state"] == {"wins": ["sidebar-drawer"], "opened": "sidebar-drawer"}
    assert o["open"]["url"] == "/#chatA", "the drawer has no URL of its own"
    assert o["log"] == ["close sidebar-drawer"] and o["after"]["i"] == 0


def test_nothing_is_written_before_the_app_is_ready_and_minimized_is_gone(box):
    """Before `ready()` a window the boot opens is tracked but writes nothing;
    a window minimized to its chip is off the stack (Back does not close what
    is not on screen) and comes back on top when restored."""
    o = _case(box, """
        B.init();
        up('calendar-modal'); B.sync();
        const before = top();
        B.ready(); await settle();
        const ready = top();
        document.getElementById('calendar-modal').classList.add('modal-minimized');
        await step(); await settle();
        const minimized = top();
        out({ before, ready, minimized });
    """, boot=False)
    assert o["before"]["n"] == 1 and o["before"]["state"]["wins"] == []
    assert o["ready"]["url"] == "/calendar#chatA" and o["ready"]["n"] == 2
    assert o["minimized"]["url"] == "/#chatA" and o["minimized"]["i"] == 0
