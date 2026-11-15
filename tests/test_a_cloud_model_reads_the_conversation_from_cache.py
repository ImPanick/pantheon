# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2125`: a cloud model reads what it was already sent from its cache.

The owner, 2026-11-15: *"we need to rework the cloud hints entirely that can
get VERY expensive, VERY fast... massive waste of tokens."* Before this, an
Anthropic request marked only the tools and the system prompt, so every agent
round paid full price for the whole conversation again; OpenAI got no cache
key; and Claude or Gemini through OpenRouter cached nothing. These drive
`stream_llm` and record the body it puts on the wire.
"""
from __future__ import annotations

import asyncio
import json

import pytest

import src.llm_core as llm_core
from src import prompt_cache


class _Resp:
    status_code = 200

    async def aiter_lines(self):
        yield "data: [DONE]"

    async def aread(self):
        return b""


class _Ctx:
    async def __aenter__(self):
        return _Resp()

    async def __aexit__(self, *a):
        return False


class _Recorder:
    def __init__(self):
        self.payload = None

    def stream(self, method, url, **kw):
        self.payload = kw.get("json") or {}
        return _Ctx()


def _sent(monkeypatch, url, model, messages, tools=None, session_id="chat-1"):
    recorder = _Recorder()
    monkeypatch.setattr(llm_core, "_get_http_client", lambda: recorder)
    monkeypatch.setattr(llm_core, "_is_host_dead", lambda u: False)
    monkeypatch.setattr(llm_core, "note_model_activity", lambda *a, **k: None)
    monkeypatch.setattr(llm_core, "_clear_host_dead", lambda *a, **k: None)
    monkeypatch.setattr(llm_core, "get_context_length", lambda u, m: 32768)

    async def go():
        return [c async for c in llm_core.stream_llm(url, model, messages, tools=tools,
                                                      session_id=session_id)]
    asyncio.run(go())
    assert recorder.payload is not None, "nothing was sent"
    return recorder.payload


TOOL = {"type": "function", "function": {
    "name": "read_file", "description": "Read a file.",
    "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}}}


def _agent_round():
    return [
        {"role": "system", "content": "You are Pantheon." * 50},
        {"role": "user", "content": "earlier question"},
        {"role": "assistant", "content": "earlier answer"},
        {"role": "user", "content": "read the config and tell me the port"},
        {"role": "assistant", "content": "", "tool_calls": [{
            "id": "c1", "type": "function",
            "function": {"name": "read_file", "arguments": "{\"path\": \"app.toml\"}"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "port = 8080\n" * 200},
    ]


def _marks(payload):
    found = []
    for t in payload.get("tools") or []:
        if "cache_control" in t:
            found.append("tools")
    for b in payload.get("system") or []:
        if isinstance(b, dict) and "cache_control" in b:
            found.append("system")
    for i, m in enumerate(payload.get("messages") or []):
        for b in m.get("content") if isinstance(m.get("content"), list) else []:
            if isinstance(b, dict) and "cache_control" in b:
                found.append(i)
    return found


# ── Anthropic ───────────────────────────────────────────────────────────────

def test_an_agent_round_marks_the_conversation_not_only_the_prefix(monkeypatch):
    body = _sent(monkeypatch, "https://api.anthropic.com/v1", "claude-sonnet-4-5",
                 _agent_round(), tools=[TOOL])
    marks = _marks(body)
    last = len(body["messages"]) - 1
    assert marks.count("tools") == 1 and marks.count("system") == 1, marks
    assert last in marks, "the end of the request is not marked, so the next round re-pays it"
    persons = [i for i, m in enumerate(body["messages"])
               if m["role"] == "user" and not any(b.get("type") == "tool_result"
                                                  for b in m["content"] if isinstance(b, dict))]
    assert persons[-1] in marks, "the person's latest message is not a read point"
    assert len(marks) <= prompt_cache.ANTHROPIC_MAX_BREAKPOINTS
    # The marker is all that changed: the text is the text.
    tool_result = body["messages"][last]["content"][-1]
    assert tool_result["type"] == "tool_result" and tool_result["content"].startswith("port = 8080")


def test_a_one_off_call_writes_no_conversation_cache(monkeypatch):
    body = _sent(monkeypatch, "https://api.anthropic.com/v1", "claude-sonnet-4-5",
                 [{"role": "user", "content": "Title this chat in four words."}])
    assert _marks(body) == []


def test_two_rounds_share_every_byte_before_the_new_step(monkeypatch):
    first = _agent_round()[:4]
    second = _agent_round()
    a = _sent(monkeypatch, "https://api.anthropic.com/v1", "claude-sonnet-4-5", first, tools=[TOOL])
    b = _sent(monkeypatch, "https://api.anthropic.com/v1", "claude-sonnet-4-5", second, tools=[TOOL])
    strip = lambda x: json.loads(json.dumps(x).replace(', "cache_control": {"type": "ephemeral"}', ""))
    assert strip(a["system"]) == strip(b["system"]) and strip(a["tools"]) == strip(b["tools"])
    assert strip(a["messages"]) == strip(b["messages"][:len(a["messages"])])


# ── OpenAI ──────────────────────────────────────────────────────────────────

def test_openai_gets_a_cache_key_for_the_conversation_and_not_its_id(monkeypatch):
    body = _sent(monkeypatch, "https://api.openai.com/v1", "gpt-4.1", _agent_round(),
                 tools=[TOOL], session_id="chat-1")
    again = _sent(monkeypatch, "https://api.openai.com/v1", "gpt-4.1", _agent_round(),
                  tools=[TOOL], session_id="chat-1")
    other = _sent(monkeypatch, "https://api.openai.com/v1", "gpt-4.1", _agent_round(),
                  tools=[TOOL], session_id="chat-2")
    key = body.get("prompt_cache_key")
    assert key and key == again["prompt_cache_key"] and key != other["prompt_cache_key"]
    assert "chat-1" not in key


@pytest.mark.parametrize("url", ["https://api.mistral.ai/v1", "https://api.groq.com/openai/v1"])
def test_a_strict_provider_gets_no_field_it_would_refuse(monkeypatch, url):
    body = _sent(monkeypatch, url, "some-model", _agent_round(), tools=[TOOL])
    assert "prompt_cache_key" not in body and "cache_control" not in json.dumps(body)


# ── OpenRouter ──────────────────────────────────────────────────────────────

def test_claude_through_openrouter_marks_the_prefix_and_the_latest_words(monkeypatch):
    body = _sent(monkeypatch, "https://openrouter.ai/api/v1", "anthropic/claude-sonnet-4.5",
                 _agent_round(), tools=[TOOL])
    msgs = body["messages"]
    assert msgs[0]["role"] == "system" and msgs[0]["content"][-1]["cache_control"]
    person = max(i for i, m in enumerate(msgs) if m["role"] == "user")
    assert msgs[person]["content"][-1]["cache_control"]
    assert all(isinstance(m.get("content"), str) or m.get("content") is None
               for m in msgs if m["role"] == "tool"), "a tool message was reshaped"


def test_through_openrouter_too_two_rounds_share_every_byte(monkeypatch):
    url, model = "https://openrouter.ai/api/v1", "anthropic/claude-sonnet-4.5"
    a = _sent(monkeypatch, url, model, _agent_round()[:4], tools=[TOOL])
    b = _sent(monkeypatch, url, model, _agent_round(), tools=[TOOL])
    strip = lambda x: json.loads(json.dumps(x).replace(', "cache_control": {"type": "ephemeral"}', ""))
    assert strip(a["messages"]) == strip(b["messages"][:len(a["messages"])])


def test_an_openrouter_model_that_caches_by_itself_is_left_alone(monkeypatch):
    body = _sent(monkeypatch, "https://openrouter.ai/api/v1", "openai/gpt-4.1",
                 _agent_round(), tools=[TOOL])
    assert "cache_control" not in json.dumps(body)


# ── a local server ──────────────────────────────────────────────────────────

def test_a_local_server_gets_none_of_the_cloud_hints(monkeypatch):
    body = _sent(monkeypatch, "http://127.0.0.1:1234/v1", "qwen3-27b", _agent_round(),
                 tools=[TOOL])
    text = json.dumps(body)
    assert "cache_control" not in text and "prompt_cache_key" not in text
