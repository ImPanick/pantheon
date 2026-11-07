# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1874` — the assistant never says a run started when it did not.

Every workflow the assistant drafts, and every one imported, is made switched
off with every step marked "check me". `manage_tasks run` answered "Task 'X'
triggered" whenever the scheduler took the run — and the run was then recorded
`skipped`, "Task no longer active (status=paused)", or ended by the marks
before its first step. **Measured on `5e4c8ec`** (the audit's probe, reproduced
here): draft, then run → `{"response": "Task 'Two sets' triggered"}`, and the
run `skipped`. The Workbench's own Run now says the truth ("… is switched off,
so it would not run") and, since `B1852`, tries a switched-off workflow as a
test run instead.

Now the assistant's `run` asks the same questions first, through the same
doors:

  * a workflow with steps nobody has checked is not started, and says so in
    the switch's own sentence (`unchecked_refusal`) — nothing is recorded;
  * a switched-off workflow whose steps are checked is TRIED, as the
    Workbench's Run now tries it: a test run (`run_task_now(test=True)`,
    `B1852`), once, and it stays off — and the reply says so;
  * a paused plain task is not started, and says why — nothing is recorded;
  * a workflow's run answers its `run_id` and `workflow_id` (`B1866`), so the
    run can be read back.

A plain task that is on runs exactly as before (`Law 1`: its reply is held
byte for byte by `test_the_agent_can_ask_what_a_task_would_do.py` and
`test_a_person_asking_for_a_run_is_not_kept_waiting.py`).

Real (`Law 20`): `do_manage_tasks` over the real scheduler and walker on a real
SQLite file; only an Action step's far end is a recorder.
"""

import json

import pytest

from core.database import ScheduledTask
from tests.helpers.walker_harness import (
    arrow, make_db, node, recording_scheduler, row, runs_of, seed_workflow, settle,
)

pytestmark = pytest.mark.asyncio

STEPS = ([node("s", "Make it", "set", fields=[{"name": "n", "value": 3}]),
          node("a", "Tidy", "action", action="tidy_sessions")],
         [arrow("start", "s"), arrow("s", "a")])


@pytest.fixture()
def world(monkeypatch, tmp_path):
    import src.event_bus as event_bus
    factory = make_db(monkeypatch, tmp_path / "said.db")
    s = recording_scheduler()
    monkeypatch.setattr(event_bus, "_task_scheduler", s)
    return factory, s


async def _run(task_id):
    from src.tools.system import do_manage_tasks
    return await do_manage_tasks(json.dumps({"action": "run", "task_id": task_id}), owner="alice")


def _marked(nodes):
    return [dict(n, unchecked={"origin": "drafted", "needs": []}) for n in nodes]


async def test_a_workflow_nobody_has_checked_is_not_started_and_says_why(world):
    factory, s = world
    seed_workflow(factory, _marked(STEPS[0]), STEPS[1], status="paused")
    said = await _run("wf")
    assert said["exit_code"] == 1, said
    assert "triggered" not in json.dumps(said)
    assert said["error"] == (
        "“Morning digest” was not started. The model drafted 2 steps nobody has checked yet: "
        "“Make it”, “Tidy”. Check them first. A person checks each step in the Workbench "
        "(Automations → “Morning digest”); dry_run says what it would do meanwhile.")
    assert said["workflow_id"] == "w-wf"
    await settle(s)
    assert runs_of(factory, "wf") == [], "nothing was recorded as a run"
    assert s.calls == []


async def test_a_switched_off_workflow_is_tried_once_and_stays_off(world):
    factory, s = world
    seed_workflow(factory, *STEPS, status="paused")
    said = await _run("wf")
    assert said["exit_code"] == 0, said
    assert said["response"] == (
        "“Morning digest” is switched off, so this is a test run: it runs once now and stays "
        "off. Switch it on in the Workbench to run it on its start.")
    assert said["workflow_id"] == "w-wf"
    await settle(s)
    [run] = runs_of(factory, "wf")
    assert run["id"] == said["run_id"]
    assert run["status"] == "success", run
    assert run["steps"][0]["detail"] == "Test run"
    assert [c["name"] for c in s.calls] == ["Morning digest · Tidy"]
    assert row(factory, "wf").status == "paused", "the switch is not touched"


async def test_a_switched_on_workflow_runs_and_answers_its_run(world):
    factory, s = world
    seed_workflow(factory, *STEPS)
    said = await _run("wf")
    assert said["exit_code"] == 0, said
    assert said["response"] == "“Morning digest” started."
    assert said["workflow_id"] == "w-wf"
    await settle(s)
    [run] = runs_of(factory, "wf")
    assert run["id"] == said["run_id"] and run["status"] == "success"
    assert run["steps"][0]["detail"] != "Test run"


async def test_a_paused_plain_task_is_not_started_and_says_why(world):
    factory, s = world
    db = factory()
    db.add(ScheduledTask(id="plain", owner="alice", name="Inbox digest", task_type="action",
                         action="tidy_sessions", trigger_type="schedule", schedule="daily",
                         scheduled_time="08:00", status="paused"))
    db.commit()
    db.close()
    said = await _run("plain")
    assert said == {"error": "Task 'Inbox digest' was not started: it is paused. Resume it to "
                             "run it, or dry_run it to see what it would do.",
                    "exit_code": 1}
    await settle(s)
    assert runs_of(factory, "plain") == [] and s.calls == []
