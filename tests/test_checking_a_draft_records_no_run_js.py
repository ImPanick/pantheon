# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B1132` — checking a drafted workflow's steps leaves its Runs list empty.

Measured by `wb-canvas-e` (drive, P22-24) and by `integrate-e` in every drive's
Runs list ("Dry run"), and here on `7a7f9b2`: the step banner and *Check them
now* read what a marked step would do from the existing dry-run door (`POST
/api/tasks/{id}/run?dry=true`, once per saved version), and every asking
recorded a `skipped` "Dry run — nothing ran, nothing changed." in the Runs — a
draft that was only read looked as if it had run, and a drive's run-wait took
the check's dry run for the newest run.

**The rule chosen:** checking is reading, and records nothing. While a step is
marked, the Doc carries what each marked step would do (`plans: {node_id:
[line]}`, the workflow dry run's own planner, `TaskScheduler._plan_workflow_
node` — and `plans_declined` when the engine would not run the document at
all); the browser reads that and asks no dry run. A dry run a person asks for
(*Show me what this would do*) is still a recorded "Dry run" (`Law 1`): that
is the person running the plan, and the Runs list is where its result is read.

Driven end to end (`Law 20`): the drafter's real routes and store with the
model's answer scripted (`assist_harness`), the real scheduler's planner, and
the real room, canvas, panels, source and `workflowApi.js` in node against the
REAL server on a loopback port (`tests/helpers/workflow_live.py`).
"""
from __future__ import annotations

import asyncio
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_tool_effect_surfaces_js import _run  # noqa: E402
from test_describe_it_drafts_a_workflow_js import (  # noqa: E402
    IDS, _DRAFT_AND_OPEN, _answer, box, live,  # noqa: F401
)
from helpers.workflow_live import LIVE_PREAMBLE  # noqa: E402


def _case(box, live, script):
    return _run(box, LIVE_PREAMBLE(live.server.base) + _DRAFT_AND_OPEN, script)


def test_checking_a_drafted_workflows_three_steps_leaves_its_runs_list_empty(box, live):
    """The row's `Verify:`, as a person does it: switch on, *Check them now*,
    *All look right*, then the Runs tab."""
    live.script(_answer())
    o = _case(box, live, """
        const { r, made } = await draftAndOpen();
        fire(by(r, 'wf-switch'), 'click'); await quiet();
        fire(sayButton(r), 'click'); await quiet();              // Check them now
        const layer = by(r, 'wf-check');
        const listed = all(layer, 'wf-check-step').map((li) => [li.dataset.nodeId,
          by(li, 'wf-check-plan').querySelectorAll('li').map((x) => x.textContent)]);
        fire(by(layer, 'wf-check-all'), 'click'); await quiet();  // All look right
        fire(r.querySelectorAll('.wf-tab').find((t) => t.textContent === 'Runs'), 'click'); await quiet();
        const taskId = made.reply.workflow.task_id;
        out({ listed, plans: made.reply.workflow.plans,
              dryRuns: calls('POST', (u) => u.includes('/run?dry=true')).length,
              runRows: all(r, 'wf-run-row').length, empty: all(r, 'wf-run-empty').map((x) => x.textContent),
              served: (await ask('/api/tasks/' + taskId + '/runs')).runs,
              after: (await ask('/api/workflows/' + made.reply.workflow.id)).workflow });
    """)
    assert [i for i, _ in o["listed"]] == IDS
    assert all(lines for _, lines in o["listed"]), "every marked step says what it would do"
    assert o["served"] == [] and o["runRows"] == 0, "its Runs list is empty"
    assert o["dryRuns"] == 0, "no dry run is asked to check a step"
    assert dict(o["listed"]) == o.get("plans"), "…as the Doc carries it"
    assert "plans" not in o["after"], "once nothing is marked, the Doc carries no plans"


@pytest.mark.asyncio
async def test_the_docs_plans_are_the_dry_runs_plan_of_each_marked_step(live):
    """One planner (`Law 7`): what the Doc says each marked step would do is
    what the workflow dry run plans for it — asked here AFTER, once, to show
    it (and it, being asked for, is recorded)."""
    import httpx

    live.script(_answer())
    async with httpx.AsyncClient(base_url=live.server.base, headers={"x-test-user": "alice"},
                                 timeout=60) as client:
        made = (await client.post("/api/workflows", json={"describe": "post new issues to #dev"})).json()
        doc = made["workflow"]
        assert sorted(doc["plans"]) == sorted(IDS) and doc["plans_declined"] is None
        assert (await client.get(f"/api/tasks/{doc['task_id']}/runs")).json()["runs"] == []
        dry = (await client.post(f"/api/tasks/{doc['task_id']}/run?dry=true")).json()
        by_node = {n["node_id"]: [s["detail"] for s in n["steps"]] for n in dry["nodes"]}
        for node_id in IDS:
            assert doc["plans"][node_id] == by_node[node_id], node_id
        runs = (await client.get(f"/api/tasks/{doc['task_id']}/runs")).json()["runs"]
        assert [r["status"] for r in runs] == ["skipped"], "a dry run a person asks for is recorded"
        # Checking one step: the Doc drops that step's plan and keeps the rest.
        checked = (await client.put(f"/api/workflows/{doc['id']}", json={"checked": [IDS[0]]})).json()
        assert sorted(checked["workflow"]["plans"]) == sorted(IDS[1:])
