# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P11-02c` — the two admin tool sets have different names and opposite jobs.

`tool_execution` and `agent_loop` both defined a module-level `_ADMIN_TOOLS`.
One **blocks** non-admins at execution (11 names); the other **force-includes**
tools in the prompt and schema list (15 names). Five names are in both, so a
grep during an RBAC refactor could land on either and the code would still look
right. `AGENTS.md` Law 14 cites the pair by name as the incident behind the law.

The absence checks are `hasattr` on the imported module, not a substring search
of the file: what matters is that nothing can still *resolve* the ambiguous
name, and a comment mentioning it in passing is history, not a live binding.

The semantic checks drive the real paths — `execute_tool_block` for the gate,
`_build_base_prompt` for the prompt — so emptying either set fails a test here
rather than silently changing what the agent can see or run.
"""
import asyncio

import pytest

import src.agent_loop as agent_loop
import src.tool_execution as tool_execution
from src.agent_tools import ToolBlock
from src.tool_execution import NO_TOOL_SECURITY_CONTEXT, execute_tool_block


def _run(coro):
    return asyncio.run(coro)


def test_the_ambiguous_name_resolves_in_neither_module():
    assert not hasattr(tool_execution, "_ADMIN_TOOLS")
    assert not hasattr(agent_loop, "_ADMIN_TOOLS")


def test_the_two_sets_are_different_sets():
    gate = tool_execution._ADMIN_ONLY_TOOLS
    prompt = agent_loop._ADMIN_PROMPT_FORCE_INCLUDE
    assert gate != prompt
    # The overlap is what made the collision dangerous rather than merely
    # confusing: five names mean "blocked" in one module and "shown" in the
    # other. Measured 2026-09-18; this pins the shape, not the exact contents.
    assert gate & prompt == {
        "manage_endpoints",
        "manage_mcp",
        "manage_settings",
        "manage_tokens",
        "manage_webhooks",
    }
    # Each set holds names the other does not, so neither is a subset anyone
    # could "simplify" into the other.
    assert gate - prompt
    assert prompt - gate


def test_the_gate_set_refuses_execution_for_a_non_admin(monkeypatch):
    # The real refusal path. All eleven names are also in
    # `NON_ADMIN_BLOCKED_TOOLS`, so *something* would block them either way —
    # the discriminator is the error string, which only this gate produces and
    # which it produces because it is checked first.
    monkeypatch.setattr(tool_execution, "_owner_is_admin", lambda owner: False)
    for tool in sorted(tool_execution._ADMIN_ONLY_TOOLS):
        desc, result = _run(
            execute_tool_block(
                ToolBlock(tool, "{}"),
                owner="bob",
                security_context=NO_TOOL_SECURITY_CONTEXT,
            )
        )
        assert desc == f"{tool}: BLOCKED"
        assert result["exit_code"] == 1
        assert "requires an admin user" in result["error"], tool


def test_the_gate_set_lets_an_admin_through_that_gate(monkeypatch):
    # Not "runs successfully" — most of these need real subsystems. Only that
    # the admin gate is not what stops an admin, proving the set is consulted
    # against the owner rather than blanket-refusing.
    monkeypatch.setattr(tool_execution, "_owner_is_admin", lambda owner: True)
    desc, result = _run(
        execute_tool_block(
            ToolBlock("manage_settings", "{}"),
            owner="root",
            security_context=NO_TOOL_SECURITY_CONTEXT,
        )
    )
    assert "requires an admin user" not in str(result.get("error", ""))


def test_the_prompt_set_adds_tools_and_does_not_gate_them():
    # `needs_admin` is intent detection, not authorization: it decides what the
    # model is *told about* after RAG narrowed the tool list. Both prompts are
    # built from the same one-tool `relevant_tools`, so the difference between
    # them is exactly this set.
    admin_prompt, _ = agent_loop._build_base_prompt(
        disabled_tools=set(),
        mcp_mgr=None,
        needs_admin=True,
        relevant_tools={"ask_user"},
        compact=False,
        owner=None,
    )
    plain_prompt, _ = agent_loop._build_base_prompt(
        disabled_tools=set(),
        mcp_mgr=None,
        needs_admin=False,
        relevant_tools={"ask_user"},
        compact=False,
        owner=None,
    )
    for tool in sorted(agent_loop._ADMIN_PROMPT_FORCE_INCLUDE):
        fence = f"```{tool}```"
        assert fence in admin_prompt, tool
        assert fence not in plain_prompt, tool


def test_being_in_the_prompt_set_grants_nothing(monkeypatch):
    # The collision's actual failure mode, stated as a test. `manage_settings`
    # is in both sets. Being force-included in an admin-intent prompt does not
    # make it executable by a non-admin; only `_ADMIN_ONLY_TOOLS` decides that.
    assert "manage_settings" in agent_loop._ADMIN_PROMPT_FORCE_INCLUDE
    monkeypatch.setattr(tool_execution, "_owner_is_admin", lambda owner: False)
    desc, result = _run(
        execute_tool_block(
            ToolBlock("manage_settings", "{}"),
            owner="bob",
            security_context=NO_TOOL_SECURITY_CONTEXT,
        )
    )
    assert desc == "manage_settings: BLOCKED"
    assert "requires an admin user" in result["error"]


def test_prompt_only_names_are_not_execution_gated(monkeypatch):
    # The inverse reading, which is the one that loses a feature rather than
    # opening a hole: ten of the fifteen prompt names are NOT in the gate, so
    # treating the prompt set as the gate would refuse tools that are meant to
    # run. `pipeline` is one of them and is in neither blocklist.
    prompt_only = agent_loop._ADMIN_PROMPT_FORCE_INCLUDE - tool_execution._ADMIN_ONLY_TOOLS
    assert "pipeline" in prompt_only
    monkeypatch.setattr(tool_execution, "_owner_is_admin", lambda owner: False)
    desc, result = _run(
        execute_tool_block(
            ToolBlock("pipeline", "{}"),
            owner="bob",
            security_context=NO_TOOL_SECURITY_CONTEXT,
        )
    )
    assert "requires an admin user" not in str(result.get("error", ""))
