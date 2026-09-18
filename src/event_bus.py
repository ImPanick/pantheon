# SPDX-License-Identifier: AGPL-3.0-or-later
"""
event_bus.py

Lightweight event bus for triggering automation tasks based on events
like session creation, message sends, etc.
"""

import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Optional

from src.constants import AUTH_FILE

logger = logging.getLogger(__name__)

# `P8-30`. THE catalogue of trigger events. There is no second one.
#
# There used to be two enumerations of this list — the `/meta/events` route and
# the `manage_tasks` tool schema — and a scatter of loose strings beside them:
# five in `HOUSEKEEPING_DEFAULTS` and two in the email MCP server. Because the
# loose strings were not a catalogue, nobody reconciled them against one, and
# `document_updated` ended up fired in production (`mcp_servers/email_server.py`,
# on an email draft being merged into an existing document) while appearing in
# neither enumeration. The picker never offered it and the tool schema rejected
# it, so no task could ever trigger on a document being updated.
#
# The rule a registry is for: **an event that can be fired is an event that can
# be chosen.** `tests/test_event_catalogue.py` holds it by walking every
# `fire_event(...)` call site in the tree, rather than against a list written
# out a second time (`Law 13`, `Law 14`).
#
# `FORBIDDEN.md` Part 1: these names are stored in `ScheduledTask.trigger_event`.
# Renaming one silently disables every task using it. Adding is fine; renaming
# is not. The module constants exist so the rest of the tree references a name
# instead of respelling a string.
EVENT_SESSION_CREATED = "session_created"
EVENT_MESSAGE_SENT = "message_sent"
EVENT_DOCUMENT_CREATED = "document_created"
EVENT_DOCUMENT_UPDATED = "document_updated"
EVENT_MEMORY_ADDED = "memory_added"
EVENT_RESEARCH_COMPLETED = "research_completed"
EVENT_EMAIL_RECEIVED = "email_received"
EVENT_SKILL_ADDED = "skill_added"

EVENT_CATALOGUE = (
    {"name": EVENT_SESSION_CREATED,
     "description": "Fires when a new chat session is created"},
    {"name": EVENT_MESSAGE_SENT,
     "description": "Fires when a user sends a message"},
    {"name": EVENT_DOCUMENT_CREATED,
     "description": "Fires when a document is created"},
    {"name": EVENT_DOCUMENT_UPDATED,
     "description": "Fires when an existing document is edited"},
    {"name": EVENT_MEMORY_ADDED,
     "description": "Fires when a memory is added"},
    {"name": EVENT_RESEARCH_COMPLETED,
     "description": "Fires when a research report completes"},
    {"name": EVENT_EMAIL_RECEIVED,
     "description": "Fires when new inbox mail is observed"},
    {"name": EVENT_SKILL_ADDED,
     "description": "Fires when a new skill is created"},
)

EVENT_NAMES = tuple(entry["name"] for entry in EVENT_CATALOGUE)

# `P8-31`. How many events an event-triggered task waits for when nobody says.
#
# One, because that is what "trigger on document created" means to anyone
# arriving from a workflow tool, and because it is what this module has always
# done with a null: `threshold = task.trigger_count or DEFAULT_TRIGGER_COUNT`.
# What was missing was anywhere that agreed with it — `POST /api/tasks`
# **refused** a task that omitted the count, and the only reason people did not
# hit that 400 was a form pre-filling 5. A number nobody chose, in front of an
# API with no opinion, over a bus that already meant 1.
DEFAULT_TRIGGER_COUNT = 1

_task_scheduler = None


def set_task_scheduler(scheduler):
    """Wire up the scheduler reference (called from app.py on startup)."""
    global _task_scheduler
    _task_scheduler = scheduler


def get_task_scheduler():
    """Return the current task scheduler instance."""
    return _task_scheduler


def fire_event(event_name: str, owner: Optional[str] = None):
    """Fire an event — increments counters and triggers tasks that hit threshold.

    Safe to call from both sync and async contexts.
    """
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_handle_event(event_name, owner))
    except RuntimeError:
        # No running loop — run in a new one (shouldn't happen in FastAPI)
        asyncio.run(_handle_event(event_name, owner))


def _resolve_event_owner(owner: Optional[str]) -> Optional[str]:
    """Resolve ownerless app events to the primary configured user.

    Some event sources run from localhost/internal code paths where request
    middleware is not present, so they cannot pass a username. Treating that as
    "all owners" made built-in tasks run once per account. Instead, route those
    events to the first admin account, matching the legacy-owner migration.
    """
    owner = (owner or "").strip()
    if owner:
        return owner

    try:
        auth_path = AUTH_FILE
        with open(auth_path, "r", encoding="utf-8") as f:
            users = (json.load(f).get("users") or {})
        for username, data in users.items():
            if data.get("is_admin") is True:
                return username
        if users:
            return next(iter(users))
    except Exception:
        logger.debug("Could not resolve ownerless event owner", exc_info=True)
    return None


async def _handle_event(event_name: str, owner: Optional[str] = None):
    """Process an event: increment counters, fire tasks that hit their threshold."""
    from core.database import SessionLocal, ScheduledTask

    resolved_owner = _resolve_event_owner(owner)
    db = SessionLocal()
    try:
        filters = [
            ScheduledTask.trigger_type == "event",
            ScheduledTask.trigger_event == event_name,
            ScheduledTask.status == "active",
        ]
        if resolved_owner:
            filters.append(ScheduledTask.owner == resolved_owner)
        else:
            filters.append(ScheduledTask.owner == None)  # noqa: E711

        tasks = db.query(ScheduledTask).filter(*filters).all()
        if not tasks:
            return

        for task in tasks:
            threshold = task.trigger_count or DEFAULT_TRIGGER_COUNT
            task.trigger_counter = (task.trigger_counter or 0) + 1

            if task.trigger_counter >= threshold:
                task.trigger_counter = 0
                # Persist the trigger before handing off to the in-memory
                # scheduler. If the process restarts while the task is queued
                # behind a model call, `next_run <= now` makes the trigger
                # survive reboot instead of losing the event after the counter
                # has already reset.
                task.next_run = datetime.utcnow()
                db.commit()
                # Fire the task
                if _task_scheduler:
                    logger.info(f"Event '{event_name}' triggered task '{task.name}' (every {threshold})")
                    await _task_scheduler.run_task_now(task.id)
                else:
                    logger.warning(f"Event triggered task '{task.name}' but no scheduler available")
            else:
                db.commit()
                logger.debug(f"Event '{event_name}': task '{task.name}' counter {task.trigger_counter}/{threshold}")

    except Exception:
        logger.exception(f"Error handling event '{event_name}'")
    finally:
        db.close()
