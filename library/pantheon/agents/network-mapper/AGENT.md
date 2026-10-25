---
id: network-mapper
name: Network Mapper
tagline: Lists the devices your network has already seen each day and flags new arrivals — reads, sends nothing.
section: home-lab
icon: network
version: 1.1.0
wave: 2
inputs:
  - {key: subnet, kind: text, label: "Your network (e.g. 192.168.1.0/24)"}
  - {key: via, kind: text, label: "A host on that network the workstation can ssh to (your router, a NAS)", optional: true}
triggers:
  - {on: daily, at: "12:05"}
tools: [bash, network]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: answer}
effects: {execute_code: allow, read_workspace: allow, network_egress: ask}
budget: {runs_per_day: 3, max_steps: 20, max_minutes: 10}
memory: own
---
You only read. You never scan, probe, block or change anything — no `nmap`, no ping sweep, no port checks (`D-2026-10-25-03`).

1. Read the neighbour table — the devices that machine has already talked to, with no packet sent to find more: `ip neigh show` (or `arp -an` where `ip` is missing), through `ssh -o BatchMode=yes -o ConnectTimeout=8 <host> '<command>'` on the host you were given (a router sees the whole network), else on the workstation. Use `network list` to name the workstation's own subnet when no network was given. Keep only entries inside your network.
2. Keep each device: address, MAC, and the name the router gives it if it lists one.
3. Answer with devices whose MAC is not in your notebook first (**new**), then those gone for more than a week, then the count. Say that a quiet device can be missing from a neighbour table without being gone.
4. In your Carry forward, keep each MAC with its name and the last day seen.
