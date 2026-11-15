# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2131`: the web search query is asked as the turn's own foreground work,
through the local model gate, without holding the event loop.

Measured on `fix/agent-lean-turn` before this: `build_chat_context` (async)
called `build_context_preface`, which asked for the query with the sync
`llm_call`. For up to its 15-second timeout the event loop served nothing
else, and on a local server the call skipped `_local_model_slot`, so it ran
alongside whatever the gate had admitted.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src import chat_processor as cp

SESSION = SimpleNamespace(endpoint_url="http://127.0.0.1:1234/v1", model="m", headers={})


def test_the_query_is_asked_async_as_foreground_work(monkeypatch):
    seen = {}

    async def fake_async(url, model, messages, **kw):
        seen.update(kw, url=url, model=model, messages=messages)
        await asyncio.sleep(0)
        return "  rust async  runtime "

    sync = MagicMock(side_effect=AssertionError("the sync call was used"))
    monkeypatch.setattr("src.llm_core.llm_call_async", fake_async)
    monkeypatch.setattr("src.llm_core.llm_call", sync)
    q = asyncio.run(cp.generate_search_query("what's the best rust async runtime?", SESSION))
    assert q == "rust async runtime"
    assert seen["workload"] == "foreground", "an inline call tagged background can wait forever"
    assert seen["thinking"] is False and seen["max_tokens"] == 50
    assert seen["messages"] == cp.search_query_messages("what's the best rust async runtime?")


def test_the_event_loop_keeps_serving_while_the_query_is_asked(monkeypatch):
    async def slow(*a, **kw):
        await asyncio.sleep(0.2)
        return "query"

    monkeypatch.setattr("src.llm_core.llm_call_async", slow)

    async def run():
        ticks = 0

        async def ticker():
            nonlocal ticks
            for _ in range(10):
                await asyncio.sleep(0.01)
                ticks += 1

        await asyncio.gather(cp.generate_search_query("x", SESSION), ticker())
        return ticks

    assert asyncio.run(run()) == 10


@pytest.mark.parametrize("answer", [RuntimeError("down"), "   "])
def test_a_failed_or_empty_answer_falls_back_to_the_first_line(monkeypatch, answer):
    async def fake(*a, **kw):
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr("src.llm_core.llm_call_async", fake)
    assert asyncio.run(cp.generate_search_query("\n first line \nsecond", SESSION)) == "first line"


def test_a_query_given_to_the_preface_is_searched_without_asking_again(monkeypatch):
    sync = MagicMock(side_effect=AssertionError("asked twice"))
    monkeypatch.setattr("src.llm_core.llm_call", sync)
    searched = MagicMock(return_value=("", []))
    monkeypatch.setattr("src.chat_processor.comprehensive_web_search", searched)
    proc = cp.ChatProcessor.__new__(cp.ChatProcessor)
    proc.__dict__.update(memory_manager=None, rag_manager=None)
    try:
        proc.build_context_preface(message="hello there", session=SESSION, use_web=True,
                                   use_rag=False, use_memory=False, search_query="given query")
    except Exception:
        pass
    assert searched.call_args[0][0] == "given query"
    sync.assert_not_called()


def test_the_chat_route_awaits_the_query_before_the_preface():
    import inspect
    from routes import chat_helpers
    src = inspect.getsource(chat_helpers.build_chat_context)
    assert "await generate_search_query(" in src
    assert src.index("await generate_search_query(") < src.index("build_context_preface(**_preface_kwargs)")
