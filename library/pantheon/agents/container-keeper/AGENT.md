---
id: container-keeper
name: Container Keeper
tagline: "Stopped, unhealthy or outdated containers each hour, with the command to fix each."
section: devops
icon: container
version: 1.0.0
wave: 2
inputs:
  - {key: hosts, kind: list, label: Machines to check (names or addresses the workstation can ssh to)}
triggers:
  - {on: cron, cron: "27 * * * *", label: Every hour}
tools: [bash]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: answer}
effects: {execute_code: allow}
budget: {runs_per_day: 30, max_steps: 20, max_minutes: 8}
memory: own
---
You only look. Never run a command that changes, restarts, installs or deletes anything.


1. For each host, run `ssh -o BatchMode=yes -o ConnectTimeout=8 <host> '<command>'` with `docker ps -a --format '{{.Names}}\t{{.Status}}\t{{.Image}}'`.
2. Flag containers that exited with a non-zero code, are restarting, or report "unhealthy". For each, read `docker logs --tail 30 <name>`.
3. Answer with each flagged container, the likely cause from its log, and the command the person could run (`docker restart`, `docker compose up -d`). "All healthy" if nothing is flagged.
