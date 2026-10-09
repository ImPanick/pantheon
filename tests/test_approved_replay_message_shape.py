# SPDX-License-Identifier: AGPL-3.0-or-later
"""Regression coverage for the assistant turn an approved-action replay appends.

Anthropic's Messages API rejects a non-final assistant message whose content is
empty, so the resumed turn after a tool approval used to fail before the model
ever saw the sealed result. The replay injects its result with no assistant
prose for that round, which is the only path that produced such a turn.
"""

import src.llm_core as llm_core
from src.agent_loop import _append_tool_results

_RESULT = "bash: ok\nhello"
_RECORD = {
    "tool_name": "bash",
    "content": "printf hello",
    "result": {"output": "hello", "exit_code": 0},
    "text": _RESULT,
}


def _replay_messages(round_response="", round_reasoning=""):
    """Mirror the approved-action injection in stream_agent_loop."""
    messages = [
        {"role": "system", "content": "system preface"},
        {"role": "user", "content": "run the command and summarise it"},
    ]
    _append_tool_results(
        messages,
        round_response,
        [],
        [_RESULT],
        [_RESULT],
        False,
        0,
        round_reasoning=round_reasoning,
        tool_result_records=[_RECORD],
    )
    return messages


def _empty_assistant_turns(messages):
    return [
        index
        for index, message in enumerate(messages)
        if message.get("role") == "assistant"
        and not str(message.get("content") or "").strip()
        and not message.get("tool_calls")
    ]


def test_replay_appends_no_empty_assistant_turn():
    assert _empty_assistant_turns(_replay_messages()) == []


def test_replay_payload_has_no_empty_content_message_for_anthropic():
    """The constraint this file exists for, asserted over the whole payload.

    `FIX-2026-10-09` item 1 corrected this case's premise. It used to read
    `== ["user"]`, because the sanitizer glued the person's request and the
    sealed tool output into one message; the merge now refuses to join the
    application's framing to the person's words, so the payload is
    user / assistant / user. **What this file protects is unchanged**: Anthropic
    rejects a non-final assistant message with empty content, and the boundary
    the merge inserts carries text, so no message in the payload is empty.
    """
    sanitized = llm_core._sanitize_llm_messages(_replay_messages())
    payload = llm_core._build_anthropic_payload(
        "claude-sonnet-5", sanitized, 0.2, 512
    )
    chat = payload["messages"]
    assert [message["role"] for message in chat] == ["user", "assistant", "user"]
    assert all(str(message.get("content") or "").strip() for message in chat)


def test_replay_keeps_the_request_and_the_tool_output_in_separate_turns():
    """`FIX-2026-10-09` item 1. The operator asked; a tool answered; the model
    must be able to tell which is which.

    Was: the two adjacent user messages were merged with `\n\n`, so the
    request and an `UNTRUSTED SOURCE DATA` block arrived as one turn — the
    shape the owner's export shows a local model reading as a prompt-injection
    test. Now a boundary separates them and the order still holds.
    """
    sanitized = llm_core._sanitize_llm_messages(_replay_messages())
    assert [m.get("role") for m in sanitized] == [
        "system", "user", "assistant", "user",
    ]
    request, boundary, output = sanitized[1], sanitized[2], sanitized[3]
    assert request["content"] == "run the command and summarise it"
    assert "UNTRUSTED SOURCE DATA" not in request["content"]
    assert boundary["content"].strip()
    assert output["content"].startswith("UNTRUSTED SOURCE DATA")
    assert output["content"].index("UNTRUSTED SOURCE DATA") < output["content"].index("hello")


def test_a_round_with_prose_still_appends_its_assistant_turn():
    messages = _replay_messages(round_response="running that now")
    assistants = [m for m in messages if m.get("role") == "assistant"]
    assert [m["content"] for m in assistants] == ["running that now"]


def test_reasoning_only_round_keeps_its_carrier_and_its_known_empty_content():
    """Characterises the one empty-content turn this change deliberately leaves.

    A round with reasoning and no prose still appends its carrier, and that
    carrier's content is still "", which Anthropic would still reject. Dropping
    it would lose the reasoning DeepSeek thinking mode requires on the next
    request, and the approval replay never takes this path because it passes no
    reasoning. Left alone on purpose; this test makes the gap visible instead of
    silent, and should be updated by whoever closes it.
    """
    messages = _replay_messages(round_reasoning="thinking about it")
    assistants = [m for m in messages if m.get("role") == "assistant"]
    assert len(assistants) == 1
    assert assistants[0].get("reasoning_content") == "thinking about it"
    assert assistants[0]["content"] == ""
