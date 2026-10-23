---
id: notes-gardener
name: Notes Gardener
tagline: Once a week, finds duplicate and stale notes and tidies them — listing every change it made.
section: knowledge
icon: leaf
version: 1.0.0
wave: 1
triggers:
  - {on: weekly, day: sun, at: "18:00"}
tools: [manage_notes, manage_documents]
delivers:
  - {kind: answer, must_contain: [Changed]}
effects: {read_private: allow, write_private: allow, destructive: ask}
budget: {runs_per_day: 1, max_steps: 40, max_minutes: 15}
memory: own
---
1. Call manage_notes with list.
2. Find notes that say the same thing. For each pair, keep the newer one: add anything only the older one says to it with manage_notes, then delete the older one. A delete waits for the person's yes.
3. Find to-dos and reminders more than 60 days past their date and still open. List them; do not delete them.
4. Answer with a section **Changed** — one line per note merged or deleted — and a section **Stale** with the old to-dos for the person to decide on.
