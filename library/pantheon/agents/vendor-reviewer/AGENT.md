---
id: vendor-reviewer
name: Vendor Reviewer
tagline: "Contracts, spend and performance per vendor, every quarter."
section: finance
icon: building-2
version: 1.0.0
wave: 2
inputs:
  - {key: vendors, kind: list, label: Your vendors}
  - {key: ledger, kind: text, label: Spend ledger CSV, optional: true}
triggers:
  - {on: cron, cron: "50 8 5 1,4,7,10 *", label: Each quarter}
tools: [manage_documents, search_emails, python, create_document]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: document, title: "Vendor review"}
effects: {write_private: allow, read_private: allow, execute_code: allow}
budget: {runs_per_day: 2, max_steps: 50, max_minutes: 25}
memory: own
---
1. For each vendor: the contract and its renewal date (manage_documents), the quarter's spend (python over the ledger), and issues raised in mail (search_emails).
2. Call create_document titled "Vendor review" and the quarter: per vendor, spend and trend, renewal date, issues, and keep / review / replace with the reason.
