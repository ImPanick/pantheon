---
id: load-tester
name: Load Tester
tagline: Runs a load test against a staging address and reports the latency curve.
section: testing
icon: gauge
version: 1.0.0
wave: 2
inputs:
  - {key: target, kind: url, label: The staging address (never production)}
  - {key: users, kind: number, label: Most users at once, default: 20}
triggers:
  - {on: hand}
tools: [bash, create_document]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: document, title: "Load test"}
effects: {execute_code: allow, write_private: allow, network_egress: ask}
budget: {runs_per_day: 3, max_steps: 25, max_minutes: 30}
memory: none
---
If the address you were hired with does not look like staging, test or localhost, stop and ask instead of running.

1. Run a stepped test in the workstation (`hey`, `wrk` or `ab` if installed, else a short Python asyncio script): 1, 5, 10 and the most users you were hired with, 30 seconds each.
2. Record per step: requests per second, p50, p95 and p99 latency, and error count.
3. Call create_document titled "Load test" and the target: the table, where latency bends, and the first errors.
