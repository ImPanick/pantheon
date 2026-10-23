---
id: bill-renewal-tracker
name: Bill & Renewal Tracker
tagline: "Lists the bills, subscriptions and renewals due in the next 30 days, from your mail and notes."
section: personal-home
icon: calendar-clock
version: 1.0.0
wave: 2
inputs: []
triggers:
  - {on: weekly, day: mon, at: "08:30"}
tools: [search_emails, read_email, manage_notes, create_document]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: document, title: "Due in the next 30 days"}
effects: {read_private: allow, write_private: allow}
budget: {runs_per_day: 2, max_steps: 35, max_minutes: 12}
memory: own
---
1. Call search_emails for the last 400 days' bills, renewals, subscriptions and "your plan renews" notices, at most 40.
2. For each, call read_email and keep: who, what, the amount, how often, and the next due date. A yearly renewal from last year is due again a year later.
3. Call manage_notes to search notes for "renews", "due" or "subscription" and add what they list.
4. Keep only what is due in the next 30 days. Call create_document titled "Due in the next 30 days" with one line per item, soonest first: date, who, what, amount, and where you found it.
5. In your Carry forward, list each recurring item with its next date, so next week starts from it.
