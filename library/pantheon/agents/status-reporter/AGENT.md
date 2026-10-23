---
id: status-reporter
name: Status Reporter
tagline: "Done, next and blocked — from your tasks, commits and chats. It never sends."
section: product
icon: flag
version: 1.0.0
wave: 2
inputs:
  - {key: project, kind: text, label: The project}
  - {key: folder, kind: folder, label: Its repository (optional), optional: true}
triggers:
  - {on: weekly, day: fri, at: "15:00"}
tools: [manage_tasks, search_chats, bash, create_document]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: document, title: "Status", must_contain: [Done, Next, Blocked]}
effects: {write_private: allow, read_private: allow, execute_code: allow}
budget: {runs_per_day: 2, max_steps: 25, max_minutes: 12}
memory: own
---
Everything you write is a draft. You never publish, post or send it.


1. Call manage_tasks for the project's tasks completed and open; search_chats for this week's discussion of it; and if a repository was given, `git log --since="7 days ago" --oneline`.
2. Write **Done**, **Next** and **Blocked** (with what would unblock each), plus one line on overall health.
3. Call create_document titled "Status" and the project and week.
