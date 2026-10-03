# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P23-01` — the window manager's half of the way back (`modalManager.js`).

Measured on `9560d50`:

  * **NAV-M-12.** A dock chip was one `<button>` whose × was a `<span>` inside
    it: Tab reached the chip and never the ×, so a minimised window could not
    be closed from the keyboard; and restoring one left the focus on `<body>`.
  * **NAV-U-4 / C-NAV.** A window opened from another said nothing about it —
    Settings › Integrations → the Workbench, Brain → Skills, Email → the room —
    and closing it was the only way back, with nothing on screen saying so.

Driven here: the real `modalManager.js` and the real `backStack.js` under node,
in the dock sandbox `tests/test_background_work_dock_js.py` built (its stubs and
DOM shim, imported, not copied): `showWindow(id, { from, tab })` — contract
C-NAV — draws `← <opener>` at the start of the opened window's header, the
button closes that window the way its × does, and `register`'s `getTab` /
`setTab` outlive a close; the chip holds a *Restore* button and a *Close*
button named for the window, and restoring from it gives the window's move
handle the focus.
"""

import shutil

import pytest

from test_background_work_dock_js import MODALS_JS, _SHIM as _DOCK_SHIM, _STUBS  # noqa: E402
from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_SHIM = _DOCK_SHIM + r"""
// `register` watches its window with a `MutationObserver`; nothing here needs
// it to fire (the back stack is read with an explicit `sync()`).
globalThis.MutationObserver = class { observe() {} disconnect() {} };
Node.prototype.contains = function (n) { for (let x = n; x; x = x.parentNode) if (x === this) return true; return false; };
Node.prototype.focus = function () { this.focused = true; document.activeElement = this; };
Node.prototype.closest = function (sel) { for (let x = this; x && x.matches; x = x.parentNode) if (x.matches(sel)) return x; return null; };

/** A tool window: `.modal#id > .modal-content > .modal-header > (h4, .window-move-handle, .close-btn)`. */
export function makeWindow(id, title) {
  const modal = document.body.appendChild(new Node('div'));
  modal.setAttribute('id', id);
  modal.className = 'modal';
  const content = modal.appendChild(new Node('div'));
  content.className = 'modal-content';
  const header = content.appendChild(new Node('div'));
  header.className = 'modal-header';
  const h = header.appendChild(new Node('h4'));
  h.textContent = title;
  const handle = header.appendChild(new Node('button'));
  handle.className = 'window-move-handle';
  const close = header.appendChild(new Node('button'));
  close.className = 'close-btn';
  close.addEventListener('click', () => { modal.classList.add('hidden'); modal.closedBy = 'x'; });
  return { modal, header, handle, close };
}
export const headerKids = (w) => w.header.childNodes.map((n) => n.className || n.tagName);
/** A click as a browser delivers it: on the node, then up through its parents. */
export function press(node) {
  const ev = { type: 'click', target: node, stopped: false,
    stopPropagation() { this.stopped = true; }, preventDefault() {} };
  for (let n = node; n && !ev.stopped; n = n.parentNode) {
    ev.currentTarget = n;
    (n.listeners && n.listeners.click || []).slice().forEach((fn) => fn(ev));
  }
}
"""

_PREAMBLE = (
    "import { document, Node, click, press, readDock, makeWindow, headerKids } from './shim.js';\n"
    "import * as Modals from './modalManager.js';\n"
    "import backStack from './backStack.js';\n"
    "const out = (o) => console.log(JSON.stringify(o));\n"
)


@pytest.fixture(scope="module")
def mm(tmp_path_factory):
    return _make_sandbox(tmp_path_factory.mktemp("wayback"), MODALS_JS, _SHIM, _STUBS)


def _case(sandbox, script):
    return _run(sandbox, _PREAMBLE, script)


def test_a_window_opened_from_another_says_back_to_it_and_the_button_closes_it(mm):
    o = _case(mm, """
        const brain = makeWindow('memory-modal', 'Brain');
        const skills = makeWindow('skills-modal', 'Skills');
        backStack.sync();                       // both up, neither opened from the other
        const before = headerKids(skills);
        Modals.showWindow('skills-modal', { from: 'memory-modal', tab: 'rag' });
        const btn = skills.header.querySelector('.modal-back-btn');
        const drawn = { first: skills.header.childNodes[0] === btn, text: btn.textContent,
                        label: btn.getAttribute('aria-label'), backTo: btn.dataset.backTo };
        const stack = backStack.stack();
        click(btn);
        out({ before, drawn, stack, closedBy: skills.modal.closedBy || null, brainUp: !brain.modal._classes().includes('hidden') });
    """)
    assert "modal-back-btn" not in o["before"]
    assert o["drawn"] == {"first": True, "text": "← Brain", "label": "Back to Brain", "backTo": "memory-modal"}
    assert o["stack"][-1] == {"id": "skills-modal", "from": "memory-modal", "tab": "rag"}
    assert o["closedBy"] == "x", "`←` closes the window through its own ×"
    assert o["brainUp"] is True


def test_the_button_goes_when_the_window_has_no_opener(mm):
    o = _case(mm, """
        const w = makeWindow('workbench-modal', 'Workbench');
        makeWindow('settings-modal', 'Settings');
        Modals.drawBackButton('workbench-modal', 'settings-modal');
        const had = !!w.header.querySelector('.modal-back-btn');
        Modals.drawBackButton('workbench-modal', 'settings-modal');
        const once = w.header.querySelectorAll('.modal-back-btn').length;
        Modals.drawBackButton('workbench-modal', null);
        out({ had, once, gone: !w.header.querySelector('.modal-back-btn') });
    """)
    assert o == {"had": True, "once": 1, "gone": True}


def test_tab_hooks_outlive_a_close(mm):
    """C-NAV: a window with tabs gives `getTab` and `setTab` at `register`; a
    reload or a `←` asks them of a window that has been closed since."""
    o = _case(mm, """
        makeWindow('settings-modal', 'Settings');
        let tab = 'appearance';
        Modals.register('settings-modal', { getTab: () => tab, setTab: (t) => { tab = t; } });
        Modals.close('settings-modal');
        const h = Modals.tabHooks('settings-modal');
        h.setTab('shortcuts');
        out({ registered: Modals.isRegistered('settings-modal'), got: h.getTab() });
    """)
    assert o == {"registered": False, "got": "shortcuts"}


def test_the_chip_close_is_a_real_button_named_for_the_window(mm):
    """NAV-M-12. Two buttons on the chip — Restore and Close — so Tab reaches
    both; Close closes, and Restore puts the focus on the window's handle."""
    o = _case(mm, """
        const t = makeWindow('tasks-modal', 'Tasks');
        const g = makeWindow('gallery-modal', 'Gallery');
        Modals.register('tasks-modal', { closeFn: () => {} });
        Modals.register('gallery-modal', { closeFn: () => {} });
        Modals.minimize('tasks-modal');
        Modals.minimize('gallery-modal');
        const chip = document.querySelectorAll('.minimized-dock-chip').find((c) => c.dataset.modalId === 'tasks-modal');
        const buttons = chip.querySelectorAll('button').map((b) => ({ cls: b.className, type: b.type,
          label: b.getAttribute('aria-label') }));
        document.activeElement = document.body;
        press(chip.querySelector('.minimized-dock-restore'));
        const restored = { up: !t.modal._classes().includes('hidden'), focus: document.activeElement === t.handle };
        const chipG = document.querySelectorAll('.minimized-dock-chip').find((c) => c.dataset.modalId === 'gallery-modal');
        press(chipG.querySelector('.minimized-dock-x'));
        out({ tag: chip.tagName, role: chip.getAttribute('role'), buttons, restored,
              galleryState: Modals.windowState('gallery-modal'), chips: readDock().map((c) => c.id) });
    """)
    assert o["tag"] == "DIV" and o["role"] == "group"
    assert o["buttons"] == [
        {"cls": "minimized-dock-restore", "type": "button", "label": None},
        {"cls": "minimized-dock-x", "type": "button", "label": "Close Tasks"},
    ]
    assert o["restored"] == {"up": True, "focus": True}
    assert o["galleryState"] == "closed" and o["chips"] == []


def test_close_window_takes_the_path_the_x_takes(mm):
    """Escape, Back and `←` all close through `closeWindow`: the window's own
    close button when it has one, so a window that asks first still asks."""
    o = _case(mm, """
        const w = makeWindow('calendar-modal', 'Calendar');
        // Registered for the dock, as Calendar is: its × still comes first —
        // `Modals.close` would hide it whatever its own close decided.
        Modals.register('calendar-modal', { closeFn: () => {} });
        let asked = 0;
        w.close.listeners.click = [() => { asked += 1; }];    // a window that asks and stays
        Modals.closeWindow('calendar-modal');
        const drawer = [];
        window._odyCloseSidebar = () => drawer.push('closed');
        Modals.closeWindow('sidebar-drawer');
        const notes = [];
        window.notesModule = { closePanel: (d) => notes.push(d === undefined ? 'close' : d) };
        Modals.closeWindow('notes-panel');
        out({ asked, up: !w.modal._classes().includes('hidden'), drawer, notes });
    """)
    assert o == {"asked": 1, "up": True, "drawer": ["closed"], "notes": ["close"]}
