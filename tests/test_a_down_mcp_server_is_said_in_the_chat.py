# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1326`: a registered MCP server that is down says so in the chat.

`B1307` tells the model, in its prompt, and `GET /api/mcp/servers` has always
told Settings. Neither put a line in front of a person who is in a chat,
asking for a tool, and getting an answer that does not mention the server —
measured, zero SSE events of any kind about a server in `status: "error"`.

The line is an agent note (`mcp_unavailable`, in `AGENT_NOTE_TYPES` on both
sides), so it rides the scaffolding every other note does (`Law 14`): the
loop sends it once, before the turn's first step; the route keeps it
(`AgentNotes`) and saves it with the reply; the reload draws it with the same
builder the live stream uses (`renderAgentNote`). The list of down servers is
the manager's own (`servers_not_answering`), the one the prompt block reads.

Driven end to end (`Law 20`): a real stdio server whose command is
`/bin/false`, connected through the real `McpManager.connect_server`; the real
loop; the real route and `save_assistant_response`; the real `addMessage`
under node. The live and resumed arms are driven in
`tests/test_a_resumed_stream_draws_what_the_live_one_drew.py`.
"""
import asyncio
import json
import shutil
from pathlib import Path

import pytest

import src.agent_loop as agent_loop
from src.agent_stops import AgentNotes
from src.mcp_manager import McpManager
from test_a_reload_keeps_the_turns_notes import _PAGE, _saved_through_route  # noqa: E402
from test_a_reload_keeps_the_turns_notes import sandbox  # noqa: E402,F401  (the fixture)
from test_tool_effect_surfaces_js import _run  # noqa: E402

pytest.importorskip("mcp")

ROOT = Path(__file__).resolve().parents[1]
node_only = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


@pytest.fixture(scope="module")
def dead_manager():
    """A manager holding one registered stdio server whose command exits at
    once — the typo'd command a person actually registers."""
    manager = McpManager()

    async def connect():
        return await manager.connect_server(
            server_id="dead-1", name="Typo server", transport="stdio",
            command="/bin/false", args=[], env={})

    assert asyncio.run(connect()) is False
    assert manager.get_server_status("dead-1")["status"] == "error"
    return manager


def _turn(monkeypatch, manager, *, session_id, blocked=()):
    monkeypatch.setattr(agent_loop, "get_setting", lambda k, d=None: d, raising=False)
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: manager, raising=False)
    monkeypatch.setattr(agent_loop, "_load_mcp_disabled_map", lambda: {}, raising=False)
    monkeypatch.setattr(agent_loop, "estimate_tokens", lambda *a, **k: 10, raising=False)
    monkeypatch.setattr(agent_loop, "blocked_tools_for_owner",
                        lambda owner: set(blocked), raising=False)

    async def fake_stream(*_a, **_k):
        yield f"data: {json.dumps({'delta': 'I looked it up another way.'})}\n\n"
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", fake_stream, raising=False)

    async def drain():
        return [c async for c in agent_loop.stream_agent_loop(
            "http://local.test/v1", "small-local-model",
            [{"role": "user", "content": "look up the release notes with my wiki tool"}],
            max_rounds=2, relevant_tools={"update_plan"}, session_id=session_id)]

    return asyncio.run(drain())


def _notes(chunks):
    out = []
    for c in chunks:
        if c.startswith("data: {"):
            data = json.loads(c[6:])
            if data.get("type") == "mcp_unavailable":
                out.append(data)
    return out


def test_a_turn_with_a_down_server_says_so_once_before_its_first_step(monkeypatch, dead_manager):
    agent_loop._MCP_DOWN_NOTED.clear()
    chunks = _turn(monkeypatch, dead_manager, session_id="chat-a")
    (note,) = _notes(chunks)
    (server,) = note["servers"]
    assert server["name"] == "Typo server"
    assert server["reason"].strip(), "a person cannot act on a note with no reason"
    # Before the turn's first step: it shaped what the turn could do.
    first = next(i for i, c in enumerate(chunks) if '"mcp_unavailable"' in c)
    budget = next(i for i, c in enumerate(chunks) if '"agent_budget"' in c)
    assert first < budget


def test_the_same_chat_is_told_once_and_another_chat_is_told_too(monkeypatch, dead_manager):
    agent_loop._MCP_DOWN_NOTED.clear()
    assert len(_notes(_turn(monkeypatch, dead_manager, session_id="chat-b"))) == 1
    assert _notes(_turn(monkeypatch, dead_manager, session_id="chat-b")) == []
    assert len(_notes(_turn(monkeypatch, dead_manager, session_id="chat-c"))) == 1


def test_a_chat_whose_servers_all_answer_hears_nothing(monkeypatch):
    agent_loop._MCP_DOWN_NOTED.clear()
    up = McpManager()
    up._connections["live-1"] = {"status": "connected", "name": "Wiki"}
    up._tools["live-1"] = [{"name": "lookup", "description": "", "input_schema": {}}]
    assert _notes(_turn(monkeypatch, up, session_id="chat-d")) == []


def test_a_non_admin_turn_carries_no_mcp_and_no_note(monkeypatch, dead_manager):
    """A non-admin's turn drops the manager entirely (the namespace is refused
    them), so there is nothing of theirs to be down."""
    agent_loop._MCP_DOWN_NOTED.clear()
    from src.tool_security import NON_ADMIN_BLOCKED_TOOLS
    chunks = _turn(monkeypatch, dead_manager, session_id="chat-e", blocked=NON_ADMIN_BLOCKED_TOOLS)
    assert _notes(chunks) == []


def test_the_route_saves_it_with_the_reply_before_the_first_round(monkeypatch, dead_manager):
    agent_loop._MCP_DOWN_NOTED.clear()
    chunks = _turn(monkeypatch, dead_manager, session_id="chat-f")
    saved = _saved_through_route(monkeypatch, chunks)
    assert len(saved) == 1
    (note,) = [n for n in saved[0].get("agent_notes") or [] if n["type"] == "mcp_unavailable"]
    assert note["round"] == 0
    assert note["servers"][0]["name"] == "Typo server"


def test_the_collector_places_it_before_the_first_round():
    notes = AgentNotes()
    notes.observe({"type": "mcp_unavailable", "servers": [{"name": "S", "reason": "gone"}]})
    notes.observe({"type": "agent_step", "round": 2})
    assert notes.saved() == [{"type": "mcp_unavailable",
                              "servers": [{"name": "S", "reason": "gone"}], "round": 0}]


@node_only
def test_the_reload_draws_it_above_the_reply_as_text(sandbox):  # noqa: F811
    out = _run(sandbox, "", _PAGE + """
        addMessage('assistant', 'I looked it up another way.', 'm', {
          round_texts: ['I looked it up another way.'],
          agent_notes: [{ type: 'mcp_unavailable', round: 0, servers: [
            { name: 'Typo <b>server</b>', reason: 'Connection closed' }] }],
        });
        const notes = history.querySelectorAll('.mcp-unavailable-note');
        console.log(JSON.stringify({
          order: history.children.map((n) => String(n.className || '')),
          text: notes.map((n) => n.textContent.replace(/\\s+/g, ' ').trim()),
          markup: notes.flatMap((n) => n._walk([]).filter((c) => c._html).map((c) => c._html)),
        }));
    """)
    assert out["markup"] == [], "a server's name or error was assigned as markup"
    assert out["text"] == [
        "MCP server not answering: Typo <b>server</b> — Connection closed. Its tools are "
        "not in this chat; the Workbench’s MCP & Integrations room shows it."]
    note_at = next(i for i, c in enumerate(out["order"]) if "mcp-unavailable-note" in c)
    reply_at = next(i for i, c in enumerate(out["order"]) if "msg-ai" in c)
    assert note_at < reply_at, out["order"]
