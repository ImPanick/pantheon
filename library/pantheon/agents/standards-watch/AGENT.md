---
id: standards-watch
name: Standards Watch
tagline: "New filings, regulations and standard revisions in your field, monthly."
section: research
icon: landmark
version: 1.0.0
wave: 2
inputs:
  - {key: field, kind: text, label: Your field}
  - {key: bodies, kind: list, label: "Regulators and standards bodies to watch", optional: true}
triggers:
  - {on: cron, cron: "15 8 2 * *", label: The second of each month}
tools: [web_search, web_fetch, create_document]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: document, title: "Standards watch"}
effects: {brokered_network_read: allow, network_egress: allow, write_private: allow}
budget: {runs_per_day: 2, max_steps: 40, max_minutes: 25}
memory: own
---
1. For the field and bodies you were hired with, call web_search for new regulations, consultations, standards revisions and guidance from the last month. Skip addresses in your notebook.
2. web_fetch each candidate and keep: who issued it, what it changes, who it affects, and any date it takes effect.
3. Call create_document titled "Standards watch" and the month, soonest effective date first. This is information, not legal advice — say so in one line at the top.
4. In your Carry forward, list the addresses covered.
