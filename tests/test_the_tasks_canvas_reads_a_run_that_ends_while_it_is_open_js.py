# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B1095` — the tasks canvas reads a run that ends while it is open.

**Measured before this file** (`integrate-c`, drive run 1, `P22-02`): with the
Workbench open on *Tasks and chains*, *Collect weekly metrics* ran (`error`)
and its *if it fails* step ran (`error`); both boxes still read "○ Not run
yet" — pressing *Tasks and chains* again did not read them — until the window
was opened again. The canvas drew each step's mark from the list it loaded and
never asked again (no poll, interval or listener in `taskSource.js`,
`canvas.js` or the room).

Now the room reads the steps' last runs again while the tasks canvas is
showing: every `SHELF_WATCH_MS` while a run is in flight, every
`TASKS_IDLE_WATCH_MS` otherwise, not while the page is hidden, at once when
*Tasks and chains* is pressed again — and a redraw keeps the step that had the
keyboard.

Driven (`Law 20`): the real room, canvas and task source in node over the
canvas test's fake task server; the watch's two timers are held by the case
and fired by hand (every other timer is the real one), so "within a few
seconds" is asserted as the delay the room asked for, not slept through.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_the_automations_room_js as room_js  # noqa: E402
from test_the_automations_room_js import box  # noqa: E402,F401

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_HOLD = """
const { SHELF_WATCH_MS, TASKS_IDLE_WATCH_MS } = await import('./workflowRoom.js');
const held = [];
const realST = globalThis.setTimeout, realCT = globalThis.clearTimeout;
globalThis.setTimeout = (fn, ms, ...a) => {
  if (ms === SHELF_WATCH_MS || ms === TASKS_IDLE_WATCH_MS) { const h = { fn, ms, fake: true }; held.push(h); return h; }
  return realST(fn, ms, ...a);
};
globalThis.clearTimeout = (h) => {
  if (h && h.fake) { const i = held.indexOf(h); if (i >= 0) held.splice(i, 1); return; }
  return realCT(h);
};
const fireWatch = async () => { const h = held.shift(); h.fn(); await settle(10); return h.ms; };
const word = (root, id) => { const n = nodeOf(root, id); const w = n && n.querySelector('.wb-node-word'); return w ? w.textContent : null; };
const reads = () => server.calls.filter((c) => c.url === '/api/tasks?include_last_run=true').length;
const task = (id) => server.tasks.find((t) => t.id === id);
"""


def _case(box, script):
    return room_js._case(box, _HOLD + script)


def test_a_run_that_starts_and_ends_while_the_canvas_is_open_changes_its_mark(box):
    o = _case(box, """
        const { root } = await room();
        const atOpen = { word: word(root, 'c'), held: held.map((h) => h.ms) };
        task('c').last_run_status = 'running'; task('c').last_run = '2026-10-02T09:00:00Z';
        const firstDelay = await fireWatch();
        const running = { word: word(root, 'c'), held: held.map((h) => h.ms) };
        task('c').last_run_status = 'error';
        const secondDelay = await fireWatch();
        const ended = { word: word(root, 'c'), tone: nodeOf(root, 'c').dataset.outcome, held: held.map((h) => h.ms) };
        out({ atOpen, firstDelay, running, secondDelay, ended, consts: [SHELF_WATCH_MS, TASKS_IDLE_WATCH_MS] });
    """)
    shelf_ms, idle_ms = o["consts"]
    assert shelf_ms <= 5000 and idle_ms <= 10000, "a few seconds, not a page reload"
    assert o["atOpen"] == {"word": "Not run yet", "held": [idle_ms]}
    assert o["firstDelay"] == idle_ms
    assert o["running"] == {"word": "Last run: Running", "held": [shelf_ms]}, "in flight: read again sooner"
    assert o["secondDelay"] == shelf_ms
    assert o["ended"] == {"word": "Last run: Failed", "tone": "error", "held": [idle_ms]}


def test_pressing_tasks_and_chains_again_reads_them_at_once(box):
    o = _case(box, """
        const { root } = await room();
        task('b').last_run_status = 'error';
        const before = reads();
        fire(root.querySelector('.wf-shelf-tasks'), 'click'); await settle(10);
        out({ word: word(root, 'b'), asked: reads() - before });
    """)
    assert o == {"word": "Last run: Failed", "asked": 1}


def test_nothing_is_asked_while_the_page_is_hidden_or_another_view_shows(box):
    o = _case(box, """
        const { root } = await room();
        document.visibilityState = 'hidden';
        task('c').last_run_status = 'error';
        const before = reads();
        await fireWatch();
        const hidden = { asked: reads() - before, word: word(root, 'c'), held: held.map((h) => h.ms) };
        document.visibilityState = 'visible';
        await openW(root);
        out({ hidden, afterOpen: held.length, idle: TASKS_IDLE_WATCH_MS });
    """)
    assert o["hidden"] == {"asked": 0, "word": "Not run yet", "held": [o["idle"]]}
    assert o["afterOpen"] == 0, "a workflow open: the tasks canvas is not read"


def test_a_redraw_keeps_the_step_that_had_the_keyboard(box):
    o = _case(box, """
        const { root } = await room();
        // The shim's `focus()` does not move `document.activeElement`; a browser's does.
        const was = nodeOf(root, 'c');
        was.focus(); document.activeElement = was;
        task('c').last_run_status = 'success';
        await fireWatch();
        const n = nodeOf(root, 'c');
        out({ word: word(root, 'c'), redrawn: n !== was, focused: !!n.focused });
    """)
    assert o["word"] == "Last run: Success"
    assert o["redrawn"] is True and o["focused"] is True, "the redraw took the keyboard away"
