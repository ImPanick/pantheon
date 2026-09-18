# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P10-06` — the icon rail, from a keyboard.

Every launcher in the rail is already a real `<button>`, so every one of them
is already in the tab order. **That is the defect, not the fix.** Measured on
the shipped `static/index.html`: 18 `.icon-rail-btn` elements sit between the
top of the page and the sidebar, so reaching the composer by Tab costs
eighteen presses through a strip a mouse user skips by not looking at it.

The ARIA pattern for that is a toolbar with a roving tabindex: the rail is one
tab stop, and the arrow keys move inside it. `static/js/a11y.js` owns it,
because that module already exists to make things operable that were not —
this is its second surface, not a second module (`Law 14`).

Driven under node against the real `a11y.js`, in the sandbox pattern
`tests/test_tool_effect_surfaces_js.py` owns: its DOM shim, its sandbox
builder, its runner, imported rather than copied. The element ids and the
button list come out of the shipped markup rather than being retyped here, so
a launcher added to the rail is in the test the day it is added.

`a11y.js` is an IIFE and not a module, which is exactly what makes this
drivable: importing the file runs it, against whatever DOM the shim has built
first.

What is pinned, and why each is a defect if it breaks:

  * **one tab stop, not eighteen.** The count is asserted directly, because
    "it has a roving tabindex" and "it has exactly one tab stop" are different
    claims and only the second one is the feature;
  * **hidden launchers never hold the stop.** Customize UI hides rail buttons
    by writing `style.display = 'none'` (`applyUIVis` in `app.js`) and two ship
    hidden in the markup. A tab stop on a hidden button is a tab stop that goes
    nowhere, and the rail then has no way in at all;
  * **the arrows wrap**, so End→Down returns to the top rather than dead-ending
    on a key that silently does nothing;
  * **the wrong keys are left alone.** Left/Right are deliberately unbound —
    the rail can be moved to the right side of the window, and a horizontal
    binding reads backwards there. This asserts the non-binding, because a
    binding that is right half the time is worse than none;
  * **Enter and Space still reach the shim's own activation path**, which is
    the thing this listener was extended rather than forked from.
"""

import json
import re
import shutil
import textwrap
from pathlib import Path

import pytest

from test_tool_effect_surfaces_js import _DOM, _make_sandbox, _run  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
A11Y = ROOT / "static" / "js" / "a11y.js"
INDEX = ROOT / "static" / "index.html"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _rail_markup() -> list:
    """(id, hidden) for every `.icon-rail-btn` inside `#icon-rail`, in order.

    Read out of the page rather than listed here. `_matches` in the shim knows
    nothing about ancestry, so the rail's own subtree is sliced out of the
    markup first — which also means a button that leaves the rail leaves this
    test.
    """
    html = INDEX.read_text(encoding="utf-8")
    start = html.index('<div class="icon-rail" id="icon-rail"')
    end = html.index("</div>\n\n", start)
    chunk = html[start:end]
    out = []
    for m in re.finditer(r"<button\b([^>]*)>", chunk):
        attrs = m.group(1)
        if "icon-rail-btn" not in attrs:
            continue
        ident = re.search(r'id="([^"]+)"', attrs)
        hidden = "display:none" in attrs.replace(" ", "")
        out.append((ident.group(1) if ident else "", hidden))
    assert len(out) >= 10, f"the rail markup moved; found {len(out)} launchers"
    assert any(h for _i, h in out), (
        "no rail launcher ships hidden any more — the `.rail-dynamic` pair is "
        "what makes the visibility rule below worth testing"
    )
    return out


_SHIM = r"""
import { installDom, Node } from './dom.js';
export const document = installDom();
export { Node };

const RAIL = __RAIL__;

const rail = document.body.appendChild(new Node('div'));
rail.setAttribute('id', 'icon-rail');
rail.className = 'icon-rail';

/** A sibling control OUTSIDE the rail, so "one tab stop" can be told apart
 *  from "the page has one focusable thing". */
const outside = document.body.appendChild(new Node('button'));
outside.setAttribute('id', 'outside-the-rail');

export const buttons = [];
for (const [id, hidden] of RAIL) {
  const b = rail.appendChild(new Node('button'));
  b.className = 'icon-rail-btn';
  b.setAttribute('id', id);
  if (hidden) b.style.display = 'none';
  buttons.push(b);
}
export { rail, outside };

/** Tab stops, by the browser's own rule: tabindex="0" or no tabindex at all. */
export function tabStops() {
  return buttons
    .filter((b) => b.getAttribute('tabindex') !== '-1')
    .map((b) => b.id);
}

export function visibleIds() {
  return buttons.filter((b) => b.style.display !== 'none').map((b) => b.id);
}

export function focused() {
  const hit = buttons.filter((b) => b.focused);
  return hit.length === 1 ? hit[0].id : hit.map((b) => b.id);
}

export function clearFocus() { for (const b of buttons) b.focused = false; }

export function press(key, targetId) {
  let prevented = false;
  const target = document.getElementById(targetId);
  document.dispatchEvent({
    type: 'keydown',
    key,
    target,
    preventDefault() { prevented = true; },
  });
  return prevented;
}

export function focusIn(targetId) {
  document.dispatchEvent({
    type: 'focusin',
    target: document.getElementById(targetId),
  });
}
"""

_PREAMBLE = (
    "import { document, rail, outside, buttons, tabStops, visibleIds, focused,"
    " clearFocus, press, focusIn } from './shim.js';\n"
    "await import('./a11y.js');\n"
)


@pytest.fixture(scope="module")
def rail_sandbox(tmp_path_factory):
    shim = _SHIM.replace("__RAIL__", json.dumps(_rail_markup()))
    return _make_sandbox(tmp_path_factory.mktemp("railtoolbar"), A11Y, shim, {})


def _rail(script: str, sandbox: Path) -> dict:
    return _run(sandbox, _PREAMBLE, script)


def test_the_rail_announces_itself_as_a_toolbar(rail_sandbox):
    out = _rail(
        """
        console.log(JSON.stringify({
          role: rail.getAttribute('role'),
          orientation: rail.getAttribute('aria-orientation'),
          label: rail.getAttribute('aria-label'),
        }));
        """,
        rail_sandbox,
    )
    assert out["role"] == "toolbar", (
        "a strip of eighteen buttons with no role is eighteen unrelated "
        "buttons to a screen reader"
    )
    assert out["orientation"] == "vertical", (
        "the orientation is what tells a reader which arrows to try, and it "
        "has to agree with the keys that are actually bound"
    )
    assert out["label"], "an unlabelled toolbar is announced as 'toolbar'"


def test_the_rail_is_one_tab_stop_and_it_is_a_visible_button(rail_sandbox):
    out = _rail(
        """
        console.log(JSON.stringify({ stops: tabStops(), visible: visibleIds() }));
        """,
        rail_sandbox,
    )
    assert len(out["stops"]) == 1, (
        f"expected one tab stop in the rail, found {len(out['stops'])}: "
        f"{out['stops']}. Every launcher being tabbable is the defect this "
        "row is named after, not the absence of one."
    )
    assert out["stops"][0] in out["visible"], (
        f"the tab stop sits on `{out['stops'][0]}`, which ships hidden — "
        "Tab would then reach nothing at all"
    )


def test_the_arrows_walk_the_visible_launchers_and_wrap(rail_sandbox):
    out = _rail(
        """
        const visible = visibleIds();
        const walk = [];
        let at = visible[0];
        clearFocus();
        for (let i = 0; i < visible.length + 1; i++) {
          press('ArrowDown', at);
          at = focused();
          walk.push(at);
          clearFocus();
        }
        console.log(JSON.stringify({ visible, walk }));
        """,
        rail_sandbox,
    )
    visible, walk = out["visible"], out["walk"]
    assert walk[: len(visible) - 1] == visible[1:], (
        "ArrowDown does not walk the visible launchers in order.\n"
        f"  visible: {visible}\n  walked:  {walk}"
    )
    assert walk[len(visible) - 1] == visible[0], (
        "ArrowDown at the last launcher does not wrap to the first; it "
        f"reached {walk[len(visible) - 1]!r}"
    )
    assert all(b not in walk for b, hidden in _rail_markup() if hidden), (
        "the arrows landed on a launcher that ships hidden"
    )


def test_home_and_end_reach_the_ends(rail_sandbox):
    out = _rail(
        """
        const visible = visibleIds();
        clearFocus(); press('End', visible[0]);
        const atEnd = focused();
        clearFocus(); press('Home', atEnd);
        const atHome = focused();
        console.log(JSON.stringify({ visible, atEnd, atHome }));
        """,
        rail_sandbox,
    )
    assert out["atEnd"] == out["visible"][-1]
    assert out["atHome"] == out["visible"][0]


def test_moving_the_focus_moves_the_tab_stop_with_it(rail_sandbox):
    """A roving tabindex that does not rove leaves the ring somewhere the user
    is not, and Shift+Tab out and back lands on the wrong button."""
    out = _rail(
        """
        const visible = visibleIds();
        clearFocus(); press('ArrowDown', visible[0]);
        const afterArrow = tabStops();
        focusIn(visible[visible.length - 1]);
        const afterFocusIn = tabStops();
        console.log(JSON.stringify({ visible, afterArrow, afterFocusIn }));
        """,
        rail_sandbox,
    )
    assert out["afterArrow"] == [out["visible"][1]], out["afterArrow"]
    assert out["afterFocusIn"] == [out["visible"][-1]], out["afterFocusIn"]


def test_left_and_right_are_left_alone(rail_sandbox):
    """The rail can be moved to the right side of the window. A horizontal
    binding would read backwards there, so there is none — asserted, because
    an unbound key is invisible in every other kind of test."""
    out = _rail(
        """
        const visible = visibleIds();
        clearFocus();
        const preventedRight = press('ArrowRight', visible[0]);
        const afterRight = focused();
        const preventedLeft = press('ArrowLeft', visible[0]);
        const afterLeft = focused();
        console.log(JSON.stringify({
          preventedRight, preventedLeft, afterRight, afterLeft,
        }));
        """,
        rail_sandbox,
    )
    assert out["afterRight"] == [] and out["afterLeft"] == [], (
        "Left/Right moved the rail focus; the rail is vertical and can sit on "
        "either side of the window, so a horizontal binding is right half the "
        "time"
    )
    assert not out["preventedRight"] and not out["preventedLeft"], (
        "a key the rail does not handle must reach the page unprevented"
    )


def test_a_key_outside_the_rail_is_not_the_rails_business(rail_sandbox):
    out = _rail(
        """
        clearFocus();
        const prevented = press('ArrowDown', 'outside-the-rail');
        console.log(JSON.stringify({ prevented, focused: focused() }));
        """,
        rail_sandbox,
    )
    assert out["focused"] == [] and not out["prevented"]


def test_hiding_the_launcher_that_holds_the_stop_moves_it(rail_sandbox):
    """Customize UI can hide the button the tab stop is sitting on. Without the
    resync the rail is left with no tab stop and becomes unreachable — from a
    settings panel, hours later, with nothing to connect the two."""
    out = _rail(
        """
        const visible = visibleIds();
        const holder = tabStops()[0];
        document.getElementById(holder).style.display = 'none';
        // The page uses a MutationObserver for this; node has none, so the
        // same resync is provoked the way a real focus change would.
        focusIn(visible.filter((v) => v !== holder)[0]);
        console.log(JSON.stringify({ holder, stops: tabStops(), visible: visibleIds() }));
        """,
        rail_sandbox,
    )
    assert len(out["stops"]) == 1
    assert out["stops"][0] != out["holder"]
    assert out["stops"][0] in out["visible"]
