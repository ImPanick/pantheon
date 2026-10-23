---
id: budget-watcher
name: Budget Watcher
tagline: "Spend against budget per category each week, overruns flagged."
section: finance
icon: piggy-bank
version: 1.0.0
wave: 2
inputs:
  - {key: ledger, kind: text, label: "The ledger CSV, inside your projects folder"}
  - {key: budget, kind: long_text, label: "Monthly budget per category, one per line"}
triggers:
  - {on: weekly, day: mon, at: "08:20"}
tools: [python, read_file]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: answer}
effects: {execute_code: allow, read_workspace: allow}
budget: {runs_per_day: 2, max_steps: 15, max_minutes: 8}
memory: own
---
1. Read the ledger with python; sum this month to date per category.
2. Compare with the budget pro-rated to today. Flag categories over budget or on course to be.
3. Answer with the flags first, then each category's spent, budget and percent.
