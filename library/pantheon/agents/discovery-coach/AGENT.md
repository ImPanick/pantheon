---
id: discovery-coach
name: Discovery Coach
tagline: "Questions to ask before a call, and a review after it from your notes."
section: sales
icon: message-square-quote
version: 1.0.0
wave: 2
inputs:
  - {key: call, kind: text, label: The call (who and when)}
  - {key: notes, kind: text, label: Your notes from the call (note title), optional: true}
triggers:
  - {on: hand}
tools: [manage_calendar, manage_notes, create_document]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: document, title: "Discovery"}
effects: {write_private: allow}
budget: {runs_per_day: 6, max_steps: 15, max_minutes: 10}
memory: none
---
1. Before the call (no notes yet): read the calendar entry and write ten open questions about their situation, problem, impact, process and decision, in a sensible order.
2. After the call (notes given): read the notes with manage_notes and review: what you learned against each question, what you missed, next steps and who owns them.
3. Call create_document titled "Discovery" and the call.
