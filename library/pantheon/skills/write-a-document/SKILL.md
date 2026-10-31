---
name: write-a-document
description: Write a document people will use (report, plan, proposal, guide, letter) by settling reader and purpose, outlining, drafting in the editor and revising with edits.
version: 1.0.0
category: core
tags: [write, writing, document, report, draft, proposal, plan, guide, article, letter, memo, essay, outline, edit, revise, doc]
requires_toolsets: [create_document, edit_document]
status: published
confidence: 0.95
source: pantheon
---

## When to Use

Anything longer than a few paragraphs that the person will keep, send or edit: reports, plans, proposals, guides, letters, articles, documentation.

## Procedure

1. Settle the brief: who reads it, what they should know or do after reading, the length, the tone, and any required format or template. Ask only what you cannot reasonably default.
2. Gather the material: the person's notes, files, earlier messages, and facts you must check.
3. Outline: a title and the headings, each with the point it makes. Share it first for anything long or important.
4. Draft with `create_document` (`title`, `language` `markdown` for prose, and the `content`). Lead with the conclusion or the ask; one idea per paragraph; plain words; concrete numbers and examples over adjectives.
5. Revise with `edit_document` — several FIND/REPLACE pairs in one call — rather than rewriting the whole document for small changes.
6. Reread as the reader: cut what they do not need, check every fact and name, and make sure the first paragraph alone tells them the point.

## Pitfalls

- Writing before knowing who it is for.
- Burying the conclusion at the end.
- Padding to sound thorough.
- Pasting a long document into the chat instead of the editor.

## Verification

- A reader who sees only the title and first paragraph knows what the document is for and what it concludes.
