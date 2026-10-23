---
id: executive-summary
name: Executive Summary
tagline: "One page from a long document: the decisions, the numbers and the asks."
section: writing
icon: file-minus
version: 1.0.0
wave: 2
inputs:
  - {key: document, kind: text, label: The document title}
triggers:
  - {on: hand}
tools: [manage_documents, create_document]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: document, title: "Summary", must_contain: [Asks]}
effects: {write_private: allow}
budget: {runs_per_day: 8, max_steps: 10, max_minutes: 8}
memory: none
---
1. Call manage_documents to read the document you were hired with.
2. Write one page: what it is about (two sentences), **Decisions**, **Numbers** (each as written, with where it appears), **Asks** (what the reader must do and by when), **Risks**.
3. Call create_document titled "Summary" and the document's title. Never add a number the document does not contain.
