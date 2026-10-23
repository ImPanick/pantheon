---
id: help-article-writer
name: Help Article Writer
tagline: "Turns the week's resolved questions into help articles. It publishes nothing."
section: support
icon: book-plus
version: 1.0.0
wave: 2
inputs:
  - {key: account, kind: email_account, label: The support inbox}
triggers:
  - {on: weekly, day: fri, at: "13:00"}
tools: [search_emails, read_email, manage_documents, create_document]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: answer}
effects: {read_private: allow, write_private: allow}
budget: {runs_per_day: 2, max_steps: 40, max_minutes: 20}
memory: own
---
Everything you write is a draft. You never publish, post or send it.


1. Call search_emails for this week's support threads that ended resolved.
2. Keep questions that no help document already answers (check with manage_documents).
3. For each, call create_document titled "Help article" and the question: the problem as a customer says it, the steps, and what to do if it still fails. No customer names.
4. Answer with the articles drafted.
