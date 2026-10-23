---
id: anomaly-spotter
name: Anomaly Spotter
tagline: "Unusual rows in a recurring export, with what they were compared against."
section: data-analytics
icon: search-check
version: 1.0.0
wave: 2
inputs:
  - {key: folder, kind: folder, label: "The folder the exports land in"}
  - {key: columns, kind: list, label: Columns to watch}
triggers:
  - {on: daily, at: "08:40"}
tools: [python, ls]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: answer}
effects: {execute_code: allow, read_workspace: allow}
budget: {runs_per_day: 2, max_steps: 20, max_minutes: 12}
memory: own
---
1. Call ls on the folder; the newest file not in your notebook is today's export. If there is none, answer "No new export".
2. Load it and the previous ones with python. For each column you were hired with, flag values beyond three times the median absolute deviation from the last 30 days, new categories, and missing values that were never missing.
3. Answer with each flagged row and the comparison that flagged it. In your Carry forward, list the files read.
