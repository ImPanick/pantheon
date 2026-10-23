---
id: content-gap-finder
name: Content Gap Finder
tagline: Topics your competitors cover and you do not.
section: seo
icon: puzzle
version: 1.0.0
wave: 2
inputs:
  - {key: site, kind: url, label: Your site}
  - {key: competitors, kind: list, label: Competitor sites}
triggers:
  - {on: cron, cron: "25 6 12 * *", label: The twelfth of each month}
tools: [web_fetch, web_search, create_document]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: document, title: "Content gaps"}
effects: {brokered_network_read: allow, network_egress: allow, write_private: allow}
budget: {runs_per_day: 2, max_steps: 50, max_minutes: 30}
memory: own
---
1. web_fetch each competitor's sitemap or blog index and your own; list their topics from page titles.
2. Match topics; keep the ones two or more competitors cover and you do not.
3. Call create_document titled "Content gaps" and the month: each gap, who covers it (addresses), and an angle you could take. In your Carry forward, list gaps already reported.
