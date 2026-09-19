# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P8-33` — a dry run that is actually dry.

"Run now" was a real run. There was no dry anything: measured on the tree
before this file, `grep -rn "dry" src/task_scheduler.py` returned one hit and it
was the word "dry" inside an assistant persona string.

**The design this file exists to hold.** The obvious dry run — thread
`dry_run=True` down to the action and let it honour the flag — is silently the
REAL run for every action that does not read the flag, and all eighteen take
`**kwargs`, which swallows it. So the dry run never calls an action at all:
`_execute_task_locked` returns before any executor, and `dry_run_plan` reads a
registry. `test_not_one_of_the_eighteen_actions_is_called` is that property
stated as a test, over all eighteen rather than a sample, because "eighteen of
eighteen" is the number the design is chosen for.

The other half is the plan being honest about what it cannot say. Two of the
eighteen replace text the person wrote with text a model wrote, and for those a
plan is not a preview of anything — it says so, in the plan, in the run.
"""

import asyncio
import json
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from tests.helpers.import_state import clear_fake_database_modules

clear_fake_database_modules()

import core.database as cdb  # noqa: E402
import src.builtin_actions as ba  # noqa: E402
from core.database import ScheduledTask, TaskRun  # noqa: E402
from src.task_scheduler import TaskScheduler  # noqa: E402


_REAL_DATABASE_ATTRS = {
    "Base": cdb.Base,
    "SessionLocal": cdb.SessionLocal,
    "ScheduledTask": ScheduledTask,
    "TaskRun": TaskRun,
}


@pytest.fixture()
def task_db(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "core.database", cdb)
    for attr, value in _REAL_DATABASE_ATTRS.items():
        monkeypatch.setattr(cdb, attr, value, raising=False)
    engine = create_engine(
        f"sqlite:///{tmp_path / 'dry.db'}",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(cdb, "SessionLocal", factory)
    return factory


def _seed(factory, *, action="tidy_sessions", task_type="action", prompt=None,
          then_task_id=None, else_task_id=None):
    db = factory()
    try:
        db.add(ScheduledTask(
            id="sub", owner=None, name="downstream", task_type="action",
            action="tidy_sessions", trigger_type="webhook", status="active"))
        db.add(ScheduledTask(
            id="t1", owner=None, name="A task", prompt=prompt,
            task_type=task_type, action=action, trigger_type="schedule",
            schedule="daily", scheduled_time="09:00", status="active",
            output_target="session", run_count=7))
        db.commit()
        task = db.query(ScheduledTask).filter(ScheduledTask.id == "t1").first()
        task.then_task_id = then_task_id
        task.else_task_id = else_task_id
        task.last_run = None
        task.next_run = None
        db.add(TaskRun(id="r1", task_id="t1", status="queued"))
        db.commit()
    finally:
        db.close()


def _scheduler(chained=None):
    s = TaskScheduler.__new__(TaskScheduler)
    s._task_handles = {}
    s._task_defer_counts = {}
    s._session_manager = None
    s._notify_run_outcome = MagicMock(return_value=True)
    s.add_notification = MagicMock()
    s._log_to_assistant = MagicMock()
    s._deliver_task_result = AsyncMock(return_value=None)

    async def _run_chained(task_id, *, handoff=None):
        (chained if chained is not None else []).append(task_id)

    s._run_chained = _run_chained
    return s


async def _settle():
    await asyncio.sleep(0)
    await asyncio.sleep(0)


def _run_row(factory, run_id="r1"):
    db = factory()
    try:
        row = db.query(TaskRun).filter(TaskRun.id == run_id).first()
        return {
            "status": row.status, "result": row.result, "error": row.error,
            "steps": json.loads(row.steps) if row.steps else [],
            "finished": row.finished_at,
        }
    finally:
        db.close()


def _task_row(factory, task_id="t1"):
    db = factory()
    try:
        row = db.query(ScheduledTask).filter(ScheduledTask.id == task_id).first()
        return {"last_run": row.last_run, "next_run": row.next_run,
                "run_count": row.run_count, "status": row.status}
    finally:
        db.close()


# ── the registry is complete, and stays complete ───────────────────────────

def test_every_dispatchable_action_declares_its_effects_and_its_dry_verdict():
    """`P8-22` reconciled two maps that had drifted two entries apart. This is
    the same guard for the two fields this row adds: a nineteenth action cannot
    ship without saying what it does and what a dry run can tell you."""
    assert set(ba.BUILTIN_ACTIONS) == set(ba.BUILTIN_ACTION_META)
    for name, meta in ba.BUILTIN_ACTION_META.items():
        assert "effects" in meta, f"{name} declares no effects"
        assert meta["effects"], f"{name} declares an empty effect list"
        assert set(meta["effects"]) <= set(ba.ACTION_EFFECTS), name
        assert meta.get("dry") in ba.DRY_VERDICTS, f"{name} dry={meta.get('dry')!r}"
        # Every effect has a sentence, or the plan drops it silently.
        for effect in meta["effects"]:
            assert effect in ba.EFFECT_SENTENCES, f"{name}: {effect}"


def test_the_two_a_dry_run_cannot_cover_are_named_and_there_are_two():
    """The deliverable this row names. Both replace text a person wrote with
    text a model wrote — `consolidate_memory` at `mem["text"] = cleaned["text"]`
    and `audit_skills` through `_apply_skill_md`. A third joining them is a
    thing somebody has to agree to in a diff, which is what this asserts."""
    assert ba.DRY_UNCOVERABLE_ACTIONS == {"consolidate_memory", "audit_skills"}
    for name in ba.DRY_UNCOVERABLE_ACTIONS:
        assert ba.EFFECT_REWRITES in ba.BUILTIN_ACTION_META[name]["effects"]
    # And nothing else claims to rewrite authored text while promising a plan.
    for name, meta in ba.BUILTIN_ACTION_META.items():
        if ba.EFFECT_REWRITES in meta["effects"]:
            assert meta["dry"] == ba.DRY_CANNOT, name


def test_the_three_that_run_your_own_command_show_it_verbatim():
    plan = "\n".join(ba.dry_run_plan(
        task_type="action", action="ssh_command",
        prompt="rm -rf /srv/data && systemctl restart prod", owner="jo"))
    assert "rm -rf /srv/data && systemctl restart prod" in plan
    assert "cannot tell you what that does" in plan
    for name in ("ssh_command", "run_script", "run_local"):
        assert ba.BUILTIN_ACTION_META[name]["dry"] == ba.DRY_SHOWS_INPUT


def test_the_plan_for_an_uncoverable_action_says_so_rather_than_guessing():
    plan = "\n".join(ba.dry_run_plan(task_type="action", action="audit_skills"))
    assert "cannot tell you what this would change" in plan
    assert "REPLACES text you wrote" in plan


# ── the guarantee ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("action", sorted(ba.BUILTIN_ACTIONS))
async def test_not_one_of_the_eighteen_actions_is_called(task_db, monkeypatch, action):
    """The row, over the whole registry.

    Each action is replaced with a recorder that would notice being called.
    `**kwargs` is what makes the naive design fail — so the stub takes it, the
    way the real ones do, and a dry run that passed a flag down instead of
    refusing to dispatch would land here and be recorded.
    """
    _seed(task_db, action=action, prompt="some prompt")
    called = []

    async def recorder(**kwargs):
        called.append(kwargs)
        return "I RAN", True

    monkeypatch.setitem(ba.BUILTIN_ACTIONS, action, recorder)
    await _scheduler()._execute_task_locked(
        "t1", "r1", gate_foreground=False, release_executing=False, dry=True)

    assert called == [], f"{action} executed during a dry run"
    row = _run_row(task_db)
    assert row["status"] == "skipped"
    assert "I RAN" not in (row["result"] or "")
    assert row["result"].startswith("Dry run — nothing ran, nothing changed.")


@pytest.mark.asyncio
async def test_a_dry_run_does_not_move_the_schedule(task_db, monkeypatch):
    """A dry run that advanced `next_run` would be a side effect on the one
    path whose whole promise is that it has none — and a task quietly skipping
    its slot is exactly how `B675` describes a run leaving no trace."""
    _seed(task_db)
    before = _task_row(task_db)
    async def recorder(**kwargs):
        return "ran", True
    monkeypatch.setitem(ba.BUILTIN_ACTIONS, "tidy_sessions", recorder)

    await _scheduler()._execute_task_locked(
        "t1", "r1", gate_foreground=False, release_executing=False, dry=True)

    after = _task_row(task_db)
    assert after == before, f"a dry run changed the task row: {before} -> {after}"


@pytest.mark.asyncio
async def test_a_dry_run_delivers_nothing_notifies_nobody_and_chains_nothing(
        task_db, monkeypatch):
    _seed(task_db, then_task_id="sub", else_task_id="sub")
    async def recorder(**kwargs):
        return "ran", True
    monkeypatch.setitem(ba.BUILTIN_ACTIONS, "tidy_sessions", recorder)
    chained = []
    sched = _scheduler(chained)

    await sched._execute_task_locked(
        "t1", "r1", gate_foreground=False, release_executing=False, dry=True)
    await _settle()

    assert chained == []
    sched._deliver_task_result.assert_not_called()
    sched._notify_run_outcome.assert_not_called()
    sched._log_to_assistant.assert_not_called()


@pytest.mark.asyncio
async def test_the_plan_reaches_the_step_log_a_person_opens(task_db, monkeypatch):
    """`Law 15`. The plan is worth nothing where nobody looks; the run's own
    step log is the surface Activity already draws."""
    _seed(task_db, action="ssh_command", prompt="shutdown -h now")
    async def recorder(**kwargs):
        return "ran", True
    monkeypatch.setitem(ba.BUILTIN_ACTIONS, "ssh_command", recorder)

    await _scheduler()._execute_task_locked(
        "t1", "r1", gate_foreground=False, release_executing=False, dry=True)

    steps = _run_row(task_db)["steps"]
    assert steps, "the dry run recorded no steps"
    assert all(s["kind"] == "dry-run" for s in steps), [s["kind"] for s in steps]
    joined = "\n".join(s["detail"] for s in steps)
    assert "shutdown -h now" in joined
    assert "Would run: ssh_command" in joined


@pytest.mark.asyncio
async def test_a_real_run_is_byte_for_byte_what_it_was(task_db, monkeypatch):
    """`Law 1`. Every existing caller passes no `dry` at all, and this is the
    path every scheduled run in the product takes."""
    _seed(task_db)
    called = []

    async def recorder(**kwargs):
        called.append(kwargs)
        return "did the real thing", True

    monkeypatch.setitem(ba.BUILTIN_ACTIONS, "tidy_sessions", recorder)
    await _scheduler()._execute_task_locked(
        "t1", "r1", gate_foreground=False, release_executing=False)

    assert len(called) == 1
    row = _run_row(task_db)
    assert row["status"] == "success"
    assert row["result"] == "did the real thing"


@pytest.mark.asyncio
async def test_an_llm_task_plans_without_calling_a_model(task_db, monkeypatch):
    _seed(task_db, task_type="llm", action=None, prompt="Summarise my inbox")
    sched = _scheduler()
    ran = []

    async def _never(*a, **k):
        ran.append(1)
        return "model output"

    sched._execute_llm_task = _never
    await sched._execute_task_locked(
        "t1", "r1", gate_foreground=False, release_executing=False, dry=True)

    assert ran == []
    assert "Would send this task's prompt to a model" in _run_row(task_db)["result"]


@pytest.mark.asyncio
async def test_the_flag_survives_the_whole_path_from_the_button(task_db, monkeypatch):
    """`Law 13`, as the mutation that found this gap.

    The tests above drive `_execute_task_locked`, so a `dry` that is accepted
    there and dropped by `_execute_task` on the way in passes every one of them
    while the button runs the task for real. This drives the outer function —
    which also proves the two things only it decides: a dry run takes neither
    the model slot nor the wait for Pantheon to be idle.
    """
    _seed(task_db, action="ssh_command", prompt="reboot")
    called = []

    async def recorder(**kwargs):
        called.append(kwargs)
        return "I RAN", True

    monkeypatch.setitem(ba.BUILTIN_ACTIONS, "ssh_command", recorder)
    sched = _scheduler()
    sched._task_needs_model_slot = MagicMock(return_value=True)
    sched._run_semaphore = None  # touching it at all would raise

    quiet = []

    async def _never_quiet(*a, **k):
        quiet.append(1)

    monkeypatch.setattr("src.interactive_gate.wait_for_interactive_quiet",
                        _never_quiet, raising=False)

    await sched._execute_task("t1", release_executing=False, dry=True)

    assert called == [], "the action ran through _execute_task's dry path"
    assert quiet == [], "a dry run waited for Pantheon to go idle"
    db = task_db()
    try:
        runs = db.query(TaskRun).filter(TaskRun.task_id == "t1").all()
        planned = [r for r in runs if (r.result or "").startswith("Dry run")]
        assert planned, [(r.id, r.status, r.result) for r in runs]
        assert planned[0].status == "skipped"
    finally:
        db.close()


@pytest.mark.asyncio
async def test_the_route_passes_dry_through_and_says_which_it_did(
        task_db, monkeypatch):
    """A query parameter the handler accepts and then does not forward is the
    same defect as no parameter at all, and it looks like a feature."""
    import routes.task.task_routes as task_routes
    from types import SimpleNamespace

    # `task_routes` binds `SessionLocal` at import, so the fixture's patch on
    # `core.database` does not reach it. Same line the other route tests carry.
    monkeypatch.setattr(task_routes, "SessionLocal", task_db)
    _seed(task_db)
    seen = {}

    async def _run_task_now(task_id, *, force=False, trigger=None, dry=False):
        seen.update(task_id=task_id, force=force, dry=dry)
        return True

    scheduler = SimpleNamespace(run_task_now=_run_task_now)
    router = task_routes.setup_task_routes(scheduler)
    endpoint = next(
        r.endpoint for r in router.routes
        if getattr(r, "path", None) == "/api/tasks/{task_id}/run"
        and "POST" in getattr(r, "methods", set()))
    request = SimpleNamespace(state=SimpleNamespace(current_user=None))

    out = await endpoint(request, "t1", dry=True)
    assert seen["dry"] is True, seen
    assert out["dry"] is True
    assert "nothing executed" in out["message"]

    seen.clear()
    out = await endpoint(request, "t1")
    assert seen["dry"] is False, seen
    assert out["dry"] is False


def test_the_plan_builder_cannot_reach_an_executor():
    """`Law 20`, read the other way round: the property is about what the
    function calls, so it is checked on the call graph rather than by grepping
    for a word. `dry_run_plan` may not call anything that could run a task."""
    import ast
    from pathlib import Path

    tree = ast.parse(Path(ba.__file__).read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.name == "dry_run_plan")
    names = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            target = node.func
            if isinstance(target, ast.Name):
                names.add(target.id)
            elif isinstance(target, ast.Attribute):
                names.add(target.attr)
    # Anything that dispatches, awaits or reaches the registry of callables.
    assert not (names & {"action_fn", "await", "coerce_node_result"}), names
    assert "BUILTIN_ACTIONS" not in {
        n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
    assert not any(isinstance(n, ast.Await) for n in ast.walk(fn))
