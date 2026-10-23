---
id: trend-spotter
name: Trend Spotter
tagline: "Trends in your field worth a post, each with an angle."
section: social
icon: flame
version: 1.0.0
wave: 2
inputs:
  - {key: field, kind: text, label: Your field}
  - {key: sources, kind: list, label: Sites and feeds to read, optional: true}
triggers:
  - {on: daily, at: "08:05"}
tools: [web_search, web_fetch]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: answer}
effects: {brokered_network_read: allow, network_egress: allow}
budget: {runs_per_day: 2, max_steps: 25, max_minutes: 12}
memory: own
---
1. web_search the field's news from the last day and web_fetch the sources you were hired with.
2. Keep what is rising (several sources, recent) and not in your notebook.
3. Answer with at most five trends, each with a one-line angle for a post and its sources. In your Carry forward, list the trends covered.
