# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1741` — a queued message is its number, its words, *Edit* and *Steer now*.

The owner, 2026-11-01, on the strip the composer drew for every run ("Working…
⌘⏎ steers, ⏎ queues · Steer now"): *"we know it's working — not sure it's
needed until a message pops up in queue, and even then the message should be
unaccompanied, aside from an Edit and a Steer Now button, and a number assigned
to position in queue."*

So the strip is gone (`tests/test_chat_steer_js.py` pins that `chatStream.js`
now only *offers* a steer, on `pantheon:steer-offer`), and the `Law 15` control
moved onto the one surface that exists exactly when a message is waiting: the
docked queue's row. This file drives the REAL `static/js/queuePanel.js` under
node — the module is imported unmodified beside stub copies of its five
imports and a DOM shim just large enough to render a list and take a click —
and reads back what the row is made of. No jsdom (zero external dependencies),
no source-text greps standing in for behaviour (`Law 20`).

What is pinned, and why each one is a defect if it breaks:

  * A queued message the person can still change is `N.` + its text + *Edit*
    + *Steer now* + ×. No status lamp, no *Waiting*, no clock: the number says
    it is waiting, and the buttons say what can be done with it. (The panel's
    other five words, for a message that has left the queue, are pinned in
    `tests/test_one_queued_message_one_word.py`.)
  * *Steer now* is offered only while the run in flight can take a steer —
    `chatStream.js`'s answer, asked through the driver — and reads *Send now*
    otherwise, because a button that says *steer* on a Chat turn, or on an old
    server with no steer route, is the `Law 13` failure the old strip was most
    exposed to. A message carrying a picture reads *Send now* even while a
    steer is on offer (`B1280`: a steer is words only).
  * Pressing *Steer now* hands THAT row's id to `driver.steerNow` and nothing
    else; pressing *Send now* still goes to `driver.startNow`.
  * The row re-reads the offer when `pantheon:steer-offer` fires, without
    anyone calling `refresh()` — the stream answers after the row is drawn.
  * A launched run (not editable) keeps the activity view's lamp, word, elapsed
    time and stop button: that cluster is about a job in flight, not about a
    message waiting, and the owner's ask was about the second.
  * *Edit* opens the row's editor and, pressed again, commits through
    `driver.update` — the same door the row itself is.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"
pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

# Stubs for the module's imports that the row does not need. `runStatus.js`
# and `icons.js` are copied in REAL, because the row's words and glyphs come
# out of them and a stub would make the panel agree with this file instead of
# with the product.
_STUBS = {
    "research/jobs.js": "export function formatElapsed(ms) { return Math.round(ms / 1000) + 's'; }\n",
    "dragSort.js": "export default { enable() {} };\n",
    "runModePicker.js": "export function promptRunMode() { return null; }\n",
}

_SHIM = r"""
// ── A DOM shim: a real tree, a small selector engine, a click that bubbles ──
const byId = new Map();
function parseCompound(s) {
  const out = { tag: null, classes: [], id: null, attrs: [] };
  const re = /([a-zA-Z][\w-]*)|\.([\w-]+)|#([\w-]+)|\[([\w-]+)(?:="([^"]*)")?\]/g;
  let m;
  while ((m = re.exec(s))) {
    if (m[1]) out.tag = m[1].toLowerCase();
    else if (m[2]) out.classes.push(m[2]);
    else if (m[3]) out.id = m[3];
    else if (m[4]) out.attrs.push([m[4], m[5] == null ? null : m[5]]);
  }
  return out;
}
function matchesCompound(el, c) {
  if (!el || !el._isEl) return false;
  if (c.tag && el.tagName.toLowerCase() !== c.tag) return false;
  if (c.id && el.id !== c.id) return false;
  for (const k of c.classes) if (!el.classList.contains(k)) return false;
  for (const [k, v] of c.attrs) {
    const got = el.getAttribute(k);
    if (got == null) return false;
    if (v != null && got !== v) return false;
  }
  return true;
}
function matches(el, selector) {
  const parts = selector.trim().split(/\s+/).map(parseCompound);
  let node = el;
  if (!matchesCompound(node, parts[parts.length - 1])) return false;
  let i = parts.length - 2;
  node = node.parentNode;
  while (i >= 0 && node) {
    if (matchesCompound(node, parts[i])) i--;
    node = node.parentNode;
  }
  return i < 0;
}
function walk(el, fn) { for (const c of el.childNodes) { fn(c); walk(c, fn); } }
class El {
  constructor(tag) {
    this._isEl = true; this.tagName = String(tag).toUpperCase();
    this.childNodes = []; this.parentNode = null; this._attrs = {};
    this.dataset = {}; this.style = {}; this.listeners = {};
    this.hidden = false; this.value = ''; this.selected = false; this.disabled = false;
    this._text = ''; this._html = ''; this.focused = false; this.selectionStart = 0; this.selectionEnd = 0;
    const self = this;
    this.classList = {
      _set: new Set(),
      add(...c) { c.forEach(k => this._set.add(k)); },
      remove(...c) { c.forEach(k => this._set.delete(k)); },
      contains(k) { return this._set.has(k); },
      toggle(k, force) {
        const on = force == null ? !this._set.has(k) : !!force;
        if (on) this._set.add(k); else this._set.delete(k);
        return on;
      },
    };
  }
  get id() { return this._attrs.id || ''; }
  set id(v) { this._attrs.id = String(v); byId.set(String(v), this); }
  get className() { return [...this.classList._set].join(' '); }
  set className(v) { this.classList._set = new Set(String(v).split(/\s+/).filter(Boolean)); }
  get title() { return this._attrs.title || ''; }
  set title(v) { this._attrs.title = String(v); }
  get type() { return this._attrs.type || ''; }
  set type(v) { this._attrs.type = String(v); }
  get rows() { return this._attrs.rows; }
  set rows(v) { this._attrs.rows = v; }
  getAttribute(k) {
    if (k.startsWith('data-')) {
      const key = k.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase());
      return Object.prototype.hasOwnProperty.call(this.dataset, key) ? String(this.dataset[key]) : null;
    }
    if (k === 'class') return this.className;
    return Object.prototype.hasOwnProperty.call(this._attrs, k) ? this._attrs[k] : null;
  }
  setAttribute(k, v) { if (k === 'class') this.className = v; else if (k === 'id') this.id = v; else this._attrs[k] = String(v); }
  appendChild(n) { n.parentNode = this; this.childNodes.push(n); return n; }
  remove() { if (this.parentNode) { const a = this.parentNode.childNodes; const i = a.indexOf(this); if (i >= 0) a.splice(i, 1); } this.parentNode = null; }
  get textContent() { return this.childNodes.length ? this.childNodes.map(c => c.textContent).join('') : (this._text || (this._html ? this._html.replace(/<[^>]*>/g, '') : '')); }
  set textContent(v) { this._text = String(v); this.childNodes = []; this._html = ''; }
  get innerHTML() { return this._html; }
  set innerHTML(v) { this._html = String(v); this._text = ''; this.childNodes = []; }
  get children() { return this.childNodes; }
  querySelectorAll(sel) { const out = []; walk(this, (c) => { if (c._isEl && sel.split(',').some(s => matches(c, s))) out.push(c); }); return out; }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  closest(sel) { let n = this; while (n) { if (n._isEl && matches(n, sel)) return n; n = n.parentNode; } return null; }
  contains(n) { let p = n; while (p) { if (p === this) return true; p = p.parentNode; } return false; }
  addEventListener(t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); }
  removeEventListener() {}
  focus() { this.focused = true; globalThis.document.activeElement = this; }
  setSelectionRange(a, b) { this.selectionStart = a; this.selectionEnd = b; }
  /** A click on this element, delivered to every ancestor's listeners as the
   *  browser would: `target` is this node, `closest` walks up from it. */
  click() {
    const ev = { type: 'click', target: this, stopPropagation() {}, preventDefault() {} };
    let n = this;
    while (n) { (n.listeners.click || []).forEach(fn => fn(ev)); n = n.parentNode; }
  }
}
const panelRoot = new El('div'); panelRoot.id = 'queue-panel';
for (const id of ['queue-panel-fold', 'queue-panel-chevron', 'queue-panel-icon', 'queue-panel-count',
                  'queue-panel-state', 'queue-panel-pause', 'queue-panel-body', 'queue-panel-list',
                  'queue-panel-run', 'queue-panel-hint']) {
  const el = new El(id.includes('fold') || id.includes('pause') || id.includes('run') ? 'button' : 'div');
  el.id = id; panelRoot.appendChild(el);
}
globalThis.document = {
  activeElement: null,
  body: panelRoot,
  createElement: (t) => new El(t),
  getElementById: (id) => byId.get(id) || null,
  querySelector: (sel) => panelRoot.querySelector(sel),
  querySelectorAll: (sel) => panelRoot.querySelectorAll(sel),
  addEventListener() {},
};
const winListeners = {};
globalThis.window = {
  addEventListener(t, fn) { (winListeners[t] = winListeners[t] || []).push(fn); },
  dispatchEvent(ev) { (winListeners[ev.type] || []).forEach(fn => fn(ev)); return true; },
};
globalThis.CustomEvent = class { constructor(type, init) { this.type = type; this.detail = (init && init.detail) || null; } };
globalThis.CSS = { escape: (s) => String(s).replace(/"/g, '\\"') };

// ── A driver: the contract `chat.js` injects, with every call recorded ──────
const calls = [];
let queue = [];
let steerable = false;
const driver = {
  getEntries: () => queue.map(q => ({ ...q })),
  getSessionId: () => 's1',
  isPaused: () => false,
  isBusy: () => true,
  canSteer: () => steerable,
  steerKeyLabel: () => 'Ctrl+⏎',
  steerNow: (id) => { calls.push(['steerNow', id]); return true; },
  startNow: (id) => { calls.push(['startNow', id]); },
  update: (id, patch) => { calls.push(['update', id, patch]); },
  remove: (id) => { calls.push(['remove', id]); },
};
function queued(id, text, extra) {
  return { queueId: id, taskName: text, kind: 'llm', status: 'queued', ts: '', result: '',
           sessionId: 's1', attachmentCount: 0, editable: true, sendable: true, subject: 'message', ...extra };
}
function running(id, text) {
  return { queueId: id, taskName: text, kind: 'llm', status: 'running', ts: new Date(Date.now() - 5000).toISOString(),
           result: '', sessionId: 's1', attachmentCount: 0, editable: false, position: 0, subject: 'message' };
}
/** What one row is made of, read back from the tree the module built. */
function describe(row) {
  const head = row.querySelector('.task-log-row-head');
  const t = (sel) => { const n = head.querySelector(sel); return n ? n.textContent.trim() : null; };
  return {
    id: row.dataset.queueId,
    pos: t('.queue-row-pos'),
    text: t('.queue-row-text'),
    dot: !!head.querySelector('.task-log-status'),
    label: t('.task-log-running-label'),
    elapsed: !!head.querySelector('.task-log-running-elapsed'),
    buttons: head.querySelectorAll('button').map(b => [b.className, b.textContent.trim(), b.title]),
    expanded: row.classList.contains('expanded'),
  };
}
const list = () => document.getElementById('queue-panel-list');
const rows = () => list().querySelectorAll('.queue-row').map(describe);
"""


def _run(body: str):
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "research").mkdir()
        for rel, src in _STUBS.items():
            (d / rel).write_text(src)
        for real in ("runStatus.js", "icons.js"):
            (d / real).write_text((JS / real).read_text())
        (d / "queuePanel.js").write_text((JS / "queuePanel.js").read_text())
        script = (
            _SHIM
            + "\nconst mod = (await import(" + json.dumps((d / "queuePanel.js").as_uri()) + ")).default;\n"
            + "mod.init(driver);\n"
            + body
            + "\nprocess.exit(0);\n"
        )
        proc = subprocess.run(
            [shutil.which("node"), "--input-type=module", "-e",
             "(async () => {\n" + script + "\n})().catch(e => { console.error(e && e.stack || e); process.exit(1); });"],
            capture_output=True, text=True, timeout=60, cwd=tmp,
        )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


# ── The row's own `Verify` ──────────────────────────────────────────────────


def test_a_queued_message_is_its_number_its_words_edit_and_steer_now():
    """Unaccompanied: no lamp, no word, no clock. A number, the text, two
    buttons and the × that was always there."""
    out = _run("""
steerable = true;
queue = [queued('q1', 'Also check the tests when you are done', { position: 1 })];
mod.refresh();
console.log(JSON.stringify(rows()));
""")
    assert len(out) == 1, out
    row = out[0]
    assert row["pos"] == "1."
    assert row["text"] == "Also check the tests when you are done"
    assert row["dot"] is False, "a waiting message grew a status lamp"
    assert row["label"] is None, "a waiting message grew a status word"
    assert row["elapsed"] is False, "a waiting message grew a clock"
    names = [b[1] for b in row["buttons"]]
    assert names == ["Edit", "Steer now", ""], names
    classes = [b[0] for b in row["buttons"]]
    assert "queue-row-edit" in classes[0]
    assert "queue-steer-now" in classes[1]
    assert "queue-remove" in classes[2]
    # The tooltip teaches the key the composer takes for the same thing.
    assert "Ctrl+⏎" in row["buttons"][1][2]


def test_two_waiting_messages_are_numbered_in_order():
    out = _run("""
steerable = true;
queue = [queued('q1', 'first', { position: 1 }), queued('q2', 'second', { position: 2 })];
mod.refresh();
console.log(JSON.stringify(rows().map(r => [r.pos, r.text])));
""")
    assert out == [["1.", "first"], ["2.", "second"]], out


# ── Steer now only while a steer is on offer ────────────────────────────────


def test_the_button_reads_send_now_when_the_run_cannot_take_a_steer():
    """A Chat turn, a research turn, an old server with no steer route: the
    stream says no, and the row must not promise what the run cannot do."""
    out = _run("""
steerable = false;
queue = [queued('q1', 'hello', { position: 1 })];
mod.refresh();
console.log(JSON.stringify(rows()[0].buttons.map(b => [b[0].includes('queue-steer-now'), b[1]])));
""")
    assert out == [[False, "Edit"], [False, "Send now"], [False, ""]], out


def test_a_message_with_a_picture_reads_send_now_even_while_a_steer_is_offered():
    """`B1280`: a steer is words only; the queue is what carries the files."""
    out = _run("""
steerable = true;
queue = [queued('q1', 'look at this', { position: 1, attachmentCount: 1 }),
         queued('q2', 'and then this', { position: 2 })];
mod.refresh();
console.log(JSON.stringify(rows().map(r => r.buttons[1][1])));
""")
    assert out == ["Send now", "Steer now"], out


def test_the_row_re_reads_the_offer_when_the_stream_announces_it():
    """The stream answers after the row is drawn, so the row listens — nobody
    has to call `refresh()` for *Send now* to become *Steer now*."""
    out = _run("""
steerable = false;
queue = [queued('q1', 'hello', { position: 1 })];
mod.refresh();
const before = rows()[0].buttons[1][1];
steerable = true;
window.dispatchEvent(new CustomEvent('pantheon:steer-offer', { detail: { offered: true } }));
const after = rows()[0].buttons[1][1];
steerable = false;
window.dispatchEvent(new CustomEvent('pantheon:steer-offer', { detail: { offered: false } }));
const withdrawn = rows()[0].buttons[1][1];
console.log(JSON.stringify({ before, after, withdrawn }));
""")
    assert out == {"before": "Send now", "after": "Steer now", "withdrawn": "Send now"}, out


# ── The buttons reach the driver, each its own call ─────────────────────────


def test_steer_now_hands_that_rows_id_to_the_driver_and_nothing_else():
    out = _run("""
steerable = true;
queue = [queued('q1', 'first', { position: 1 }), queued('q2', 'second', { position: 2 })];
mod.refresh();
const second = list().querySelectorAll('.queue-row')[1];
second.querySelector('.queue-steer-now').click();
console.log(JSON.stringify(calls));
""")
    assert out == [["steerNow", "q2"]], out


def test_send_now_still_goes_to_start_now():
    out = _run("""
steerable = false;
queue = [queued('q1', 'first', { position: 1 })];
mod.refresh();
list().querySelector('.queue-force-run').click();
console.log(JSON.stringify(calls));
""")
    assert out == [["startNow", "q1"]], out


def test_edit_opens_the_editor_and_pressed_again_commits_through_the_driver():
    out = _run("""
steerable = true;
queue = [queued('q1', 'first words', { position: 1 })];
mod.refresh();
const row = list().querySelector('.queue-row');
row.querySelector('.queue-row-edit').click();
const opened = row.classList.contains('expanded');
const ta = row.querySelector('.queue-row-input');
const focused = !!ta && ta.focused;
ta.value = 'second thoughts';
row.querySelector('.queue-row-edit').click();
console.log(JSON.stringify({ opened, focused, calls: calls.map(c => c[0] === 'update' ? ['update', c[1], c[2].message] : c) }));
""")
    assert out["opened"] is True and out["focused"] is True, out
    assert ["update", "q1", "second thoughts"] in out["calls"], out


# ── A run in flight keeps the activity view's cluster ───────────────────────


def test_a_launched_run_still_shows_its_lamp_word_clock_and_stop():
    """The owner's ask was about a message waiting. A job in flight is the
    activity view's own row — lamp, *Sending*, elapsed, stop — and it stays."""
    out = _run("""
steerable = true;
const base = driver.getEntries;
driver.getEntries = () => [queued('q1', 'waiting one', { position: 1 }), running('r1', 'sending one')];
mod.refresh();
console.log(JSON.stringify(rows()));
""")
    waiting, run = out
    assert waiting["dot"] is False and waiting["label"] is None
    assert run["dot"] is True
    assert run["label"] == "Sending"
    assert run["elapsed"] is True
    names = [b[0] for b in run["buttons"]]
    assert any("queue-stop" in n for n in names), names
    assert not any("queue-row-edit" in n or "queue-steer-now" in n for n in names), names


# ── A row whose words are on their way ───────────────────────────────────────


def test_a_steering_row_says_so_offers_nothing_and_does_not_open():
    """Steer now was pressed and the server said yes. Until the run picks the
    words up, the row is the message and the one word *Steering…*: no Edit,
    no second Steer now (a second press would send the words twice), no ×,
    and a click on it opens no editor."""
    out = _run("""
steerable = true;
queue = [queued('q1', 'on its way', { position: 1, steering: true }), queued('q2', 'still waiting', { position: 2 })];
mod.refresh();
const first = list().querySelectorAll('.queue-row')[0];
first.querySelector('.task-log-row-head').click();
const note = first.querySelector('.queue-row-steering');
console.log(JSON.stringify({ rows: rows(), note: note ? note.textContent : null, opened: first.classList.contains('expanded') }));
""")
    steering, waiting = out["rows"]
    assert out["note"] == "Steering…"
    assert steering["buttons"] == [], steering
    assert steering["pos"] == "1." and steering["text"] == "on its way"
    assert out["opened"] is False, "a click opened the editor on a row that is on its way"
    assert [b[1] for b in waiting["buttons"]] == ["Edit", "Steer now", ""], waiting


def test_a_render_asked_for_mid_drag_waits_for_the_drop():
    """A rebuild under a drag detaches the row in hand and the drop is lost
    (`dragSort.js` ends the drag on a placeholder with no parent). A run
    starting or ending asks for a render through `pantheon:chat-busy-change`,
    so the render waits for the drop and then catches up."""
    out = _run("""
steerable = true;
queue = [queued('q1', 'first', { position: 1 })];
mod.refresh();
list().querySelector('.queue-row').classList.add('dragging');
queue = [queued('q1', 'first', { position: 1 }), queued('q2', 'second', { position: 2 })];
window.dispatchEvent(new CustomEvent('pantheon:chat-busy-change', { detail: { active: false } }));
const during = list().querySelectorAll('.queue-row').length;
list().querySelector('.queue-row').classList.remove('dragging');
await new Promise(r => setTimeout(r, 350));
const after = list().querySelectorAll('.queue-row').length;
console.log(JSON.stringify({ during, after }));
""")
    assert out == {"during": 1, "after": 2}, out


def test_the_panel_says_when_two_or_more_are_waiting():
    """The cockpit strip shows the foot's one button — *Send all N now*, which
    asks one after another or all at once (`P6-06`) — only then: a single
    message has its own buttons on its row."""
    out = _run("""
steerable = true;
queue = [queued('q1', 'first', { position: 1 })];
mod.refresh();
const one = document.getElementById('queue-panel').classList.contains('queue-panel-many');
queue = [queued('q1', 'first', { position: 1 }), queued('q2', 'second', { position: 2 })];
mod.refresh();
const two = document.getElementById('queue-panel').classList.contains('queue-panel-many');
const run = document.getElementById('queue-panel-run');
console.log(JSON.stringify({ one, two, runText: run.textContent, runHidden: run.hidden }));
""")
    assert out["one"] is False and out["two"] is True, out
    assert out["runText"] == "Send all 2 now" and out["runHidden"] is False, out


# ── The driver: what Steer now does to the queue, in chat.js ────────────────
#
# `chat.js` owns the queue; its `_queuePanelDriver` (and the two listeners
# under it) are sliced out of the REAL file and run with their surroundings as
# inputs — the array, `_removeQueuedRequest`, the panel, `chatStream` — so the
# property is measured where it lives rather than in a copy.

CHAT_JS = JS / "chat.js"

_DRIVER_SHIM = r"""
const winListeners = {};
globalThis.window = {
  addEventListener(t, fn) { (winListeners[t] = winListeners[t] || []).push(fn); },
  dispatchEvent(ev) { (winListeners[ev.type] || []).forEach(fn => fn(ev)); return true; },
};
globalThis.CustomEvent = class { constructor(type, init) { this.type = type; this.detail = (init && init.detail) || null; } };
const calls = { steers: [], removed: [], refreshes: 0, toasts: [], promoted: [] };
const _queuedAgentRequests = [];
let steerAnswer = 'steered';
let offered = true, canNow = true;
const chatStream = {
  isSteerOffered: () => offered,
  canSteerNow: () => canNow,
  STEER_KEY_LABEL: 'Ctrl+⏎',
  submitSteer: async (text, opts) => { calls.steers.push([text, opts]); await new Promise(r => setTimeout(r, 5)); return typeof steerAnswer === 'function' ? steerAnswer() : steerAnswer; },
};
const queuePanel = { refresh: () => { calls.refreshes++; } };
const uiModule = { showToast: (t) => { calls.toasts.push(t); }, el: () => null };
const _currentSessionIdSafe = () => 's1';
const _removeQueuedRequest = (id) => { const i = _queuedAgentRequests.findIndex(it => it.id === id); if (i < 0) return null; const [it] = _queuedAgentRequests.splice(i, 1); calls.removed.push(id); return it; };
const _promoteQueuedRequest = (id) => { calls.promoted.push(id); };
const getQueueActivityEntries = () => _queuedAgentRequests.map((it, i) => ({ queueId: it.id, taskName: it.message, steering: !!it.steering, position: i + 1 }));
const isStreaming = true, _sendInFlight = false; let _queuePaused = false;
const _drainQueuedAgentRequests = () => {}, _reorderQueuedRequests = () => {}, _updateQueuedRequest = () => {};
const _stopLaunchedQueueRun = () => {}, _runQueueParallel = async () => {}, _isQueueRunLive = () => true;
const settle = () => new Promise(r => setTimeout(r, 20));
"""


def _run_driver(body: str):
    src = CHAT_JS.read_text()
    start = src.index("  const _queuePanelDriver = {")
    end = src.index("  /**\n   * `P23-04` (CHAT-M-1)", start)
    block = src[start:end]
    assert "steerNow" in block and "pantheon:steer-applied" in block, "the driver slice moved"
    script = (
        _DRIVER_SHIM + "\n" + block + "\n(async () => {\n" + body
        + "\n})().catch(e => { console.error(e && e.stack || e); process.exit(1); });\n"
    )
    proc = subprocess.run([shutil.which("node"), "-e", script], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_steer_now_marks_the_row_and_the_run_picking_it_up_takes_it_off_the_queue():
    """The words leave the queue when the run has them (`steer_applied`), not
    when the server merely accepted them — a steer accepted in a run's last
    moments is dropped with the run, and a row deleted at acceptance would
    have put the message nowhere."""
    out = _run_driver("""
_queuedAgentRequests.push({ id: 'q1', message: 'turn left', sessionId: 's1' }, { id: 'q2', message: 'then right', sessionId: 's1' });
const p = _queuePanelDriver.steerNow('q1');
const markedAtOnce = !!_queuedAgentRequests[0].steering;
const ok = await p;
const stillQueued = _queuedAgentRequests.map(it => [it.id, !!it.steering]);
window.dispatchEvent(new CustomEvent('pantheon:steer-applied', { detail: { count: 1, queued: 1, round: 3 } }));
console.log(JSON.stringify({ ok, markedAtOnce, stillQueued, steers: calls.steers, removed: calls.removed,
  left: _queuedAgentRequests.map(it => it.id) }));
""")
    assert out["ok"] is True and out["markedAtOnce"] is True
    assert out["steers"] == [["turn left", {"queued": True}]]
    assert out["stillQueued"] == [["q1", True], ["q2", False]], "the row left the queue at acceptance"
    assert out["removed"] == ["q1"] and out["left"] == ["q2"]


def test_a_run_that_ends_first_leaves_the_message_queued_and_plain():
    out = _run_driver("""
_queuedAgentRequests.push({ id: 'q1', message: 'turn left', sessionId: 's1' });
await _queuePanelDriver.steerNow('q1');
window.dispatchEvent(new CustomEvent('pantheon:chat-busy-change', { detail: { active: false } }));
console.log(JSON.stringify({ left: _queuedAgentRequests.map(it => [it.id, !!it.steering]), removed: calls.removed }));
""")
    assert out == {"left": [["q1", False]], "removed": []}, out


def test_a_second_press_while_the_first_is_answered_sends_nothing_twice():
    out = _run_driver("""
_queuedAgentRequests.push({ id: 'q1', message: 'turn left', sessionId: 's1' });
const a = _queuePanelDriver.steerNow('q1');
const b = _queuePanelDriver.steerNow('q1');
const [ra, rb] = await Promise.all([a, b]);
console.log(JSON.stringify({ ra, rb, posted: calls.steers.length }));
""")
    assert out == {"ra": True, "rb": False, "posted": 1}, out


def test_a_refusal_unmarks_the_row():
    out = _run_driver("""
_queuedAgentRequests.push({ id: 'q1', message: 'turn left', sessionId: 's1' });
steerAnswer = false;
const ok = await _queuePanelDriver.steerNow('q1');
console.log(JSON.stringify({ ok, left: _queuedAgentRequests.map(it => [it.id, !!it.steering]) }));
""")
    assert out == {"ok": False, "left": [["q1", False]]}, out


def test_the_rows_answer_is_the_offer_not_the_busy_tail():
    """`canSteerNow` stays true through chat.js's 1.2 s busy tail after a run
    ends and nothing re-renders when the tail expires, so rows kept saying
    Steer now on an idle chat. The offer is withdrawn before the run-end
    edge reaches anyone; the row reads that."""
    out = _run_driver("""
offered = true; canNow = true;
const live = _queuePanelDriver.canSteer();
offered = false;
const tail = _queuePanelDriver.canSteer();
offered = true; canNow = false;
const offeredButNot = _queuePanelDriver.canSteer();
console.log(JSON.stringify({ live, tail, offeredButNot }));
""")
    assert out == {"live": True, "tail": False, "offeredButNot": False}, out
