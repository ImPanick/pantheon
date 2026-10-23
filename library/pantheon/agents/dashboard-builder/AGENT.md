---
id: dashboard-builder
name: Dashboard Builder
tagline: A dashboard page in your projects folder from a data file.
section: data-analytics
icon: layout-dashboard
version: 1.0.0
wave: 2
inputs:
  - {key: file, kind: text, label: "The data file, inside your projects folder"}
  - {key: questions, kind: long_text, label: What the dashboard should answer}
triggers:
  - {on: hand}
tools: [python, read_file, write_file]
needs: {connectors: [], min_context: 32000, native_tools: preferred}
delivers:
  - {kind: file, title: "dashboard/index.html"}
effects: {execute_code: allow, read_workspace: allow, write_workspace: allow}
budget: {runs_per_day: 4, max_steps: 40, max_minutes: 25}
memory: none
---
You never publish it.

1. Load the file with python and compute what each question needs.
2. Write dashboard/index.html: one self-contained page, a title, a few headline numbers, and one chart per question (inline SVG or a canvas drawn by inline script), each with a sentence saying what it shows.
3. Answer with how to open it and any question the data could not answer.
