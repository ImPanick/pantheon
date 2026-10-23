---
id: local-news-digest
name: Local News Digest
tagline: "Town, school and council news worth knowing, every morning."
section: research
icon: newspaper
version: 1.0.0
wave: 2
inputs:
  - {key: place, kind: text, label: Your town or area}
  - {key: sources, kind: list, label: Local sites to read, optional: true}
  - {key: at, kind: time, label: When it arrives, default: "07:15"}
triggers:
  - {on: daily, at: "{at}"}
tools: [web_search, web_fetch]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: answer}
effects: {brokered_network_read: allow, network_egress: allow}
budget: {runs_per_day: 2, max_steps: 25, max_minutes: 12}
memory: own
---
1. web_fetch each source you were hired with, and call web_search for the place's news from the last day.
2. Keep what is local and useful: council decisions, schools, roads and transport, safety, events. Skip national news, adverts and anything in your notebook.
3. Answer with at most eight items, each one sentence and its source address; "Nothing new" if nothing qualifies.
4. In your Carry forward, list the addresses covered, at most 150.
