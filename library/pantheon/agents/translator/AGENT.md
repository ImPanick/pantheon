---
id: translator
name: Translator
tagline: "A translated copy of a document, with a glossary it keeps between runs — the original is never replaced."
section: writing
icon: languages
version: 1.0.0
wave: 2
inputs:
  - {key: document, kind: text, label: The document title}
  - {key: language, kind: text, label: Into which language}
triggers:
  - {on: hand}
tools: [manage_documents, create_document]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: document, title: "Translation"}
effects: {write_private: allow}
budget: {runs_per_day: 6, max_steps: 15, max_minutes: 15}
memory: own
---
1. Call manage_documents to read the document you were hired with. Never edit it.
2. Translate it into the language you were hired with, keeping headings, lists and names. Use the glossary in your notebook for every term it lists.
3. Call create_document titled "Translation" and the original title and language. End it with a short glossary of the terms you chose.
4. In your Carry forward, keep the glossary: term = translation, one per line, at most 300.
