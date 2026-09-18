# SPDX-License-Identifier: AGPL-3.0-or-later
"""A schedulable task has a floor, and a failing one slows down (`P15-08`).

Measured on the tree before this row:

  * `routes/task/task_routes.py` validated cron **syntax** and nothing else,
    against a free-text field. `* * * * *` was accepted by create and by update:
    1,440 runs a day, each able to open a mailbox, walk the whole search
    provider chain and call a model API. `P15` exists because this product got
    its owner's IP soft-banned by GitHub in one afternoon; this is that
    afternoon, on a timer, every day.
  * a failing task did not back off. `_execute_task_locked`'s error path
    recomputed `next_run` from the schedule, so a task failing against a
    rate-limiting provider retried at full cadence for ever — and every retry is
    another request to the thing already refusing us.

The product has been bitten by this exact class once already: the seeded
`check_email_urgency` shipped at `*/15 * * * *` and was walked back to hourly
with a migration.
"""
from datetime import datetime, timedelta

import pytest

from src import task_scheduler as ts

pytest.importorskip("croniter")


@pytest.fixture(autouse=True)
def _floor(monkeypatch):
    """Five minutes, pinned — the tests are about the rule, not the number.

    `raising=False` so this file COLLECTS and fails on a tree that has no floor
    at all, rather than erroring in a fixture: a red test is evidence and a
    fixture error is a missing import (`Law 9`).
    """
    monkeypatch.setattr(ts, "min_task_interval_seconds", lambda: 300,
                        raising=False)


# ---------------------------------------------------------------------------
# What "too fast" means
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("expr,seconds", [
    ("* * * * *", 60),
    ("*/2 * * * *", 120),
    ("*/15 * * * *", 900),
    ("0 * * * *", 3600),
    ("0 6,18 * * *", 12 * 3600),
    # The one a naive implementation gets wrong: three firings an hour is not
    # "every twenty minutes", and the gap that matters is the shortest one.
    ("0,1,30 * * * *", 60),
])
def test_the_shortest_gap_is_what_a_floor_is_compared_against(expr, seconds):
    assert ts.cron_interval_seconds(expr) == seconds


def test_an_unparseable_expression_is_not_this_functions_answer_to_give():
    assert ts.cron_interval_seconds("not a cron") is None
    assert ts.cron_floor_problem("not a cron") is None      # the syntax check's job


@pytest.mark.parametrize("expr", ["* * * * *", "*/2 * * * *", "0,1,30 * * * *"])
def test_a_too_fast_schedule_is_refused_with_a_reason_a_person_can_read(expr):
    problem = ts.cron_floor_problem(expr)
    assert problem
    # What they asked for, what the limit is, and the setting that moves it.
    assert "minimum" in problem and "5 minutes" in problem
    assert "min_task_interval_minutes" in problem


@pytest.mark.parametrize("expr", ["*/5 * * * *", "0 * * * *", "0 3 * * *"])
def test_a_schedule_at_or_over_the_floor_is_left_alone(expr):
    assert ts.cron_floor_problem(expr) is None


def test_turning_the_floor_off_is_a_setting_not_a_code_edit(monkeypatch):
    """`Law 1`. An operator whose tasks only touch their own LAN keeps the
    capability; what changes is what you get without thinking about it."""
    monkeypatch.setattr(ts, "min_task_interval_seconds", lambda: 0,
                        raising=False)
    assert ts.cron_floor_problem("* * * * *") is None


# ---------------------------------------------------------------------------
# The rows that are already in the database
# ---------------------------------------------------------------------------

def test_a_minute_by_minute_task_already_in_the_database_is_paced_not_broken():
    """Refusing new ones does nothing about a task created before this shipped,
    seeded by a migration, or written straight into the DB."""
    now = datetime(2026, 9, 18, 12, 0, 0)
    nxt = ts.compute_next_run("cron", None, None, None, after=now,
                              cron_expression="* * * * *")
    assert nxt >= now + timedelta(seconds=300)


def test_pacing_never_pulls_a_slow_schedule_forward():
    """The floor is a floor. A daily task must not start running every 5
    minutes because something clamped in the wrong direction."""
    now = datetime(2026, 9, 18, 12, 0, 0)
    nxt = ts.compute_next_run("cron", None, None, None, after=now,
                              cron_expression="0 3 * * *")
    assert nxt == datetime(2026, 9, 19, 3, 0, 0)


def test_a_schedule_that_is_already_late_enough_is_untouched():
    now = datetime(2026, 9, 18, 12, 0, 0)
    assert ts.apply_interval_floor(now + timedelta(hours=1), after=now) == \
        now + timedelta(hours=1)


def test_the_floor_does_not_invent_a_run_for_a_task_that_has_none():
    assert ts.apply_interval_floor(None) is None


def test_the_shipped_housekeeping_jobs_are_all_over_the_floor():
    """If the product's own seeded tasks tripped this, the floor would be
    silently rescheduling them — which is a migration, not a validation."""
    for action, defs in ts.HOUSEKEEPING_DEFAULTS.items():
        expr = defs.get("cron_expression")
        if expr:
            assert ts.cron_floor_problem(expr) is None, action


# ---------------------------------------------------------------------------
# A failing task slows down
# ---------------------------------------------------------------------------

def test_the_backoff_escalates_and_is_capped():
    first = ts.failure_backoff_seconds(1)
    second = ts.failure_backoff_seconds(2)
    assert ts.FAILURE_BACKOFF_BASE_SECONDS <= first < second
    # Capped, so a task that has failed for a week is not scheduled for next year.
    assert ts.failure_backoff_seconds(40) <= ts.FAILURE_BACKOFF_CAP_SECONDS * 1.25


def test_the_backoff_is_jittered():
    """`P15-10`'s reason, not a new one: a provider that rate-limits everyone at
    once is the synchronising event, and a fleet retrying at exactly 5, 10 and
    20 minutes past it is the herd arriving three times."""
    values = {ts.failure_backoff_seconds(2) for _ in range(50)}
    assert len(values) > 10


def test_consecutive_failures_counts_the_streak_and_a_success_ends_it(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from core.database import Base, ScheduledTask, TaskRun

    engine = create_engine(f"sqlite:///{tmp_path}/t.db")
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    # `task_runs.task_id` is a real FK with ON DELETE CASCADE, and
    # `core.database` turns SQLite's enforcement on — so the runs need a task.
    db.add(ScheduledTask(id="T", name="nightly", task_type="llm",
                         schedule="cron", cron_expression="0 * * * *"))
    db.commit()

    base = datetime(2026, 9, 18, 9, 0, 0)

    def add(i, status):
        db.add(TaskRun(id=f"r{i}", task_id="T", status=status,
                       started_at=base + timedelta(minutes=i)))

    add(1, "success")
    add(2, "error")
    add(3, "error")
    db.commit()
    assert ts.consecutive_failures(db, "T") == 2

    add(4, "success")
    db.commit()
    assert ts.consecutive_failures(db, "T") == 0

    add(5, "error")
    add(6, "running")          # in flight — says nothing about the last attempt
    db.commit()
    assert ts.consecutive_failures(db, "T") == 1
    # The run being processed right now is excluded, because its row is updated
    # in an unflushed session and would otherwise be counted or not by accident.
    assert ts.consecutive_failures(db, "T", before_run_id="r5") == 0
    db.close()


def test_a_failing_task_is_pushed_past_its_next_slot():
    """The whole row, in one line of arithmetic: the next slot is one minute
    away, the backoff is five, and the later of the two wins."""
    now = datetime(2026, 9, 18, 12, 0, 0)
    next_slot = now + timedelta(seconds=60)
    delay = ts.failure_backoff_seconds(1)
    assert now + timedelta(seconds=delay) > next_slot


# ---------------------------------------------------------------------------
# The two doors it can come in by
# ---------------------------------------------------------------------------

def _endpoint(method, path):
    """The real route function, out of the real router (`Law 20` — drive it)."""
    from unittest.mock import MagicMock
    import routes.task_routes as task_routes

    router = task_routes.setup_task_routes(MagicMock())
    for route in router.routes:
        if (getattr(route, "path", None) == path
                and method in getattr(route, "methods", set())):
            return route.endpoint
    raise RuntimeError(f"{method} {path} not found")


@pytest.mark.asyncio
async def test_the_create_route_refuses_a_minute_by_minute_task(monkeypatch):
    from fastapi import HTTPException
    import routes.task_routes as task_routes

    monkeypatch.setattr(task_routes, "get_current_user", lambda request: "alice")
    create = _endpoint("POST", "/api/tasks")
    body = task_routes.TaskCreate(
        prompt="check my mail", task_type="llm", trigger_type="schedule",
        schedule="cron", cron_expression="* * * * *")

    with pytest.raises(HTTPException) as e:
        await create(request=None, req=body)
    assert e.value.status_code == 400
    assert "minimum" in e.value.detail
    assert "min_task_interval_minutes" in e.value.detail


@pytest.fixture()
def task_db(monkeypatch, tmp_path):
    """Real tables on a throwaway SQLite file, bound where the route looks."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import NullPool
    import core.database as cdb
    import routes.task_routes as task_routes

    engine = create_engine(f"sqlite:///{tmp_path / 'tasks.db'}",
                           connect_args={"check_same_thread": False},
                           poolclass=NullPool)
    cdb.Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(task_routes, "SessionLocal", maker)
    monkeypatch.setattr(cdb, "SessionLocal", maker)
    return maker


@pytest.mark.asyncio
async def test_the_update_route_refuses_it_too(monkeypatch, task_db):
    """An edit was the way round the create check: make it hourly, then PUT
    `* * * * *`. One rule, two doors (`Law 13`)."""
    from fastapi import HTTPException
    from core.database import ScheduledTask
    import routes.task_routes as task_routes

    monkeypatch.setattr(task_routes, "get_current_user", lambda request: "alice")
    db = task_db()
    db.add(ScheduledTask(id="T1", owner="alice", name="mail", prompt="p",
                         task_type="llm", trigger_type="schedule",
                         schedule="cron", cron_expression="0 * * * *",
                         status="active"))
    db.commit()
    db.close()

    update = _endpoint("PUT", "/api/tasks/{task_id}")
    body = task_routes.TaskUpdate(cron_expression="*/2 * * * *")

    with pytest.raises(HTTPException) as e:
        await update(request=None, task_id="T1", req=body)
    assert e.value.status_code == 400
    assert "min_task_interval_minutes" in e.value.detail

    # And the row is unchanged — a refused edit must not half-apply.
    db = task_db()
    assert db.query(ScheduledTask).filter(ScheduledTask.id == "T1").first() \
             .cron_expression == "0 * * * *"
    db.close()


@pytest.mark.asyncio
async def test_a_schedule_over_the_floor_still_gets_through_the_route(monkeypatch):
    """`Law 1`. The refusal must not be the only thing the route now does."""
    from fastapi import HTTPException
    import routes.task_routes as task_routes

    monkeypatch.setattr(task_routes, "get_current_user", lambda request: "alice")
    update = _endpoint("PUT", "/api/tasks/{task_id}")
    body = task_routes.TaskUpdate(cron_expression="0 * * * *")
    try:
        await update(request=None, task_id="no-such-task", req=body)
    except HTTPException as e:
        # 404 is the right refusal for a task that does not exist. 400 would
        # mean the floor rejected an hourly schedule.
        assert e.status_code == 404, e.detail


@pytest.mark.asyncio
async def test_a_failing_task_actually_gets_held_back_by_the_scheduler(monkeypatch, task_db):
    """The wiring, not the helper.

    Every other test here calls `failure_backoff_seconds` or
    `consecutive_failures` directly, and all of them keep passing with the call
    site deleted — which is the survived mutation this project keeps finding.
    This one runs the real error path and reads `next_run` off the row.
    """
    from datetime import timezone
    from core.database import ScheduledTask, TaskRun
    from src.task_scheduler import TaskScheduler

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db = task_db()
    db.add(ScheduledTask(id="T9", owner="alice", name="mail", prompt="p",
                         task_type="llm", trigger_type="schedule",
                         schedule="cron", cron_expression="*/10 * * * *",
                         status="active", next_run=now - timedelta(minutes=1)))
    # Two runs that already failed, so `seen` below distinguishes "the streak
    # was counted" from "a constant 1 was passed" — which a single failure
    # cannot, and a survived mutation proved it could not.
    db.add(TaskRun(id="old-1", task_id="T9", status="error",
                   started_at=now - timedelta(hours=2)))
    db.add(TaskRun(id="old-2", task_id="T9", status="error",
                   started_at=now - timedelta(hours=1)))
    db.add(TaskRun(id="run-9", task_id="T9", status="queued", started_at=now))
    db.commit()
    db.close()

    async def _boom(self, task, db):
        raise RuntimeError("provider said 429")

    monkeypatch.setattr(TaskScheduler, "_execute_llm_task", _boom)
    # Pinned, so the assertion is about the WIRING and not about whether a
    # jittered five minutes happened to land past a `*/10` boundary.
    seen = []
    monkeypatch.setattr(ts, "failure_backoff_seconds",
                        lambda failures: (seen.append(failures), 3600.0)[1],
                        raising=False)

    sched = TaskScheduler.__new__(TaskScheduler)
    sched._task_handles = {}
    sched._pending_notifications = []
    sched._task_defer_counts = {}
    await sched._execute_task_locked("T9", "run-9", gate_foreground=False,
                                     release_executing=False)

    db = task_db()
    task = db.query(ScheduledTask).filter(ScheduledTask.id == "T9").first()
    run = db.query(TaskRun).filter(TaskRun.id == "run-9").first()
    assert run.status == "error"
    assert seen == [3], "the failure streak was not counted"
    # Its schedule says every ten minutes. The backoff says an hour, and the
    # later of the two is what is written.
    assert task.next_run > now + timedelta(minutes=55), (
        "a failing task went straight back onto its own schedule")
    db.close()


# ---------------------------------------------------------------------------
# The setting is a setting, and what is stored is what runs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_floor_setting_is_clamped_where_every_other_number_is(monkeypatch):
    """`routes/auth_routes.py`'s `_INT_RANGES` exists because a stored value
    that is not the effective value is the settings page lying about itself.

    `min_task_interval_minutes` falls back to the default on a value it cannot
    use, so without an entry there an operator could store `-5`, be told it
    saved, and get five minutes.
    """
    from types import SimpleNamespace
    import routes.auth_routes as auth_routes
    import src.settings as settings_mod

    store = dict(settings_mod.DEFAULT_SETTINGS)

    class _AuthManager:
        def get_username_for_token(self, token):
            return "admin" if token == "admin-session" else None

        def is_admin(self, username):
            return username == "admin"

    class _Request(SimpleNamespace):
        def __init__(self, body):
            super().__init__(cookies={auth_routes.SESSION_COOKIE: "admin-session"},
                             _body=body)

        async def json(self):
            return self._body

    monkeypatch.setattr(auth_routes, "migrate_from_settings", lambda: None)
    monkeypatch.setattr(auth_routes, "_load_settings", lambda: dict(store))
    monkeypatch.setattr(auth_routes, "_save_settings",
                        lambda updated: (store.clear(), store.update(updated)))
    router = auth_routes.setup_auth_routes(_AuthManager())
    post = next(r.endpoint for r in router.routes
                if r.path == "/api/auth/settings" and "POST" in r.methods)

    await post(_Request({"min_task_interval_minutes": -5,
                         "index_max_file_mb": -1,
                         "index_budget_mb": 99_999_999}))
    assert store["min_task_interval_minutes"] == 0     # clamped to "off"
    assert store["index_max_file_mb"] == 0             # clamped to "no ceiling"
    assert store["index_budget_mb"] == 16384           # clamped to the top

    await post(_Request({"min_task_interval_minutes": 30}))
    assert store["min_task_interval_minutes"] == 30    # a real value is kept
