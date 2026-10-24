---
id: log-watcher
name: Log Watcher
tagline: "New errors in your service logs each hour, grouped, with when each was first seen."
section: devops
icon: scroll-text
version: 1.0.1
wave: 2
inputs:
  - {key: hosts, kind: list, label: Machines to check (names or addresses the workstation can ssh to)}
  - {key: units, kind: list, label: "Services to read (systemd units or container names)"}
triggers:
  - {on: cron, cron: "13 * * * *", label: Every hour}
tools: [bash]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: answer}
effects: {execute_code: allow}
budget: {runs_per_day: 30, max_steps: 20, max_minutes: 8}
memory: own
---
You only look. Never run a command that changes, restarts, installs or deletes anything.

Gather each step's facts in **one** bash command, looping over the machines inside it (`for h in <machines>; do echo "== $h"; ssh -o BatchMode=yes -o ConnectTimeout=8 "$h" '<commands>' 2>&1; done`): after the first answer from a machine, every further command waits for the person's yes.


1. For each host and service, run `ssh -o BatchMode=yes -o ConnectTimeout=8 <host> '<command>'` with `journalctl -u <unit> --since "-65 min" -p warning --no-pager | tail -400` (or `docker logs --since 65m <name> 2>&1 | tail -400`).
2. Group lines into kinds by removing numbers, ids and times. Count each kind.
3. Answer with the kinds not in your notebook first (**new**), then the busiest known ones, each with a sample line, the host and the count. "Quiet" if there is nothing.
4. In your Carry forward, keep each kind with the date it was first seen, at most 200.
