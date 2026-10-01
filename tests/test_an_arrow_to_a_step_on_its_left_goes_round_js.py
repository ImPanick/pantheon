# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B1053` — an arrow to a step on its left is routed round, and reads the way it was saved.

Measured on the merged tree (`a97d969`, `verify-a`): the canvas keeps every
step where it is after a connect, so a step can be joined to one on its left.
*if it fails* from *Ann target* (right) to *Zed source* (left, same row) was
saved right — but the arrow was `edgePath`'s curve from Ann's right edge to
Zed's left edge, which ran back **under both boxes** (12 of 21 sampled points),
and its only visible piece, with its words, sat between them leaving Zed's *if
it fails* port: on screen, "if Zed source fails, run Ann target", the reverse.

`static/js/workbench/graphLayout.js` is pure, so `edgeRoute` is called directly
under node, as `tests/test_the_workbench_lays_out_a_chain_js.py` calls the
layout; every path it returns is sampled — its lines, corners and curves walked
point by point — and no point may fall inside either step. The last case drives
the real `canvas.js` in the shared DOM shim (`tests/test_the_workbench_canvas_js.py`'s
sandbox and fake server) to show the canvas draws the route.
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

from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402
from test_the_workbench_canvas_js import _SHIM as _CANVAS_SHIM, _UP, _TASKS  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"
LAYOUT_JS = JS / "workbench" / "graphLayout.js"
CANVAS_JS = JS / "workbench" / "canvas.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

# Walks an absolute M/L/Q/C path — the commands `edgePath` and `edgeRoute`
# write — into points, and says which of them fall inside a box.
_GEOMETRY = r"""
export function sample(d, n = 24) {
  const t = String(d).match(/[MLQC]|-?\d+(?:\.\d+)?/g);
  const pts = [];
  let i = 0, cur = null;
  const num = () => Number(t[i++]);
  const pt = () => ({ x: num(), y: num() });
  while (i < t.length) {
    const c = t[i++];
    if (c === 'M') { cur = pt(); pts.push(cur); }
    else if (c === 'L') {
      const p = pt();
      for (let k = 1; k <= n; k++) pts.push({ x: cur.x + (p.x - cur.x) * k / n, y: cur.y + (p.y - cur.y) * k / n });
      cur = p;
    } else if (c === 'Q') {
      const c1 = pt(), p = pt();
      for (let k = 1; k <= n; k++) {
        const s = k / n, u = 1 - s;
        pts.push({ x: u * u * cur.x + 2 * u * s * c1.x + s * s * p.x, y: u * u * cur.y + 2 * u * s * c1.y + s * s * p.y });
      }
      cur = p;
    } else if (c === 'C') {
      const c1 = pt(), c2 = pt(), p = pt();
      for (let k = 1; k <= n; k++) {
        const s = k / n, u = 1 - s;
        pts.push({
          x: u * u * u * cur.x + 3 * u * u * s * c1.x + 3 * u * s * s * c2.x + s * s * s * p.x,
          y: u * u * u * cur.y + 3 * u * u * s * c1.y + 3 * u * s * s * c2.y + s * s * s * p.y,
        });
      }
      cur = p;
    } else throw new Error('unexpected path command ' + c);
  }
  return pts;
}
export const inside = (p, box, W, H) => p.x > box.x + 1 && p.x < box.x + W - 1 && p.y > box.y + 1 && p.y < box.y + H - 1;
"""


def _pure(tmp_path: Path, script: str) -> dict:
    (tmp_path / "geometry.mjs").write_text(_GEOMETRY, encoding="utf-8")
    entry = tmp_path / "case.mjs"
    entry.write_text(
        "import * as gl from '%s';\nimport { sample, inside } from './geometry.mjs';\n"
        "const under = (d, ...boxes) => sample(d).filter((p) => boxes.some((b) => inside(p, b, gl.NODE_W, gl.NODE_H))).length;\n"
        % LAYOUT_JS.as_posix() + textwrap.dedent(script), encoding="utf-8")
    proc = subprocess.run(["node", str(entry)], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


# verify-a's two steps, in canvas pixels: the source on the right, the target
# on its left, on one row.
_ANN = {"x": 440, "y": 40}
_ZED = {"x": 40, "y": 40}


def test_the_curve_it_replaces_runs_under_both_steps(tmp_path):
    """The premise, re-measured (`Law 3`): the plain curve for this pair goes
    under the boxes. This is what the canvas drew before."""
    o = _pure(tmp_path, """
        const ann = %s, zed = %s;
        const d = gl.edgePath(gl.portPoint(ann, 'error'), gl.inputPoint(zed));
        console.log(JSON.stringify({ under: under(d, ann, zed), all: sample(d).length }));
    """ % (json.dumps(_ANN), json.dumps(_ZED)))
    assert o["under"] > o["all"] / 3, o


@pytest.mark.parametrize("when", ["success", "error"])
def test_an_arrow_to_a_step_on_its_left_goes_round_and_never_under_either(tmp_path, when):
    o = _pure(tmp_path, """
        const ann = %s, zed = %s, when = %s;
        const r = gl.edgeRoute(ann, zed, when);
        const pts = sample(r.d);
        const port = gl.portPoint(ann, when), into = gl.inputPoint(zed);
        console.log(JSON.stringify({
          routed: r.routed, under: under(r.d, ann, zed), first: pts[0], second: pts[1],
          last: pts[pts.length - 1], beforeLast: pts[pts.length - 2], port, into, end: r.end,
          label: r.label, labelUnder: [ann, zed].some((b) => gl.nodeAt([{ id: 'x', ...b }], r.label, null)),
          head: gl.arrowPath(r.end), H: gl.NODE_H,
        }));
    """ % (json.dumps(_ANN), json.dumps(_ZED), json.dumps(when)))
    assert o["routed"] is True
    assert o["under"] == 0, "a point of the arrow is under one of the two steps"
    # It leaves the source's own port, outward...
    assert o["first"] == o["port"] and o["second"]["x"] > o["port"]["x"] and o["second"]["y"] == o["port"]["y"]
    # ...and arrives at the target's input from its left, where the head points in.
    assert o["last"] == o["into"] == o["end"]
    assert o["beforeLast"]["y"] == o["into"]["y"] and o["beforeLast"]["x"] < o["into"]["x"]
    assert o["head"].startswith("M %g %g L %g " % (o["into"]["x"], o["into"]["y"], o["into"]["x"] - 9))
    # The words are on the lane, clear of both steps: above them for the first
    # port, below them for the second.
    assert o["labelUnder"] is False
    if when == "success":
        assert o["label"]["y"] < _ANN["y"]
    else:
        assert o["label"]["y"] > _ANN["y"] + o["H"]


def test_a_steps_two_arrows_to_the_same_step_take_different_lanes(tmp_path):
    o = _pure(tmp_path, """
        const ann = %s, zed = %s;
        const works = gl.edgeRoute(ann, zed, 'success'), fails = gl.edgeRoute(ann, zed, 'error');
        console.log(JSON.stringify({ same: works.d === fails.d, ys: [works.label.y, fails.label.y] }));
    """ % (json.dumps(_ANN), json.dumps(_ZED)))
    assert o["same"] is False and o["ys"][0] < o["ys"][1]


@pytest.mark.parametrize("target", [{"x": 40, "y": 400}, {"x": 40, "y": -320}, {"x": 140, "y": 400}],
                         ids=["below-left", "above-left", "stacked-under"])
def test_a_step_above_or_below_is_reached_between_the_rows(tmp_path, target):
    o = _pure(tmp_path, """
        const src = { x: 300, y: 40 }, dst = %s;
        const r = gl.edgeRoute(src, dst, 'error');
        console.log(JSON.stringify({ routed: r.routed, under: under(r.d, src, dst), lane: r.label.y + 6,
                                     H: gl.NODE_H }));
    """ % json.dumps(target))
    assert o["routed"] is True and o["under"] == 0
    rows = sorted([40, target["y"]])
    assert rows[0] + o["H"] < o["lane"] < rows[1], "the lane runs between the two rows"


def test_a_forward_arrow_is_the_curve_it_always_was(tmp_path):
    """`Law 1`: the arrows the layout draws — target to the right — are not
    touched. Down to a 16px gap the plain curve stays between the two steps."""
    o = _pure(tmp_path, """
        const a = { x: 40, y: 40 }, b = { x: 368, y: 168 }, near = { x: 40 + gl.NODE_W + 16, y: 200 };
        const r = gl.edgeRoute(a, b, 'error'), n = gl.edgeRoute(a, near, 'success');
        const port = gl.portPoint(a, 'error'), into = gl.inputPoint(b), mid = gl.edgeMid(port, into);
        console.log(JSON.stringify({
          same: r.d === gl.edgePath(port, into), label: r.label, mid, routed: r.routed,
          near: { routed: n.routed, under: under(n.d, a, near) },
        }));
    """)
    assert o["same"] is True and o["routed"] is False
    assert o["label"] == {"x": o["mid"]["x"], "y": o["mid"]["y"] - 6}
    assert o["near"] == {"routed": False, "under": 0}


# ── the canvas draws the route ─────────────────────────────────────────────

@pytest.fixture(scope="module")
def box(tmp_path_factory):
    root = tmp_path_factory.mktemp("wbback")
    (root / "workbench").mkdir()
    sandbox = _make_sandbox(root / "workbench", CANVAS_JS, _CANVAS_SHIM, {})
    for rel in _UP:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(JS / rel, root / rel)
    (root / "windowDrag.js").write_text(
        "export const KEY_STEP = 16;\nexport const MOVE_THRESHOLD = 4;\n"
        "export function makeWindowDraggable() {}\n", encoding="utf-8")
    (root / "geometry.mjs").write_text(_GEOMETRY, encoding="utf-8")
    return sandbox


def test_right_after_connecting_to_a_step_on_its_left_the_canvas_draws_it_round(box):
    """The row's `Verify:`: immediately after connecting a step to one on its
    left, the arrow is routed from the source's port to the target's input."""
    prefs = {"v": 1, "tasks": {"a": [440, 40], "b": [40, 40], "c": [840, 400]}}
    o = _run(box, (
        "import { server, net, mountPanel, fire, settle, nodeOf, portOf, at, edgeEls } from './shim.js';\n"
        "import { sample, inside } from '../geometry.mjs';\n"
        "import * as gl from './graphLayout.js';\n"
        "const { mountCanvas } = await import('./canvas.js');\n"
        "server.tasks = %s;\nserver.prefs = %s;\n" % (json.dumps(_TASKS), json.dumps(prefs))
    ), """
        const root = document.body.appendChild(new Node('div'));
        const c = mountCanvas(root, { fetch: net, mountPanel });
        await c.ready; await settle();
        const port = portOf(nodeOf(root, 'a'), 'error'), b = at(nodeOf(root, 'b'));
        fire(port, 'pointerdown', {});
        fire(port, 'pointerup', { clientX: b.x + 5, clientY: b.y + 5 });
        await settle(5);
        const g = edgeEls(root).find((x) => x.getAttribute('data-from') === 'a' && x.getAttribute('data-when') === 'error');
        const d = g.querySelectorAll('path')[1].getAttribute('d');
        const A = at(nodeOf(root, 'a')), B = at(nodeOf(root, 'b'));
        const label = g.querySelectorAll('text')[0];
        console.log(JSON.stringify({
          routed: g.getAttribute('data-routed'), drawn: d === gl.edgeRoute(A, B, 'error').d,
          under: sample(d).filter((p) => inside(p, A, gl.NODE_W, gl.NODE_H) || inside(p, B, gl.NODE_W, gl.NODE_H)).length,
          labelY: Number(label.getAttribute('y')), bottom: A.y + gl.NODE_H, words: label.textContent,
          forward: edgeEls(root).find((x) => x.getAttribute('data-to') === 'c').getAttribute('data-routed'),
        }));
    """)
    assert o["routed"] == "true" and o["drawn"] is True
    assert o["under"] == 0
    assert o["labelY"] > o["bottom"] and o["words"] == "if it fails"
    assert o["forward"] == "false", "the arrow to the step on the right is the plain curve"
