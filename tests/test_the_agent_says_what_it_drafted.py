# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1875` — the assistant's draft reply says what the Workbench's says: when
the workflow starts, what the drafter changed, and where it sends things.

`workflow_assist.draft_workflow` answers `Drafted(wf, trigger, notes, missing,
destinations)`, and the Workbench's *Describe it* shows all of it. The
`draft_workflow` arm of `manage_tasks` returned the name, the step count and
`missing` — and dropped the rest. **Measured on `5e4c8ec`** (the audit's
probe, reproduced here): the model drafts a start on an event Pantheon does
not fire (`bank_mail_arrived`), so the start falls back to daily 09:00 and the
drafter notes it; the AI step's model and address are left out and noted. The
assistant saw only "Drafted “Bank mail digest” as a workflow of 1 step,
switched off. …" and told the person their "when mail arrives" automation was
made — a daily 09:00 schedule, which it never said, sending to a chat server
it never named.

Now the reply carries, after the sentence it always had: when it starts, in
words (`start_words`); the drafter's notes but the "Made …" line (the reply's
own first sentence says that) and the webhook address (its secret token stays
on the Workbench's start); and where it sends things (`destination_lines`).

Real (`Law 20`): `do_manage_tasks` over a real SQLite file, the drafter, the
store, the rule; the model is `workflow_assist._complete`, scripted.
"""

import json

import pytest

from src.user_time import clear_user_time_context, set_user_tz_name
from tests.helpers.assist_harness import POST, build_world, script_model, stored

pytestmark = pytest.mark.asyncio

BANK_MAIL = {
    "name": "Bank mail digest",
    "trigger": {"type": "event", "event": "bank_mail_arrived"},
    "steps": [{"id": "sum", "kind": "llm", "label": "Summarise",
               "config": {"prompt": "Summarise the newest bank mail.", "model": "their-model",
                          "endpoint_url": "http://elsewhere.example/v1"}},
              {"id": "post", "kind": "mcp", "label": "Post to #bank",
               "config": {"tool": POST, "args": {"channel": "#bank",
                                                 "text": "{{ steps.sum.text }}"}}}],
    "arrows": [{"from": "sum", "port": "success", "to": "post"}],
    "missing": [],
}
WEBHOOK = {
    "name": "Issue digest",
    "trigger": {"type": "webhook"},
    "steps": [{"id": "sum", "kind": "llm", "label": "Summarise",
               "config": {"prompt": "Summarise {{ steps.start.data.json.issue.title }}."}}],
    "arrows": [], "missing": [],
}


@pytest.fixture()
def world(monkeypatch, tmp_path):
    clear_user_time_context()
    yield build_world(monkeypatch, tmp_path, name="said.db")
    clear_user_time_context()


async def _draft(description):
    from src.tools.system import do_manage_tasks
    return await do_manage_tasks(json.dumps({"action": "draft_workflow",
                                             "description": description}), owner="alice")


async def test_the_reply_says_when_it_starts_what_changed_and_where_it_sends(world, monkeypatch):
    script_model(monkeypatch, BANK_MAIL)
    set_user_tz_name("Europe/Berlin")
    said = await _draft("When mail arrives from my bank, summarise it and post it to #bank.")
    assert said["exit_code"] == 0, said
    assert said["response"] == (
        "Drafted “Bank mail digest” as a workflow of 2 steps, switched off. A person checks "
        "each step in the Workbench before it can run (Automations → “Bank mail digest”), and "
        "switches it on there. It starts daily at 09:00 (Europe/Berlin). "
        "When it starts was left at daily 09:00 — set it on the start. "
        "“Summarise”: endpoint_url, model were left out — a draft does not set them. "
        "Where it sends things: “Post to #bank” sends to Chat: send_message — channel: #bank.")
    trigger = stored(world.factory, said["workflow_id"])[2]
    assert (trigger.trigger_type, trigger.schedule, trigger.scheduled_time) == (
        "schedule", "daily", "09:00"), "what the reply says is what was stored"


async def test_a_webhook_start_is_named_and_its_address_stays_in_the_workbench(world, monkeypatch):
    script_model(monkeypatch, WEBHOOK)
    said = await _draft("When GitHub says an issue opened, summarise it.")
    assert said["exit_code"] == 0, said
    token = stored(world.factory, said["workflow_id"])[2].webhook_token
    assert token and token not in json.dumps(said), "the webhook's secret is not in the chat"
    assert said["response"].endswith(
        "switches it on there. It starts when its webhook is called; its address is on the "
        "start in the Workbench.")
