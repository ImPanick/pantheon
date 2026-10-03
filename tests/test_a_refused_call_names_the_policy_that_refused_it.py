# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1101` — the dispatcher's refusal says the policy that refused the call.

`tool_execution._execute_tool_block_impl` is the backstop behind the agent
loop: the loop refuses a name its `ToolPolicy` blocks before anything is
dispatched, and the dispatcher refuses it again for any caller that reaches
it some other way. Until this row the backstop answered EVERY `ToolPolicy`
refusal with "Execution of tool 'X' is forbade by the active guide-only
policy." — for a workflow AI step's own tool list (`P22-16`), whose loop
refusal says "“X” is not one of this step's tools.", and for an ordinary
turn's denylist alike. Both now ask one rule, `ToolPolicy.refusal_for`: the
spelling the model called first, then the policy-equivalent ones
(`email_tool_policy_names`) in a fixed order.

Driven (`Law 20`): the real `execute_tool_block` with the real policies
`build_effective_tool_policy` composes, and the real loop with a scripted
model (`test_an_ai_step_uses_only_its_tools._drive`), whose `tool_blocked`
event is compared with what the dispatcher says for the same call.
"""
import pytest

from src.agent_tools import ToolBlock
from src.tool_execution import NO_TOOL_SECURITY_CONTEXT, execute_tool_block
from src.tool_policy import ToolPolicy, build_effective_tool_policy
from tests.test_an_ai_step_uses_only_its_tools import STEP_TOOLS, _base, _drive


async def _dispatch(tool, content, policy):
    return await execute_tool_block(ToolBlock(tool, content), owner="local", tool_policy=policy,
                                    security_context=NO_TOOL_SECURITY_CONTEXT)


@pytest.mark.asyncio
async def test_a_name_outside_a_steps_list_is_refused_in_the_lists_words():
    desc, result = await _dispatch("bash", "echo should-not-run", ToolPolicy(allowed_tools=STEP_TOOLS))
    assert desc == "bash: BLOCKED" and result["exit_code"] == 1
    assert result["error"] == "“bash” is not one of this step's tools."
    assert "forbade" not in result["error"] and "guide-only" not in result["error"]


@pytest.mark.asyncio
async def test_an_email_tool_is_refused_by_the_spelling_the_model_called():
    """`list_emails` and `mcp__email__list_emails` are one tool to the policy;
    the sentence names the one the model wrote, whichever set order says."""
    policy = ToolPolicy(allowed_tools={"web_search"})
    for called in ("list_emails", "mcp__email__list_emails"):
        _desc, result = await _dispatch(called, "{}", policy)
        assert result["error"] == f"“{called}” is not one of this step's tools.", called


@pytest.mark.asyncio
async def test_an_ordinary_turns_denylist_says_its_own_reason():
    policy = build_effective_tool_policy(disabled_tools={"bash"}, last_user_message="tidy my notes")
    _desc, result = await _dispatch("bash", "id", policy)
    assert result["error"] == policy.reason_for("bash") == "Tool is disabled for this request."


@pytest.mark.asyncio
async def test_a_guide_only_turn_says_the_person_forbade_tools():
    policy = build_effective_tool_policy(last_user_message="Do not use any tools, just explain it.")
    assert policy.mode == "guide_only"
    _desc, result = await _dispatch("bash", "id", policy)
    assert result["error"] == "user forbade tool use."
    assert result["error"] == policy.reason_for("bash")


def test_the_loop_and_the_dispatcher_say_the_same_sentence(monkeypatch):
    """The loop's refusal reaches the model first; the backstop says the same
    words for the same call — one rule (`Law 7`)."""
    import asyncio

    _base(monkeypatch)
    policy = ToolPolicy(allowed_tools=STEP_TOOLS)
    for called in ("bash", "list_emails"):
        events, _sent = _drive(monkeypatch, [[(called, {"command": "id"})]], policy=policy)
        [blocked] = [e for e in events if e.get("type") == "tool_blocked"]
        # The loop's block is the native call as the loop names it (a built-in
        # email tool arrives as its `mcp__email__` spelling); the dispatcher is
        # handed that same block.
        tool = blocked["tool"]
        _desc, result = asyncio.run(_dispatch(tool, "{}", policy))
        assert blocked["reason"] == result["error"] == f"“{tool}” is not one of this step's tools."
