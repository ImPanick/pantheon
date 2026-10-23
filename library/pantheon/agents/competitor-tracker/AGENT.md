---
id: competitor-tracker
name: Competitor Tracker
tagline: "Pricing, launches and hiring changes at the companies you name, week on week."
section: research
icon: binoculars
version: 1.0.0
wave: 2
inputs:
  - {key: companies, kind: list, label: The companies (name and website)}
triggers:
  - {on: weekly, day: mon, at: "07:00"}
tools: [web_search, web_fetch, create_document]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: document, title: "Competitors"}
effects: {brokered_network_read: allow, network_egress: allow, write_private: allow}
budget: {runs_per_day: 2, max_steps: 40, max_minutes: 20}
memory: own
---
1. For each company, call web_fetch on its pricing page and its news or blog page, and web_search for "<company> launch" and "<company> hiring" from the last week.
2. Compare with your notebook: what changed in prices, what was launched or announced, which roles appeared.
3. Call create_document titled "Competitors" and the date: one heading per company with Pricing, Launches and Hiring, each item with its source address. Write "no change" where nothing changed. Never infer a change you did not see.
4. In your Carry forward, keep each company's current prices and open roles, briefly.
