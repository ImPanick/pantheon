#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""check-mcp-schemas.py — one schema per tool, not one per audience.

`B74`. Thirteen tools are served by an `mcp_servers/*.py` **and** declared in
`src/tool_schemas.py`, and each carried two hand-maintained schemas until
2026-09-14. An AST comparison of all thirteen found **no pair matched**, and
what had drifted was not only wording:

  * `send_email` accepted `cc` and `bcc` in the handler and declared them on the
    server. `FUNCTION_TOOL_SCHEMAS` — the register Pantheon's own model reads —
    named neither, and neither did the system prompt's example. **The agent
    could not cc anybody**, on a capability that worked.
  * `reply_to_email` was the same story for `reply_all`.
  * `read_email` demanded `uid` in one copy while the handler also accepts
    `message_id` and the server required neither.
  * `list_emails` declared `limit` in one copy, which the handler honours, and
    the server's copy did not mention it.
  * `manage_rag`'s description carries the sentence `B66` landed to make the
    tool findable at all. The server's copy never got it.

The two copies are read by **different audiences**: `FUNCTION_TOOL_SCHEMAS` by
Pantheon, the server's `list_tools()` by any third-party MCP client pointed at
`mcp_servers/`, which `D-2026-09-14-01` made an explicitly supported way to use
these files. So the copy that rots is the one nobody here runs, and the reader
it misleads is the one least able to notice.

The fix is `src/tool_schemas.mcp_tool_schema(name)` and the servers deriving
from it. This file is what stops the second copy coming back.

The checks:

  A. Every tool a built-in server serves whose name is also in
     `FUNCTION_TOOL_SCHEMAS` is **identical** to it — description and schema.
     Compared by calling `list_tools()`, not by reading the file: a server that
     builds a schema at runtime is still serving a schema (`Law 20`).
  B. Every such tool is **derived**, not retyped — the `Tool(...)` call passes
     `mcp_tool_schema(...)` rather than a literal `name=`/`inputSchema=`. A is
     the property; B is what keeps A true the day someone pastes a schema back
     in that happens to match.
  C. A served tool with no function schema is reachable some other way, or it
     is a tool nobody can call. The five email drafting tools and
     `generate_image` are in `TOOL_TAGS` and reached through the fenced
     channel, which takes no schema — that is the legitimate shape, and this
     check is what tells it apart from a missed registration.
"""
import ast
import asyncio
import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SERVERS = ("memory_server", "rag_server", "email_server", "image_gen_server")


def _function_schemas() -> dict:
    from src.agent_tools import TOOL_TAGS  # noqa: F401 — breaks the import cycle
    from src.tool_schemas import FUNCTION_TOOL_SCHEMAS
    return {
        entry["function"]["name"]: entry["function"]
        for entry in FUNCTION_TOOL_SCHEMAS
        if entry.get("type") == "function"
    }


def _derived_names(module_name: str) -> set:
    """Names whose `Tool(...)` is built by `mcp_tool_schema`, read with `ast`."""
    source = (ROOT / "mcp_servers" / f"{module_name}.py").read_text(encoding="utf-8")
    derived = set()
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "Tool"):
            continue
        for kw in node.keywords:
            # `Tool(**mcp_tool_schema("x"))` — a starred keyword has arg None.
            if kw.arg is not None:
                continue
            call = kw.value
            if not (isinstance(call, ast.Call)
                    and getattr(call.func, "id", "") == "mcp_tool_schema"):
                continue
            if call.args and isinstance(call.args[0], ast.Constant):
                derived.add(call.args[0].value)
    return derived


def main() -> int:
    problems = []
    schemas = _function_schemas()
    from src.agent_tools import TOOL_TAGS

    shared = 0
    fenced_only = []
    for module_name in SERVERS:
        module = importlib.import_module(f"mcp_servers.{module_name}")
        derived = _derived_names(module_name)
        for tool in asyncio.run(module.list_tools()):
            if tool.name not in schemas:
                # C — no function schema. Legitimate only if the fenced channel
                # can reach it, because that channel carries no schema at all.
                if tool.name not in TOOL_TAGS:
                    problems.append(
                        f"E  {module_name} serves {tool.name!r}, which is in no "
                        f"function schema and in no tag set — nothing can call it"
                    )
                else:
                    fenced_only.append(tool.name)
                continue

            shared += 1
            declared = schemas[tool.name]
            if tool.name not in derived:
                problems.append(
                    f"E  {module_name} spells out {tool.name!r} by hand — it is "
                    f"also in FUNCTION_TOOL_SCHEMAS, so use "
                    f"Tool(**mcp_tool_schema({tool.name!r}))"
                )
            if tool.description != declared["description"]:
                problems.append(
                    f"E  {module_name}:{tool.name} description differs from "
                    f"FUNCTION_TOOL_SCHEMAS"
                )
            if tool.inputSchema != declared["parameters"]:
                problems.append(
                    f"E  {module_name}:{tool.name} schema differs from "
                    f"FUNCTION_TOOL_SCHEMAS"
                )

    if problems:
        print("mcp schemas PROBLEMS\n")
        for line in problems:
            print(f"  {line}")
        print(f"\n{len(problems)} problem(s). One schema per tool name: "
              f"`src/tool_schemas.mcp_tool_schema` is the source and the "
              f"servers derive from it.")
        return 1

    print(f"mcp schemas OK — {shared} shared tools derived from one register, "
          f"{len(fenced_only)} served without a function schema and reachable "
          f"through the fenced channel")
    return 0


if __name__ == "__main__":
    sys.exit(main())
