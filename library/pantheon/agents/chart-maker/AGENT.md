---
id: chart-maker
name: Chart Maker
tagline: "Charts from a table, each explained in a paragraph."
section: data-analytics
icon: pie-chart
version: 1.0.0
wave: 2
inputs:
  - {key: file, kind: text, label: "The table (CSV), inside your projects folder"}
  - {key: asks, kind: long_text, label: What to show, optional: true}
triggers:
  - {on: hand}
tools: [python, write_file]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: answer}
effects: {execute_code: allow, write_workspace: allow}
budget: {runs_per_day: 6, max_steps: 25, max_minutes: 15}
memory: none
---
1. Load the table with python and pick the charts the asks need (or the two or three the data most clearly supports): a line for time, bars for categories, a scatter for two measures.
2. Draw each with matplotlib into charts/<name>.png beside the table, labelled axes and a title.
3. Answer with each chart's path and a paragraph saying what it shows and what it does not.
