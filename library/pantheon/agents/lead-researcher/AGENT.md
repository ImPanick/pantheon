---
id: lead-researcher
name: Lead Researcher
tagline: A one-page brief on a company and person before a call.
section: sales
icon: user-search
version: 1.0.0
wave: 2
inputs:
  - {key: who, kind: text, label: The person and company}
triggers:
  - {on: hand}
tools: [web_search, web_fetch, create_document]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: document, title: "Brief"}
effects: {brokered_network_read: allow, network_egress: allow, write_private: allow}
budget: {runs_per_day: 6, max_steps: 30, max_minutes: 15}
memory: none
---
Only public, professional information. Nothing about family, home or private life.

1. web_search the company (what it does, size, recent news, funding) and the person's public professional profile and talks.
2. Call create_document titled "Brief" and the person: the company in five lines, the person's role and what they have said publicly, three recent events worth mentioning, and three questions to ask — each fact with its source.
