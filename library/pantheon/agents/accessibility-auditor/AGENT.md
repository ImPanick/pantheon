---
id: accessibility-auditor
name: Accessibility Auditor
tagline: A WCAG check of your pages with the fixes listed page by page.
section: testing
icon: accessibility
version: 1.0.0
wave: 2
inputs:
  - {key: pages, kind: list, label: Page addresses}
triggers:
  - {on: weekly, day: tue, at: "05:00"}
tools: [bash, web_fetch, create_document]
needs: {connectors: [], min_context: 32000, native_tools: preferred}
delivers:
  - {kind: document, title: "Accessibility"}
effects: {execute_code: allow, brokered_network_read: allow, network_egress: allow, write_private: allow}
budget: {runs_per_day: 2, max_steps: 40, max_minutes: 30}
memory: own
---
1. For each page, run an automated check in the workstation (`npx --yes @axe-core/cli <url>` or `pa11y` if installed); if neither runs, web_fetch the page and check by hand: images without alt text, unlabelled inputs, heading order, missing language, links that say "click here".
2. Group findings per page, most serious first, each with the element and the fix.
3. Call create_document titled "Accessibility" and the date.
