# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B561` — a card answered after its deadline, through the chat, says *Ask
again*.

`POST /api/chat_stream` peeks at the card before it consumes it and answered
every `None` with one neutral 409 (*"invalid, expired, or belongs to another
thread"*). `peek` purges lapsed cards, so the card was gone before `consume`
— which can tell a lapsed card from an unknown one (`P4-21`) — ever ran, and
`approval_consume_message("expired")`, the one sentence of the four that says
what to do, could not be reached from the surface it was written for.

Now `peek` reports why it found nothing, in `consume`'s words and on
`consume`'s terms (*expired* only to the card's own owner and chat), and the
route says the lapsed card's sentence. Driven through the real route and the
real store, with the store's clock moved past the deadline.
"""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import routes.chat_routes as chat_routes
import src.tool_approvals as tool_approvals
from src.tool_approvals import ToolApprovalStore
from src.tool_capabilities import capabilities_for_action
from test_foreground_model_routing import _RouteRequest, _chat_stream_endpoint  # noqa: E402

NEUTRAL = "This tool approval is invalid, expired, or belongs to another thread."


def _card(store, owner="alice", session="session-1"):
    return store.create(
        owner=owner, session_id=session, origin_run_id="run-1",
        tool_name="bash", content="ls /srv", workspace=None,
        external_untrusted_context_seen=False,
        capabilities=capabilities_for_action("bash", "ls /srv"),
    )


async def _answer(monkeypatch, approval_id, *, later=0):
    endpoint = _chat_stream_endpoint(monkeypatch, "agent", {})
    if later:
        now = time.time() + later
        monkeypatch.setattr(tool_approvals, "time", SimpleNamespace(time=lambda: now))
    request = _RouteRequest("agent")
    request._form.update({"tool_approval_id": approval_id, "tool_approval_decision": "approve",
                          "compare_mode": "false"})
    with pytest.raises(HTTPException) as exc:
        await endpoint(request)
    return exc.value


@pytest.fixture()
def store(monkeypatch):
    s = ToolApprovalStore(ttl_seconds=600)
    monkeypatch.setattr(chat_routes, "tool_approval_store", s)
    return s


@pytest.mark.asyncio
async def test_a_card_answered_after_its_deadline_says_ask_again(monkeypatch, store):
    card = _card(store)
    refused = await _answer(monkeypatch, card.approval_id, later=3600)
    assert refused.status_code == 409
    assert "Ask again" in refused.detail and "expired" in refused.detail


@pytest.mark.asyncio
async def test_someone_elses_lapsed_card_still_gets_the_neutral_sentence(monkeypatch, store):
    card = _card(store, owner="bob")
    refused = await _answer(monkeypatch, card.approval_id, later=3600)
    assert (refused.status_code, refused.detail) == (409, NEUTRAL)


@pytest.mark.asyncio
async def test_another_chats_live_card_still_gets_the_neutral_sentence(monkeypatch, store):
    card = _card(store, session="another-chat")
    refused = await _answer(monkeypatch, card.approval_id)
    assert (refused.status_code, refused.detail) == (409, NEUTRAL)


@pytest.mark.asyncio
async def test_an_id_nobody_issued_gets_the_neutral_sentence(monkeypatch, store):
    refused = await _answer(monkeypatch, "never-issued")
    assert (refused.status_code, refused.detail) == (409, NEUTRAL)


@pytest.mark.parametrize("card_owner, asker, session, expect", [
    ("alice", "Alice", "session-1", "expired"),     # the owner, however it is spelled
    ("bob", "alice", "session-1", "unknown"),       # a stranger is told nothing more
    ("alice", "alice", "another-chat", "unknown"),  # nor is another chat
])
def test_peek_says_why_on_consumes_terms(monkeypatch, card_owner, asker, session, expect):
    s = ToolApprovalStore(ttl_seconds=600)
    card = _card(s, owner=card_owner)
    out = {}
    assert s.peek(card.approval_id, owner=card_owner, session_id="session-1", outcome=out) is card
    assert out == {}, "a card that is there needs no reason"
    later = time.time() + 3600
    monkeypatch.setattr(tool_approvals, "time", SimpleNamespace(time=lambda: later))
    assert s.peek(card.approval_id, owner=asker, session_id=session, outcome=out) is None
    assert out == {"reason": expect}
    assert s.peek("never-issued") is None   # the contract every other caller has
