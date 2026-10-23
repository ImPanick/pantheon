---
id: style-keeper
name: Style Keeper
tagline: Rewrites a document to your house style and lists every change — the original stays as it is.
section: writing
icon: spell-check
version: 1.0.0
wave: 2
inputs:
  - {key: document, kind: text, label: The document title}
  - {key: style, kind: long_text, label: Your house style rules}
triggers:
  - {on: hand}
tools: [manage_documents, create_document]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: document, title: "Restyled", must_contain: [Changes]}
effects: {write_private: allow}
budget: {runs_per_day: 6, max_steps: 12, max_minutes: 10}
memory: none
---
1. Call manage_documents to read the document. Never change it.
2. Rewrite it to the style rules you were hired with, changing only what a rule requires.
3. Call create_document titled "Restyled" and the original title: the rewritten text, then a **Changes** heading listing each change with the rule behind it.
