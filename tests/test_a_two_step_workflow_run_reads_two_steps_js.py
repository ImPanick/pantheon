# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1081` — a two-step workflow's run reads "2 steps" in Activity.

**Measured before this file** (`wf-ui`, on the scratch merge): *Morning inbox
brief*, two steps, read "Morning inbox brief · 3 steps" in Activity. The run's
step log holds a line per step (`kind: "node"`) and a "Continued to …" line
between them, and `step_count` was the log's length; a person who built two
steps reads three (`Law 10`).

Now a workflow's run carries `node_count` — the distinct steps its log has a
line for — beside `step_count` (the log's length, unchanged for every other
run), and the Activity chip and the run history's summary say it. Driven
(`Law 20`): a real two-step workflow run by the real scheduler on a real SQLite
file, served by the real routes, and the served run drawn by the real Activity
row and run history under node.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tests.helpers.walker_harness import (  # noqa: E402
    OWNER, app_for, arrow, client_for, make_db, node, recording_scheduler, seed_workflow,
    settle,
)
from test_the_palette_moves_to_the_server_js import _tasks, tasks_sandbox  # noqa: E402,F401


@pytest.fixture()
def served(monkeypatch, tmp_path):
    """A two-step workflow's run, and a plain task's, as the routes serve them."""
    import asyncio

    from core.database import ScheduledTask
    factory = make_db(monkeypatch, tmp_path / "steps.db")
    s = recording_scheduler()
    seed_workflow(factory, [node("n1", "Read my inbox"), node("n2", "Write the brief")],
                  [arrow("n1", "n2")], name="Morning inbox brief")
    db = factory()
    db.add(ScheduledTask(id="plain", owner=OWNER, name="Daily brief", task_type="llm",
                         prompt="Summarise.", trigger_type="webhook", status="active"))
    db.commit()
    db.close()

    async def go():
        await s._execute_task("wf")
        await s._execute_task("plain")
        await settle(s)
        async with client_for(app_for(factory, s, monkeypatch)) as client:
            head = {"x-test-user": OWNER}
            recent = (await client.get("/api/tasks/runs/recent", headers=head)).json()["runs"]
            history = (await client.get("/api/tasks/wf/runs", headers=head)).json()["runs"]
        return recent, history

    recent, history = asyncio.run(go())
    return {r["task_id"]: r for r in recent}, history


def test_the_wire_counts_the_steps_a_person_built(served):
    recent, history = served
    wf = recent["wf"]
    assert wf["status"] == "success", wf
    assert wf["node_count"] == 2, wf
    assert wf["step_count"] > 2, "the premise: the log holds more lines than steps"
    assert history[0]["node_count"] == 2
    # Every other run is what it was (`Law 1`).
    assert recent["plain"]["node_count"] is None


def test_the_activity_chip_and_the_history_read_two_steps(served, tasks_sandbox):
    recent, history = served
    out = _tasks(tasks_sandbox, """
        const entry = __t._runToActivityEntry(%s);
        const row = __t._renderActivityEntry(entry);
        const at = row.indexOf('task-log-steps');
        console.log(JSON.stringify({
          chip: row.slice(at, row.indexOf('</button>', at)),
          summary: __t._renderRunSteps(%s),
        }));
    """ % (json.dumps(recent["wf"]), json.dumps(history[0])))
    assert out["chip"].endswith(">2 steps"), out["chip"]
    assert "<summary>2 steps</summary>" in out["summary"], out["summary"]
