# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P22-04`, server half (folds `B803`) — the agent can dry-run a task.

`P8-33` built a dry run that is actually dry: `POST /api/tasks/{id}/run?dry=true`
→ `run_task_now(dry=True)` → `_execute_task_locked` returns before any executor
and `_record_dry_run` writes the plan on a `skipped` run. The agent could run a
task and could not ask what one would do, because `manage_tasks` had no way in
(`B803`, measured again 2026-10-01: the schema's action enum was `list, create,
edit, delete, pause, resume, run`, and `do_manage_tasks` answered anything else
with "Unknown action").

What this file holds, driven against the real scheduler and a real SQLite file
(`Law 20`):

  * `manage_tasks` `dry_run` goes through the SAME path the route does — the
    reply is the plan the run row holds, and the route's reply carries that row
    too (`Law 14`: one dry run, two doors);
  * it runs nothing: every one of the eighteen built-in actions, the model
    executor, the research pipeline, delivery, notification and the chain are
    recorders, and every recorder is empty afterwards;
  * the plan exists when the call returns — a spawned dry run answered before
    the plan was written, which is why the model could not read it back.
"""

import asyncio
import json
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from tests.helpers.import_state import clear_fake_database_modules

clear_fake_database_modules()

import core.database as cdb  # noqa: E402
import src.builtin_actions as ba  # noqa: E402
import src.event_bus as event_bus  # noqa: E402
import src.task_action_policy as policy  # noqa: E402
import src.task_scheduler as ts  # noqa: E402
from core.database import ScheduledTask, TaskRun  # noqa: E402
from src.task_scheduler import TaskScheduler  # noqa: E402
from src.tools.system import do_manage_tasks  # noqa: E402
from tests.helpers.signed_in import ADMIN, signed_in  # noqa: E402

_REAL_DATABASE_ATTRS = {
    "Base": cdb.Base,
    "SessionLocal": cdb.SessionLocal,
    "ScheduledTask": ScheduledTask,
    "TaskRun": TaskRun,
}

HEADLINE = "Dry run — nothing ran."  # P23-05 (COPY-U-27)


@pytest.fixture()
def task_db(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "core.database", cdb)
    for attr, value in _REAL_DATABASE_ATTRS.items():
        monkeypatch.setattr(cdb, attr, value, raising=False)
    engine = create_engine(
        f"sqlite:///{tmp_path / 'dry-tool.db'}",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(cdb, "SessionLocal", factory)
    # The person asking is the install's admin, signed in; alice and bob are
    # not admins. (The asker was nobody until `D-2026-10-07-02` §2, answered as
    # an admin by an install with no account.)
    signed_in(monkeypatch, tmp_path / "auth", members=("alice", "bob"))
    return factory


@pytest.fixture()
def calls(monkeypatch):
    """Everything that could DO something, replaced by something that would
    notice being called. The eighteen take `**kwargs`, as the real ones do —
    the shape that would swallow a dry flag passed down instead of refused."""
    seen = []
    for name in list(ba.BUILTIN_ACTIONS):
        async def recorder(_name=name, **kwargs):
            seen.append(("action", _name))
            return "I RAN", True
        monkeypatch.setitem(ba.BUILTIN_ACTIONS, name, recorder)
    return seen


@pytest.fixture()
def scheduler(monkeypatch, calls):
    """The real scheduler — real `run_task_now`, `_execute_task`,
    `_execute_task_locked`, `_record_dry_run` — registered where the tool finds
    it, with every way out of a run recorded instead of taken."""
    s = TaskScheduler(None)

    def recorded(label):
        async def _rec(*a, **k):
            calls.append((label, a[:1]))
            return "I RAN"
        return _rec

    s._execute_llm_task = recorded("llm")
    s._execute_research_task = recorded("research")
    s._deliver_task_result = recorded("deliver")
    s._run_chained = recorded("chain")
    s._notify_run_outcome = MagicMock(side_effect=lambda *a, **k: calls.append(("notify", a[:1])))
    s.add_notification = MagicMock(side_effect=lambda *a, **k: calls.append(("notification", a[:1])))
    s._log_to_assistant = MagicMock(side_effect=lambda *a, **k: calls.append(("chat", a[:1])))
    monkeypatch.setattr(event_bus, "_task_scheduler", s)
    return s


def _seed(factory, *, task_id="t1", owner=ADMIN, task_type="action",
          action="summarize_emails", prompt="some prompt", status="active"):
    db = factory()
    try:
        db.add(ScheduledTask(
            id="sub", owner=owner, name="downstream", task_type="action",
            action="tidy_sessions", trigger_type="webhook", status="active"))
        db.add(ScheduledTask(
            id=task_id, owner=owner, name="Inbox digest", prompt=prompt,
            task_type=task_type, action=action, trigger_type="schedule",
            schedule="daily", scheduled_time="09:00", status=status,
            output_target="session", run_count=7))
        db.commit()
        row = db.query(ScheduledTask).filter(ScheduledTask.id == task_id).first()
        row.then_task_id = "sub"
        row.else_task_id = "sub"
        db.commit()
    finally:
        db.close()


def _task(factory, task_id="t1"):
    db = factory()
    try:
        t = db.query(ScheduledTask).filter(ScheduledTask.id == task_id).first()
        return {"last_run": t.last_run, "next_run": t.next_run,
                "run_count": t.run_count, "status": t.status}
    finally:
        db.close()


def _runs(factory, task_id="t1"):
    db = factory()
    try:
        return [{"id": r.id, "status": r.status, "result": r.result,
                 "steps": json.loads(r.steps) if r.steps else []}
                for r in db.query(TaskRun).filter(TaskRun.task_id == task_id).all()]
    finally:
        db.close()


def _ask(args, owner=ADMIN):
    return do_manage_tasks(json.dumps(args), owner=owner)


# ── the tool ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("action", sorted(ba.BUILTIN_ACTION_META))
async def test_dry_run_runs_nothing_and_answers_with_the_plan(
        task_db, scheduler, calls, action):
    """`B803`'s `Verify:`, over every built-in action: the person asks what the
    task would do and is told, and nothing ran."""
    _seed(task_db, action=action)
    before = _task(task_db)

    out = await _ask({"action": "dry_run", "task_id": "t1"})
    await asyncio.sleep(0)

    assert out.get("exit_code") == 0, out
    assert calls == [], f"a dry run reached {calls}"
    assert out["response"].startswith(f"Task 'Inbox digest': {HEADLINE}"), out
    assert f"Would run: {action}" in out["response"]
    # Nothing about the task moved: no schedule, no count, no pause.
    assert _task(task_db) == before
    # The plan is the run's — one dry run, read back from where it wrote.
    (run,) = _runs(task_db)
    assert run["id"] == out["run_id"]
    assert run["status"] == "skipped"
    assert out["response"] == f"Task 'Inbox digest': {run['result']}"


@pytest.mark.asyncio
async def test_a_prompt_task_is_planned_without_calling_a_model(task_db, scheduler, calls):
    _seed(task_db, task_type="llm", action=None, prompt="Summarise my inbox")

    out = await _ask({"action": "dry_run", "task_id": "t1"})

    assert out.get("exit_code") == 0, out
    assert calls == []
    assert "Would send this task's prompt to a model" in out["response"]


@pytest.mark.asyncio
async def test_your_own_command_is_shown_exactly_as_it_would_be_sent(
        task_db, scheduler, calls):
    """The dry run worth most: the argv before it reaches a production box."""
    _seed(task_db, action="ssh_command", prompt="systemctl restart billing")

    out = await _ask({"action": "dry_run", "task_id": "t1"})

    assert calls == []
    assert "systemctl restart billing" in out["response"]
    assert "cannot tell you what that does" in out["response"]


@pytest.mark.asyncio
async def test_a_task_already_running_is_said_and_nothing_is_planned(
        task_db, scheduler, calls):
    _seed(task_db)
    scheduler._executing.add("t1")

    out = await _ask({"action": "dry_run", "task_id": "t1"})

    assert out == {"error": "Task is already running", "exit_code": 1}
    assert _runs(task_db) == [] and calls == []


@pytest.mark.asyncio
async def test_someone_elses_task_and_a_missing_one_are_refused(task_db, scheduler, calls):
    _seed(task_db, owner="bob")

    assert await _ask({"action": "dry_run", "task_id": "t1"}, owner="alice") == {
        "error": "Access denied", "exit_code": 1}
    assert (await _ask({"action": "dry_run", "task_id": "nope"}))["error"] == (
        "Task nope not found")
    assert (await _ask({"action": "dry_run"}))["error"] == "task_id is required for dry_run"
    assert _runs(task_db) == [] and calls == []


@pytest.mark.asyncio
async def test_an_admin_only_task_is_refused_before_the_engine_could_pause_it(
        task_db, scheduler, calls, monkeypatch):
    """The route answers a non-admin's dry run of an admin-only task with a 403
    before the scheduler is reached. Left to the engine, the same refusal
    PAUSES the task (`record_admin_refusal`) — a dry run that changed the task.
    The tool asks the same policy the route asks, first."""
    for module in (policy, ts):
        monkeypatch.setattr(module, "owner_has_admin_task_privileges",
                            lambda owner: False)
    _seed(task_db, owner="bob", action="ssh_command", prompt="reboot")
    before = _task(task_db)

    out = await _ask({"action": "dry_run", "task_id": "t1"}, owner="bob")

    assert out == {"error": policy.admin_refusal_message("ssh_command"), "exit_code": 1}
    assert _task(task_db) == before, "the dry run paused the task"
    assert _runs(task_db) == [] and calls == []


@pytest.mark.asyncio
async def test_a_run_the_engine_declined_to_plan_is_not_passed_off_as_a_plan(
        task_db, scheduler, calls, monkeypatch):
    """A declined run is recorded `skipped` with its reason, and it is not a
    plan. Driven while writing this file, the first version of the tool replied
    *"Task 'Inbox digest': Queued — waiting for a free slot…"* with exit 0 — an
    answer, and a false one.

    The decline here was a paused task until `B1036`, which made a paused task
    plan. What is left is a task the engine will not run for this owner, met
    by the privilege going between the tool's own check and the engine's — and
    the engine's answer to it no longer pauses the task (`B1036`)."""
    monkeypatch.setattr(policy, "owner_has_admin_task_privileges", lambda owner: True)
    monkeypatch.setattr(ts, "owner_has_admin_task_privileges", lambda owner: False)
    _seed(task_db, action="ssh_command", prompt="reboot")
    before = _task(task_db)

    out = await _ask({"action": "dry_run", "task_id": "t1"})

    assert out["exit_code"] == 1, out
    assert out["error"] == (
        "'Inbox digest' was not planned: Action 'ssh_command' requires admin privileges")
    assert "Queued" not in json.dumps(out)
    assert _task(task_db) == before, "the dry run changed the task"
    assert not [c for c in calls if c[0] in ("action", "llm", "research", "deliver", "chain")]


@pytest.mark.asyncio
async def test_run_still_runs(task_db, scheduler, calls):
    """`Law 1`. The action beside it is byte-for-byte what it was."""
    _seed(task_db, action="tidy_sessions")

    out = await _ask({"action": "run", "task_id": "t1"})
    for _ in range(20):
        await asyncio.sleep(0)
        if ("action", "tidy_sessions") in calls:
            break

    assert out == {"response": "Task 'Inbox digest' triggered", "exit_code": 0}
    assert ("action", "tidy_sessions") in calls


@pytest.mark.asyncio
async def test_every_action_the_schema_offers_is_one_the_tool_answers(task_db):
    """`Law 13`, both halves at once: the schema offers `dry_run` and the
    handler serves it — and nothing else offered falls through to "Unknown"."""
    from src.tool_schemas import FUNCTION_TOOL_SCHEMAS
    schema = next(s["function"] for s in FUNCTION_TOOL_SCHEMAS
                  if s["function"]["name"] == "manage_tasks")
    offered = schema["parameters"]["properties"]["action"]["enum"]
    assert "dry_run" in offered
    assert "dry_run" in schema["parameters"]["properties"]["task_id"]["description"]
    for action in offered:
        out = await _ask({"action": action})
        assert out.get("error") != f"Unknown action: {action}", action


# ── one dry run, two doors ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_plan_is_written_before_the_call_returns(task_db, scheduler, calls):
    """The reason the agent could not read its plan back: a spawned dry run
    answered `True` before the plan existed. Awaited, it answers with the run
    that holds it — and a real run still answers `True`."""
    _seed(task_db)

    started = await scheduler.run_task_now("t1", dry=True)

    assert isinstance(started, str), started
    (run,) = _runs(task_db)
    assert run["id"] == started and run["status"] == "skipped"
    assert run["result"].startswith(HEADLINE)
    assert "t1" not in scheduler._executing, "the dry run kept its claim"
    assert calls == []


def test_the_route_answers_a_dry_run_with_the_run_that_holds_the_plan(
        task_db, scheduler, calls, monkeypatch):
    """The browser's door (`?dry=true`), through `TestClient`, against the
    same scheduler: the reply carries the run in the shape the history route
    serves, and its plan is the one the agent is told."""
    import routes.task.task_routes as task_routes
    monkeypatch.setattr(task_routes, "SessionLocal", task_db)
    from tests.helpers.signed_in import as_person
    app = as_person(FastAPI(), ADMIN)   # the admin's browser, as `AuthMiddleware` leaves it
    app.include_router(task_routes.setup_task_routes(scheduler))
    _seed(task_db, action="ssh_command", prompt="shutdown -h now")

    r = TestClient(app).post("/api/tasks/t1/run?dry=true")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dry"] is True and body["run_id"] == body["run"]["id"]
    assert body["run"]["status"] == "skipped"
    assert {s["kind"] for s in body["run"]["steps"]} == {"dry-run"}
    assert "shutdown -h now" in body["run"]["result"]
    assert calls == []

    history = TestClient(app).get("/api/tasks/t1/runs").json()["runs"]
    assert history[0] == body["run"]
