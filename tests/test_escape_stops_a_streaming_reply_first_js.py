# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B-NEW-7` — one Escape stops a streaming reply, even with its thinking open.

Measured on `a936b5c` (`/work/notes/p23-acceptance.md`) and again on `cdf040f`
in Chromium, the paced scripted model, the caret in the message box: a reply
streams with its live reasoning drawn open; **Escape #1 folded the thinking**
and the reply went on (6 → 25 → 43 words), **Escape #2 stopped it**. The
`ui.js` arbiter's last rule (an open `.thinking-content.expanded` → fold,
`stopImmediatePropagation`) took the key in the capture phase, so the stop —
`keyboard-shortcuts.js`, on `window` in the bubble phase, after every other
listener (`B945`, `CHAT-M-1`) — never heard it.

With the fold out of the way the first Escape still stopped nothing in
Chromium. Traced on `cdf040f` (a diff of `<body>`'s children between the stop's
capture snapshot and its decision): `sessions.js`' `_initDropdownDismiss` wrote
`display: none` onto every chat row's menu on every Escape — twenty of them,
fresh from the list render that the new reply's chat caused, closed by the
stylesheet with no inline style — and the stop reads any such change as "this
Escape closed something" (`escapeClaim` → `'closed'`). The rule now writes only
onto a menu that is open. Both halves are driven below.

Driven here, not read (`Law 20`): the real arbiter and its helpers, cut out of
`static/js/ui.js` with the cut `tests/test_escape_closes_the_workbench_panel_before_the_window_js.py`
makes, registered as `ui.js` registers them (capture and bubble on
`document`), `sessions.js`' `_initDropdownDismiss` as the page wires it, and the
real `static/js/keyboard-shortcuts.js` with its real
`initKeyboardShortcuts`, in the event model
`tests/test_escape_stops_the_reply_only_when_it_closed_nothing_js.py` built
(keys travel window → document → target → document → window, both phases).
The count is of calls to `chatModule.stopCurrentReply`, Escape's stop.
"""

import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_tool_effect_surfaces_js import _run  # noqa: E402
from test_escape_closes_the_workbench_panel_before_the_window_js import _arbiter  # noqa: E402
from test_escape_stops_the_reply_only_when_it_closed_nothing_js import _SHIM as _STOP_SHIM  # noqa: E402
from tests.helpers.js_source import js_definition  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"
_SESSIONS_JS = (JS / "sessions.js").read_text(encoding="utf-8")
_DROPDOWN_DISMISS = js_definition(_SESSIONS_JS, _SESSIONS_JS.index("function _initDropdownDismiss("))

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

# The arbiter asks for more of the DOM than the stop's own cases did: a
# compound class (`.thinking-content.expanded`), an attribute
# (`.thinking-header[data-thinking-id]`), a tag (`input, textarea, …`),
# `querySelector` inside an element, `contains`, `nodeType`. A browser has
# all of them.
_SHIM = _STOP_SHIM + r"""
const _matches1 = El.prototype.matches;
El.prototype.matches = function (sel) {
  return sel.split(',').map((s) => s.trim()).some((s) => {
    const m = /^([a-z]*)((?:\.[\w-]+)*)(?:\[([\w-]+)\])?$/.exec(s);
    if (!m || (!m[1] && !m[2] && !m[3])) return _matches1.call(this, s);
    if (m[1] && this.tagName !== m[1].toUpperCase()) return false;
    if (!m[2].split('.').filter(Boolean).every((c) => this.classList.contains(c))) return false;
    return !m[3] || m[3] in this.attrs;
  });
};
El.prototype.querySelectorAll = function (sel) {
  const out = [];
  const walk = (n) => n.children.forEach((c) => { if (c.matches(sel)) out.push(c); walk(c); });
  walk(this);
  return out;
};
El.prototype.querySelector = function (sel) { return this.querySelectorAll(sel)[0] || null; };
El.prototype.contains = function (n) { for (let x = n; x; x = x.parentNode) if (x === this) return true; return false; };
Object.defineProperty(El.prototype, 'nodeType', { get() { return 1; } });
El.prototype.blur = function () { if (document.activeElement === this) document.activeElement = document.body; };
"""

_PREAMBLE = r"""
import { document, win, composer, toolWindow, press, El } from './shim.js';
import * as KS from './keyboard-shortcuts.js';
let stops = 0;
KS.initKeyboardShortcuts({
  el: (id) => document.getElementById(id), Storage: {}, sessionModule: null, uiModule: {},
  chatModule: { stopCurrentReply() { stops += 1; return true; } },
  adminModule: null, settingsModule: null, searchChatModule: null,
  _closeCompareIfActive: () => false, _deactivateIncognito: () => {}, API_BASE: '',
});
// What the arbiter imports, standing in: the window manager closes a window
// the way its × does; the back stack has nothing on it; no menu is open.
const closed = [];
const Modals = { closeWindow: (id) => { closed.push(id); document.getElementById(id).classList.add('hidden'); } };
const backStack = { DRAWER: 'sidebar-drawer', top: () => null, isTracked: (id) => /-modal$/.test(id) };
const toolWindowZ = () => 0;
const dismissTopMenu = () => false;
%s
document.addEventListener('keydown', escapeArbiter, true);
document.addEventListener('keydown', escapeLeavesField);
// `sessions.js`' Escape rule for the chat rows' menus, as the page wires it.
%s
_initDropdownDismiss();
/** A chat row's menu as a list render leaves it on `<body>`: closed by the
 *  stylesheet, no inline `display`. */
const rowMenu = (cls = 'dropdown session-dropdown session-dropdown-menu') => document.body.append(new El('div', '', cls));

// The chat: the send button in its streaming state, a reply's live reasoning
// drawn open under its header.
const send = document.body.append(new El('button', '', 'send-btn'));
send.dataset = { mode: 'streaming' };
const section = document.body.append(new El('div', '', 'thinking-section'));
const header = section.append(new El('div', '', 'thinking-header'));
header.setAttribute('data-thinking-id', 't1');
const think = section.append(new El('div', '', 'thinking-content expanded'));
let folds = 0;
header.click = () => { folds += 1; think.classList.remove('expanded'); };
const open = () => think.classList.contains('expanded');
const out = (o) => console.log(JSON.stringify(o));
"""


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    d = tmp_path_factory.mktemp("escstream")
    (d / "shim.js").write_text(_SHIM, encoding="utf-8")
    (d / "appConfig.js").write_text(
        "export function getSettings() { return Promise.resolve({}); }\n", encoding="utf-8")
    shutil.copy(JS / "keyboard-shortcuts.js", d / "keyboard-shortcuts.js")
    shutil.copy(JS / "platform.js", d / "platform.js")
    return d


def _go(box, script):
    return _run(box, _PREAMBLE % (_arbiter(), _DROPDOWN_DISMISS), script)


def test_the_first_escape_stops_the_reply_and_leaves_the_thinking_open(box):
    """The acceptance's walk: the caret in the message box, the reply
    streaming, its thinking open — one Escape is the stop."""
    o = _go(box, """
        composer.focus();
        const ev = press(composer);
        out({ stops, folds, open: open(), claimed: ev.defaultPrevented || ev.propagationStopped });
    """)
    assert o == {"stops": 1, "folds": 0, "open": True, "claimed": False}


def test_once_the_reply_has_stopped_the_next_escape_folds_the_thinking(box):
    """The fold is not lost, only second: with the button idle again the
    arbiter folds the open block and the key goes no further."""
    o = _go(box, """
        composer.focus();
        press(composer);
        send.dataset.mode = '';          // the stop drew the idle button
        const ev = press(composer);
        out({ stops, folds, open: open(), claimed: ev.defaultPrevented });
    """)
    assert o == {"stops": 1, "folds": 1, "open": False, "claimed": True}


def test_with_no_reply_streaming_escape_folds_the_thinking_as_before(box):
    o = _go(box, """
        send.dataset.mode = '';
        composer.focus();
        press(composer);
        out({ stops, folds, open: open() });
    """)
    assert o == {"stops": 0, "folds": 1, "open": False}


def test_a_window_on_screen_is_still_the_first_thing_escape_closes(box):
    """Streaming changes only the fold's place: a tool window open over the
    chat is a layer on screen, closed first (`P23-01`), and the reply goes on."""
    o = _go(box, """
        const tasks = toolWindow('tasks-modal');
        composer.focus();
        press(composer);
        const first = { stops, folds, closed: closed.slice() };
        press(composer);
        out({ first, second: { stops, folds, open: open() } });
    """)
    assert o["first"] == {"stops": 0, "folds": 0, "closed": ["tasks-modal"]}
    assert o["second"] == {"stops": 1, "folds": 0, "open": True}


def test_menus_a_list_render_left_closed_do_not_hold_the_first_escape(box):
    """The second half, found on the drive: with the fold out of the way the
    first Escape still stopped nothing in Chromium, because `sessions.js`
    wrote `display: none` onto every chat row's menu — twenty fresh ones after
    the reply's own chat appeared in the list — and the stop reads a change on
    `<body>` as "this Escape closed something". Closed menus are left alone."""
    o = _go(box, """
        const menus = [rowMenu(), rowMenu('dropdown session-folder-submenu'), rowMenu(), rowMenu('dropdown session-folder-submenu')];
        composer.focus();
        press(composer);
        out({ stops, folds, open: open(), styles: menus.map((m) => m.style.display || '') });
    """)
    assert o == {"stops": 1, "folds": 0, "open": True, "styles": ["", "", "", ""]}


def test_an_open_chat_menu_is_the_first_escape_and_the_stop_the_second(box):
    """One layer per press still: a chat row's menu that is open closes on the
    first Escape and the reply goes on; the next Escape stops it."""
    o = _go(box, """
        const shut = rowMenu();
        const opened = rowMenu(); opened.style.display = 'block';
        composer.focus();
        press(composer);
        const first = { stops, opened: opened.style.display, shut: shut.style.display || '' };
        press(composer);
        out({ first, second: { stops } });
    """)
    assert o["first"] == {"stops": 0, "opened": "none", "shut": ""}
    assert o["second"] == {"stops": 1}
