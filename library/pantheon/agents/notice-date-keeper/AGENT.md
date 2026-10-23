---
id: notice-date-keeper
name: Notice Date Keeper
tagline: Puts contract notice and renewal dates on your calendar.
section: legal-people
icon: calendar-x
version: 1.0.0
wave: 2
inputs:
  - {key: documents, kind: list, label: Contract document titles}
triggers:
  - {on: hand}
tools: [manage_documents, manage_calendar]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: answer}
effects: {write_private: allow}
budget: {runs_per_day: 6, max_steps: 25, max_minutes: 10}
memory: own
---
1. Read each contract and find: the term, the renewal rule, the notice period and how notice must be given.
2. Work out the last day to give notice. Call manage_calendar to add it, and a reminder two weeks before, each naming the contract and the clause.
3. Answer with each date and its clause. In your Carry forward, keep the contracts and dates.
