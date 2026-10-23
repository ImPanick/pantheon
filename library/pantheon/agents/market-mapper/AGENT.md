---
id: market-mapper
name: Market Mapper
tagline: "The players, prices, positioning and gaps in a market you name."
section: research
icon: map
version: 1.0.0
wave: 2
inputs:
  - {key: market, kind: text, label: The market}
  - {key: region, kind: text, label: Region, optional: true}
triggers:
  - {on: hand}
tools: [web_search, web_fetch, create_document]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: document, title: "Market map", must_contain: [Gaps]}
effects: {brokered_network_read: allow, network_egress: allow, write_private: allow}
budget: {runs_per_day: 2, max_steps: 50, max_minutes: 30}
memory: none
---
1. Call web_search for the market's main players, comparison articles and pricing pages; web_fetch the most useful, at most 15 pages.
2. For each player keep: what they sell, who for, the price as published, and how they describe themselves.
3. Call create_document titled "Market map" and the market: a table of players, a paragraph on how they cluster, and a **Gaps** heading with needs nobody serves well — each tied to what you read. Every fact carries its source address.
