# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B1083` — a step opened on the canvas stays in sight beside its panel.

**Measured before this file** (`wf-ui`, 1400×860, Runs tab): clicking *Send
me the summary* opened its panel over the very box clicked. The panel is the
viewport's flex sibling (`.wb-panel`, `flex: 0 0 min(400px, 46%)`), so opening
it narrows the canvas, and nothing moved the view: a step near the right edge
ends up under the panel. A failed run's step was fitted beside its panel
(`P23-06`, `applyFocusChain`); a step a person opens was not, on any canvas.

Now `openPanel` keeps the step inside what the panel leaves: the fit is done
again into the narrower canvas while the view is the fit, and the view is
panned just enough otherwise.

Driven (`Law 20`): the real `canvas.js` and task source in node over the
canvas test's fake server. The DOM shim lays nothing out, so the one element
whose size the canvas reads — the viewport — is given the stage's width less
the panel's while the panel is shown (1000 px less `min(400px, 46%)`), which is
what the flex rule above does; where a step is on screen is the world's
translate and scale applied to its place, as `test_a_wide_run_opens_with_its_
start_on_screen_js.py` reads it.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_the_workbench_canvas_js as canvas_t  # noqa: E402
from test_the_workbench_canvas_js import box  # noqa: E402,F401

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

STAGE_W, STAGE_H, PANEL_W = 1000, 600, 400

_MEASURE = """
const STAGE_W = %d, H = %d, PANEL_W = %d;
const realRect = Node.prototype.getBoundingClientRect;
const panelOpen = (vp) => { const p = vp.parentNode && vp.parentNode.querySelector('.wb-panel'); return !!(p && !p.hidden); };
Node.prototype.getBoundingClientRect = function () {
  if (String(this.className || '').split(/\\s+/).includes('wb-viewport')) {
    const W = panelOpen(this) ? STAGE_W - PANEL_W : STAGE_W;
    return { left: 0, top: 0, right: W, bottom: H, width: W, height: H, x: 0, y: 0 };
  }
  return realRect.call(this);
};
const onScreen = (root, id) => {
  const world = root.querySelector('.wb-world');
  const m = /translate\\(([-\\d.]+)px, ([-\\d.]+)px\\) scale\\(([-\\d.]+)\\)/.exec(world.style.transform);
  const [x, y, z] = [Number(m[1]), Number(m[2]), Number(m[3])];
  const n = nodeOf(root, id);
  const left = x + parseFloat(n.style.left) * z, top = y + parseFloat(n.style.top) * z;
  return { left, right: left + 232 * z, top, bottom: top + parseFloat(n.style.height) * z, zoom: z };
};
const canvasW = (root) => root.querySelector('.wb-viewport').getBoundingClientRect().width;
const rightmost = (root) => ['a', 'b', 'c'].map((id) => [id, parseFloat(nodeOf(root, id).style.left)])
  .sort((p, q) => q[1] - p[1])[0][0];
"""

# Three steps in a row, so the right-hand one sits near the canvas's right edge.
_ROW = [
    {"id": k, "name": f"Step {k.upper()}", "task_type": "llm", "status": "active", "trigger_words": "",
     "then_task_id": n, "else_task_id": None}
    for k, n in (("a", "b"), ("b", "c"), ("c", None))
]


def _case(box, script):
    return canvas_t._case(box, _MEASURE % (STAGE_W, STAGE_H, PANEL_W) + script, tasks=_ROW)


def _inside(rect, width, height):
    return 0 <= rect["left"] and rect["right"] <= width and 0 <= rect["top"] and rect["bottom"] <= height


def test_a_step_opened_while_the_view_is_the_fit_is_beside_its_panel(box):
    o = _case(box, """
        const { root } = await mount();
        const id = rightmost(root);
        const before = { ...onScreen(root, id), width: canvasW(root) };
        fire(nodeOf(root, id), 'click'); await settle();
        out({ id, before, after: onScreen(root, id), width: canvasW(root), open: !root.querySelector('.wb-panel').hidden });
    """)
    assert o["open"] is True and o["width"] == STAGE_W - PANEL_W
    assert o["before"]["right"] > o["width"], "the premise: the step is where the panel now is"
    assert _inside(o["after"], o["width"], STAGE_H), f"the opened step is under its panel: {o['after']}"


def test_a_step_opened_after_the_person_moved_the_view_is_brought_beside_its_panel(box):
    """Panned so the step sits at the right edge, the zoom the person's: the
    view moves just enough, and the zoom stays."""
    o = _case(box, """
        const { root } = await mount();
        const id = rightmost(root);
        const vp = root.querySelector('.wb-viewport');
        const s0 = onScreen(root, id);
        // A wheel pans (no Ctrl): bring the step's right edge to 10 px from the canvas's.
        fire(vp, 'wheel', { deltaX: -(STAGE_W - 10 - s0.right), deltaY: 0 });
        const before = onScreen(root, id);
        fire(nodeOf(root, id), 'click'); await settle();
        out({ before, after: onScreen(root, id), width: canvasW(root) });
    """)
    assert o["before"]["right"] == pytest.approx(STAGE_W - 10)
    assert _inside(o["after"], o["width"], STAGE_H), o["after"]
    assert o["after"]["zoom"] == o["before"]["zoom"], "the person's zoom is kept"
    assert o["after"]["right"] == pytest.approx(o["width"] - 16), "moved just enough, to the margin"


def test_a_step_already_in_sight_does_not_move_the_view(box):
    o = _case(box, """
        const { root } = await mount();
        const vp = root.querySelector('.wb-viewport');
        const s0 = onScreen(root, 'a');
        fire(vp, 'wheel', { deltaX: s0.left - 40, deltaY: 0 });   // step A at 40 px from the left
        const before = root.querySelector('.wb-world').style.transform;
        fire(nodeOf(root, 'a'), 'click'); await settle();
        out({ same: root.querySelector('.wb-world').style.transform === before, at: onScreen(root, 'a').left });
    """)
    assert o["same"] is True and o["at"] == pytest.approx(40)
