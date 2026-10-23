---
id: ai-visibility-check
name: AI Visibility Check
tagline: "What assistants and search engines say about you, month on month."
section: seo
icon: sparkles
version: 1.0.0
wave: 2
inputs:
  - {key: name, kind: text, label: Your name or brand}
  - {key: questions, kind: list, label: Questions people ask that should mention you}
triggers:
  - {on: cron, cron: "45 7 8 * *", label: The eighth of each month}
tools: [web_search, chat_with_model, create_document]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: document, title: "AI visibility"}
effects: {brokered_network_read: allow, network_egress: allow, write_private: allow}
budget: {runs_per_day: 2, max_steps: 40, max_minutes: 20}
memory: own
---
1. For each question, web_search it and note whether and where you appear; ask it to each model available through chat_with_model and note whether the answer mentions you and whether what it says is right.
2. Call create_document titled "AI visibility" and the month: per question, search position and each model's mention (yes, no, wrong), with last month's beside (your notebook), and what is wrong that you could correct on your own site.
3. In your Carry forward, keep the per-question results.
