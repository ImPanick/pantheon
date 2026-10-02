# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1103` — a workflow step's question outlives a message typed into the
workflow's own chat.

Measured by `wf-walker` (`test_a_card_withdrawn_by_a_new_chat_message_says_so`,
§ 5's named residual) and again here on `7a7f9b2`: a Prompt step's card is
sealed to the trigger's chat (the seal needs a session, and the step that
resumes runs in it), and the chat route answers every ordinary message with
`tool_approval_store.retire_for_session(owner, session)` — so a person who
typed anything into that chat withdrew the question, and the step took its
"if it fails" way. A newer chat card in that chat superseded it the same way
(`create`: "one pending card per session").

**The rule chosen:** a workflow run's question belongs to its run, not to the
chat its step writes into. It is answered from the run's surfaces — the
notification, the waiting list, the Runs view — through the workflow's answer
route, and the chat never draws it; so a chat message neither withdraws it
nor (by minting a newer card) supersedes it. It still ends by its answer, its
12-hour deadline, Stop or switch-off (the walker's `_retire_cards`), and the
store's size cap. **Why this way and not "say before sending that it will
withdraw the question":** the question is about the run, and the person
answering it is usually not in that chat (it is a "[Task] …" chat in the Tasks
folder); a warning would make an unrelated message cost an overnight run its
step. **What does not change:** retiring still carries the card's taint into
that next chat turn (`retire_for_session` answers it), so the chat's model is
exactly as gated as before; the seal, TTL, single use and owner binding are
the store's (`FORBIDDEN.md` Part 2).

Driven (`Law 20`): the real walker, agent loop (model words scripted), gate,
approval store and answer route (`test_a_step_that_needs_a_yes_waits_for_it`'s
world). The chat route's ordinary-message branch is one call —
`retire_for_session(owner=…, session_id=…)` — and it is that call these cases
make; the whole route is driven in the Chromium drive (handoff note).
"""
import pytest

from src.tool_approvals import tool_approval_store
from src.tool_capabilities import capabilities_for_action
from tests.helpers.walker_harness import client_for, records_of, runs_of, settle
from tests.test_a_step_that_needs_a_yes_waits_for_it import _park, _reply_workflow, world  # noqa: F401

pytestmark = pytest.mark.asyncio


def _chat_of(w):
    from core.database import ScheduledTask
    db = w.factory()
    try:
        return db.query(ScheduledTask).filter(ScheduledTask.id == "wf").first().session_id
    finally:
        db.close()


def _chat_card(chat, content="echo from the chat"):
    """A card the chat's own model mints in the same chat."""
    return tool_approval_store.create(
        owner="alice", session_id=chat, origin_run_id="chat-run", tool_name="bash",
        content=content, workspace=None, external_untrusted_context_seen=False,
        capabilities=capabilities_for_action("bash", content))


async def _answer(w, run, rec, decision="approve_task"):
    async with client_for(w.app) as client:
        return await client.post(f"/api/workflows/w-wf/runs/{run['id']}/answer",
                                 headers={"x-test-user": "alice"},
                                 json={"node_id": "reply", "item": None, "decision": decision,
                                       "approval_id": rec["waiting"]["approval"]["approval_id"]})


async def test_a_message_in_the_workflows_chat_leaves_the_question_answerable(world):
    w = world
    _reply_workflow(w)
    run, rec = await _park(w)
    chat = _chat_of(w)
    approval_id = rec["waiting"]["approval"]["approval_id"]
    assert tool_approval_store.peek(approval_id).session_id == chat, "the card is sealed to that chat"
    # The person types into the workflow's chat: the chat route's one call.
    carried = tool_approval_store.retire_for_session(owner="alice", session_id=chat)
    assert carried is True, "the step's card was tainted (the webhook body); the turn carries it"
    assert tool_approval_store.peek(approval_id) is not None, "the question is still open"
    assert await w.s._resume_due_waits() == 0, "nothing to resume: it still waits for the person"
    [still] = runs_of(w.factory, "wf")
    assert still["status"] == "waiting"
    res = await _answer(w, run, rec)
    assert res.status_code == 200 and res.json()["outcome"] == "resumed", res.text
    await settle(w.s)
    [done] = runs_of(w.factory, "wf")
    assert done["status"] == "success"
    assert w.executed == [("bash", "printf reply-sent")], "Allow ran it once"


async def test_a_newer_card_in_that_chat_does_not_supersede_the_question(world):
    w = world
    _reply_workflow(w)
    run, rec = await _park(w)
    chat = _chat_of(w)
    approval_id = rec["waiting"]["approval"]["approval_id"]
    first = _chat_card(chat, "echo one")
    assert tool_approval_store.peek(approval_id) is not None, "the run's question is the run's"
    second = _chat_card(chat, "echo two")
    assert tool_approval_store.peek(first.approval_id) is None, "a chat card still supersedes a chat card"
    assert tool_approval_store.peek(second.approval_id) is not None
    assert tool_approval_store.peek(approval_id) is not None
    # And an ordinary message still retires the chat's own card (`Law 1`).
    tool_approval_store.retire_for_session(owner="alice", session_id=chat)
    assert tool_approval_store.peek(second.approval_id) is None
    assert tool_approval_store.peek(approval_id) is not None


async def test_the_question_still_ends_on_deny(world):
    """Its answer still ends it: a Deny consumes it, and the step takes its
    failure port."""
    w = world
    _reply_workflow(w)
    run, rec = await _park(w)
    res = await _answer(w, run, rec, "deny")
    assert res.status_code == 200 and res.json()["outcome"] == "denied"
    assert tool_approval_store.peek(rec["waiting"]["approval"]["approval_id"]) is None
    await settle(w.s)
    by = {r["node_id"]: r for r in records_of(w.factory, run["id"])}
    assert by["told"]["status"] == "success" and w.executed == []


async def test_stop_still_retires_the_question(world):
    """Stop (the real `stop_task`) ends the run and retires its card, consumed
    as a denial — a held card is not one that outlives the run."""
    w = world
    _reply_workflow(w)
    run, rec = await _park(w)
    approval_id = rec["waiting"]["approval"]["approval_id"]
    assert await w.s.stop_task("wf") is True
    assert tool_approval_store.peek(approval_id) is None
    [run] = runs_of(w.factory, "wf")
    assert run["status"] == "aborted"


async def test_a_chat_runs_card_is_not_held(world):
    """Every chat card is minted exactly as before (`held_by_run` False)."""
    card = _chat_card("some-chat")
    assert card.held_by_run is False
    assert "held_by_run" not in str(card.public_payload()), "nothing about it reaches a page"
