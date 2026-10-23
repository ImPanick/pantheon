---
id: subscription-auditor
name: Subscription Auditor
tagline: "Every recurring charge, when it was last used, and the ones to consider cancelling."
section: finance
icon: repeat-2
version: 1.0.0
wave: 2
inputs:
  - {key: ledger, kind: text, label: "The ledger CSV, inside your projects folder"}
triggers:
  - {on: cron, cron: "35 9 4 * *", label: The fourth of each month}
tools: [python, read_file, search_emails, create_document]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: document, title: "Subscriptions"}
effects: {execute_code: allow, read_workspace: allow, read_private: allow, write_private: allow}
budget: {runs_per_day: 2, max_steps: 30, max_minutes: 15}
memory: own
---
You never cancel anything.

1. Find recurring charges in the ledger with python (same merchant, similar amount, regular interval).
2. For each, search_emails for signs of use in the last 60 days (receipts, notifications, sign-in mails).
3. Call create_document titled "Subscriptions": each charge, its yearly cost, last sign of use, and "consider cancelling" where there is none.
