# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1621` — a tool reads one of the person's own chats through, bounded.

Measured before the fix: no tool read a chat. `search_chats` hands back a
match and 180 characters either side of it, and `list_sessions` the titles,
yet Decision Log, Weekly Review, FAQ Builder, Dataset Curator and Eval
Builder are hired to summarise what was said in chats — so they summarised
snippets, and a decision stated past the 180th character was not there to
find.

`read_chat` reads one chat, its messages in order, a page at a time: at most
`READ_CHAT_MAX_CHARS` a call, each message cut at
`READ_CHAT_MESSAGE_MAX_CHARS` with the cut said, and where the next page
starts. **Owner-scoped, and only that:** a chat is read only when its owner is
the caller — not a legacy chat with no owner, which `search_chats` reads and
is an admin's for that reason — and another person's chat is answered exactly
as one that does not exist. A call that names no owner reads nothing.

Driven through the real dispatcher (`execute_tool_block`) over a real SQLite
world (`evals.isolated`), and through the real harness for Decision Log, whose
file now names the tool.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta

from src.agent_tools import ToolBlock
from src.agent_tools.session_tools import (
    NO_OWNER, NOT_YOUR_CHAT, READ_CHAT_MAX_CHARS, READ_CHAT_MESSAGE_MAX_CHARS)
from src.agents import evals as E
from src.agents.catalogue import get_agent
from src.tool_capabilities import ResultIntegrity, ToolEffect, capabilities_for_action
from src.tool_execution import NO_TOOL_SECURITY_CONTEXT, execute_tool_block
from src.tool_schemas import FUNCTION_TOOL_SCHEMAS, function_call_to_tool_block

DECISION = ("We decided to go with the Lisbon flat in Alfama, because the other one had no lift "
            "and Ana's knee would not manage four floors.")


def _chat(factory, sid, owner, name, messages):
    from core.database import ChatMessage, Session
    db = factory()
    try:
        db.add(Session(id=sid, owner=owner, name=name, endpoint_url="x", model="m"))
        start = datetime(2026, 10, 20, 9, 0)
        for n, (role, content) in enumerate(messages):
            db.add(ChatMessage(id=str(uuid.uuid4()), session_id=sid, role=role, content=content,
                               timestamp=start + timedelta(minutes=n)))
        db.commit()
    finally:
        db.close()


def _read(args, owner="ann"):
    return asyncio.run(execute_tool_block(ToolBlock("read_chat", json.dumps(args)), owner=owner,
                                          security_context=NO_TOOL_SECURITY_CONTEXT))[1]


def test_the_owner_reads_their_chat_through_in_order():
    with E.isolated() as (factory, _data):
        _chat(factory, "c-ann", "ann", "Trip to Lisbon", [
            ("user", "Two flats in Lisbon — which one?"),
            ("assistant", "The Alfama one is cheaper. " + "x" * 400 + " " + DECISION)])
        out = _read({"session_id": "c-ann"})
    text = out["results"]
    assert "Trip to Lisbon" in text and "messages 1 to 2 of 2" in text
    assert text.index("[1] user") < text.index("[2] assistant")
    assert DECISION in text, "the decision past the 180th character is there to read"
    assert text.rstrip().endswith("That is the end of the chat.")


def test_another_persons_chat_is_answered_as_one_that_is_not_there():
    with E.isolated() as (factory, _data):
        _chat(factory, "c-bob", "bob", "Bob's salary talk", [("user", "My salary is 90k")])
        _chat(factory, "c-legacy", None, "From before accounts", [("user", "old words")])
        theirs = _read({"session_id": "c-bob"})
        legacy = _read({"session_id": "c-legacy"})
        missing = _read({"session_id": "no-such-chat"})
        nobody = _read({"session_id": "c-bob"}, owner=None)
    for refused in (theirs, legacy, missing):
        assert refused.get("error") == NOT_YOUR_CHAT, refused
        assert "90k" not in json.dumps(refused) and "old words" not in json.dumps(refused)
    assert nobody.get("error") == NO_OWNER


def test_a_long_chat_comes_in_bounded_pages_that_say_where_the_next_starts():
    long = [("user" if n % 2 == 0 else "assistant", f"message {n + 1}: " + "y" * 1500) for n in range(40)]
    huge = [("user", "z" * (READ_CHAT_MESSAGE_MAX_CHARS + 5000))]
    with E.isolated() as (factory, _data):
        _chat(factory, "c-long", "ann", "A long one", long)
        _chat(factory, "c-huge", "ann", "One huge message", huge)
        first = _read({"session_id": "c-long"})
        nxt = first["shown"][1] + 1
        second = _read({"session_id": "c-long", "from": nxt})
        one = _read({"session_id": "#session-c-huge"})      # a link from list_sessions reads too
    assert first["shown"][0] == 1 and 1 < nxt <= 40
    assert len(first["results"]) <= READ_CHAT_MAX_CHARS + 2000
    assert f'"from": {nxt}' in first["results"] and "are not shown" in first["results"]
    assert f"message {nxt}:" in second["results"] and f"message {nxt - 1}:" not in second["results"]
    assert "5,000 more characters of this message are not shown" in one["results"]


def test_it_is_a_read_of_private_data_whose_result_is_data():
    caps = capabilities_for_action("read_chat", json.dumps({"session_id": "c"}))
    assert caps.effects == {ToolEffect.READ_PRIVATE}
    assert caps.result_integrity is ResultIntegrity.EXTERNAL_UNTRUSTED
    assert any(s["function"]["name"] == "read_chat" for s in FUNCTION_TOOL_SCHEMAS)
    block = function_call_to_tool_block("read_chat", {"session_id": "c1", "from": 3})
    assert block.tool_type == "read_chat" and json.loads(block.content) == {"session_id": "c1", "from": 3}


def test_decision_log_reads_the_whole_chat_in_its_world(monkeypatch):
    """The real harness: Decision Log's kit has `read_chat`, and the model is
    handed the chat whole — the decision and its why, not a snippet."""
    import src.tool_execution as tool_execution
    seen = []
    real = tool_execution._execute_tool_block_impl

    async def spy(block, *a, **kw):
        out = await real(block, *a, **kw)
        seen.append((block.tool_type, out[1] if isinstance(out, tuple) else out))
        return out

    monkeypatch.setattr(tool_execution, "_execute_tool_block_impl", spy)
    m = get_agent(None, "decision-log")
    assert "read_chat" in m.tools
    case = {
        "id": "a-decision-read-whole",
        "world": {"chats": [{"id": "c-lisbon", "title": "Trip to Lisbon", "messages": [
            {"role": "user", "content": "Two flats in Lisbon — which one?"},
            {"role": "assistant", "content": "Comparing them. " + "x" * 400 + " " + DECISION}]}]},
        "script": [{"call": [["read_chat", {"session_id": "c-lisbon"}]]}, {"say": "Done."}],
        "checks": [{"called": "read_chat"}],
    }
    asyncio.run(E.run_agent(m, cases=[case]))
    results = [json.dumps(r, ensure_ascii=False) for t, r in seen if t == "read_chat"]
    assert results and "Ana's knee" in results[0], results
