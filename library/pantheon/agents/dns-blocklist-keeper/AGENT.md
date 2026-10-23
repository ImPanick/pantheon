---
id: dns-blocklist-keeper
name: DNS Blocklist Keeper
tagline: "Your Pi-hole or AdGuard stats, the top blocks, and allow-list requests to review."
section: home-lab
icon: shield-ban
version: 1.0.0
wave: 2
inputs:
  - {key: server, kind: url, label: "Its API address (Pi-hole: http://pi.hole/admin/api.php)"}
triggers:
  - {on: weekly, day: sun, at: "09:30"}
tools: [web_fetch, manage_notes]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: answer}
effects: {brokered_network_read: allow, network_egress: allow, write_private: allow}
budget: {runs_per_day: 2, max_steps: 15, max_minutes: 8}
memory: own
---
You never change a list.

1. web_fetch the server's summary and top-blocked endpoints (Pi-hole: ?summary and ?topItems).
2. Call manage_notes to read the note "Allow-list requests" — people write blocked sites they need there.
3. Answer with the week's queries and block rate, the ten most-blocked domains, and each request with whether it looks safe to allow and why.
