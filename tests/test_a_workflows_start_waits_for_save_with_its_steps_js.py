# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B1209` — a workflow's start is part of its draft: its Done waits for the
toolbar's Save, which sends it with the steps, and leaving asks about it.

**Measured before this file** (`fx-words`, `P23-05`, and here): Workbench → a
workflow → *Starts*: its own *Save* wrote the trigger task at once
(`PUT /api/tasks/{id}`), while a step's *Done* waited for the toolbar's
*Save*; and closing asked about the steps only (`WB-U-3`) — a change to the
start was never "unsaved", whatever else was.

Now the start's form says *Done* and hands what changed to the workflow's
source (`startPatch`); the canvas shows it, the workflow is dirty, leaving
asks, Discard drops it, and Save writes it through `PUT /api/tasks/{id}` and
then the steps.

Driven end to end (`Law 20`): the real room, canvas, panels, source and
`workflowApi.js` in node against the REAL server on a loopback port
(`tests/helpers/workflow_live.py`). The start's form is the `P22` panel
contract, recorded (its own Done is driven in
`test_one_form_for_a_step_and_a_start_js.py`): the case calls the `onSaved`
the panel handed it, with what that form hands over.
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
from tests.helpers.walker_harness import arrow, node, row, seed_workflow  # noqa: E402

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

# What the start's form hands over on Done (`taskFields.js` `'trigger'` mode).
PATCH = {"trigger_type": "schedule", "schedule": "daily", "scheduled_time": "07:30", "tz_name": "",
         "max_retries": 0, "timeout_seconds": 0, "notifications_enabled": True}


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    return build_sandbox(tmp_path_factory.mktemp("startdraft"), _CANVAS_SHIM)


@pytest.fixture()
def live(monkeypatch, tmp_path):
    from tests.helpers.assist_harness import build_world

    w = build_world(monkeypatch, tmp_path)
    seed_workflow(w.factory, [node("n1", "Summarise my inbox"), node("n2", "Send me the summary")],
                  [arrow("n1", "n2")], trigger_type="schedule", schedule="daily", scheduled_time="08:00")
    w.server = LiveServer(w.app)
    try:
        yield w
    finally:
        w.server.close()


_OPEN_START = """
const forms = [];
const recorder = (host, args) => { forms.push({ ...args, host }); return { destroy() {} }; };
// A person changes a field: the event reaches the start panel's host, as typing does.
const typedIn = (f) => f.host.dispatchEvent({ type: 'input', target: f.host, stopPropagation() {}, preventDefault() {} });
const said = (t) => t && t.scheduled_time ? 'Daily at ' + t.scheduled_time : '';
const { r } = await room({ workflowId: 'w-wf', mountTaskFields: recorder, describeTrigger: said });
const startSub = () => nodeEl(r, '__start__').querySelector('.wb-node-sub').textContent;
const startPuts = () => calls('PUT', (u) => u === '/api/tasks/wf');
fire(nodeEl(r, '__start__'), 'click'); await quiet();
const form = forms[forms.length - 1];
const before = { mode: form.mode, time: form.task.scheduled_time, sub: startSub() };
typedIn(form);
await form.onSaved(PATCH); await quiet();
const afterDone = { puts: startPuts().length, dirty: by(r, 'wf-dirty').textContent, sub: startSub() };
"""


def _case(box, live, script):
    import json
    return _run(box, LIVE_PREAMBLE(live.server.base) + f"const PATCH = {json.dumps(PATCH)};\n"
                + _OPEN_START, script)


def test_done_on_the_start_waits_for_save_and_save_sends_it(box, live):
    o = _case(box, live, """
        fire(by(r, 'wf-save'), 'click'); await quiet();
        out({ before, afterDone, puts: startPuts().map(([, b]) => b),
              afterSave: { dirty: by(r, 'wf-dirty').textContent, sub: startSub() } });
    """)
    assert o["before"] == {"mode": "trigger", "time": "08:00", "sub": "Daily at 08:00"}
    assert o["afterDone"]["puts"] == 0, "Done wrote the start at once"
    assert o["afterDone"]["dirty"] == "Unsaved changes", "the start's change is in the draft"
    assert o["afterDone"]["sub"] == "Daily at 07:30", "the canvas shows the draft's start"
    (sent,) = o["puts"]
    assert sent["scheduled_time"] == "07:30", "Save sends the start, through the task door"
    assert set(sent) <= set(PATCH) and "schedule" not in sent and "trigger_type" not in sent, (
        "only what differs from the saved start is sent")
    assert o["afterSave"]["dirty"] in ("Saved", "")
    assert o["afterSave"]["sub"] == "Daily at 07:30"
    assert row(live.factory, "wf").scheduled_time == "07:30"


def test_leaving_with_only_the_start_changed_asks_and_discard_drops_it(box, live):
    o = _case(box, live, """
        fire(r.querySelectorAll('.wf-shelf-item').find((b) => b.dataset.key === 'tasks'), 'click'); await quiet();
        const leave = by(r, 'wf-ask');
        const asked = { shown: !leave.hidden, words: leave.textContent };
        fire(by(r, 'wf-ask-discard'), 'click'); await quiet();
        out({ asked, puts: startPuts().length, onTasks: !by(r, 'wf-view') || by(r, 'wf-view').hidden });
    """)
    assert o["asked"]["shown"] is True, "closing asked about the steps only"
    assert "not saved" in o["asked"]["words"]
    assert o["puts"] == 0 and o["onTasks"] is True
    assert row(live.factory, "wf").scheduled_time == "08:00", "Discard drops the start's change"


def test_a_done_that_changed_nothing_is_not_an_edit(box, live):
    o = _case(box, live, """
        fire(nodeEl(r, '__start__'), 'click'); await quiet();
        const again = forms[forms.length - 1];
        const shownAgain = again.task.scheduled_time;
        await again.onSaved(null); await quiet();      // the form's Done with nothing touched
        out({ shownAgain, dirty: by(r, 'wf-dirty').textContent });
    """)
    assert o["shownAgain"] == "07:30", "the start's form opens on the draft's start"
    assert o["dirty"] == "Unsaved changes", "the first Done's change is still there"
