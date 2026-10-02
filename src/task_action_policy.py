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


def document_steps(graph) -> list:
    """Every step of a parsed workflow document, each For-each followed by the
    step it repeats (`P22-12`) — the steps whose privileges a workflow needs.
    One walk for every door that asks (`Law 7`, `integrate-d`)."""
    from src.workflow_document import NODE_KIND_FOREACH

    out = []
    for node in (graph or {}).get("nodes") or ():
        if not isinstance(node, dict):
            continue
        out.append(node)
        inner = (node.get("config") or {}).get("step") if node.get("kind") == NODE_KIND_FOREACH else None
        if isinstance(inner, dict):
            out.append(inner)
    return out


def admin_only_action_in(graph) -> str | None:
    """The first Action step — or step a For-each repeats — whose action only
    an admin may schedule (`ADMIN_ONLY_TASK_ACTIONS`, asked through
    `is_admin_only_task_action`, so a step is refused exactly where a task with
    that action is). The save door's question (`workflow_store.check_document`)
    and the first half of `admin_only_action_of`'s."""
    from src.workflow_document import NODE_KIND_ACTION

    for node in document_steps(graph):
        config = node.get("config") if isinstance(node.get("config"), dict) else {}
        if node.get("kind") == NODE_KIND_ACTION and is_admin_only_task_action(
                NODE_KIND_ACTION, config.get("action")):
            return config.get("action")
    return None


def admin_only_action_of(db, task) -> str | None:
    """The admin-only action this task would run, or `None`. `P22-05`.

    One question for every door that asks it — the scheduler before a run (and
    before a dry run), the task route before a save, the webhook before a
    trigger: the task's own action, or, for a workflow's trigger
    (`task_type="workflow"`), any Action step in its document and the action
    of any task a Run task step runs. A workflow is not a way round
    `ADMIN_ONLY_TASK_ACTIONS` (`FORBIDDEN.md` Part 1; the privilege check
    itself is `owner_has_admin_task_privileges`, unchanged).

    A document that cannot be read answers `None` here: the walker refuses it
    at run with its own sentence, and nothing in it runs.

    `P22-12` / `P22-13` / `P22-14` (`B1097`, closed by `integrate-d`).
    The step a For-each repeats is asked too, and so are the two kinds only an
    admin's agent may run (`workflow_document.ADMIN_ONLY_KINDS`, one rule with
    the save's `admin_only`): an HTTP step answers the tool it calls through,
    `api_call`, and an MCP step its tool's qualified name — so a non-admin's
    workflow holding one is paused with a `skipped` run, as an admin-only
    Action step is, instead of failing at run with the document's sentence.
    """
    if task is None:
        return None
    if is_admin_only_task_action(getattr(task, "task_type", None), getattr(task, "action", None)):
        return task.action
    if (getattr(task, "task_type", None) or "llm") != "workflow":
        return None
    from core.database import ScheduledTask, Workflow
    from src.workflow_document import (
        ADMIN_ONLY_KINDS, NODE_KIND_HTTP, NODE_KIND_RUN_TASK, DocumentError, parse_graph,
    )
    from src.workflow_slots import API_CALL_TOOL

    wf = db.query(Workflow).filter(Workflow.task_id == task.id).first()
    if wf is None:
        return None
    try:
        graph = parse_graph(wf.graph)
    except DocumentError:
        return None
    found = admin_only_action_in(graph)
    if found:
        return found
    targets = []
    for node in document_steps(graph):
        kind = node.get("kind")
        config = node.get("config") if isinstance(node.get("config"), dict) else {}
        if kind in ADMIN_ONLY_KINDS:
            tool = API_CALL_TOOL if kind == NODE_KIND_HTTP else config.get("tool")
            return str(tool or kind)
        if kind == NODE_KIND_RUN_TASK and isinstance(config.get("task_id"), str):
            targets.append(config["task_id"])
    if targets:
        for row in db.query(ScheduledTask).filter(ScheduledTask.id.in_(targets)).all():
            if is_admin_only_task_action(row.task_type, row.action):
                return row.action
    return None


def record_admin_refusal(db, task, *, run_id: str | None = None,
                         action: str | None = None) -> str:
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

    `P22-05`. `action` names the refused action when it is not the task's own
    — a workflow's Action step (`admin_only_action_of`). The message still
    ends in `ADMIN_REFUSAL_SUFFIX`, the migration's join key.
    """
    from core.database import TaskRun

    msg = admin_refusal_message(action or getattr(task, "action", None))
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
