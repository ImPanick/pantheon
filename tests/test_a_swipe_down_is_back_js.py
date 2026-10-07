# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P23-06` (NAV-M-13) — `swipeBack` in `static/js/ui.js`, driven under node.

The gesture itself is driven in a browser (`test_display_and_motion_in_a_browser.py`).
This file pins the seam the swipe shares with fx-back's back stack (`P23-01`,
contract C-NAV): when `modalManager.js` exports `closeWindow` — the path
Escape, the browser's Back and `← <opener>` all take — a swipe goes through it
and nothing else; until then it presses the sheet's own ×. And a window that
asks before it closes (`B1052`'s *Save / Discard / Keep editing*) keeps its
sheet, which comes back up.

The function is cut out of `ui.js` with `tests/helpers/js_source.js_definition`
and run with a stand-in `Modals`, element and clock — the parts it touches.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from helpers.js_source import js_definition

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "static" / "js" / "ui.js"

try:
    _NODE = subprocess.run(["node", "--version"], capture_output=True, text=True).returncode == 0
except FileNotFoundError:  # pragma: no cover - node is on PATH in CI
    _NODE = False
pytestmark = pytest.mark.skipif(not _NODE, reason="node binary not on PATH")


def _swipe_back_source() -> str:
    src = UI.read_text(encoding="utf-8")
    return js_definition(src, src.index("function swipeBack("))


_HARNESS = r"""
const calls = [];
const timers = [];
globalThis.setTimeout = (fn) => { timers.push(fn); return timers.length; };
const flush = () => { while (timers.length) timers.shift()(); };
const prefersReducedMotion = () => false;
const cls = (init = []) => { const s = new Set(init); return {
  add: (c) => s.add(c), remove: (...c) => c.forEach((x) => s.delete(x)), contains: (c) => s.has(c) }; };
const style = () => { const props = {}; return new Proxy(props, {
  get: (t, k) => k === 'setProperty' ? (n, v, p) => { t[n] = v + (p ? ' !' + p : ''); }
    : k === 'removeProperty' ? (n) => { delete t[n]; } : (t[k] ?? ''),
  set: (t, k, v) => { t[k] = v; return true; } }); };
const closeBtn = { click: () => calls.push('x-click') };
const modal = { id: 'tasks-modal', isConnected: true, classList: cls(), style: style(),
  querySelector: () => closeBtn };
const el = { classList: cls(['sheet-ready']), style: style(), closest: (sel) => sel === '.modal' ? modal : null };
el.style.transform = 'translateY(100%)';
const document = { getElementById: () => null };
const window = {};
const Modals = MODALS;
__SWIPE_BACK__
const asked = swipeBack(el);
const during = el.style.animation;
flush();
process.stdout.write(JSON.stringify({ asked, calls, during, after: { transform: el.style.transform,
  animation: el.style.animation, sheetReady: el.classList.contains('sheet-ready') } }) + '\n');
"""


def _run(tmp_path: Path, modals: str) -> dict:
    script = _HARNESS.replace("__SWIPE_BACK__", _swipe_back_source()).replace("MODALS", modals)
    case = tmp_path / "case.mjs"
    case.write_text(script)
    proc = subprocess.run(["node", str(case)], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_with_the_back_stack_present_a_swipe_takes_its_close_path_and_only_that(tmp_path):
    out = _run(tmp_path, "{ closeWindow: (id) => { calls.push('closeWindow:' + id); modal.classList.add('hidden'); },"
                         " isRegistered: () => true, close: () => calls.push('close') }")
    assert out["asked"] is True
    assert out["calls"] == ["closeWindow:tasks-modal"], out
    assert out["during"] == "none !important", out   # the sheet stays where the finger left it
    assert out["after"] == {"transform": "", "animation": "", "sheetReady": False}, out


def test_before_the_back_stack_lands_a_swipe_presses_the_sheets_close_button(tmp_path):
    out = _run(tmp_path, "{ isRegistered: () => true, close: () => calls.push('close') }")
    assert out["calls"] == ["x-click"], out


def test_a_window_that_asks_before_closing_gets_its_sheet_back(tmp_path):
    # The close asked (a Tasks draft, the Workbench's three choices): the window is still up.
    out = _run(tmp_path, "{ closeWindow: (id) => calls.push('closeWindow:' + id) }")
    assert out["calls"] == ["closeWindow:tasks-modal"], out
    assert out["after"]["transform"] == "", out    # slid back up
    assert out["after"]["animation"] == "", out
    assert out["after"]["sheetReady"] is True, out  # still an open sheet
