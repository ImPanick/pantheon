# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2126`: a long chat over its budget keeps its instructions, and keeps the
same beginning from one round to the next.

Measured on `fix/agent-lean-turn` before this (a 9,000-character prompt, a
60-message chat, one 6,000-character tool result a round, a 20,000-token
budget): `trim_for_context` cut the prompt to its first 2,045 characters while
every old turn was still sent, and the first message after the prompt moved
every round, so a local server re-read the whole request each time. The owner,
2026-11-15: per-round trimming should take out what the model would not need
"to do the same job at the same quality".
"""
from __future__ import annotations

from src.context_compactor import (EARLIER_TURNS_WORDS, PROMPT_CUT_NOTICE, PROMPT_CUT_WORDS,
                                   TRIM_HOLD_WATERMARK, trim_for_context, trim_left_out)
from src.model_context import estimate_tokens

PROMPT = {"role": "system", "content": "Rules of the house. " * 450}   # ~9,000 chars
BUDGET = 20_000


def _history(pairs=30):
    out = []
    for i in range(pairs):
        out.append({"role": "user", "content": f"question {i} " + "words " * 200})
        out.append({"role": "assistant", "content": f"answer {i} " + "words " * 200})
    return out


def _round(n):
    """The person's request, then `n` tool rounds of 6,000 characters each."""
    msgs = [{"role": "user", "content": "now fix the build"}]
    for i in range(n):
        msgs.append({"role": "assistant", "content": "", "tool_calls": [{
            "id": f"c{i}", "type": "function",
            "function": {"name": "bash", "arguments": "{}"}}]})
        msgs.append({"role": "tool", "tool_call_id": f"c{i}", "content": f"out {i} " + "x" * 6000})
    return msgs


def test_old_turns_go_before_the_instructions_are_cut():
    sent = trim_for_context([PROMPT] + _history() + _round(1), BUDGET)
    assert sent[0]["content"] == PROMPT["content"], "the instructions were cut"
    assert PROMPT_CUT_NOTICE not in sent[0]["content"]
    assert any(m.get("content") == "now fix the build" for m in sent), "the request was cut"
    assert estimate_tokens(sent) <= BUDGET


def test_a_held_trim_keeps_the_same_beginning_round_after_round():
    hold: dict = {}
    history = _history()
    firsts, cuts = [], 0
    # Nine rounds: by the ninth every earlier turn is gone, and what is left
    # is this turn's own results, which `B2128` shapes as they arrive.
    for n in range(1, 10):
        sent = trim_for_context([PROMPT] + history + _round(n), BUDGET, hold=hold)
        assert sent[0]["content"] == PROMPT["content"]
        assert estimate_tokens(sent) <= BUDGET
        first = sent[1]["content"]
        if firsts and first != firsts[-1]:
            cuts += 1
        firsts.append(first)
    # Without the hold the beginning moved on every one of these rounds.
    assert cuts <= 3, f"the beginning moved {cuts} times in 9 rounds"


def test_a_held_trim_lands_under_the_watermark_so_the_next_rounds_fit():
    hold: dict = {}
    sent = trim_for_context([PROMPT] + _history() + _round(1), BUDGET, hold=hold)
    assert estimate_tokens(sent) <= BUDGET * TRIM_HOLD_WATERMARK + 600
    assert hold.get("prior_dropped", 0) > 0


def test_a_chat_that_fits_is_sent_as_it_is():
    msgs = [PROMPT] + _history(2) + _round(1)
    assert trim_for_context(msgs, BUDGET, hold={}) == msgs


def test_the_trim_says_it_left_out_the_earlier_part_of_the_chat():
    before = [PROMPT] + _history() + _round(1)
    said = trim_left_out(before, trim_for_context(before, BUDGET))
    assert said == [EARLIER_TURNS_WORDS], said
    assert PROMPT_CUT_WORDS not in said


def test_saved_memory_before_the_request_is_not_an_earlier_turn():
    memory = {"role": "user", "content": "a fact. " * 2000,
              "metadata": {"source": "saved memory"}}
    msgs = [PROMPT] + _history(2) + [memory] + _round(1)
    sent = trim_for_context(msgs, estimate_tokens(msgs) - 100, hold={})
    assert any(m is memory for m in sent), "saved memory went as if it were a turn"
    assert trim_left_out(msgs, sent) == [EARLIER_TURNS_WORDS]
