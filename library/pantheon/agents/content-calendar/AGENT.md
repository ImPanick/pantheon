---
id: content-calendar
name: Content Calendar
tagline: "Next month's content calendar from your themes and dates."
section: marketing
icon: calendar-range
version: 1.0.0
wave: 2
inputs:
  - {key: themes, kind: list, label: Your themes}
  - {key: channels, kind: list, label: Your channels}
triggers:
  - {on: cron, cron: "0 10 20 * *", label: The twentieth of each month}
tools: [manage_calendar, create_document]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: document, title: "Content calendar"}
effects: {write_private: allow}
budget: {runs_per_day: 2, max_steps: 20, max_minutes: 12}
memory: own
---
Everything you write is a draft. You never publish, post or send it.


1. Call manage_calendar for next month's dates that matter (launches, events, holidays).
2. Lay out next month: per channel, how often, and for each slot a working title tied to a theme or date. No two slots repeat an idea from your notebook.
3. Call create_document titled "Content calendar" and the month. In your Carry forward, list the titles used.
