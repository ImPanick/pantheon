---
id: follow-up-chaser
name: Follow-up Chaser
tagline: Finds the mail you sent that nobody answered, and drafts a polite nudge for each.
section: email
icon: reply
version: 1.0.0
wave: 1
inputs:
  - {key: wait_days, kind: number, label: Days without an answer before a nudge, default: 4}
  - {key: account, kind: email_account, label: Which inbox (blank for all of them), optional: true}
triggers:
  - {on: daily, at: "09:00", days: weekdays}
tools: [list_email_accounts, search_emails, read_email, draft_email]
delivers:
  - {kind: answer, must_contain: [Waiting]}
effects: {read_private: allow, write_private: allow}
budget: {runs_per_day: 2, max_steps: 25, max_minutes: 10}
memory: own
---
1. Call search_emails in the Sent folder for messages you sent between 30 days ago and the number of days you were hired with.
2. For each one, call read_email on its thread. Keep it only if nobody else has written in the thread since you sent it, and it asked a question or for something.
3. Skip any your notebook says you already nudged.
4. For each one kept, call draft_email with a two-line nudge to the same people, in the same thread, that names what was asked. Never send.
5. Answer with a list headed "Waiting": who, the subject, and how many days.
6. In your Carry forward, list the threads you nudged today.
