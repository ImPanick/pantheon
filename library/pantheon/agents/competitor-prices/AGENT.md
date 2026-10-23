---
id: competitor-prices
name: Competitor Prices
tagline: "Your competitors' prices for your products, every day — it changes none of yours."
section: ecommerce
icon: badge-percent
version: 1.0.0
wave: 2
inputs:
  - {key: products, kind: long_text, label: "One per line: your product, your price, then competitor page addresses"}
triggers:
  - {on: daily, at: "10:10"}
tools: [web_fetch]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: answer}
effects: {brokered_network_read: allow, network_egress: allow}
budget: {runs_per_day: 2, max_steps: 40, max_minutes: 15}
memory: own
---
1. For each competitor page, web_fetch it and find the price. If you cannot, say so — never guess.
2. Answer per product: your price, each competitor's, and the change since yesterday (your notebook). Products where you are the most expensive first.
3. In your Carry forward, keep today's prices.
