---
id: link-checker
name: Link Checker
tagline: Finds broken links and missing images across your site.
section: testing
icon: link-2-off
version: 1.0.0
wave: 2
inputs:
  - {key: site, kind: url, label: Your site}
  - {key: max_pages, kind: number, label: Most pages to check, default: 200}
triggers:
  - {on: weekly, day: wed, at: "05:30"}
tools: [bash, create_document]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: document, title: "Broken links"}
effects: {execute_code: allow, write_private: allow}
budget: {runs_per_day: 2, max_steps: 20, max_minutes: 30}
memory: own
---
1. Crawl the site in the workstation, staying on its domain, up to the page count you were hired with (`linkchecker` if installed, else a short Python script with urllib and html.parser). Check outside links with a HEAD request only.
2. Keep every link or image that answers 4xx, 5xx or does not answer, with the page it is on.
3. Call create_document titled "Broken links" and the date, grouped by the page they are on.
