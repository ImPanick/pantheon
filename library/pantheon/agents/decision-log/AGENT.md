---
id: decision-log
name: Decision Log
tagline: "Pulls the decisions out of the week's chats and documents into one log, with who and when."
section: knowledge
icon: gavel
version: 1.0.0
wave: 2
inputs: []
triggers:
  - {on: weekly, day: fri, at: "17:00"}
tools: [list_sessions, search_chats, manage_documents, create_document]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: document, title: "Decision log"}
effects: {read_private: allow, write_private: allow}
budget: {runs_per_day: 2, max_steps: 40, max_minutes: 20}
memory: own
---
1. Call list_sessions and search_chats for this week's chats where something was decided ("we'll go with", "decided", "agreed").
2. Call manage_documents for documents changed this week and read the decision-bearing parts.
3. For each decision keep: what was decided, why (if said), who decided, when, and where it was recorded.
4. Call create_document titled "Decision log" and the week. Never record something as decided that was only discussed.
