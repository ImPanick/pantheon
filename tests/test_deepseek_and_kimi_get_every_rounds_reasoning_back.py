# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1797`. DeepSeek and Kimi were sent a turn's earlier tool rounds without
their reasoning.

DeepSeek's thinking mode (its API's default for `deepseek-v4-pro` and
`deepseek-v4-flash`) and Moonshot's Kimi thinking models (`kimi-k2.6`) want
every assistant tool-call message of a turn sent back with the
`reasoning_content` it came with, and refuse the request with HTTP 400 when
one is missing. `_append_tool_results` took `reasoning_content` off every
earlier assistant message each time it appended a round, so only the newest
tool-call turn kept it: the request after a turn's second tool round carried
round one's call bare, and the turn ended in a stream error. A turn resumed
after an approval card lost it the same way. The strip is a guard for local
chat templates, Nemotron's first, which re-inject every earlier
`reasoning_content` as a think block and so pile a run's reasoning up round
after round.

Now a route to DeepSeek's or Moonshot's API keeps every round's reasoning, and
a tool round that brought none carries an empty `reasoning_content` there
rather than none. Every other route keeps the strip exactly as before.

Upstream Odysseus fixed the same gap in its own agent harness (508e017d),
which Pantheon does not have; this is the rule in Pantheon's loop.

Driven (`Law 20`): the real agent loop, the real fallback wrapper and the
real `stream_llm`, down to the payload it posts, and the real approval store
for the resumed turn. Only the model's socket and the tools' execution are
stood in for (`B1199`'s harness, with the socket where its stream stood).
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

import src.agent_loop as agent_loop
import src.llm_core as llm_core
import src.model_context as model_context

DEEPSEEK = ("https://api.deepseek.com/v1", "deepseek-v4-pro")
KIMI = ("https://api.moonshot.ai/v1", "kimi-k2.6")
# A vLLM / llama.cpp server on the LAN: the chat templates the strip is for.
NEMOTRON = ("http://192.168.1.20:8000/v1", "nemotron-3-nano")
ROUTES = {"deepseek": DEEPSEEK, "kimi": KIMI, "nemotron": NEMOTRON}

R1 = "The plan has to exist before anything else."
R2 = "Step one is ticked; now the second step."
ABSENT = object()


def _round(reasoning="", call_id=None, tool="update_plan", args="{}", content=None):
    """One streamed answer, as an OpenAI-compatible server sends it."""
    deltas = []
    if reasoning:
        deltas.append({"reasoning_content": reasoning})
    if content:
        deltas.append({"content": content})
    if call_id:
        deltas.append({"tool_calls": [{"index": 0, "id": call_id, "type": "function",
                                       "function": {"name": tool, "arguments": args}}]})
    return [f"data: {json.dumps({'choices': [{'delta': d}]})}" for d in deltas] + ["data: [DONE]"]


DONE = _round(content="Done.")
PLAN_1 = json.dumps({"plan": "- [ ] draft\n- [ ] send"})
PLAN_2 = json.dumps({"plan": "- [x] draft\n- [ ] send"})


class _Socket:
    """The model's socket: every payload `stream_llm` posts, as it posted it,
    each answered with the next scripted round."""

    def __init__(self, rounds):
        self.sent = []
        self._rounds = iter(rounds)

    def stream(self, method, url, **kwargs):
        # A copy: the loop goes on changing its own messages after the post.
        self.sent.append(json.loads(json.dumps(kwargs["json"])))
        lines = next(self._rounds)

        async def aiter_lines():
            for line in lines:
                yield line

        async def aread():
            return b""

        class _Answer:
            async def __aenter__(self):
                return SimpleNamespace(status_code=200, aiter_lines=aiter_lines, aread=aread)

            async def __aexit__(self, *exc):
                return False

        return _Answer()


@pytest.fixture
def model(monkeypatch):
    """`model(rounds)` scripts the model's answers and returns its socket."""
    monkeypatch.setattr(llm_core, "_is_host_dead", lambda url: False)
    monkeypatch.setattr(llm_core, "note_model_activity", lambda *a, **k: None)
    monkeypatch.setattr(model_context, "_query_context_length",
                        lambda url, model: (131_072, True, model_context.BASIS_REPORTED))
    monkeypatch.setattr(model_context, "_context_cache", {})
    monkeypatch.setattr(agent_loop, "get_setting", lambda key, default=None: default)
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: None)
    monkeypatch.setattr(agent_loop, "blocked_tools_for_owner", lambda owner: set())
    monkeypatch.setattr(agent_loop, "_agent_route_tool_mode", lambda *a, **k: (True, False, False))

    async def fake_execute(block, *args, **kwargs):
        return block.tool_type, {"output": f"{block.tool_type}: qwen3-8b", "exit_code": 0}

    monkeypatch.setattr(agent_loop, "execute_tool_block", fake_execute)
    llm_core._response_cache.clear()

    def script(rounds):
        socket = _Socket(rounds)
        monkeypatch.setattr(llm_core, "_client_for", lambda url: socket)
        return socket

    yield script
    llm_core._response_cache.clear()


def _events(route, words, tools, **kwargs):
    url, model_id = route

    async def drain():
        return [chunk async for chunk in agent_loop.stream_agent_loop(
            url, model_id, [{"role": "user", "content": words}], max_rounds=4,
            owner="alice", session_id="s-b1797", workspace=None,
            relevant_tools=set(tools), **kwargs)]

    out = []
    for chunk in asyncio.run(drain()):
        if chunk.startswith("data: {"):
            try:
                out.append(json.loads(chunk[6:]))
            except json.JSONDecodeError:
                pass
    return out


def _reasoning_by_call(payload):
    """Each assistant tool-call turn of a posted payload: its call id and its
    `reasoning_content`, `ABSENT` when it has none."""
    return [(m["tool_calls"][0]["id"], m.get("reasoning_content", ABSENT))
            for m in payload["messages"] if m["role"] == "assistant" and m.get("tool_calls")]


def _two_tool_rounds(model, route, first_reasoning=R1):
    socket = model([_round(first_reasoning, "call_1", args=PLAN_1),
                    _round(R2, "call_2", args=PLAN_2), DONE])
    _events(route, "Draft the release note, then send it.", {"update_plan"})
    assert len(socket.sent) == 3, "two tool rounds, then the answer"
    return socket.sent


@pytest.mark.parametrize("name", ["deepseek", "kimi"])
def test_deepseek_and_kimi_are_sent_every_tool_rounds_reasoning(model, name):
    """The request after the second tool round: both tool-call turns, each
    with the reasoning it came with."""
    sent = _two_tool_rounds(model, ROUTES[name])
    assert _reasoning_by_call(sent[1]) == [("call_1", R1)]
    assert _reasoning_by_call(sent[2]) == [("call_1", R1), ("call_2", R2)]


def test_a_local_template_is_still_sent_only_the_newest_rounds_reasoning(model):
    """The Nemotron guard stands: the third request carries round one's call
    without its reasoning, as it always did."""
    sent = _two_tool_rounds(model, NEMOTRON)
    assert _reasoning_by_call(sent[1]) == [("call_1", R1)]
    assert _reasoning_by_call(sent[2]) == [("call_1", ABSENT), ("call_2", R2)]


@pytest.mark.parametrize("name, first", [("deepseek", ""), ("kimi", ""), ("nemotron", ABSENT)],
                         ids=["deepseek", "kimi", "nemotron"])
def test_a_tool_round_that_brought_no_reasoning_carries_an_empty_one_there(model, name, first):
    """A round that brought no reasoning: an empty `reasoning_content` on
    DeepSeek's and Moonshot's APIs, which name a missing one; still no field
    anywhere else."""
    sent = _two_tool_rounds(model, ROUTES[name], first_reasoning="")
    assert _reasoning_by_call(sent[2]) == [("call_1", first), ("call_2", R2)]


@pytest.mark.parametrize("name, first", [("deepseek", R1), ("kimi", R1), ("nemotron", ABSENT)],
                         ids=["deepseek", "kimi", "nemotron"])
def test_a_turn_resumed_after_a_card_keeps_the_reasoning_it_had(model, name, first):
    """Round one's result (provider-controlled model names) arms the gate,
    round two's call asks, and the person says yes: the resumed turn's first
    request carries both rounds, round one with its reasoning on DeepSeek and
    Kimi, without it elsewhere (`B1069`'s resume, `B1620`'s round)."""
    route = ROUTES[name]
    tools = {"list_served_models", "list_models"}
    socket = model([_round(R1, "call_1", tool="list_served_models"),
                    _round(R2, "call_2", tool="list_models"), DONE])
    events = _events(route, "Which models are served, and which are listed?", tools)
    card = next(e["data"] for e in events if e.get("type") == "ask_user")
    assert len(socket.sent) == 2, "the card stopped the second round"
    grant = agent_loop.tool_approval_store.consume(
        card["approval_id"], decision="approve", owner="alice", session_id="s-b1797")
    assert grant is not None and grant.pending.tool_name == "list_models"

    _events(route, "yes", tools, exact_approval=grant)

    assert len(socket.sent) == 3
    assert _reasoning_by_call(socket.sent[2]) == [("call_1", first), ("call_2", R2)]


@pytest.mark.parametrize("url, keeps", [
    ("https://api.deepseek.com/v1", True),
    ("https://api.deepseek.com", True),
    ("https://api.moonshot.ai/v1", True),
    ("https://api.moonshot.cn/v1", True),
    ("http://192.168.1.20:8000/v1", False),
    ("http://localhost:11434/v1", False),
    ("https://api.openai.com/v1", False),
    ("https://deepseek.com.example/v1", False),
    ("", False),
])
def test_only_deepseeks_and_moonshots_apis_keep_every_rounds_reasoning(url, keeps):
    assert agent_loop._keeps_every_reasoning(url) is keeps
