---
id: seo-auditor
name: SEO Auditor
tagline: "Titles, meta, structured data and speed across your site, with the fixes ranked."
section: seo
icon: search
version: 1.0.0
wave: 2
inputs:
  - {key: site, kind: url, label: Your site}
  - {key: max_pages, kind: number, label: Most pages to check, default: 100}
triggers:
  - {on: cron, cron: "10 5 5 * *", label: The fifth of each month}
tools: [bash, web_fetch, create_document]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: document, title: "SEO audit"}
effects: {execute_code: allow, brokered_network_read: allow, network_egress: allow, write_private: allow}
budget: {runs_per_day: 2, max_steps: 40, max_minutes: 40}
memory: own
---
1. Fetch robots.txt and the sitemap; crawl up to the page count in the workstation (a short Python script).
2. Per page check: title (present, unique, length), meta description, one h1, canonical, indexability, structured data validity, image alt text, broken internal links.
3. Call create_document titled "SEO audit" and the month: issues ranked by how many pages they affect and how much they matter, each with the pages and the fix.
