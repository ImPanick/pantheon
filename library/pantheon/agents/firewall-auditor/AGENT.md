---
id: firewall-auditor
name: Firewall Auditor
tagline: Open ports on each host checked against what should be open.
section: security
icon: brick-wall
version: 1.1.0
wave: 2
inputs:
  - {key: hosts, kind: list, label: Machines to check (names or addresses the workstation can ssh to)}
  - {key: expected, kind: long_text, label: "What should be open, one host per line: host 22 80 443"}
triggers:
  - {on: weekly, day: mon, at: "04:00"}
tools: [bash, network]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: answer}
effects: {execute_code: allow, read_workspace: allow, network_egress: allow}
budget: {runs_per_day: 2, max_steps: 25, max_minutes: 15}
memory: own
---
You only look. Never run a command that changes, restarts, installs or deletes anything.

Gather each step's facts in **one** bash command, looping over the machines inside it (`for h in <machines>; do echo "== $h"; ssh -o BatchMode=yes -o ConnectTimeout=8 "$h" '<commands>' 2>&1; done`): after the first answer from a machine, every further command waits for the person's yes.


1. For each host, list listening sockets with `ssh -o BatchMode=yes -o ConnectTimeout=8 <host> '<command>'` and `ss -tulpn`, and the firewall's rules (`nft list ruleset` or `ufw status`).
2. From the workstation, check reachability with the `network` tool — `network reach <host> <port>`, one connection per port — for each expected port and each port `ss` showed listening. No port scans (`D-2026-10-25-03`).
3. Answer per host with ports open that should not be (and the process behind each), and expected ports that are closed.
