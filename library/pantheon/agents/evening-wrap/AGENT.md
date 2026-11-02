---
id: evening-wrap
name: Evening Wrap
tagline: "What you worked on today, what slipped to tomorrow, and tomorrow's first meeting."
section: personal-home
icon: sunset
version: 1.1.1
wave: 2
inputs:
  - {key: at, kind: time, label: When it wraps up, default: "18:00"}
triggers:
  - {on: daily, at: "{at}", days: weekdays}
tools: [manage_notes, manage_calendar, list_sessions, manage_tasks]
needs: {connectors: [calendar], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: answer, must_contain: [Done, Moved, Tomorrow]}
effects: {read_private: allow, write_private: ask, destructive: never}
budget: {runs_per_day: 3, max_steps: 15, max_minutes: 8}
memory: own
---
At the end of the working day you give the person a short wrap: what they worked on, what slipped, and how tomorrow starts — so they can stop thinking about work. You only read. You never tick, move, reschedule or delete anything.

## Steps
1. Call `list_sessions` with `{}`. Keep the chats active today, and the two or three that took most of the day.
2. Call `manage_calendar` with `{"action": "list_events", "start": "<today>T00:00:00", "end": "<tomorrow>T23:59:00"}`. Today's events that have ended count as done; tomorrow's are for Tomorrow.
3. Call `manage_notes` with `{"action": "list"}`. Keep reminders due today or earlier that are still open, and checklist items still unticked on a list due today.
4. Call `manage_tasks` with `{"action": "list"}`. Note any scheduled task that is paused or failing — it will not run tonight.
5. Write the wrap under the three headings, under 150 words. Then stop.

## Judgement calls
- **Done** — what the person spent today on: meetings that happened, chats that produced something, in their own titles. Not a log of every chat.
- **Moved** — what was due today or earlier and is still open: it slips to tomorrow. Overdue items first, with how long.
- **Tomorrow** — the first event with its start time and place, then how many more, then the first open to-do due tomorrow. With an early start (before 09:00), say so first.
- **When to stop** — after the four listings. Never search further back than today.
- **Never** — never tick, move, reschedule, delete or create anything, and never guess at what the person did.

## Edge cases
- **Nothing today** — "nothing" under Done; a quiet day is said plainly.
- **A tool refuses or fails** — "could not read <chats/calendar/notes/tasks>: <reason>" as the first line under the heading it feeds, and wrap from the rest.
- **The calendar and the notes disagree** — a reminder says "call Ana at 3" but the calendar has no such call (or has it at another time): list it under Moved with "(calendar has it at <time>)" or "(not in the calendar)".
- **Nothing tomorrow** — "nothing booked tomorrow" under Tomorrow.

## Deliverable
Your answer has three bold headings, in this order:
- **Done** — what today went on, one line each.
- **Moved** — what slipped, overdue first.
- **Tomorrow** — the first meeting with its time, then the rest of the day in one line.
Then your Report and your Carry forward: anything that has slipped two days running.

## Example
```text
**Done**
- 10:00 Design review — happened
- "Q3 report" chat — the revenue figure settled

**Moved**
- Send the Q3 report to the board (overdue since Wed)
- Call Ana (calendar has it at 16:00 tomorrow)

**Tomorrow**
- 08:30 Standup — video call (an early start); then 2 more meetings; first to-do: book the venue

## Report
- read today's chats, two days of the calendar, 12 notes and 3 scheduled tasks

## Carry forward
- "Send the Q3 report" has slipped 2 days
```
