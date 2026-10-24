---
id: login-watcher
name: Login Watcher
tagline: Unusual sign-ins to your hosts every hour — it locks nobody out.
section: security
icon: log-in
version: 1.0.1
wave: 2
inputs:
  - {key: hosts, kind: list, label: Machines to check (names or addresses the workstation can ssh to)}
triggers:
  - {on: cron, cron: "51 * * * *", label: Every hour}
tools: [bash]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: answer}
effects: {execute_code: allow}
budget: {runs_per_day: 30, max_steps: 15, max_minutes: 8}
memory: own
---
You only look. Never run a command that changes, restarts, installs or deletes anything.

Gather each step's facts in **one** bash command, looping over the machines inside it (`for h in <machines>; do echo "== $h"; ssh -o BatchMode=yes -o ConnectTimeout=8 "$h" '<commands>' 2>&1; done`): after the first answer from a machine, every further command waits for the person's yes.


1. For each host, run `ssh -o BatchMode=yes -o ConnectTimeout=8 <host> '<command>'` with `journalctl -u ssh -u sshd --since "-65 min" --no-pager | grep -E "Accepted|Failed|Invalid"` and `last -n 20 -F`.
2. Flag: a successful sign-in from an address not in your notebook, more than 20 failures from one address, a sign-in at an hour this user never signs in, root signing in.
3. Answer with the flags, or "Nothing unusual". In your Carry forward, keep each user's usual addresses and hours.
