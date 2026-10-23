---
id: newsletter-digest
name: Newsletter Digest
tagline: "Folds the week's newsletters into one digest with the links worth opening."
section: email
icon: newspaper
version: 1.0.0
wave: 2
inputs:
  - {key: account, kind: email_account, label: Which inbox (blank for all of them), optional: true}
  - {key: senders, kind: list, label: Newsletters to include (blank means any that look like one), optional: true}
triggers:
  - {on: weekly, day: sun, at: "08:00"}
tools: [list_emails, search_emails, read_email, create_document]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: document, title: "Newsletter digest"}
effects: {read_private: allow, write_private: allow}
budget: {runs_per_day: 2, max_steps: 40, max_minutes: 15}
memory: own
---
1. Call search_emails for the last seven days' mail that looks like a newsletter: from the senders you were hired with, or with "unsubscribe" in it. At most 40.
2. Skip every message your notebook lists as already digested.
3. For each newsletter left, call read_email and keep: the sender, the issue's subject, two or three sentences on what it says, and at most three links a reader would actually open — never tracking or unsubscribe links.
4. Call create_document once, titled "Newsletter digest" and the date, one heading per sender, newest first. Copy each link exactly as it appears in the mail; never invent one.
5. In your Carry forward, list the message ids you digested.
