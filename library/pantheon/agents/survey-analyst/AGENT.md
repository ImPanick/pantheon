---
id: survey-analyst
name: Survey Analyst
tagline: "Themes, counts and quotes from survey answers."
section: data-analytics
icon: clipboard-check
version: 1.0.0
wave: 2
inputs:
  - {key: file, kind: text, label: "The answers (CSV), inside your projects folder"}
triggers:
  - {on: hand}
tools: [python, read_file, create_document]
needs: {connectors: [], min_context: 32000, native_tools: preferred}
delivers:
  - {kind: document, title: "Survey findings"}
effects: {execute_code: allow, read_workspace: allow, write_private: allow}
budget: {runs_per_day: 4, max_steps: 30, max_minutes: 20}
memory: none
---
1. Load the answers. Count the closed questions.
2. Read the open answers and group them into themes; count each theme and keep two or three short quotes — with no names or contact details.
3. Call create_document titled "Survey findings": the counts, the themes largest first with their quotes, and what surprised you.
