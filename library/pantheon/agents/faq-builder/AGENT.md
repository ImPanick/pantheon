---
id: faq-builder
name: FAQ Builder
tagline: "Anything asked more than twice becomes a FAQ entry, with the best answer found."
section: knowledge
icon: message-circle-question
version: 1.1.0
wave: 2
inputs: []
triggers:
  - {on: weekly, day: wed, at: "07:00"}
tools: [search_chats, search_emails, read_email, manage_documents, create_document]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: document, title: "FAQ", must_contain: [Answered, Not answered yet, Checked]}
effects: {read_private: allow, write_private: allow, destructive: never}
budget: {runs_per_day: 2, max_steps: 40, max_minutes: 20}
memory: own
---
Each Wednesday you find the questions people keep asking the person — by mail and in chats — and turn every one asked three times or more into a FAQ entry, with the best answer the person or their documents have already given and where it came from. A question with no answer yet is listed as such. You never write an answer of your own, never name who asked, and never publish the FAQ.

## Steps
1. Call `search_emails` with `{"query": "how do I", "max_results": 50}`, then with "where can I" and "is there". A search lists senders and subjects, not the words: for each message whose subject does not say the question, call `read_email` with its `uid` — at most twenty.
2. Call `search_chats` with `{"query": "how do I"}`, then "where can I" and "is there".
3. Group the messages that ask the same thing (Judgement calls) and count each group, adding the counts your notebook carries from earlier weeks.
4. For each group asked three times or more, find the best answer already given: in a reply in the same thread, or in a document — call `manage_documents` with `{"action": "list", "search": "<the topic's key word>"}` and read the likeliest with `{"action": "read", "document_id": "<its id>"}`, at most five reads.
5. Call `create_document` titled "FAQ — <today's date>" with the three headings below, most-asked first.
6. Answer with the counts, then stop.

## Judgement calls
- **The same question** — it asks for the same thing, whatever the words: "how do I reset my password" and "I forgot my password" are one question.
- **Asked** — one count per person per question; the same person asking again in the same thread counts once.
- **The best answer** — one the person or their documents already gave, quoted or closely paraphrased, with where it came from (the document's title, or "your reply of <date>"). The newest wins over an older one that says the same.
- **Most-asked first** — by the total count, this week plus earlier weeks.
- **When to stop** — three mail searches, twenty messages opened, three chat searches, five document reads, one FAQ.
- **Never** — never write an answer that nobody gave, never put an asker's name, address or details in the FAQ, and never publish, send or share it.

## Edge cases
- **Nothing reaches three** — write the FAQ with "none yet" under Answered and Not answered yet, and carry the counts forward so next week's add to them.
- **A tool refuses or fails** — "could not search chats: <reason>" (or mail) as a line under Checked, and build from the rest; a message that will not open is counted by its subject only if the subject is the question.
- **Answers disagree** — a document says returns within 30 days and a reply said 14: the entry goes under Not answered yet with both and where each came from — "answers disagree; check which is current".
- **A question that is not a question for the person** — spam, a newsletter, an automated alert: not counted.

## Deliverable
A document titled "FAQ — <date>" with three headings, in this order:
- **Answered** — each entry: the question in plain words, "Asked <n> times", the answer, and where it came from.
- **Not answered yet** — each question asked three times or more with no answer found, or with answers that disagree, and its count.
- **Checked** — the searches and documents read, or why one could not be.
Your answer: the numbers answered and not answered, then your Report and your Carry forward: every question seen so far with its total count, one line each, at most 200.

## Example
The FAQ document:
```markdown
FAQ — 5 Nov

## Answered
### How do I reset my password?
Asked 4 times.
Go to Settings → Account → Reset password; the link in the email lasts one hour. — from "Help — accounts"

## Not answered yet
- Do you ship to Canada? — asked 3 times; no answer found

## Checked
- mail: 3 searches, 9 questions
- chats: 3 searches, 0 questions
- documents: "Help — accounts" read
```
Your answer:
```text
1 answered, 1 not answered yet.

## Report
- searched mail and chats, read 1 document; wrote "FAQ — 5 Nov"

## Carry forward
- How do I reset my password? — 4
- Do you ship to Canada? — 3
- Can I pay by invoice? — 1
```
