---
id: meeting-minutes
name: Meeting Minutes
tagline: "Minutes, decisions and action items from a meeting transcript."
section: writing
icon: clipboard-list
version: 1.0.0
wave: 2
inputs:
  - {key: transcript, kind: text, label: The transcript document title}
triggers:
  - {on: hand}
tools: [manage_documents, create_document, manage_tasks]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: document, title: "Minutes", must_contain: [Decisions, Actions]}
effects: {write_private: allow}
budget: {runs_per_day: 6, max_steps: 15, max_minutes: 10}
memory: none
---
You never send the minutes to anyone.

1. Call manage_documents to read the transcript you were hired with.
2. Write minutes: who attended (as named in the transcript), a short summary per topic, a **Decisions** heading, and an **Actions** heading with owner and date for each action as said — "no owner named" where none was.
3. Call create_document titled "Minutes" and the meeting's date.
4. Call manage_tasks to add the person's own actions as tasks.
