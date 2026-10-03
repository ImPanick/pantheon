# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P23-01` (SET-M-7) — Settings stays open when it is opened.

Measured on `9560d50` (`s07d`, `s07e`, deterministic): cog → Settings → a click
into *Find settings…* → Escape → cog again, and Settings opened and hid itself a
quarter-second later. `hideSettingsModal` armed a `{ once: true }`
`animationend` listener and a 250 ms timer; when the window was hidden without
its exit animation playing, the listener stayed armed, and the NEXT open's
`modal-enter` animation fired it: `[5418 animationend modal-enter] [5418 modal
hidden]`. The timer had the mirror-image flaw: a window reopened inside its
250 ms was hidden by it.

Driven here: the real `static/js/settings/lifecycle.js` under node in the DOM
shim; animations are dispatched by hand, as a browser would, with the name and
the element they belong to.
"""

import shutil
from pathlib import Path

import pytest

from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
LIFECYCLE_JS = ROOT / "static" / "js" / "settings" / "lifecycle.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_SHIM = r"""
import { installDom, Node } from './dom.js';
export const document = installDom();
export { Node };
export function makeSettings() {
  const modal = document.body.appendChild(new Node('div'));
  modal.setAttribute('id', 'settings-modal');
  modal.className = 'modal hidden';
  const content = modal.appendChild(new Node('div'));
  content.className = 'modal-content settings-modal-content';
  return { modal, content };
}
export const animationEnd = (el, name, target = el) =>
  el.dispatchEvent({ type: 'animationend', animationName: name, target });
export const isOpen = (m) => !m._classes().includes('hidden');
export const wait = (ms) => new Promise((r) => setTimeout(r, ms));
"""

_STUBS = {
    "../windowDrag.js": "export function makeWindowDraggable() {}\n",
    "../modalSnap.js": "export function clearDockSide() {}\n",
}

_PREAMBLE = (
    "import { document, makeSettings, animationEnd, isOpen, wait } from './shim.js';\n"
    "import { showSettingsModal, hideSettingsModal } from './lifecycle.js';\n"
    "const out = (o) => console.log(JSON.stringify(o));\n"
)


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    root = tmp_path_factory.mktemp("setlife")
    (root / "settings").mkdir()
    shutil.copy(ROOT / "static" / "js" / "backStack.js", root / "backStack.js")   # the real one
    return _make_sandbox(root / "settings", LIFECYCLE_JS, _SHIM, _STUBS)


def _case(box, script):
    return _run(box, _PREAMBLE, script)


def test_closed_without_its_exit_animation_the_next_open_stays_open(box):
    """The measured case: no `modal-exit` ever ends; the timer hides it; the
    next open's `modal-enter` ends — and Settings stays."""
    o = _case(box, """
        const { modal, content } = makeSettings();
        showSettingsModal(modal);
        hideSettingsModal(modal);
        await wait(300);
        const closed = !isOpen(modal);
        showSettingsModal(modal);
        animationEnd(content, 'modal-enter');
        await wait(10);
        out({ closed, open: isOpen(modal) });
    """)
    assert o == {"closed": True, "open": True}


def test_reopened_while_closing_it_stays_open(box):
    o = _case(box, """
        const { modal, content } = makeSettings();
        showSettingsModal(modal);
        hideSettingsModal(modal);
        await wait(50);
        showSettingsModal(modal);           // the cog, again, inside the 250 ms
        await wait(300);
        animationEnd(content, 'modal-exit');
        out({ open: isOpen(modal), closing: content._classes().includes('modal-closing') });
    """)
    assert o == {"open": True, "closing": False}


def test_a_close_still_closes_on_its_own_exit_animation_and_not_on_a_child_s(box):
    o = _case(box, """
        const { modal, content } = makeSettings();
        showSettingsModal(modal);
        hideSettingsModal(modal);
        const child = content.appendChild(document.createElement('span'));
        animationEnd(content, 'spin', child);       // a spinner inside the window
        const afterChild = isOpen(modal);
        animationEnd(content, 'modal-exit');
        out({ afterChild, open: isOpen(modal) });
    """)
    assert o == {"afterChild": True, "open": False}
