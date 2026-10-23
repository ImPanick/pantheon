---
id: web-performance
name: Web Performance
tagline: "Core Web Vitals and bundle sizes for each page, worst first."
section: design
icon: zap
version: 1.0.0
wave: 2
inputs:
  - {key: pages, kind: list, label: Page addresses}
triggers:
  - {on: weekly, day: tue, at: "05:40"}
tools: [bash, create_document]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: document, title: "Web performance"}
effects: {execute_code: allow, write_private: allow}
budget: {runs_per_day: 2, max_steps: 30, max_minutes: 30}
memory: own
---
1. For each page, run Lighthouse in the workstation (`npx --yes lighthouse <url> --quiet --chrome-flags=--headless --output=json`).
2. Keep LCP, CLS, INP (or TBT), total bytes, and the three largest resources.
3. Call create_document titled "Web performance" and the date: pages worst first, last week's numbers beside (your notebook), and the single most useful fix per page.
4. In your Carry forward, keep each page's numbers.
