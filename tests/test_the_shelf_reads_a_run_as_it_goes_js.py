# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B1108` — the shelf reads a run's state while the room is open.

Measured by `integrate-d` (`dark-1400-11-waiting.png`): with *Three feeds*
open, its Runs list read "… Waiting · 5:25:49 AM" and the shelf beside it
"Three feeds · On · Not run yet"; reopening the room read "Last run:
Success". The server's `last_real_runs` already served the run — the shelf was
drawn when the room opened (and after a save or a switch), not when a run
started or ended. Now *Run now* and an answer read the shelf again, the Runs
list sets the open workflow's row whenever it is read (the server's rule: a
dry run is never a last run), and while the server's shelf lists a run in
flight it is read again every `SHELF_WATCH_MS` (4 s) — and not at all while
nothing is in flight.

Driven end to end (`Law 20`): the real room, canvas, source and
`workflowApi.js` in node against the REAL server on a loopback port
(`tests/helpers/workflow_live.py`): Run now reaches the real task route and the
real scheduler runs the workflow in the server's own loop; one step takes 1.5 s
(its executor is the recorder, the one stand-in), another parks on a Wait.
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


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    return build_sandbox(tmp_path_factory.mktemp("shelf"), _CANVAS_SHIM)


@pytest.fixture()
def live(monkeypatch, tmp_path):
    from tests.helpers.assist_harness import build_world

    w = build_world(monkeypatch, tmp_path)

    async def slow(task, run_id):
        await asyncio.sleep(1.5)
        return "Tidied."

    w.s_outcomes = {"Slow one · Tidy": slow}
    # The recorder answers the outcome named for the stand-in (`walker_harness`).
    original = w.s._execute_action

    async def action(task, run_id=None):
        if task.name in w.s_outcomes:
            from src.builtin_actions import NodeResult
            return NodeResult("success", payload=await w.s_outcomes[task.name](task, run_id))
        return await original(task, run_id=run_id)

    w.s._execute_action = action
    seed_workflow(w.factory, [node("tidy", "Tidy", "action", action="tidy_sessions")],
                  task_id="slow", name="Slow one", trigger_type="webhook")
    seed_workflow(w.factory, [node("a", "Tidy first", "action", action="tidy_sessions"),
                              node("w", "Then wait", "wait", mode="for", minutes=30)],
                  [arrow("a", "w")], task_id="parks", name="Parks on a wait", trigger_type="webhook")
    w.server = LiveServer(w.app)
    try:
        yield w
    finally:
        w.server.close()


_HELPERS = """
const shelfRow = (r, key) => {
  const b = r.querySelectorAll('.wf-shelf-item').find((x) => x.dataset.key === key);
  return b ? b.querySelector('.wf-shelf-last').textContent : null;
};
const lists = () => calls('GET', (u) => u === '/api/workflows').length;
const open = async (r, key) => {
  fire(r.querySelectorAll('.wf-shelf-item').find((b) => b.dataset.key === key), 'click'); await quiet();
};
const runNow = async (r) => { fire(by(r, 'wf-run-now'), 'click'); await quiet(); };
const wait = (ms) => new Promise((res) => setTimeout(res, ms));
"""


def test_run_now_reads_the_shelf_and_the_shelf_reads_the_end_of_the_run(box, live):
    o = _run(box, LIVE_PREAMBLE(live.server.base) + _HELPERS, """
        const { r, handle } = await room();
        const atOpen = shelfRow(r, 'w-slow');
        await open(r, 'w-slow');
        await runNow(r);
        const started = shelfRow(r, 'w-slow');
        await wait(1800);                       // the step ends; the shelf has not been read since
        const beforeTheWatch = shelfRow(r, 'w-slow');
        await wait(4500); await quiet();        // one SHELF_WATCH_MS later
        const ended = shelfRow(r, 'w-slow');
        const listsAfterEnd = lists();
        await wait(4500); await quiet();
        out({ atOpen, started, beforeTheWatch, ended, quietAfter: lists() - listsAfterEnd,
              runs: calls('POST', (u) => u.endsWith('/run')).length });
        handle.destroy();
    """)
    assert o["atOpen"] == "Not run yet"
    assert o["runs"] == 1
    assert o["started"] in ("Last run: Queued", "Last run: Running"), o
    assert o["ended"] == "Last run: Success", "read without opening the room again"
    assert o["quietAfter"] == 0, "nothing in flight: the shelf is not read again"


def test_the_shelf_says_what_the_runs_list_says_of_a_parked_run(box, live):
    """The drive's case: the run parks on a Wait while the room is open."""
    o = _run(box, LIVE_PREAMBLE(live.server.base) + _HELPERS, """
        const { r, handle } = await room();
        await open(r, 'w-parks');
        await runNow(r);
        await wait(4500); await quiet();
        const shelf = shelfRow(r, 'w-parks');
        fire(r.querySelectorAll('.wf-tab').find((t) => t.textContent === 'Runs'), 'click'); await quiet();
        out({ shelf, runWord: all(r, 'wf-run-word').map((s) => s.textContent),
              afterRuns: shelfRow(r, 'w-parks'), other: shelfRow(r, 'w-slow') });
        handle.destroy();
    """)
    assert o["runWord"] == ["Waiting"]
    assert o["shelf"] == "Last run: Waiting" and o["afterRuns"] == "Last run: Waiting"
    assert o["other"] == "Not run yet", "another workflow's row is its own"


def test_the_runs_list_sets_the_open_workflows_row(box, live):
    """A run the room did not start (a webhook, another tab): reading the
    Runs list is enough for the shelf to say it — no watch was armed, since
    nothing the room knew of was in flight."""
    o = _run(box, LIVE_PREAMBLE(live.server.base) + _HELPERS, """
        const { r, handle } = await room();
        await open(r, 'w-slow');
        const before = shelfRow(r, 'w-slow');
        const listed = lists();
        await net('/api/tasks/slow/run', { method: 'POST' });   // as another tab would
        await wait(2000);
        fire(r.querySelectorAll('.wf-tab').find((t) => t.textContent === 'Runs'), 'click'); await quiet();
        out({ before, runWord: all(r, 'wf-run-word').map((s) => s.textContent),
              after: shelfRow(r, 'w-slow'), shelfReads: lists() - listed });
        handle.destroy();
    """)
    assert o["before"] == "Not run yet"
    assert o["runWord"] == ["Success"]
    assert o["after"] == "Last run: Success", "the Runs list and the shelf say the same"
    assert o["shelfReads"] == 0, "from the list just read — no second request"
