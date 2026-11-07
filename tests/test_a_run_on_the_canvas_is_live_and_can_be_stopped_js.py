# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B1837`, `B1869`, `B1847` — a run on the Automations canvas is read as it
goes, can be stopped where it is, and switching off says first what it ends.

**Measured before this file** (the live-UX audit, 2026-11-07, in Chromium
against the real server): a run's canvas was drawn once, when it was opened —
a step that finished after that still read "Running" until the run was opened
again — and the arrows a run took looked like the ones it did not; a run on
the Runs tab had no Stop (the only stop was the Tasks window's, by task); and
switching off while a run waited in a Wait said only "Switched off." — the run
was later found "Stopped", with nothing said at the press.

Each case drives the real room, canvas, panels, source and `workflowApi.js`
in node against the REAL server on a loopback port
(`tests/helpers/workflow_live.py`); Run now reaches the real task route and
the real scheduler walks the workflow in the server's own loop, where it
parks on a five-minute Wait.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_tool_effect_surfaces_js import _run  # noqa: E402
from test_the_workbench_canvas_js import _SHIM as _CANVAS_SHIM  # noqa: E402
from helpers.workflow_live import LIVE_PREAMBLE, LiveServer, build_sandbox  # noqa: E402
from tests.helpers.walker_harness import arrow, node, runs_of, seed_workflow  # noqa: E402

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    return build_sandbox(tmp_path_factory.mktemp("liverun"), _CANVAS_SHIM)


@pytest.fixture()
def live(monkeypatch, tmp_path):
    from tests.helpers.assist_harness import build_world

    w = build_world(monkeypatch, tmp_path)
    seed_workflow(w.factory, [
        node("a", "Make it", "set", fields=[{"name": "title", "value": "Printer on fire"}]),
        node("b", "Shout it", "set", fields=[{"name": "loud", "value": "{{ steps.a.data.title }}"}]),
        node("w", "Pause", "wait", mode="for", minutes=5),
    ], [arrow("a", "b"), arrow("b", "w")], trigger_type="webhook")
    w.server = LiveServer(w.app)
    try:
        yield w
    finally:
        w.server.close()


_HELPERS = """
const wait = (ms) => new Promise((res) => setTimeout(res, ms));
const runView = (r) => r.querySelector('.wf-run-canvas');
const runNode = (r, id) => runView(r).querySelectorAll('.wb-node').find((n) => n.dataset.itemId === id) || null;
const runSay = (r) => { const s = runView(r).querySelectorAll('.wb-say-text').filter(shown); return s.length ? s[s.length - 1].textContent : ''; };
const runSayButton = (r) => runView(r).querySelectorAll('.wb-say-action').find((b) => !b.hidden && shown(b)) || null;
const runEdges = (r) => runView(r).querySelectorAll('g').filter((g) => g.getAttribute('data-from') != null)
  .map((g) => [g.getAttribute('data-from'), g.getAttribute('data-to'), g.getAttribute('data-taken')]);
const runsTab = (r) => r.querySelectorAll('.wf-tab').find((t) => t.textContent === 'Runs');
const statusOf = async () => { const l = await ask('/api/tasks/wf/runs'); const runs = l.runs || l; return runs.length ? runs[0].status : null; };
// Run now, then wait until the real scheduler has parked the run on its Wait.
const parked = async (r) => {
  fire(by(r, 'wf-run-now'), 'click'); await quiet();
  for (let i = 0; i < 60; i += 1) { if ((await statusOf()) === 'waiting') return true; await wait(100); }
  return false;
};
"""


def _case(box, live, script):
    return _run(box, LIVE_PREAMBLE(live.server.base) + _HELPERS, script)


def test_a_parked_run_lights_the_steps_it_ran_and_the_arrows_it_took(box, live):
    o = _case(box, live, """
        const { r } = await room({ workflowId: 'w-wf' });
        const isParked = await parked(r);
        fire(runsTab(r), 'click'); await quiet();
        const outcome = (id) => { const n = runNode(r, id); return n ? n.dataset.outcome || null : null; };
        const last = (id) => { const n = runNode(r, id); const l = n && n.querySelector('.wb-node-last');
          return l ? (l.readable || l.textContent) : null; };
        out({ isParked, a: outcome('a'), b: outcome('b'), w: outcome('w'), aWords: last('a'),
              edges: runEdges(r), said: runSay(r), action: runSayButton(r) && runSayButton(r).textContent });
    """)
    assert o["isParked"] is True
    assert o["a"] == "ok" and o["b"] == "ok", "the steps it ran are lit as they went"
    assert o["w"] == "pending", o
    assert " · " in (o["aWords"] or ""), "how long the step took is on its box"
    taken = {(f, t): lit for f, t, lit in o["edges"]}
    assert taken[("a", "b")] == "true" and taken[("b", "w")] == "true", o["edges"]
    assert o["said"].startswith("“Pause” is waiting"), o["said"]
    assert o["action"] == "Stop this run", "a waiting run offers Stop where it is said"


def test_stop_on_the_open_run_ends_it_where_it_waits(box, live):
    o = _case(box, live, """
        const { r } = await room({ workflowId: 'w-wf' });
        await parked(r);
        fire(runsTab(r), 'click'); await quiet();
        fire(runSayButton(r), 'click'); await quiet();
        out({ said: runSay(r), status: await statusOf(),
              stops: calls('POST', (u) => u.endsWith('/stop')).map(([u]) => u),
              word: all(r, 'wf-run-word').map((s) => s.textContent) });
    """)
    assert len(o["stops"]) == 1 and o["stops"][0].startswith("/api/workflows/w-wf/runs/")
    assert o["status"] == "aborted"
    assert o["said"].startswith("Stopped where it waited."), o["said"]
    [run] = runs_of(live.factory, "wf")
    assert run["status"] == "aborted"


def test_switching_off_while_a_run_waits_says_so_first_and_ends_it_on_the_second_press(box, live):
    o = _case(box, live, """
        const { r } = await room({ workflowId: 'w-wf' });
        await parked(r);
        const before = by(r, 'wf-switch').textContent;
        fire(by(r, 'wf-switch'), 'click'); await quiet();
        const asked = sayOf(r);
        const button = sayButton(r) && sayButton(r).textContent;
        const still = by(r, 'wf-switch').textContent;
        const statusAsked = await statusOf();
        fire(sayButton(r), 'click'); await quiet();
        out({ before, asked, button, still, statusAsked, after: by(r, 'wf-switch').textContent, said: sayOf(r) });
    """)
    assert o["before"] == "On"
    assert o["asked"].startswith("A run is waiting in “Pause”. Switching off ends it there"), o["asked"]
    assert o["button"] == "Switch off and end it"
    assert o["still"] == "On" and o["statusAsked"] == "waiting", "said first: nothing is switched off yet"
    assert o["after"] == "Off"
