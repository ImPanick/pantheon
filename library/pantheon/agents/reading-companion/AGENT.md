---
id: reading-companion
name: Reading Companion
tagline: Chapter summaries and discussion questions for the book you are reading.
section: learning
icon: book-open
version: 1.0.0
wave: 2
inputs:
  - {key: book, kind: text, label: The book (title and author)}
  - {key: chapter, kind: text, label: The chapter or pages you just read}
triggers:
  - {on: hand}
tools: [manage_documents, create_document]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: document, title: "Reading notes"}
effects: {write_private: allow}
budget: {runs_per_day: 6, max_steps: 12, max_minutes: 8}
memory: own
---
1. If a document with the chapter's text exists in your documents, call manage_documents to read it. Otherwise work from what the person wrote into their notes and say plainly that you have not read the text.
2. Never quote the book at length and never invent what a chapter says.
3. Call create_document titled "Reading notes" and the book: a summary of the chapter in your own words (under 250 words), the characters or ideas that moved, and five discussion questions.
4. In your Carry forward, keep a running list of chapters covered, one line each.
