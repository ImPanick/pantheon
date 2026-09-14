# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared privilege policy for scheduled task actions."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone


def _utcnow() -> datetime:
    """Naive UTC, matching what every other task DB field stores."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


ADMIN_ONLY_TASK_ACTIONS = frozenset({
    "run_local",
    "run_script",
    "ssh_command",
    "cookbook_serve",
})


def is_admin_only_task_action(task_type: str | None, action: str | None) -> bool:
    return (task_type or "llm") == "action" and (action or "") in ADMIN_ONLY_TASK_ACTIONS


def owner_has_admin_task_privileges(owner: str | None) -> bool:
    try:
        from src.auth_helpers import _auth_disabled
        if _auth_disabled():
            return True
    except Exception:
        pass

    if owner:
        try:
            from core.middleware import INTERNAL_TOOL_USER
            if owner == INTERNAL_TOOL_USER:
                return True
        except Exception:
            pass

    try:
        from core.auth import AuthManager
        auth = AuthManager()
        if not auth.is_configured:
            return True
        if not owner:
            return False
        return bool(auth.is_admin(owner))
    except Exception:
        pass

    if not owner:
        return False

    return False


# The one sentence both refusal sites show. It is also the migration's join key
# (`core.database._migrate_reclassify_admin_refusals`), so it is a constant
# rather than two f-strings that can drift apart.
ADMIN_REFUSAL_SUFFIX = "requires admin privileges"


def admin_refusal_message(action: str | None) -> str:
    return f"Action '{action or ''}' {ADMIN_REFUSAL_SUFFIX}"


def record_admin_refusal(db, task, *, run_id: str | None = None) -> str:
    """Pause an admin-only task whose owner is not an admin, and file the
    refusal as a **`skipped`** run.

    Two things were wrong and both are `Law 13` — one rule, two recordings.

    `src/task_scheduler.py` wrote `status="error"`. The vocabulary block in
    `core/database.py` reserves `error` for *"the task itself failed"* and
    defines `skipped` as *"deliberately did not run… Not a failure"*, which is
    exactly this: the action never started. Every privilege refusal was
    counting against the task's error rate — the same corruption that block
    names for `aborted`.

    `routes/task/task_routes.py`'s webhook path applied the identical policy and
    wrote **no run row at all**, so a refusal arriving through a webhook was
    invisible in Activity: the task went from active to paused with nothing on
    screen explaining why. The 403 goes to whatever called the webhook, which is
    not the person who has to work out why their task stopped.

    `run_id` names an existing queued run to overwrite (the scheduler path,
    which created one before it got here); without it a fresh terminal run row
    is created (the webhook path, which has none). Commits — both callers want
    the refusal durable before they return or raise.
    """
    from core.database import TaskRun

    msg = admin_refusal_message(getattr(task, "action", None))
    now = _utcnow()

    run = None
    if run_id:
        run = db.query(TaskRun).filter(TaskRun.id == run_id).first()
    if run is None:
        run = TaskRun(id=str(uuid.uuid4()), task_id=task.id, started_at=now)
        db.add(run)
    run.status = "skipped"
    run.result = msg
    run.error = msg
    run.finished_at = now

    task.status = "paused"
    task.next_run = None
    task.last_run = now

    db.commit()
    return msg
