---
id: speed-logger
name: Speed Logger
tagline: Logs your connection speed and latency through the day and charts the slow hours.
section: home-lab
icon: wifi
version: 1.0.0
wave: 2
inputs:
  - {key: folder, kind: folder, label: "Folder for the log, inside your projects folder"}
triggers:
  - {on: cron, cron: "41 * * * *", label: Every hour}
tools: [bash, read_file]
needs: {connectors: [], min_context: 8000, native_tools: preferred}
delivers:
  - {kind: answer}
effects: {execute_code: allow, read_workspace: allow}
budget: {runs_per_day: 30, max_steps: 10, max_minutes: 5}
memory: own
---
1. Measure: `speedtest-cli --simple` if installed, else download a 25 MB test file with curl and time it; and `ping -c 5 1.1.1.1` for latency.
2. Append a line to speed.csv in the folder (time, down Mbit/s, up if known, ping ms).
3. At 21:41 runs only, read the day's lines and answer with the slowest hours and the day's median; otherwise answer the one measurement.
