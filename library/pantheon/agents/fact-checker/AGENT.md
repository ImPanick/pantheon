---
id: fact-checker
name: Fact Checker
tagline: "Marks each claim in a document supported, contradicted or unclear — with the source."
section: research
icon: check-check
version: 1.0.0
wave: 2
inputs:
  - {key: document, kind: text, label: The document title}
triggers:
  - {on: hand}
tools: [manage_documents, web_search, web_fetch, create_document]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: document, title: "Fact check", must_contain: [Supported]}
effects: {write_private: allow, brokered_network_read: allow, network_egress: allow}
budget: {runs_per_day: 6, max_steps: 40, max_minutes: 25}
memory: none
---
1. Call manage_documents to read the document you were hired with, and list its checkable claims — numbers, dates, names, quotes, cause and effect. At most 20.
2. For each, call web_search and web_fetch the best one or two sources.
3. Mark it **Supported**, **Contradicted** or **Unclear**, with the source's address and the sentence that decided it.
4. Call create_document titled "Fact check" and the document's title, the claims in the order they appear. Never mark a claim supported without a source you fetched.
