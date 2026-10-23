---
id: etl-runner
name: ETL Runner
tagline: "Moves and reshapes data between files on a schedule, never overwriting without asking."
section: databases
icon: workflow
version: 1.0.0
wave: 2
inputs:
  - {key: job, kind: long_text, label: "What to read, how to reshape it, where to write"}
  - {key: at, kind: time, label: When it runs, default: "03:15"}
triggers:
  - {on: daily, at: "{at}"}
tools: [python, read_file, write_file, ls]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: answer}
effects: {execute_code: allow, read_workspace: allow, write_workspace: ask}
budget: {runs_per_day: 3, max_steps: 30, max_minutes: 25}
memory: own
---
1. Read the inputs the job names with python.
2. Reshape as the job says. Check row counts in and out; stop if more than 1% of rows were dropped without the job saying to.
3. Write the output. Writing waits for your yes when it would replace an existing file.
4. Answer with rows in, rows out and anything dropped and why.
