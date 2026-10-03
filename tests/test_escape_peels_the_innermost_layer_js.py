# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P23-01` — one Escape arbiter: one press peels the innermost layer.

Measured on `9560d50` (NAV-M-2/3/4/6, DOCS-U-1, BRAIN-U-4, DOCS-M-8): four
handlers owned Escape — `ui.js`'s capture listener, a second arbiter in
`app.js` that closed a fixed list of windows with no text-field guard, the
stream stop, and ten per-window `document` listeners — so:

  * Escape typed in the Brain's search box closed the Brain; in a Tasks field
    it removed the window and the draft with it (NAV-M-2);
  * Tasks open, the Brain over it, the focus in the composer: Escape closed
    Tasks, the window *behind* (NAV-M-3);
  * a ⋮ menu open with the pointer on its window: Escape closed the window and
    the menu with it (NAV-M-4, DOCS-U-1, BRAIN-U-4).

The owner's ruling `D-2026-10-03-01` §2: Escape = Back = `←`, innermost first.

Driven here: the arbiter's own functions and both its Escape listeners, cut out
of the real `static/js/ui.js` with `js_definition` (the same cut
`tests/test_escape_closes_the_workbench_panel_before_the_window_js.py` makes —
that file pins `B1052`'s Workbench cases on it), run under node against the real
`escMenuStack.js` in the DOM shim with its HTML layer (`closest`, `contains`).
What stands in for the browser: `modalManager.closeWindow` (recorded),
`backStack.js`'s `top`/`isTracked`, `getComputedStyle` (z and display from the
element's own style and classes), and one selector the shim cannot parse
(`[id$="-bulk-cancel"]`), answered the way a browser would.
"""

import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402
from test_escape_closes_the_workbench_panel_before_the_window_js import _arbiter  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
ESC_STACK_JS = ROOT / "static" / "js" / "escMenuStack.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_SHIM = r"""
import { installDom, installHtmlParsing, Node } from './dom.js';
export const document = installDom();
installHtmlParsing();
export { Node };
Node.prototype.click = function click() { this.dispatchEvent({ type: 'click', target: this, currentTarget: this }); };
Node.prototype.blur = function blur() { this.blurred = true; this.focused = false; };
// `_targetEl` asks `nodeType`, as a browser answers it.
Object.defineProperty(Node.prototype, 'nodeType', { configurable: true,
  get() { return this.tagName === '#TEXT' ? 3 : 1; } });

export const closed = [];
export const Modals = {
  closeWindow: (id) => {
    closed.push(id);
    const m = document.getElementById(id);
    if (m) m.classList.add('hidden');
  },
};
export const stackTop = { id: null };
export const backStack = {
  DRAWER: 'sidebar-drawer',
  top: () => stackTop.id,
  isTracked: (id) => ['memory-modal', 'tasks-modal', 'settings-modal', 'calendar-modal', 'doclib-modal'].includes(id),
};
export const toolWindowZ = (el) => parseInt((el.style && el.style.zIndex) || '0', 10);
globalThis.getComputedStyle = (el) => ({
  zIndex: (el.style && el.style.zIndex) || '0',
  display: (el.style && el.style.display === 'none') || (el._classes && el._classes().includes('hidden')) ? 'none' : 'block',
  visibility: 'visible',
});
const _qsa = Node.prototype.querySelectorAll;
Node.prototype.querySelectorAll = function (sel) {
  if (sel === '[id$="-bulk-cancel"]') return this._walk([]).filter((n) => String(n.id || '').endsWith('-bulk-cancel'));
  return _qsa.call(this, sel);
};
Node.prototype.querySelector = function (sel) { return this.querySelectorAll(sel)[0] || null; };
document.querySelectorAll = (sel) => Node.prototype.querySelectorAll.call(document, sel);
document.querySelector = (sel) => document.querySelectorAll(sel)[0] || null;

/** A window: `.modal#id > .modal-content > (.modal-header > .close-btn, .modal-body)`. */
export function makeWindow(id, z) {
  const modal = document.body.appendChild(new Node('div'));
  modal.setAttribute('id', id);
  modal.className = 'modal';
  modal.style.zIndex = String(z);
  const content = modal.appendChild(new Node('div'));
  content.className = 'modal-content';
  const header = content.appendChild(new Node('div'));
  header.className = 'modal-header';
  const body = content.appendChild(new Node('div'));
  body.className = 'modal-body';
  return { modal, body };
}
export function field(parent, tag = 'input') {
  const n = parent.appendChild(new Node(tag));
  if (tag === 'input') n.type = 'text';
  return n;
}
export const isOpen = (id) => !document.getElementById(id)._classes().includes('hidden');
"""

_PREAMBLE = (
    "import { document, Node, closed, Modals, backStack, stackTop, toolWindowZ, makeWindow, field, isOpen }"
    " from './shim.js';\n"
    "import { dismissTopMenu, registerMenuDismiss, _openMenuCount } from './escMenuStack.js';\n"
    "%s\n"
    "/** One Escape: the capture listener, then — unless it stopped the key —\n"
    " *  the field's own listeners (`own`) and the bubble listener. */\n"
    "const escape = (target = null, own = null) => {\n"
    "  const ev = { key: 'Escape', defaultPrevented: false, isComposing: false, target, stopped: false,\n"
    "    stopImmediatePropagation() { this.stopped = true; }, preventDefault() { this.defaultPrevented = true; } };\n"
    "  escapeArbiter(ev);\n"
    "  if (!ev.stopped && own) own(ev);\n"
    "  if (!ev.stopped) escapeLeavesField(ev);\n"
    "  return { stopped: ev.stopped, prevented: ev.defaultPrevented };\n"
    "};\n"
    "const out = (o) => console.log(JSON.stringify(o));\n"
)


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    return _make_sandbox(tmp_path_factory.mktemp("escarbiter"), ESC_STACK_JS, _SHIM, {})


def _case(box, script):
    return _run(box, _PREAMBLE % _arbiter(), script)


def test_escape_typed_in_a_field_leaves_the_field_and_the_window_keeps_the_draft(box):
    """NAV-M-2. The first Escape takes the person out of the field; the window
    and what they typed stay. The next Escape closes the window."""
    o = _case(box, """
        const brain = makeWindow('memory-modal', 1001);
        const box1 = field(brain.body);
        box1.value = 'hello'; box1.focused = true;
        const first = escape(box1);
        const after1 = { open: isOpen('memory-modal'), value: box1.value, blurred: !!box1.blurred };
        const second = escape(null);
        out({ first, after1, second, closed });
    """)
    assert o["first"] == {"stopped": False, "prevented": True}
    assert o["after1"] == {"open": True, "value": "hello", "blurred": True}
    assert o["second"]["stopped"] is True and o["closed"] == ["memory-modal"]


def test_a_field_that_answers_its_own_escape_keeps_it(box):
    """An inline rename that cancels on Escape is not blurred under it: the
    arbiter leaves a field's key to the field, and only a key nobody used
    leaves the field."""
    o = _case(box, """
        const brain = makeWindow('memory-modal', 1001);
        const rename = field(brain.body);
        let cancelled = 0;
        const r = escape(rename, (ev) => { cancelled += 1; ev.preventDefault(); });
        out({ r, cancelled, blurred: !!rename.blurred, open: isOpen('memory-modal'), closed });
    """)
    assert o == {"r": {"stopped": False, "prevented": True}, "cancelled": 1, "blurred": False,
                 "open": True, "closed": []}


def test_with_the_focus_in_the_composer_the_top_window_closes_not_the_one_behind(box):
    """NAV-M-3. Tasks under the Brain, the focus in the message box (outside
    every window): the Brain closes, Tasks stays — by z, not by a list."""
    o = _case(box, """
        makeWindow('tasks-modal', 1008);
        makeWindow('memory-modal', 1009);
        const composer = field(document.body, 'textarea');
        const r = escape(composer);
        out({ r, tasks: isOpen('tasks-modal'), brain: isOpen('memory-modal'), closed });
    """)
    assert o == {"r": {"stopped": True, "prevented": True}, "tasks": True, "brain": False,
                 "closed": ["memory-modal"]}


def test_a_menu_closes_before_its_window_wherever_the_pointer_is(box):
    """NAV-M-4, DOCS-U-1, BRAIN-U-4: one Escape for the menu, the next for the
    window."""
    o = _case(box, """
        makeWindow('tasks-modal', 1001);
        let menu = 0;
        registerMenuDismiss(() => { menu += 1; });
        escape();
        const first = { menu, tasks: isOpen('tasks-modal'), left: _openMenuCount() };
        escape();
        out({ first, tasks: isOpen('tasks-modal'), closed });
    """)
    assert o["first"] == {"menu": 1, "tasks": True, "left": 0}
    assert o["tasks"] is False and o["closed"] == ["tasks-modal"]


def test_select_mode_then_an_expanded_card_then_the_window(box):
    """DOCS-U-1 and the Library's own order: Select mode's Cancel, then the open
    card, then the window."""
    o = _case(box, """
        const lib = makeWindow('doclib-modal', 1001);
        const cancel = lib.body.appendChild(new Node('button'));
        cancel.setAttribute('id', 'doclib-bulk-cancel');
        cancel.offsetWidth = 40;
        let cancelled = 0;
        cancel.addEventListener('click', () => { cancelled += 1; cancel.style.display = 'none'; });
        const card = lib.body.appendChild(new Node('div'));
        card.className = 'doclib-card doclib-card-expanded';
        card.addEventListener('click', () => card.classList.remove('doclib-card-expanded'));
        escape(); const one = { cancelled, expanded: card._classes().includes('doclib-card-expanded'), open: isOpen('doclib-modal') };
        escape(); const two = { expanded: card._classes().includes('doclib-card-expanded'), open: isOpen('doclib-modal') };
        escape();
        out({ one, two, open: isOpen('doclib-modal'), closed });
    """)
    assert o["one"] == {"cancelled": 1, "expanded": True, "open": True}
    assert o["two"] == {"expanded": False, "open": True}
    assert o["open"] is False and o["closed"] == ["doclib-modal"]


def test_a_popover_inside_a_window_and_an_inline_edit_go_first(box):
    """Settings' kebab (the rule `settings/lifecycle.js` kept in its own
    listener) and the Brain's inline memory edit (the rule `app.js` kept)."""
    o = _case(box, """
        const set = makeWindow('settings-modal', 1001);
        const kebab = set.body.appendChild(new Node('div'));
        kebab.setAttribute('id', 'adm-epLocalMoreMenu');
        kebab.style.display = 'flex';
        escape();
        const one = { menu: kebab.style.display, open: isOpen('settings-modal') };
        set.modal.classList.add('hidden');
        const brain = makeWindow('memory-modal', 1002);
        const row = brain.body.appendChild(new Node('div'));
        row.className = 'memory-item memory-item-editing';
        let rerendered = 0;
        window.memoryModule = { renderMemoryList: () => { rerendered += 1; row.classList.remove('memory-item-editing'); } };
        escape();
        out({ one, rerendered, brain: isOpen('memory-modal'), closed });
    """)
    assert o["one"] == {"menu": "none", "open": True}
    assert o["rerendered"] == 1 and o["brain"] is True and o["closed"] == []


def test_a_window_that_peels_its_own_layer_keeps_the_key_for_it(box):
    """Calendar's settings panel and event form are peeled by `calendar.js`'s
    own listener; while one is open the arbiter leaves it the key (before, it
    closed Calendar first and that listener never ran)."""
    o = _case(box, """
        const cal = makeWindow('calendar-modal', 1001);
        const form = cal.body.appendChild(new Node('div'));
        form.className = 'cal-form';
        const r = escape();
        form.remove();
        const r2 = escape();
        out({ r, r2, closed });
    """)
    assert o["r"] == {"stopped": False, "prevented": False}
    assert o["r2"]["stopped"] is True and o["closed"] == ["calendar-modal"]


def test_a_dialog_that_answers_its_own_escape_keeps_it(box):
    """The palette (`search-chat.js`) and the confirm dialog close themselves;
    the window under them stays."""
    o = _case(box, """
        makeWindow('memory-modal', 1001);
        const pal = document.body.appendChild(new Node('div'));
        pal.setAttribute('id', 'search-overlay');
        const r1 = escape();
        pal.classList.add('hidden');
        const conf = document.body.appendChild(new Node('div'));
        conf.setAttribute('id', 'styled-confirm-overlay');
        const r2 = escape();
        out({ r1, r2, brain: isOpen('memory-modal'), closed });
    """)
    assert o == {"r1": {"stopped": False, "prevented": False}, "r2": {"stopped": False, "prevented": False},
                 "brain": True, "closed": []}


def test_with_no_window_the_drawer_then_the_document_pane(box):
    o = _case(box, """
        stackTop.id = 'sidebar-drawer';
        escape();
        const drawer = closed.slice();
        stackTop.id = null;
        const calls = [];
        window.documentModule = { isPanelOpen: () => true, closePanel: (d) => calls.push(d) };
        escape();
        stackTop.id = 'notes-panel';
        const under = [];
        window.documentModule = { isPanelOpen: () => true, closePanel: (d) => under.push(d) };
        const notes = escape();
        out({ drawer, calls, notes, under });
    """)
    assert o["drawer"] == ["sidebar-drawer"]
    assert o["calls"] == ["down"], "the document pane goes to its chip, as it did"
    assert o["notes"] == {"stopped": False, "prevented": False}, "Notes peels its own layers"
    assert o["under"] == [], "the document pane under Notes went first"
