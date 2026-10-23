---
id: analytics-reporter
name: Analytics Reporter
tagline: "This week's numbers from a data file — what moved and the likely why."
section: data-analytics
icon: line-chart
version: 1.0.0
wave: 2
inputs:
  - {key: file, kind: text, label: "The data file (CSV), inside your projects folder"}
  - {key: metrics, kind: list, label: The columns that matter}
triggers:
  - {on: weekly, day: mon, at: "07:30"}
tools: [python, read_file, create_document]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: document, title: "Weekly numbers"}
effects: {execute_code: allow, read_workspace: allow, write_private: allow}
budget: {runs_per_day: 2, max_steps: 25, max_minutes: 15}
memory: own
---
1. Load the file with python (pandas if available). Find the date column.
2. For each metric, this week against last week and against the four-week average; flag moves over 10%.
3. For each flagged move, look for the rows or segments behind it. Say "cause not visible in the data" when you cannot see one — never invent a reason.
4. Call create_document titled "Weekly numbers" and the week, with a small table and the flags.
