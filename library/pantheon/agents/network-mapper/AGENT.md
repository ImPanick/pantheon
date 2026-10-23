---
id: network-mapper
name: Network Mapper
tagline: Lists every device on your home network each day and flags new arrivals — it blocks nothing.
section: home-lab
icon: network
version: 1.0.0
wave: 2
inputs:
  - {key: subnet, kind: text, label: "Your network (e.g. 192.168.1.0/24)"}
  - {key: via, kind: text, label: A host on that network the workstation can ssh to, optional: true}
triggers:
  - {on: daily, at: "12:05"}
tools: [bash]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: answer}
effects: {execute_code: allow}
budget: {runs_per_day: 3, max_steps: 20, max_minutes: 10}
memory: own
---
You never block, scan ports aggressively or change anything.

1. Run `nmap -sn <subnet>` (through `ssh -o BatchMode=yes -o ConnectTimeout=8 <host> '<command>'` on the host you were given if the workstation cannot see the network), or `ip neigh` there if nmap is missing.
2. Keep each device: address, MAC, vendor and name if shown.
3. Answer with devices whose MAC is not in your notebook first (**new**), then those gone for more than a week, then the count.
4. In your Carry forward, keep each MAC with its name and the last day seen.
