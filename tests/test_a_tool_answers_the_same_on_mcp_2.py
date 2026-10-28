# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B621`. What a tool answers reaches the model the same way on mcp 2.x.

mcp 2.x is not a rename of 1.x. Three things the 1.x server decorator did for
free are gone from the 2.x low-level `Server`, and the SDK's models moved their
attributes to snake_case, keeping the camelCase only as aliases for the wire.
Each one is a way a working product goes quietly wrong rather than loudly:

* a tool that **raises** used to answer `isError` with its own words; a 2.x
  handler that raises answers a protocol error instead;
* a call with arguments its schema refuses used to be answered `Input
  validation error: …` before the tool ran; 2.x runs the tool;
* `getattr(result, "isError", False)` is `False` for every 2.x result — every
  failing tool reaches the model as a success;
* a tool's annotations dumped without `by_alias` come back `read_only_hint`,
  and plan mode, which reads `readOnlyHint`, sees nothing.

So each is driven here end to end on the installed SDK: the real
`src/mcp_tool_server.tool_server`, a real `ClientSession` over the SDK's own
in-memory streams, and the real `McpManager.call_tool` reading the answer.
"""
import asyncio

import pytest

from src.mcp_manager import McpManager, _tool_entries, mcp_tool_is_readonly
from src.mcp_tool_server import tool_server

SCHEMA = {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}


def _tools():
    import mcp.types as types
    return [
        types.Tool(name="double", description="Doubles n.", inputSchema=SCHEMA,
                   annotations=types.ToolAnnotations(readOnlyHint=True)),
        types.Tool(name="explode", description="Always fails.", inputSchema={"type": "object"}),
    ]


async def _list_tools():
    return _tools()


async def _call_tool(name, arguments):
    import mcp.types as types
    if name == "explode":
        raise RuntimeError("the disk is full")
    return [types.TextContent(type="text", text=str(arguments["n"] * 2))]


def _through_the_manager(server, calls):
    """Run *calls* — `(tool, arguments)` pairs — through `McpManager.call_tool`
    against *server*, both ends real, and return what the manager answered."""
    from mcp import ClientSession
    from mcp.shared.memory import create_client_server_memory_streams

    async def go():
        async with create_client_server_memory_streams() as (client, srv):
            async def serve():
                await server.run(srv[0], srv[1], server.create_initialization_options())

            task = asyncio.ensure_future(serve())
            try:
                async with ClientSession(client[0], client[1]) as session:
                    await session.initialize()
                    listed = await session.list_tools()
                    mgr = McpManager()
                    mgr._sessions["b621mem"] = session
                    mgr._connections["b621mem"] = {"status": "connected", "name": "mem"}
                    answers = [await mgr.call_tool(f"mcp__b621mem__{tool}", args)
                               for tool, args in calls]
                    return listed, answers
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    return asyncio.run(go())


def test_a_tool_that_answers_is_a_success():
    _, [answer] = _through_the_manager(tool_server("t", _list_tools, _call_tool),
                                       [("double", {"n": 21})])
    assert answer["exit_code"] == 0 and answer["stdout"] == "42", answer


def test_a_tool_that_raises_is_a_failure_in_its_own_words():
    _, [answer] = _through_the_manager(tool_server("t", _list_tools, _call_tool),
                                       [("explode", {})])
    assert answer["exit_code"] == 1, answer
    assert answer["stderr"] == "the disk is full" and answer["stdout"] == "", answer
    assert answer.get("untrusted_content") is True


def test_arguments_the_schema_refuses_never_reach_the_tool():
    ran = []

    async def call(name, arguments):
        ran.append(arguments)
        return await _call_tool(name, arguments)

    _, [answer] = _through_the_manager(tool_server("t", _list_tools, call),
                                       [("double", {"n": "lots"})])
    assert ran == []
    assert answer["exit_code"] == 1 and answer["stderr"].startswith("Input validation error"), answer


def test_a_server_that_validates_its_own_input_is_not_second_guessed():
    """The workstation relay's opt-out (`validate_input=False`): the server in
    the workstation is the judge of its own schema (`D-2026-09-27-02`)."""
    ran = []

    async def call(name, arguments):
        ran.append(arguments)
        import mcp.types as types
        return [types.TextContent(type="text", text="passed through")]

    _, [answer] = _through_the_manager(
        tool_server("t", _list_tools, call, validate_input=False), [("double", {"n": "lots"})])
    assert ran == [{"n": "lots"}] and answer["stdout"] == "passed through", answer


def test_an_error_result_the_sdk_built_is_read_as_one():
    """The manager's read, apart from the server: a 2.x `CallToolResult` with
    its error flag set, as any third-party server sends it."""
    import mcp.types as types

    class _Session:
        async def call_tool(self, name, arguments, read_timeout_seconds=None):
            return types.CallToolResult(
                content=[types.TextContent(type="text", text="quota exceeded")], isError=True)

    mgr = McpManager()
    mgr._sessions["b621err"] = _Session()
    mgr._connections["b621err"] = {"status": "connected", "name": "err"}
    answer = asyncio.run(mgr.call_tool("mcp__b621err__anything", {}))
    assert answer["exit_code"] == 1 and answer["stderr"] == "quota exceeded", answer


def test_annotations_keep_the_protocols_names_and_plan_mode_reads_them():
    listed, _ = _through_the_manager(tool_server("t", _list_tools, _call_tool), [])
    entries = {e["name"]: e for e in _tool_entries(listed)}
    assert entries["double"]["annotations"] == {"readOnlyHint": True}, entries["double"]
    assert entries["double"]["input_schema"] == SCHEMA
    assert mcp_tool_is_readonly(entries["double"]) is True
    assert entries["explode"]["annotations"] is None


@pytest.mark.parametrize("returned", ["a bare string", {"a": "dict"}, 42])
def test_a_tool_that_returns_no_content_is_a_failure_not_a_crash(returned):
    async def call(name, arguments):
        return returned

    _, [answer] = _through_the_manager(tool_server("t", _list_tools, call), [("explode", {})])
    assert answer["exit_code"] == 1 and "Unexpected return type" in answer["stderr"], answer
