# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1939`. On a phone, ticking an item or drawing on a note was not an edit.

On a window 768 px wide or less, Notes opens an existing note with its save
button in archive-mode: it says Archive, and pressing it archives the note
(`_buildForm`'s "tap a note to skim, then tap the check to archive"). The
button turns into Update on the first `input` or `change` the form hears.
Typing makes one. Ticking an item did not, and nor did removing one with its
x or with Backspace, indenting one with Tab, moving one by touch or by mouse,
a stroke on a drawing, its Undo, or clearing its photo. After any of those the
button still said Archive, so pressing it (or the overlay's Back chevron,
which presses it for you) archived the note without the change. The draft
autosave listens for the same events, so the change was not kept as a draft
either.

Now each of those sends an `input` that bubbles to the form: the button turns
into Update, the press saves, and the draft autosave keeps the change. A tap
on the drawing that puts nothing down, a stray mouseup elsewhere on the page,
and a drag that puts the row back where it was still leave the button alone,
and a note nobody touched still archives on the press.

Upstream Odysseus made the tick and the drawing count in 84aa9a91. Its
'Finish' label is not taken: it put a fully ticked list back into
archive-mode, so the press archived it without the last tick.

Driven (`Law 20`): the real `_wireRow`, `_wireCanvas`, `_beginChecklistGrab`,
`_onClTouchEnd`, the draft autosave and `_buildForm`'s archive-mode block and
the head of its save press are cut out of `static/js/notes.js` and run under
node, in a small DOM that delivers events through capture, target and bubble.
`tests/test_back_on_a_note_you_only_read_keeps_it_js.py` drives the same page.
"""
import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from tests.helpers.js_source import js_binding, js_definition, js_function

ROOT = Path(__file__).resolve().parents[1]
NOTES_JS = ROOT / "static" / "js" / "notes.js"
SRC = NOTES_JS.read_text(encoding="utf-8")

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_ARCHIVE_MODE = "if (isEdit && window.innerWidth <= 768)"
_SAVE_PRESS = "_saveBtnEl0.addEventListener('click', async () => {"
_ARCHIVE_BRANCH = "if (_saveBtn.classList.contains('archive-mode'))"


def top(name: str) -> str:
    """The top-level `function name(…) {…}` of `notes.js`, whole."""
    found = re.search(r"^(?:async\s+)?function %s\(" % re.escape(name), SRC, re.M)
    assert found, f"no top-level function {name} in notes.js"
    return js_definition(SRC, found.start())


def archive_mode_block() -> str:
    """`_buildForm`'s phone-only block that starts the button in archive-mode."""
    return _ARCHIVE_MODE + " " + js_function(SRC, _ARCHIVE_MODE)


def save_press_head() -> str:
    """The save button's click handler down to its archive-mode branch, as
    shipped, closed with a line that records a save instead of making one."""
    start = SRC.index(_SAVE_PRESS)
    at = SRC.index(_ARCHIVE_BRANCH, start)
    branch = js_function(SRC, _ARCHIVE_BRANCH)
    end = SRC.index(branch, at) + len(branch)
    return SRC[start:end] + "\n    pressed.push('save ' + note?.id);\n  });"


# A page: elements with capture, target and bubble; a window that keeps its
# listeners; storage; and timers that run at once.
_DOM = r"""
class Ev {
  constructor(type, init = {}) {
    this.type = type;
    this.bubbles = !!init.bubbles;
    this.target = null;
    this.stopped = false;
    this.defaultPrevented = false;
    this.key = init.key;
    this.shiftKey = !!init.shiftKey;
    this.touches = init.touches;
    this.clientX = init.clientX;
    this.clientY = init.clientY;
    this.dataTransfer = { effectAllowed: '', setData() {} };
  }
  preventDefault() { this.defaultPrevented = true; }
  stopPropagation() { this.stopped = true; }
}
globalThis.Event = Ev;

function simple(el, sel) {
  if (sel.startsWith('#')) return el.id === sel.slice(1);
  if (sel.startsWith('[')) return false;
  return sel.split('.').filter(Boolean).every((c) => el.classList.contains(c));
}

class El {
  constructor(tag, cls = '') {
    this.tagName = tag.toUpperCase();
    this.className = cls;
    this.children = [];
    this.parentNode = null;
    this.listeners = [];
    this.dataset = {};
    this.style = {};
    this.attributes = {};
    this.textContent = '';
    this.title = '';
    this.value = '';
    this.id = '';
  }
  get classList() {
    const el = this;
    const list = () => el.className.split(/\s+/).filter(Boolean);
    return {
      contains: (c) => list().includes(c),
      add: (...cs) => { el.className = [...new Set([...list(), ...cs])].join(' '); },
      remove: (...cs) => { el.className = list().filter((c) => !cs.includes(c)).join(' '); },
      toggle: (c) => {
        const on = !list().includes(c);
        if (on) el.classList.add(c); else el.classList.remove(c);
        return on;
      },
    };
  }
  get previousElementSibling() {
    const kids = this.parentNode ? this.parentNode.children : [];
    const at = kids.indexOf(this);
    return at > 0 ? kids[at - 1] : null;
  }
  get nextElementSibling() {
    const kids = this.parentNode ? this.parentNode.children : [];
    const at = kids.indexOf(this);
    return at >= 0 && at + 1 < kids.length ? kids[at + 1] : null;
  }
  appendChild(child) { return this.insertBefore(child, null); }
  insertBefore(child, ref) {
    if (child.parentNode) child.parentNode.removeChild(child);
    const at = ref ? this.children.indexOf(ref) : -1;
    if (at < 0) this.children.push(child); else this.children.splice(at, 0, child);
    child.parentNode = this;
    return child;
  }
  replaceChild(fresh, old) { this.insertBefore(fresh, old); this.removeChild(old); return old; }
  removeChild(child) {
    this.children = this.children.filter((c) => c !== child);
    child.parentNode = null;
    return child;
  }
  remove() { if (this.parentNode) this.parentNode.removeChild(this); }
  contains(node) { for (let n = node; n; n = n.parentNode) if (n === this) return true; return false; }
  descendants() { return this.children.flatMap((c) => [c, ...c.descendants()]); }
  matches(selector) {
    return selector.split(',').some((one) => {
      const parts = one.trim().split(/\s+/);
      if (!simple(this, parts[parts.length - 1])) return false;
      let up = this.parentNode;
      for (let k = parts.length - 2; k >= 0; k--) {
        while (up && !simple(up, parts[k])) up = up.parentNode;
        if (!up) return false;
        up = up.parentNode;
      }
      return true;
    });
  }
  querySelector(sel) { return this.descendants().find((n) => n.matches(sel)) || null; }
  querySelectorAll(sel) { return this.descendants().filter((n) => n.matches(sel)); }
  closest(sel) { for (let n = this; n; n = n.parentNode) if (n.matches(sel)) return n; return null; }
  setAttribute(k, v) { this.attributes[k] = String(v); }
  getAttribute(k) { return k in this.attributes ? this.attributes[k] : null; }
  removeAttribute(k) { delete this.attributes[k]; }
  addEventListener(type, fn, opts) {
    this.listeners.push({ type, fn, capture: opts === true || !!(opts && opts.capture) });
  }
  removeEventListener(type, fn) {
    this.listeners = this.listeners.filter((l) => l.type !== type || l.fn !== fn);
  }
  dispatchEvent(ev) {
    ev.target = this;
    const path = [];
    for (let n = this.parentNode; n; n = n.parentNode) path.unshift(n);
    const run = (node, phase) => {
      for (const l of node.listeners.slice()) {
        if (l.type !== ev.type) continue;
        if (phase === 'capture' && !l.capture) continue;
        if (phase === 'bubble' && l.capture) continue;
        l.fn.call(node, ev);
      }
    };
    for (const n of path) { if (ev.stopped) return !ev.defaultPrevented; run(n, 'capture'); }
    if (!ev.stopped) run(this, 'target');
    if (ev.bubbles) for (const n of path.reverse()) { if (ev.stopped) break; run(n, 'bubble'); }
    return !ev.defaultPrevented;
  }
  click() { this.dispatchEvent(new Ev('click', { bubbles: true })); }
  focus() {}
  blur() {}
  getBoundingClientRect() { return { left: 0, top: 0, right: 300, bottom: 160, width: 300, height: 160 }; }
}

const body = new El('body');
globalThis.document = {
  body,
  createElement: (tag) => new El(tag),
  querySelector: (sel) => body.querySelector(sel),
  querySelectorAll: (sel) => body.querySelectorAll(sel),
  getElementById: (id) => body.descendants().find((n) => n.id === id) || null,
};
const windowListeners = [];
globalThis.window = {
  innerWidth: 390, innerHeight: 800, devicePixelRatio: 1,
  addEventListener: (type, fn) => windowListeners.push({ type, fn }),
  removeEventListener: () => {},
};
function fireWindow(type) {
  for (const l of windowListeners.slice()) if (l.type === type) l.fn(new Ev(type));
}
globalThis.Image = class { set src(v) { this._src = v; } get src() { return this._src; } };
globalThis.getComputedStyle = () => ({ position: 'relative' });
globalThis.requestAnimationFrame = (fn) => fn();
const store = new Map();
globalThis.localStorage = {
  getItem: (k) => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => { store.set(k, String(v)); },
  removeItem: (k) => { store.delete(k); },
};
const setTimeout = (fn) => { fn(); return 0; };
const clearTimeout = () => {};

// What the save press did: 'archive N1' from the archive-mode branch, or
// 'save N1' where the real handler goes on to save.
const pressed = [];
function _archiveNoteById(id) { pressed.push('archive ' + id); return true; }
const spawnConfetti = () => {};
const attachColorPicker = () => {};
const CTX = new Proxy({}, {
  get: (t, k) => (k in t ? t[k] : () => ({})),
  set: (t, k, v) => { t[k] = v; return true; },
});
"""

_LIFTED = ("_uid", "_markDoneControl", "_safeImgSrc", "_draftKey", "_loadDraft", "_clearDraft",
           "_collectFormDraft", "_isDraftEmpty", "_wireDraftAutosave", "_collectItems", "_wireRow",
           "_wireCanvas", "_beginChecklistGrab", "_onClTouchEnd")

# An existing note opened on a phone: `_buildForm`'s order (the checklist or
# the canvas wired first, then the save press, the archive-mode block and
# the draft autosave), with the markup each of those reads.
_FORM = r"""
function phoneForm({ type = 'todo', photo = null, id = 'N1' } = {}) {
  const note = { id };
  const isEdit = true;
  const form = new El('div', 'note-form');
  form.dataset.noteType = type;
  form.appendChild(new El('input', 'note-form-title')).value = 'Groceries';
  const formBody = form.appendChild(new El('div', 'note-form-body'));
  if (type === 'todo') {
    const inputs = formBody.appendChild(new El('div', 'note-checklist-inputs'));
    ['milk', 'eggs', 'bread'].forEach((text, k) => {
      const row = inputs.appendChild(new El('div', 'note-cl-row'));
      row.dataset.itemId = 'i' + k;
      row.dataset.indent = '0';
      row.appendChild(new El('span', 'note-cl-grip'));
      row.appendChild(new El('span', 'note-cl-dot'));
      row.appendChild(new El('input', 'note-cl-text')).value = text;
      row.appendChild(new El('button', 'note-cl-rm'));
    });
    inputs.appendChild(new El('button', 'note-cl-add'));
    formBody.querySelectorAll('.note-cl-row').forEach((row) => _wireRow(row, formBody));
  } else {
    const wrap = formBody.appendChild(new El('div', 'note-form-draw-wrap'));
    const canvas = wrap.appendChild(new El('canvas', 'note-form-canvas'));
    canvas.width = 600;
    canvas.height = 320;
    canvas.getContext = () => CTX;
    wrap.appendChild(new El('button', 'note-form-draw-undo'));
    _wireCanvas(formBody, photo);
  }
  const _saveBtnEl0 = form.appendChild(new El('button', 'note-form-save'));
  _saveBtnEl0.appendChild(new El('span', 'nft-label')).textContent = 'Update';
  SAVE_PRESS
  ARCHIVE_MODE
  _wireDraftAutosave(form, note.id);
  return form;
}
function state(form) {
  const btn = form.querySelector('.note-form-save');
  return { label: btn.querySelector('.nft-label').textContent, archive: btn.classList.contains('archive-mode') };
}
function press(form) {
  const from = pressed.length;
  form.querySelector('.note-form-save').click();
  return pressed.slice(from);
}
function fire(el, type, init = {}) { el.dispatchEvent(new Event(type, { bubbles: true, ...init })); }
const at = (x, y) => ({ touches: [{ clientX: x, clientY: y }] });
"""


def page(*extra_functions: str, bindings=("_DRAFT_PREFIX", "_clDrag")) -> str:
    """The DOM, the functions lifted from `notes.js` (and any more named),
    and the phone form built the way `_buildForm` builds it."""
    lifted = [js_binding(SRC, name) for name in bindings]
    lifted += [top(name) for name in _LIFTED + tuple(extra_functions)]
    form = _FORM.replace("SAVE_PRESS", save_press_head()).replace("ARCHIVE_MODE", archive_mode_block())
    return _DOM + "\n" + "\n".join(lifted) + "\n" + form


def run(script: str, *extra_functions: str) -> dict:
    """Run `script` on the page and return the JSON it logs last."""
    done = subprocess.run(["node", "--input-type=module"], cwd=str(ROOT),
                          input=page(*extra_functions) + "\n" + textwrap.dedent(script),
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[-4000:]
    return json.loads(done.stdout.strip().splitlines()[-1])


ARCHIVE = {"label": "Archive", "archive": True}
UPDATE = {"label": "Update", "archive": False}


def test_ticking_an_item_turns_archive_into_update_and_the_press_saves_it():
    """The note opens as Archive and, untouched, the press archives it (the
    shortcut stays, `Law 1`). After a tick the button says Update, the press
    saves, and the tick is in the draft the autosave keeps."""
    out = run("""
        const untouched = phoneForm({ id: 'N0' });
        const opened = state(untouched);
        const untouchedPress = press(untouched);
        const form = phoneForm();
        form.querySelector('.note-cl-dot').click();
        const ticked = state(form);
        const draft = _loadDraft('N1');
        console.log(JSON.stringify({ opened, untouchedPress, ticked, press: press(form),
          draft: draft && draft.items.map((it) => [it.text, it.done]) }));
    """)
    assert out["opened"] == ARCHIVE
    assert out["untouchedPress"] == ["archive N0"]
    assert out["ticked"] == UPDATE, "a tick is an edit: the button must stop offering to archive"
    assert out["press"] == ["save N1"], "after a tick the press must save, not archive"
    assert out["draft"] == [["milk", True], ["eggs", False], ["bread", False]], (
        "the draft autosave must have kept the tick")


@pytest.mark.parametrize("edit", ["remove with x", "remove with Backspace", "indent with Tab"])
def test_removing_or_indenting_an_item_is_an_edit(edit):
    """Each of these changes the list without a keystroke reaching a text box."""
    out = run("""
        const form = phoneForm();
        const row = form.querySelectorAll('.note-cl-row')[1];
        const txt = row.querySelector('.note-cl-text');
        const edit = %s;
        if (edit === 'remove with x') row.querySelector('.note-cl-rm').click();
        if (edit === 'remove with Backspace') { txt.value = ''; fire(txt, 'keydown', { key: 'Backspace' }); }
        if (edit === 'indent with Tab') fire(txt, 'keydown', { key: 'Tab' });
        console.log(JSON.stringify({ state: state(form), rows: form.querySelectorAll('.note-cl-row').length,
          indent: row.dataset.indent, press: press(form) }));
    """ % json.dumps(edit))
    assert out["rows"] == (2 if edit.startswith("remove") else 3)
    assert out["indent"] == ("1" if edit == "indent with Tab" else "0")
    assert out["state"] == UPDATE, f"{edit} is an edit"
    assert out["press"] == ["save N1"]


@pytest.mark.parametrize("by", ["touch", "mouse"])
def test_a_row_moved_to_a_new_place_is_an_edit_and_one_put_back_is_not(by):
    """The order of the rows is what Save writes, so a row that ends up
    somewhere else is an edit; a drag that ends where it began changes
    nothing and leaves Archive alone."""
    out = run("""
        const by = %s;
        const drag = (form, moveTo) => {
          const inputs = form.querySelector('.note-checklist-inputs');
          const [first, second] = form.querySelectorAll('.note-cl-row');
          if (by === 'touch') {
            _beginChecklistGrab(first, inputs, { clientX: 5, clientY: 5 });
            if (moveTo) inputs.insertBefore(_clDrag.placeholder, second.nextElementSibling);
            else { inputs.insertBefore(_clDrag.placeholder, second.nextElementSibling);
                   inputs.insertBefore(_clDrag.placeholder, first); }
            _onClTouchEnd();
          } else {
            fire(first, 'dragstart');
            inputs.insertBefore(first, second.nextElementSibling);   // what dragover does
            if (!moveTo) inputs.insertBefore(first, second);
            fire(first, 'dragend');
          }
          return form.querySelectorAll('.note-cl-row').map((r) => r.querySelector('.note-cl-text').value);
        };
        const back = phoneForm();
        const backOrder = drag(back, false);
        const moved = phoneForm();
        const movedOrder = drag(moved, true);
        console.log(JSON.stringify({ backOrder, back: state(back), movedOrder, moved: state(moved) }));
    """ % json.dumps(by))
    assert out["backOrder"] == ["milk", "eggs", "bread"]
    assert out["back"] == ARCHIVE, "a row put back where it was is not an edit"
    assert out["movedOrder"] == ["eggs", "milk", "bread"]
    assert out["moved"] == UPDATE, f"a row moved by {by} is an edit"


@pytest.mark.parametrize("by", ["touch", "mouse"])
def test_a_stroke_is_an_edit_and_a_tap_or_a_stray_mouseup_is_not(by):
    """`_end` runs on every mouseup anywhere on the page, and a tap puts no
    pixel down; only a press that drew something turns the button."""
    out = run("""
        const by = %s;
        const form = phoneForm({ type: 'draw' });
        const canvas = form.querySelector('.note-form-canvas');
        const opened = state(form);
        fireWindow('mouseup');
        const stray = state(form);
        if (by === 'touch') { fire(canvas, 'touchstart', at(10, 10)); fire(canvas, 'touchend'); }
        else { fire(canvas, 'mousedown', { clientX: 10, clientY: 10 }); fireWindow('mouseup'); }
        const tap = state(form);
        if (by === 'touch') {
          fire(canvas, 'touchstart', at(10, 10)); fire(canvas, 'touchmove', at(40, 30)); fire(canvas, 'touchend');
        } else {
          fire(canvas, 'mousedown', { clientX: 10, clientY: 10 });
          fire(canvas, 'mousemove', { clientX: 40, clientY: 30 });
          fireWindow('mouseup');
        }
        console.log(JSON.stringify({ opened, stray, tap, stroke: state(form), press: press(form) }));
    """ % json.dumps(by))
    assert out["opened"] == ARCHIVE
    assert out["stray"] == ARCHIVE, "a mouseup with no stroke is not an edit"
    assert out["tap"] == ARCHIVE, "a tap that drew nothing is not an edit"
    assert out["stroke"] == UPDATE, f"a stroke drawn by {by} is an edit"
    assert out["press"] == ["save N1"]


@pytest.mark.parametrize("edit", ["clear the photo", "undo"])
def test_clearing_the_photo_or_pressing_undo_is_an_edit(edit):
    """The drawing's own buttons change it without a stroke."""
    out = run("""
        const edit = %s;
        const form = phoneForm({ type: 'draw', photo: '/api/upload/photo-1' });
        const opened = state(form);
        if (edit === 'clear the photo') form.querySelector('.note-form-draw-bg-rm').click();
        if (edit === 'undo') {
          const canvas = form.querySelector('.note-form-canvas');
          fire(canvas, 'touchstart', at(10, 10)); fire(canvas, 'touchend');   // Undo pops what this took
          form.querySelector('.note-form-draw-undo').click();
        }
        console.log(JSON.stringify({ opened, after: state(form), press: press(form) }));
    """ % json.dumps(edit))
    assert out["opened"] == ARCHIVE
    assert out["after"] == UPDATE, f"{edit} is an edit"
    assert out["press"] == ["save N1"]
