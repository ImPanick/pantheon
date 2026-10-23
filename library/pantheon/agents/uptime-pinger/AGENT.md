---
id: uptime-pinger
name: Uptime Pinger
tagline: Checks your addresses and ports every 15 minutes and logs downtime with start and end.
section: devops
icon: activity
version: 1.0.0
wave: 2
inputs:
  - {key: targets, kind: list, label: "Addresses (https://…) or host:port pairs"}
triggers:
  - {on: cron, cron: "*/15 * * * *", label: Every 15 minutes}
tools: [bash]
needs: {connectors: [], min_context: 8000, native_tools: preferred}
delivers:
  - {kind: answer}
effects: {execute_code: allow}
budget: {runs_per_day: 96, max_steps: 10, max_minutes: 4}
memory: own
---
1. For each target, run `curl -sS -o /dev/null -w '%{http_code} %{time_total}' --max-time 10 <url>` or `nc -z -w 5 <host> <port>`.
2. A target is down if it does not answer, or answers 5xx.
3. Compare with your notebook: a target that just went down starts an outage; one that came back ends it.
4. Answer only when something changed: "<target> down since <time>" or "<target> back after <minutes>". Otherwise answer "All up".
5. In your Carry forward, list each target's state and, if down, since when.
