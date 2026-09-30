# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P10-06` — the composer's context wheel, from a keyboard.

`B892` moved the context wheel into the composer (`#chat-context-pill`, a real
`<button>` in `.chat-input-right`), so the composer surface this row checked on
2026-09-18 gained a popup. **Measured 2026-09-27 in Chromium against the
running app**, three defects in the way the panel opened and closed, all in
`_openContextPanel` (`static/js/chat.js`):

  1. **Closed from the wheel and opened again, a click inside the new panel
     closed it.** The panel put a `pointerdown` and a capture-phase `keydown`
     listener on `document` and took them off only from inside its own
     handler; closing it any other way — the wheel, a re-render, Compact —
     left them there, and the old one fired on the next click anywhere,
     inside the new panel included.
  2. **One Escape closed two things.** With the docked Notes pane open, Escape
     closed the panel and Notes with it: the arbiter in `ui.js` closes exactly
     one thing per press by asking `escMenuStack.js` first, and the panel had
     never registered there, so the arbiter let the key through.
  3. **Opened with Enter, it left the focus on the wheel**, six Tab presses —
     Agent, Chat, Send, the scroll button, a toast — from its first row,
     because it is appended to the end of `<body>`.

The Escape-and-return half of the integrator's question held already (Escape
from inside a first-opened panel closed it and focused the wheel); it broke
only after (1) had left a stale listener behind. The fix is to use the one
popup registry every other `<body>` popup uses, `bindMenuDismiss`, which
`tests/test_a_menu_opened_from_the_keyboard_is_operable_js.py` pins on its own.

Driven here under node: the panel functions are cut out of the real
`chat.js` with `tests/helpers/js_source.js_definition` and run against the real
`contextUsage.js` and `escMenuStack.js`, over the DOM shim of
`tests/test_tool_effect_surfaces_js.py` with focus, `contains`, `isConnected`
and `:focus-visible` patched in this sandbox only.
"""

import json
import shutil
from pathlib import Path

import pytest

from tests.helpers.js_source import js_definition
from tests.helpers.source_text import blank_text
from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"
CHAT_JS = JS / "chat.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_PANEL_FUNCTIONS = (
    "_contextColorClass", "_returnContextMeterHome", "_closeContextHeaderPopup",
    "_positionContextHeaderPopup", "_showContextHeaderPopup", "_openContextPanel",
)

# What `GET /api/session/{id}/context` returned for the chat the measurement
# used: one category with parts, so the panel has a `<summary>` row, and
# `can_compact`, so it has a Compact button after it.
_DATA = {
    "model": "local/model", "messages": 6, "context_length": 128000,
    "used_tokens": 1338, "context_percent": 1.0, "can_compact": True,
    "auto_compact_threshold": 85,
    "breakdown": {
        "source": "history", "used_tokens": 1338, "context_percent": 1.0, "uncounted": [],
        "categories": [
            {"key": "conversation", "label": "Conversation", "tokens": 1338, "measured": True,
             "items": [{"name": "Your messages", "count": 3, "tokens": 507},
                       {"name": "Replies and tool calls", "count": 3, "tokens": 831}]},
        ],
    },
}


def _panel_code() -> str:
    src = CHAT_JS.read_text(encoding="utf-8")
    code = blank_text(src, "js")
    return "\n".join(js_definition(src, code.index(f"function {name}("))
                     for name in _PANEL_FUNCTIONS)


_SHIM = r"""
import { installDom, Node } from './dom.js';
export const document = installDom();
export { Node };

Node.prototype.focus = function () { document.activeElement = this; this.focused = true; };
Node.prototype.contains = function (n) {
  for (let x = n; x; x = x.parentNode) if (x === this) return true;
  return false;
};
Object.defineProperty(Node.prototype, 'isConnected', {
  get() { let n = this; while (n.parentNode) n = n.parentNode; return n === document; },
});
const _matches = Node.prototype.matches;
Node.prototype.matches = function (sel) {
  if (sel === ':focus-visible') return document.activeElement === this && this._fv === true;
  return _matches.call(this, sel);
};
globalThis.innerHeight = 900;
globalThis.innerWidth = 1400;

export const pill = document.body.appendChild(new Node('button'));
pill.setAttribute('id', 'chat-context-pill');
pill.setAttribute('aria-expanded', 'false');
const home = document.body.appendChild(new Node('div'));
home.setAttribute('id', 'context-meter-home');
export const meter = home.appendChild(new Node('div'));
meter.setAttribute('id', 'context-meter');
export const notes = document.body.appendChild(new Node('div'));
notes.className = 'notes-pane';

export function tick() { return new Promise((r) => setTimeout(r, 5)); }
export function panels() { return document.querySelectorAll('.chat-context-popup'); }
export function focusPill(keyboard) { pill._fv = !!keyboard; pill.focus(); }
/** A mouse click on `target`, the way a browser delivers one to document. */
export function clickOn(target) {
  for (const type of ['pointerdown', 'mousedown', 'click']) {
    for (const fn of (document.listeners[type] || []).slice()) fn({ type, target });
  }
}
export function describeFocus() {
  const a = document.activeElement;
  if (!a) return null;
  if (a === pill) return 'pill';
  return a.tagName.toLowerCase() + ':' + (a.textContent || '').trim().slice(0, 20);
}
"""


def _preamble() -> str:
    return (
        "import { document, Node, pill, meter, notes, tick, panels, focusPill, clickOn,"
        " describeFocus } from './shim.js';\n"
        "import * as contextUsage from './contextUsage.js';\n"
        "import { bindMenuDismiss, dismissOrRemove, dismissTopMenu, _openMenuCount }"
        " from './escMenuStack.js';\n"
        "const fileHandlerModule = { getPendingInfo: () => [] };\n"
        "const spinnerModule = { createWhirlpool: () => ({ element: new Node('span') }) };\n"
        "async function compactCurrentChatContext() { return true; }\n"
        f"let _contextHeaderData = {json.dumps(_DATA)};\n"
        + _panel_code() + "\n"
    )


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    d = _make_sandbox(tmp_path_factory.mktemp("ctxpanelkeys"), JS / "contextUsage.js", _SHIM, {})
    shutil.copy(JS / "escMenuStack.js", d / "escMenuStack.js")
    return d


def _drive(script: str, sandbox: Path) -> dict:
    return _run(sandbox, _preamble(), script)


def test_opened_from_the_keyboard_the_first_row_has_the_focus(sandbox):
    out = _drive(
        """
        focusPill(true);
        _showContextHeaderPopup();
        await tick();
        console.log(JSON.stringify({
          open: panels().length, expanded: pill.getAttribute('aria-expanded'),
          focused: describeFocus(),
        }));
        """,
        sandbox,
    )
    assert out["open"] == 1 and out["expanded"] == "true"
    assert out["focused"] == "summary:Conversation1.3K1.0%", (
        f"Enter on the wheel left the focus on {out['focused']!r}; the panel "
        "hangs off the end of <body>, six Tab presses from the wheel"
    )


def test_one_escape_closes_the_panel_and_nothing_else(sandbox):
    """The arbiter in `ui.js` asks `dismissTopMenu()` first and stops the key
    when it answers true. False meant the key went on to the docked Notes
    pane's own listener, which closed Notes too."""
    out = _drive(
        """
        focusPill(true);
        _showContextHeaderPopup();
        await tick();
        const handled = dismissTopMenu();
        console.log(JSON.stringify({
          handled, open: panels().length, left: _openMenuCount(),
          focused: describeFocus(), expanded: pill.getAttribute('aria-expanded'),
          meterHome: meter.parentNode && meter.parentNode.id,
        }));
        """,
        sandbox,
    )
    assert out["handled"] is True, (
        "the panel is not on the Escape stack, so the arbiter lets the key "
        "through to the next listener — measured closing the Notes pane with it"
    )
    assert out["open"] == 0 and out["left"] == 0
    assert out["focused"] == "pill", out["focused"]
    assert out["expanded"] == "false"
    assert out["meterHome"] == "context-meter-home", (
        "the allowance meter the panel adopts was not handed back to its home"
    )


def test_a_click_inside_a_reopened_panel_does_not_close_it(sandbox):
    """Closed from the wheel and opened again: the first panel's listener must
    have gone with it, or the next click anywhere — inside the second panel
    included — closes the second panel."""
    out = _drive(
        """
        focusPill(false);
        _showContextHeaderPopup();          // open
        await tick();
        _showContextHeaderPopup();          // the wheel again: close
        await tick();
        _showContextHeaderPopup();          // and open
        await tick();
        const row = panels()[0].querySelector('summary');
        clickOn(row);
        await tick();
        console.log(JSON.stringify({ open: panels().length, left: _openMenuCount() }));
        """,
        sandbox,
    )
    assert out["open"] == 1, (
        "a click on a row inside the reopened panel closed it: a listener from "
        "the first opening was still on the document"
    )
    assert out["left"] == 1, f"the Escape stack holds {out['left']} entries for one panel"


def test_a_click_outside_still_closes_it_and_the_wheel_is_not_outside(sandbox):
    out = _drive(
        """
        focusPill(false);
        _showContextHeaderPopup();
        await tick();
        clickOn(pill);
        const afterWheelClick = panels().length;
        clickOn(notes);
        console.log(JSON.stringify({
          afterWheelClick, afterOutside: panels().length, left: _openMenuCount(),
        }));
        """,
        sandbox,
    )
    assert out["afterWheelClick"] == 1, (
        "a click on the wheel counted as outside; the wheel's own handler "
        "toggles the panel, and closing it first would reopen it"
    )
    assert out["afterOutside"] == 0 and out["left"] == 0


def test_opened_with_the_mouse_the_focus_stays_where_it_was(sandbox):
    out = _drive(
        """
        focusPill(false);
        _showContextHeaderPopup();
        await tick();
        console.log(JSON.stringify({ focused: describeFocus() }));
        """,
        sandbox,
    )
    assert out["focused"] == "pill"


def test_a_redraw_while_open_keeps_one_panel_and_one_stack_entry(sandbox):
    """`refreshChatContextHeader` and the attachment sync redraw an open panel
    by closing and reopening it; neither may leave the old one's entry."""
    out = _drive(
        """
        focusPill(true);
        _showContextHeaderPopup();
        await tick();
        _closeContextHeaderPopup();
        _openContextPanel(pill);
        await tick();
        console.log(JSON.stringify({
          open: panels().length, left: _openMenuCount(), focused: describeFocus(),
        }));
        """,
        sandbox,
    )
    assert out["open"] == 1 and out["left"] == 1, out
    assert out["focused"] == "summary:Conversation1.3K1.0%", out["focused"]
