# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B-NEW` (f-import) — for 350 ms after the email Send caret toggles its menu,
only the caret's own trailing click is cancelled.

``handleCaretIntent`` (``static/js/document.js``) toggles the send-options menu
on ``pointerdown``; a cancelled ``pointerdown`` suppresses the ``mousedown``
that follows but not the ``click``, so the handler swallows a ``click`` that
lands within 350 ms of a toggle. It did that by time alone, before asking
whether the click was on the caret: driven under node with the shipped handler
on the tree before this row, a click at (10, 10) straight after a toggle came
back cancelled — and so did a click on the menu item the toggle had just shown.

The page's two capture-phase handlers and the hit test they share are cut out
of ``document.js`` with ``js_source`` and run under node as they ship, in the
`B400` page (``tests/test_a_file_imported_from_device_opens_readable.py``):
what is asserted is whether each event came back cancelled and what the menu
did (`Law 20`). The clock is the page's ``Date.now``, stepped by the case.
"""
import shutil

import pytest

from tests.helpers.js_source import js_binding
from tests.test_a_file_imported_from_device_opens_readable import DOCJS, _PAGE, _run_js

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_CAPTURE = "\n".join(js_binding(DOCJS, n) for n in (
    "_eventInsideElement", "handleSendIntent", "lastCaretToggleAt", "toggleSendMenu",
    "handleCaretIntent"))

# The email footer is showing: Send at (900, 820), the caret beside it, and the
# menu the caret opens above them, with one item in it.
_SCENE = r"""
let clock = 10000;
Date.now = () => clock;
sendBtn.r = rect(900, 820, 80, 30);
caret.r = rect(980, 820, 24, 30);
const menuItem = { nodeType: 1, closest: () => null };
const onCaret = { nodeType: 1, closest: (sel) => sel === '#doc-email-send-caret' ? caret : null };
const elsewhere = { nodeType: 1, closest: () => null };
/** One event of `type` at (x, y) on `target`, through both capture handlers. */
const fire = (type, target, x, y) => {
  const e = { type, target, clientX: x, clientY: y, defaultPrevented: false,
              preventDefault() { this.defaultPrevented = true; }, stopPropagation() {} };
  handleSendIntent(e);
  handleCaretIntent(e);
  return e.defaultPrevented;
};
/** A person presses the caret: pointerdown toggles; its click trails it. */
const pressCaret = () => {
  const down = fire('pointerdown', onCaret, 990, 835);
  clock += 90;
  const click = fire('click', onCaret, 990, 835);
  return { down, click, menu: moreMenu.style.display };
};
"""


def _page(tmp_path, body: str) -> dict:
    return _run_js(tmp_path / "caret", _PAGE + _CAPTURE + _SCENE + body)


def test_a_click_elsewhere_just_after_a_toggle_is_not_cancelled(tmp_path):
    out = _page(tmp_path, """
        const opened = pressCaret();
        clock += 60;            // 150 ms after the toggle
        const away = fire('click', elsewhere, 10, 10);
        console.log(JSON.stringify({ opened, away, sent: sentEmail.length }));
    """)
    assert out["opened"] == {"down": True, "click": True, "menu": ""}
    assert out["away"] is False
    assert out["sent"] == 0


def test_the_menu_item_the_toggle_showed_can_be_clicked_at_once(tmp_path):
    out = _page(tmp_path, """
        pressCaret();
        clock += 40;            // 130 ms after the toggle, on the menu
        const down = fire('pointerdown', menuItem, 985, 780);
        const click = fire('click', menuItem, 985, 780);
        console.log(JSON.stringify({ down, click, menu: moreMenu.style.display }));
    """)
    assert out == {"down": False, "click": False, "menu": ""}


def test_the_carets_own_trailing_click_is_still_swallowed(tmp_path):
    """What the window is for: without it the trailing click toggles the menu
    shut again the instant it opened."""
    out = _page(tmp_path, """
        const first = pressCaret();
        clock += 1000;
        const second = pressCaret();
        console.log(JSON.stringify({ first, second }));
    """)
    assert out["first"] == {"down": True, "click": True, "menu": ""}
    assert out["second"] == {"down": True, "click": True, "menu": "none"}


def test_a_click_on_the_caret_after_the_window_toggles_it(tmp_path):
    """A keyboard press on the caret is a `click` with no `pointerdown`, and a
    browser reports it at (0, 0): the caret is found by its target."""
    out = _page(tmp_path, """
        pressCaret();
        clock += 400;
        const click = fire('click', onCaret, 0, 0);
        console.log(JSON.stringify({ click, menu: moreMenu.style.display }));
    """)
    assert out == {"click": True, "menu": "none"}


def test_send_inside_the_window_still_sends(tmp_path):
    out = _page(tmp_path, """
        pressCaret();
        clock += 50;
        const sent = fire('click', elsewhere, 930, 835);
        console.log(JSON.stringify({ sent, n: sentEmail.length }));
    """)
    assert out == {"sent": True, "n": 1}
