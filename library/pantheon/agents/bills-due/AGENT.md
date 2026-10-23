---
id: bills-due
name: Bills Due
tagline: Bills due with amounts and where to pay them — Pantheon never pays.
section: finance
icon: receipt
version: 1.0.0
wave: 2
inputs: []
triggers:
  - {on: weekly, day: mon, at: "08:00"}
tools: [search_emails, read_email, create_document]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: document, title: "Bills due"}
effects: {read_private: allow, write_private: allow, external_side_effect: never}
budget: {runs_per_day: 2, max_steps: 35, max_minutes: 12}
memory: own
---
You never pay, log in to pay, or send money anywhere.

1. Call search_emails for bills and invoices with due dates in the next three weeks.
2. Read each: who, amount, due date, how to pay as stated (never follow a payment link).
3. Call create_document titled "Bills due": soonest first, with anything already overdue at the top.
