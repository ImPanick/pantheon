# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1813`. The assistant's resume and edit dropped a task's cron expression,
its date and its time zone, and its create stored tasks that could not run.

`manage_tasks` worked out a task's next run from its frequency, time and day
alone. A cron task has no time of its own (the six email and calendar
built-ins that ship paused, and every hired agent's daily or weekly start), so
asked to turn one on the assistant answered "resumed" and left it with no next
run, and the scheduler never picked it up. Asked to move one's time, it wrote
the time and cleared the next run of a task that was running. A one-off task's
date was dropped the same way, and a task's own zone, or its crew member's
(`P8-32`), was read as UTC: a 09:00 New York task resumed from chat first ran
at 09:00 UTC the next day. A create of `once`, which the tool has no date for,
was stored with no next run and reported done. The Tasks window's own routes
pass all of it.

Now the tool asks the scheduler's one formula (`workflow_store._next_run_of`,
which the window's routes and the engine agree with), refuses in words when a
task would be left with no next run, and refuses to move a cron task's time,
which lives in its expression and is changed in the Tasks window. A create
stores the frequency its next run was worked out from. Upstream Odysseus
passed the expression in e5e23e64; its resume and edit cases are adapted
here, without its cron, weekday and day-of-month arguments to create.

Driven: the real tool against a real SQLite file, at a fixed hour.
"""

import json
import sys
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from tests.helpers.import_state import clear_fake_database_modules

clear_fake_database_modules()

import core.database as cdb  # noqa: E402
import src.task_scheduler as task_scheduler  # noqa: E402
from core.database import CrewMember, ScheduledTask  # noqa: E402
from src.tools.system import do_manage_tasks  # noqa: E402

NOW = datetime(2026, 11, 9, 10, 0)   # a Monday: 05:00 in New York, 21:00 in Sydney


@pytest.fixture()
def tasks(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "core.database", cdb)
    engine = create_engine(
        f"sqlite:///{tmp_path / 'tasks.db'}",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(cdb, "SessionLocal", factory)
    monkeypatch.setattr(task_scheduler, "_utcnow", lambda: NOW)
    with factory() as db:
        # Shaped like `summarize_emails`, one of the built-ins that ship paused.
        db.add(ScheduledTask(id="digest", owner="bob", name="Summarize emails", task_type="action",
                             action="summarize_emails", trigger_type="schedule", schedule="cron",
                             cron_expression="0 */2 * * *", status="paused"))
        # Shaped like a hired agent's weekday start, running.
        db.add(ScheduledTask(id="hire", owner="bob", name="Start the day", task_type="llm",
                             prompt="Plan my day", trigger_type="schedule", schedule="cron",
                             cron_expression="30 7 * * 1-5", status="active",
                             next_run=datetime(2026, 11, 10, 7, 30)))
        db.add(ScheduledTask(id="standup", owner="bob", name="Standup notes", task_type="llm",
                             prompt="Draft my standup", trigger_type="schedule", schedule="daily",
                             scheduled_time="09:00", tz_name="America/New_York", status="paused"))
        db.add(ScheduledTask(id="passport", owner="bob", name="Renew the passport", task_type="llm",
                             prompt="Remind me", trigger_type="schedule", schedule="once",
                             scheduled_time="09:00", scheduled_date=datetime(2026, 11, 1, 9, 0),
                             status="paused"))
        db.add(CrewMember(id="sydney", owner="bob", name="Ops in Sydney", timezone="Australia/Sydney"))
        db.commit()
    yield factory
    engine.dispose()


async def _ask(**args):
    return await do_manage_tasks(json.dumps(args), owner="bob")


def _row(factory, task_id):
    with factory() as db:
        task = db.get(ScheduledTask, task_id)
        return None if task is None else {
            column: getattr(task, column)
            for column in ("name", "status", "schedule", "scheduled_time", "scheduled_day",
                           "cron_expression", "next_run")}


@pytest.mark.asyncio
async def test_resuming_a_cron_task_gives_it_the_next_run_its_expression_says(tasks):
    answer = await _ask(action="resume", task_id="digest")

    assert answer["exit_code"] == 0, answer
    assert _row(tasks, "digest")["status"] == "active"
    assert _row(tasks, "digest")["next_run"] == datetime(2026, 11, 9, 12, 0)


@pytest.mark.asyncio
async def test_resuming_a_task_reads_its_time_in_its_own_zone(tasks):
    answer = await _ask(action="resume", task_id="standup")

    assert answer["exit_code"] == 0, answer
    assert _row(tasks, "standup")["next_run"] == datetime(2026, 11, 9, 14, 0)   # 09:00 in New York


@pytest.mark.asyncio
async def test_a_one_off_task_whose_date_has_passed_is_not_resumed(tasks):
    answer = await _ask(action="resume", task_id="passport")

    assert answer["exit_code"] == 1
    assert "no next run" in answer["error"]
    assert _row(tasks, "passport")["status"] == "paused"


@pytest.mark.asyncio
@pytest.mark.parametrize("move", [
    pytest.param({"scheduled_time": "07:00"}, id="time"),
    pytest.param({"scheduled_day": 2}, id="day"),
    pytest.param({"scheduled_time": "07:00", "name": "Morning plan"}, id="time-and-name"),
])
async def test_moving_a_cron_tasks_time_is_refused_and_changes_nothing(tasks, move):
    before = _row(tasks, "hire")

    answer = await _ask(action="edit", task_id="hire", **move)

    assert answer["exit_code"] == 1
    assert "30 7 * * 1-5" in answer["error"] and "Tasks window" in answer["error"]
    assert _row(tasks, "hire") == before, "the task keeps running when it did"


@pytest.mark.asyncio
async def test_renaming_a_cron_task_leaves_its_next_run_alone(tasks):
    answer = await _ask(action="edit", task_id="hire", name="Morning plan")

    assert answer["exit_code"] == 0, answer
    assert _row(tasks, "hire")["name"] == "Morning plan"
    assert _row(tasks, "hire")["next_run"] == datetime(2026, 11, 10, 7, 30)


@pytest.mark.asyncio
async def test_a_one_off_task_the_tool_has_no_date_for_is_not_created(tasks):
    answer = await _ask(action="create", name="Call the bank", prompt="Remind me to call the bank",
                        schedule="once", scheduled_time="09:00")

    assert answer["exit_code"] == 1
    assert "no next run" in answer["error"]
    with tasks() as db:
        assert db.query(ScheduledTask).filter(ScheduledTask.name == "Call the bank").count() == 0


@pytest.mark.asyncio
async def test_a_task_made_for_a_crew_member_first_runs_in_their_zone(tasks):
    answer = await _ask(action="create", name="Ops check", prompt="Check the queue",
                        schedule="daily", scheduled_time="09:00", crew_member_id="sydney")

    assert answer["exit_code"] == 0, answer
    assert _row(tasks, answer["task_id"])["next_run"] == datetime(2026, 11, 9, 22, 0)   # 09:00 in Sydney


@pytest.mark.asyncio
async def test_a_task_made_without_a_frequency_stores_the_daily_one_its_next_run_assumed(tasks):
    answer = await _ask(action="create", name="Brief me", prompt="Brief me", scheduled_time="08:00")

    assert answer["exit_code"] == 0, answer
    made = _row(tasks, answer["task_id"])
    assert (made["schedule"], made["next_run"]) == ("daily", datetime(2026, 11, 10, 8, 0))
