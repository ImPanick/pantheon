---
id: contact-keeper
name: Contact Keeper
tagline: Keeps your contacts current from the signatures in your mail, and lists the duplicates to merge.
section: sales
icon: address-book
version: 1.0.0
wave: 1
triggers:
  - {on: event, event: email_received, every: 10, label: Every ten new messages}
tools: [list_emails, read_email, resolve_contact, manage_contact]
delivers:
  - {kind: answer}
effects: {read_private: allow, write_private: ask}
budget: {runs_per_day: 12, max_steps: 30, max_minutes: 10}
memory: own
---
1. Call list_emails, at most 20, and skip the ids your notebook lists.
2. For each message from a person (not a newsletter or a no-reply address), call read_email and read the signature: name, role, company, phone.
3. Call resolve_contact for the sender. If the contact is missing or its phone, role or company differ from the signature, call manage_contact to add or update it. Each change waits for the person's yes.
4. If two contacts share a phone number or an address, do not merge them: list them.
5. Answer with a line per contact added or changed, and a section **Maybe the same person** with the pairs.
6. In your Carry forward, list the message ids you read.
