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
  F. Every name in `TOOL_TAGS` is ANNOUNCED to the model somewhere. See below.
  G. A name a built-in server serves has no native `TOOL_HANDLERS` entry.
     One name, one implementation.

`P17-06` CLOSED THIS FILE'S SECOND CLAUSE, AND ADDED F AND G. The row asked for
*"the rule that decides where a new capability goes"*. Checks A–E answer the
half of that question about **wiring**: whatever shape you choose, these are the
registers. F and G answer the half that had no rule at all.

**F — being dispatchable and being offered are different properties, and only
one of them was checked.** A–E prove a name can be *executed*. Nothing proved
the model is ever *told the name exists*. On this tree that was not
hypothetical: `draft_email`, `draft_email_reply`, `ai_draft_email_reply`,
`search_emails` and `download_attachment` were in `TOOL_TAGS`, classified in
`TOOL_CAPABILITIES`, routed through `BUILTIN_EMAIL_TOOLS` to `mcp__email__*`,
and served with full descriptions by `mcp_servers/email_server.py` — and the
model was never shown one of them by any channel. They have no function schema
(deliberately: fenced-channel only, which `check-mcp-schemas.py` check C already
blesses), they were in no `BUILTIN_TOOL_DESCRIPTIONS` entry so agent-mode
retrieval could not surface them, the system prompt names none of them, and
built-in servers are skipped from `get_tool_descriptions_for_prompt`. Meanwhile
`send_email`'s own schema — which the model does read — says *"for normal
assistant-written mail prefer `draft_email` so the user reviews it first"*.
That is `B66`'s defect with the sides swapped: there the prompt named a tool
the tags did not carry, here the tags carry tools nothing names. So the
announcement channels are enumerated and one of them has to be true:

  * a `FUNCTION_TOOL_SCHEMAS` entry — the function channel ships its own
    description;
  * a `BUILTIN_TOOL_DESCRIPTIONS` entry — agent mode embeds these and retrieves
    against them, so this is the only way a tool enters a *selected* tool set;
  * a backticked mention in the system prompt — the fence channel on a
    full-prompt turn.

`tests/test_tool_index_schema_parity.py` is not this check and does not cover
it: it runs schema → index, so a tool with no schema is outside it in exactly
the direction that goes wrong.

**G — one name, one implementation.** `B66` found *three* `manage_rag`s (the
prompt's, the server's, and a dead in-process `do_manage_rag` with a smaller
action set) and `B67` found two `manage_memory`s. A built-in server is spawned
on every startup, so a name it serves that also has a native handler is two live
implementations of one name with nothing deciding which answers. Routes into
*optional* servers (`_MCP_TOOL_MAP` → `bash`, `python`, `filesystem`,
`web_search`, `web_fetch`) are a different thing and are not checked: those
servers are registered by an operator, the native handler is the documented
fallback when they are not, and one of the two is always absent.

**THE PLACEMENT RULE ITSELF IS PROSE AND LIVES IN `CONTRIBUTING.md`**, under
*Adding a tool*, because it is a judgement a contributor makes before writing
code and a checker cannot make it for them. What a checker can do is refuse the
half-registered result, which is what this file is. `D-2026-09-10-03` records
the rule's own accuracy against the servers that existed when it was written.
"""
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# A connected built-in server whose tools nothing routes to, with the reason.
# Not a ratchet: a ratchet with one entry is a place to hide the second.
#
# **Empty since `B67` closed** (`D-2026-09-14-01`). Its one entry was `memory`,
# and the entry existed because this checker found the defect and a checker's
# landing is the wrong place to fix one. The fix was not to route the tool —
# the in-process and server forms are identical in surface, and routing would
# have split the vector index across two processes — but to stop connecting a
# server nothing could call. So the rule below now has nothing to forgive,
# which is the state an exemption table should be in.
SHADOWED_ON_PURPOSE = {}


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


def unannounced(tags, schema_names, descriptions, prompt_names) -> list:
    """Names the model is never told about. Check F's rule, as a function.

    Pulled out so a test can drive the rule with inputs it controls rather than
    re-deriving it (`Law 13`: the rule reads one way, in one place). `main`
    calls it with the real registers.
    """
    announced = set(schema_names) | set(descriptions) | set(prompt_names)
    return sorted(set(tags) - announced)


def doubly_implemented(server_tools, handlers) -> list:
    """`(server_id, name)` for every name a built-in server AND a handler owns.

    Check G's rule, same reasoning as above. Optional-server routes are not
    passed in, because only a *built-in* server is spawned unconditionally and
    only then are both implementations live at once.
    """
    return sorted((sid, name)
                  for sid, names in server_tools.items()
                  for name in set(names) & set(handlers))


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

    # ── F. the model is told the name exists ────────────────────────────────
    from src.tool_index import BUILTIN_TOOL_DESCRIPTIONS

    announced = schema_names | set(BUILTIN_TOOL_DESCRIPTIONS) | prompt_names
    for name in unannounced(TOOL_TAGS, schema_names, BUILTIN_TOOL_DESCRIPTIONS,
                            prompt_names):
        problems.append(
            f"F  {name} is dispatchable and the model is never told it exists — "
            f"no function schema, no BUILTIN_TOOL_DESCRIPTIONS entry for agent-mode "
            f"retrieval, and the system prompt does not name it")

    # ── G. one name, one implementation ─────────────────────────────────────
    for sid, name in doubly_implemented(server_tools, TOOL_HANDLERS):
        problems.append(
            f"G  {name} is served by the built-in '{sid}' server AND has a "
            f"native TOOL_HANDLERS entry — two live implementations of one "
            f"name, which is how B66 shipped three manage_rags")

    if problems:
        print("tool surface PROBLEMS\n")
        for p in problems:
            print(f"  {p}")
        print(f"\n{len(problems)} problem(s). A tool name has to be registered in "
              f"every register; the header of this file lists them.")
        return 1

    print(f"tool surface OK — {len(TOOL_TAGS)} tagged names, "
          f"{len(schema_names)} function schemas, {len(server_tools)} built-in servers, "
          f"{len(prompt_names)} named in the prompt, "
          f"{len(set(TOOL_TAGS) & announced)} announced to the model, "
          f"all registered everywhere")
    for sid in sorted(SHADOWED_ON_PURPOSE):
        print(f"  shadowed on purpose: {sid}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
