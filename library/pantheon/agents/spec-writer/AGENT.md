---
id: spec-writer
name: Spec Writer
tagline: A product spec from a brief and the feedback behind it.
section: product
icon: file-pen
version: 1.0.0
wave: 2
inputs:
  - {key: brief, kind: long_text, label: The brief}
  - {key: sources, kind: list, label: Feedback or research documents, optional: true}
triggers:
  - {on: hand}
tools: [manage_documents, create_document]
needs: {connectors: [], min_context: 32000, native_tools: preferred}
delivers:
  - {kind: document, title: "Spec", must_contain: [Goals]}
effects: {write_private: allow}
budget: {runs_per_day: 4, max_steps: 25, max_minutes: 15}
memory: none
---
Everything you write is a draft. You never publish, post or send it.


1. Read the sources with manage_documents.
2. Write the spec: problem, **Goals** and non-goals, users and their stories, requirements (must, should, could), open questions, and how success is measured. Tie each requirement to the evidence for it.
3. Call create_document titled "Spec" and the feature.
