# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B1888` (front end) — *Test this step* shows what the step reads, and a
value typed there is what that step made in the test.

**Measured before this file**: the route learned to answer what a tested
step's references read (`context_only`, `reads`) and to take what the person
types for the steps it reads (`outputs`), and the panel asked neither — so an
If that reads a step two back could only be tested on that step's last real
record, whatever was typed in the one input box (which is the step before's
hand-off, not the step two back).

Now the panel asks, when it opens and whenever its input changes, what the
step would read, and draws one box per step its settings name, each saying
where its value came from; a box the person changes is sent as `outputs`.

Driven end to end (`Law 20`): the real routes over a real SQLite file
(`assist_harness`), the real room, canvas, panels, source and
`workflowApi.js` in node against the REAL server on a loopback port.
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
from helpers.workflow_live import LIVE_PREAMBLE, LiveServer, as_js, build_sandbox  # noqa: E402
from tests.helpers.walker_harness import arrow, node, seed_workflow  # noqa: E402

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    return build_sandbox(tmp_path_factory.mktemp("testreads"), _CANVAS_SHIM)


@pytest.fixture()
def world(monkeypatch, tmp_path):
    from tests.helpers.assist_harness import build_world

    w = build_world(monkeypatch, tmp_path)
    seed_workflow(w.factory, [
        node("a", "Score", "set", fields=[{"name": "score", "value": 1}]),
        node("b", "Note", "set", fields=[{"name": "note", "value": "seen"}]),
        node("c", "High?", "if", join="all", conditions=[
            {"left": "{{ steps.a.data.score }}", "op": "greater_than", "right": "5"},
            {"left": "{{ steps.b.data.note }}", "op": "equals", "right": "seen"}]),
    ], [arrow("start", "a"), arrow("a", "b"), arrow("b", "c")], trigger_type="webhook",
        webhook_token="tok", schedule=None)
    asyncio.run(w.s._execute_task("wf"))     # a real run: score 1, so "otherwise"
    w.server = LiveServer(w.app)
    try:
        yield w
    finally:
        w.server.close()


_OPEN = """
const panelOf = async (r, id) => {
  fire(nodeEl(r, id), 'click'); await quiet();
  const open = all(r, 'wf-test').filter(shown);
  return open[open.length - 1];
};
const readsOf = (p) => ({
  head: p.querySelector('.wf-test-reads-head').textContent,
  shown: !p.querySelector('.wf-test-reads').hidden,
  rows: p.querySelectorAll('.wf-test-read').map((row) => [
    row.querySelector('.wf-test-read-name').textContent,
    row.querySelector('.wf-test-read-from').textContent,
    row.querySelector('.wf-test-read-input').value]),
});
const testsSent = () => calls('POST', (u) => u.endsWith('/nodes/c/test')).map((c) => c[1]);
"""


def _case(box, w, script):
    return _run(box, LIVE_PREAMBLE(w.server.base) + _OPEN + f"const WID = {as_js('w-wf')};\n", script)


def test_the_panel_shows_each_step_it_reads_and_a_changed_one_is_what_that_step_made(box, world):
    o = _case(box, world, """
        const { r } = await room({ workflowId: WID });
        const p = await panelOf(r, 'c');
        const before = readsOf(p);
        const asked = testsSent();
        // Two back: the score the run made was 1; type 9 for it.
        const score = p.querySelectorAll('.wf-test-read-input')[0];
        typed(score, '{"score": 9}');
        const after = readsOf(p);
        fire(p.querySelector('.wf-test-go'), 'click'); await quiet();
        const sent = testsSent();
        const oc = p.querySelector('.wf-test-outcome');
        out({ before, asked, after, sent: sent[sent.length - 1],
              outcome: oc ? oc.textContent : null,
              made: p.querySelector('.wf-test-result').textContent,
              said: p.querySelector('.wf-test-say').textContent });
    """)
    assert o["before"]["shown"] is True and o["before"]["head"] == "What it reads: 2 steps"
    # Two back reads its last run; the step before is what the chosen input
    # ("What it was handed in the last run") says it made.
    assert [row[:2] for row in o["before"]["rows"]] == [
        ["Score", "from its last run"], ["Note", "the input chosen above"]]
    assert '"score": 1' in o["before"]["rows"][0][2] and '"note": "seen"' in o["before"]["rows"][1][2]
    assert o["asked"] and all(body.get("context_only") is True for body in o["asked"]), \
        "opening the panel only asks what it would read: nothing runs"
    assert o["after"]["rows"][0][1] == "what you typed here"
    assert o["sent"].get("context_only") is None
    assert o["sent"]["outputs"] == {"a": {"data": {"score": 9}}}, "only the box the person changed"
    assert "Success" in o["outcome"], o
    assert "if so" in o["made"] or "then" in o["made"], o["made"]


def test_a_step_that_reads_no_other_step_shows_no_box(box, world):
    o = _case(box, world, """
        const { r } = await room({ workflowId: WID });
        const p = await panelOf(r, 'a');
        out(readsOf(p));
    """)
    assert o["shown"] is False and o["rows"] == []
