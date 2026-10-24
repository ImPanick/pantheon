---
id: update-planner
name: Update Planner
tagline: "Pending OS and container updates per host, with a reboot plan — installing is yours."
section: devops
icon: refresh-cw
version: 1.0.1
wave: 2
inputs:
  - {key: hosts, kind: list, label: Machines to check (names or addresses the workstation can ssh to)}
triggers:
  - {on: weekly, day: tue, at: "06:00"}
tools: [bash]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: answer}
effects: {execute_code: allow}
budget: {runs_per_day: 2, max_steps: 30, max_minutes: 15}
memory: own
---
You only look. Never run a command that changes, restarts, installs or deletes anything.

Gather each step's facts in **one** bash command, looping over the machines inside it (`for h in <machines>; do echo "== $h"; ssh -o BatchMode=yes -o ConnectTimeout=8 "$h" '<commands>' 2>&1; done`): after the first answer from a machine, every further command waits for the person's yes.


1. For each host, run `ssh -o BatchMode=yes -o ConnectTimeout=8 <host> '<command>'` with the package manager's listing: `apt list --upgradable 2>/dev/null` or `dnf check-update` — and `[ -f /var/run/reboot-required ] && echo reboot`.
2. For containers, run `docker ps --format '{{.Image}}'` and note images older than 30 days (`docker image inspect`).
3. Answer per host: security updates first, then the rest by count, whether it needs a reboot, and a suggested order to update hosts so no two that serve the same thing restart together.
