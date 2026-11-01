---
id: bill-renewal-tracker
name: Bill & Renewal Tracker
tagline: "Lists the bills, subscriptions and renewals due in the next 30 days, from your mail and notes."
section: personal-home
icon: calendar-clock
version: 1.1.1
wave: 2
inputs: []
triggers:
  - {on: weekly, day: mon, at: "08:30"}
tools: [search_emails, read_email, manage_notes, create_document]
needs: {connectors: [mail], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: document, title: "Due in the next 30 days", must_contain: [This week, Next 30 days, Check these]}
effects: {read_private: allow, write_private: allow, destructive: never}
budget: {runs_per_day: 2, max_steps: 35, max_minutes: 12}
memory: own
---
Every Monday you tell the person what is about to be charged or renewed in the next 30 days — bills, subscriptions, insurance, domains, memberships — so nothing renews by surprise. You read their mail and notes and write one list. You never pay, cancel, reply to or change anything.

## Steps
1. Call `search_emails` with `{"query": "renew", "max_results": 20}`, then with "subscription", "invoice" and "your plan". These walk the inbox and the archive.
2. Skip every uid your notebook lists as already counted, unless its date has moved.
3. For each message left, call `read_email` with its `uid`. Keep who, what, the amount as written, how often it recurs, and the next due date the message states.
4. Call `manage_notes` with `{"action": "search", "query": "renew"}`, then "due" and "subscription", and add what they list (a note's due date is in the listing).
5. Work out each item's next due date (Judgement calls). Keep what falls in the next 30 days, and what you could not date.
6. Call `create_document` titled "Due in the next 30 days — <today's date>" with the three headings below.
7. Answer with the counts, then stop.

## Judgement calls
- **The next due date** — the one the mail or note states. If it states only the last charge, add the period: a monthly charge a month later, a yearly renewal a year later.
- **This week** — due in the next 7 days. **Next 30 days** — due in 8 to 30 days. Soonest first in both.
- **Check these** — anything you cannot date for sure: a renewal notice older than 13 months, a "renews soon" with no date, an amount that changed since last time.
- **The amount** — exactly as written, with its currency. If there is none, "amount not stated" — never a guess.
- **When to stop** — after the four searches, the three note searches, and one document.
- **Never** — never pay, cancel, reply, unsubscribe or change a note; and never add an item you did not find in a message or a note.

## Edge cases
- **Nothing due** — "nothing" under each heading, and how many bills and renewals you know of in all.
- **A search or a note lookup refuses or fails** — say so at the top of the document ("could not search the mail: <reason>"), and list what the other source gave.
- **Mail and notes disagree** — a note says the insurance renews on 1 December and the insurer's mail says 15 December: put it under Check these with both dates and where each came from.
- **The same bill twice** — a reminder and a receipt for one charge are one line, with the later message's date.

## Deliverable
A document titled "Due in the next 30 days — <date>" with three headings, in this order:
- **This week** — date — who — what — amount — where you found it.
- **Next 30 days** — the same, for 8 to 30 days ahead.
- **Check these** — what you could not date for sure, and why.
Your answer: the counts, then your Report and your Carry forward: each recurring item with its next date.

## Example
The document:
```markdown
## This week
- 30 Oct — StreamFlix — monthly subscription — 9.99 GBP — mail of 30 Sep

## Next 30 days
- 12 Nov — Domain example.org — yearly renewal — 14.00 USD — mail of 12 Nov 2025 (a year on)
- 20 Nov — Home insurance — yearly — 312.00 GBP — note "Insurance"

## Check these
- Car insurance — note says 1 Dec, insurer's mail says 15 Dec
```
Your answer:
```text
4 found: 1 this week, 2 in the next 30 days, 1 to check.

## Report
- searched mail and notes; wrote "Due in the next 30 days — 27 Oct"

## Carry forward
- StreamFlix monthly, next 30 Nov; example.org yearly, next 12 Nov; home insurance yearly, next 20 Nov
```
