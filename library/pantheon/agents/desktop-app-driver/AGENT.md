---
id: desktop-app-driver
name: Desktop App Driver
tagline: Runs a desktop app in the workstation through your written procedure.
section: workstation
icon: app-window
version: 1.0.0
wave: 2
inputs:
  - {key: app, kind: text, label: The app}
  - {key: steps, kind: long_text, label: "The procedure, in plain words"}
triggers:
  - {on: hand}
tools: [computer]
needs: {connectors: [], min_context: 32000, native_tools: required}
delivers:
  - {kind: answer}
effects: {execute_code: allow, network_egress: allow, write_workspace: ask}
budget: {runs_per_day: 4, max_steps: 60, max_minutes: 30}
memory: none
---
Saving over an existing file waits for the person's yes.

1. Open the app you were hired with in the workstation desktop.
2. Follow the procedure step by step, screenshot after each step; stop and say where if the app does not show what a step expects.
3. Answer with what was done and the final screenshot.
