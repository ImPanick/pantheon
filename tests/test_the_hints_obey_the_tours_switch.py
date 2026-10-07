# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P23-05` (COPY-M-6) — the two first-open hints obey *First-run tours*.

Measured by the audit (`audit/parts/mech-copy.md` COPY-M-6): with the switch
off, the Notes hint *"Notes is your basic todo list…"* still appeared on the
first open, and was still on screen over the Calendar after Notes had closed —
it went on a 6.5 s timer, not with the pane. *Show again* cleared only the
tours' own markers (`tourAutoplay.js:resetSeenTours`), so the drag hint and the
Notes hint never came back either.

Now both hints ask the switch before showing (through
`window.pantheonToursEnabled`, which `tourAutoplay.js` sets — a hint must not
import the module that imports the slash-command table), *Replay* clears their
keys, and the Notes hint leaves when the pane does. Their words are the voice
guide's (Doc 2 § 5): *To-dos and reminders live here.* and *Drag a window's
title bar to an edge to snap it; to the top to fill the screen.*

Driven: the shipped functions cut out with `tests/helpers/js_source` and run
under node; `resetSeenTours` through the tours module's own sandbox
(`tests/test_first_run_tours_are_gated.py`, `Law 14`).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tests.helpers.js_source import js_binding, js_function  # noqa: E402
from test_first_run_tours_are_gated import sandbox, _run  # noqa: E402,F401

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_REPO = Path(__file__).resolve().parents[1]
_JS = _REPO / "static" / "js"


def _src(name: str) -> str:
    return (_JS / name).read_text(encoding="utf-8")


def _node(script: str) -> dict:
    proc = subprocess.run(["node", "--input-type=module", "-e", textwrap.dedent(script)],
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads([ln for ln in proc.stdout.splitlines() if ln.strip()][-1])


def _binding_value(file: str, name: str) -> str:
    decl = js_binding(_src(file), name).replace("export const", "const", 1)
    return _node(f"{decl}\nconsole.log(JSON.stringify({{ v: {name} }}));")["v"]


def test_replay_knows_the_keys_the_hints_write():
    """`Law 7`: the keys are written in two modules and cleared in a third; a
    rename in one would leave *Replay* clearing a key nobody writes."""
    keys = _binding_value("tourAutoplay.js", "HINT_KEYS")
    assert sorted(keys) == sorted([_binding_value("tourHints.js", "HINT_SEEN_KEY"),
                                   _binding_value("notes.js", "NOTES_FIRST_OPEN_HINT_KEY")])


def test_replay_clears_both_hints(sandbox):
    out = _run(sandbox, """
        localStorage.setItem('pantheon-hint-drag-to-snap-seen', '1');
        localStorage.setItem('pantheon-notes-first-open-hint-v1', '1');
        tours.resetSeenTours();
        console.log(JSON.stringify({ left: tours.HINT_KEYS.filter((k) => localStorage.getItem(k)),
                                     global: typeof window.pantheonToursEnabled }));
    """)
    assert out == {"left": [], "global": "function"}


# ── the drag hint ─────────────────────────────────────────────────────────────


def _drag_case(tours_on) -> dict:
    src = _src("tourHints.js")
    on = "function _toursOn() " + js_function(src, "function _toursOn")
    opened = "function _onModalOpened(modal) " + js_function(src, "function _onModalOpened")
    return _node(f"""
        const scheduled = [];
        globalThis.window = {{ innerWidth: 1440, pantheonToursEnabled: {tours_on} }};
        globalThis.document = {{ body: {{ classList: {{ contains: () => false }} }}, getElementById: () => null }};
        globalThis.setTimeout = (fn, ms) => {{ scheduled.push(ms); return 0; }};
        let _shown = false;
        const _hasSeen = () => false;
        const _modalShouldShowHint = () => true;
        const _show = () => {{}};
        {on}
        {opened}
        _onModalOpened({{ id: 'calendar-modal' }});
        console.log(JSON.stringify({{ scheduled, shown: _shown }}));
    """)


def test_the_drag_hint_waits_while_tours_are_off():
    assert _drag_case("() => false") == {"scheduled": [], "shown": False}


def test_the_drag_hint_shows_while_tours_are_on_and_when_nobody_said():
    assert _drag_case("() => true") == {"scheduled": [380], "shown": True}
    assert _drag_case("undefined") == {"scheduled": [380], "shown": True}


def test_the_drag_hint_says_one_plain_sentence():
    body = js_function(_src("tourHints.js"), "function _show")
    assert "Pro tip" not in body
    assert "Drag a window’s title bar to an edge to snap it; to the top to fill the screen." in body


# ── the Notes hint ────────────────────────────────────────────────────────────


def _notes_case(tours_on, *, close_pane_after=None) -> dict:
    fn = "function _showNotesFirstOpenHint(pane) " + js_function(_src("notes.js"),
                                                                 "function _showNotesFirstOpenHint")
    return _node(f"""
        const store = new Map();
        globalThis.localStorage = {{ getItem: (k) => store.has(k) ? store.get(k) : null,
                                     setItem: (k, v) => store.set(k, String(v)) }};
        const appended = [];
        const timeouts = [];
        const intervals = [];
        const el = () => ({{ id: '', className: '', style: {{}}, innerHTML: '', removed: false,
          classList: {{ add() {{}} }}, offsetWidth: 260,
          querySelector: () => ({{ addEventListener() {{}} }}),
          remove() {{ this.removed = true; }} }});
        globalThis.document = {{ getElementById: () => null, createElement: el,
                                 body: {{ appendChild: (n) => appended.push(n) }} }};
        globalThis.window = {{ innerWidth: 1440, pantheonToursEnabled: {tours_on},
                               addEventListener() {{}}, removeEventListener() {{}} }};
        globalThis.requestAnimationFrame = (fn) => fn();
        globalThis.setTimeout = (fn, ms) => {{ timeouts.push({{ fn, ms }}); return 0; }};
        globalThis.setInterval = (fn) => {{ intervals.push(fn); return 1; }};
        globalThis.clearInterval = () => {{}};
        const topPortalZ = () => 10000;
        const NOTES_FIRST_OPEN_HINT_KEY = 'pantheon-notes-first-open-hint-v1';
        const pane = {{ isConnected: true, getBoundingClientRect: () => ({{ top: 0, left: 900 }}) }};
        {fn}
        _showNotesFirstOpenHint(pane);
        const hint = appended[0] || null;
        let removedAfterClose = null;
        if (hint && {json.dumps(close_pane_after is not None)}) {{
          pane.isConnected = false;
          intervals.forEach((t) => t());            // the pane check — not the 6.5 s timer
          timeouts.filter((t) => t.ms === 180).forEach((t) => t.fn());   // the fade-out
          removedAfterClose = hint.removed;
        }}
        console.log(JSON.stringify({{ shown: !!hint, text: hint ? hint.innerHTML : '',
          seen: localStorage.getItem(NOTES_FIRST_OPEN_HINT_KEY), removedAfterClose }}));
    """)


def test_the_notes_hint_waits_while_tours_are_off():
    out = _notes_case("() => false")
    assert out["shown"] is False
    assert out["seen"] is None, "a hint not shown is not marked seen"


def test_the_notes_hint_is_one_line_and_leaves_with_the_pane():
    out = _notes_case("() => true", close_pane_after=True)
    assert out["shown"] is True and out["seen"] == "1"
    assert "To-dos and reminders live here." in out["text"]
    assert "basic todo list" not in out["text"]
    assert out["removedAfterClose"] is True, "the hint outlived the pane it explains"
