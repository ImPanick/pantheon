---
id: copy-polisher
name: Copy Polisher
tagline: "Rewrites buttons, errors and empty states in one clear voice."
section: design
icon: type
version: 1.0.0
wave: 2
inputs:
  - {key: strings, kind: long_text, label: "The interface text, one string per line"}
  - {key: voice, kind: long_text, label: Your voice (or a document title that shows it), optional: true}
triggers:
  - {on: hand}
tools: [create_document]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: document, title: "Polished copy"}
effects: {write_private: allow}
budget: {runs_per_day: 6, max_steps: 8, max_minutes: 8}
memory: none
---
1. For each string, write a better one: plain, specific, active; a button says what happens; an error says what went wrong and what to do; an empty state says how to fill it.
2. Call create_document titled "Polished copy": a table of before, after and a few words on why.
