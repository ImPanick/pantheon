# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B-NEW-10` — the window's move chip shows for a keyboard, not after a click.

A tool window's header holds a move handle (`windowDrag.js`, `P10-06`) that
draws *Move: arrow keys · Resize: Shift + arrows* over the title bar whenever
it has the focus — `style.css` uses `:focus` on purpose, "nothing but a
keyboard can focus it". `P23-01` made two more things focus it: a window
re-raised when the one opened from it closes (`backStack.js`), and a window
restored from its dock chip (`modalManager.js`). Measured on `a936b5c` and
again on `cdf040f` in Chromium at 1440×900: after a click on `← Brain`, after
the browser's Back, and after a click on the Brain's dock chip, the chip sat
on the Brain's title bar (`focusOnHandle: true, chipShown: true`).

The rule now (`modalManager.focusWindowHandle`, which the back stack's re-raise
calls through its `focusWindow` hook): focus the handle, and ask the browser
whether that focus is a keyboard's — `:focus-visible`, its own reading of the
last input. If not, or if the handle is not drawn (phone width), the window's
content takes the focus (`tabindex="-1"`): the focus is still in the window,
and no chip.

Driven here, not read (`Law 20`): the real `modalManager.js` and the real
`backStack.js` under node in the dock sandbox (`tests/test_the_dock_chip_and_the_way_back_js.py`'s,
imported). What stands in for the browser is the answer to `:focus-visible`,
per case: a keyboard's focus, or a pointer's.
"""

import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_background_work_dock_js import MODALS_JS, _STUBS  # noqa: E402
from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402
from test_the_dock_chip_and_the_way_back_js import _SHIM, _PREAMBLE  # noqa: E402

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_HELPERS = r"""
/** The browser's answer to `:focus-visible` for this handle: `true` after a
 *  key, `false` after a pointer. */
const input = (w, keyboard) => {
  const own = Node.prototype.matches;
  w.handle.matches = function (sel) { return sel === ':focus-visible' ? keyboard : own.call(this, sel); };
};
const where = (w) => {
  const a = document.activeElement;
  const content = w.modal.querySelector('.modal-content');
  return { handle: a === w.handle, content: a === content, tabindex: content.getAttribute('tabindex') };
};
"""


@pytest.fixture(scope="module")
def mm(tmp_path_factory):
    return _make_sandbox(tmp_path_factory.mktemp("movechip"), MODALS_JS, _SHIM, _STUBS)


def _case(sandbox, script):
    return _run(sandbox, _PREAMBLE + _HELPERS, script)


def test_restoring_from_the_chip_with_the_mouse_focuses_the_window_not_the_handle(mm):
    o = _case(mm, """
        const t = makeWindow('tasks-modal', 'Tasks');
        Modals.register('tasks-modal', { closeFn: () => {} });
        Modals.minimize('tasks-modal');
        document.activeElement = document.body;
        input(t, false);
        press(document.querySelector('.minimized-dock-restore'));
        out(where(t));
    """)
    assert o == {"handle": False, "content": True, "tabindex": "-1"}


def test_restoring_from_the_chip_with_the_keyboard_focuses_the_handle(mm):
    o = _case(mm, """
        const t = makeWindow('tasks-modal', 'Tasks');
        Modals.register('tasks-modal', { closeFn: () => {} });
        Modals.minimize('tasks-modal');
        document.activeElement = document.body;
        input(t, true);
        press(document.querySelector('.minimized-dock-restore'));
        out(where(t));
    """)
    assert o == {"handle": True, "content": False, "tabindex": None}


@pytest.mark.parametrize("keyboard", [False, True], ids=["pointer", "keyboard"])
def test_the_opener_re_raised_by_the_back_stack_takes_the_focus_the_input_says(mm, keyboard):
    """`P23-00`'s first sentence: Brain → Skills shows `← Brain`; closing Skills
    re-raises the Brain. After a click on `←` (or the browser's Back) the
    Brain's content has the focus; after Escape, its handle."""
    o = _case(mm, f"""
        const brain = makeWindow('memory-modal', 'Brain');
        const skills = makeWindow('skills-modal', 'Skills');
        backStack.sync();
        Modals.showWindow('skills-modal', {{ from: 'memory-modal', tab: 'rag' }});
        input(brain, {str(keyboard).lower()});
        document.activeElement = document.body;
        click(skills.header.querySelector('.modal-back-btn'));
        backStack.sync();                       // the back stack sees Skills go
        out(where(brain));
    """)
    if keyboard:
        assert o == {"handle": True, "content": False, "tabindex": None}
    else:
        assert o == {"handle": False, "content": True, "tabindex": "-1"}


def test_a_handle_the_phone_layout_does_not_draw_leaves_the_focus_in_the_window(mm):
    """At 390×844 the handle is `display: none` and cannot take the focus; the
    window does, whatever the input."""
    o = _case(mm, """
        const t = makeWindow('tasks-modal', 'Tasks');
        Modals.register('tasks-modal', { closeFn: () => {} });
        Modals.minimize('tasks-modal');
        document.activeElement = document.body;
        input(t, true);
        t.handle.focus = () => {};              // not focusable while not drawn
        press(document.querySelector('.minimized-dock-restore'));
        out(where(t));
    """)
    assert o == {"handle": False, "content": True, "tabindex": "-1"}
