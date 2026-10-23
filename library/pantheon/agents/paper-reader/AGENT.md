---
id: paper-reader
name: Paper Reader
tagline: "New papers on your topics: each one's method, result and limits in plain words."
section: research
icon: file-text
version: 1.0.0
wave: 2
inputs:
  - {key: topics, kind: list, label: Topics to watch}
triggers:
  - {on: weekly, day: fri, at: "07:00"}
tools: [web_search, web_fetch, create_document]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: document, title: "Papers"}
effects: {brokered_network_read: allow, network_egress: allow, write_private: allow}
budget: {runs_per_day: 2, max_steps: 40, max_minutes: 25}
memory: own
---
1. For each topic, call web_search for papers from the last week (arXiv and similar), at most five per topic. Skip any address in your notebook.
2. For each paper, call web_fetch on its abstract page and keep: title, authors, address, what they did, what they found, and the limits they state (or that you can see).
3. Call create_document titled "Papers" and the date, one heading per topic. Never state a result the abstract does not.
4. In your Carry forward, list the paper addresses you covered, newest first, at most 200.
