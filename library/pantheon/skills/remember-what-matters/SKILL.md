---
name: remember-what-matters
description: Keep the person's memory useful — save lasting facts and preferences they would otherwise have to repeat, search before adding, update rather than duplicate, and never store secrets.
version: 1.0.0
category: core
tags: [memory, remember, preference, fact, recall, forget, personal, profile, save, note, context, contact, update]
requires_toolsets: [manage_memory]
status: published
confidence: 0.95
source: pantheon
---

## When to Use

The person says "remember…", "forget…", corrects something you knew about them, or shares a lasting fact or preference (their role, a project, how they like answers, an important person or date) that later chats would need.

## Procedure

1. Decide if it lasts: a preference, standing fact, relationship or recurring event is worth keeping; a one-off detail of today's task is not.
2. `manage_memory` `action: search` with the key words first, to find anything that already covers it.
3. Something close exists → `action: edit` with its `memory_id` and the corrected `text`. Nothing → `action: add` with a short self-contained `text` and a `category` (`fact`, `event`, `contact`, `preference`).
4. Write each memory as one fact a stranger could understand later: "Prefers metric units", not "yes, that one".
5. "Forget X" → search, then `action: delete` each matching `memory_id`, and confirm what was removed.
6. Tell the person in a few words what you saved or changed.

## Pitfalls

- Saving passwords, keys, card numbers or other secrets. Point them to the vault instead.
- Adding a duplicate instead of editing the existing memory.
- Saving guesses about the person as facts.
- Saving every detail of a conversation.

## Verification

- A `search` for the topic returns exactly one memory that states the fact correctly.
