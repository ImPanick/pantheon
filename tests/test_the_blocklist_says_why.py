# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P2-25` — the non-admin blocklist stays, and it says why.

The row was retitled from *"Prune…"* to *"Document… prune nothing"* because the
title was the whole hazard: an agent that stopped at it would have pruned, and
the safe prune count is zero. What this file pins is the part of that finding a
human cannot check by trying it.

**A prune of eleven of these names cannot be falsified by a manual test.**
`tool_execution._ADMIN_ONLY_TOOLS` is checked *first*, with its own error
string, and every one of its eleven names is also in
`NON_ADMIN_BLOCKED_TOOLS`. Remove one from the blocklist and the call is still
refused — by the other gate — while what the model is *advertised* has changed,
because the prompt and schema filters read the blocklist and not the gate.
`B533` put both gates and their order into `THREAT_MODEL.md` for this reason.

So the tests below drive the real refusal path rather than reading the file
(`Law 20`), and the completeness check is a recomputation rather than a
substring search (`Law 8`).
"""
import asyncio

import pytest

import src.tool_execution as tool_execution
import src.tool_security as tool_security
from src.agent_tools import ToolBlock
from src.tool_execution import NO_TOOL_SECURITY_CONTEXT, execute_tool_block
from src.tool_security import (
    BUILTIN_EMAIL_TOOLS,
    MCP_NAMESPACE_BLOCK_REASON,
    NON_ADMIN_BLOCKED_REASONS,
    NON_ADMIN_BLOCKED_TOOLS,
    blocked_tool_reason,
)


def _run(coro):
    return asyncio.run(coro)


def test_every_blocked_name_has_a_reason_and_no_reason_is_an_orphan():
    """The register and the set are one thing held in two shapes, so they are
    checked against each other rather than trusted. A name added to the set
    without a reason is a red test here, not a silent gap in the register."""
    assert set(NON_ADMIN_BLOCKED_REASONS) == set(NON_ADMIN_BLOCKED_TOOLS)
    for name in sorted(NON_ADMIN_BLOCKED_TOOLS):
        reason = blocked_tool_reason(name)
        assert reason, name
        # A reason that restates the name explains nothing. Each says what the
        # tool *reaches*, which is what somebody arguing for a prune has to
        # answer, so it is longer than a label.
        assert len(reason) > 25, name
        assert reason.strip().lower() != name.lower()


def test_the_sixteen_email_tools_inherit_their_reason_from_the_registry():
    """`BUILTIN_EMAIL_TOOLS` is the single source of truth the module's own
    header claims it is: a tool added to the email server is blocked
    automatically, and it must acquire a reason automatically too, or the
    register becomes the next place a name goes missing (`Law 7`)."""
    assert BUILTIN_EMAIL_TOOLS <= set(NON_ADMIN_BLOCKED_REASONS)
    reasons = {blocked_tool_reason(n) for n in BUILTIN_EMAIL_TOOLS}
    assert len(reasons) == 1
    # The qualified spelling policy also sees resolves to the same sentence.
    assert blocked_tool_reason("mcp__email__read_email") == reasons.pop()


def test_the_mcp_namespace_rule_has_a_reason_although_it_is_not_in_the_set():
    """The `mcp__` prefix rule lives in `is_public_blocked_tool` and not in the
    set, which is why `blocked_tools_for_owner` does not carry it. A reader who
    only has the set would conclude MCP tools are allowed."""
    assert "mcp__anything__do_it" not in NON_ADMIN_BLOCKED_TOOLS
    assert tool_security.is_public_blocked_tool("mcp__anything__do_it")
    assert blocked_tool_reason("mcp__anything__do_it") == MCP_NAMESPACE_BLOCK_REASON


def test_a_tool_this_policy_does_not_block_has_no_reason():
    """`Law 10`: *no reason recorded* and *not blocked* are different answers,
    so the empty string means the second and nothing else."""
    assert not tool_security.is_public_blocked_tool("web_search")
    assert blocked_tool_reason("web_search") == ""
    assert blocked_tool_reason(None) == ""
    assert blocked_tool_reason(object()) == ""


def test_every_admin_only_name_is_also_in_the_blocklist():
    """The pairing that makes a prune unfalsifiable by hand, asserted so that
    a prune of either is visibly a change to a pair.

    Measured 2026-09-19: eleven names in `_ADMIN_ONLY_TOOLS`, all eleven in
    `NON_ADMIN_BLOCKED_TOOLS`. `B533`'s `Verify:` line asks `THREAT_MODEL.md`
    to state this; a sentence in a document is not a check."""
    gate = set(tool_execution._ADMIN_ONLY_TOOLS)
    assert gate, "the second gate is empty — the first gate is now the only one"
    assert gate <= set(NON_ADMIN_BLOCKED_TOOLS), sorted(gate - set(NON_ADMIN_BLOCKED_TOOLS))


def test_pruning_a_paired_name_is_invisible_at_the_call_and_visible_in_the_ad(monkeypatch):
    """The row's own finding, executed.

    `manage_settings` is in both sets. Simulate the prune by removing it from
    the blocklist only: the call is still refused — by the first gate, with a
    different sentence — while `blocked_tools_for_owner`, which is what the
    prompt and schema filters read, has stopped naming it. That is the whole
    reason a manual test cannot validate a prune."""
    monkeypatch.setattr(tool_execution, "_owner_is_admin", lambda owner: False)
    pruned = frozenset(NON_ADMIN_BLOCKED_TOOLS) - {"manage_settings"}
    monkeypatch.setattr(tool_security, "NON_ADMIN_BLOCKED_TOOLS", pruned)

    desc, result = _run(
        execute_tool_block(
            ToolBlock("manage_settings", "{}"),
            owner="bob",
            security_context=NO_TOOL_SECURITY_CONTEXT,
        )
    )
    assert desc == "manage_settings: BLOCKED"
    assert "requires an admin user" in result["error"]

    # And yet the advertisement moved.
    assert "manage_settings" not in tool_security.blocked_tools_for_owner("bob")


def test_adopt_served_model_is_the_one_the_second_gate_does_not_catch(monkeypatch):
    """The counter-example, and the reason the register records it.

    Five of the six model tools are in both sets. `adopt_served_model` is in
    this one alone — it registers a running server in `cookbook_state.json` and
    adds it as a chat endpoint — so a prune there is the prune in that family
    that really does open something."""
    gate = set(tool_execution._ADMIN_ONLY_TOOLS)
    assert "adopt_served_model" in NON_ADMIN_BLOCKED_TOOLS
    assert "adopt_served_model" not in gate
    assert {"serve_model", "download_model"} <= gate

    monkeypatch.setattr(tool_execution, "_owner_is_admin", lambda owner: False)
    _, blocklist_only = _run(
        execute_tool_block(
            ToolBlock("adopt_served_model", "{}"),
            owner="bob",
            security_context=NO_TOOL_SECURITY_CONTEXT,
        )
    )
    _, both_gates = _run(
        execute_tool_block(
            ToolBlock("serve_model", "{}"),
            owner="bob",
            security_context=NO_TOOL_SECURITY_CONTEXT,
        )
    )
    # Different gates, different sentences — which is how you can tell which
    # one refused, and therefore what a prune would have cost.
    assert "restricted to admin users" in blocklist_only["error"]
    assert "requires an admin user" in both_gates["error"]


def test_the_refusal_tells_the_person_what_the_tool_reaches(monkeypatch):
    """`Law 15`. The refusal used to say only that it was refused. The register
    is documentation for the reader who most needs it, and putting it in the
    message is also what stops the register rotting: a reason nobody ever sees
    is a reason nobody checks."""
    monkeypatch.setattr(tool_execution, "_owner_is_admin", lambda owner: False)
    for tool in ("bash", "get_workspace", "resolve_contact", "vault_get"):
        _, result = _run(
            execute_tool_block(
                ToolBlock(tool, "{}"),
                owner="bob",
                security_context=NO_TOOL_SECURITY_CONTEXT,
            )
        )
        assert blocked_tool_reason(tool) in result["error"], tool
        # `tests/test_review_regressions.py` asserts this substring; the reason
        # is added to the sentence, not swapped for it.
        assert "restricted to admin users" in result["error"]


@pytest.mark.parametrize("tool,must_name", [
    # The three entries most likely to be read as harmless, and the specific
    # word each reason has to carry for the reader to see why it is not.
    ("resolve_contact", "never reads it"),
    ("search_chats", "owner IS NULL"),
    ("get_workspace", "absolute host path"),
])
def test_the_three_traps_name_the_thing_that_makes_them_traps(tool, must_name):
    assert must_name in blocked_tool_reason(tool), tool
