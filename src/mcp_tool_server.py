# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B621`. Where Pantheon's own MCP servers meet the SDK's server API — once.

The four built-in servers under `mcp_servers/` and the workstation relay
(`src/workstation_mcp.py`'s `build_relay`) each registered two functions with
mcp 1.x's decorators, `@server.list_tools()` and `@server.call_tool()`. mcp 2.x
removed both: `mcp.server.lowlevel.Server` takes `on_list_tools=` and
`on_call_tool=` handlers of `(ctx, params)` in its constructor, and every one
of the five died at import with `'Server' object has no attribute
'list_tools'` — in a fresh process as well as under pytest, which is the exact
condition `src/builtin_mcp.py` spawns them under.

The servers keep their two functions exactly as they were — `list_tools()`
returning `Tool`s and `call_tool(name, arguments)` returning content — because
those are what a test, `.pantheon/check-mcp-schemas.py` and `src/agents/evals.py`
call directly. What changed is only how they are handed to the SDK, and that is
this module.

**Three things the v1 decorator did that the v2 handler does not**, kept here
because each one is behaviour a caller could see:

1. **Input validation.** v1 checked `arguments` against the tool's
   `inputSchema` (jsonschema) before the tool ran and answered
   ``Input validation error: …`` as an error result. A v2 low-level server
   calls the handler with whatever arrived. ``validate_input=False`` is the
   relay's opt-out, as it was (`D-2026-09-27-02`: the server in the workstation
   enforces its own schema).
2. **A raised exception is an error result, not a protocol error.** v1 caught
   whatever the tool raised and answered ``isError`` with ``str(exc)``, which
   `McpManager.call_tool` hands the model as the tool's own words. Without it a
   v2 server answers a JSON-RPC error, and the client raises instead.
3. **A list of content is a result.** v1 wrapped a returned list in a
   `CallToolResult`; a v2 handler must return one.

The tool definitions are cached from the last `tools/list`, and a call for a
name not in the cache lists once more first — v1's `_get_cached_tool_definition`.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, Iterable, List


def _error_result(text: str):
    import mcp.types as types
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)],
                                is_error=True)


def tool_server(
    name: str,
    list_tools: Callable[[], Awaitable[List[Any]]],
    call_tool: Callable[[str, Dict[str, Any]], Awaitable[Any]],
    *,
    validate_input: bool = True,
    version: str = "",
):
    """An SDK `Server` named *name* that serves *list_tools* and *call_tool*.

    *list_tools* returns `mcp.types.Tool`s; *call_tool* returns an iterable of
    content blocks or a whole `CallToolResult`, as v1's decorator accepted.
    """
    import jsonschema
    import mcp.types as types
    from mcp.server.lowlevel import Server

    cache: Dict[str, Any] = {}

    async def _listed() -> List[Any]:
        tools = list(await list_tools())
        cache.clear()
        cache.update({tool.name: tool for tool in tools})
        return tools

    async def _on_list_tools(ctx, params) -> "types.ListToolsResult":
        return types.ListToolsResult(tools=await _listed())

    async def _on_call_tool(ctx, params) -> "types.CallToolResult":
        tool_name = params.name
        arguments = params.arguments or {}
        try:
            if validate_input:
                if tool_name not in cache:
                    await _listed()
                tool = cache.get(tool_name)
                if tool is not None:
                    try:
                        jsonschema.validate(instance=arguments, schema=tool.input_schema)
                    except jsonschema.ValidationError as exc:
                        return _error_result(f"Input validation error: {exc.message}")
            results = await call_tool(tool_name, arguments)
            if isinstance(results, types.CallToolResult):
                return results
            return types.CallToolResult(content=_content(results), is_error=False)
        except Exception as exc:   # (2) above: the tool's failure, in its own words
            return _error_result(str(exc))

    return Server(name, version=version, on_list_tools=_on_list_tools,
                  on_call_tool=_on_call_tool)


def _content(results: Any) -> List[Any]:
    """(3) above. v1 took any iterable of content blocks; a bare string is
    iterable too, and is not one."""
    if isinstance(results, (str, bytes, dict)) or not isinstance(results, Iterable):
        raise TypeError(f"Unexpected return type from tool: {type(results).__name__}")
    return list(results)


async def serve_stdio(server) -> None:
    """Serve *server* over this process's stdin and stdout until the client
    closes them — the one way `McpManager` starts a built-in server."""
    from mcp.server.stdio import stdio_server
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


__all__ = ["serve_stdio", "tool_server"]
