---
id: mockup-maker
name: Mockup Maker
tagline: Three different HTML mockups from a description.
section: design
icon: layout-template
version: 1.0.0
wave: 2
inputs:
  - {key: brief, kind: long_text, label: What the screen is for}
  - {key: folder, kind: text, label: Folder name for them}
triggers:
  - {on: hand}
tools: [write_file]
needs: {connectors: [], min_context: 32000, native_tools: preferred}
delivers:
  - {kind: file, title: "{folder}/a.html"}
effects: {write_workspace: allow}
budget: {runs_per_day: 4, max_steps: 15, max_minutes: 15}
memory: none
---
1. Design three genuinely different directions for the brief (layout, emphasis, density).
2. Write each as a self-contained page — {folder}/a.html, b.html, c.html — inline CSS, placeholder content that fits the brief, original design only.
3. Answer with one line per direction on what it bets on.
