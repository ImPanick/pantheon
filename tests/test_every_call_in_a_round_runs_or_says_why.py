# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1620` — after one call in a round asks, the round's other calls are not
dropped without a word.

Measured before the fix, with this file's round: the model asked for
`list_served_models`, `list_models` and `list_cached_models` in one step; the
first ran, its result (provider-controlled model names) armed the gate, and
`list_models` asked. `list_cached_models` was then neither run nor refused —
no event for it reached the person, it was not on the record a reload draws
from, and the run that resumed after the yes rebuilt the round with two calls
of three, so the model was not told either.

A question stays a turn boundary — nothing after it in the step runs before it
is answered — and each call after it is now refused in a sentence: shown to
the person as a refused call, kept on the record, and handed to the model as
that call's own result when the turn resumes.

Driven through the real agent loop and the real approval store, with the
model's sockets and the tools' execution stood in for (`B1199`'s harness).
"""

import asyncio
import json

import src.agent_loop as agent_loop

ROUND = ["list_served_models", "list_models", "list_cached_models"]
NOT_RUN = ("'list_cached_models' was not run: it came after 'list_models' in the same step, "
           "and 'list_models' waits for an answer.")


def _patch(monkeypatch, script, sent):
    monkeypatch.setattr(agent_loop, "get_setting", lambda key, default=None: default)
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: None)
    monkeypatch.setattr(agent_loop, "estimate_tokens", lambda *a, **k: 10)
    monkeypatch.setattr(agent_loop, "blocked_tools_for_owner", lambda owner: set())
    monkeypatch.setattr(agent_loop, "_agent_route_tool_mode", lambda *a, **k: (True, False, False))
    steps = iter(script)

    async def fake_stream(candidates, messages, *args, **kwargs):
        sent.append(json.loads(json.dumps(messages, default=str)))
        step = next(steps, "Done.")
        if isinstance(step, list):
            yield f'data: {json.dumps({"type": "tool_calls", "calls": step})}\n\n'
        else:
            yield f"data: {json.dumps({'delta': step})}\n\n"
        yield "data: [DONE]\n\n"

    ran = []

    async def fake_execute(block, *args, **kwargs):
        ran.append(block.tool_type)
        if block.tool_type == "ask_user":
            # The real tool: it touches nothing and returns the question.
            from src.agent_tools.interaction_tools import AskUserTool
            return await AskUserTool().execute(block.content, {})
        return block.tool_type, {"output": f"{block.tool_type}: qwen3-8b", "exit_code": 0}

    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", fake_stream)
    monkeypatch.setattr(agent_loop, "execute_tool_block", fake_execute)
    return ran


def _events(generator):
    async def _drain():
        return [chunk async for chunk in generator]

    out = []
    for chunk in asyncio.run(_drain()):
        if chunk.startswith("data: {"):
            try:
                out.append(json.loads(chunk[6:]))
            except json.JSONDecodeError:
                pass
    return out


def _turn(**kw):
    return _events(agent_loop.stream_agent_loop(
        "http://local.test/v1", "small-local-model",
        [{"role": "user", "content": "which models are served, listed and cached?"}],
        max_rounds=3, owner="alice", session_id="s-b1620", workspace=None,
        relevant_tools=set(ROUND), **kw))


def _calls():
    return [{"id": f"call_{n}", "name": name, "arguments": "{}"} for n, name in enumerate(ROUND)]


def test_a_call_after_the_card_is_refused_in_a_sentence(monkeypatch):
    """The person sees every call of the step: the first ran, the second asks,
    the third says why it did not run — before the card, which stays last."""
    sent = []
    ran = _patch(monkeypatch, [_calls(), "Done."], sent)
    events = _turn()

    assert ran == ["list_served_models"], "nothing after the question runs before it is answered"
    blocked = [e for e in events if e.get("type") == "tool_blocked"]
    assert [b["tool"] for b in blocked] == ["list_cached_models"], events
    assert blocked[0]["reason"].startswith(NOT_RUN)
    assert blocked[0]["policy"] == agent_loop.AFTER_A_QUESTION
    kinds = [e.get("type") for e in events if e.get("type") in ("tool_blocked", "ask_user")]
    assert kinds == ["tool_blocked", "ask_user"], "the card is still the step's last word"

    # On the record a reload draws from, in the order the calls were made.
    record = next(e for e in events if e.get("type") == "metrics")["data"]["tool_events"]
    assert [e["tool"] for e in record] == ROUND
    assert record[2]["blocked"] is True and record[2]["output"].startswith(NOT_RUN)
    assert record[1].get("ask_user"), "the second call's card is kept on it"


def test_the_turn_resumed_after_the_yes_answers_every_call(monkeypatch):
    """After the yes, the model is asked with the whole round: three calls,
    each answered — the first's result, the approved one's, and the third's
    sentence — so it can ask for `list_cached_models` again."""
    sent = []
    _patch(monkeypatch, [_calls(), "Done."], sent)
    events = _turn()
    card = next(e["data"] for e in events if e.get("type") == "ask_user")
    grant = agent_loop.tool_approval_store.consume(
        card["approval_id"], decision="approve", owner="alice", session_id="s-b1620")
    assert grant is not None and grant.pending.tool_name == "list_models"

    resumed_sent = []
    ran = _patch(monkeypatch, ["Done."], resumed_sent)
    _events(agent_loop.stream_agent_loop(
        "http://local.test/v1", "small-local-model",
        [{"role": "user", "content": "yes"}], max_rounds=3, owner="alice",
        session_id="s-b1620", workspace=None, relevant_tools=set(ROUND), exact_approval=grant))

    assert ran == ["list_models"], "the yes runs the call it was given for, and only that one"
    messages = resumed_sent[0]
    asked = next(m for m in messages if m.get("role") == "assistant" and m.get("tool_calls"))
    assert [c["function"]["name"] for c in asked["tool_calls"]] == ROUND
    answers = {m["tool_call_id"]: m["content"] for m in messages if m.get("role") == "tool"}
    assert set(answers) == {"call_0", "call_1", "call_2"}, "every call the model made has its answer"
    assert "list_models: qwen3-8b" in answers["call_1"]
    assert NOT_RUN in answers["call_2"]


def test_a_question_the_model_asks_leaves_no_call_unanswered_either(monkeypatch):
    """The model's own `ask_user` is a question too: a call after it in the
    same step is refused in the same sentence, not lost."""
    sent = []
    ran = _patch(monkeypatch, [[
        {"id": "q", "name": "ask_user", "arguments": json.dumps(
            {"question": "Which endpoint?", "options": [{"label": "A"}, {"label": "B"}]})},
        {"id": "l", "name": "list_cached_models", "arguments": "{}"},
    ], "Done."], sent)
    events = _events(agent_loop.stream_agent_loop(
        "http://local.test/v1", "small-local-model",
        [{"role": "user", "content": "check my cached models"}], max_rounds=3, owner="alice",
        session_id="s-b1620-q", workspace=None, relevant_tools={"ask_user", "list_cached_models"}))
    blocked = [e for e in events if e.get("type") == "tool_blocked"]
    assert [b["tool"] for b in blocked] == ["list_cached_models"], events
    assert "came after 'ask_user'" in blocked[0]["reason"]
    assert ran == ["ask_user"]
