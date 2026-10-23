---
id: expense-tracker
name: Expense Tracker
tagline: Categorises your receipts and statements into a monthly ledger.
section: finance
icon: wallet
version: 1.0.0
wave: 2
inputs:
  - {key: folder, kind: folder, label: "Folder of receipts and statement CSVs"}
triggers:
  - {on: cron, cron: "0 8 2 * *", label: The second of each month}
tools: [python, read_file, write_file, ls]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: answer}
effects: {execute_code: allow, read_workspace: allow, write_workspace: allow}
budget: {runs_per_day: 2, max_steps: 30, max_minutes: 20}
memory: own
---
1. List the folder; read statement CSVs with python and receipt text where available.
2. Categorise each line (housing, food, transport, utilities, software, travel, other) using your notebook's rules for merchants seen before.
3. Write ledger-<YYYY-MM>.csv for last month. Answer with totals per category and against the month before.
4. In your Carry forward, keep merchant → category rules.
