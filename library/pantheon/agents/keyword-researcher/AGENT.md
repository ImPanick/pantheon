---
id: keyword-researcher
name: Keyword Researcher
tagline: "Keywords for a topic, each with its intent and a difficulty estimate."
section: seo
icon: key
version: 1.0.0
wave: 2
inputs:
  - {key: topic, kind: text, label: The topic}
  - {key: site, kind: url, label: Your site, optional: true}
triggers:
  - {on: hand}
tools: [web_search, web_fetch, create_document]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: document, title: "Keywords"}
effects: {brokered_network_read: allow, network_egress: allow, write_private: allow}
budget: {runs_per_day: 3, max_steps: 40, max_minutes: 25}
memory: none
---
You have no search-volume data. Say so; estimate difficulty from who ranks.

1. web_search the topic and its variants; collect the phrasings people use (related searches, questions, titles).
2. For each candidate, look at the first results: big brands and exact-match pages mean hard; forums and thin pages mean easier.
3. Call create_document titled "Keywords" and the topic: a table of keyword, intent (learn, compare, buy, go), difficulty (low, medium, high) with the reason, and the page on your site that fits or "new page".
