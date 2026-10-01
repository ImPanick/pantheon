# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B1052` — Escape over the Workbench closes the innermost thing first.

Measured on the merged tree (`a97d969`, `verify-a`): click a step, edit its
form, press Escape with the pointer still on the window — **the Workbench
closed**, and the unsaved form with it. With the pointer moved off the window
the first Escape closed only the panel. The arbiter in `static/js/ui.js` runs
`_closeHoveredWindow()` before `dismissTopMenu()`, so a window's own layers on
`escMenuStack.js` never saw the key while the pointer was on the window — and a
mouse user's pointer is always there, because they just clicked the step.

Driven here, not read: the arbiter's own code — `_visibleModalForSpace`,
`_spaceWindowId`, `_windowAtPointer`, `_closeHoveredWindow`, `_isVisible`,
`pickTopModal` and the capture-phase Escape handler — cut out of the real
`ui.js` with `tests/helpers/js_source.js_definition`, run against the real
`workbench/canvas.js`, `escMenuStack.js` and the rest of the canvas's modules
in the DOM shim of `tests/test_tool_effect_surfaces_js.py` (with its opt-in
HTML layer, for `closest` and `contains`). What stands in for the browser:
`modalManager.js` (`isRegistered` / `close`, recorded), `getComputedStyle`
(z-index and display), the pointer's last position, and one selector the shim
cannot parse (`.modal:not(.hidden):not(.modal-minimized) .modal-content`),
answered the way a browser would. The step form is the `P22` panel contract's
stub, as in `tests/test_the_workbench_canvas_js.py`.

**What else the `ui.js` change affects** is pinned too: a window that does not
mark an open layer with `[data-esc-layer]` closes on the first Escape exactly
as before, even with a menu registered elsewhere on the stack.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402
from test_the_workbench_canvas_js import _SHIM as _CANVAS_SHIM, _UP, _TASKS  # noqa: E402
from tests.helpers.js_source import js_definition  # noqa: E402
from tests.helpers.source_text import blank_text  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"
CANVAS_JS = JS / "workbench" / "canvas.js"
UI_JS = JS / "ui.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _arbiter() -> str:
    """The arbiter's functions and its Escape handler, as `ui.js` has them."""
    src = UI_JS.read_text(encoding="utf-8")
    code = blank_text(src, "js")
    parts = []
    for name in ("_visibleModalForSpace", "_spaceWindowId", "_windowAtPointer", "_closeHoveredWindow"):
        assert code.count(f"function {name}(") == 1, name
        parts.append(js_definition(src, code.index(f"function {name}(")))
    for name in ("_isVisible", "pickTopModal"):
        assert code.count(f"const {name} = ") == 1, name
        parts.append(js_definition(src, code.index(f"const {name} = ")))
    anchor = code.index("if (e.key !== 'Escape' || e.defaultPrevented) return;")
    start = code.rindex("(e) => {", 0, anchor)
    parts.append("const escapeArbiter = " + js_definition(src, start) + ";")
    return "\n".join(parts)


_SHIM = _CANVAS_SHIM + r"""
import { installHtmlParsing } from './dom.js';
installHtmlParsing();
// The arbiter presses a window's close button with `.click()`, inside a
// `try` that would swallow the shim's missing method as silence.
Node.prototype.click = function click() { this.dispatchEvent({ type: 'click', target: this, currentTarget: this }); };

// ── the browser around the arbiter ──────────────────────────────────────────
export const closed = [];
export const Modals = {
  isRegistered: (id) => ['workbench-modal', 'notes-modal'].includes(id),
  isMinimized: () => false,
  close: (id) => { closed.push(id); document.getElementById(id).classList.add('hidden'); },
};
globalThis.getComputedStyle = (el) => ({
  zIndex: (el.style && el.style.zIndex) || '0',
  display: el._classes && el._classes().includes('hidden') ? 'none' : 'block',
});
document.elementFromPoint = () => null;
const _qsa = document.querySelectorAll.bind(document);
document.querySelectorAll = (sel) => {
  if (sel === '.modal:not(.hidden):not(.modal-minimized) .modal-content') {
    return _qsa('.modal').filter((m) => !m._classes().includes('hidden') && !m._classes().includes('modal-minimized'))
      .flatMap((m) => m.querySelectorAll('.modal-content'));
  }
  return _qsa(sel);
};
document.querySelector = (sel) => document.querySelectorAll(sel)[0] || null;

/** A window: `.modal#id > .modal-content > (.close-btn, body)`, 1000×800 at 0,0. */
export function makeWindow(id, z) {
  const modal = document.body.appendChild(new Node('div'));
  modal.setAttribute('id', id);
  modal.className = 'modal';
  modal.style.zIndex = String(z);
  const content = modal.appendChild(new Node('div'));
  content.className = 'modal-content';
  content.getBoundingClientRect = () => ({ left: 0, top: 0, right: 1000, bottom: 800, width: 1000, height: 800 });
  const close = content.appendChild(new Node('button'));
  close.className = 'close-btn';
  close.addEventListener('click', () => { closed.push(id + ' (button)'); modal.classList.add('hidden'); });
  const body = content.appendChild(new Node('div'));
  body.className = 'workbench-room';
  return { modal, content, body };
}
export const isOpen = (id) => !document.getElementById(id)._classes().includes('hidden');
"""

_PREAMBLE = (
    "import { document, Node, server, net, panel, mountPanel, fire, settle, nodeOf, said, edgeEls,"
    " closed, Modals, makeWindow, isOpen } from './shim.js';\n"
    "import { dismissTopMenu, registerMenuDismiss, _openMenuCount } from '../escMenuStack.js';\n"
    "const { mountCanvas } = await import('./canvas.js');\n"
    "let _lastPointerClientX = 500, _lastPointerClientY = 400;\n"
    "let hoveredToggleWindow = null;\n"
    "const pointerOn = () => { _lastPointerClientX = 500; _lastPointerClientY = 400; };\n"
    "const pointerOff = () => { _lastPointerClientX = 5000; _lastPointerClientY = 5000; };\n"
    "%s\n"
    "/** One Escape keypress, as the capture-phase listener receives it. */\n"
    "const escape = (target = null) => {\n"
    "  const ev = { key: 'Escape', defaultPrevented: false, target, stopped: false,\n"
    "    stopImmediatePropagation() { this.stopped = true; }, preventDefault() { this.defaultPrevented = true; } };\n"
    "  escapeArbiter(ev);\n"
    "  return ev.stopped;\n"
    "};\n"
    "const wb = makeWindow('workbench-modal', 1002);\n"
    "const mount = async () => {\n"
    "  const c = mountCanvas(wb.body, { fetch: net, mountPanel });\n"
    "  await c.ready; await settle();\n"
    "  return c;\n"
    "};\n"
    "const panelOpen = () => !wb.body.querySelector('.wb-panel').hidden;\n"
    "const marked = () => wb.body.dataset.escLayer != null;\n"
    "const out = (o) => console.log(JSON.stringify(o));\n"
)


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    root = tmp_path_factory.mktemp("wbesc")
    (root / "workbench").mkdir()
    sandbox = _make_sandbox(root / "workbench", CANVAS_JS, _SHIM, {})
    for rel in _UP:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(JS / rel, root / rel)
    (root / "windowDrag.js").write_text(
        "export const KEY_STEP = 16;\nexport const MOVE_THRESHOLD = 4;\n"
        "export function makeWindowDraggable() {}\n", encoding="utf-8")
    return sandbox


def _case(box, script, tasks=None):
    setup = "server.tasks = %s;\n" % json.dumps(tasks if tasks is not None else _TASKS)
    return _run(box, _PREAMBLE % _arbiter() + setup, script)


def test_over_the_window_escape_closes_the_step_panel_then_the_window(box):
    """The row's `Verify:` with nothing edited: the pointer stays on the window
    the whole time, as it does for someone who just clicked a step."""
    o = _case(box, """
        await mount();
        pointerOn();
        fire(nodeOf(wb.body, 'b'), 'click');
        const opened = { panel: panelOpen(), marked: marked() };
        const first = { stopped: escape(), window: isOpen('workbench-modal'), panel: panelOpen(),
                        destroyed: panel.mounts[0].destroyed, focused: !!nodeOf(wb.body, 'b').focused,
                        marked: marked() };
        const second = { stopped: escape(), window: isOpen('workbench-modal') };
        out({ opened, first, second, closed });
    """)
    assert o["opened"] == {"panel": True, "marked": True}
    assert o["first"] == {"stopped": True, "window": True, "panel": False, "destroyed": True,
                          "focused": True, "marked": False}
    assert o["second"] == {"stopped": True, "window": False}
    assert o["closed"] == ["workbench-modal"]


def test_an_edited_step_asks_first_then_closes_the_panel_then_the_window(box):
    o = _case(box, """
        await mount();
        pointerOn();
        fire(nodeOf(wb.body, 'b'), 'click');
        const m = panel.mounts[0];
        fire(m.host, 'input');                       // typed into the Name box
        const first = { window: isOpen('workbench-modal'), panel: panelOpen(), destroyed: m.destroyed,
                        said: said(wb.body) };
        escape();
        const asked = { window: isOpen('workbench-modal'), panel: panelOpen(), destroyed: m.destroyed,
                        said: said(wb.body), marked: marked() };
        escape();
        const second = { window: isOpen('workbench-modal'), panel: panelOpen(), destroyed: m.destroyed,
                         said: said(wb.body) };
        escape();
        out({ asked, second, third: { window: isOpen('workbench-modal') }, closed });
    """)
    assert o["asked"] == {
        "window": True, "panel": True, "destroyed": False, "marked": True,
        "said": "Message me has changes that are not saved. Press Escape again to close it without "
                "saving them, or Save.",
    }
    assert o["second"] == {"window": True, "panel": False, "destroyed": True,
                           "said": "Closed Message me without saving."}
    assert o["third"] == {"window": False}
    assert o["closed"] == ["workbench-modal"]


def test_typing_again_after_the_question_asks_again(box):
    """Said first, done second — and only for two Escapes in a row. More typing
    in between is more work that would be lost."""
    o = _case(box, """
        await mount();
        pointerOn();
        fire(nodeOf(wb.body, 'a'), 'click');
        const m = panel.mounts[0];
        fire(m.host, 'change');
        escape();
        fire(m.host, 'input');
        escape();
        const kept = { panel: panelOpen(), destroyed: m.destroyed, said: said(wb.body) };
        escape();
        out({ kept, after: { panel: panelOpen(), window: isOpen('workbench-modal') } });
    """)
    assert o["kept"]["panel"] is True and o["kept"]["destroyed"] is False
    assert o["kept"]["said"].startswith("Nightly backup has changes that are not saved.")
    assert o["after"] == {"panel": False, "window": True}


def test_a_new_step_with_edits_asks_too(box):
    o = _case(box, """
        await mount();
        pointerOn();
        fire(wb.body.querySelector('.wb-tool-new'), 'click');
        fire(panel.mounts[0].host, 'input');
        escape();
        out({ panel: panelOpen(), said: said(wb.body), window: isOpen('workbench-modal') });
    """)
    assert o["panel"] is True and o["window"] is True
    assert o["said"].startswith("This new step has changes that are not saved.")


def test_over_the_window_escape_closes_connect_and_ends_a_drag_before_the_window(box):
    o = _case(box, """
        await mount();
        pointerOn();
        fire(nodeOf(wb.body, 'a').querySelector('.wb-node-connect'), 'click');
        escape();
        const connect = { open: !!wb.body.querySelector('.wb-connect'), window: isOpen('workbench-modal'),
                          focusedA: !!nodeOf(wb.body, 'a').focused };
        const port = nodeOf(wb.body, 'a').querySelectorAll('.wb-port').find((p) => p.dataset.when === 'error');
        fire(port, 'pointerdown', {});
        const linking = wb.body._classes().includes('wb-linking');
        escape();
        const drag = { linking: wb.body._classes().includes('wb-linking'), window: isOpen('workbench-modal') };
        fire(edgeEls(wb.body)[0], 'focus');
        fire(edgeEls(wb.body)[0], 'keydown', { key: 'Delete' });
        escape();
        const removal = { said: said(wb.body), window: isOpen('workbench-modal'), writes: server.calls
          .filter((c) => c.method === 'PUT').length };
        out({ connect, linking, drag, removal, marked: marked(), left: _openMenuCount() });
    """)
    assert o["connect"] == {"open": False, "window": True, "focusedA": True}
    assert o["linking"] is True
    assert o["drag"] == {"linking": False, "window": True}
    assert o["removal"]["window"] is True and o["removal"]["writes"] == 0
    assert o["removal"]["said"].startswith("Kept. After Nightly backup, if it works")
    assert o["marked"] is False and o["left"] == 0, "every layer gave its mark and its stack entry back"


def test_with_the_pointer_off_the_window_the_order_is_the_same(box):
    """The path verify-a measured as right already — the stack, then the top
    window's close button — is unchanged."""
    o = _case(box, """
        await mount();
        fire(nodeOf(wb.body, 'b'), 'click');
        fire(panel.mounts[0].host, 'input');
        pointerOff();
        escape(); const asked = panelOpen();
        escape(); const panelGone = !panelOpen();
        escape();
        out({ asked, panelGone, window: isOpen('workbench-modal'), closed });
    """)
    assert o == {"asked": True, "panelGone": True, "window": False, "closed": ["workbench-modal (button)"]}


def test_the_workbench_with_nothing_open_closes_on_the_first_escape(box):
    o = _case(box, """
        await mount();
        pointerOn();
        const marked0 = marked();
        escape();
        out({ marked0, window: isOpen('workbench-modal'), closed });
    """)
    assert o == {"marked0": False, "window": False, "closed": ["workbench-modal"]}


def test_a_window_that_marks_no_layer_closes_as_before_whatever_is_on_the_stack(box):
    """What else the `ui.js` change touches: nothing that does not say it holds
    a layer. A menu registered elsewhere — a kebab dropdown hanging off
    `<body>` — does not stop Escape over another window closing that window."""
    o = _case(box, """
        const notes = makeWindow('notes-modal', 1003);
        wb.modal.classList.add('hidden');
        let menuClosed = false;
        registerMenuDismiss(() => { menuClosed = true; });
        pointerOn();
        escape();
        out({ notes: isOpen('notes-modal'), menuClosed, left: _openMenuCount(), closed });
    """)
    assert o == {"notes": False, "menuClosed": False, "left": 1, "closed": ["notes-modal"]}
