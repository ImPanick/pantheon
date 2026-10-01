# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B949` — a tool window is announced as blocking only when it blocks.

`static/js/a11y.js` (`enhanceModal`) added `aria-modal="true"` to every
`.modal-content` that lacked it, and the static tool windows lack it on purpose
(`tests/test_dialog_aria.py`: "dockable/tiling windows, so they are
role=\"dialog\" WITHOUT aria-modal"). Measured at runtime 2026-09-27: Brain,
Theme, Prompt, Rename session, Forge and Settings all carried it, and Tasks once
built. None of them blocks anything — `.modal { pointer-events: none; background:
none }` — so a screen reader that honours `aria-modal` confined its reading
cursor to the window while the chat behind it stayed usable.
`tests/test_dialog_aria.py` greps `index.html` and never sees the attribute the
script adds at runtime (`Law 20`).

The attribute now says what the overlay does, read from the overlay's computed
`pointer-events` rather than from a list of windows: the PDF export overlay
(inline `pointer-events: auto` and a backdrop, `static/js/document.js`) is
modal; every tool window on a desktop is not; on a phone every window is a
bottom sheet over a backdrop (`static/style.css`, the `max-width: 768px`
`.modal` rule) and is modal, so it is re-read when the viewport changes. A
dialog that brought its own `aria-modal` — the styled confirm and prompt — is
the author's word and is never touched.

Driven under node against the real `a11y.js` (an IIFE, imported for its side
effects) over the DOM shim of `tests/test_tool_effect_surfaces_js.py`, with a
`getComputedStyle` that answers what the stylesheet would.
"""

import shutil
from pathlib import Path

import pytest

from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
A11Y = ROOT / "static" / "js" / "a11y.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_SHIM = r"""
import { installDom, Node } from './dom.js';
export const document = installDom();
export { Node };

Node.prototype.hasAttribute = function (k) { return this.getAttribute(k) != null; };
// The module skips anything that is not an element, and the shared shim has no
// `nodeType`: without this every case below would pass by enhancing nothing.
Object.defineProperty(Node.prototype, 'nodeType', {
  configurable: true,
  get() { return this.tagName === '#TEXT' ? 3 : this.tagName === '#DOCUMENT' ? 9 : 1; },
});
export const writes = [];
const _set = Node.prototype.setAttribute;
Node.prototype.setAttribute = function (k, v) { if (k === 'aria-modal') writes.push(['set', v]); _set.call(this, k, v); };
Node.prototype.removeAttribute = function (k) { if (k === 'aria-modal') writes.push(['remove']); delete this.attrs[k]; };
// `[name="value"]` for any attribute name, read from `attrs` or `dataset` —
// the shared matcher's name pattern has no digits, and `data-a11y-*` has two.
const _matches = Node.prototype._matches;
Node.prototype._matches = function (sel) {
  const m = String(sel).trim().match(/^\[([\w-]+)="([^"]*)"\]$/);
  if (!m) return _matches.call(this, sel);
  let v = this.getAttribute(m[1]);
  if (v == null && m[1].startsWith('data-')) {
    v = this.dataset[m[1].slice(5).replace(/-([a-z0-9])/g, (x, c) => c.toUpperCase())];
  }
  return v === m[2];
};

// What `static/style.css` computes for the overlays: `.modal` lets the page
// through on a desktop and takes it on a phone; the Notes backdrop lets it
// through; an inline `pointer-events` (the PDF export) wins over both.
globalThis.__phone = false;
globalThis.getComputedStyle = (el) => ({
  pointerEvents: el.style.pointerEvents
    || (el.classList.contains('modal') ? (globalThis.__phone ? 'auto' : 'none')
      : el.classList.contains('notes-pane-backdrop') ? 'none' : 'auto'),
});
const listeners = {};
globalThis.addEventListener = (type, fn) => { (listeners[type] = listeners[type] || []).push(fn); };
globalThis.removeEventListener = () => {};
globalThis.requestAnimationFrame = (fn) => setTimeout(() => fn(0), 0);
globalThis.MutationObserver = class {
  constructor(fn) { this.fn = fn; (globalThis.__observers = globalThis.__observers || []).push(this); }
  observe(target) { this.target = target; }
  disconnect() {}
};
export const tick = (ms = 5) => new Promise((r) => setTimeout(r, ms));
export function fire(type) { (listeners[type] || []).forEach((fn) => fn({ type })); }

/** A window as the markup or a module builds it: an overlay and its content. */
export function makeWindow(name, { overlayClass = 'modal', contentClass = 'modal-content', inline = null,
                                   ownModal = null } = {}) {
  const overlay = document.createElement('div');
  overlay.className = overlayClass;
  if (inline) overlay.style.pointerEvents = inline;
  const content = overlay.appendChild(document.createElement('div'));
  content.className = contentClass;
  content.setAttribute('aria-label', name);
  if (ownModal) content.setAttribute('aria-modal', ownModal);
  return { overlay, content };
}
/** Append at runtime, and tell the module's body observer, as a browser would. */
export function append(w) {
  document.body.appendChild(w.overlay);
  for (const o of globalThis.__observers || []) {
    if (o.target === document.body) o.fn([{ type: 'childList', addedNodes: [w.overlay] }]);
  }
  return w;
}
export const modal = (w) => w.content.getAttribute('aria-modal');
"""

_PREAMBLE = (
    "import { document, writes, tick, fire, makeWindow, append, modal } from './shim.js';\n"
)


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    return _make_sandbox(tmp_path_factory.mktemp("ariamodal"), A11Y, _SHIM, {})


def _go(sandbox, script):
    return _run(sandbox, _PREAMBLE, script)


def test_a_tool_window_in_the_markup_is_a_dialog_and_not_modal(sandbox):
    """Brain, Theme, Settings… are in `index.html` when the module starts."""
    out = _go(sandbox, """
        const w = makeWindow('Brain');
        document.body.appendChild(w.overlay);
        await import('./a11y.js');
        console.log(JSON.stringify({ role: w.content.getAttribute('role'), modal: modal(w) }));
    """)
    assert out["role"] == "dialog"
    assert out["modal"] is None, "a window that blocks nothing is announced as blocking"


def test_a_tool_window_built_later_is_not_modal_either(sandbox):
    """The row's `Verify`: open Tasks — built at runtime — and its dialog has no
    `aria-modal`; open the PDF export, and it does."""
    out = _go(sandbox, """
        await import('./a11y.js');
        const tasks = append(makeWindow('Tasks'));
        const pdf = append(makeWindow('Export filled PDF', { overlayClass: 'modal pdf-export-overlay',
                                                             inline: 'auto' }));
        console.log(JSON.stringify({ tasks: modal(tasks), pdf: modal(pdf),
                                     tasksRole: tasks.content.getAttribute('role') }));
    """)
    assert out["tasks"] is None
    assert out["tasksRole"] == "dialog"
    assert out["pdf"] == "true", "the PDF export takes the pointer and has a backdrop: it is modal"


def test_on_a_phone_every_window_is_a_sheet_over_a_backdrop_and_is_modal(sandbox):
    """`static/style.css` turns `.modal` into a bottom sheet with a backdrop and
    `pointer-events: auto` under 768px, so there the windows do block. Re-read
    when the viewport changes, both ways."""
    out = _go(sandbox, """
        await import('./a11y.js');
        const w = append(makeWindow('Settings'));
        const desktop = modal(w);
        globalThis.__phone = true; fire('resize'); await tick();
        const phone = modal(w);
        globalThis.__phone = false; fire('resize'); await tick();
        console.log(JSON.stringify({ desktop, phone, back: modal(w) }));
    """)
    assert out == {"desktop": None, "phone": "true", "back": None}


def test_a_dialog_that_brings_its_own_aria_modal_keeps_it(sandbox):
    """The styled confirm and prompt (`ui.js`) are blocking dialogs and say so
    in their own markup; the module never second-guesses an author."""
    out = _go(sandbox, """
        await import('./a11y.js');
        const confirm = append(makeWindow('Confirm', { ownModal: 'true' }));
        fire('resize'); await tick();
        console.log(JSON.stringify({ confirm: modal(confirm) }));
    """)
    assert out["confirm"] == "true"


def test_the_notes_pane_is_not_modal(sandbox):
    out = _go(sandbox, """
        await import('./a11y.js');
        const notes = append(makeWindow('Notes', { overlayClass: 'notes-pane-backdrop',
                                                   contentClass: 'notes-pane' }));
        console.log(JSON.stringify({ notes: modal(notes), role: notes.content.getAttribute('role') }));
    """)
    assert out == {"notes": None, "role": "dialog"}


def test_a_resize_that_changes_nothing_writes_nothing(sandbox):
    """`B923`/`B924`'s rule for anything a resize or an observer can call
    repeatedly: write only what changed."""
    out = _go(sandbox, """
        await import('./a11y.js');
        const a = append(makeWindow('Tasks'));
        const b = append(makeWindow('Export', { overlayClass: 'modal pdf-export-overlay', inline: 'auto' }));
        const before = writes.length;
        fire('resize'); await tick(); fire('resize'); await tick(); fire('load');
        console.log(JSON.stringify({ extra: writes.slice(before) }));
    """)
    assert out["extra"] == []
