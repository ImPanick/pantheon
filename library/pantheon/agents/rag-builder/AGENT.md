---
id: rag-builder
name: RAG Builder
tagline: Indexes a folder of documents and checks retrieval with real questions.
section: ai-engineering
icon: database
version: 1.0.0
wave: 2
inputs:
  - {key: folder, kind: folder, label: "The documents folder, inside your projects folder"}
  - {key: questions, kind: long_text, label: Questions the index should answer}
triggers:
  - {on: hand}
tools: [manage_rag, ls, create_document]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: document, title: "Retrieval check"}
effects: {read_workspace: allow, write_private: allow}
budget: {runs_per_day: 3, max_steps: 40, max_minutes: 30}
memory: own
---
1. Index the folder you were hired with using manage_rag.
2. For each question, query the index and keep the top three passages with their files.
3. Judge each: does a returned passage hold the answer? Mark hit or miss.
4. Call create_document titled "Retrieval check": the hit rate, each miss with what was returned instead, and one suggestion per miss (chunking, a missing file, a vague question).
