#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""check-tool-surface.py — a tool name has to be registered in every register.

`P17-06` asked for "the rule that decides where a new capability goes". Counting
the surface first produced a different and better answer: **the native-vs-MCP
question is not where the defects come from.** A tool name has to appear in up to
eight independent places, and a name missing from any one of them fails silently
and differently:

  1. `TOOL_TAGS`                    src/agent_tools/__init__.py  — the fence gate
  2. `FUNCTION_TOOL_SCHEMAS`        src/tool_schemas.py          — the function-call channel
  3. a dispatch branch              src/tool_execution.py        — or `_MCP_TOOL_MAP`/`TOOL_HANDLERS`
  4. `TOOL_CAPABILITIES`            src/tool_capabilities.py     — the approval card
  5. `_FEATURE_TOOLS`               src/tool_security.py         — the operator's feature flag
  6. the `disable_tool` group alias src/agent_tools/admin_tools.py
  7. the system prompt              src/agent_loop.py
  8. the MCP server, when it has one
  9. `BUILTIN_TOOL_DESCRIPTIONS`    src/tool_index.py            — agent-mode tool retrieval

This has now shipped four times, and the fourth was found by the ninth register
while this checker was being written — which is the argument for the checker,
made by the surface itself. `TOOL_TAGS` carries a comment about two of them: the
whole cookbook family, then `tail_serve_output`, which the system prompt
*ordered* the agent to call after every serve. `tool_index.py`'s parity test
carries a third in its docstring — *"api_call was missing exactly this way"* —
and agent mode selects tools by embedding those descriptions, so a schema
without one can never be retrieved and the model is never shown it. `B66` is the
fourth:
`manage_rag` was named twice in the prompt and was in no tag set, so
`parse_tool_blocks` returned `[]`, no `ToolBlock` was ever built, and not even
the "Unknown tool" branch ran — no error, no `events` row, and the raw fence left
visible in the reply while the agent said it had stored the data.

`Law 13` says a feature set in one of N places is the defect class. The rule that
prevents it cannot be a paragraph in a doc, because the paragraph is what was
missing all three times. It has to be this file.

The checks, each one derived from a defect that actually shipped:

  A. Every tool name the system prompt names in backticks is in `TOOL_TAGS`.
     (`tail_serve_output`, `manage_rag`.)
  B. Every name in `FUNCTION_TOOL_SCHEMAS` is in `TOOL_TAGS`.
     Both call channels gate on `TOOL_TAGS`; a schema without a tag is a
     function the model is offered and cannot invoke. (The cookbook family.)
     Register 9 is NOT re-checked here: `tests/test_tool_index_schema_parity.py`
     already pins schema-to-index parity in both directions and runs in the same
     CI, and a second copy of a rule is the thing `Law 14` is about. It is listed
     above because this header is the canonical list of the registers, and a
     reader who cannot see all nine cannot tell which one they missed.
  C. Every name in `TOOL_TAGS` has a capability classification, or the approval
     card cannot say what the tool does.
  D. Every name in `TOOL_TAGS` has somewhere to be dispatched: a handler, an
     `_MCP_TOOL_MAP` route, a built-in email name, or a branch in the dispatch
     chain. The chain is read with `ast`, not a regex — a comment mentioning a
     tool name is not a dispatch (`Law 20`).
  E. Every built-in MCP server that gets connected at startup serves at least
     one tool something can actually route to. A connected server nothing
     reaches is a subprocess and a duplicate client held open for nothing.
"""
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# A connected built-in server whose tools nothing routes to, with the reason.
# Not a ratchet: a ratchet with one entry is a place to hide the second.
SHADOWED_ON_PURPOSE = {
    "memory": (
        "`B67`. `manage_memory` is in `TOOL_TAGS` and dispatches in-process to "
        "`do_manage_memory` via `dispatch_ai_tool`, so the connected `memory` "
        "server never serves a call — it holds a second `MemoryVectorStore` "
        "client in a second process for nothing. Filed rather than fixed here "
        "because the fix is either a subtraction (`Law 1`) or a live change to "
        "the Brain's write path, and neither belongs in a checker's landing."
    ),
}


def _module(rel: str) -> ast.Module:
    return ast.parse((ROOT / rel).read_text(encoding="utf-8"), filename=rel)


def _string_constants(tree: ast.AST) -> list:
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def _dispatch_names(rel: str) -> set:
    """Names compared against the dispatch variable, read structurally.

    Collects the string constants on the right of `tool == "x"` and
    `tool in ("x", "y")`. A name inside a comment or a docstring is not a
    dispatch and this cannot see one.
    """
    names = set()
    for node in ast.walk(_module(rel)):
        if not isinstance(node, ast.Compare):
            continue
        left = node.left
        if not (isinstance(left, ast.Name) and left.id in ("tool", "tool_type", "name")):
            continue
        for op, comp in zip(node.ops, node.comparators):
            if isinstance(op, ast.Eq) and isinstance(comp, ast.Constant):
                if isinstance(comp.value, str):
                    names.add(comp.value)
            elif isinstance(op, ast.In) and isinstance(comp, (ast.Tuple, ast.List, ast.Set)):
                for el in comp.elts:
                    if isinstance(el, ast.Constant) and isinstance(el.value, str):
                        names.add(el.value)
    return names


def _mcp_server_tool_names(rel: str) -> set:
    """Tool names a built-in MCP server declares, from its `Tool(name=...)`."""
    names = set()
    for node in ast.walk(_module(rel)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "Tool"):
            continue
        for kw in node.keywords:
            if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                names.add(kw.value.value)
    return names


def main() -> int:
    import src.agent_tools as agent_tools  # noqa: F401  (breaks a circular import)
    from src.agent_tools import TOOL_TAGS, TOOL_HANDLERS
    from src.tool_capabilities import TOOL_CAPABILITIES
    from src.tool_execution import _MCP_TOOL_MAP
    from src.tool_schemas import FUNCTION_TOOL_SCHEMAS
    from src.tool_security import BUILTIN_EMAIL_TOOLS
    from src.builtin_mcp import _BUILTIN_SERVERS

    problems = []

    # ── the universe of things that are a tool somewhere in this tree ────────
    server_tools = {}
    for sid, (rel, _label) in _BUILTIN_SERVERS.items():
        server_tools[sid] = _mcp_server_tool_names(rel)
    universe = set(TOOL_TAGS) | set(TOOL_HANDLERS) | set(BUILTIN_EMAIL_TOOLS)
    for names in server_tools.values():
        universe |= names

    # ── A. the prompt may only name a tool the fence will accept ────────────
    prompt_names = set()
    backticked = re.compile(r"`([a-z][a-z0-9_]{2,})`")
    for text in _string_constants(_module("src/agent_loop.py")):
        for hit in backticked.findall(text):
            if hit in universe:
                prompt_names.add(hit)
    for name in sorted(prompt_names - set(TOOL_TAGS)):
        problems.append(
            f"A  the system prompt names `{name}` but it is not in TOOL_TAGS — "
            f"the fence parser drops the block and nothing reports it")

    # ── B. both call channels gate on the same set ──────────────────────────
    schema_names = {s["function"]["name"] for s in FUNCTION_TOOL_SCHEMAS
                    if isinstance(s, dict) and "function" in s}
    for name in sorted(schema_names - set(TOOL_TAGS)):
        problems.append(
            f"B  {name} has a function schema but no TOOL_TAGS entry — the model "
            f"is offered a function it cannot invoke")

    # ── C. the approval card has to know what it does ───────────────────────
    for name in sorted(set(TOOL_TAGS) - set(TOOL_CAPABILITIES)):
        problems.append(f"C  {name} is dispatchable and has no capability classification")

    # ── D. everything tagged has somewhere to go ────────────────────────────
    routable = (set(TOOL_HANDLERS) | set(_MCP_TOOL_MAP) | set(BUILTIN_EMAIL_TOOLS)
                | _dispatch_names("src/tool_execution.py")
                | _dispatch_names("src/ai_interaction.py"))
    for name in sorted(set(TOOL_TAGS) - routable):
        problems.append(f"D  {name} is in TOOL_TAGS and has no dispatch path")

    # ── E. a connected server nobody reaches ────────────────────────────────
    routed_servers = {sid for sid, _t in _MCP_TOOL_MAP.values()}
    for sid, names in sorted(server_tools.items()):
        if sid in SHADOWED_ON_PURPOSE:
            continue
        if sid in routed_servers:
            continue
        if names & set(BUILTIN_EMAIL_TOOLS):
            continue
        problems.append(
            f"E  built-in MCP server '{sid}' is connected at startup and nothing "
            f"routes to any of {sorted(names) or ['(no tools declared)']}")
    for sid in sorted(set(SHADOWED_ON_PURPOSE) - set(server_tools)):
        problems.append(
            f"E  '{sid}' is exempted as shadowed but is no longer a built-in "
            f"server — delete the exemption")

    if problems:
        print("tool surface PROBLEMS\n")
        for p in problems:
            print(f"  {p}")
        print(f"\n{len(problems)} problem(s). A tool name has to be registered in "
              f"every register; the header of this file lists them.")
        return 1

    print(f"tool surface OK — {len(TOOL_TAGS)} tagged names, "
          f"{len(schema_names)} function schemas, {len(server_tools)} built-in servers, "
          f"{len(prompt_names)} named in the prompt, all registered everywhere")
    for sid in sorted(SHADOWED_ON_PURPOSE):
        print(f"  shadowed on purpose: {sid}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
