---
id: rank-tracker
name: Rank Tracker
tagline: "Where your pages rank for your terms, week on week."
section: seo
icon: trending-up
version: 1.0.0
wave: 2
inputs:
  - {key: site, kind: url, label: Your site}
  - {key: terms, kind: list, label: Search terms}
triggers:
  - {on: weekly, day: mon, at: "06:45"}
tools: [web_search]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: answer}
effects: {brokered_network_read: allow}
budget: {runs_per_day: 2, max_steps: 40, max_minutes: 15}
memory: own
---
Results through a search API differ from a person's; treat positions as an indication.

1. For each term, web_search it and find the first result on your site's domain, within the first 30.
2. Answer with a table: term, position (or "not in top 30"), last week's (your notebook), and the change. Biggest moves first.
3. In your Carry forward, keep each term's position.
