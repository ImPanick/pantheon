# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P10-06` — a menu opened from the keyboard can be used from the keyboard.

**Measured 2026-09-27 in Chromium, against the running app, before a line
changed.** The Workshop's two kebabs — a skill's in the Brain window and a
task's in the Tasks window — open their menus on Enter, and then nothing: the
focus stays on the kebab, the menu is appended to the end of `<body>`, and Tab
walks to the next card's controls and out of the window. No item was reached
in any number of presses, so a task's Run now, Edit, History and Delete, and a
skill's Publish, Edit, Test and Delete, had no keyboard path at all. The
previous pass called the Workshop clean because `skills.js` and `memory.js`
put no `onclick` on a `<div>`; the menus were never opened by a keyboard.

Every such menu already calls `bindMenuDismiss` (`static/js/escMenuStack.js`,
29 call sites in 14 modules), so that is where this is fixed, once (`Law 14`).
Driven here under node against the real module, in the sandbox pattern
`tests/test_tool_effect_surfaces_js.py` owns. The shared DOM shim does not
track `document.activeElement`, `contains`, `isConnected` or `:focus-visible`;
they are patched on the prototype in THIS sandbox only, the way
`tests/test_the_resize_handles_take_a_keyboard.py` patches geometry, because a
change to the instrument is a change to every other test that uses it.

What is pinned, and why each is a defect if it breaks:

  * **the first item takes the focus** when the menu was opened from the
    keyboard — without it the menu is unreachable, which is the measurement;
  * **the arrows walk the items and wrap, Home/End jump**, and a hidden or
    disabled item is never landed on (`.dropdown-cancel-mobile` is hidden on
    desktop in every one of these menus);
  * **every way of closing gives the focus back to the button** — Escape
    through the arbiter's `dismissTopMenu()`, an item, and Tab, which must
    NOT be prevented so the browser carries on from the button;
  * **a menu opened with the mouse is left exactly as it was**: no focus moved,
    no key bound, nothing given back. A clicked button is focused but not
    `:focus-visible`, which is the whole test for "opened from the keyboard";
  * **a text field is never an opener** — it is always `:focus-visible`, and a
    search dropdown must keep the focus in its input;
  * **the focus is never taken back from somewhere the person moved it**, and
    never handed to a button that is no longer in the page.
"""

import shutil
from pathlib import Path

import pytest

from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
ESC_STACK = ROOT / "static" / "js" / "escMenuStack.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_SHIM = r"""
import { installDom, Node } from './dom.js';
export const document = installDom();
export { Node };

// What the browser has and the shared shim does not, patched HERE (see the
// module docstring). `_fv` is how a node was focused: true for the keyboard,
// false for a mouse click — Chromium's own `:focus-visible` heuristic.
Node.prototype.focus = function () {
  document.activeElement = this;
  this.focused = true;
  this.focusCalls = (this.focusCalls || 0) + 1;
};
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

export function tick() { return new Promise((r) => setTimeout(r, 5)); }

/** A kebab button and a menu of `labels`, appended to <body> like the real ones. */
export function build(labels, { hidden = [], disabled = [] } = {}) {
  const host = document.body.appendChild(new Node('div'));
  const opener = host.appendChild(new Node('button'));
  opener.className = 'kebab';
  const after = host.appendChild(new Node('button'));
  after.className = 'after';
  const menu = new Node('div');
  menu.className = 'menu';
  const items = labels.map((label) => {
    const b = menu.appendChild(new Node('button'));
    b.textContent = label;
    if (hidden.includes(label)) b.style.display = 'none';
    if (disabled.includes(label)) b.disabled = true;
    return b;
  });
  return { opener, after, menu, items };
}

export function focusFrom(node, keyboard) { node._fv = !!keyboard; node.focus(); }

export function press(menu, key, target, opts = {}) {
  let prevented = !!opts.alreadyPrevented;
  menu.dispatchEvent({
    type: 'keydown', key, target: target || document.activeElement,
    get defaultPrevented() { return prevented; },
    preventDefault() { prevented = true; },
  });
  return prevented;
}

export function label(n) { return n && n.textContent ? n.textContent : (n ? n.className : null); }
"""

_PREAMBLE = (
    "import { document, Node, tick, build, focusFrom, press, label } from './shim.js';\n"
    "const { bindMenuDismiss, dismissTopMenu, _openMenuCount } = await import('./escMenuStack.js');\n"
    "function openMenu(m, onClose) {\n"
    "  document.body.appendChild(m.menu);\n"
    "  return bindMenuDismiss(m.menu, onClose || (() => m.menu.remove()));\n"
    "}\n"
)


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    return _make_sandbox(tmp_path_factory.mktemp("kbdmenu"), ESC_STACK, _SHIM, {})


def _drive(script: str, sandbox: Path) -> dict:
    return _run(sandbox, _PREAMBLE, script)


def test_a_keyboard_opened_menu_hands_its_first_item_the_focus(sandbox):
    out = _drive(
        """
        const m = build(['Run now', 'Edit', 'Delete']);
        focusFrom(m.opener, true);
        openMenu(m);
        await tick();
        console.log(JSON.stringify({ focused: label(document.activeElement) }));
        """,
        sandbox,
    )
    assert out["focused"] == "Run now", (
        "a menu opened with Enter left the focus on the button that opened it "
        f"({out['focused']!r}); appended to <body>, the menu is then unreachable "
        "by Tab — the measured defect"
    )


def test_the_arrows_walk_the_items_wrap_and_skip_what_cannot_be_used(sandbox):
    out = _drive(
        """
        const m = build(['Run now', 'Edit', 'Cancel', 'Busy', 'Delete'],
                        { hidden: ['Cancel'], disabled: ['Busy'] });
        focusFrom(m.opener, true);
        openMenu(m);
        await tick();
        const walk = [];
        for (const key of ['ArrowDown', 'ArrowDown', 'ArrowDown', 'ArrowUp', 'ArrowUp', 'End', 'Home']) {
          const prevented = press(m.menu, key);
          walk.push([key, label(document.activeElement), prevented]);
        }
        console.log(JSON.stringify({ walk }));
        """,
        sandbox,
    )
    assert out["walk"] == [
        ["ArrowDown", "Edit", True],
        ["ArrowDown", "Delete", True],
        ["ArrowDown", "Run now", True],
        ["ArrowUp", "Delete", True],
        ["ArrowUp", "Edit", True],
        ["End", "Delete", True],
        ["Home", "Run now", True],
    ], out["walk"]


def test_escape_through_the_arbiter_gives_the_focus_back(sandbox):
    """The arbiter in `ui.js` closes a menu by calling `dismissTopMenu()`; this
    is that call, and the focus has to land where the menu was opened from."""
    out = _drive(
        """
        const m = build(['Run now', 'Edit']);
        focusFrom(m.opener, true);
        openMenu(m);
        await tick();
        press(m.menu, 'ArrowDown');
        const handled = dismissTopMenu();
        console.log(JSON.stringify({
          handled, left: _openMenuCount(), inPage: m.menu.isConnected,
          focused: label(document.activeElement),
        }));
        """,
        sandbox,
    )
    assert out["handled"] is True and out["left"] == 0 and out["inPage"] is False
    assert out["focused"] == "kebab", (
        f"Escape closed the menu and left the focus on {out['focused']!r}; a "
        "focused node that is removed drops the focus to <body>, and the next "
        "Tab starts from the top of the page"
    )


def test_tab_inside_the_menu_is_the_browsers_own(sandbox):
    """The context panel is a popup with several controls in it, not only a
    list of commands; Tab between them has to work the way it does anywhere."""
    out = _drive(
        """
        const m = build(['Run now', 'Edit', 'Delete']);
        focusFrom(m.opener, true);
        let closed = 0;
        openMenu(m, () => { closed++; m.menu.remove(); });
        await tick();
        const prevented = press(m.menu, 'Tab');                   // on the first of three
        m.items[1].focus();
        const againPrevented = press(m.menu, 'Tab');              // on the middle one
        console.log(JSON.stringify({ closed, prevented, againPrevented, open: m.menu.isConnected }));
        """,
        sandbox,
    )
    assert out == {"closed": 0, "prevented": False, "againPrevented": False, "open": True}, out


def test_tab_past_the_last_item_closes_and_carries_on_from_the_button(sandbox):
    out = _drive(
        """
        const m = build(['Run now', 'Edit']);
        focusFrom(m.opener, true);
        let closed = 0;
        openMenu(m, () => { closed++; m.menu.remove(); });
        await tick();
        press(m.menu, 'End');
        const prevented = press(m.menu, 'Tab');
        console.log(JSON.stringify({
          closed, prevented, focused: label(document.activeElement), left: _openMenuCount(),
        }));
        """,
        sandbox,
    )
    assert out["closed"] == 1 and out["left"] == 0
    assert out["focused"] == "kebab"
    assert out["prevented"] is False, (
        "Tab was prevented; the browser then moves nowhere and the person is "
        "left on the button with the menu gone, pressing Tab twice to move on"
    )


def test_shift_tab_before_the_first_item_closes_onto_the_button(sandbox):
    """The menu sits after its button in the order a person expects, so
    stepping back out of it lands on the button — not on whatever is before
    the button, which is where the browser would go from there."""
    out = _drive(
        """
        const m = build(['Run now', 'Edit']);
        focusFrom(m.opener, true);
        openMenu(m);
        await tick();
        let prevented = false;
        m.menu.dispatchEvent({
          type: 'keydown', key: 'Tab', shiftKey: true, target: document.activeElement,
          get defaultPrevented() { return prevented; }, preventDefault() { prevented = true; },
        });
        console.log(JSON.stringify({
          prevented, focused: label(document.activeElement), left: _openMenuCount(),
        }));
        """,
        sandbox,
    )
    assert out == {"prevented": True, "focused": "kebab", "left": 0}, out


def test_an_item_that_closes_the_menu_gives_the_focus_back_too(sandbox):
    """The real items call `close()` then their action — `tasks.js` and
    `skills.js` both do — so a person who picks one lands back on the kebab
    rather than on <body>."""
    out = _drive(
        """
        const m = build(['Run now', 'Edit']);
        focusFrom(m.opener, true);
        const close = openMenu(m);
        await tick();
        press(m.menu, 'ArrowDown');
        close();
        console.log(JSON.stringify({ focused: label(document.activeElement) }));
        """,
        sandbox,
    )
    assert out["focused"] == "kebab"


def test_a_menu_opened_with_the_mouse_is_left_exactly_as_it_was(sandbox):
    out = _drive(
        """
        const m = build(['Run now', 'Edit']);
        focusFrom(m.opener, false);           // a clicked button: focused, not :focus-visible
        const close = openMenu(m);
        await tick();
        const afterOpen = label(document.activeElement);
        const prevented = press(m.menu, 'ArrowDown', m.items[0]);
        const afterArrow = label(document.activeElement);
        close();
        console.log(JSON.stringify({
          afterOpen, prevented, afterArrow,
          openerFocusCalls: m.opener.focusCalls, itemFocusCalls: m.items[0].focusCalls || 0,
          keyListeners: (m.menu.listeners.keydown || []).length,
        }));
        """,
        sandbox,
    )
    assert out["afterOpen"] == "kebab" and out["itemFocusCalls"] == 0, (
        "a mouse-opened menu moved the focus; the change is for keyboard "
        "openers only, and a mouse user's flow must not move"
    )
    assert out["prevented"] is False and out["keyListeners"] == 0
    assert out["openerFocusCalls"] == 1, (
        "closing a mouse-opened menu focused the button again — nothing was "
        "taken from it, so nothing is given back"
    )


def test_a_text_field_is_never_the_opener(sandbox):
    """A search box with a results dropdown: the input is `:focus-visible`
    whatever opened it, and the person is typing in it."""
    out = _drive(
        """
        const host = document.body.appendChild(new Node('div'));
        const input = host.appendChild(new Node('input'));
        input.type = 'search';
        const menu = new Node('div');
        const row = menu.appendChild(new Node('button'));
        row.textContent = 'a result';
        focusFrom(input, true);
        document.body.appendChild(menu);
        bindMenuDismiss(menu, () => menu.remove());
        await tick();
        console.log(JSON.stringify({ focused: document.activeElement === input }));
        """,
        sandbox,
    )
    assert out["focused"] is True, "the dropdown took the focus out of the field being typed in"


def test_the_focus_is_not_taken_back_from_where_the_person_moved_it(sandbox):
    """An outside click that closes the menu has already put the focus where
    the person clicked; giving it to the kebab then would steal it."""
    out = _drive(
        """
        const m = build(['Run now', 'Edit']);
        focusFrom(m.opener, true);
        const close = openMenu(m);
        await tick();
        focusFrom(m.after, false);           // the person clicked something else
        close();
        console.log(JSON.stringify({ focused: label(document.activeElement) }));
        """,
        sandbox,
    )
    assert out["focused"] == "after"


def test_a_button_that_left_the_page_is_not_given_the_focus(sandbox):
    """Delete on a task re-renders the list and the kebab goes with it."""
    out = _drive(
        """
        const m = build(['Delete']);
        focusFrom(m.opener, true);
        const close = openMenu(m);
        await tick();
        m.opener.remove();
        const before = m.opener.focusCalls;
        close();
        console.log(JSON.stringify({ calls: m.opener.focusCalls - before }));
        """,
        sandbox,
    )
    assert out["calls"] == 0


def test_a_key_the_menu_already_answered_is_left_alone(sandbox):
    """A menu with its own arrow handling (an emoji grid, a list with a filter)
    calls `preventDefault`; the generic walk must not move the focus a second
    time on the same press."""
    out = _drive(
        """
        const m = build(['a', 'b', 'c']);
        focusFrom(m.opener, true);
        openMenu(m);
        await tick();
        press(m.menu, 'ArrowDown', null, { alreadyPrevented: true });
        console.log(JSON.stringify({ focused: label(document.activeElement) }));
        """,
        sandbox,
    )
    assert out["focused"] == "a"
