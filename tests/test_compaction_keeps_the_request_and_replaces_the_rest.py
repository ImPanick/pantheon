# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2127`: compaction is what keeps a long chat in its room.

The owner, 2026-11-15: *"we have a monitor to watch where the context fill is
at, then at a certain point, we compact the chat (condense to a
machine-readable super-fast summary) - and then proceed... Reducing 200k down
to ~sub 1k is the goal"*. Measured on `fix/agent-lean-turn` before this:
`maybe_compact` measured the chat alone against the window, so on an agent
turn the trim (measured against the agent budget, its prompt included) bound
first and compaction never fired; when it did, it kept the newer half by
count and asked for a 1,024-token markdown report whatever it replaced, and
each compaction added one more summary beside the last.
"""
from __future__ import annotations

import asyncio

import pytest

import src.context_compactor as cc
from src.context_compactor import (
    COMPACT_THRESHOLD, SUMMARY_MAX_TOKENS, SUMMARY_MIN_TOKENS, maybe_compact,
)
from src.model_context import estimate_tokens


def _chat(pairs=200):
    msgs = [{"role": "system", "content": "You are a careful agent."}]
    for i in range(pairs):
        msgs.append({"role": "user", "content": f"step {i}: " + "detail " * 120})
        msgs.append({"role": "assistant", "content": f"done {i}: " + "result " * 120})
    msgs.append({"role": "user", "content": "now ship it"})
    return msgs


@pytest.fixture
def summariser(monkeypatch):
    calls = []

    async def fake_call(url, model, messages, **kwargs):
        calls.append({"messages": messages, **kwargs})
        return "SUMMARY turns=1 compactions=1\nGOAL: ship it\nSTATE: ready"

    monkeypatch.setattr(cc, "llm_call_async", fake_call)
    monkeypatch.setattr(cc, "resolve_endpoint", lambda *a, **k: (None, None, None))
    monkeypatch.setattr(cc, "get_context_length", lambda url, model: 200_000)
    return calls


def _run(msgs, **kw):
    return asyncio.run(maybe_compact(None, "http://local/v1", "m", msgs, {},
                                     persist=False, **kw))


def test_the_agent_budget_and_its_prompt_set_when_compaction_fires(summariser):
    msgs = _chat(40)                      # ~20K tokens in a 200K window
    used = estimate_tokens(msgs)
    _out, _ctx, did = _run(list(msgs))
    assert did is False, "under the window's threshold nothing happens"
    room = int(used / COMPACT_THRESHOLD) + 2000
    _out, _ctx, did = _run(list(msgs), budget=room)
    assert did is False, "under the budget's threshold nothing happens"
    _out, _ctx, did = _run(list(msgs), budget=room, overhead_tokens=4000)
    assert did is True, "the agent's own prompt counts toward the fill"


def test_a_long_chat_comes_down_to_its_request_and_a_short_record(summariser):
    msgs = _chat(200)                      # ~100K tokens
    before = estimate_tokens(msgs)
    out, _ctx, did = _run(list(msgs), budget=20_000)
    assert did is True
    assert out[-1]["content"] == "now ship it", "the person's message was summarised"
    assert out[0]["content"] == "You are a careful agent."
    convo_after = estimate_tokens(out[1:])
    assert convo_after <= 0.05 * before, (before, convo_after)
    asked = summariser[-1]
    assert SUMMARY_MIN_TOKENS <= int(asked["max_tokens"]) <= SUMMARY_MAX_TOKENS * 1.5 + 256


def test_the_summary_is_sized_to_what_it_replaces(summariser):
    _run(_chat(8), budget=2_000)
    small = summariser[-1]["max_tokens"]
    _run(_chat(200), budget=20_000)
    large = summariser[-1]["max_tokens"]
    assert small < large


def test_an_earlier_summary_is_merged_not_stacked(summariser):
    msgs = _chat(60)
    msgs.insert(1, {"role": "system",
                    "content": "[Conversation summary — earlier messages were compacted]\nGOAL: old goal"})
    state = {}
    out, _ctx, did = _run(list(msgs), budget=10_000, compaction_state=state)
    assert did is True
    summaries = [m for m in out if str(m.get("content", "")).startswith("[Conversation summary")]
    assert len(summaries) == 1
    assert "EARLIER SUMMARY: GOAL: old goal" in summariser[-1]["messages"][1]["content"]
    assert state["merged_earlier"] is True


def test_the_summariser_reads_each_message_in_full_when_it_fits(summariser):
    msgs = _chat(10)
    msgs[3]["content"] = "step 1: " + "x" * 3000 + " END-OF-STEP"
    _run(list(msgs), budget=2_000)
    assert "END-OF-STEP" in summariser[-1]["messages"][1]["content"]
