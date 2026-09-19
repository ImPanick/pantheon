# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P8-32` — per-task timezone, retries and a per-task timeout.

Three things a task could not say about its own execution, and one premise in
the row that was true and understated.

**The premise, re-measured 2026-09-19.** *"Timezone today comes only via a crew
member"* is true, and the crew member's zone reaches **one** of the six places
that compute a next run — the executor. The other five (create, edit, resume,
bulk-resume, revert) computed it in UTC, so a crew-member-linked daily task was
created at the wrong time and stayed there until its first run corrected it.
Two of the six disagreed in the other direction too: `_task_period_seconds`
read `getattr(task, "tz_name", None)` against a column that did not exist.

**What is reused rather than invented.** `P15-08`'s ladder
(`failure_backoff_seconds`, jittered, capped) is the only backoff; `P8-24`'s
`retry_after` is the unit; `consecutive_failures` is the attempt count, read
from run history rather than stored. The one thing deliberately NOT reused is
`deferred`: `TaskDeferred` deletes the run row (`B675`), and a failure with
retries left is the case where the row is the entire point.

**And the half of `P15-08` that was never wired.** The backoff lived in the
`except Exception` handler, so it covered a task that RAISED and not one whose
action RETURNED `(text, False)` — which is how every built-in email action
reports failure, and those are the actions that get an owner soft-banned.
"""

import asyncio
import sqlite3
import sys
from datetime import datetime, timedelta
from types import SimpleNamespace
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
from src.task_scheduler import (  # noqa: E402
    MAX_TASK_TIMEOUT_SECONDS,
    MIN_TASK_TIMEOUT_SECONDS,
    TaskScheduler,
    _resolve_task_timezone,
    dispatch_hold,
    failure_next_run,
    task_timeout_seconds,
    valid_timezone,
)

# `scheduled_tasks` as it was before this row, written out rather than derived
# from the model — a schema derived from the model is the schema that already
# has the columns, which is the whole failure `Law 20` guards and the one
# `P8-25` fell into.
_LEGACY_SCHEDULED_TASKS = """
CREATE TABLE scheduled_tasks (
    id VARCHAR NOT NULL,
    owner VARCHAR,
    name VARCHAR NOT NULL,
    prompt TEXT,
    task_type VARCHAR,
    action VARCHAR,
    schedule VARCHAR,
    scheduled_time VARCHAR,
    scheduled_day INTEGER,
    scheduled_date DATETIME,
    trigger_type VARCHAR,
    trigger_event VARCHAR,
    trigger_count INTEGER,
    trigger_counter INTEGER,
    next_run DATETIME,
    last_run DATETIME,
    status VARCHAR,
    output_target VARCHAR,
    session_id VARCHAR,
    model VARCHAR,
    endpoint_url VARCHAR,
    run_count INTEGER,
    cron_expression VARCHAR,
    then_task_id VARCHAR,
    else_task_id VARCHAR,
    webhook_token VARCHAR,
    crew_member_id VARCHAR,
    character_id VARCHAR,
    max_steps INTEGER,
    email_results BOOLEAN,
    notifications_enabled BOOLEAN,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (webhook_token)
)
"""

_NEW_COLUMNS = ("tz_name", "max_retries", "timeout_seconds")


def _legacy_db(tmp_path):
    path = tmp_path / "legacy-exec.db"
    conn = sqlite3.connect(path)
    try:
        conn.execute(_LEGACY_SCHEDULED_TASKS)
        conn.execute(
            "INSERT INTO scheduled_tasks (id, name, task_type, status, "
            "created_at, updated_at) VALUES "
            "('old', 'An existing task', 'llm', 'active', "
            "'2026-01-01 00:00:00', '2026-01-01 00:00:00')"
        )
        conn.commit()
    finally:
        conn.close()
    return path


def _columns(path, table="scheduled_tasks"):
    conn = sqlite3.connect(path)
    try:
        return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
    finally:
        conn.close()


# ── the migration, against a database that never had the columns ───────────

def test_a_database_without_the_columns_rejects_the_write(tmp_path):
    """The defect, stated as a test: this is what an upgraded install does."""
    path = _legacy_db(tmp_path)
    for column in _NEW_COLUMNS:
        assert column not in _columns(path)
    conn = sqlite3.connect(path)
    try:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute(
                "INSERT INTO scheduled_tasks (id, name, tz_name, created_at, "
                "updated_at) VALUES ('new', 'x', 'UTC', '2026-01-02 00:00:00', "
                "'2026-01-02 00:00:00')")
    finally:
        conn.close()


def test_the_migration_adds_all_three_to_a_database_that_never_had_them(
        monkeypatch, tmp_path):
    path = _legacy_db(tmp_path)
    monkeypatch.setattr(cdb, "DATABASE_URL", f"sqlite:///{path}")

    cdb._migrate_add_scheduled_task_execution_columns()

    cols = _columns(path)
    for column in _NEW_COLUMNS:
        assert column in cols, f"{column} missing; table is {cols}"
    conn = sqlite3.connect(path)
    try:
        # The row that was already there survives, unset rather than lost.
        row = conn.execute(
            "SELECT tz_name, max_retries, timeout_seconds FROM scheduled_tasks "
            "WHERE id='old'").fetchone()
        assert row == (None, None, None)
        conn.execute(
            "INSERT INTO scheduled_tasks (id, name, tz_name, max_retries, "
            "timeout_seconds, created_at, updated_at) VALUES "
            "('new', 'x', 'Australia/Sydney', 3, 600, '2026-01-02 00:00:00', "
            "'2026-01-02 00:00:00')")
        conn.commit()
        assert conn.execute(
            "SELECT tz_name, max_retries, timeout_seconds FROM scheduled_tasks "
            "WHERE id='new'").fetchone() == ("Australia/Sydney", 3, 600)
    finally:
        conn.close()


def test_the_migration_is_idempotent(monkeypatch, tmp_path):
    """`init_db` runs every migration on every boot."""
    path = _legacy_db(tmp_path)
    monkeypatch.setattr(cdb, "DATABASE_URL", f"sqlite:///{path}")
    cdb._migrate_add_scheduled_task_execution_columns()
    cdb._migrate_add_scheduled_task_execution_columns()
    cols = _columns(path)
    for column in _NEW_COLUMNS:
        assert cols.count(column) == 1


def test_the_migration_adds_only_what_is_missing(monkeypatch, tmp_path):
    """A half-migrated database — one column added by an earlier partial run —
    gets the other two rather than erroring out on the first."""
    path = _legacy_db(tmp_path)
    conn = sqlite3.connect(path)
    try:
        conn.execute("ALTER TABLE scheduled_tasks ADD COLUMN tz_name TEXT")
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setattr(cdb, "DATABASE_URL", f"sqlite:///{path}")
    cdb._migrate_add_scheduled_task_execution_columns()
    for column in _NEW_COLUMNS:
        assert column in _columns(path)


def test_init_db_runs_the_migration():
    """A migration nobody calls is the same defect wearing a fix (`Law 13`).

    Parsed from the file with `ast` rather than grepped, and from the path
    rather than `inspect.getsource` (`Law 19`, `Law 20`).
    """
    import ast
    from pathlib import Path

    tree = ast.parse(Path(cdb.__file__).read_text(encoding="utf-8"))
    init_db = next(
        n for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "init_db")
    called = {
        node.func.id for node in ast.walk(init_db)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert "_migrate_add_scheduled_task_execution_columns" in called


# ── the timezone ───────────────────────────────────────────────────────────

def test_a_zone_this_machine_does_not_know_is_refused_not_stored():
    """`compute_next_run` swallows the lookup error and falls back to naive
    UTC, so a typo is a task that runs every day at the wrong time and says
    nothing. One function decides, and it is this one."""
    assert valid_timezone("Australia/Sydney") == "Australia/Sydney"
    assert valid_timezone("UTC") == "UTC"
    assert valid_timezone("Ameria/New_York") is None
    assert valid_timezone("") is None
    assert valid_timezone(None) is None
    assert valid_timezone("  Europe/Berlin  ") == "Europe/Berlin"


def test_the_task_beats_the_crew_member_and_the_crew_member_still_works():
    """`Law 1`. The crew-member path is what every existing task uses."""
    crew = SimpleNamespace(id="c1", timezone="Europe/Berlin")
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = crew

    own = SimpleNamespace(tz_name="Australia/Sydney", crew_member_id="c1")
    assert _resolve_task_timezone(db, own) == "Australia/Sydney"

    inherited = SimpleNamespace(tz_name=None, crew_member_id="c1")
    assert _resolve_task_timezone(db, inherited) == "Europe/Berlin"

    neither = SimpleNamespace(tz_name=None, crew_member_id=None)
    assert _resolve_task_timezone(db, neither) is None

    # A stored zone this build no longer knows falls THROUGH to the crew
    # member rather than silently meaning UTC.
    stale = SimpleNamespace(tz_name="Mars/Olympus", crew_member_id="c1")
    assert _resolve_task_timezone(db, stale) == "Europe/Berlin"


def test_the_dispatch_spread_is_sized_in_the_same_zone_the_run_uses():
    """The two-answers bug. `_task_period_seconds` read a column that did not
    exist, so the spread was always sized against a UTC period while the run
    itself was scheduled in the crew member's zone."""
    task = SimpleNamespace(
        schedule="daily", scheduled_time="09:00", scheduled_day=None,
        scheduled_date=None, cron_expression=None)
    now = datetime(2026, 6, 1, 12, 0, 0)
    # A daily task is a 24h period wherever it is, so the spread is capped the
    # same way — what is asserted here is that the zone REACHES the call at
    # all, which is checked by a zone that shifts the period: an hourly cron is
    # zone-independent, a daily one is not, and a nonsense zone would raise
    # inside `compute_next_run` and be swallowed into `None`.
    held_utc = dispatch_hold(task, now=now, tz_name=None)
    held_syd = dispatch_hold(task, now=now, tz_name="Australia/Sydney")
    assert 0.0 <= held_utc <= 45.0
    assert 0.0 <= held_syd <= 45.0
    import inspect
    sig = inspect.signature(dispatch_hold)
    assert "tz_name" in sig.parameters, "the caller has no way to pass the zone"


# ── retries ────────────────────────────────────────────────────────────────

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
        f"sqlite:///{tmp_path / 'exec.db'}",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(cdb, "SessionLocal", factory)
    return factory


def _seed(factory, *, max_retries=None, timeout_seconds=None, failures=0,
          action="tidy_sessions", task_type="action"):
    db = factory()
    try:
        db.add(ScheduledTask(
            id="t1", owner=None, name="A task", prompt="do it",
            task_type=task_type, action=action, trigger_type="schedule",
            schedule="daily", scheduled_time="09:00", status="active",
            output_target="session", max_retries=max_retries,
            timeout_seconds=timeout_seconds))
        base = datetime(2026, 6, 1, 0, 0, 0)
        for i in range(failures):
            db.add(TaskRun(id=f"old-{i}", task_id="t1", status="error",
                           started_at=base + timedelta(minutes=i)))
        db.add(TaskRun(id="r1", task_id="t1", status="queued",
                       started_at=base + timedelta(hours=1)))
        db.commit()
    finally:
        db.close()


def _task(factory, task_id="t1"):
    db = factory()
    try:
        return db.query(ScheduledTask).filter(ScheduledTask.id == task_id).first()
    finally:
        db.close()


def _scheduler():
    s = TaskScheduler.__new__(TaskScheduler)
    s._task_handles = {}
    s._task_defer_counts = {}
    s._session_manager = None
    s._notify_run_outcome = MagicMock(return_value=True)
    s.add_notification = MagicMock()
    s._log_to_assistant = MagicMock()
    s._deliver_task_result = AsyncMock(return_value=None)

    async def _run_chained(task_id, *, handoff=None):
        return None

    s._run_chained = _run_chained
    return s


def test_a_task_with_no_retry_budget_is_exactly_what_it_was(task_db):
    """`Law 1`. Every task in every existing install. The schedule, pushed out
    only when the backoff lands later — which is what `P15-08` computed."""
    _seed(task_db, max_retries=None, failures=1)
    db = task_db()
    try:
        task = db.query(ScheduledTask).filter(ScheduledTask.id == "t1").first()
        now = datetime(2026, 6, 1, 12, 0, 0)
        plan = failure_next_run(db, task, run_id="r1", now=now)
    finally:
        db.close()
    assert plan.is_retry is False
    assert plan.attempt == 2          # one recorded failure plus this one
    # A daily task's next slot is tomorrow 09:00; a 2-failure backoff is ~10
    # minutes, so the schedule wins and nothing is held back.
    assert plan.next_run == datetime(2026, 6, 2, 9, 0, 0)
    assert plan.note == ""


def test_a_retry_budget_brings_the_next_attempt_forward_to_the_ladder(task_db):
    """The row. A daily task that fails at 09:00 waited until tomorrow; with a
    budget it comes back on `P15-08`'s ladder and then falls back."""
    _seed(task_db, max_retries=2, failures=0)
    db = task_db()
    try:
        task = db.query(ScheduledTask).filter(ScheduledTask.id == "t1").first()
        now = datetime(2026, 6, 1, 12, 0, 0)
        first = failure_next_run(db, task, run_id="r1", now=now)
    finally:
        db.close()
    assert first.is_retry is True
    assert first.attempt == 1
    assert first.next_run < datetime(2026, 6, 2, 9, 0, 0), "not a retry at all"
    assert "retrying (attempt 1 of 2)" in first.note


def test_a_retry_never_fires_sooner_than_the_interval_floor(task_db):
    """`FORBIDDEN.md` Part 2. A retry is one more request to the provider that
    has just refused us, so the floor holds and the ladder is jittered — both
    of them the ones that already exist."""
    from src.task_scheduler import MIN_TASK_INTERVAL_SECONDS

    _seed(task_db, max_retries=5, failures=0)
    db = task_db()
    try:
        task = db.query(ScheduledTask).filter(ScheduledTask.id == "t1").first()
        now = datetime(2026, 6, 1, 12, 0, 0)
        seen = [failure_next_run(db, task, run_id="r1", now=now)
                for _ in range(25)]
    finally:
        db.close()
    for plan in seen:
        assert (plan.next_run - now).total_seconds() >= MIN_TASK_INTERVAL_SECONDS
    # Jittered, not a constant — the herd this avoids is across installs.
    assert len({p.next_run for p in seen}) > 1


def test_the_budget_runs_out_and_the_schedule_comes_back(task_db):
    _seed(task_db, max_retries=2, failures=2)
    db = task_db()
    try:
        task = db.query(ScheduledTask).filter(ScheduledTask.id == "t1").first()
        plan = failure_next_run(db, task, run_id="r1",
                                now=datetime(2026, 6, 1, 12, 0, 0))
    finally:
        db.close()
    assert plan.attempt == 3
    assert plan.is_retry is False
    assert plan.next_run == datetime(2026, 6, 2, 9, 0, 0)


def test_an_event_triggered_task_is_not_put_on_a_clock(task_db):
    """Re-firing an event task without its event would make it a different
    kind of task. It waits for the trigger, and always has."""
    _seed(task_db, max_retries=3)
    db = task_db()
    try:
        task = db.query(ScheduledTask).filter(ScheduledTask.id == "t1").first()
        task.trigger_type = "event"
        plan = failure_next_run(db, task, run_id="r1",
                                now=datetime(2026, 6, 1, 12, 0, 0))
    finally:
        db.close()
    assert plan.next_run is None
    assert plan.is_retry is False


@pytest.mark.asyncio
async def test_a_retry_budget_is_honoured_by_the_engine_not_just_the_helper(
        task_db, monkeypatch):
    """`Law 13`. The arithmetic being right is worth nothing if the executor
    does not call it — and the failure path that calls it is the one nobody
    had wired."""
    _seed(task_db, max_retries=1)

    async def failing(**kwargs):
        return "the mailbox refused us", False

    monkeypatch.setitem(ba.BUILTIN_ACTIONS, "tidy_sessions", failing)
    await _scheduler()._execute_task_locked(
        "t1", "r1", gate_foreground=False, release_executing=False)

    task = _task(task_db)
    assert task.next_run is not None
    # Brought forward onto the ladder rather than left at tomorrow 09:00.
    assert task.next_run < datetime.utcnow() + timedelta(hours=12)
    db = task_db()
    try:
        run = db.query(TaskRun).filter(TaskRun.id == "r1").first()
        assert run.status == "error"
        # The person is told, in the run they open, not only in the log.
        assert "retrying" in (run.steps or ""), run.steps
    finally:
        db.close()


@pytest.mark.asyncio
async def test_the_backoff_finally_reaches_a_returned_failure(task_db, monkeypatch):
    """The half of `P15-08` that was never wired, with no retry budget at all.

    A `*/5` cron task that has already failed five times. `P15-08`'s ladder
    puts attempt six about 2.7 hours out, which is later than the task's own
    next slot, so the ladder is what should win. A task that RAISED got that.
    A task whose action RETURNED `(text, False)` came straight back in **five
    minutes**, at full cadence, against the provider already refusing it —
    measured on the tree before this row, and `(text, False)` is exactly how
    every built-in email action reports failure.
    """
    from src.task_scheduler import FAILURE_BACKOFF_BASE_SECONDS

    db = task_db()
    try:
        db.add(ScheduledTask(
            id="t1", owner=None, name="Email", prompt="", task_type="action",
            action="tidy_sessions", trigger_type="schedule", schedule="cron",
            cron_expression="*/5 * * * *", status="active",
            output_target="session", max_retries=None))
        base = datetime(2026, 6, 1)
        for i in range(5):
            db.add(TaskRun(id=f"old-{i}", task_id="t1", status="error",
                           started_at=base + timedelta(minutes=i)))
        db.add(TaskRun(id="r1", task_id="t1", status="queued",
                       started_at=base + timedelta(hours=1)))
        db.commit()
    finally:
        db.close()

    async def failing(**kwargs):
        return "429 Too Many Requests", False

    monkeypatch.setitem(ba.BUILTIN_ACTIONS, "tidy_sessions", failing)
    await _scheduler()._execute_task_locked(
        "t1", "r1", gate_foreground=False, release_executing=False)

    gap = (_task(task_db).next_run - datetime.utcnow()).total_seconds()
    # Attempt six on a doubling ladder from a 300s base is 9600s. The assertion
    # is only that the ladder applied at all — "much more than the 5-minute
    # slot" — because the value is jittered on purpose.
    assert gap > 4 * FAILURE_BACKOFF_BASE_SECONDS, (
        f"a returned failure came back in {gap / 60:.1f} min at full cadence")


# ── the timeout ────────────────────────────────────────────────────────────

def test_the_ceiling_is_clamped_and_zero_means_none():
    assert task_timeout_seconds(SimpleNamespace(timeout_seconds=None)) == 0
    assert task_timeout_seconds(SimpleNamespace(timeout_seconds=0)) == 0
    assert task_timeout_seconds(SimpleNamespace(timeout_seconds=-5)) == 0
    assert task_timeout_seconds(SimpleNamespace(timeout_seconds="nope")) == 0
    # A three-second ceiling is a task that can never finish.
    assert task_timeout_seconds(
        SimpleNamespace(timeout_seconds=3)) == MIN_TASK_TIMEOUT_SECONDS
    assert task_timeout_seconds(
        SimpleNamespace(timeout_seconds=10 ** 9)) == MAX_TASK_TIMEOUT_SECONDS
    assert task_timeout_seconds(SimpleNamespace(timeout_seconds=600)) == 600
    # A row from before the column.
    assert task_timeout_seconds(SimpleNamespace()) == 0


@pytest.mark.asyncio
async def test_a_run_past_its_ceiling_is_stopped_and_called_a_failure(
        task_db, monkeypatch):
    """`error`, not `aborted`. `core/database.py` puts a user stop, a
    foreground takeover and a restart under `aborted` and calls them "not a
    failure", because folding infrastructure into the error rate corrupts it.
    A ceiling the OWNER set on THIS task is the opposite of infrastructure."""
    _seed(task_db, timeout_seconds=MIN_TASK_TIMEOUT_SECONDS)
    monkeypatch.setattr("src.task_scheduler.task_timeout_seconds",
                        lambda task: 0.05)
    finished = []

    async def slow(**kwargs):
        await asyncio.sleep(5)
        finished.append(1)
        return "eventually", True

    monkeypatch.setitem(ba.BUILTIN_ACTIONS, "tidy_sessions", slow)
    sched = _scheduler()
    await sched._execute_task_locked(
        "t1", "r1", gate_foreground=False, release_executing=False)

    assert finished == [], "the action outlived its own timeout"
    db = task_db()
    try:
        run = db.query(TaskRun).filter(TaskRun.id == "r1").first()
        assert run.status == "error", run.status
        assert "Timed out" in (run.error or "")
        assert "Stopped by user" not in (run.error or "")
    finally:
        db.close()


@pytest.mark.asyncio
async def test_a_task_with_no_ceiling_is_never_wrapped(task_db, monkeypatch):
    """`Law 1`. Unbounded is what every run has always been, and a `wait_for`
    with no timeout is still a `wait_for` — one more frame on every run in the
    product to say nothing."""
    _seed(task_db, timeout_seconds=None)
    waits = []
    real_wait_for = asyncio.wait_for

    async def counting_wait_for(coro, timeout=None, **kwargs):
        waits.append(timeout)
        return await real_wait_for(coro, timeout=timeout, **kwargs)

    monkeypatch.setattr(asyncio, "wait_for", counting_wait_for)

    async def quick(**kwargs):
        return "done", True

    monkeypatch.setitem(ba.BUILTIN_ACTIONS, "tidy_sessions", quick)
    await _scheduler()._execute_task_locked(
        "t1", "r1", gate_foreground=False, release_executing=False)

    assert waits == [], f"a task with no ceiling went through wait_for: {waits}"
    db = task_db()
    try:
        assert db.query(TaskRun).filter(TaskRun.id == "r1").first().status == "success"
    finally:
        db.close()


@pytest.mark.asyncio
async def test_a_timeout_from_inside_an_executor_is_not_claimed_as_ours(
        task_db, monkeypatch):
    """An executor can raise `asyncio.TimeoutError` from a `wait_for` of its
    own. Calling that "this task's timeout" would name a limit the task does
    not have, and would print a ceiling of zero seconds.

    Driven on the **llm** path deliberately. `_execute_action` catches
    `Exception`, and `asyncio.TimeoutError` is one in 3.11 — so an action can
    never raise it out of that function, and a test written against an action
    would be green whatever this branch did.
    """
    _seed(task_db, timeout_seconds=None, task_type="llm", action=None)
    sched = _scheduler()

    async def inner_timeout(*a, **k):
        raise asyncio.TimeoutError("something inside gave up")

    sched._execute_llm_task = inner_timeout
    await sched._execute_task_locked(
        "t1", "r1", gate_foreground=False, release_executing=False)

    db = task_db()
    try:
        run = db.query(TaskRun).filter(TaskRun.id == "r1").first()
        assert run.status == "error"
        assert "this task's own timeout" not in (run.error or ""), run.error
        assert "0 minutes" not in (run.error or ""), run.error
    finally:
        db.close()


@pytest.mark.asyncio
async def test_the_scheduler_sizes_the_spread_in_the_task_s_own_zone(
        task_db, monkeypatch):
    """`Law 20`, driven rather than parsed.

    `_task_period_seconds` having a `tz_name` parameter is worth nothing if the
    only caller that knows the zone does not pass it — which is the shape the
    defect had in the first place.
    """
    _seed(task_db)
    db = task_db()
    try:
        db.query(ScheduledTask).filter(ScheduledTask.id == "t1").first().tz_name = \
            "Australia/Sydney"
        db.query(ScheduledTask).filter(ScheduledTask.id == "t1").first().next_run = \
            datetime.utcnow() - timedelta(minutes=1)
        db.commit()
    finally:
        db.close()

    seen = {}

    def _hold(task, *, now=None, tz_name=None):
        seen["tz_name"] = tz_name
        return 0.0

    monkeypatch.setattr("src.task_scheduler.dispatch_hold", _hold)
    sched = _scheduler()
    sched._executing = set()
    sched._executing_lock = asyncio.Lock()
    sched._refresh_concurrency_cap = MagicMock(return_value=1)
    dispatched = []

    async def _dispatch_after(task_id, hold):
        dispatched.append(task_id)

    sched._dispatch_after = _dispatch_after
    await sched._check_due_tasks()
    await asyncio.sleep(0)

    assert dispatched == ["t1"], dispatched
    assert seen.get("tz_name") == "Australia/Sydney", seen


@pytest.mark.asyncio
async def test_the_api_refuses_a_timezone_this_machine_does_not_know(
        task_db, monkeypatch):
    """A typo stored is a task that runs every day at the wrong time and says
    nothing, because `compute_next_run` swallows the lookup error."""
    import routes.task.task_routes as task_routes
    from fastapi import HTTPException

    monkeypatch.setattr(task_routes, "SessionLocal", task_db)
    _seed(task_db)
    router = task_routes.setup_task_routes(MagicMock())
    create = next(
        r.endpoint for r in router.routes
        if getattr(r, "path", None) == "/api/tasks" and "POST" in getattr(r, "methods", set()))
    request = SimpleNamespace(state=SimpleNamespace(current_user=None))

    bad = task_routes.TaskCreate(
        name="x", prompt="y", task_type="llm", schedule="daily",
        scheduled_time="09:00", tz_name="Ameria/New_York")
    with pytest.raises(HTTPException) as exc:
        await create(request, bad)
    assert exc.value.status_code == 400
    assert "timezone" in str(exc.value.detail).lower()


@pytest.mark.asyncio
async def test_the_api_refuses_a_ceiling_that_cannot_work(task_db, monkeypatch):
    import routes.task.task_routes as task_routes
    from fastapi import HTTPException

    monkeypatch.setattr(task_routes, "SessionLocal", task_db)
    _seed(task_db)
    router = task_routes.setup_task_routes(MagicMock())
    create = next(
        r.endpoint for r in router.routes
        if getattr(r, "path", None) == "/api/tasks" and "POST" in getattr(r, "methods", set()))
    request = SimpleNamespace(state=SimpleNamespace(current_user=None))

    for field, value in (("timeout_seconds", 3), ("max_retries", 99)):
        body = task_routes.TaskCreate(
            name="x", prompt="y", task_type="llm", schedule="daily",
            scheduled_time="09:00", **{field: value})
        with pytest.raises(HTTPException) as exc:
            await create(request, body)
        assert exc.value.status_code == 400, field
