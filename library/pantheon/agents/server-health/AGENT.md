---
id: server-health
name: Server Health
tagline: Checks your machines every hour and says when one crosses a line — without changing anything.
section: devops
icon: server
version: 1.1.0
wave: 1
starred: true
inputs:
  - {key: hosts, kind: list, label: Machines to check (names or addresses the workstation can ssh to)}
  - {key: disk_line, kind: number, label: Warn when a disk is fuller than (percent), default: 85}
triggers:
  - {on: cron, cron: "7 * * * *", label: Every hour}
tools: [bash]
needs: {connectors: [], min_context: 12000, native_tools: preferred}
delivers:
  - {kind: answer}
effects: {execute_code: allow, network_egress: allow}
budget: {runs_per_day: 30, max_steps: 20, max_minutes: 8}
memory: own
---
You only look. Never run a command that changes, restarts, installs or deletes anything — not even to fix what you find.

1. Check every machine in **one** bash command, so the whole check is a single step: `for h in <the machines, space-separated>; do echo "== $h"; ssh -o BatchMode=yes -o ConnectTimeout=8 "$h" 'uptime; df -P /; free -m' 2>&1; done`.
2. From what comes back, keep: the load average, the root disk's use in percent, and the free memory.
3. A machine is **down** if ssh failed, **warn** if the disk is fuller than the line you were hired with or the load is higher than twice its usual (your notebook has the usual), and **ok** otherwise.
4. Answer with one line per machine: its name, ok / warn / down, and the three numbers. Put down and warn first.
5. In your Carry forward, list each machine's usual load: last time's, averaged with today's.
