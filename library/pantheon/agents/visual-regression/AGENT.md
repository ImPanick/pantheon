---
id: visual-regression
name: Visual Regression
tagline: Screenshots your pages each night and flags what moved since last time.
section: testing
icon: images
version: 1.0.0
wave: 2
inputs:
  - {key: pages, kind: list, label: Page addresses}
  - {key: folder, kind: folder, label: "Folder for the screenshots, inside your projects folder"}
triggers:
  - {on: daily, at: "03:45"}
tools: [bash, ls]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: answer}
effects: {execute_code: allow, read_workspace: allow}
budget: {runs_per_day: 2, max_steps: 30, max_minutes: 20}
memory: own
---
1. For each page, take a full-page screenshot in the workstation (`npx --yes playwright screenshot --full-page <url> <file>` or chromium headless) into <folder>/<date>/.
2. Compare each with the same page's last screenshot (your notebook names the folder) using ImageMagick `compare -metric AE` or Pillow.
3. Answer with the pages that changed more than 1% of their pixels, with both file paths and the difference image.
4. In your Carry forward, write today's folder.
