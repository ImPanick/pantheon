---
id: breach-watch
name: Breach Watch
tagline: Checks your domains and addresses against public breach notices each week.
section: security
icon: shield-alert
version: 1.0.0
wave: 2
inputs:
  - {key: names, kind: list, label: Your domains and email addresses}
triggers:
  - {on: weekly, day: fri, at: "08:15"}
tools: [web_search, web_fetch]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: answer}
effects: {brokered_network_read: allow, network_egress: allow}
budget: {runs_per_day: 2, max_steps: 25, max_minutes: 12}
memory: own
---
1. For each name, web_search for breach and leak notices that mention it or its domain from the last weeks; web_fetch the credible ones (the company's own notice, established security news).
2. Never visit paste or leak sites and never download a leak.
3. Answer with each notice: what leaked, when, which of your names, the source address, and what to change. "Nothing new" otherwise. In your Carry forward, list the notices covered.
