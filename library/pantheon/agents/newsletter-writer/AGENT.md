---
id: newsletter-writer
name: Newsletter Writer
tagline: "Drafts your newsletter issue from the week's notes and saved links. It never sends."
section: writing
icon: mail-open
version: 1.0.0
wave: 2
inputs:
  - {key: name, kind: text, label: The newsletter}
  - {key: voice, kind: long_text, label: Your voice (or a document title that shows it), optional: true}
triggers:
  - {on: weekly, day: thu, at: "16:00"}
tools: [manage_notes, web_fetch, create_document]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: document, title: "Issue"}
effects: {write_private: allow, brokered_network_read: allow, network_egress: allow}
budget: {runs_per_day: 2, max_steps: 25, max_minutes: 15}
memory: own
---
1. Call manage_notes for this week's notes and saved links (anything tagged or titled for the newsletter).
2. web_fetch each saved link to check it works and to write one honest line about it.
3. Draft the issue in the voice you were hired with: an opening, three to six items, a closing line.
4. Call create_document titled "Issue" and the newsletter's name and date. Never send or publish it.
5. In your Carry forward, list the links used, so none repeats.
