---
id: weekly-review
name: Weekly Review
tagline: What you did this week from your chats, documents and tasks — and what is still open.
section: personal-home
icon: clipboard
version: 1.0.0
wave: 1
inputs:
  - {key: at, kind: time, label: When it arrives on Fridays, default: "16:00"}
triggers:
  - {on: weekly, day: fri, at: "{at}"}
tools: [list_sessions, search_chats, manage_documents, manage_tasks, manage_notes]
delivers:
  - {kind: answer, must_contain: [Done, Still open]}
effects: {read_private: allow}
budget: {runs_per_day: 2, max_steps: 20, max_minutes: 10}
memory: own
---
1. Call list_sessions and keep the chats active in the last seven days.
2. Call manage_documents with list and keep the documents changed in the last seven days.
3. Call manage_tasks with list and note which tasks ran and how they ended.
4. Call manage_notes with list and keep the to-dos still open.
5. Answer with two sections:
   - **Done** — what moved this week, one line per chat, document or task that mattered.
   - **Still open** — open to-dos, and threads that stopped without an answer.
   Group lines by project where the names make it plain. Keep it under 300 words.
