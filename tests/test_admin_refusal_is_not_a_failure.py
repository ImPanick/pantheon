# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B07` — a privilege refusal is not a failure, and it must still be actionable.

`src/task_scheduler.py` filed an admin-privilege refusal as `status="error"`.
The vocabulary block in `core/database.py` reserves `error` for *"the task
itself failed"* and defines `skipped` as *"deliberately did not run… Not a
failure"* — the refusal is the second of those, because the action never
started. Every refusal was counting against the task's error rate, which is the
corruption that block names in its own text for `aborted`.

**The value change alone would have subtracted UI, and that is the half of this
row that reading cannot find.** `_renderActivityEntry` computes `actionBtn`
(Copy log, Run again, Clear cache) and *then*, for a `skipped` row, returns a
slim single-line template that never interpolates it. Measured against the
pre-fix tree, flipping the status took **Copy log and Run again** off the row —
and `_wireActivityRows` gives `.is-skipped` no expand handler, so there was no
way back to them either. The slim row carries the buttons now.

The same measurement found a second regression the row does not mention: the
task card's last-run badge tested `last_run_status === 'error'` and painted a
**green ✓** on everything else. On the pre-fix tree a `skipped`, `aborted` or
`running` last run all rendered as a green tick — so the refusal would have
arrived beside one, reading "✓ Action 'x' requires admin privileges".

And the recording diverged at the second refusal site. `routes/task/task_routes.py`'s
webhook path applied the identical policy and wrote **no run row at all**, so a
refusal that arrived through a webhook was invisible in Activity: the task went
from active to paused with nothing on screen saying why, and the 403 went to
whatever POSTed the webhook rather than to the owner. One rule, two recordings
(`Law 13`) — both go through `record_admin_refusal` now.
"""

import asyncio
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from tests.helpers.import_state import clear_fake_database_modules

clear_fake_database_modules()

import core.auth as core_auth
import core.database as cdb
import routes.task_routes as task_routes
from core.database import ScheduledTask, TaskRun
from src.task_action_policy import ADMIN_REFUSAL_SUFFIX
from src.task_scheduler import TaskScheduler

ROOT = Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "harness" / "activity_row_status.js"

REFUSAL = f"Action 'cookbook_serve' {ADMIN_REFUSAL_SUFFIX}"

_REAL_DATABASE_ATTRS = {
    "Base": cdb.Base,
    "SessionLocal": cdb.SessionLocal,
    "ScheduledTask": ScheduledTask,
    "TaskRun": TaskRun,
}
if hasattr(cdb, "engine"):
    _REAL_DATABASE_ATTRS["engine"] = cdb.engine


def _restore_module_binding(monkeypatch, name, module):
    monkeypatch.setitem(sys.modules, name, module)
    parent_name, _, attr = name.rpartition(".")
    parent = sys.modules.get(parent_name)
    if parent is not None:
        monkeypatch.setattr(parent, attr, module, raising=False)


@pytest.fixture()
def task_db(monkeypatch, tmp_path):
    """Real tables on a throwaway SQLite file, bound into every module that
    reaches for `SessionLocal` or `engine`. `engine` matters here in a way it
    does not for the CRUD suites: the migration runs raw SQL through it."""
    _restore_module_binding(monkeypatch, "core.database", cdb)
    for attr, value in _REAL_DATABASE_ATTRS.items():
        monkeypatch.setattr(cdb, attr, value, raising=False)
    engine = create_engine(
        f"sqlite:///{tmp_path / 'tasks.db'}",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    cdb.Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(task_routes, "SessionLocal", testing_session)
    monkeypatch.setattr(cdb, "SessionLocal", testing_session)
    monkeypatch.setattr(cdb, "engine", engine)
    return testing_session


@pytest.fixture()
def configured_auth(monkeypatch):
    _restore_module_binding(monkeypatch, "core.auth", core_auth)
    monkeypatch.setenv("AUTH_ENABLED", "true")

    class FakeAuthManager:
        is_configured = True

        def is_admin(self, user):
            return user == "admin"

    monkeypatch.setattr(core_auth, "AuthManager", FakeAuthManager)


def _endpoint(method, path, scheduler=None):
    router = task_routes.setup_task_routes(scheduler or MagicMock())
    for route in router.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise RuntimeError(f"{method} {path} not found")


def _seed(session_factory, task_id="alice-task", owner="alice", **kw):
    db = session_factory()
    try:
        db.add(ScheduledTask(
            id=task_id, owner=owner, name=task_id, prompt="{}",
            task_type="action", action="cookbook_serve", trigger_type="webhook",
            status="active", output_target="session", **kw,
        ))
        db.commit()
    finally:
        db.close()


def _runs(session_factory, task_id="alice-task"):
    db = session_factory()
    try:
        return [
            SimpleNamespace(id=r.id, status=r.status, result=r.result,
                            error=r.error, finished_at=r.finished_at)
            for r in db.query(TaskRun).filter(TaskRun.task_id == task_id).all()
        ]
    finally:
        db.close()


def _task(session_factory, task_id="alice-task"):
    db = session_factory()
    try:
        t = db.query(ScheduledTask).filter(ScheduledTask.id == task_id).first()
        return SimpleNamespace(status=t.status, next_run=t.next_run, last_run=t.last_run)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# The scheduler path — the value the row is about
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scheduler_files_the_refusal_as_skipped(task_db, configured_auth):
    """`skipped`, not `error`: the action never ran, so it is not a failure."""
    due = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1)
    _seed(task_db, next_run=due)
    db = task_db()
    try:
        db.add(TaskRun(id="run-1", task_id="alice-task", status="queued"))
        db.commit()
    finally:
        db.close()

    scheduler = TaskScheduler.__new__(TaskScheduler)
    scheduler._task_handles = {}
    scheduler._pending_notifications = []
    await scheduler._execute_task_locked(
        "alice-task", "run-1", gate_foreground=False, release_executing=False)

    (run,) = _runs(task_db)
    assert run.status == "skipped"
    assert run.error == REFUSAL
    assert run.result == REFUSAL       # the Activity row reads `result`
    assert run.finished_at is not None  # terminal, not left in flight

    task = _task(task_db)
    assert task.status == "paused"
    assert task.next_run is None
    assert task.last_run is not None


def _refuse(task_db, configured_auth):
    """Run the scheduler's refusal path and hand back what it queued."""
    due = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1)
    _seed(task_db, next_run=due)
    db = task_db()
    try:
        db.add(TaskRun(id="run-1", task_id="alice-task", status="queued"))
        db.commit()
    finally:
        db.close()

    scheduler = TaskScheduler.__new__(TaskScheduler)
    scheduler._task_handles = {}
    scheduler._pending_notifications = []
    return scheduler


@pytest.mark.asyncio
async def test_scheduler_refusal_notifies_what_the_vocabulary_says_it_should(
        task_db, configured_auth):
    """`B07` pinned this as *notifies nobody*, and `B112` rewrote the pin.

    The original reason was the client, not the server. `_pollTaskNotifications`
    in `static/js/tasks.js` knew two statuses — `success` was "Task finished" and
    **everything else was "Task failed: <name>"** in a red error toast — so a
    `skipped` notification here would have put the exact lie this row removes
    back on screen in a different surface. `B78` fixed the client: `skipped` and
    `aborted` now produce a plain toast naming what they were and only `error`
    raises the failure dot. The constraint is gone, so the silence is no longer
    the answer, and pinning an ABSENCE would mean the next agent has to guess
    whether it is a decision or an oversight.

    So this asserts the statement instead: `core.database.TASK_RUN_NOTIFY` says
    which outcomes are worth telling the owner about, with a reason per status,
    and the refusal emits exactly what it says. The thing that must not come
    back is the WORD *failed*, and that is asserted separately below.
    """
    from core.database import TASK_RUN_NOTIFY, TASK_RUN_NOTIFY_STATUSES

    scheduler = _refuse(task_db, configured_auth)
    await scheduler._execute_task_locked(
        "alice-task", "run-1", gate_foreground=False, release_executing=False)

    assert TASK_RUN_NOTIFY["skipped"][0] is True, (
        "the policy is the thing under test; if it says no, so must the scheduler")
    assert "skipped" in TASK_RUN_NOTIFY_STATUSES
    (note,) = scheduler._pending_notifications
    assert note["status"] == "skipped"
    assert note["task_name"] == "alice-task"
    assert note["owner"] == "alice"
    assert note["body"] == REFUSAL, "the owner is told WHY the task stopped"


@pytest.mark.asyncio
async def test_the_refusal_notification_is_not_a_failure(task_db, configured_auth):
    """The half `B07` was actually protecting. `skipped` is not `error`, here or
    anywhere: the client scores the tone off the status, and a refusal filed as
    a failure corrupts the same error-rate numbers `core/database.py` names."""
    scheduler = _refuse(task_db, configured_auth)
    await scheduler._execute_task_locked(
        "alice-task", "run-1", gate_foreground=False, release_executing=False)

    (note,) = scheduler._pending_notifications
    assert note["status"] != "error"
    assert "fail" not in str(note.get("body", "")).lower()


@pytest.mark.asyncio
async def test_a_task_with_notifications_off_is_still_not_told(task_db, configured_auth):
    """`notifications_enabled` is the owner's per-task quiet switch and `B112`
    honours it. Without this, closing the gap would have made the switch a lie
    for exactly the tasks whose owners had asked for quiet."""
    scheduler = _refuse(task_db, configured_auth)
    db = task_db()
    try:
        t = db.query(ScheduledTask).filter(ScheduledTask.id == "alice-task").first()
        t.notifications_enabled = False
        db.commit()
    finally:
        db.close()

    await scheduler._execute_task_locked(
        "alice-task", "run-1", gate_foreground=False, release_executing=False)

    assert scheduler._pending_notifications == []
    # …and the refusal is still recorded, which is the part that is not optional.
    (run,) = _runs(task_db)
    assert run.status == "skipped"


# ---------------------------------------------------------------------------
# The webhook path — the recording that did not exist
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_webhook_refusal_is_visible_in_activity(task_db, configured_auth):
    """It used to pause the task and write nothing, so Activity showed no reason."""
    _seed(task_db, webhook_token="secret")
    webhook_trigger = _endpoint("POST", "/api/tasks/{task_id}/webhook/{token}")

    with pytest.raises(HTTPException) as exc:
        await webhook_trigger("alice-task", "secret")

    assert exc.value.status_code == 403
    assert exc.value.detail == REFUSAL

    runs = _runs(task_db)
    assert len(runs) == 1, "the webhook refusal must leave a run row"
    assert runs[0].status == "skipped"
    assert runs[0].error == REFUSAL
    assert runs[0].finished_at is not None

    task = _task(task_db)
    assert task.status == "paused"
    assert task.next_run is None


@pytest.mark.asyncio
async def test_webhook_refusal_never_starts_the_task(task_db, configured_auth):
    """Recording the refusal must not have turned it into a run."""
    _seed(task_db, webhook_token="secret")
    scheduler = SimpleNamespace(run_task_now=MagicMock())
    webhook_trigger = _endpoint(
        "POST", "/api/tasks/{task_id}/webhook/{token}", scheduler=scheduler)

    with pytest.raises(HTTPException):
        await webhook_trigger("alice-task", "secret")

    scheduler.run_task_now.assert_not_called()


@pytest.mark.asyncio
async def test_both_refusal_paths_record_the_same_thing(task_db, configured_auth):
    """`Law 13` in assertion form: one policy, one recording, checked against
    each other rather than against two hand-written expectations."""
    due = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1)
    _seed(task_db, task_id="sched-task", next_run=due)
    _seed(task_db, task_id="hook-task", webhook_token="secret")
    db = task_db()
    try:
        db.add(TaskRun(id="run-1", task_id="sched-task", status="queued"))
        db.commit()
    finally:
        db.close()

    scheduler = TaskScheduler.__new__(TaskScheduler)
    scheduler._task_handles = {}
    scheduler._pending_notifications = []
    await scheduler._execute_task_locked(
        "sched-task", "run-1", gate_foreground=False, release_executing=False)

    webhook_trigger = _endpoint("POST", "/api/tasks/{task_id}/webhook/{token}")
    with pytest.raises(HTTPException):
        await webhook_trigger("hook-task", "secret")

    (sched,) = _runs(task_db, "sched-task")
    (hook,) = _runs(task_db, "hook-task")
    assert (sched.status, sched.result, sched.error) == (hook.status, hook.result, hook.error)
    assert _task(task_db, "sched-task").status == _task(task_db, "hook-task").status == "paused"


# ---------------------------------------------------------------------------
# The migration — decided: migrate
# ---------------------------------------------------------------------------

def _seed_run(session_factory, run_id, task_id, status, error):
    db = session_factory()
    try:
        db.add(TaskRun(id=run_id, task_id=task_id, status=status,
                       result=error, error=error))
        db.commit()
    finally:
        db.close()


def _status_of(session_factory, run_id):
    db = session_factory()
    try:
        return db.query(TaskRun).filter(TaskRun.id == run_id).first().status
    finally:
        db.close()


def test_migration_refiles_old_refusals_and_nothing_else(task_db):
    """Leaving them would mean the Errors chip keeps showing historical
    refusals while every new one stays out of it — the same event filed two
    ways depending on when it happened."""
    _seed(task_db)
    _seed_run(task_db, "old-refusal", "alice-task", "error", REFUSAL)
    _seed_run(task_db, "real-failure", "alice-task", "error",
              "Traceback: the model endpoint refused the connection")
    # A row that merely mentions the phrase in its OUTPUT, not its error — the
    # predicate reads `error`, so this must survive as a failure.
    db = task_db()
    try:
        db.add(TaskRun(id="mentions-it", task_id="alice-task", status="error",
                       result=REFUSAL, error="the script exited 1"))
        db.commit()
    finally:
        db.close()

    cdb._migrate_reclassify_admin_refusals()

    assert _status_of(task_db, "old-refusal") == "skipped"
    assert _status_of(task_db, "real-failure") == "error"
    assert _status_of(task_db, "mentions-it") == "error"


def test_migration_is_idempotent_and_leaves_later_failures_alone(task_db):
    """Narrowed to `status = 'error'` so a re-run cannot touch an already-filed
    row, and a genuine later failure of the same task keeps its status."""
    _seed(task_db)
    _seed_run(task_db, "old-refusal", "alice-task", "error", REFUSAL)

    cdb._migrate_reclassify_admin_refusals()
    cdb._migrate_reclassify_admin_refusals()
    assert _status_of(task_db, "old-refusal") == "skipped"

    # A real failure recorded after the migration ran.
    _seed_run(task_db, "later", "alice-task", "error", "disk full")
    cdb._migrate_reclassify_admin_refusals()
    assert _status_of(task_db, "later") == "error"


def test_migration_is_wired_into_init_db():
    """A migration nobody calls is a comment."""
    import inspect
    src = inspect.getsource(cdb.init_db)
    assert "_migrate_reclassify_admin_refusals()" in src


@pytest.mark.asyncio
async def test_migration_predicate_matches_what_the_code_writes(task_db, configured_auth):
    """The join key is asserted against a refusal the current code produced,
    not against a string retyped in the test — so renaming the message cannot
    leave the migration matching nothing while every test still passes."""
    _seed(task_db, webhook_token="secret")
    webhook_trigger = _endpoint("POST", "/api/tasks/{task_id}/webhook/{token}")
    with pytest.raises(HTTPException):
        await webhook_trigger("alice-task", "secret")

    db = task_db()
    try:
        matched = db.execute(
            text("SELECT COUNT(*) FROM task_runs WHERE error LIKE :pat"),
            {"pat": f"%{ADMIN_REFUSAL_SUFFIX}"},
        ).scalar()
    finally:
        db.close()
    assert matched == 1


# ---------------------------------------------------------------------------
# The renderers — run, not read (`Law 20`)
# ---------------------------------------------------------------------------

def _harness(mode, payload=None):
    argv = ["node", str(HARNESS), mode]
    if payload is not None:
        argv.append(json.dumps(payload))
    proc = subprocess.run(argv, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _entry(status):
    return {
        "status": status, "kind": "action", "action": "cookbook_serve",
        "taskId": "t1", "taskName": "Serve model", "result": REFUSAL,
        "ts": "2026-09-14T00:00:00Z",
    }


def test_the_skipped_row_keeps_the_controls_the_error_row_had():
    """The `Law 1` half. On the pre-fix tree this row rendered with
    `copyLog=false, runAgain=false`; the slim template dropped a value it had
    already computed."""
    err = _harness("row", _entry("error"))
    skipped = _harness("row", _entry("skipped"))

    assert err["copyLog"] and err["runAgain"], "baseline: the error row had both"
    assert skipped["copyLog"], "Copy log must survive the status change"
    assert skipped["runAgain"], "Run again must survive the status change"
    assert skipped["showsResult"], "and the reason must still be readable"
    assert skipped["slim"], "while staying the slim one-line variant"


def test_the_buttons_on_the_skipped_row_are_actually_wired():
    """Rendering a button and attaching its handler are two functions in two
    places, and `_wireActivityRows` singles `.is-skipped` out — so a rendered
    button is not yet a working one. Run against the markup the renderer
    emitted: the row itself gets no click handler (it cannot expand, which is
    why the buttons had to go in the head rather than the hidden footer), and
    Copy log and Run again get theirs."""
    wired = _harness("wire", _entry("skipped"))
    assert wired["rowClick"] is False, "the slim row still does not expand"
    assert wired[".task-log-copy"], "Copy log is rendered but dead"
    assert wired[".task-log-run-again"], "Run again is rendered but dead"

    # Same two controls the error row had, same handlers.
    err = _harness("wire", _entry("error"))
    assert err[".task-log-copy"] and err[".task-log-run-again"]


def test_a_noop_skipped_row_gains_the_same_controls():
    """Not special-cased to the refusal: any skipped run that has a result and
    a task behind it can be copied and re-run."""
    noop = _harness("row", {
        "status": "skipped", "kind": "action", "action": "check_pings",
        "taskId": "t2", "taskName": "Ping check", "result": "no pings due",
        "ts": "2026-09-14T00:00:00Z",
    })
    assert noop["copyLog"] and noop["runAgain"]
    assert noop["slim"]


def test_the_refusal_leaves_the_errors_chip():
    """The row's own `Verify:` line — and the reason the status had to change."""
    assert _harness("row", _entry("error"))["chip"] == "error"
    assert _harness("row", _entry("skipped"))["chip"] == "info"
    assert _harness("row", _entry("success"))["chip"] == "ok"


def test_a_stored_status_still_outranks_the_text_scan():
    """The harness's `_classifyResult` stub answers `'error'` for every string,
    so a row that reaches the chip through the text scan shows up here. The
    2026-08-27 fix this protects — an `aborted` run whose partial output
    mentions "error" must not be filed under Errors — has to survive `B07`
    routing the same decision through `runStatusTone`."""
    for status, chip in (("aborted", "info"), ("skipped", "info"), ("success", "ok")):
        assert _harness("row", _entry(status))["chip"] == chip, status
    # No status at all is the one case the scan is allowed to decide.
    scanned = dict(_entry("error"))
    scanned.pop("status")
    assert _harness("row", scanned)["chip"] == "error"


def test_the_row_keeps_its_own_status_name_for_the_dot():
    """`runStatusTone` decides what is *scored* as a failure; it must not flatten
    the six `.task-log-status-*` styles down to three."""
    assert _harness("row", _entry("skipped"))["dot"] == "skipped"
    assert _harness("row", _entry("aborted"))["dot"] == "aborted"
    assert _harness("row", _entry("running"))["dot"] == "running"
    assert _harness("row", _entry("error"))["dot"] == "error"


def test_the_card_badge_does_not_tick_a_refusal():
    """Measured on the pre-fix tree: `skipped`, `aborted` and `running` all
    rendered a green ✓, because the badge had two outcomes for six statuses."""
    assert _harness("badge", {"last_run_status": "success",
                              "last_run_result": "done"})["mark"] == "✓"
    assert _harness("badge", {"last_run_status": "error",
                              "last_run_result": "boom"})["mark"] == "✗"
    for neutral in ("skipped", "aborted", "running", "queued"):
        got = _harness("badge", {"last_run_status": neutral,
                                 "last_run_result": REFUSAL})
        assert got["mark"] == "·", neutral
        assert not got["green"] and not got["red"], neutral


def test_run_status_tone_scores_the_whole_vocabulary():
    """The six stored values, plus the legacy `failed` older rows carry."""
    tone = _harness("tone")
    assert tone["success"] == "ok"
    assert tone["error"] == "error" and tone["failed"] == "error"
    assert tone["skipped"] == "info" and tone["aborted"] == "info"
    assert tone["queued"] == "pending" and tone["running"] == "pending"
    # Unknown falls through to the caller's text-scan fallback rather than
    # being silently scored.
    assert tone["undefined"] is None and tone[""] is None


# ---------------------------------------------------------------------------
# `B112` — which terminal outcomes reach the owner, and which deliberately
#          do not
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_failing_quiet_action_task_still_reaches_its_owner(
        task_db, configured_auth, monkeypatch):
    """The rule that shipped before `B112` and had to survive it.

    Housekeeping actions do not toast, and the owner can turn a task's
    notifications off — two quiet gates, and `error` overrides both, because a
    task failing on a schedule that nobody is told about keeps failing. `B112`
    moved every terminal branch through one policy reader, and the reader
    honours both gates; the override lives at the call site and is the only
    thing between "one statement of the policy" and a regression nobody would
    notice until a cron task had been broken for a week.
    """
    db = task_db()
    try:
        db.add(ScheduledTask(
            id="quiet-task", owner="alice", name="quiet-task", prompt="{}",
            task_type="action", action="tidy_sessions", trigger_type="webhook",
            status="active", output_target="session", notifications_enabled=False,
        ))
        db.add(TaskRun(id="run-q", task_id="quiet-task", status="queued"))
        db.commit()
    finally:
        db.close()

    scheduler = TaskScheduler.__new__(TaskScheduler)
    scheduler._task_handles = {}
    scheduler._task_defer_counts = {}
    scheduler._pending_notifications = []

    async def _fail(task, run_id=None):
        return "the tidy action exited 1", False

    monkeypatch.setattr(scheduler, "_execute_action", _fail, raising=False)
    await scheduler._execute_task_locked(
        "quiet-task", "run-q", gate_foreground=False, release_executing=False)

    (run,) = _runs(task_db, "quiet-task")
    assert run.status == "error"
    (note,) = scheduler._pending_notifications
    assert note["status"] == "error"
    assert note["task_name"] == "quiet-task"
    assert note["body"] == "the tidy action exited 1", (
        "the error branch carries the reason; the quiet branch would carry None")


@pytest.mark.asyncio
async def test_a_succeeding_quiet_action_task_stays_quiet(
        task_db, configured_auth, monkeypatch):
    """The other side of the same line, so the override cannot be widened into
    "notify on everything" without something failing."""
    db = task_db()
    try:
        db.add(ScheduledTask(
            id="quiet-ok", owner="alice", name="quiet-ok", prompt="{}",
            task_type="action", action="tidy_sessions", trigger_type="webhook",
            status="active", output_target="session", notifications_enabled=False,
        ))
        db.add(TaskRun(id="run-ok", task_id="quiet-ok", status="queued"))
        db.commit()
    finally:
        db.close()

    scheduler = TaskScheduler.__new__(TaskScheduler)
    scheduler._task_handles = {}
    scheduler._task_defer_counts = {}
    scheduler._pending_notifications = []

    async def _ok(task, run_id=None):
        return "tidied 3 sessions", True

    monkeypatch.setattr(scheduler, "_execute_action", _ok, raising=False)
    monkeypatch.setattr(scheduler, "_log_to_assistant", lambda *a, **k: None,
                        raising=False)
    await scheduler._execute_task_locked(
        "quiet-ok", "run-ok", gate_foreground=False, release_executing=False)

    (run,) = _runs(task_db, "quiet-ok")
    assert run.status == "success"
    assert scheduler._pending_notifications == []


def _noop_task(task_db, task_id, schedule):
    db = task_db()
    try:
        db.add(ScheduledTask(
            id=task_id, owner="alice", name=task_id, prompt="{}",
            task_type="action", action="tidy_sessions", trigger_type="schedule",
            schedule=schedule, scheduled_time="09:00",
            status="active", output_target="session",
        ))
        db.add(TaskRun(id=f"run-{task_id}", task_id=task_id, status="queued"))
        db.commit()
    finally:
        db.close()
    scheduler = TaskScheduler.__new__(TaskScheduler)
    scheduler._task_handles = {}
    scheduler._task_defer_counts = {}
    scheduler._pending_notifications = []
    return scheduler


async def _run_noop(scheduler, monkeypatch, task_id):
    from src.builtin_actions import TaskNoop

    async def _noop(task, run_id=None):
        raise TaskNoop("no new emails since watermark")

    monkeypatch.setattr(scheduler, "_execute_action", _noop, raising=False)
    await scheduler._execute_task_locked(
        task_id, f"run-{task_id}", gate_foreground=False, release_executing=False)


@pytest.mark.asyncio
async def test_a_no_op_on_a_task_that_keeps_running_says_nothing(
        task_db, configured_auth, monkeypatch):
    """`B112`'s decision, the quiet half. `skipped` is declared notifiable, but
    a housekeeping action reporting *"nothing to do"* recurs on every tick — a
    daily tidy with no new emails would toast every day forever. The rule is the
    task's own state, not a list of causes: this one is still scheduled, so
    nothing stopped and there is nothing to act on."""
    scheduler = _noop_task(task_db, "daily-tidy", "daily")
    await _run_noop(scheduler, monkeypatch, "daily-tidy")

    (run,) = _runs(task_db, "daily-tidy")
    assert run.status == "skipped"
    assert run.result == "no new emails since watermark"
    assert scheduler._pending_notifications == [], (
        "a task that will run again on its schedule is not a task that stopped")
    assert _task(task_db, "daily-tidy").next_run is not None


@pytest.mark.asyncio
async def test_a_no_op_on_a_task_that_will_not_run_again_is_told(
        task_db, configured_auth, monkeypatch):
    """The loud half, same rule. A one-shot that no-ops has produced nothing and
    will never come round again; the owner scheduled it for a reason and the
    Activity tab is the only place that would otherwise say so."""
    scheduler = _noop_task(task_db, "one-shot", "once")
    await _run_noop(scheduler, monkeypatch, "one-shot")

    (run,) = _runs(task_db, "one-shot")
    assert run.status == "skipped"
    assert _task(task_db, "one-shot").next_run is None
    (note,) = scheduler._pending_notifications
    assert note["status"] == "skipped"
    assert note["body"] == "no new emails since watermark"


@pytest.mark.asyncio
async def test_a_run_skipped_because_the_task_was_paused_mid_queue_is_reported(
        task_db, configured_auth):
    """The third `skipped` site, and the plainest case of the row's complaint:
    the run sat in the queue, somebody paused or deleted the task, and the run
    was filed `skipped` with the reason in `error` — where nothing looked at it
    unless the owner opened Activity. The task is not active, so by the same
    rule as the no-op above it will not run again and the owner is told."""
    db = task_db()
    try:
        db.add(ScheduledTask(
            id="paused-task", owner="alice", name="paused-task", prompt="{}",
            task_type="llm", trigger_type="schedule", schedule="daily",
            scheduled_time="09:00", status="paused", output_target="session",
        ))
        db.add(TaskRun(id="run-p", task_id="paused-task", status="queued"))
        db.commit()
    finally:
        db.close()

    scheduler = TaskScheduler.__new__(TaskScheduler)
    scheduler._task_handles = {}
    scheduler._task_defer_counts = {}
    scheduler._pending_notifications = []
    await scheduler._execute_task_locked(
        "paused-task", "run-p", gate_foreground=False, release_executing=False)

    (run,) = _runs(task_db, "paused-task")
    assert run.status == "skipped"
    (note,) = scheduler._pending_notifications
    assert note["status"] == "skipped"
    assert note["body"] == "Task no longer active (status=paused)"


@pytest.mark.asyncio
async def test_an_aborted_run_is_silent_because_the_policy_says_so(
        task_db, configured_auth, monkeypatch):
    """`B112`'s decision in the other direction, and the shape it had to take.

    `aborted` stays quiet — the restart sweep aborts every in-flight run on
    every boot and a foreground takeover re-queues this one 15 minutes later —
    but the branch ASKS and is told no, rather than returning before the notify
    block the way it did. The difference is invisible until the answer changes,
    so the second half of this test changes it: with `aborted` declared
    notifiable, the same branch emits. A branch that simply returned would stay
    silent both times.
    """
    from core.database import TASK_RUN_NOTIFY

    async def _drive(task_id):
        db = task_db()
        try:
            db.add(ScheduledTask(
                id=task_id, owner="alice", name=task_id, prompt="{}",
                task_type="action", action="tidy_sessions", trigger_type="schedule",
                schedule="daily", scheduled_time="09:00", status="active",
                output_target="session",
            ))
            db.add(TaskRun(id=f"run-{task_id}", task_id=task_id, status="queued"))
            db.commit()
        finally:
            db.close()

        scheduler = TaskScheduler.__new__(TaskScheduler)
        scheduler._task_handles = {}
        scheduler._task_defer_counts = {}
        scheduler._pending_notifications = []

        async def _stopped(task, run_id=None):
            raise asyncio.CancelledError()

        scheduler._execute_action = _stopped
        await scheduler._execute_task_locked(
            task_id, f"run-{task_id}", gate_foreground=False, release_executing=False)
        return scheduler

    scheduler = await _drive("abort-quiet")
    (run,) = _runs(task_db, "abort-quiet")
    assert run.status == "aborted"
    assert scheduler._pending_notifications == [], (
        "an abort fires on every restart; toasting it is the noise the row refused")

    # Same branch, one entry in the table flipped.
    monkeypatch.setitem(TASK_RUN_NOTIFY, "aborted", (True, "flipped for this test"))
    scheduler = await _drive("abort-loud")
    (note,) = scheduler._pending_notifications
    assert note["status"] == "aborted", (
        "the aborted branch does not consult the policy — the silence is an "
        "omission again, not a decision")
