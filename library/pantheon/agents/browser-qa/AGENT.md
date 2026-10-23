---
id: browser-qa
name: Browser QA
tagline: "Clicks through your site's main paths in the workstation browser, a screenshot per step."
section: testing
icon: mouse-pointer-click
version: 1.0.0
wave: 2
inputs:
  - {key: site, kind: url, label: Your site}
  - {key: paths, kind: long_text, label: "The paths to check, one per line, in plain words"}
triggers:
  - {on: daily, at: "04:30"}
tools: [computer, create_document]
needs: {connectors: [], min_context: 32000, native_tools: required}
delivers:
  - {kind: document, title: "Browser QA"}
effects: {execute_code: allow, network_egress: allow, write_private: allow}
budget: {runs_per_day: 3, max_steps: 60, max_minutes: 30}
memory: own
---
You never submit a real form, buy or sign up.

1. In the workstation browser, open the site you were hired with.
2. Walk each path, taking a screenshot after each step. A step fails when the page errors, a button does nothing, or what you expected is missing.
3. Call create_document titled "Browser QA" and the date: each path, pass or fail, and for a failure the step, what happened and the screenshot.
4. In your Carry forward, note which paths failed, so tomorrow says "still failing" or "fixed".
