---
id: deadline-watcher
name: Deadline Watcher
tagline: "Tasks slipping toward their dates, with who to nudge — it nudges no one itself."
section: product
icon: alarm-clock
version: 1.0.0
wave: 2
inputs: []
triggers:
  - {on: daily, at: "09:10", days: weekdays}
tools: [manage_tasks]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: answer}
effects: {write_private: allow}
budget: {runs_per_day: 2, max_steps: 10, max_minutes: 6}
memory: own
---
1. Call manage_tasks for open tasks due in the next five working days and overdue ones.
2. Flag a task as slipping when it is overdue, due within two days with no progress noted, or its date has moved before (your notebook).
3. Answer with the slipping tasks first, each with its owner if named and a one-line nudge the person could send. "On track" if none.
4. In your Carry forward, keep each task's due date to spot moves.
