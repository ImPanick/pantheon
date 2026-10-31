---
name: schedule-recurring-work
description: Turn "every morning…" or "each Friday…" into a scheduled task instead of doing it once: pick the task type, convert the time to UTC, dry-run it, and confirm.
version: 1.0.0
category: core
tags: [schedule, scheduled, recurring, daily, weekly, monthly, every, morning, automate, automation, task, routine, cron, reminder, brief, job]
requires_toolsets: [manage_tasks]
status: published
confidence: 0.95
source: pantheon
---

## When to Use

The person wants something to happen on a schedule or after an event: "every morning summarise my email", "each Monday research X", "once a month tidy my documents", "after every new document…".

## Procedure

1. Pin down what runs, how often, at what time and timezone, and where the result should go. Ask for the time if it matters and was not given.
2. Choose `task_type`: `action` with an `action_name` when a built-in one fits (for example `daily_brief`, `summarize_emails`, `tidy_documents`); `research` for a recurring research question; otherwise `llm` with a self-contained `prompt` that will make sense with no chat around it.
3. Time: `trigger_type: schedule`, `schedule` (`once`, `daily`, `weekly`, `monthly`), `scheduled_time` as HH:MM in **UTC** — convert from the person's local time using the offset in the current date and time context — and `scheduled_day` for weekly (0 = Monday) or monthly (day of month). Event-driven: `trigger_type: event` with `trigger_event` and `trigger_count`.
4. `manage_tasks` `action: create` with a clear `name`.
5. `action: dry_run` with the new `task_id` to see what a run would do, and fix the task with `action: edit` if it is not what was meant.
6. Confirm in plain words: what it does, when it next runs in their local time, and where results appear. Offer `action: run` for a first run now.

## Pitfalls

- Doing the work once in the chat when they asked for it every day.
- Using local time in `scheduled_time` instead of UTC.
- An `llm` prompt that says "do the thing we discussed" — the task runs without this chat.

## Verification

- `manage_tasks` `action: list` shows the task with the intended schedule, and its dry run describes what the person asked for.
