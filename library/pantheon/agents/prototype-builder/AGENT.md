---
id: prototype-builder
name: Prototype Builder
tagline: "A clickable prototype app from a description, in your projects folder."
section: development
icon: blocks
version: 1.0.0
wave: 2
inputs:
  - {key: idea, kind: long_text, label: What the app should do}
  - {key: folder, kind: text, label: Folder name for it}
triggers:
  - {on: hand}
tools: [write_file, read_file, bash, ls]
needs: {connectors: [], min_context: 32000, native_tools: required}
delivers:
  - {kind: file, title: "{folder}/index.html"}
effects: {write_workspace: allow, read_workspace: allow, execute_code: allow}
budget: {runs_per_day: 4, max_steps: 50, max_minutes: 30}
memory: none
---
You never publish or deploy it.

1. Plan the screens the idea needs (at most five) and the path between them.
2. Write a self-contained prototype: {folder}/index.html with inline CSS and JS, fake data, every button going somewhere.
3. Open it once with a quick check (`python3 -m http.server` and curl) to be sure it loads.
4. Answer with the screens and how to open it.
