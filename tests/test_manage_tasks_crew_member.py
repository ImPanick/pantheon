"""`manage_tasks` must persist `crew_member_id`, and must scope it to the caller.

P6-10 exposed the field in the tool schema (`src/tool_schemas.py`) before the
executor knew about it, so the model accepted the argument, reported the task
assigned, and the value was silently dropped. That is the failure mode worth a
test: not a crash, but the model confidently telling a user their task runs as
Research Bot when it does not.

The owner scoping is a security property, not tidiness. The executor runs the
task with the crew member's `personality` (its system prompt), `model`,
`endpoint_url` and `enabled_tools` — so an unscoped id would let one user run a
task under another user's persona and read that prompt back out of the task's
own session.
"""
import asyncio
import json

import pytest

from core.database import SessionLocal, ScheduledTask, CrewMember
from src.tools.system import do_manage_tasks


def _run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


@pytest.fixture()
def crew():
    db = SessionLocal()
    mine = CrewMember(id="crew-test-mine", owner="alice-crewtest", name="Research Bot")
    theirs = CrewMember(id="crew-test-theirs", owner="bob-crewtest", name="Bob's Bot")
    db.add_all([mine, theirs])
    db.commit()
    yield db
    for obj in (mine, theirs):
        db.delete(obj)
    db.query(ScheduledTask).filter(
        ScheduledTask.owner == "alice-crewtest"
    ).delete(synchronize_session=False)
    db.commit()
    db.close()


def _create(crew_member_id, owner="alice-crewtest", name="crewtest"):
    return _run(do_manage_tasks(json.dumps({
        "action": "create", "name": name, "prompt": "do a thing",
        "trigger_type": "schedule", "schedule": "daily",
        "scheduled_time": "09:00", "crew_member_id": crew_member_id,
    }), owner=owner))


def test_create_persists_crew_member_id(crew):
    res = _create("crew-test-mine")
    task_id = res.get("task_id")
    assert task_id, res
    row = crew.query(ScheduledTask).filter(ScheduledTask.id == task_id).first()
    assert row is not None
    assert row.crew_member_id == "crew-test-mine"


def test_another_owners_crew_member_is_refused_not_dropped(crew):
    res = _create("crew-test-theirs")
    # Refused loudly. Silently ignoring it is the defect this test exists for:
    # the model would report the task assigned and it would not be.
    assert res.get("exit_code") == 1
    assert "not found" in (res.get("error") or "")
    assert not res.get("task_id")


def test_unknown_crew_member_is_refused(crew):
    res = _create("crew-does-not-exist")
    assert res.get("exit_code") == 1
    assert not res.get("task_id")


def test_edit_with_empty_string_unassigns(crew):
    task_id = _create("crew-test-mine").get("task_id")
    assert task_id
    _run(do_manage_tasks(json.dumps({
        "action": "edit", "task_id": task_id, "crew_member_id": "",
    }), owner="alice-crewtest"))
    crew.expire_all()
    row = crew.query(ScheduledTask).filter(ScheduledTask.id == task_id).first()
    assert row.crew_member_id is None


def test_edit_omitting_the_field_leaves_the_assignment_alone(crew):
    """`None` means "not mentioned"; only an explicit "" unassigns."""
    task_id = _create("crew-test-mine").get("task_id")
    assert task_id
    _run(do_manage_tasks(json.dumps({
        "action": "edit", "task_id": task_id, "name": "renamed",
    }), owner="alice-crewtest"))
    crew.expire_all()
    row = crew.query(ScheduledTask).filter(ScheduledTask.id == task_id).first()
    assert row.name == "renamed"
    assert row.crew_member_id == "crew-test-mine"


def test_the_tool_schema_and_the_executor_agree():
    """Law 13: the schema must not advertise a field the executor drops.

    Read as source text rather than importing `src.tool_schemas`, which pulls
    in the whole agent-tools facade. The defect this guards is textual anyway:
    a property in the schema literal with no reader in the executor.
    """
    import inspect
    import pathlib

    schema_src = pathlib.Path("src/tool_schemas.py").read_text(encoding="utf-8")
    assert '"crew_member_id"' in schema_src, "schema lost the field"

    import src.tools.system as system_mod
    executor_src = inspect.getsource(system_mod.do_manage_tasks)
    assert "crew_member_id" in executor_src, (
        "manage_tasks advertises crew_member_id but the executor never reads it"
    )
