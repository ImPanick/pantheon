# SPDX-License-Identifier: AGPL-3.0-or-later
"""The assistant's words for workflows (`B1875`, `B1878`).

A workflow is built in the Workbench (Automations) and run by the scheduler's
walker; the assistant reaches it through `manage_tasks` (`draft_workflow`,
`run`, `dry_run`) and `manage_workflows` (`B1878`). Everything here SAYS what
the store and the engine already decided — when a start fires, what a draft
changed, where a step sends things — in the sentences the Workbench shows, so
the assistant and the page cannot tell the person two different things
(`Law 7`). Nothing here decides anything.
"""

from __future__ import annotations

_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def start_words(trigger) -> str:
    """When a workflow's start (its trigger task) fires, as a person says it:
    "daily at 09:00 (Europe/Berlin)", "when its webhook is called", "only when
    you run it". A schedule names its zone, or UTC when it has none — the
    scheduler reads a time with no zone as UTC (`compute_next_run`)."""
    if trigger is None:
        return "never: it has no start"
    kind = getattr(trigger, "trigger_type", None) or "schedule"
    if kind == "manual":
        return "only when you run it"
    if kind == "webhook":
        return "when its webhook is called"
    if kind == "event":
        event = getattr(trigger, "trigger_event", None) or "an event"
        count = getattr(trigger, "trigger_count", None) or 1
        return (f"on every {count} “{event}” events" if count > 1
                else f"each time “{event}” happens")
    schedule = getattr(trigger, "schedule", None) or "daily"
    at = getattr(trigger, "scheduled_time", None) or "09:00"
    day = getattr(trigger, "scheduled_day", None)
    zone = getattr(trigger, "tz_name", None) or "UTC"
    if schedule == "cron":
        return f"on the cron schedule “{getattr(trigger, 'cron_expression', None) or '?'}” ({zone})"
    if schedule == "weekly" and isinstance(day, int) and 0 <= day <= 6:
        when = f"every {_WEEKDAYS[day]} at {at}"
    elif schedule == "monthly" and isinstance(day, int):
        when = f"monthly on day {day} at {at}"
    elif schedule == "once":
        date = getattr(trigger, "scheduled_date", None)
        when = f"once, on {date:%Y-%m-%d} at {at}" if date is not None else f"once, at {at}"
    else:
        when = f"daily at {at}"
    return f"{when} ({zone})"


def drafted_reply(drafted) -> str:
    """`B1875`. What `manage_tasks draft_workflow` answers the model with: the
    sentence it always had, then what the Workbench's *Describe it* shows
    beside the draft — when it starts, the drafter's notes, where it sends
    things, and what was not drafted.

    Two of the notes stay out: "Made …" (the first sentence says it), and the
    webhook's address, which carries its secret token — a trigger anybody
    holding it can ring. The person reads it on the start in the Workbench;
    a chat transcript is no place for it."""
    from src.workflow_store import nodes_of, stored_graph, webhook_path
    wf, trigger = drafted.wf, drafted.trigger
    count = len(nodes_of(stored_graph(wf)))
    said = (f"Drafted “{wf.name}” as a workflow of {count} "
            f"step{'s' if count != 1 else ''}, switched off. A person checks each "
            f"step in the Workbench before it can run (Automations → "
            f"“{wf.name}”), and switches it on there.")
    if (getattr(trigger, "trigger_type", None) or "schedule") == "webhook":
        said += (f" It starts {start_words(trigger)}; its address is on the start in the "
                 f"Workbench.")
    else:
        said += f" It starts {start_words(trigger)}."
    address = webhook_path(trigger) if trigger is not None else None
    notes = [str(n) for n in (drafted.notes or ())
             if n and not str(n).startswith("Made ") and not (address and address in str(n))]
    if notes:
        said += " " + " ".join(notes)
    if drafted.destinations:
        said += " Where it sends things: " + " ".join(str(d) for d in drafted.destinations)
    if drafted.missing:
        said += " Not drafted: " + " ".join(str(m) for m in drafted.missing)
    return said
