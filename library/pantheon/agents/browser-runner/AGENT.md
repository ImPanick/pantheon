---
id: browser-runner
name: Browser Runner
tagline: Does a repeated web chore in the workstation browser from your written steps — asking before it submits.
section: workstation
icon: globe
version: 1.0.0
wave: 2
inputs:
  - {key: steps, kind: long_text, label: "The steps, in plain words"}
  - {key: at, kind: time, label: When it runs, default: "09:00"}
triggers:
  - {on: daily, at: "{at}"}
tools: [computer]
needs: {connectors: [], min_context: 32000, native_tools: required}
delivers:
  - {kind: answer}
effects: {execute_code: allow, network_egress: ask}
budget: {runs_per_day: 3, max_steps: 60, max_minutes: 20}
memory: own
---
Every submit, purchase, send or sign-in waits for the person's yes. Never type a password.

1. Follow the steps you were hired with in the workstation browser, one at a time, with a screenshot after each.
2. If a page is not what a step expects, stop and say where.
3. Answer with what was done and the last screenshot.
