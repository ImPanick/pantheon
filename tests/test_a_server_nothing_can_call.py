# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B67` / `D-2026-09-14-01` — the `memory` MCP server stops being spawned.

It was connected on every startup and served zero calls, because nothing could
produce the name `mcp__memory__manage_memory`: `manage_memory` dispatches
in-process, has no `_MCP_TOOL_MAP` entry, and no `mcp__*` name is in
`TOOL_TAGS`. Routing to it instead — `B66`'s answer for `manage_rag` — was
rejected because the main process holds its own `MemoryVectorStore`, so a
write in the subprocess would leave this process's index stale.

These tests hold the two halves that can rot: that nothing reconnects it, and
that the *premise* of the decision (the two forms are the same size, so
routing gains nothing) is still true. The premise test is the one that matters
— if someone adds an action to one form and not the other, the reason this
server was disconnected has quietly stopped applying, and a test that only
checked the dict would still pass.
"""
import ast
import asyncio
from pathlib import Path

import pytest

import mcp_servers.memory_server as memory_server
from src.agent_tools import TOOL_TAGS
from src.builtin_mcp import _BUILTIN_SERVERS
from src.tool_execution import _MCP_TOOL_MAP
from src.tool_schemas import FUNCTION_TOOL_SCHEMAS


def _function_schema(name):
    for entry in FUNCTION_TOOL_SCHEMAS:
        if entry.get("type") == "function" and entry["function"]["name"] == name:
            return entry["function"]
    raise AssertionError(f"{name} is not in FUNCTION_TOOL_SCHEMAS")


def test_pantheon_does_not_spawn_the_memory_server():
    assert "memory" not in _BUILTIN_SERVERS
    assert set(_BUILTIN_SERVERS) == {"image_gen", "rag", "email"}


def test_the_file_is_still_there_and_is_not_referenced_as_a_built_in():
    # `Law 1` — we add, never subtract. The server is unspawned, not deleted.
    assert Path("mcp_servers/memory_server.py").is_file()
    for _script, _label in _BUILTIN_SERVERS.values():
        assert "memory_server" not in _script


def test_nothing_could_ever_have_called_it():
    # The reason it served zero calls is readable in the dispatch chain, and
    # it is not "nobody wanted it".
    assert "manage_memory" not in _MCP_TOOL_MAP
    assert not [t for t in _MCP_TOOL_MAP.values() if t[0] == "memory"]
    assert not [name for name in TOOL_TAGS if name.startswith("mcp__memory")]


def test_the_capability_a_person_can_reach_did_not_go_away():
    # `manage_memory` is offered and dispatched exactly as before.
    assert "manage_memory" in TOOL_TAGS
    assert _function_schema("manage_memory")
    from src import ai_interaction
    assert callable(ai_interaction.do_manage_memory)


def test_manage_memory_still_answers_through_the_native_path(monkeypatch):
    from src import ai_interaction

    class StubManager:
        def load(self, owner=None):
            return [{"id": "abcd1234", "text": "the kettle is descaled monthly",
                     "category": "fact"}]

    monkeypatch.setattr(ai_interaction, "_memory_manager", StubManager(), raising=False)

    result = asyncio.run(ai_interaction.do_manage_memory("list"))
    assert isinstance(result, dict)
    assert "descaled" in str(result)


# --- the premise: routing would gain nothing --------------------------------

def _server_tool(name):
    tools = asyncio.run(memory_server.list_tools())
    for tool in tools:
        if tool.name == name:
            return tool
    raise AssertionError(f"{name} is not served by memory_server.list_tools()")


def test_the_two_forms_offer_the_same_actions():
    served = _server_tool("manage_memory").inputSchema
    native = _function_schema("manage_memory")["parameters"]
    assert served["properties"]["action"]["enum"] == native["properties"]["action"]["enum"]


def test_the_two_forms_take_the_same_parameters():
    served = _server_tool("manage_memory").inputSchema
    native = _function_schema("manage_memory")["parameters"]
    assert set(served["properties"]) == set(native["properties"])
    assert set(served["required"]) == set(native["required"])
    for prop, spec in served["properties"].items():
        assert spec["type"] == native["properties"][prop]["type"], prop
        assert spec.get("enum") == native["properties"][prop].get("enum"), prop


def test_the_server_still_works_on_its_own_terms():
    # "The file stays and stays supported" is a claim about behaviour, so it
    # is tested by running the server rather than by reading it.
    tool = _server_tool("manage_memory")
    assert tool.description
    unknown = asyncio.run(memory_server.call_tool("no_such_tool", {}))
    assert "Unknown tool" in unknown[0].text


def test_the_cost_that_made_routing_a_regression_is_still_there():
    # The decision rests on the main process holding its own vector store for
    # the process lifetime. Read it as code, not as a string: if
    # `initialize_app` stops constructing `MemoryVectorStore`, the stale-index
    # argument evaporates and `D-2026-09-14-01` says that reopens the choice.
    tree = ast.parse(Path("src/app_initializer.py").read_text())
    constructed = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "MemoryVectorStore" in constructed


@pytest.mark.parametrize("doc_claim", [
    "does not spawn",
    "PANTHEON_MCP_MEMORY_OWNER",
])
def test_the_server_tells_the_next_reader_how_to_start_it(doc_claim):
    # A server that used to be started for you and now is not has to say so
    # in the place someone opening the file will look.
    assert doc_claim in (memory_server.__doc__ or "")


# --- the second list, which said "memory" for a day ------------------------

def test_is_builtin_is_derived_and_not_restated():
    """`Law 13`. The set of built-in servers lived in two places — the dict in
    `builtin_mcp.py` and a literal in `McpManager.is_builtin` — and removing
    `memory` from one left the other saying `True` about a server Pantheon does
    not run.

    That is not cosmetic. `is_builtin` **mutes a server**: built-in Python
    servers are skipped from `get_all_openai_schemas` and from
    `get_tool_descriptions_for_prompt`. An operator registering their own
    server under the id `memory` — the id the canonical upstream memory server
    uses — would have had its tools hidden from both call channels with no
    error, which is `B66`'s failure mode exactly.
    """
    from src.mcp_manager import McpManager
    manager = McpManager.__new__(McpManager)

    assert not manager.is_builtin("memory")
    for server_id in _BUILTIN_SERVERS:
        assert manager.is_builtin(server_id), server_id
    assert manager.is_builtin("builtin_browser")
    assert not manager.is_builtin("a_server_the_operator_added")


def test_a_muted_server_is_what_is_builtin_costs():
    """Pins the consequence, so the test above is not a tautology about a dict.

    A server `is_builtin` calls True is dropped from the function schemas; one
    it calls False is kept. If that stops being true, the divergence above
    stops mattering and this test should be the thing that says so.
    """
    from src.mcp_manager import McpManager

    manager = McpManager.__new__(McpManager)
    manager._tools = {
        "memory": [{"name": "manage_memory", "description": "d", "inputSchema": {}}],
        "rag": [{"name": "manage_rag", "description": "d", "inputSchema": {}}],
    }
    manager._connections = {
        "memory": {"name": "Someone's memory server", "status": "connected"},
        "rag": {"name": "Built-in: RAG", "status": "connected"},
    }

    names = {s["function"]["name"] for s in manager.get_all_openai_schemas({})}
    assert any("manage_memory" in n for n in names), names
    assert not any("manage_rag" in n for n in names), names
