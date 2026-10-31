---
name: clarify-the-goal
description: Before planning or building anything sizeable, learn what the person wants: look first, ask only questions that change the work, restate their vision, then plan.
version: 1.0.0
category: core
tags: [clarify, requirements, vision, scope, goal, plan, planning, questions, ask, ambiguous, vague, brief, spec, build, project, idea]
requires_toolsets: [ask_user]
status: published
confidence: 0.95
source: pantheon
---

## When to Use

A request to build, plan, design or write something where the answer depends on things the person has not said: who it is for, what "done" looks like, what it must and must not do, constraints (budget, stack, deadline, style), or which of several readings they mean. Also when asked to draft a plan and you could not name the plan's success criteria yourself.

Skip it for small, clear or easily reversed asks: do those and say which reading you chose.

## Procedure

1. Look before you ask. Read what is already here — the conversation, attached files, their memories, the project folder, an open document. Never ask a question a tool or the context could answer.
2. Write down, privately, what you know and what you are missing: goal, audience, must-haves, nice-to-haves, constraints, success test, and anything you would otherwise have to guess.
3. Keep only the gaps whose answer would change what you build. A guess that is cheap to change later is a default, not a question.
4. Ask those with `ask_user`, one decision per call, most important first. Give 2–6 concrete options with a one-line trade-off each, put your recommendation first, and leave room for their own answer. Calling `ask_user` ends your turn; their pick arrives as the next message.
5. For open-ended vision ("what should it feel like?") ask in plain text instead, with two or three examples of the kind of answer that helps.
6. Stop asking once the remaining unknowns are defaults. Three rounds is a lot; most work needs one or two.
7. Restate the vision back in a few lines — the goal in their words, what is in, what is out, how you will know it works, and the defaults you chose — and ask them to confirm or correct it.
8. Then plan: a short checklist of steps that each end in something you can check, and keep it current as steps are done.

## Pitfalls

- Asking everything up front as a questionnaire. Ask only what changes the work, in order.
- Asking what you could have looked up, or what you already asked.
- Drafting a detailed plan on guesses and presenting it as settled. If you had to guess something important, say so in the plan.
- Endless clarification: after the vision is confirmed, act.

## Verification

- You can state the goal, the audience, the success test and the main constraints without inventing any of them, and the person has confirmed your restatement.
