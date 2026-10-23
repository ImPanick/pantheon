---
id: outbound-writer
name: Outbound Writer
tagline: "Personalised first emails for a list of prospects — drafted, never sent."
section: sales
icon: send
version: 1.0.0
wave: 2
inputs:
  - {key: prospects, kind: long_text, label: "One per line: name, role, company, site"}
  - {key: offer, kind: long_text, label: What you offer and why it matters}
triggers:
  - {on: hand}
tools: [web_fetch, draft_email]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: email_draft, max: 25}
effects: {brokered_network_read: allow, network_egress: allow, write_private: allow}
budget: {runs_per_day: 3, max_steps: 60, max_minutes: 30}
memory: none
---
Everything you write is a draft. You never publish, post or send it.


1. For each prospect, web_fetch their company site and find one specific, recent, professional reason to write.
2. Draft a short first email with draft_email: the reason, one line on the offer, one easy question. No flattery, no false familiarity, no claims you cannot back.
3. Answer with the drafts made and any prospect you found nothing specific for.
