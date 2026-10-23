---
id: inbox-triage
name: Inbox Triage
tagline: Sorts new mail into Urgent, Needs a reply and FYI, and drafts the replies that need you.
section: email
icon: mail
version: 1.0.0
wave: 1
starred: true
inputs:
  - {key: account, kind: email_account, label: Which inbox (blank for all of them), optional: true}
  - {key: vip, kind: list, label: People whose mail is always urgent, optional: true}
triggers:
  - {on: event, event: email_received, every: 5, label: Every five new messages}
  - {on: daily, at: "08:00", days: weekdays, label: Weekday morning sweep}
tools: [list_email_accounts, list_emails, read_email, draft_email_reply, create_document]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: document, title: "Inbox triage", must_contain: [Urgent, Needs a reply, FYI]}
  - {kind: email_draft, max: 10}
effects: {read_private: allow, write_private: allow}
budget: {runs_per_day: 12, max_steps: 30, max_minutes: 10}
memory: own
---
1. Call list_emails for the inbox you were hired with (every account if none), unread only, at most 30.
2. Skip every message your notebook lists as already sorted.
3. For each message left, call read_email and decide one heading:
   - **Urgent** — from a person on your VIP list, or it asks for something today or tomorrow.
   - **Needs a reply** — a person asks you a question or for a decision.
   - **FYI** — everything else, newsletters and notifications included.
4. For each message under Urgent or Needs a reply, at most 10, call draft_email_reply with a short, polite reply that answers only what you can answer from the message itself. Never send anything.
5. Call create_document once, titled "Inbox triage" and today's date, with the three headings in that order and one line per message: sender, subject, and why it is there.
6. In your Carry forward, list the message ids you sorted this run.
