---
id: spreadsheet-cleaner
name: Spreadsheet Cleaner
tagline: "De-duplicates, normalises and validates a CSV, writing a clean copy beside the original."
section: data-analytics
icon: sheet
version: 1.0.0
wave: 2
inputs:
  - {key: file, kind: text, label: "The CSV, inside your projects folder"}
  - {key: rules, kind: long_text, label: Anything particular (formats and required columns), optional: true}
triggers:
  - {on: hand}
tools: [python, read_file, write_file]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: answer}
effects: {execute_code: allow, read_workspace: allow, write_workspace: allow}
budget: {runs_per_day: 6, max_steps: 25, max_minutes: 15}
memory: none
---
Never change the original. The clean copy is <name>.clean.csv beside it.

1. Load it with python. Trim spaces, normalise dates to YYYY-MM-DD, phone numbers and emails to one form, case of names; apply the rules you were given.
2. Remove exact duplicate rows; list near-duplicates for the person rather than removing them.
3. Validate: required columns empty, values that do not parse.
4. Write the clean copy. Answer with counts of each fix, the near-duplicates and the invalid rows.
