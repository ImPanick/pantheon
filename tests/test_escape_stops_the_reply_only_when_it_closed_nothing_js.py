# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B945` — Escape stops the reply only when it closed nothing.

`static/js/keyboard-shortcuts.js` ran `chatModule.abortCurrentRequest()` for
`cancel: 'escape'` on every keydown that reached `document`. **Measured
2026-10-01** in Chromium against the running app, counting calls to the abort:
with the focus on a window's own button the `ui.js` arbiter already closed the
window and stopped the key, so the row's "every Escape anywhere" was too wide —
but with the focus in the message box, which is where a person is while a reply
streams, Calendar, Tasks, Gallery, Library, Deep Research, Forge, Theme, Brain,
Compare and Settings each closed **and** the reply stopped, and so did Settings
with its own finder focused. One key, two things.

The decision: Escape stays the stop key (registered, rebindable, *Cancel /
close*), and it peels one layer per press. The stop is decided last, on
`window` once every other listener has had the key, and the key counts as
claimed when a listener said so (`preventDefault`, or stopped it), when it was
typed inside a window, dialog, menu or the palette, when something on the page
closed during the press (`escapeLayerPrint` before the first listener and after
the last), or while an input method composes. The page-wide chain in `app.js`
now says so when it closes something.

Driven under node (`Law 20`): the real `keyboard-shortcuts.js`, its real
`initKeyboardShortcuts`, over a DOM whose events travel window → document →
target → document → window in both phases, as a browser's do. The `app.js`
chain and the real windows are driven in Chromium by
`tests/test_the_windows_in_a_browser.py`.
"""

import shutil
from pathlib import Path

import pytest

from test_tool_effect_surfaces_js import _run  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_SHIM = r"""
export class Ev {
  constructor(type, init = {}) {
    Object.assign(this, { type, bubbles: true, cancelable: true, defaultPrevented: false,
      ctrlKey: false, altKey: false, shiftKey: false, metaKey: false, repeat: false, isComposing: false,
      propagationStopped: false, immediate: false }, init);
  }
  preventDefault() { if (this.cancelable) this.defaultPrevented = true; }
  stopPropagation() { this.propagationStopped = true; }
  stopImmediatePropagation() { this.propagationStopped = true; this.immediate = true; }
  getModifierState() { return false; }
}
class Target {
  constructor() { this._l = []; this.parentNode = null; }
  addEventListener(type, fn, o) { this._l.push({ type, fn, capture: o === true || !!(o && o.capture) }); }
  removeEventListener() {}
  _fire(ev, phase) {
    for (const l of [...this._l]) {
      if (l.type !== ev.type || (phase === 'capture' && !l.capture) || (phase === 'bubble' && l.capture)) continue;
      l.fn.call(this, ev);
      if (ev.immediate) return;
    }
  }
  dispatchEvent(ev) {
    ev.target = this;
    const path = [];
    for (let n = this.parentNode; n; n = n.parentNode) path.push(n);
    for (const n of [...path].reverse()) { n._fire(ev, 'capture'); if (ev.propagationStopped) return; }
    this._fire(ev, 'target');
    if (ev.bubbles) for (const n of path) { if (ev.propagationStopped) break; n._fire(ev, 'bubble'); }
  }
}
class ClassList {
  constructor(el) { this.el = el; }
  _s() { return String(this.el.className || '').split(/\s+/).filter(Boolean); }
  add(...c) { this.el.className = [...new Set([...this._s(), ...c])].join(' '); }
  remove(...c) { this.el.className = this._s().filter((x) => !c.includes(x)).join(' '); }
  contains(c) { return this._s().includes(c); }
  toggle(c, on) { const want = on === undefined ? !this.contains(c) : !!on; if (want) this.add(c); else this.remove(c); }
}
export class El extends Target {
  constructor(tag, id = '', cls = '') {
    super();
    Object.assign(this, { tagName: tag.toUpperCase(), id, className: cls, attrs: {}, children: [],
      hidden: false, style: {}, value: '' });
    this.classList = new ClassList(this);
  }
  append(child) { child.parentNode = this; this.children.push(child); return child; }
  remove() { const p = this.parentNode; if (p) p.children = p.children.filter((c) => c !== this); this.parentNode = null; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  matches(sel) {
    return sel.split(',').map((s) => s.trim()).some((s) => {
      if (s.startsWith('#')) return this.id === s.slice(1);
      if (s.startsWith('.')) return this.classList.contains(s.slice(1));
      const m = /^\[role="([^"]+)"\]$/.exec(s);
      return !!m && this.attrs.role === m[1];
    });
  }
  closest(sel) { for (let n = this; n instanceof El; n = n.parentNode) if (n.matches(sel)) return n; return null; }
  focus() { document.activeElement = this; }
}
class Doc extends Target {
  constructor() { super(); this.body = new El('body'); this.body.parentNode = this; }
  _all(n = this.body, out = []) { out.push(n); n.children.forEach((c) => this._all(c, out)); return out; }
  getElementById(id) { return this._all().find((n) => n.id === id) || null; }
  querySelectorAll(sel) { return this._all().filter((n) => n.matches(sel)); }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
}
class Win extends Target {}
export const win = new Win();
export const document = new Doc();
document.parentNode = win;
globalThis.window = globalThis;
globalThis.document = document;
globalThis.addEventListener = (...a) => win.addEventListener(...a);
globalThis.removeEventListener = () => {};
globalThis.getComputedStyle = () => ({ display: 'block', visibility: 'visible', opacity: '1' });

export const composer = document.body.append(new El('textarea', 'message'));
/** A tool window as the page has them: a `.modal` child of `<body>`. */
export function toolWindow(id) {
  const m = document.body.append(new El('div', id, 'modal'));
  const content = m.append(new El('div', '', 'modal-content'));
  const input = content.append(new El('input', id + '-search'));
  return { m, content, input };
}
export function press(target, key = 'Escape', init = {}) {
  const ev = new Ev('keydown', Object.assign({ key }, init));
  target.dispatchEvent(ev);
  return ev;
}
"""

_PREAMBLE = r"""
import { document, win, composer, toolWindow, press, El } from './shim.js';
import * as KS from './keyboard-shortcuts.js';
let stops = 0;
KS.initKeyboardShortcuts({
  el: (id) => document.getElementById(id), Storage: {}, sessionModule: null, uiModule: {},
  chatModule: { abortCurrentRequest() { stops += 1; } },
  adminModule: null, settingsModule: null, searchChatModule: null,
  _closeCompareIfActive: () => false, _deactivateIncognito: () => {}, API_BASE: '',
});
const said = () => stops;
"""


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    d = tmp_path_factory.mktemp("escstop")
    (d / "shim.js").write_text(_SHIM, encoding="utf-8")
    (d / "appConfig.js").write_text(
        "export function getSettings() { return Promise.resolve({}); }\n", encoding="utf-8")
    shutil.copy(JS / "keyboard-shortcuts.js", d / "keyboard-shortcuts.js")
    shutil.copy(JS / "platform.js", d / "platform.js")
    return d


def _go(box, script):
    return _run(box, _PREAMBLE, script)


def test_with_nothing_open_escape_in_the_message_box_stops_the_reply(box):
    """The key keeps its job. Nothing to close: Escape is the stop."""
    out = _go(box, "press(composer); console.log(JSON.stringify({ stops: said() }));")
    assert out["stops"] == 1


def test_a_window_a_listener_closes_is_the_only_thing_escape_does(box):
    """The measured case: the focus in the message box, a window open, and a
    module's own listener on `document` closing it — without saying so, as
    Calendar's and Settings' do. The window goes; the reply keeps drawing."""
    out = _go(box, """
        const cal = toolWindow('calendar-modal');
        document.addEventListener('keydown', (e) => { if (e.key === 'Escape') cal.m.classList.add('hidden'); });
        press(composer);
        console.log(JSON.stringify({ stops: said(), closed: cal.m.classList.contains('hidden') }));
    """)
    assert out == {"stops": 0, "closed": True}


@pytest.mark.parametrize("how", ["removed", "closing", "docked"])
def test_every_way_a_window_closes_counts(box, how):
    """A popup removed from `<body>`; a window animating shut (`dismissModal`
    marks `.modal-closing` and hides it on `animationend`); a docked panel that
    shows only on `<body>`'s own classes (`doc-view`)."""
    out = _go(box, """
        const how = %r;
        const w = toolWindow('lightbox');
        if (how === 'docked') document.body.className = 'doc-view';
        document.addEventListener('keydown', (e) => {
          if (e.key !== 'Escape') return;
          if (how === 'removed') w.m.remove();
          if (how === 'closing') w.content.classList.add('modal-closing');
          if (how === 'docked') document.body.className = '';
        });
        press(composer);
        console.log(JSON.stringify({ stops: said() }));
    """ % how)
    assert out["stops"] == 0


def test_a_listener_that_claims_the_key_keeps_the_reply(box):
    """`app.js`'s page-wide chain now marks the key when it closes something."""
    out = _go(box, """
        document.addEventListener('keydown', (e) => { if (e.key === 'Escape') e.preventDefault(); });
        press(composer);
        console.log(JSON.stringify({ stops: said() }));
    """)
    assert out["stops"] == 0


def test_a_listener_that_stops_the_key_on_document_keeps_the_reply(box):
    """Settings' lifecycle listener closes the window and stops propagation on
    `document`. The old stop sat on that same node, so `stopPropagation` could
    not keep it from running."""
    out = _go(box, """
        const s = toolWindow('settings-modal');
        document.addEventListener('keydown', (e) => {
          if (e.key !== 'Escape') return;
          s.m.classList.add('hidden'); e.stopPropagation();
        });
        press(composer);
        console.log(JSON.stringify({ stops: said() }));
    """)
    assert out["stops"] == 0


def test_an_escape_typed_inside_a_window_belongs_to_that_window(box):
    """Settings with its own finder focused: measured, Settings closed and the
    reply stopped. The key belongs to the window that has the focus, even when
    that window does nothing with it."""
    out = _go(box, """
        const s = toolWindow('settings-modal');
        press(s.input);
        const menu = document.body.append(new El('div', 'menu'));
        menu.setAttribute('role', 'menu');
        const item = menu.append(new El('button', 'item'));
        press(item);
        console.log(JSON.stringify({ stops: said() }));
    """)
    assert out["stops"] == 0


def test_an_input_method_composing_keeps_the_reply(box):
    out = _go(box, """
        press(composer, 'Escape', { isComposing: true });
        console.log(JSON.stringify({ stops: said() }));
    """)
    assert out["stops"] == 0


def test_the_stop_follows_the_key_it_is_bound_to(box):
    """`cancel` is rebindable. Bound elsewhere, the new key stops the reply and
    Escape does not."""
    out = _go(box, """
        window._pantheonKeybinds = Object.assign({}, window._pantheonKeybinds, { cancel: 'ctrl+alt+x' });
        press(composer, 'Escape');
        const afterEscape = said();
        press(composer, 'x', { ctrlKey: true, altKey: true });
        console.log(JSON.stringify({ afterEscape, afterChord: said() }));
    """)
    assert out == {"afterEscape": 0, "afterChord": 1}


def test_a_window_left_open_does_not_hold_the_key(box):
    """Notes, docked beside the chat, takes no Escape from the message box; so
    there Escape has nothing to close and stops the reply — the rule is "closed
    nothing", not "nothing is open"."""
    out = _go(box, """
        const notes = document.body.append(new El('div', 'notes-pane-backdrop', 'notes-pane-backdrop'));
        notes.append(new El('div', 'notes-pane', 'notes-pane'));
        press(composer);
        console.log(JSON.stringify({ stops: said() }));
    """)
    assert out["stops"] == 1
