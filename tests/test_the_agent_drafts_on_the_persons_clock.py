# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1873` — a workflow the assistant drafts runs on the person's clock, and an
edit the assistant makes to a zoned start keeps its first fire and its later
fires on that clock.

**Measured on `5e4c8ec`** (the audit's two probes, reproduced here): with the
chat turn's zone set to `Australia/Sydney` (`user_time.set_user_tz_name`, which
the chat route sets for every turn), `manage_tasks draft_workflow` asked the
drafter with "It is now … in UTC" and stored the start as 08:00 with no
`tz_name` — 08:00 UTC, 19:00 in Sydney — while the Workbench's own *Describe
it* sends the browser's zone (`B1867`). The arm read `args.get("tz_name")`, a
parameter `manage_tasks` does not have, and never the turn's zone. And an edit
of a zoned start's time (the schema says `scheduled_time` is UTC) stored the
UTC figure in the zone's column and computed the first fire with no zone, so a
Berlin start "moved to 06:00 UTC" fired first at 06:00Z and then every day at
05:00Z, and the Workbench showed 06:00 as Berlin time.

Now the draft takes the turn's zone (`workflow_store.person_zone`, the one
check `B1867` uses); an edit, create or resume of a task that resolves to a
zone (`_resolve_task_timezone`: its own, else its crew member's) reads the
model's UTC time into that zone before it is stored and computes the next fire
in it; and `list` names the zone beside a zoned time.

Real (`Law 20`): `do_manage_tasks` over a real SQLite file, the drafter, the
store; the model is `workflow_assist._complete`, scripted.
"""

import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from core.database import ScheduledTask
from src.task_scheduler import compute_next_run
from src.user_time import clear_user_time_context, set_user_tz_name
from tests.helpers.assist_harness import build_world, rows, script_model, stored

pytestmark = pytest.mark.asyncio

DAILY_AT_8 = {
    "name": "Morning brief",
    "trigger": {"type": "schedule", "schedule": "daily", "time": "08:00"},
    "steps": [{"id": "brief", "kind": "action", "label": "Daily brief",
               "config": {"action": "daily_brief"}}],
    "arrows": [], "missing": [],
}


@pytest.fixture()
def world(monkeypatch, tmp_path):
    clear_user_time_context()
    yield build_world(monkeypatch, tmp_path, name="clock.db")
    clear_user_time_context()


async def _ask(args, owner="alice"):
    from src.tools.system import do_manage_tasks
    return await do_manage_tasks(json.dumps(args), owner=owner)


def _local(utc_hhmm: str, zone: str) -> str:
    """What a UTC wall-clock time today is in `zone`, as the fix reads it."""
    h, m = (int(x) for x in utc_hhmm.split(":"))
    now = datetime.now(timezone.utc)
    at = now.replace(hour=h, minute=m, second=0, microsecond=0)
    return at.astimezone(ZoneInfo(zone)).strftime("%H:%M")


async def test_a_draft_in_chat_takes_the_turns_time_zone(world, monkeypatch):
    model = script_model(monkeypatch, DAILY_AT_8)
    set_user_tz_name("Australia/Sydney")
    said = await _ask({"action": "draft_workflow",
                       "description": "Every weekday at 8:00, give me my daily brief."})
    assert said["exit_code"] == 0, said
    _wf, _graph, trigger = stored(world.factory, said["workflow_id"])
    assert trigger.tz_name == "Australia/Sydney"
    assert trigger.scheduled_time == "08:00"
    first = next(m["content"] for m in model.calls[0]["messages"] if m["role"] == "user")
    assert first.startswith("It is now ") and " in Australia/Sydney." in first.splitlines()[0]


async def test_a_zone_the_machine_does_not_know_leaves_the_draft_on_the_servers_clock(
        world, monkeypatch):
    script_model(monkeypatch, DAILY_AT_8)
    set_user_tz_name("Mars/Olympus_Mons")
    said = await _ask({"action": "draft_workflow", "description": "Every day at 8:00, brief me."})
    assert said["exit_code"] == 0, said
    assert stored(world.factory, said["workflow_id"])[2].tz_name is None


async def test_an_edit_to_a_zoned_start_keeps_every_fire_on_its_clock(world, monkeypatch):
    script_model(monkeypatch, DAILY_AT_8)
    set_user_tz_name("Europe/Berlin")
    drafted = await _ask({"action": "draft_workflow", "description": "Every day at 8:00, brief me."})
    trigger_id = drafted["task_id"]
    # The schema says scheduled_time is UTC: "move it to 07:00" in Berlin is 06:00 UTC in winter.
    edited = await _ask({"action": "edit", "task_id": trigger_id, "scheduled_time": "06:00"})
    assert edited["exit_code"] == 0, edited
    [task] = rows(world.factory, ScheduledTask, id=trigger_id)
    assert task.tz_name == "Europe/Berlin"
    assert task.scheduled_time == _local("06:00", "Europe/Berlin")
    # The first fire is the fire every later one is: the same clock.
    assert task.next_run == compute_next_run("daily", task.scheduled_time, None,
                                             tz_name="Europe/Berlin")


async def test_a_plain_task_with_a_zone_is_edited_and_resumed_on_its_clock(world):
    db = world.factory()
    db.add(ScheduledTask(id="t-z", owner="alice", name="Water the plants", task_type="llm",
                         prompt="Remind me.", trigger_type="schedule", schedule="weekly",
                         scheduled_time="17:00", scheduled_day=4, tz_name="Asia/Tokyo",
                         status="paused"))
    db.commit()
    db.close()
    # 23:30 UTC on a Monday is 08:30 on the Tuesday in Tokyo.
    edited = await _ask({"action": "edit", "task_id": "t-z", "scheduled_time": "23:30",
                         "scheduled_day": 0})
    assert edited["exit_code"] == 0, edited
    [task] = rows(world.factory, ScheduledTask, id="t-z")
    assert (task.scheduled_time, task.scheduled_day) == ("08:30", 1)
    resumed = await _ask({"action": "resume", "task_id": "t-z"})
    assert resumed["exit_code"] == 0, resumed
    [task] = rows(world.factory, ScheduledTask, id="t-z")
    assert task.next_run == compute_next_run("weekly", "08:30", 1, tz_name="Asia/Tokyo")
    listed = await _ask({"action": "list"})
    assert "08:30 Asia/Tokyo" in listed["response"], listed["response"]


async def test_a_task_with_no_zone_is_edited_exactly_as_before(world):
    db = world.factory()
    db.add(ScheduledTask(id="t-utc", owner="alice", name="Backup", task_type="llm",
                         prompt="Back up.", trigger_type="schedule", schedule="daily",
                         scheduled_time="02:00", status="active"))
    db.commit()
    db.close()
    set_user_tz_name("Europe/Berlin")      # the turn's zone is not the task's
    edited = await _ask({"action": "edit", "task_id": "t-utc", "scheduled_time": "03:15"})
    assert edited["exit_code"] == 0, edited
    [task] = rows(world.factory, ScheduledTask, id="t-utc")
    assert (task.scheduled_time, task.tz_name) == ("03:15", None)
    assert task.next_run == compute_next_run("daily", "03:15", None)
