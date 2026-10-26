# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1382`: a non-admin who asks for an admin tool is told why, not just that.

`P2-25` put a sentence on every entry in `NON_ADMIN_BLOCKED_TOOLS` so the
refusal could say what the tool reaches, and the dispatcher builds that
sentence. But `blocked_tools_for_owner` puts the same names into the loop's
cap first, so the loop's own `tool_blocked` arm answered earlier with
*"Tool 'bash' is disabled by the current request policy."* — and through the
chat route, where the same names also sit in the `ToolPolicy`, with *"Tool is
disabled for this request."* The register was never read.

The gate does not move (`FORBIDDEN.md` Part 2): every case asserts the call
was refused and never dispatched. What changes is the sentence, chosen from
the reason the cap already records (`WITHHELD_BY_PRIVILEGE`).

The wider case — the real probe world, a real non-admin — is
`tests/test_every_tool_in_the_suite_is_reachable_and_callable.py::
test_a_tool_a_gate_holds_is_held_with_a_sentence_not_silence`; these drive
the loop directly for the two callers that case does not cover.
"""
import asyncio
import json

import src.agent_loop as agent_loop
from src.tool_policy import (
    TurnToolAccess,
    WITHHELD_BY_POLICY,
    WITHHELD_BY_PRIVILEGE,
    build_effective_tool_policy,
)
from src.tool_security import (
    NON_ADMIN_BLOCKED_REASONS,
    NON_ADMIN_BLOCKED_TOOLS,
    delegated_credential_blocked_tools,
)


def test_the_cap_answers_with_the_registers_sentence_only_for_a_privilege():
    access = TurnToolAccess()
    access.withhold({"bash"}, because=WITHHELD_BY_PRIVILEGE)
    access.withhold({"web_search"}, because=WITHHELD_BY_POLICY)

    said = access.privilege_refusal("bash")
    assert "restricted to admin users" in said
    assert NON_ADMIN_BLOCKED_REASONS["bash"] in said
    assert "Ask an admin" in said
    # Not withheld by privilege, or not withheld at all: no claim about admins.
    assert access.privilege_refusal("web_search") is None
    assert access.privilege_refusal("read_file") is None
    # A bearer token's cap is a privilege too, with the token's own sentence.
    assert "API-token callers" in access.privilege_refusal("bash", delegated_credential=True)


def _blocked_events(monkeypatch, *, blocked, tool_policy=None, delegated=False):
    """Drive the real loop: the model calls `bash`, the turn's cap holds it."""
    dispatched = []
    calls = {"n": 0}
    monkeypatch.setattr(agent_loop, "get_setting", lambda key, default=None: default)
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: None)
    monkeypatch.setattr(agent_loop, "estimate_tokens", lambda *args, **kwargs: 10)
    monkeypatch.setattr(agent_loop, "blocked_tools_for_owner", lambda owner: set(blocked))
    monkeypatch.setattr(
        agent_loop, "_agent_route_tool_mode", lambda *args, **kwargs: (True, False, False)
    )

    async def fake_stream(candidates, messages, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            call = {"name": "bash", "arguments": json.dumps({"command": "id"})}
            yield f'data: {json.dumps({"type": "tool_calls", "calls": [call]})}\n\n'
        else:
            yield 'data: {"delta": "I could not run that."}\n\n'
        yield "data: [DONE]\n\n"

    async def fake_execute(block, *args, **kwargs):
        dispatched.append(block.tool_type)
        return block.tool_type, {"output": "uid=0(root)", "exit_code": 0}

    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", fake_stream)
    monkeypatch.setattr(agent_loop, "execute_tool_block", fake_execute)

    async def _drain():
        return [
            chunk
            async for chunk in agent_loop.stream_agent_loop(
                "http://local.test/v1",
                "small-local-model",
                [{"role": "user", "content": "run id in the shell for me"}],
                max_rounds=3,
                relevant_tools={"bash", "ask_user"},
                owner="bob",
                tool_policy=tool_policy,
                delegated_credential=delegated,
                _is_teacher_run=True,
            )
        ]

    chunks = asyncio.run(_drain())
    events = []
    for chunk in chunks:
        if chunk.startswith("data: {"):
            try:
                events.append(json.loads(chunk[6:]))
            except json.JSONDecodeError:
                pass
    assert "bash" not in dispatched, "the gate stood down: a held call was dispatched"
    held = [e for e in events if e.get("type") == "tool_blocked" and e.get("tool") == "bash"]
    assert held, "a non-admin's bash was refused in silence"
    return held


def test_a_non_admins_refusal_in_the_loop_says_why_and_who_may(monkeypatch):
    (held,) = _blocked_events(monkeypatch, blocked=NON_ADMIN_BLOCKED_TOOLS)
    assert "restricted to admin users" in held["reason"], held["reason"]
    assert NON_ADMIN_BLOCKED_REASONS["bash"] in held["reason"]
    assert "disabled by the current request policy" not in held["reason"]


def test_through_the_chat_routes_policy_the_reason_still_wins(monkeypatch):
    """The route hands the same names in a `ToolPolicy` whose reason for each is
    *"Tool is disabled for this request."*, and that arm used to answer first."""
    policy = build_effective_tool_policy(disabled_tools=NON_ADMIN_BLOCKED_TOOLS)
    assert policy.blocks("bash")
    (held,) = _blocked_events(monkeypatch, blocked=NON_ADMIN_BLOCKED_TOOLS,
                              tool_policy=policy)
    assert NON_ADMIN_BLOCKED_REASONS["bash"] in held["reason"], held["reason"]
    assert held["reason"] != "Tool is disabled for this request."


def test_a_bearer_token_run_is_told_it_is_a_token_not_a_non_admin(monkeypatch):
    (held,) = _blocked_events(monkeypatch, blocked=set(),
                              delegated=True)
    assert "bash" in delegated_credential_blocked_tools()
    assert "API-token callers" in held["reason"], held["reason"]
