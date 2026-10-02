# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1107` — auto-memory's extraction sent the last six messages whole.

`services/memory/memory_extractor.extract_and_store` flattens the last
`CONTEXT_WINDOW` (6) messages into one user message, with no bound, and sends it
to the chat's endpoint at `max_tokens=4096` with no `max_tokens_floor`. So a
long reply made a server that holds a request to its window refuse it, and the
pass logged a warning and kept only `_fallback_memory_candidates` — a handful of
regexes — instead: nothing the person sees, and worse memory. **Measured by
`w9-llm`** through the real app against the showcase's scripted model served as
vLLM serves a 20,000 window: after a 72,548-character reply the extraction
request was refused (`4096 > 20000 - 19364`); after 58,036 it was accepted.
Re-measured here on `7a7f9b2` through `extract_and_store` itself — the same
72,548-character reply, the same window: one request, refused
(`4096 > 20000 - 18537`), the warning logged; and on a 5,000 window with room
for the chat but not the reply, refused (`4096 > 5000 - 1400`) and never sent
again.

The transcript is now held to the room the endpoint's proven window leaves
(`budget_context_for_model`, the agent path's own reading of it) after the
reply's — every message kept, the longest cut in the middle first, so the
person's own words survive a long answer — and the call opts in to `B1029`'s
resend (`max_tokens_floor`), so a server with room for the transcript but not
for the reply is asked for what fits.

`Law 20`: `extract_and_store` is called as the chat path calls it, and its
request goes over a real socket to `demo_model.DemoModel` with a window; only
the chat session is a plain object holding the messages.
"""
from __future__ import annotations

import logging
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "showcase"))

import demo_model  # noqa: E402

WINDOW = 20_000
LONG_REPLY = 72_548        # the reply `w9-llm` measured refused on this window
ASK = "Plan the move of the billing tables to the new cluster this weekend."
FOLLOW = "Thanks. Keep the rollback notes to one page and put them first."


def _long_reply(chars: int) -> str:
    line = "Step: copy the next shard, check its row counts, then switch its reads over. "
    return (line * (chars // len(line) + 1))[:chars]


def _chat(reply: str) -> list:
    return [
        {"role": "user", "content": ASK},
        {"role": "assistant", "content": reply},
        {"role": "user", "content": FOLLOW},
        {"role": "assistant", "content": "Done — the rollback notes are first."},
    ]


@pytest.fixture
def fresh_clients(monkeypatch):
    """`llm_core`'s shared clients are made inside this test's own event loop
    (and closed in it, by `_extract`); nothing a server stated is carried in."""
    from src import llm_core

    monkeypatch.setattr(llm_core, "_http_client", None)
    monkeypatch.setattr(llm_core, "_direct_clients", {})
    monkeypatch.setattr(llm_core, "_stated_windows", {})


async def _extract(model, messages):
    """One auto-memory pass over `messages`, as the chat path runs it. Answers
    what the model was sent for it."""
    from services.memory.memory_extractor import extract_and_store

    session = SimpleNamespace(owner="", get_context_messages=lambda: list(messages))
    from src import llm_core

    start = len(model.log)
    try:
        await extract_and_store(session, memory_manager=None, memory_vector=None,
                                endpoint_url=model.base_url, model=demo_model.MODEL_ID)
    finally:
        for client in [llm_core._http_client, *llm_core._direct_clients.values()]:
            if client is not None and not client.is_closed:
                await client.aclose()
    return [e for e in model.log[start:]
            if "memory extraction assistant" in str(e["messages"][0].get("content"))]


class _Model:
    def __init__(self, window):
        self.log: list = []
        self._served = demo_model.DemoModel(log=self.log, max_model_len=window)

    def __enter__(self):
        self._served.__enter__()
        self.base_url = self._served.base_url
        return self

    def __exit__(self, *exc):
        self._served.__exit__(*exc)


def _transcript(request) -> str:
    return request["messages"][-1]["content"]


def _failed(caplog) -> list:
    return [r.getMessage() for r in caplog.records
            if "memory extraction failed" in r.getMessage()]


@pytest.mark.asyncio
async def test_after_a_reply_longer_than_the_window_the_extraction_is_sent_inside_it(
        fresh_clients, caplog):
    """The row's `Verify:` — after a reply longer than the window, the
    extraction request is sent inside it and answered: once, not refused, no
    fall-back to the heuristics. The person's words are there whole; the long
    reply keeps its beginning and end and says what was left out."""
    caplog.set_level(logging.INFO)
    with _Model(WINDOW) as model:
        sent = await _extract(model, _chat(_long_reply(LONG_REPLY)))
    assert len(sent) == 1, [(e["max_tokens"], bool(e.get("refused"))) for e in sent]
    assert not sent[0].get("refused"), sent[0].get("refused")
    assert not _failed(caplog)
    transcript = _transcript(sent[0])
    assert f"user: {ASK}" in transcript and f"user: {FOLLOW}" in transcript
    assert "left out" in transcript
    reply = _long_reply(LONG_REPLY)
    assert reply[:200] in transcript and reply[-80:] in transcript
    assert len(transcript) < LONG_REPLY


@pytest.mark.asyncio
async def test_a_transcript_that_fits_is_sent_whole(fresh_clients):
    """What does not move: a conversation the window holds is sent exactly as
    it was flattened before — every message whole, in order."""
    messages = _chat("Copy shard by shard; switch reads per shard.")
    with _Model(WINDOW) as model:
        sent = await _extract(model, messages)
    assert len(sent) == 1 and not sent[0].get("refused")
    flattened = "\n\n".join(f"{m['role']}: {m['content']}" for m in messages)
    assert _transcript(sent[0]) == (
        "Conversation to analyze:\n\n" + flattened
        + "\n\nReturn the JSON array of durable facts now (or [] if none).")


@pytest.mark.asyncio
async def test_room_for_the_chat_but_not_the_reply_is_asked_for_what_fits(
        fresh_clients, caplog):
    """The resend's opt-in (`max_tokens_floor`): a 5,000 window holds this
    chat but not the chat plus 4,096 for the answer. Refused once, sent again
    asking for exactly what the server can serve, answered — where before the
    refusal was the end of it and the heuristics stood in."""
    caplog.set_level(logging.INFO)
    with _Model(5_000) as model:
        sent = await _extract(model, _chat(_long_reply(4_000)))
    assert len(sent) == 2, [(e["max_tokens"], bool(e.get("refused"))) for e in sent]
    refused, resent = sent
    assert refused["max_tokens"] == 4096 and refused.get("refused")
    window = int(re.search(r"maximum context length is (\d+)", refused["refused"]).group(1))
    prompt = int(re.search(r"your request has (\d+) input tokens", refused["refused"]).group(1))
    assert resent["max_tokens"] == window - prompt < 4096
    assert not resent.get("refused") and resent["messages"] == refused["messages"]
    assert not _failed(caplog)


@pytest.mark.asyncio
async def test_a_window_nobody_stated_is_not_guessed(fresh_clients):
    """A server that reports no window and takes any length is sent the whole
    transcript, as before — the bound is applied only against a window the
    endpoint proved (`budget_context_for_model` answers 0 otherwise)."""
    reply = _long_reply(LONG_REPLY)
    with _Model(None) as model:
        sent = await _extract(model, _chat(reply))
    assert len(sent) == 1 and not sent[0].get("refused")
    assert reply in _transcript(sent[0])
