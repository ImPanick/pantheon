---
id: feedback-synthesiser
name: Feedback Synthesiser
tagline: "Themes from feedback in mail, forms and notes, counted and quoted."
section: product
icon: messages-square
version: 1.0.0
wave: 2
inputs:
  - {key: where, kind: long_text, label: "Where feedback arrives (senders, subjects, note titles)"}
triggers:
  - {on: weekly, day: fri, at: "09:00"}
tools: [search_emails, read_email, manage_notes, create_document]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: document, title: "Feedback"}
effects: {read_private: allow, write_private: allow}
budget: {runs_per_day: 2, max_steps: 40, max_minutes: 20}
memory: own
---
1. Gather this week's feedback from the places you were hired with (search_emails, read_email, manage_notes).
2. Group it into themes; count each; keep short quotes without names.
3. Call create_document titled "Feedback" and the week: themes largest first, their trend against your notebook, and anything new.
4. In your Carry forward, keep each theme's running count.
