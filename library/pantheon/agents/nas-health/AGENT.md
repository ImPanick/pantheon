---
id: nas-health
name: NAS Health
tagline: "Your NAS drives' SMART status, pool health and scrub results, every morning."
section: home-lab
icon: hard-drive
version: 1.0.1
wave: 2
inputs:
  - {key: nas, kind: text, label: The NAS (a name the workstation can ssh to)}
triggers:
  - {on: daily, at: "07:05"}
tools: [bash]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: answer}
effects: {execute_code: allow}
budget: {runs_per_day: 2, max_steps: 20, max_minutes: 10}
memory: own
---
You only look. Never run a command that changes, restarts, installs or deletes anything.

Gather each step's facts in **one** bash command, looping over the machines inside it (`for h in <machines>; do echo "== $h"; ssh -o BatchMode=yes -o ConnectTimeout=8 "$h" '<commands>' 2>&1; done`): after the first answer from a machine, every further command waits for the person's yes.


1. With `ssh -o BatchMode=yes -o ConnectTimeout=8 <host> '<command>'`, run `zpool status -x` (or `cat /proc/mdstat`, or `btrfs device stats`), and for each drive `smartctl -H -A /dev/<d>`.
2. Flag: a pool not ONLINE, a scrub with errors or older than 35 days, reallocated or pending sectors that rose since your notebook, a drive hotter than 50 °C.
3. Answer flags first, then "healthy" with the pool size used. In your Carry forward, keep each drive's sector counts.
