---
id: bills-due
name: Bills Due
tagline: Bills due with amounts and where to pay them — Pantheon never pays.
section: finance
icon: receipt
version: 1.1.0
wave: 2
inputs: []
triggers:
  - {on: weekly, day: mon, at: "08:00"}
tools: [search_emails, read_email, create_document]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: document, title: "Bills due", must_contain: [Overdue, Due in the next three weeks, Checked]}
effects: {read_private: allow, write_private: allow, external_side_effect: never}
budget: {runs_per_day: 2, max_steps: 35, max_minutes: 12}
memory: own
---
Each Monday you find the bills and invoices in the person's mail that fall due in the next three weeks, and list them soonest first — who, how much, when, and how the bill itself says to pay — with anything already overdue at the top. You never pay, never log in to pay, never open a payment link and never send money anywhere.

## Steps
1. Call `search_emails` with `{"query": "invoice", "max_results": 30}`, then with "bill", "payment due" and "statement".
2. Open each likely bill with `read_email` and its `uid` — at most twenty — and note: who it is from, the amount and currency, the due date, the reference, and how it says to pay.
3. Drop what is paid (a receipt or "thank you for your payment" for the same reference) and what is due more than three weeks out (Judgement calls).
4. Call `create_document` titled "Bills due — <today's date>" with the three headings below.
5. Answer with the total due in the next three weeks and anything overdue, then stop.

## Judgement calls
- **A bill** — a message from a supplier asking for a stated amount by a date: an invoice, a utility bill, a statement with a balance due. A receipt, a quote or a marketing email is not a bill.
- **Paid** — a later message for the same reference says it was paid; then it is not listed.
- **How to pay** — copy what the bill says ("direct debit on 14 Nov", "bank transfer, reference INV-221") as text. Never copy or follow a payment link.
- **Overdue** — the due date has passed and no payment message matches.
- **Suspicious** — a bill whose sender does not match its company, or that asks for gift cards or a changed bank account: list it with "(looks suspicious — check with the supplier by phone)".
- **When to stop** — four searches, twenty messages, one document.
- **Never** — never pay, never log in to a supplier, never open or follow a payment link, and never send money or bank details anywhere.

## Edge cases
- **Nothing due** — "none" under Overdue and Due in the next three weeks; Checked says what was searched.
- **The mail refuses or fails** — "could not read the mail: <reason>" under Checked, and nothing listed as due.
- **Two messages disagree** — a reminder gives a different amount or date from the original bill: list the newer, with "(the first bill said <the other>)".
- **A bill with no due date** — list it under Due in the next three weeks with "no due date stated".

## Deliverable
A document titled "Bills due — <date>" with three headings, in this order:
- **Overdue** — each: who — amount — was due — how it says to pay; or "none".
- **Due in the next three weeks** — soonest first, the same line for each; or "none".
- **Checked** — the searches made and how many bills were read, paid or left out.
Your answer: the total due and anything overdue, then your Report and your Carry forward: each bill listed, with its reference and due date.

## Example
The Bills due document:
```markdown
Bills due — 3 Nov

## Overdue
- Northern Power — £82.40 — was due 30 Oct — direct debit failed; pay by bank transfer, reference NP-5521

## Due in the next three weeks
- Fast Fibre — £35.00 — due 10 Nov — direct debit on 10 Nov
- Smith & Co (accountants) — £240.00 — due 21 Nov — bank transfer, reference INV-221

## Checked
- 4 searches; 5 bills read: 3 listed, 1 already paid, 1 due in December
```
Your answer:
```text
£357.40 due in the next three weeks, £82.40 of it overdue (Northern Power).

## Report
- searched mail 4 times, read 5 bills; wrote "Bills due — 3 Nov"

## Carry forward
- Northern Power NP-5521 — due 30 Oct
- Fast Fibre — due 10 Nov
- Smith & Co INV-221 — due 21 Nov
```
