---
id: morning-brief
name: Morning Brief
tagline: One page each morning — today's calendar, urgent mail, what is due, and what changed overnight.
section: personal-home
icon: sun
version: 1.0.0
wave: 1
starred: true
inputs:
  - {key: at, kind: time, label: When it arrives, default: "07:30"}
triggers:
  - {on: daily, at: "{at}"}
tools: [manage_calendar, list_emails, manage_notes, manage_tasks]
needs: {connectors: [], min_context: 12000, native_tools: preferred}
delivers:
  - {kind: answer, must_contain: [Today]}
effects: {read_private: allow}
budget: {runs_per_day: 3, max_steps: 15, max_minutes: 8}
memory: own
---
1. Call manage_calendar with list_events from now until the end of today.
2. Call list_emails, unread only, at most 20. Keep only the ones a person wrote to you.
3. Call manage_notes with list, and keep reminders and to-dos due today or overdue.
4. Call manage_tasks with list, and keep the tasks whose last run failed since yesterday.
5. Answer with four short sections, in this order:
   - **Today** — each event with its time.
   - **Mail that needs you** — sender and subject, at most eight.
   - **Due** — the notes and reminders.
   - **Overnight** — tasks that failed, and anything else that changed.
   Say "nothing" under a heading with nothing in it. No advice, no filler.
