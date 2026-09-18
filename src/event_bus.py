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

# `P8-23`. Each entry also declares WHAT THE TRIGGER HANDS THE TASK.
#
# `fire_event(name, owner)` was the entire payload until 2026-09-18, so a task
# triggered by `document_updated` ran with its own static prompt and no way to
# say **which** document — `B602`, filed the day `P8-30` added that event to the
# catalogue and made the gap visible in the picker. Four of the eight triggers
# were worth roughly what a timer was worth.
#
# `payload` is the field list, and `payload_summary` is the same fact in the
# English the picker shows, because the person choosing a trigger needs to know
# what they will be able to refer to before they write the prompt (`Law 15`).
#
# The declaration is load-bearing, not documentation: `build_trigger` keeps
# exactly these keys and drops anything else, so a producer that invents a
# ninth field cannot quietly start a second vocabulary of payload shapes
# (`Law 10`, `Law 14`). A declared field a producer does not pass is simply
# absent — the consumer sees a payload with fewer keys, never a fabricated one.
EVENT_CATALOGUE = (
    {"name": EVENT_SESSION_CREATED,
     "description": "Fires when a new chat session is created",
     "payload": ("session_id", "name"),
     "payload_summary": "the new chat's id and name"},
    {"name": EVENT_MESSAGE_SENT,
     "description": "Fires when a user sends a message",
     "payload": ("session_id", "text"),
     "payload_summary": "the chat's id and the message that was sent"},
    {"name": EVENT_DOCUMENT_CREATED,
     "description": "Fires when a document is created",
     "payload": ("document_id", "title"),
     "payload_summary": "the document's id and title"},
    {"name": EVENT_DOCUMENT_UPDATED,
     "description": "Fires when an existing document is edited",
     "payload": ("document_id", "title"),
     "payload_summary": "the document's id and title"},
    {"name": EVENT_MEMORY_ADDED,
     "description": "Fires when a memory is added",
     "payload": ("memory_id", "text"),
     "payload_summary": "the memory's id and what it says"},
    {"name": EVENT_RESEARCH_COMPLETED,
     "description": "Fires when a research report completes",
     "payload": ("session_id", "topic"),
     "payload_summary": "the research session's id and its topic"},
    {"name": EVENT_EMAIL_RECEIVED,
     "description": "Fires when new inbox mail is observed",
     "payload": ("account", "folder", "message_key"),
     "payload_summary": "the account, the folder and the message's id"},
    {"name": EVENT_SKILL_ADDED,
     "description": "Fires when a new skill is created",
     "payload": ("name",),
     "payload_summary": "the skill's name"},
)

EVENT_NAMES = tuple(entry["name"] for entry in EVENT_CATALOGUE)

EVENT_PAYLOAD_FIELDS = {
    entry["name"]: tuple(entry.get("payload") or ()) for entry in EVENT_CATALOGUE
}

# Where a trigger came from. Two values, and they are not interchangeable: a
# webhook body arrives from outside the machine over an unauthenticated route,
# an app event does not. `trigger_context_message` reads this.
TRIGGER_SOURCE_EVENT = "event"
TRIGGER_SOURCE_WEBHOOK = "webhook"

# The payload rides into a model prompt and into a run's step log, and both are
# things a person loads to read a summary. One field, then the whole envelope.
# Two caps and not one, because a single enormous field and forty small ones are
# different failures and only the second is bounded by a field limit.
TRIGGER_FIELD_MAX_CHARS = 2000
TRIGGER_MAX_CHARS = 6000

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


def _clip(value, limit: int = TRIGGER_FIELD_MAX_CHARS):
    """One payload field, small enough to put in a prompt and a row.

    Structure survives the cap: a parsed webhook body stays a dict as long as
    it fits, so a task can be told `data.json.issue.title` rather than handed
    a string it would have to parse a second time. Only an oversized one is
    flattened to truncated text, which is what "too big to keep" looks like on
    a wire that has to stay JSON.
    """
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        text = value.strip()
        return text[:limit].rstrip() + "\u2026" if len(text) > limit else text
    try:
        text = json.dumps(value, default=str)
    except (TypeError, ValueError):
        text = str(value)
    if len(text) <= limit:
        return value
    return text[:limit].rstrip() + "\u2026"


def build_trigger(source: str, name: str, data: Optional[dict] = None,
                  *, fields: Optional[tuple] = None) -> dict:
    """The envelope a trigger hands the run it starts.

    `P8-23`. One shape for both trigger kinds, because a task does not care
    whether the thing that fired it was an app event or a POST — it cares what
    it can name. `source` says which, `name` says what, `data` says which one.

    For an app event `fields` defaults to the catalogue's declaration for
    `name`, and anything outside it is dropped: the catalogue is the schema.
    The webhook passes its own `fields`, because a request body has no
    catalogue and its keys are fixed here instead.
    """
    allowed = EVENT_PAYLOAD_FIELDS.get(name, ()) if fields is None else tuple(fields)
    kept = {}
    for key in allowed:
        if not isinstance(data, dict) or key not in data:
            continue
        value = data.get(key)
        if value is None or value == "":
            continue
        kept[key] = _clip(value)
    if isinstance(data, dict):
        extra = sorted(set(data) - set(allowed))
        if extra:
            logger.debug("Trigger %r dropped undeclared field(s): %s", name, extra)
    return {
        "source": source,
        "event": name,
        "at": datetime.utcnow().isoformat() + "Z",
        "data": kept,
    }


def trigger_summary(trigger: Optional[dict]) -> str:
    """One line naming what fired a run, for the run's step log."""
    if not isinstance(trigger, dict):
        return ""
    source = trigger.get("source") or TRIGGER_SOURCE_EVENT
    name = trigger.get("event") or "?"
    data = trigger.get("data") if isinstance(trigger.get("data"), dict) else {}
    lead = f"Triggered by {name}" if source == TRIGGER_SOURCE_EVENT else f"Triggered by {source}"
    if not data:
        # Said out loud rather than left blank: "no payload" and "the payload
        # did not survive" look identical in an empty string, and the first is
        # the ordinary case for a trigger whose producer has nothing to name.
        return f"{lead} \u2014 no payload"
    parts = ", ".join(
        f"{k}={v if isinstance(v, str) else json.dumps(v, default=str)}"
        for k, v in data.items()
    )
    return _clip(f"{lead} \u2014 {parts}", TRIGGER_FIELD_MAX_CHARS)


def trigger_context_message(trigger: Optional[dict]) -> Optional[dict]:
    """The trigger payload as a message the model can read but not obey.

    `P8-23`. Wrapped, always, in the wrapper this repo already has
    (`src.prompt_security.untrusted_context_message`) rather than pasted into
    the prompt — three of the eight producers carry text an attacker can choose.
    A webhook body arrives on an UNAUTHENTICATED route where the token is the
    only credential, and `document_updated` is fired by the email MCP server
    merging a received draft into a document, so "which document" can be a title
    someone else wrote.

    That means the post-external blocked-effect gate arms for a run that has a
    payload: `messages_contain_external_untrusted_context` reads the
    `tool_gate_untrusted` marker this wrapper sets, so a privileged action after
    reading the payload needs an approval the scheduled run cannot give and the
    run reports the boundary instead of taking it. That is the `FORBIDDEN.md`
    Part 2 control working, not a limitation of this row — and it is why the
    payload is data the task can name rather than instructions it follows.

    Returns `None` when there is nothing to say, so a run with no trigger
    payload builds byte-identical messages to the ones it built before this row.
    """
    if not isinstance(trigger, dict):
        return None
    body = trigger_as_text(trigger)
    if not body:
        return None
    from src.prompt_security import untrusted_context_message

    source = trigger.get("source") or TRIGGER_SOURCE_EVENT
    name = trigger.get("event") or "?"
    label = (f"webhook request that triggered this task"
             if source == TRIGGER_SOURCE_WEBHOOK
             else f"{name} event that triggered this task")
    return untrusted_context_message(
        label, body, provenance_origin="external", arm_tool_gate=True,
    )


def trigger_as_text(trigger: Optional[dict]) -> str:
    """The payload as the body of an untrusted-source block, capped."""
    if not isinstance(trigger, dict):
        return ""
    try:
        text = json.dumps(trigger, indent=2, default=str, sort_keys=True)
    except (TypeError, ValueError):
        return ""
    if len(text) > TRIGGER_MAX_CHARS:
        text = text[:TRIGGER_MAX_CHARS].rstrip() + "\n\u2026 (truncated)"
    return text


def set_task_scheduler(scheduler):
    """Wire up the scheduler reference (called from app.py on startup)."""
    global _task_scheduler
    _task_scheduler = scheduler


def get_task_scheduler():
    """Return the current task scheduler instance."""
    return _task_scheduler


def fire_event(event_name: str, owner: Optional[str] = None,
               payload: Optional[dict] = None):
    """Fire an event — increments counters and triggers tasks that hit threshold.

    Safe to call from both sync and async contexts.

    `P8-23`. `payload` names the thing that happened — the document, the
    memory, the message. It is optional and defaults to nothing, so every
    caller that has not been given one keeps working exactly as before
    (`Law 1`); a caller that passes one gets it filtered to the catalogue's
    declared fields for this event and handed to whatever task fires.
    """
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_handle_event(event_name, owner, payload))
    except RuntimeError:
        # No running loop — run in a new one (shouldn't happen in FastAPI)
        asyncio.run(_handle_event(event_name, owner, payload))


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


async def _handle_event(event_name: str, owner: Optional[str] = None,
                        payload: Optional[dict] = None):
    """Process an event: increment counters, fire tasks that hit their threshold."""
    from core.database import SessionLocal, ScheduledTask

    resolved_owner = _resolve_event_owner(owner)
    trigger = build_trigger(TRIGGER_SOURCE_EVENT, event_name, payload)
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
                    # `P8-23`. The Nth event is the one the task runs for, so
                    # that is the payload it is handed. The N-1 events that only
                    # moved the counter are not carried: a task set to fire every
                    # fifth document wants the fifth document, and a list of five
                    # would be a different feature nobody asked for.
                    await _task_scheduler.run_task_now(task.id, trigger=trigger)
                else:
                    logger.warning(f"Event triggered task '{task.name}' but no scheduler available")
            else:
                db.commit()
                logger.debug(f"Event '{event_name}': task '{task.name}' counter {task.trigger_counter}/{threshold}")

    except Exception:
        logger.exception(f"Error handling event '{event_name}'")
    finally:
        db.close()
