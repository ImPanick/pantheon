# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P22-02` — where each step of a chain sits on the Workbench's canvas.

`static/js/workbench/graphLayout.js` is pure — no DOM, no fetch, no module
state — so it is imported and called directly under node with no sandbox and no
stubs, the way `tests/test_a_workflow_you_did_not_write_js.py` drives
`tasks/workflowDiagram.js`. That is the strongest form `Law 20` has: every
assertion here is about what the function returned, never about its source.

What is pinned, and why each is a defect if it breaks:

  * **the same graph lands the same way every time** — a canvas that reshuffles
    on every open is one a person has to re-read on every open;
  * **a chain reads left to right** — a step's column is the longest path to it,
    and the step reached *if it works* sits above the one reached *if it fails*;
  * **workflows do not overlap**, the longest is drawn first, and tasks chained
    to nothing sit in a grid underneath, ready to be joined;
  * **a cycle does not hang the window** — the engine refuses one, and a
    hand-edited database can still hold one (`longestChain`'s promise, kept);
  * **a position a person chose is kept exactly**, and a step nobody placed
    goes where the layout would put it relative to its own workflow, never on
    top of something placed;
  * **the ports are `workflowDiagram.js:EDGE_WORDS`'s conditions, read rather
    than copied** — proven by handing the module a table with a third
    condition and watching a third port appear;
  * the geometry the canvas hit-tests with is the geometry it draws with.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LAYOUT_JS = ROOT / "static" / "js" / "workbench" / "graphLayout.js"
DIAGRAM_JS = ROOT / "static" / "js" / "tasks" / "workflowDiagram.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _layout(tmp_path: Path, script: str, module: Path = LAYOUT_JS) -> dict:
    entry = tmp_path / "case.mjs"
    entry.write_text("import * as gl from '%s';\n" % module.as_posix() + textwrap.dedent(script),
                     encoding="utf-8")
    proc = subprocess.run(["node", str(entry)], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


# The shape `build_task_graph` serves. A three-step chain with a failure branch
# off its first step, a second two-step chain, two tasks chained to nothing,
# and an edge to a task the caller cannot see (`dangling`, kept on purpose).
_GRAPH = {
    "nodes": [
        {"id": "lone1", "name": "Tidy sessions"},
        {"id": "a", "name": "Nightly backup"},
        {"id": "b", "name": "Verify backup"},
        {"id": "c", "name": "Post the summary"},
        {"id": "d", "name": "Message me"},
        {"id": "p", "name": "Fetch feed"},
        {"id": "q", "name": "Summarise feed"},
        {"id": "lone2", "name": "Weekly report"},
    ],
    "edges": [
        {"from": "a", "to": "b", "when": "success", "dangling": False},
        {"from": "a", "to": "d", "when": "error", "dangling": False},
        {"from": "b", "to": "c", "when": "success", "dangling": False},
        {"from": "p", "to": "q", "when": "success", "dangling": False},
        {"from": "q", "to": "gone", "when": "error", "dangling": True},
    ],
    "conditions": ["success", "error"],
    "max_depth": 10,
}

_OVERLAPS = """
const overlaps = (list) => {
  const out = [];
  for (let i = 0; i < list.length; i++) for (let j = i + 1; j < list.length; j++) {
    const a = list[i], b = list[j];
    if (a.x < b.x + gl.NODE_W && b.x < a.x + gl.NODE_W && a.y < b.y + gl.NODE_H && b.y < a.y + gl.NODE_H)
      out.push([a.id, b.id]);
  }
  return out;
};
const at = (r) => Object.fromEntries(r.nodes.map((n) => [n.id, n]));
"""


def test_the_same_graph_always_lands_the_same_way(tmp_path):
    """Twice in one process, and once more through a JSON round trip of the
    input — a layout that read `Map` insertion order or `Math.random` would
    differ between the three."""
    out = _layout(tmp_path, """
        const g = %s;
        const one = gl.layoutGraph(g, {});
        const two = gl.layoutGraph(g, {});
        const three = gl.layoutGraph(JSON.parse(JSON.stringify(g)), new Map());
        console.log(JSON.stringify({ one, same: JSON.stringify(one) === JSON.stringify(two)
          && JSON.stringify(one) === JSON.stringify(three) }));
    """ % json.dumps(_GRAPH))
    assert out["same"] is True
    ids = [n["id"] for n in out["one"]["nodes"]]
    assert sorted(ids) == sorted(["lone1", "a", "b", "c", "d", "p", "q", "lone2", "gone"])
    for n in out["one"]["nodes"]:
        assert isinstance(n["x"], (int, float)) and isinstance(n["y"], (int, float)), n


def test_a_chain_reads_left_to_right_and_works_sits_above_fails(tmp_path):
    out = _layout(tmp_path, _OVERLAPS + """
        const r = gl.layoutGraph(%s, {});
        const n = at(r);
        console.log(JSON.stringify({ n, step: gl.NODE_W + gl.GAP_X }));
    """ % json.dumps(_GRAPH))
    n, step = out["n"], out["step"]
    # Columns: the longest path to each step.
    assert n["b"]["x"] - n["a"]["x"] == step
    assert n["c"]["x"] - n["b"]["x"] == step
    assert n["d"]["x"] == n["b"]["x"], "both branches of `a` are one column on"
    # `if it works` above `if it fails`, and the step it leads to stays level.
    assert n["b"]["y"] == n["a"]["y"] < n["d"]["y"]
    assert n["c"]["y"] == n["b"]["y"]


def test_workflows_do_not_overlap_the_longest_comes_first_and_loners_wait_below(tmp_path):
    out = _layout(tmp_path, _OVERLAPS + """
        const r = gl.layoutGraph(%s, {});
        console.log(JSON.stringify({ n: at(r), overlaps: overlaps(r.nodes), comps: r.components }));
    """ % json.dumps(_GRAPH))
    n = out["n"]
    assert out["overlaps"] == []
    # Three steps deep before two steps deep, whatever order they were served.
    assert out["comps"][0][0] == "a" and set(out["comps"][0]) == {"a", "b", "c", "d"}
    assert set(out["comps"][1]) == {"p", "q", "gone"}
    assert max(n[i]["y"] for i in "abcd") < min(n[i]["y"] for i in ("p", "q"))
    # A task chained to nothing is its own component, in served order, under
    # every workflow and side by side.
    assert out["comps"][2:] == [["lone1"], ["lone2"]]
    assert n["lone1"]["y"] == n["lone2"]["y"] > max(n[i]["y"] for i in ("p", "q", "gone"))
    assert n["lone1"]["x"] < n["lone2"]["x"]
    # The far end of a dangling edge is drawn and marked, not dropped.
    assert n["gone"]["missing"] is True and n["a"]["missing"] is False


def test_a_cycle_terminates_and_every_step_is_still_placed(tmp_path):
    """Two-step loop, a three-step loop with a branch out, a self-loop, and a
    loop with no entry at all. Run under node's own timeout: a walk that did
    not set the back edge aside would spin here rather than fail."""
    loops = {
        "nodes": [{"id": x} for x in ("a", "b", "c", "d", "e", "s", "x", "y")],
        "edges": [
            {"from": "a", "to": "b", "when": "success"},
            {"from": "b", "to": "a", "when": "error"},
            {"from": "c", "to": "d", "when": "success"},
            {"from": "d", "to": "e", "when": "success"},
            {"from": "e", "to": "c", "when": "success"},
            {"from": "e", "to": "a", "when": "error"},
            {"from": "s", "to": "s", "when": "success"},
            {"from": "x", "to": "y", "when": "success"},
            {"from": "y", "to": "x", "when": "success"},
        ],
    }
    out = _layout(tmp_path, _OVERLAPS + """
        const t0 = Date.now();
        const r = gl.layoutGraph(%s, {});
        console.log(JSON.stringify({ ms: Date.now() - t0, n: at(r), overlaps: overlaps(r.nodes),
          finite: r.nodes.every((p) => Number.isFinite(p.x) && Number.isFinite(p.y)) }));
    """ % json.dumps(loops))
    assert out["finite"] is True
    assert set(out["n"]) == {"a", "b", "c", "d", "e", "s", "x", "y"}
    assert out["overlaps"] == []
    assert out["ms"] < 2000, out["ms"]
    # The back edge is set aside, so a loop still reads as a chain.
    assert out["n"]["d"]["x"] > out["n"]["c"]["x"] and out["n"]["e"]["x"] > out["n"]["d"]["x"]


def test_a_long_chain_does_not_run_out_of_stack(tmp_path):
    """The walk is iterative. Two thousand steps in a line would overflow a
    recursive one long before the browser's stack would forgive it."""
    out = _layout(tmp_path, """
        const N = 2000;
        const g = { nodes: Array.from({ length: N }, (_, i) => ({ id: 't' + i })),
          edges: Array.from({ length: N - 1 }, (_, i) => ({ from: 't' + i, to: 't' + (i + 1), when: 'success' })) };
        const r = gl.layoutGraph(g, {});
        const n = Object.fromEntries(r.nodes.map((p) => [p.id, p]));
        console.log(JSON.stringify({ last: n['t' + (N - 1)].x, first: n.t0.x, step: gl.NODE_W + gl.GAP_X }));
    """)
    assert out["last"] - out["first"] == 1999 * out["step"]


def test_a_position_a_person_chose_is_kept_and_nothing_lands_on_it(tmp_path):
    """`a` placed somewhere else entirely: it stays to the pixel; `b`, `c` and
    `d` — never placed — follow it, keeping their places relative to `a`; and
    the other workflow and the loners, with nothing placed and nothing in their
    way, stay exactly where the layout puts them.

    Measured in Chromium before the rule was this one: every unplaced workflow
    went below the lowest placed step, so a person who nudged one step 32px
    found the whole canvas rearranged on their next visit."""
    out = _layout(tmp_path, _OVERLAPS + """
        const g = %s;
        const base = at(gl.layoutGraph(g, {}));
        const r = gl.layoutGraph(g, { a: { x: 900, y: 700 }, lone2: { x: 40, y: 40 } });
        console.log(JSON.stringify({ base, n: at(r), overlaps: overlaps(r.nodes) }));
    """ % json.dumps(_GRAPH))
    base, n = out["base"], out["n"]
    assert (n["a"]["x"], n["a"]["y"], n["a"]["saved"]) == (900, 700, True)
    assert (n["lone2"]["x"], n["lone2"]["y"], n["lone2"]["saved"]) == (40, 40, True)
    for i in "bcd":
        assert n[i]["saved"] is False
        assert n[i]["x"] - n["a"]["x"] == base[i]["x"] - base["a"]["x"], i
        assert n[i]["y"] - n["a"]["y"] == base[i]["y"] - base["a"]["y"], i
    assert out["overlaps"] == []
    for i in ("p", "q", "gone", "lone1"):
        assert (n[i]["x"], n[i]["y"]) == (base[i]["x"], base[i]["y"]), i


def test_a_workflow_in_the_way_of_a_placed_step_moves_down_as_a_whole(tmp_path):
    """A person drops a task chained to nothing exactly where the second
    workflow is laid out. That workflow moves down — every step of it by the
    same amount, so it still reads as itself — and lands on nothing."""
    out = _layout(tmp_path, _OVERLAPS + """
        const g = %s;
        const base = at(gl.layoutGraph(g, {}));
        const r = gl.layoutGraph(g, { lone1: { x: base.q.x, y: base.q.y } });
        console.log(JSON.stringify({ base, n: at(r), overlaps: overlaps(r.nodes) }));
    """ % json.dumps(_GRAPH))
    base, n = out["base"], out["n"]
    assert out["overlaps"] == []
    dy = n["p"]["y"] - base["p"]["y"]
    assert dy > 0
    for i in ("p", "q", "gone"):
        assert n[i]["x"] == base[i]["x"] and n[i]["y"] - base[i]["y"] == dy, i
    for i in "abcd":
        assert (n[i]["x"], n[i]["y"]) == (base[i]["x"], base[i]["y"]), "the first workflow was not in the way"


def test_a_step_placed_beside_its_workflow_moves_off_a_step_someone_put_there(tmp_path):
    """`b` would land where the person put `z`. It moves down a row instead."""
    g = {"nodes": [{"id": "a"}, {"id": "b"}, {"id": "z"}],
         "edges": [{"from": "a", "to": "b", "when": "success"}]}
    out = _layout(tmp_path, _OVERLAPS + """
        const g = %s;
        const base = at(gl.layoutGraph(g, {}));
        const r = gl.layoutGraph(g, { a: base.a, z: base.b });
        console.log(JSON.stringify({ base, n: at(r), overlaps: overlaps(r.nodes) }));
    """ % json.dumps(g))
    n, base = out["n"], out["base"]
    assert (n["z"]["x"], n["z"]["y"]) == (base["b"]["x"], base["b"]["y"])
    assert n["b"]["x"] == base["b"]["x"] and n["b"]["y"] > base["b"]["y"]
    assert out["overlaps"] == []


def test_a_saved_position_for_a_task_that_is_gone_is_ignored(tmp_path):
    out = _layout(tmp_path, """
        const r = gl.layoutGraph({ nodes: [{ id: 'a' }], edges: [] },
          { deleted: { x: 5, y: 5 }, a: { x: 'nope', y: 3 } });
        console.log(JSON.stringify(r.nodes));
    """)
    assert [n["id"] for n in out] == ["a"]
    assert out[0]["saved"] is False, "a non-numeric position is not a placement"


def test_the_ports_are_the_diagrams_conditions_read_not_copied(tmp_path):
    """A copy of `workflowDiagram.js` with a third condition beside the two, and
    the real `graphLayout.js` beside it: the third port appears below the
    second, at the same spacing. A module holding its own list would still
    say two."""
    box = tmp_path / "js"
    (box / "tasks").mkdir(parents=True)
    (box / "workbench").mkdir()
    diagram = DIAGRAM_JS.read_text(encoding="utf-8").replace(
        "  error: 'if it fails',\n});",
        "  error: 'if it fails',\n  skipped: 'if it is skipped',\n});", 1)
    assert "if it is skipped" in diagram, "EDGE_WORDS moved — re-read this test"
    (box / "tasks" / "workflowDiagram.js").write_text(diagram, encoding="utf-8")
    shutil.copy(LAYOUT_JS, box / "workbench" / "graphLayout.js")
    out = _layout(tmp_path, """
        const p = { x: 0, y: 0 };
        console.log(JSON.stringify({ ports: gl.PORTS,
          ys: gl.PORTS.map((w) => gl.portPoint(p, w).y) }));
    """, module=box / "workbench" / "graphLayout.js")
    assert out["ports"] == ["success", "error", "skipped"]
    ys = out["ys"]
    assert ys[1] - ys[0] == ys[2] - ys[1] > 0


def test_the_geometry_the_canvas_hits_is_the_geometry_it_draws(tmp_path):
    out = _layout(tmp_path, """
        const a = { id: 'a', x: 100, y: 50 }, b = { id: 'b', x: 500, y: 300 };
        const works = gl.portPoint(a, 'success'), fails = gl.portPoint(a, 'error'), into = gl.inputPoint(b);
        console.log(JSON.stringify({
          works, fails, into, W: gl.NODE_W, H: gl.NODE_H,
          path: gl.edgePath(works, into), mid: gl.edgeMid(works, into), head: gl.arrowPath(into),
          insideB: gl.nodeAt([a, b], { x: 510, y: 310 }, null),
          onEdgeOfA: gl.nodeAt([a, b], { x: 100 + gl.NODE_W, y: 50 }, null),
          excluded: gl.nodeAt([a, b], { x: 110, y: 60 }, 'a'),
          nowhere: gl.nodeAt([a, b], { x: 0, y: 0 }, null),
          topmost: gl.nodeAt([a, { id: 'c', x: 100, y: 50 }], { x: 110, y: 60 }, null),
        }));
    """)
    assert out["works"] == {"x": 100 + out["W"], "y": out["works"]["y"]}
    assert 50 < out["works"]["y"] < out["fails"]["y"] < 50 + out["H"]
    assert out["into"] == {"x": 500, "y": 300 + out["H"] / 2}
    assert out["path"].startswith("M %g %g C " % (out["works"]["x"], out["works"]["y"]))
    assert out["path"].endswith(", 500 %g" % out["into"]["y"])
    assert out["head"].startswith("M 500 %g L 491 " % out["into"]["y"])
    assert out["insideB"] == "b" and out["onEdgeOfA"] == "a"
    assert out["excluded"] is None and out["nowhere"] is None
    assert out["topmost"] == "c", "the last step drawn is the one on top"


def test_fit_shows_everything_and_never_divides_by_a_window_with_no_size(tmp_path):
    out = _layout(tmp_path, """
        const big = { x: 40, y: 40, w: 2000, h: 900 };
        const small = { x: 40, y: 40, w: 232, h: 96 };
        console.log(JSON.stringify({
          big: gl.fitView(big, 1000, 600), small: gl.fitView(small, 1000, 600),
          none: gl.fitView(big, 0, 0), empty: gl.fitView(gl.boundsOf([]), 800, 600),
          clamp: [gl.clampZoom(0.01), gl.clampZoom(50), gl.clampZoom('x')],
          lo: gl.ZOOM_MIN, hi: gl.ZOOM_MAX,
        }));
    """)
    big = out["big"]
    assert out["lo"] <= big["zoom"] < 1
    # The whole box is inside the viewport at that zoom.
    assert big["x"] + 40 * big["zoom"] >= 0 and big["x"] + 2040 * big["zoom"] <= 1000 + 0.5
    assert big["y"] + 40 * big["zoom"] >= 0 and big["y"] + 940 * big["zoom"] <= 600 + 0.5
    assert out["small"]["zoom"] == 1, "two steps are not blown up to fill the window"
    assert out["none"] == {"zoom": 1, "x": 0, "y": 0}
    assert out["empty"]["zoom"] == 1
    assert out["clamp"] == [out["lo"], out["hi"], 1]
