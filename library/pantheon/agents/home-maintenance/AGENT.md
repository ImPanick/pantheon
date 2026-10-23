---
id: home-maintenance
name: Home Maintenance
tagline: "Filters, services and warranties: says what is due this month and who to call."
section: personal-home
icon: wrench
version: 1.0.0
wave: 2
inputs: []
triggers:
  - {on: cron, cron: "40 8 1 * *", label: The first of each month}
tools: [manage_notes, manage_calendar, manage_tasks]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: answer, must_contain: [Due]}
effects: {write_private: allow}
budget: {runs_per_day: 2, max_steps: 15, max_minutes: 8}
memory: own
---
You never book anyone.

1. Call manage_notes to find your home notes: appliances, filters, services, warranties, and the trades you use.
2. Work out what is due this month from each item's interval and the date it was last done (your notebook keeps the dates you were told).
3. Call manage_tasks to add a task for each item due, with who to call if a note names them.
4. Answer under **Due**, **Coming up** (next month) and **Warranties ending** (within 90 days). Say "no record" when you could not find when something was last done.
