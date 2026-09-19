# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P2-14` — the guide-only trigger fired on a mention, and on a question.

Seven unanchored `.search`es over the whole user message. A hit disarmed the
turn completely: every known tool into the denylist, MCP manager dropped, tool
preprocessing and background extraction off. The three reproductions below are
`P2-CORRECTED`'s, re-run on 2026-09-19 against this tree before the fix — all
three still fired.

The sharpest one was the seventh pattern, and it was not a false positive at
all: *"ask me before using tools"* asks to be **consulted**, and the product
answered by taking the tools away. It is a trust rung now.

Everything here drives the detector or the loop rather than reading the source
(`Law 20`), and the tool count is recomputed rather than quoted (`Law 6`).
"""
import asyncio
import json

import pytest

import src.agent_loop as al
from src.agent_tools import ToolBlock
from src.tool_capabilities import TrustRung
from src.tool_execution import NO_TOOL_SECURITY_CONTEXT, execute_tool_block
from src.tool_policy import (
    build_effective_tool_policy,
    detect_guide_only_turn,
    detect_tool_confirmation_turn,
    known_tool_names,
)


def _collect(gen):
    async def _run():
        return [c async for c in gen]

    return asyncio.run(_run())


def _events(chunks):
    out = []
    for chunk in chunks:
        if chunk.startswith("data: ") and not chunk.startswith("data: [DONE]"):
            try:
                out.append(json.loads(chunk[6:]))
            except Exception:
                pass
    return out


def _delta_chunk(text):
    return "data: " + json.dumps({"delta": text}) + "\n\n"


def _patch_loop_basics(monkeypatch):
    monkeypatch.setattr(al, "get_setting", lambda key, default=None: default, raising=False)
    monkeypatch.setattr(al, "get_mcp_manager", lambda: None, raising=False)
    monkeypatch.setattr(al, "estimate_tokens", lambda *a, **k: 10, raising=False)


# ── The three reproductions ────────────────────────────────────────────────

@pytest.mark.parametrize("message,why", [
    ("Why am I not allowed to use tools here?",
     "a question ABOUT the policy is not the policy"),
    ('Quote: "do not use any tools" — what does that mean?',
     "a quotation is somebody else's instruction"),
    ("I love guide-only mode discussions",
     "naming a mode is not asking for it"),
])
def test_the_three_reproductions_no_longer_disarm_the_turn(message, why):
    assert detect_guide_only_turn(message) is None, why
    assert detect_tool_confirmation_turn(message) is None, why
    policy = build_effective_tool_policy(last_user_message=message)
    assert policy.mode == "normal"
    assert policy.block_all_tool_calls is False
    assert policy.disabled_tools == frozenset()


@pytest.mark.parametrize("message", [
    "GUIDE-ONLY MODE. DO NOT USE TOOLS.",
    "NO-TOOLS MODE.",
    "You are not allowed to:\n- use tools\n- execute commands",
    "Guide-only mode for this one — just tell me what to type",
    "Please use guide-only mode",
    "don't use any tools",
    "Not allowed to use any tools.",
    # The two that only pass because the anchors are per CLAUSE. A
    # whole-message anchor puts `^` at "Sure" and "Thanks", and the request in
    # the second sentence is then invisible.
    "Sure, sounds good. Guide-only mode.",
    "Thanks, that helps. Not allowed to use any tools.",
])
def test_a_real_request_still_disarms_the_turn(message):
    """`Law 1`. Narrowing a trigger that over-fires is only correct if the
    thing it triggers still happens when it should. The fourth case is why the
    decision's *whole-message* anchor was implemented per CLAUSE instead: it is
    the most natural way anybody asks, and a whole-message match refuses it."""
    assert detect_guide_only_turn(message)
    policy = build_effective_tool_policy(last_user_message=message)
    assert policy.mode == "guide_only"
    assert policy.block_all_tool_calls is True
    assert policy.disable_mcp is True


def test_past_tense_is_a_report_and_present_tense_is_an_instruction():
    """The distinction rule 3 rests on, stated as its own case."""
    assert detect_guide_only_turn(
        "In your last answer you said you were not allowed to use tools. Why?"
    ) is None
    assert detect_guide_only_turn("You are not allowed to use tools")


def test_the_disarm_still_costs_every_known_tool_and_the_number_is_measured():
    """The row's second number, recomputed rather than quoted (`Law 6`).

    **And its scope matters** (`Law 5`): `known_tool_names()` answers **82** in
    a process that has not imported `src.agent_loop`, and **84** in one that
    has — the `TOOL_SECTIONS` leg is an import cycle and fails quietly, so
    `host_shell` and `manage_rag` are absent from the cold answer. The live app
    always gets the larger number. Filed as `B830`; asserted here as a
    relationship rather than a literal, so it cannot go stale either way."""
    known = known_tool_names()
    assert len(known) >= 80, len(known)
    policy = build_effective_tool_policy(
        disabled_tools={"web_search"},
        last_user_message="GUIDE-ONLY MODE.",
    )
    assert known <= set(policy.disabled_tools)
    assert known <= set(policy.hidden_tools)
    # The enforcement does not depend on that list being complete:
    # `block_all_tool_calls` refuses names the denylist never learned.
    assert policy.blocks("host_shell")
    assert policy.blocks("a_tool_invented_after_this_test_was_written")


def test_a_short_tool_list_says_so_instead_of_swallowing_the_reason(caplog):
    """`B830`. The leg that actually fails was the one that said nothing.

    `known_tool_names()` builds its answer from three imports. Two of them
    logged on failure; the first — `FUNCTION_TOOL_SCHEMAS` — was a bare
    `except Exception: pass`, and it is the leg that really does raise, because
    `src/tool_schemas.py` and `src/agent_tools/__init__.py` import each other.
    That is why the number is **82** on the first call in a cold process and
    **84** afterwards.

    Driven by forcing the same failure rather than by reading the source
    (`Law 20`): with the module poisoned the answer must still come back, must
    be shorter, and must have said why."""
    import sys

    with caplog.at_level("DEBUG", logger="src.tool_policy"):
        with pytest.MonkeyPatch.context() as mp:
            mp.setitem(sys.modules, "src.tool_schemas", None)
            degraded = known_tool_names()

    assert degraded, "a failed leg must degrade, not empty the list"
    assert len(degraded) < len(known_tool_names())
    assert any(
        "FUNCTION_TOOL_SCHEMAS" in record.getMessage() for record in caplog.records
    ), [record.getMessage() for record in caplog.records]


# ── Pattern 7: confirmation, not disarm ────────────────────────────────────

@pytest.mark.parametrize("message", [
    "Ask me before using tools.",
    "ask me for confirmation before using tools",
    "check with me before running tools",
])
def test_asking_to_be_consulted_keeps_every_tool(message):
    confirm = build_effective_tool_policy(
        disabled_tools={"web_search"}, last_user_message=message)
    assert confirm.mode == "confirm_tools"
    assert confirm.require_tool_confirmation is True
    assert confirm.confirms() is True
    # Nothing added, nothing hidden, MCP intact — the difference from a disarm.
    assert confirm.block_all_tool_calls is False
    assert confirm.disable_mcp is False
    assert set(confirm.disabled_tools) == {"web_search"}
    assert confirm.hidden_tools == frozenset()
    assert confirm.blocks("bash") is False


def test_a_turn_that_asks_for_both_gets_the_stronger_reading():
    policy = build_effective_tool_policy(
        last_user_message="Do not use any tools. Ask me before using tools.")
    assert policy.mode == "guide_only"
    assert policy.require_tool_confirmation is False


def test_the_executor_backstop_refuses_a_disarm_and_not_a_confirmation():
    """The policy backstop in `execute_tool_block` refuses outright, and its
    sentence is what identifies it. A confirmation turn must pass straight
    through so the action can reach the approval gate instead.

    The policy backstop is checked FIRST, before both admin gates, so the
    sentence tells you which gate answered — the distinction `P2-25` is about,
    met here by accident: this ownerless `read_file` is refused either way, and
    only the reason says whether this row's change worked."""
    def _call(message):
        policy = build_effective_tool_policy(last_user_message=message)
        return asyncio.run(
            execute_tool_block(
                ToolBlock("read_file", '{"path": "README.md"}'),
                tool_policy=policy,
                security_context=NO_TOOL_SECURITY_CONTEXT,
            )
        )

    _, disarmed = _call("Do not use any tools.")
    assert "forbade" in disarmed["error"]

    _, confirmed = _call("Ask me before using tools.")
    assert "forbade" not in confirmed["error"]
    assert "restricted to admin users" in confirmed["error"]


def test_the_run_is_raised_to_the_rung_that_asks_every_time(monkeypatch):
    """The real path. `P7-03`'s ladder is the product's confirmation mechanism
    and the request routes into it (`Law 14`) rather than into a second idea of
    what "ask me" means."""
    _patch_loop_basics(monkeypatch)
    seen = {}

    real_ctx = al.ToolRunSecurityContext

    def _capture(*args, **kwargs):
        seen["rung"] = kwargs.get("rung")
        return real_ctx(*args, **kwargs)

    monkeypatch.setattr(al, "ToolRunSecurityContext", _capture, raising=False)
    monkeypatch.setattr(al, "resolve_trust_rung",
                        lambda: TrustRung.GATE_ON_UNTRUSTED, raising=False)

    async def _fake_stream(_candidates, messages, **kwargs):
        yield _delta_chunk("done")
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(al, "stream_llm_with_fallback", _fake_stream, raising=False)

    policy = build_effective_tool_policy(last_user_message="Ask me before using tools.")
    _collect(
        al.stream_agent_loop(
            "http://local.test/v1", "local-model",
            [{"role": "user", "content": "Ask me before using tools."}],
            max_rounds=1, relevant_tools={"bash"}, tool_policy=policy,
        )
    )
    assert seen["rung"] is TrustRung.ASK_EVERY_TIME


def test_an_ordinary_turn_is_left_on_its_stored_rung(monkeypatch):
    """The other half of "it only ever raises": a turn that did not ask keeps
    whatever the operator configured."""
    _patch_loop_basics(monkeypatch)
    seen = {}
    real_ctx = al.ToolRunSecurityContext

    def _capture(*args, **kwargs):
        seen["rung"] = kwargs.get("rung")
        return real_ctx(*args, **kwargs)

    monkeypatch.setattr(al, "ToolRunSecurityContext", _capture, raising=False)
    monkeypatch.setattr(al, "resolve_trust_rung",
                        lambda: TrustRung.GATE_ON_UNTRUSTED, raising=False)

    async def _fake_stream(_candidates, messages, **kwargs):
        yield _delta_chunk("done")
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(al, "stream_llm_with_fallback", _fake_stream, raising=False)
    policy = build_effective_tool_policy(last_user_message="Please read the README.")
    _collect(
        al.stream_agent_loop(
            "http://local.test/v1", "local-model",
            [{"role": "user", "content": "Please read the README."}],
            max_rounds=1, relevant_tools={"bash"}, tool_policy=policy,
        )
    )
    assert seen["rung"] is TrustRung.GATE_ON_UNTRUSTED


def test_the_model_is_told_it_will_be_asked(monkeypatch):
    """A gate nobody announced reads to the model as a broken tool. The
    directive is prepended on a confirmation turn and on no other."""
    _patch_loop_basics(monkeypatch)
    sent = []

    async def _fake_stream(_candidates, messages, **kwargs):
        sent.append(messages)
        yield _delta_chunk("ok")
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(al, "stream_llm_with_fallback", _fake_stream, raising=False)

    def _run_with(message):
        sent.clear()
        policy = build_effective_tool_policy(last_user_message=message)
        _collect(
            al.stream_agent_loop(
                "http://local.test/v1", "local-model",
                [{"role": "user", "content": message}],
                max_rounds=1, relevant_tools={"bash"}, tool_policy=policy,
            )
        )
        return json.dumps(sent[0]) if sent else ""

    confirm_text = _run_with("Ask me before using tools.")
    plain_text = _run_with("Please read the README.")
    assert "CONFIRM-BEFORE-TOOLS" in confirm_text
    assert "CONFIRM-BEFORE-TOOLS" not in plain_text
