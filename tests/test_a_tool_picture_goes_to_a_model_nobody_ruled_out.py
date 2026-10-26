# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1281` — a tool's picture goes to a model nobody ruled out, and a refusal is recovered.

`tool_result_images.for_model` asked `model_supports_vision`, which keeps the
name list's *no* when the endpoint says nothing, so a `computer` screenshot to
a model the list does not know was replaced by words — the
`D-2026-10-07-02` §1 shape `B1279` closed for a person's picture. It was left
because a refusal comes mid-run and the run could not drop the picture and say
so. Now unknown sends it; a round refused for its picture is asked again with
the pictures in words, every later request of the turn carries words, and the
chat says so once.

Driven through the real loop, the real fallback wrapper and the real request
factory; only the socket (`llm_core.stream_llm`) is replaced — a server that
refuses image parts the way llama.cpp does without its mmproj — and the tool
that returns the screenshot.
"""
import asyncio
import json

import pytest

import src.agent_tools  # noqa: F401  (break the agent_tools <-> tool_parsing import cycle)
import src.chat_helpers as chat_helpers
import src.tool_result_images as tri

PNG = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
UNKNOWN_MODEL = "text-box-7b"   # a name the list does not know; the server says nothing


def _image_parts(messages):
    return sum(1 for m in messages if isinstance(m.get("content"), list)
               for p in m["content"] if isinstance(p, dict) and p.get("type") == "image_url")


@pytest.fixture
def no_answer_from_the_endpoint(monkeypatch):
    monkeypatch.setattr(chat_helpers, "endpoint_supports_vision", lambda url, model: None)
    import src.settings as settings
    monkeypatch.setattr(settings, "get_setting", lambda key, default=None: default)


def test_an_unknown_model_is_sent_the_picture(no_answer_from_the_endpoint):
    assert chat_helpers.vision_answer(UNKNOWN_MODEL, "http://local.test/v1") is None
    assert tri.sees_images(UNKNOWN_MODEL, "http://local.test/v1") is True


def test_a_model_the_endpoint_says_cannot_see_still_gets_words(monkeypatch):
    monkeypatch.setattr(chat_helpers, "endpoint_supports_vision", lambda url, model: False)
    assert tri.sees_images(UNKNOWN_MODEL, "http://local.test/v1") is False


def test_a_refusal_counts_only_for_a_request_that_carried_a_picture():
    refusal = ('event: error\ndata: {"status": 400, "text": "image input is not supported '
               '- hint: if this is unexpected, you may need to provide the mmproj"}\n\n')
    picture = [tri.images_message([{"result": {"images": [
        {"type": "image", "data": PNG, "mimeType": "image/png"}]}, "tool_name": "computer"}])]
    assert tri.refused_for_its_picture(refusal, picture) is True
    assert tri.refused_for_its_picture(refusal, [{"role": "user", "content": "hi"}]) is False
    assert tri.refused_for_its_picture(
        'event: error\ndata: {"status": 400, "text": "context too long"}\n\n', picture) is False


# ── Through the real loop ───────────────────────────────────────────────────

def _drive(monkeypatch, *, refuses):
    import src.agent_loop as agent_loop
    import src.llm_core as llm_core
    from src.agent_tools import ToolBlock

    monkeypatch.setattr(agent_loop, "get_setting",
                        lambda key, default=None: "gate_on_untrusted" if key == "trust_rung" else default,
                        raising=False)
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: None, raising=False)
    monkeypatch.setattr(agent_loop, "estimate_tokens", lambda *a, **k: 10)
    monkeypatch.setattr(agent_loop, "blocked_tools_for_owner", lambda owner: set(), raising=False)
    monkeypatch.setattr(agent_loop, "_agent_route_tool_mode",
                        lambda url, model, owner=None, headers=None: (False, False, False))
    monkeypatch.setattr(chat_helpers, "endpoint_supports_vision", lambda url, model: None)

    sent = []   # the image parts on each request that reached the socket

    async def socket(url, model, messages, *a, **k):
        sent.append(_image_parts(messages))
        if refuses and _image_parts(messages):
            yield ('event: error\ndata: ' + json.dumps({
                "status": 400, "text": "image input is not supported - hint: if this is "
                "unexpected, you may need to provide the mmproj"}) + '\n\n')
            return
        reply = "```web_fetch\nhttp://192.168.1.9/screen\n```" if len(sent) == 1 else "I can see the desktop."
        yield f"data: {json.dumps({'delta': reply})}\n\n"
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(llm_core, "stream_llm", socket)

    async def run_tool(block, *a, **k):
        return block.tool_type, {"output": "Took a screenshot.", "exit_code": 0,
                                 "images": [{"type": "image", "data": PNG,
                                             "mimeType": "image/png"}]}

    monkeypatch.setattr(agent_loop, "execute_tool_block", run_tool)

    async def collect():
        return [c async for c in agent_loop.stream_agent_loop(
            "http://local.test/v1", UNKNOWN_MODEL, [{"role": "user", "content": "What is on screen?"}],
            max_rounds=3, relevant_tools={"web_fetch"}, owner="alice", session_id="b1281")]

    events = []
    for chunk in asyncio.run(collect()):
        if chunk.startswith("data: ") and not chunk.startswith("data: [DONE]"):
            try:
                events.append(json.loads(chunk[6:]))
            except json.JSONDecodeError:
                pass
        elif chunk.startswith("event: error"):
            events.append({"type": "error", "raw": chunk})
    return events, sent


def _said(events):
    return "".join(e.get("delta", "") for e in events if isinstance(e.get("delta"), str))


def test_a_model_that_can_see_is_sent_the_screenshot(monkeypatch):
    events, sent = _drive(monkeypatch, refuses=False)
    assert sent[:2] == [0, 1], "the screenshot was put into words for a model nobody ruled out"
    assert tri.PICTURES_REFUSED_NOTE not in _said(events)


def test_a_refusal_is_asked_again_in_words_and_said_once(monkeypatch):
    events, sent = _drive(monkeypatch, refuses=True)

    # Round two carried the picture and was refused; asked again in words.
    assert sent[:3] == [0, 1, 0]
    said = _said(events)
    assert said.count(tri.PICTURES_REFUSED_NOTE) == 1
    assert "I can see the desktop." in said
    assert not [e for e in events if e.get("type") == "error"], "the turn ended on the refusal"
    assert not [e for e in events if e.get("type") == "agent_terminal"]
