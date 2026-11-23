# SPDX-License-Identifier: AGPL-3.0-or-later
"""Apollo: each person's standing partner in Pantheon.

The outline (`pantheon/assistant-chat-outline/outline.md`) in one line: Chat
and Agent mode are tools a person drives; Apollo is a colleague who drives the
work and reports back. What it does lives here as server rules, never in a
prompt, so a 12B local model and a frontier API model give the same product:

  * `tasks`    — a goal or errand as its own record (state, next step, the one
                 question it is stuck on), staffed by a lead agent;
  * `lead`     — which roster agent leads a goal, by fit for the job and model;
  * `budget`   — a goal's token budget, capped by the admin on API-billed
                 models only; local models run uncapped;
  * `notebook` — Apollo's working state: open loops and what was talked through;
  * `knows`    — what Apollo knows about the person, in Brain, stated or
                 inferred, every line visible and editable;
  * `frame`    — what Apollo is told at the top of each turn in its own chat;
  * `tool`     — the one `apollo` tool its chat uses to act on all of the above;
  * `runs`     — a goal's work as a hire of its lead agent, and its report back.

Every read and write takes the owner and filters on it: one Apollo per account,
nothing crossing accounts.
"""

APOLLO_NAME = "Apollo"
