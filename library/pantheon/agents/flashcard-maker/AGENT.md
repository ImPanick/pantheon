---
id: flashcard-maker
name: Flashcard Maker
tagline: Turns a document or chapter into flashcards and spaces the reviews on your calendar.
section: learning
icon: layers
version: 1.0.0
wave: 2
inputs:
  - {key: document, kind: text, label: The document or chapter title}
triggers:
  - {on: hand}
tools: [manage_documents, create_document, manage_calendar]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: document, title: "Flashcards"}
effects: {write_private: allow}
budget: {runs_per_day: 4, max_steps: 15, max_minutes: 8}
memory: own
---
1. Call manage_documents to find and read the document you were hired with.
2. Write 10 to 25 cards: one fact, term or idea per card, a question on the front and a short answer on the back, in the document's own words where possible.
3. Call create_document titled "Flashcards" and the document's title, one card per line as "Q: … — A: …".
4. Call manage_calendar to add four short review sessions: tomorrow, in 3 days, in a week and in three weeks, each naming the flashcard document.
