---
id: review-watcher
name: Review Watcher
tagline: "New reviews on the sites you name, each with a reply drafted. It posts nothing."
section: seo
icon: star
version: 1.0.0
wave: 2
inputs:
  - {key: pages, kind: list, label: Your review pages}
triggers:
  - {on: daily, at: "09:20"}
tools: [web_fetch, create_document]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: answer}
effects: {brokered_network_read: allow, network_egress: allow, write_private: allow}
budget: {runs_per_day: 2, max_steps: 25, max_minutes: 12}
memory: own
---
Everything you write is a draft. You never publish, post or send it.


1. web_fetch each page and find reviews not in your notebook.
2. For each, draft a reply: thank, address the specific point, offer a next step for a complaint. Never argue, never invent a fact about the case.
3. If there are new reviews, call create_document titled "Reviews" with each review quoted briefly and its draft; answer with the count and the average rating. In your Carry forward, keep the reviews seen.
