---
id: screenshot-reporter
name: Screenshot Reporter
tagline: Captures the pages and dashboards you name into one PDF every morning.
section: workstation
icon: camera
version: 1.0.0
wave: 2
inputs:
  - {key: pages, kind: list, label: Page addresses}
  - {key: folder, kind: folder, label: "Folder for the PDFs, inside your projects folder"}
triggers:
  - {on: daily, at: "07:45"}
tools: [bash]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: answer}
effects: {execute_code: allow}
budget: {runs_per_day: 2, max_steps: 25, max_minutes: 15}
memory: own
---
1. Capture each page in the workstation with headless Chromium (`chromium --headless --screenshot` or Playwright), full page.
2. Combine them in order into <folder>/<date>.pdf (img2pdf or ImageMagick).
3. Answer with the file's path and any page that failed to load.
