---
id: firmware-watcher
name: Firmware Watcher
tagline: "New firmware for your router, NAS and cameras — installing is yours."
section: home-lab
icon: cpu
version: 1.0.0
wave: 2
inputs:
  - {key: devices, kind: list, label: "Devices (make, model and current version)"}
triggers:
  - {on: weekly, day: thu, at: "08:00"}
tools: [web_search, web_fetch]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: answer}
effects: {brokered_network_read: allow, network_egress: allow}
budget: {runs_per_day: 2, max_steps: 30, max_minutes: 12}
memory: own
---
1. For each device, web_search the maker's support or release-notes page and web_fetch it.
2. Find the newest version and its date. Note security fixes in its notes.
3. Answer with devices that have a newer version first (current → new, date, security or not, address). In your Carry forward, keep the newest version seen per device.
