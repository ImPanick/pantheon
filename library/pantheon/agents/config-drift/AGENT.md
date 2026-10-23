---
id: config-drift
name: Config Drift
tagline: Compares your hosts with their recorded config in git and lists the drift — it fixes nothing.
section: devops
icon: git-compare
version: 1.0.0
wave: 2
inputs:
  - {key: hosts, kind: list, label: Machines to check (names or addresses the workstation can ssh to)}
  - {key: folder, kind: folder, label: "The config repository (one folder per host)"}
triggers:
  - {on: daily, at: "05:20"}
tools: [bash, read_file, ls]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: answer}
effects: {execute_code: allow, read_workspace: allow}
budget: {runs_per_day: 2, max_steps: 40, max_minutes: 15}
memory: own
---
You only look. Never run a command that changes, restarts, installs or deletes anything.


1. In the config repository, list each host's recorded files (<host>/etc/...).
2. For each file, fetch the live copy with `ssh -o BatchMode=yes -o ConnectTimeout=8 <host> '<command>'` and `cat <path>`, and compare with `diff -u`.
3. Answer per host with each drifted file and the diff's first 20 lines. "No drift" if none.
