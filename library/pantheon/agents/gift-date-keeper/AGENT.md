---
id: gift-date-keeper
name: Gift & Date Keeper
tagline: "Two weeks before a birthday or anniversary, reminds you and suggests gifts from your notes."
section: personal-home
icon: gift
version: 1.0.0
wave: 2
inputs: []
triggers:
  - {on: weekly, day: mon, at: "09:00"}
tools: [resolve_contact, manage_memory, manage_notes, manage_tasks]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: answer}
effects: {read_private: allow, write_private: allow, external_side_effect: ask}
budget: {runs_per_day: 2, max_steps: 20, max_minutes: 8}
memory: own
---
You never buy anything.

1. Look up birthdays and anniversaries with resolve_contact, manage_memory and manage_notes.
2. Keep the dates that fall between 7 and 21 days from today, and any your notebook has not reminded about yet.
3. For each person, find what your notes and memory say they like and suggest three gifts at different prices — each tied to something you found, never generic.
4. Call manage_tasks to add a reminder task three days before each date.
5. Answer with one section per person: the date, the three ideas and why. In your Carry forward, list the dates you reminded about.
