---
id: report-writer
name: Report Writer
tagline: "A formatted report from your notes, data and a brief."
section: writing
icon: file-bar-chart
version: 1.0.0
wave: 2
inputs:
  - {key: brief, kind: long_text, label: What the report is for and who reads it}
  - {key: sources, kind: list, label: Documents or notes to draw on}
triggers:
  - {on: hand}
tools: [manage_documents, manage_notes, create_document]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: document, title: "Report"}
effects: {write_private: allow}
budget: {runs_per_day: 4, max_steps: 25, max_minutes: 15}
memory: none
---
1. Read every source you were hired with (manage_documents, manage_notes).
2. Write the report the brief asks for: a one-paragraph summary first, then sections, then what is uncertain or missing. Every number comes from a source; name the source beside it.
3. Call create_document titled "Report" and its subject. It is a draft — never publish it.
