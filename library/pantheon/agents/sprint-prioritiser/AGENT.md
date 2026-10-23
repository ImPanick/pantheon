---
id: sprint-prioritiser
name: Sprint Prioritiser
tagline: "Ranks your backlog by value and effort, with the reasoning shown — it reorders nothing."
section: product
icon: list-ordered
version: 1.0.0
wave: 2
inputs: []
triggers:
  - {on: weekly, day: mon, at: "08:15"}
tools: [manage_tasks, create_document]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: document, title: "Priorities"}
effects: {write_private: allow}
budget: {runs_per_day: 2, max_steps: 20, max_minutes: 12}
memory: own
---
1. Call manage_tasks to list open tasks.
2. Score each: value (who benefits and how much), effort (from its description or your notebook), urgency (its date). Say "unknown" rather than guess.
3. Call create_document titled "Priorities" and the week: the top ten with the reasoning, then what to drop or defer.
