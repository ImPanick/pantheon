# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B1113` — at 390 px a workflow wider than the screen opens with its start on screen.

Measured by `integrate-d` (Runs, dark 390): *Three feeds* "Starts" at x
−75…6, *Issue digest* −18…63, at the 35 % zoom floor; a three-column workflow
fitted. `graphLayout.fitView` centred the graph whatever its width, so a graph
still wider than the viewport at the zoom floor hung off both edges — its
start off the left one. Now a graph that fits is centred as before, and one
that does not has its first column (row) at the padding: the start is where
a person begins reading, and panning reaches the rest.

Driven end to end (`Law 20`): the real room, canvas, run source and
`workflowApi.js` in node against the REAL server on a loopback port
(`tests/helpers/workflow_live.py`), which ran a seven-column workflow once
through the real walker; the canvas's viewport measures 390 × 640 (the DOM
shim measures nothing, so the one element is given the phone's size).
"""
from __future__ import annotations

import asyncio
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_tool_effect_surfaces_js import _run  # noqa: E402
from test_the_workbench_canvas_js import _SHIM as _CANVAS_SHIM  # noqa: E402
from helpers.workflow_live import LIVE_PREAMBLE, LiveServer, build_sandbox  # noqa: E402
from tests.helpers.walker_harness import arrow, node, seed_workflow  # noqa: E402

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

STEPS = "abcdef"          # six steps after the start: seven columns


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    return build_sandbox(tmp_path_factory.mktemp("wide"), _CANVAS_SHIM)


@pytest.fixture()
def live(monkeypatch, tmp_path):
    from tests.helpers.assist_harness import build_world

    w = build_world(monkeypatch, tmp_path)
    seed_workflow(w.factory, [node(k, f"Step {k.upper()}", "action", action="tidy_sessions") for k in STEPS],
                  [arrow(a, b) for a, b in zip(STEPS, STEPS[1:])], trigger_type="webhook",
                  name="Six in a row")
    asyncio.run(w.s._execute_task("wf"))
    w.server = LiveServer(w.app)
    try:
        yield w
    finally:
        w.server.close()


_MEASURE = """
const W = %d, H = 640;
const realRect = Node.prototype.getBoundingClientRect;
Node.prototype.getBoundingClientRect = function () {
  if (String(this.className || '').split(/\\s+/).includes('wb-viewport')) {
    return { left: 0, top: 0, right: W, bottom: H, width: W, height: H, x: 0, y: 0 };
  }
  return realRect.call(this);
};
// Where a step is on the screen: the world's translate and scale, applied to
// the step's place in the world (its left/top, as the canvas sets them).
const onScreen = (hostEl, id) => {
  const world = hostEl.querySelector('.wb-world');
  const m = /translate\\(([-\\d.]+)px, ([-\\d.]+)px\\) scale\\(([-\\d.]+)\\)/.exec(world.style.transform);
  const [x, y, z] = [Number(m[1]), Number(m[2]), Number(m[3])];
  const n = hostEl.querySelectorAll('.wb-node').find((e) => e.dataset.itemId === id);
  const left = x + parseFloat(n.style.left) * z;
  return { left, right: left + 232 * z, zoom: z };
};
const { r } = await room();
fire(r.querySelectorAll('.wf-shelf-item').find((b) => b.dataset.key === 'w-wf'), 'click'); await quiet();
const edit = onScreen(by(r, 'wf-edit'), '__start__');
fire(r.querySelectorAll('.wf-tab').find((t) => t.textContent === 'Runs'), 'click'); await quiet();
const run = onScreen(by(r, 'wf-run-canvas'), '__start__');
const last = onScreen(by(r, 'wf-run-canvas'), 'f');
out({ edit, run, last, runs: all(r, 'wf-run-word').map((s) => s.textContent) });
"""


@pytest.mark.parametrize("width", [390])
def test_a_seven_column_run_opens_with_its_start_on_screen(box, live, width):
    o = _run(box, LIVE_PREAMBLE(live.server.base), _MEASURE % width)
    assert o["runs"] == ["Success"], "the real run, as the real route lists it"
    run = o["run"]
    assert run["zoom"] == 0.35, "at the zoom floor: the graph is wider than the phone"
    assert 0 <= run["left"] and run["right"] <= width, f"the start is on screen: {run}"
    assert o["last"]["right"] > width, "the rest is wider than the screen — panning reaches it"
    assert 0 <= o["edit"]["left"] and o["edit"]["right"] <= width, "the editing canvas too"


def test_a_graph_that_fits_is_still_centred(tmp_path):
    """`Law 1`: what fitted is drawn where it was — centred, at zoom ≤ 1."""
    import json
    import subprocess

    layout = Path(__file__).resolve().parents[1] / "static" / "js" / "workbench" / "graphLayout.js"
    entry = tmp_path / "case.mjs"
    entry.write_text(
        f"import * as gl from '{layout.as_posix()}';\n"
        "const small = { x: 40, y: 40, w: 232 * 3 + 96 * 2, h: 96 };\n"
        "const wide = { x: 40, y: 40, w: 232 * 7 + 96 * 6, h: 96 };\n"
        "console.log(JSON.stringify({ small: gl.fitView(small, 1400, 860), wide: gl.fitView(wide, 390, 640),\n"
        "  tall: gl.fitView({ x: 40, y: 40, w: 232, h: 5000 }, 1400, 640) }));\n", encoding="utf-8")
    o = json.loads(subprocess.run(["node", str(entry)], capture_output=True, text=True, check=True).stdout)
    s = o["small"]
    assert s["zoom"] == 1 and s["x"] + 40 == (1400 - (232 * 3 + 96 * 2)) / 2, "centred, as before"
    w = o["wide"]
    assert w["zoom"] == 0.35 and w["x"] + 40 * 0.35 == 40, "its first column at the padding"
    t = o["tall"]
    assert t["zoom"] == 0.35 and round(t["y"] + 40 * 0.35, 6) == 40, "a graph too tall: its first row"
