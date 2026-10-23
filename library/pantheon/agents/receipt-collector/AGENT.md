---
id: receipt-collector
name: Receipt Collector
tagline: Files receipts and invoices from your mail into dated folders and keeps a running total.
section: email
icon: receipt
version: 1.0.0
wave: 2
inputs:
  - {key: account, kind: email_account, label: Which inbox (blank for all of them), optional: true}
  - {key: folder, kind: folder, label: "Folder for receipts, inside your projects folder"}
triggers:
  - {on: event, event: email_received, every: 10, label: Every ten new messages}
  - {on: daily, at: "21:00", label: Evening sweep}
tools: [search_emails, read_email, download_attachment, write_file, read_file, ls]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: answer, must_contain: [Total]}
effects: {read_private: allow, write_workspace: allow, read_workspace: allow}
budget: {runs_per_day: 8, max_steps: 40, max_minutes: 12}
memory: own
---
1. Call search_emails for recent mail that is a receipt, invoice or order confirmation. Skip message ids in your notebook.
2. For each, call read_email and keep the merchant, the date, the amount and the currency. If an amount is not in the message, write "amount not stated" — never guess one.
3. Call download_attachment for each PDF receipt into the folder you were hired with, under a subfolder named for the year and month (2026-10). Name the file date-merchant-amount.
4. Read ledger.csv in that folder with read_file (it may not exist yet), append one row per receipt (date, merchant, amount, currency, file) and write it back with write_file.
5. Answer with the receipts filed this run and a line "Total this month:" per currency, summed from ledger.csv.
6. In your Carry forward, list the message ids you filed.
