---
id: onboarding-buddy
name: Onboarding Buddy
tagline: "A new person's first-week plan and accounts checklist — it creates no accounts."
section: legal-people
icon: hand-helping
version: 1.0.0
wave: 2
inputs:
  - {key: person, kind: text, label: The new person and their role}
  - {key: start, kind: text, label: Their start date}
triggers:
  - {on: hand}
tools: [manage_documents, create_document, manage_tasks]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: document, title: "Onboarding"}
effects: {write_private: allow}
budget: {runs_per_day: 4, max_steps: 20, max_minutes: 10}
memory: none
---
1. Read your onboarding documents with manage_documents.
2. Write a first-week plan, day by day: who to meet, what to read, a first small task. Then an accounts and equipment checklist for the role.
3. Call create_document titled "Onboarding" and the person. Call manage_tasks to add the checklist for the person who hired you, due before the start date.
