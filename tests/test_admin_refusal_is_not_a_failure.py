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


@pytest.mark.asyncio
async def test_scheduler_refusal_notifies_nobody(task_db, configured_auth):
    """The refusal returns before the notification block, so nothing is queued.

    Pinned rather than fixed, and the reason is the client. `_pollTaskNotifications`
    in `static/js/tasks.js` (`:3433`, `:3458`) knows two statuses: `success` is "Task finished" and
    **everything else is "Task failed: <name>"** in a red error toast. Firing a
    `skipped` notification here would put the exact lie this row removes back on
    screen in a different surface. Filed as `B75`; this test is the marker that
    the gap is deliberate, so nobody closes it by adding a notification that says
    "failed".
    """
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

    assert scheduler._pending_notifications == []


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
