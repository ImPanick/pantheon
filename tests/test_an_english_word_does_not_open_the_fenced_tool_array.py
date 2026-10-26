# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1388`: on a fenced route the only door to a `tools` array is the turn's
text asking for something an MCP server serves — and it opened on English.

`_tool_schemas_for_route`'s fenced branch asked
`any(keyword in _last_user.lower() for keyword in _MCP_KEYWORDS)`, a raw
substring, so *"eventually"* (`event`) and *"feedback"* (`feed`) sent the MCP
schemas to an Ollama endpoint that had been told nothing about MCP. The fix is
one compiled alternation, anchored at both edges of a word with each keyword's
own inflections allowed.

Driven twice (`Law 20`): the predicate over the row's table, and the real
`stream_agent_loop` on a fenced route with a registered MCP server, reading
the `tools` the request actually carried.
"""

import asyncio
import json

import pytest

import src.agent_loop as agent_loop
from src.mcp_manager import McpManager

SERVER = "abcd1234"
MCP_NAMES = {f"mcp__{SERVER}__probe_echo", f"mcp__{SERVER}__probe_inventory"}

TABLE = [
    ("I'll get to it eventually", False),
    ("thanks for the feedback", False),
    ("use my mcp server", True),
    ("open the browser", True),
    ("what's on my calendar", True),
    ("I was browsing yesterday", True),
    ("any events this week?", True),
    ("call mcp__abcd1234__probe_echo", True),
    ("tell me a joke", False),
]


@pytest.mark.parametrize("sentence,expected", TABLE)
def test_the_fenced_branch_asks_a_word_not_a_substring(sentence, expected):
    assert agent_loop._wants_mcp_schemas(sentence) is expected


def _manager():
    mgr = McpManager()
    mgr._tools[SERVER] = [
        {"name": "probe_echo", "description": "Echo text back.",
         "input_schema": {"type": "object", "properties": {"text": {"type": "string"}}}},
        {"name": "probe_inventory", "description": "List things.",
         "input_schema": {"type": "object", "properties": {}}},
    ]
    mgr._connections[SERVER] = {"status": "connected", "name": "Probe"}
    return mgr


def _tools_sent_on_a_fenced_route(monkeypatch, sentence):
    sent = []
    mgr = _manager()
    monkeypatch.setattr(agent_loop, "get_setting", lambda key, default=None: default)
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: mgr)
    monkeypatch.setattr(agent_loop, "_load_mcp_disabled_map", lambda: {})
    # An admin's turn: a non-admin's never carries the MCP manager at all.
    monkeypatch.setattr(agent_loop, "blocked_tools_for_owner", lambda owner: set())
    monkeypatch.setattr(agent_loop, "estimate_tokens", lambda *args, **kwargs: 10)
    # A fenced route: not an API model, and no `tools` array by policy.
    monkeypatch.setattr(
        agent_loop, "_agent_route_tool_mode", lambda *args, **kwargs: (False, False, False)
    )
    monkeypatch.setattr(agent_loop, "_agent_route_schema_offer", lambda *a, **k: "fenced")

    async def fake_stream(candidates, messages, **kwargs):
        sent.append(kwargs.get("tools"))
        yield 'data: {"delta": "ok"}\n\n'
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", fake_stream)

    async def _drain():
        return [
            chunk
            async for chunk in agent_loop.stream_agent_loop(
                "http://127.0.0.1:11434/v1",
                "local-model",
                [{"role": "user", "content": sentence}],
                relevant_tools={"read_file"} | MCP_NAMES,
                _is_teacher_run=True,
            )
        ]

    asyncio.run(_drain())
    assert sent, "the loop never asked the model"
    names = set()
    for tools in sent:
        for schema in tools or []:
            names.add((schema.get("function") or {}).get("name") or schema.get("name"))
    return names


@pytest.mark.parametrize("sentence", [
    "Remind me what we decided, I'll get to it eventually and plan the rest",
    "Thanks for the feedback on the draft plan, please summarise it for me",
])
def test_an_english_word_sends_no_array_to_a_fenced_route(monkeypatch, sentence):
    assert _tools_sent_on_a_fenced_route(monkeypatch, sentence) == set()


def test_asking_for_the_mcp_server_still_sends_its_tools(monkeypatch):
    names = _tools_sent_on_a_fenced_route(
        monkeypatch, "Use my mcp server to echo the words hello world back to me")
    assert MCP_NAMES <= names, names
