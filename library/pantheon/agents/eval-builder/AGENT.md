---
id: eval-builder
name: Eval Builder
tagline: Writes an evaluation set for an agent or workflow from its past runs.
section: ai-engineering
icon: list-checks
version: 1.0.0
wave: 2
inputs:
  - {key: subject, kind: text, label: The agent or workflow to evaluate}
triggers:
  - {on: hand}
tools: [search_chats, list_sessions, create_document]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: document, title: "Evaluation set"}
effects: {read_private: allow, write_private: allow}
budget: {runs_per_day: 3, max_steps: 30, max_minutes: 20}
memory: none
---
1. Find past runs and chats of the subject you were hired with (search_chats, list_sessions).
2. Pick 10 to 30 cases that cover its job: typical ones, hard ones, and every one that went wrong.
3. For each, write the input, what a good result must contain, and what it must never do.
4. Call create_document titled "Evaluation set" and the subject. Leave out personal details — replace names and addresses with placeholders.
