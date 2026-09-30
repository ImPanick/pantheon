# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P10-06` / `B660` — a tool window, from a keyboard: reached, moved, resized,
and left.

**Measured 2026-09-27 in Chromium against the running app, before a line
changed.** `static/js/windowDrag.js` and `static/js/windowResize.js` still had
zero `keydown` handlers between them (`P10-06` counted zero on 2026-09-18), so a
window could be opened and closed from a keyboard and never moved. And "opened"
was generous: Enter on the Tasks launcher left the focus on the launcher, the
window hangs off the end of `<body>`, and it was twenty Shift+Tab presses away —
forward Tab never arrived, because it stopped in the composer's textarea, where
Tab toggles Plan mode (filed, the owner's call). Closing it by its own ✕ from
the keyboard then dropped the focus to `<body>`.

What changed, and what each case below pins:

  * **`windowDrag.js` puts a real `<button>` first in every window's header**,
    painted only while it has the focus. Arrow keys move the window 16px —
    `P10-03`'s step — kept whole on the screen; Shift + an arrow resizes it
    through `windowResize.js`'s new `resizeBy`, which persists the size the way
    a drag does. A docked window is un-docked by the first arrow, as dragging it
    off the edge does. A window wired with `enableResize: false` offers no
    resize. Keys with Ctrl/Alt/Meta, and every key at phone width, are left
    alone.
  * **`a11y.js` hands the focus to that button** when a window appears while the
    focus is still on the control a person just pressed Enter or Space on — in
    the rail, the sidebar, the dock, or another tool window (the Skills window
    opens from the Brain) — and gives it back to that control when the window
    goes away with the focus inside it. A window a script opens, or one opened
    with the mouse, is never handed the focus.

Both modules are driven under node in the sandbox pattern
`tests/test_tool_effect_surfaces_js.py` owns. Geometry, focus, `contains`,
`isConnected` and `getComputedStyle` are patched in these sandboxes only;
`modalSnap.js` is stubbed down to the two names `windowDrag.js` imports, so the
case can see whether an un-dock was asked for.
"""

import json
import shutil
from pathlib import Path

import pytest

from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_PATCHES = r"""
Node.prototype.focus = function () { document.activeElement = this; this.focused = true; };
Node.prototype.contains = function (n) {
  for (let x = n; x; x = x.parentNode) if (x === this) return true;
  return false;
};
Object.defineProperty(Node.prototype, 'isConnected', {
  get() { let n = this; while (n.parentNode) n = n.parentNode; return n === document; },
});
// A browser lays out before it answers, so what a module writes to
// `style.left/top/width/height` is what it reads back on the next line.
Node.prototype.getBoundingClientRect = function () {
  const g = this._geom || {};
  const px = (v, d) => { const n = parseFloat(v); return Number.isNaN(n) ? d : n; };
  const left = px(this.style.left, g.left || 0), top = px(this.style.top, g.top || 0);
  const width = px(this.style.width, g.width || 0), height = px(this.style.height, g.height || 0);
  return { left, top, width, height, right: left + width, bottom: top + height, x: left, y: top };
};
Node.prototype.getAnimations = function () { return []; };
globalThis.getComputedStyle = () => ({ position: 'sticky', getPropertyValue: () => '' });
globalThis.innerWidth = 1400;
globalThis.innerHeight = 900;
globalThis.requestAnimationFrame = () => 0;
export function tick(ms = 5) { return new Promise((r) => setTimeout(r, ms)); }
"""

# ── windowDrag.js / windowResize.js ────────────────────────────────────────

_DRAG_SHIM = r"""
import { installDom, Node } from './dom.js';
export const document = installDom();
export { Node };
""" + _PATCHES + r"""
export const calls = { undock: 0, dragStart: 0, dragEnd: [] };
globalThis.__calls = calls;

/** A window: `.modal` > content (600x500 at 400,100) > header. */
export function makeWindow(id) {
  const modal = document.body.appendChild(new Node('div'));
  modal.className = 'modal';
  modal.setAttribute('id', id);
  const content = modal.appendChild(new Node('div'));
  content.className = 'modal-content';
  content._geom = { left: 400, top: 100, width: 600, height: 500 };
  const header = content.appendChild(new Node('div'));
  header.className = 'modal-header';
  const title = header.appendChild(new Node('h4'));
  title.textContent = 'Tasks';
  const close = header.appendChild(new Node('button'));
  close.className = 'close-btn';
  return { modal, content, header, title, close };
}

export function key(node, k, mods = {}) {
  let prevented = false;
  node.dispatchEvent(Object.assign({
    type: 'keydown', key: k, target: node,
    preventDefault() { prevented = true; },
  }, mods));
  return prevented;
}

export function box(n) {
  const r = n.getBoundingClientRect();
  return [r.left, r.top, r.width, r.height];
}
"""

_SNAP_STUB = r"""
export function makeEdgeDockController() {
  return { onMove() { return false; }, hovering() { return false; }, commit() {}, release() {}, side() { return 'right'; } };
}
export function clearRightDock(modal) {
  globalThis.__calls.undock += 1;
  modal.classList.remove('modal-right-docked', 'modal-left-docked');
}
"""

_DRAG_PREAMBLE = (
    "import { document, Node, tick, calls, makeWindow, key, box } from './shim.js';\n"
    "const { makeWindowDraggable } = await import('./windowDrag.js');\n"
    "function wire(w, opts = {}) {\n"
    "  makeWindowDraggable(w.modal, Object.assign({ content: w.content, header: w.header,\n"
    "    onDragStart: () => { calls.dragStart += 1; },\n"
    "    onDragEnd: ({ rect }) => { calls.dragEnd.push([rect.left, rect.top]); } }, opts));\n"
    "  return w.header.querySelector('.window-move-handle');\n"
    "}\n"
)


@pytest.fixture(scope="module")
def drag_sandbox(tmp_path_factory):
    d = _make_sandbox(tmp_path_factory.mktemp("winkeys"), JS / "windowDrag.js", _DRAG_SHIM,
                      {"modalSnap.js": _SNAP_STUB})
    shutil.copy(JS / "windowResize.js", d / "windowResize.js")
    return d


def _drag(script: str, sandbox: Path) -> dict:
    return _run(sandbox, _DRAG_PREAMBLE, script)


def test_every_window_gets_a_real_button_first_in_its_header(drag_sandbox):
    out = _drag(
        """
        const w = makeWindow('tasks-modal');
        const h = wire(w);
        wire(w);                                   // a second wiring adds nothing
        console.log(JSON.stringify({
          tag: h && h.tagName, type: h && h.type, first: w.header.childNodes[0] === h,
          handles: w.header.querySelectorAll('.window-move-handle').length,
          text: h && h.textContent,
          contentIsWindow: w.content.getAttribute('data-window-keys') !== null,
          headerIsWindow: w.header.getAttribute('data-window-keys') !== null
            || w.header.dataset.windowKeys !== undefined,
        }));
        """,
        drag_sandbox,
    )
    assert out["tag"] == "BUTTON" and out["type"] == "button", out
    assert out["first"] is True, "the handle must be the first stop inside the window"
    assert out["handles"] == 1, "wiring a window twice put two handles in its header"
    assert "arrow" in out["text"].lower() and "resize" in out["text"].lower(), out["text"]
    assert out["contentIsWindow"] is True
    assert out["headerIsWindow"] is False, (
        "the header carries `data-window-keys` too, so `a11y.js` counts it as a "
        "window of its own and hangs the opener on it — measured in Chromium: "
        "closing the Skills window then gave the focus to nobody"
    )


def test_the_arrows_move_the_window_sixteen_pixels(drag_sandbox):
    out = _drag(
        """
        const w = makeWindow('tasks-modal');
        const h = wire(w);
        const start = box(w.content);
        const pr = key(h, 'ArrowRight');
        key(h, 'ArrowRight');
        key(h, 'ArrowDown');
        const moved = box(w.content);
        key(h, 'ArrowLeft'); key(h, 'ArrowUp');
        console.log(JSON.stringify({ start, pr, moved, back: box(w.content),
          fixed: w.content.style.position, dragEnd: calls.dragEnd.length, dragStart: calls.dragStart }));
        """,
        drag_sandbox,
    )
    assert out["start"] == [400, 100, 600, 500]
    assert out["pr"] is True, "an arrow the handle answered must not also scroll the page"
    assert out["moved"] == [432, 116, 600, 500], out["moved"]
    assert out["back"] == [416, 100, 600, 500], out["back"]
    assert out["fixed"] == "fixed"
    assert out["dragEnd"] == 5 and out["dragStart"] == 5, (
        "a keyboard move must report through onDragStart/onDragEnd like a drag, "
        "or a window that saves its position (the Library) forgets this one"
    )


def test_a_moved_window_stays_whole_on_the_screen(drag_sandbox):
    out = _drag(
        """
        const w = makeWindow('tasks-modal');
        const h = wire(w);
        for (let i = 0; i < 80; i++) key(h, 'ArrowLeft');
        for (let i = 0; i < 80; i++) key(h, 'ArrowUp');
        const topLeft = box(w.content);
        for (let i = 0; i < 120; i++) key(h, 'ArrowRight');
        for (let i = 0; i < 120; i++) key(h, 'ArrowDown');
        console.log(JSON.stringify({ topLeft, bottomRight: box(w.content) }));
        """,
        drag_sandbox,
    )
    assert out["topLeft"][:2] == [0, 0], out
    assert out["bottomRight"][:2] == [1400 - 600, 900 - 500], (
        "a keyboard cannot drag back a title bar it pushed off the screen"
    )


def test_shift_and_an_arrow_resize_it_and_the_size_persists(drag_sandbox):
    out = _drag(
        """
        const w = makeWindow('tasks-modal');
        const h = wire(w);
        const pr = key(h, 'ArrowRight', { shiftKey: true });
        key(h, 'ArrowDown', { shiftKey: true });
        const grown = box(w.content);
        for (let i = 0; i < 80; i++) key(h, 'ArrowLeft', { shiftKey: true });
        const smallest = box(w.content);
        console.log(JSON.stringify({ pr, grown, smallest,
          saved: localStorage.getItem('winsize-tasks-modal') }));
        """,
        drag_sandbox,
    )
    assert out["pr"] is True
    assert out["grown"] == [400, 100, 616, 516], out["grown"]
    assert out["smallest"][2] == 320, "resize must stop at the drag's own minimum width"
    assert json.loads(out["saved"]) == {"w": 320, "h": 516}, (
        "a size set from the keyboard must be the size the window reopens at"
    )


def test_a_window_without_resize_offers_none(drag_sandbox):
    out = _drag(
        """
        const w = makeWindow('rename-session-modal');
        const h = wire(w, { enableResize: false });
        const pr = key(h, 'ArrowRight', { shiftKey: true });
        console.log(JSON.stringify({ pr, box: box(w.content), text: h.textContent }));
        """,
        drag_sandbox,
    )
    assert out["pr"] is False and out["box"] == [400, 100, 600, 500]
    assert "resize" not in out["text"].lower(), (
        "the handle offers a resize this window does not have"
    )


def test_a_docked_window_is_undocked_by_the_first_arrow(drag_sandbox):
    out = _drag(
        """
        const w = makeWindow('notes-panel');
        w.modal.classList.add('modal-right-docked');
        const h = wire(w);
        const pr = key(h, 'ArrowLeft');
        console.log(JSON.stringify({ pr, undock: calls.undock,
          docked: w.modal.classList.contains('modal-right-docked'), box: box(w.content) }));
        """,
        drag_sandbox,
    )
    assert out["undock"] == 1 and out["docked"] is False
    assert out["pr"] is True and out["box"][0] == 384


def test_keys_that_are_not_the_handles_are_left_alone(drag_sandbox):
    out = _drag(
        """
        const w = makeWindow('tasks-modal');
        const h = wire(w);
        const ctrl = key(h, 'ArrowRight', { ctrlKey: true });
        const alt = key(h, 'ArrowRight', { altKey: true });
        const enter = key(h, 'Enter');
        const letter = key(h, 'a');
        console.log(JSON.stringify({ ctrl, alt, enter, letter, box: box(w.content) }));
        """,
        drag_sandbox,
    )
    assert out == {"ctrl": False, "alt": False, "enter": False, "letter": False,
                   "box": [400, 100, 600, 500]}, out


def test_nothing_moves_at_phone_width(drag_sandbox):
    """Below 768px the windows are sheets and the drag is off; the arrows have
    to be off too, and the key has to reach whatever else wants it."""
    out = _drag(
        """
        globalThis.innerWidth = 700;
        const w = makeWindow('tasks-modal');
        const h = wire(w);
        const pr = key(h, 'ArrowRight');
        const rs = key(h, 'ArrowRight', { shiftKey: true });
        console.log(JSON.stringify({ pr, rs, box: box(w.content) }));
        """,
        drag_sandbox,
    )
    assert out == {"pr": False, "rs": False, "box": [400, 100, 600, 500]}, out


def test_pressing_the_handle_is_not_a_click_on_the_header(drag_sandbox):
    """Enter on a `<button>` is a click, and a header can have a click handler
    of its own (the Library's "back to the list")."""
    out = _drag(
        """
        const w = makeWindow('doclib-modal');
        const h = wire(w);
        let stopped = false;
        h.dispatchEvent({ type: 'click', target: h, stopPropagation() { stopped = true; } });
        console.log(JSON.stringify({ stopped }));
        """,
        drag_sandbox,
    )
    assert out["stopped"] is True


# ── a11y.js: the focus in, and back ─────────────────────────────────────────

_A11Y_SHIM = r"""
import { installDom, Node } from './dom.js';
export const document = installDom();
export { Node };
""" + _PATCHES + r"""
const rail = document.body.appendChild(new Node('div'));
rail.setAttribute('id', 'icon-rail');
const sidebar = document.body.appendChild(new Node('nav'));
sidebar.setAttribute('id', 'sidebar');
export const launcher = sidebar.appendChild(new Node('button'));
launcher.setAttribute('id', 'tool-tasks-btn');
export const composer = document.body.appendChild(new Node('textarea'));
composer.setAttribute('id', 'message');
export const elsewhere = document.body.appendChild(new Node('button'));
elsewhere.setAttribute('id', 'elsewhere');

/** A hidden window as `windowDrag.js` leaves it: content marked, handle first. */
export function makeWindow(id) {
  const modal = document.body.appendChild(new Node('div'));
  modal.className = 'modal hidden';
  modal.setAttribute('id', id);
  const content = modal.appendChild(new Node('div'));
  content.setAttribute('data-window-keys', '');
  const header = content.appendChild(new Node('div'));
  const handle = header.appendChild(new Node('button'));
  handle.className = 'window-move-handle';
  const close = header.appendChild(new Node('button'));
  close.className = 'close-btn';
  const body = content.appendChild(new Node('button'));
  body.className = 'first-in-body';
  return { modal, content, handle, close, body };
}
export function show(w) { w.modal.classList.remove('hidden'); }
export function hide(w) { w.modal.classList.add('hidden'); }

/** Enter pressed on `node`, the way the document hears it. */
export function press(node, k = 'Enter') {
  document.dispatchEvent({ type: 'keydown', key: k, target: node, preventDefault() {} });
}
/** What the browser does when the focused control is hidden or removed. */
export function focusFallsToBody(from) {
  document.activeElement = document.body;
  document.dispatchEvent({ type: 'focusout', target: from, relatedTarget: null });
}
export function who() {
  const a = document.activeElement;
  if (!a) return null;
  return a.id || a.className || a.tagName;
}
"""

_A11Y_PREAMBLE = (
    "import { document, Node, tick, launcher, composer, elsewhere, makeWindow, show, hide,"
    " press, focusFallsToBody, who } from './shim.js';\n"
    "await import('./a11y.js');\n"
)


@pytest.fixture(scope="module")
def a11y_sandbox(tmp_path_factory):
    return _make_sandbox(tmp_path_factory.mktemp("winfocus"), JS / "a11y.js", _A11Y_SHIM, {})


def _focus(script: str, sandbox: Path) -> dict:
    return _run(sandbox, _A11Y_PREAMBLE, script)


def test_a_window_opened_from_the_keyboard_takes_the_focus(a11y_sandbox):
    out = _focus(
        """
        const w = makeWindow('tasks-modal');
        launcher.focus();
        press(launcher);
        show(w);                                  // the launcher's own click opens it
        await tick(120);
        console.log(JSON.stringify({ focused: who(), opener: w.content._a11yOpener === launcher }));
        """,
        a11y_sandbox,
    )
    assert out["focused"] == "window-move-handle", (
        f"the window opened from Enter on its launcher left the focus on "
        f"{out['focused']!r}; measured, that is twenty Shift+Tab presses away"
    )
    assert out["opener"] is True


def test_a_window_that_shows_after_a_fetch_is_still_this_press(a11y_sandbox):
    """Tasks fetches before it shows; the press is still the reason it opened."""
    out = _focus(
        """
        const w = makeWindow('tasks-modal');
        launcher.focus();
        press(launcher);
        setTimeout(() => show(w), 400);
        await tick(600);
        console.log(JSON.stringify({ focused: who() }));
        """,
        a11y_sandbox,
    )
    assert out["focused"] == "window-move-handle"


def test_a_person_who_moved_on_keeps_their_focus(a11y_sandbox):
    out = _focus(
        """
        const w = makeWindow('tasks-modal');
        launcher.focus();
        press(launcher);
        elsewhere.focus();                        // they moved on before it showed
        setTimeout(() => show(w), 200);
        await tick(400);
        console.log(JSON.stringify({ focused: who() }));
        """,
        a11y_sandbox,
    )
    assert out["focused"] == "elsewhere"


def test_a_window_a_script_opens_is_not_handed_the_focus(a11y_sandbox):
    """The assistant can open Notes mid-reply; the person is typing, and Enter
    in the composer is not a launcher."""
    out = _focus(
        """
        const w = makeWindow('notes-panel');
        composer.focus();
        press(composer);                          // Enter sends the message
        show(w);                                  // the reply opens a window
        await tick(150);
        const afterSend = who();
        const w2 = makeWindow('tasks-modal');
        show(w2);                                 // no key at all: a script or a mouse
        await tick(150);
        console.log(JSON.stringify({ afterSend, afterScript: who() }));
        """,
        a11y_sandbox,
    )
    assert out == {"afterSend": "message", "afterScript": "message"}, out


def test_a_control_in_another_window_is_a_launcher_too(a11y_sandbox):
    """The Skills window has no launcher of its own; it opens from the Brain's
    Skills tab and its "Open Skills" buttons (`P9-06`)."""
    out = _focus(
        """
        const brain = makeWindow('memory-modal');
        show(brain);
        const tab = brain.content.appendChild(new Node('button'));
        tab.className = 'memory-tab';
        const skills = makeWindow('skills-modal');
        tab.focus();
        press(tab);
        show(skills);
        await tick(120);
        const inSkills = skills.content.contains(document.activeElement);
        hide(skills);
        focusFallsToBody(skills.handle);
        await tick(20);
        console.log(JSON.stringify({ inSkills, back: document.activeElement === tab }));
        """,
        a11y_sandbox,
    )
    assert out == {"inSkills": True, "back": True}, out


def test_closing_the_window_gives_the_focus_back_to_its_launcher(a11y_sandbox):
    out = _focus(
        """
        const w = makeWindow('tasks-modal');
        launcher.focus();
        press(launcher);
        show(w);
        await tick(120);
        w.close.focus();
        hide(w);                                  // Enter on its ✕
        focusFallsToBody(w.close);
        await tick(20);
        console.log(JSON.stringify({ focused: who(), cleared: w.content._a11yOpener == null }));
        """,
        a11y_sandbox,
    )
    assert out["focused"] == "tool-tasks-btn", (
        f"closing the window from the keyboard left the focus on {out['focused']!r}"
    )
    assert out["cleared"] is True


def test_a_click_elsewhere_while_it_is_open_is_left_alone(a11y_sandbox):
    out = _focus(
        """
        const w = makeWindow('tasks-modal');
        launcher.focus();
        press(launcher);
        show(w);
        await tick(120);
        focusFallsToBody(w.handle);               // the window is still open
        await tick(20);
        console.log(JSON.stringify({ focused: who(), kept: w.content._a11yOpener === launcher }));
        """,
        a11y_sandbox,
    )
    assert out == {"focused": "BODY", "kept": True}, out


def test_a_launcher_that_left_the_page_is_not_given_the_focus(a11y_sandbox):
    out = _focus(
        """
        const w = makeWindow('tasks-modal');
        const temp = document.getElementById('sidebar').appendChild(new Node('button'));
        temp.focus();
        press(temp);
        show(w);
        await tick(120);
        temp.remove();
        hide(w);
        focusFallsToBody(w.handle);
        await tick(20);
        console.log(JSON.stringify({ focused: who() }));
        """,
        a11y_sandbox,
    )
    assert out["focused"] == "BODY"
