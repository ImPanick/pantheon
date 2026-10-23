---
id: evening-wrap
name: Evening Wrap
tagline: "What got done today, what moved to tomorrow, and tomorrow's first meeting."
section: personal-home
icon: sunset
version: 1.0.0
wave: 2
inputs:
  - {key: at, kind: time, label: When it wraps up, default: "18:00"}
triggers:
  - {on: daily, at: "{at}", days: weekdays}
tools: [manage_tasks, manage_calendar, list_sessions]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: answer, must_contain: [Done, Tomorrow]}
effects: {write_private: allow, read_private: allow}
budget: {runs_per_day: 3, max_steps: 15, max_minutes: 8}
memory: own
---
1. Call manage_tasks to list tasks completed today and tasks still open that were due today.
2. Call manage_calendar to list tomorrow's events.
3. Call list_sessions for today's chats and note the two or three subjects that took the most of the day.
4. Answer under three headings: **Done** (what was completed), **Moved** (what was due and is still open), **Tomorrow** (the first meeting with its time, then the rest of the day in one line). Never invent a task or an event.
