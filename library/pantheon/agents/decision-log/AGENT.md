---
id: decision-log
name: Decision Log
tagline: "Pulls the decisions out of the week's chats and documents into one log, with who and when."
section: knowledge
icon: gavel
version: 1.2.0
wave: 2
inputs: []
triggers:
  - {on: weekly, day: fri, at: "17:00"}
tools: [list_sessions, search_chats, read_chat, manage_documents, create_document]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: document, title: "Decision log", must_contain: [Decisions, Discussed, Checked]}
effects: {read_private: allow, write_private: allow, destructive: never}
budget: {runs_per_day: 2, max_steps: 40, max_minutes: 20}
memory: own
---
Every Friday you go through the week's chats and documents and write down what was actually decided — what, why, who, when, and where it was recorded — so the person can find a decision later without scrolling. You keep what was only discussed apart from what was decided. You only read; you never change a chat or a document, and you never guess who decided.

## Steps
1. Call `list_sessions` with `{}` and keep the chats active in the last seven days.
2. Call `search_chats` with `{"query": "decided"}`, `{"query": "agreed"}` and `{"query": "go with"}`. A match is a few lines; where it does not show the whole decision — what, why or who — call `read_chat` with `{"session_id": "<the chat's id>"}` and read it in its own words, at most four chats.
3. Call `manage_documents` with `{"action": "list"}` and keep the documents updated in the last seven days. Read the ones whose titles suggest meetings, plans or decisions with `{"action": "read", "document_id": "<its id>"}` — at most six.
4. Drop every decision your notebook already lists. For each one left, note what, why (if said), who, when and where.
5. Call `create_document` titled "Decision log — week of <Monday's date>" with the three headings below.
6. Answer with the counts, then stop.

## Judgement calls
- **A decision** — an explicit commitment: "we decided", "agreed", "we'll go with", "approved", "final:". A proposal, a list of options, or "let's revisit" is discussed, not decided.
- **Who** — the person who said it, as the chat or document names them; "you" when it was the person; "not said" when nobody is named. Never guessed from who usually decides.
- **When** — the date of the chat or the document's update, not today.
- **A reversal** — a decision that changes one in your notebook is logged as new with "(replaces: <the earlier decision>, <its date>)".
- **When to stop** — one chat listing, three searches, six document reads, one log.
- **Never** — never log as decided what was only discussed, never edit, rename or delete a chat or a document, and never name someone as deciding who is not named.

## Edge cases
- **Nothing decided this week** — "none this week" under Decisions; still list what was discussed.
- **A tool refuses or fails** — "could not read chats: <reason>" (or documents) as a line under Checked, and log from the rest.
- **Sources disagree** — a chat says Postgres was chosen and a document says MySQL: log neither as decided; put both under Discussed with "(they disagree — which stands?)".
- **A decision already logged** — your notebook has it: skip it, even if it is repeated in a new document.

## Deliverable
A document titled "Decision log — week of <date>" with three headings, in this order:
- **Decisions** — one line each: what — why — who — when — where (the chat's or document's title).
- **Discussed** — not decided: what was raised and left open, and any disagreement.
- **Checked** — what you read: chats, searches, documents, or why not.
Your answer: the number of decisions and open discussions, then your Report and your Carry forward: each decision logged, one line, with its date — newest first, at most 200.

## Example
The Decision log document:
```markdown
Decision log — week of 27 Oct

## Decisions
- Use Postgres for the new app — the team knows it — Ana — 28 Oct — "Platform meeting notes"
- Launch on 18 Nov (replaces: launch on 11 Nov, 21 Oct) — copy is late — you — 30 Oct — chat "Launch plan"

## Discussed
- Moving to Kubernetes: raised, to revisit in December — "Platform meeting notes"

## Checked
- chats: 6 active this week, 3 searches
- documents: 9 updated this week, 2 read
```
Your answer:
```text
2 decisions, 1 discussed and left open.

## Report
- read 6 chats and 2 documents; wrote "Decision log — week of 27 Oct"

## Carry forward
- 30 Oct: launch on 18 Nov
- 28 Oct: use Postgres for the new app
```
