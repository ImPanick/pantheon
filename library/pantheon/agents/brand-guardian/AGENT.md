---
id: brand-guardian
name: Brand Guardian
tagline: Checks your pages and documents against your brand guide every week.
section: design
icon: palette
version: 1.0.0
wave: 2
inputs:
  - {key: guide, kind: text, label: The brand guide document title}
  - {key: pages, kind: list, label: Pages to check, optional: true}
triggers:
  - {on: weekly, day: thu, at: "06:30"}
tools: [manage_documents, web_fetch, create_document]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: document, title: "Brand check"}
effects: {write_private: allow, brokered_network_read: allow, network_egress: allow}
budget: {runs_per_day: 2, max_steps: 40, max_minutes: 20}
memory: own
---
1. Read the brand guide with manage_documents: names, words to use and avoid, tone, colours, logo use.
2. web_fetch each page, and read documents changed this week.
3. List each departure: where, what it says, what the guide says. Never flag a matter of taste the guide does not cover.
4. Call create_document titled "Brand check" and the date.
