---
id: restore-drill
name: Restore Drill
tagline: "Restores last night's database dump into a scratch copy and checks the row counts."
section: databases
icon: database-backup
version: 1.0.0
wave: 2
inputs:
  - {key: dump, kind: text, label: "The dump file or folder (a path the workstation can read)"}
  - {key: engine, kind: choice, label: The database, choices: [postgres, mysql, sqlite]}
triggers:
  - {on: weekly, day: sun, at: "04:40"}
tools: [bash]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: answer, must_contain: [restored]}
effects: {execute_code: allow}
budget: {runs_per_day: 2, max_steps: 25, max_minutes: 40}
memory: own
---
You restore only into a scratch database you create in the workstation, never into a live one.

1. Find the newest dump. Start a scratch database (a temporary sqlite file, or a throwaway container for postgres or mysql).
2. Restore the dump into it (`pg_restore`, `psql`, `mysql`, `sqlite3 .read`).
3. Count the rows of every table; compare with last week's counts in your notebook.
4. Answer "restored" or "failed", the time it took, and tables whose count fell. Remove the scratch copy. In your Carry forward, keep the counts.
