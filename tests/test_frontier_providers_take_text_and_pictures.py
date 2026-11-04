# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1750` — every frontier provider is reached at its real address, with a
picture in the shape it reads.

Panick, 2026-11-04: *"I used external LLM's for the first time. OpenAI endpoint
resulted in a 404 when delivering an image to decipher and analyze. Ensure API
routing is good to go for any/all Frontier AI endpoints."*

OpenAI answers `/v1/chat/completions` with a 404 for the models it serves only
at `/v1/responses` (the `-pro`, deep-research, computer-use and codex models).
Those now go to `/v1/responses`, and any other model OpenAI refuses that way is
learnt from the 404 and sent again there. The rest of this file pins the
address, auth header and picture shape for OpenAI, Anthropic, Gemini, xAI,
Mistral and OpenRouter, entered either as the form's preset or as a bare host.

The transport tests run the real `stream_llm` / `llm_call_async` / `llm_call`
builders and stop at the socket: the client records the request and answers
the way the provider does.
"""
from __future__ import annotations

import asyncio
import json

import pytest

import src.llm_core as llm_core
from src import openai_responses as responses
from src.endpoint_resolver import build_chat_url, build_headers, build_models_url

PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="

PICTURE_TURN = [
    {"role": "system", "content": "You are Pantheon."},
    {"role": "user", "content": [
        {"type": "text", "text": "Decipher and analyze this image."},
        {"type": "image_url", "image_url": {"url": PNG}},
    ]},
]


@pytest.fixture(autouse=True)
def _forget_learnt_models():
    responses._LEARNED.clear()
    yield
    responses._LEARNED.clear()


# ── addresses ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("base,chat", [
    # the endpoint form's presets
    ("https://api.openai.com/v1", "https://api.openai.com/v1/chat/completions"),
    ("https://api.anthropic.com", "https://api.anthropic.com/v1/messages"),
    ("https://api.anthropic.com/v1", "https://api.anthropic.com/v1/messages"),
    ("https://generativelanguage.googleapis.com/v1beta/openai",
     "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"),
    ("https://api.x.ai/v1", "https://api.x.ai/v1/chat/completions"),
    ("https://api.mistral.ai/v1", "https://api.mistral.ai/v1/chat/completions"),
    ("https://openrouter.ai/api/v1", "https://openrouter.ai/api/v1/chat/completions"),
    # the same providers entered as the bare host — each used to 404
    ("https://api.openai.com", "https://api.openai.com/v1/chat/completions"),
    ("https://generativelanguage.googleapis.com",
     "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"),
    ("https://generativelanguage.googleapis.com/v1beta",
     "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"),
    ("https://api.x.ai", "https://api.x.ai/v1/chat/completions"),
    ("https://api.mistral.ai", "https://api.mistral.ai/v1/chat/completions"),
    ("https://openrouter.ai", "https://openrouter.ai/api/v1/chat/completions"),
    ("https://openrouter.ai/api", "https://openrouter.ai/api/v1/chat/completions"),
    ("https://api.groq.com", "https://api.groq.com/openai/v1/chat/completions"),
    # a full chat URL pasted in is kept
    ("https://api.x.ai/v1/chat/completions", "https://api.x.ai/v1/chat/completions"),
])
def test_each_provider_is_reached_at_its_chat_address(base, chat):
    assert build_chat_url(base) == chat


@pytest.mark.parametrize("base,models", [
    ("https://api.x.ai", "https://api.x.ai/v1/models"),
    ("https://api.mistral.ai", "https://api.mistral.ai/v1/models"),
    ("https://openrouter.ai", "https://openrouter.ai/api/v1/models"),
    ("https://api.openai.com", "https://api.openai.com/v1/models"),
    ("https://api.anthropic.com", "https://api.anthropic.com/v1/models"),
])
def test_each_provider_lists_its_models_at_its_address(base, models):
    assert build_models_url(base) == models


def test_a_look_alike_host_is_left_as_entered():
    assert build_chat_url("https://api.x.ai.example.com") == "https://api.x.ai.example.com/chat/completions"


def test_a_bare_frontier_host_passed_straight_to_the_transport_gets_its_path():
    assert llm_core._normalize_openai_chat_url("https://api.x.ai") == "https://api.x.ai/v1/chat/completions"


# ── auth ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("base", [
    "https://api.openai.com/v1",
    "https://generativelanguage.googleapis.com/v1beta/openai",
    "https://api.x.ai/v1",
    "https://api.mistral.ai/v1",
    "https://openrouter.ai/api/v1",
])
def test_openai_compatible_providers_take_a_bearer_key(base):
    h = build_headers("k-123", base)
    assert h["Authorization"] == "Bearer k-123"
    assert "x-api-key" not in h


def test_anthropic_takes_its_own_key_header_and_version():
    h = build_headers("sk-ant-1", "https://api.anthropic.com")
    assert h == {"x-api-key": "sk-ant-1", "anthropic-version": "2023-06-01"}


def test_openrouter_is_told_who_is_calling():
    h = build_headers("sk-or-1", "https://openrouter.ai/api/v1")
    assert h["HTTP-Referer"] and h["X-OpenRouter-Title"] == "Pantheon"


# ── which models go to /v1/responses ────────────────────────────────────────

@pytest.mark.parametrize("model", [
    "gpt-5-pro", "gpt-5.1-pro", "gpt-5.2-pro-2025-12-11", "o3-pro", "o1-pro",
    "o3-deep-research", "o4-mini-deep-research", "computer-use-preview",
    "codex-mini-latest", "gpt-5-codex", "gpt-5.1-codex-max", "openai/gpt-5-pro",
])
def test_responses_only_models_on_openai_go_to_responses(model):
    assert responses.uses_responses_api("https://api.openai.com/v1/chat/completions", model)


@pytest.mark.parametrize("url,model", [
    ("https://api.openai.com/v1/chat/completions", "gpt-5"),
    ("https://api.openai.com/v1/chat/completions", "gpt-5.1"),
    ("https://api.openai.com/v1/chat/completions", "gpt-4o"),
    ("https://api.openai.com/v1/chat/completions", "gpt-4.1-mini"),
    ("https://api.openai.com/v1/chat/completions", "o3"),
    # OpenRouter serves the pro models over chat completions itself
    ("https://openrouter.ai/api/v1/chat/completions", "openai/gpt-5-pro"),
    ("http://localhost:1234/v1/chat/completions", "gpt-5-pro"),
])
def test_everything_else_stays_on_chat_completions(url, model):
    assert not responses.uses_responses_api(url, model)


def test_only_openais_responses_refusal_is_learnt():
    url = "https://api.openai.com/v1/chat/completions"
    not_found = '{"error":{"message":"The model `gpt-nope` does not exist or you do not have access to it.","code":"model_not_found"}}'
    assert not responses.learn_from_refusal(url, "gpt-nope", 404, not_found)
    assert not responses.uses_responses_api(url, "gpt-nope")
    refusal = '{"error":{"message":"This model is only supported in v1/responses and not in v1/chat/completions."}}'
    assert not responses.learn_from_refusal("https://openrouter.ai/api/v1/chat/completions", "gpt-x", 404, refusal)
    assert responses.learn_from_refusal(url, "gpt-6-pro-preview", 404, refusal)
    assert responses.uses_responses_api(url, "gpt-6-pro-preview")


# ── picture shapes ──────────────────────────────────────────────────────────

def test_responses_payload_carries_the_picture_tools_and_tool_turns():
    msgs = PICTURE_TURN + [
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "call_1", "type": "function",
             "function": {"name": "web_search", "arguments": '{"q":"x"}'}}]},
        {"role": "tool", "tool_call_id": "call_1", "content": "result"},
    ]
    tools = [{"type": "function", "function": {
        "name": "web_search", "description": "Search", "parameters": {"type": "object"}}}]
    body = responses.build_payload("gpt-5-pro", msgs, 2048, stream=True, tools=tools)
    assert body["instructions"] == "You are Pantheon."
    assert body["max_output_tokens"] == 2048 and body["stream"] is True
    assert "temperature" not in body and "messages" not in body
    user = body["input"][0]
    assert user["role"] == "user"
    assert user["content"] == [
        {"type": "input_text", "text": "Decipher and analyze this image."},
        {"type": "input_image", "image_url": PNG},
    ]
    assert body["input"][1] == {"type": "function_call", "call_id": "call_1",
                                "name": "web_search", "arguments": '{"q":"x"}'}
    assert body["input"][2] == {"type": "function_call_output", "call_id": "call_1", "output": "result"}
    assert body["tools"] == [{"type": "function", "name": "web_search",
                              "description": "Search", "parameters": {"type": "object"}}]


def test_reasoning_effort_moves_into_the_responses_shape():
    assert responses.finish_payload({"reasoning_effort": "low"}, "o3-pro") == {"reasoning": {"effort": "low"}}
    # gpt-5-pro takes only `high`
    assert responses.finish_payload({"reasoning_effort": "low"}, "gpt-5-pro") == {}
    assert responses.finish_payload({"reasoning_effort": "high"}, "gpt-5-pro") == {"reasoning": {"effort": "high"}}


def test_anthropic_gets_a_base64_image_block():
    body = llm_core._build_anthropic_payload("claude-sonnet-4-6", PICTURE_TURN, 0.7, 1024)
    parts = body["messages"][0]["content"]
    assert parts[0] == {"type": "text", "text": "Decipher and analyze this image."}
    assert parts[1]["type"] == "image"
    assert parts[1]["source"]["type"] == "base64"
    assert parts[1]["source"]["media_type"] == "image/png"
    assert PNG.endswith(parts[1]["source"]["data"])


# ── the transport, stopped at the socket ────────────────────────────────────

RESPONSES_STREAM = [
    'event: response.created',
    'data: {"type":"response.created","response":{"model":"gpt-5-pro-2025-10-06"}}',
    'data: {"type":"response.output_text.delta","delta":"A red "}',
    'data: {"type":"response.output_text.delta","delta":"square."}',
    'data: {"type":"response.completed","response":{"model":"gpt-5-pro-2025-10-06",'
    '"usage":{"input_tokens":120,"output_tokens":4}}}',
]
CHAT_STREAM = [
    'data: {"choices":[{"index":0,"delta":{"content":"A red square."}}]}',
    "data: [DONE]",
]
REFUSAL = '{"error":{"message":"This model is only supported in v1/responses and not in v1/chat/completions.","type":"invalid_request_error"}}'


class _Resp:
    def __init__(self, status, lines=(), body=""):
        self.status_code = status
        self._lines = list(lines)
        self._body = body
        self.text = body
        self.headers = {}
        self.is_success = 200 <= status < 300

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def aread(self):
        return self._body.encode()

    def json(self):
        return json.loads(self._body)


class _Stream:
    def __init__(self, resp):
        self.resp = resp

    async def __aenter__(self):
        return self.resp

    async def __aexit__(self, *a):
        return False


class _Provider:
    """Answers like OpenAI: chat completions refuse Responses-only models."""

    def __init__(self, responses_only=()):
        self.calls = []
        self.responses_only = set(responses_only)

    def answer(self, url, body):
        self.calls.append((url, body))
        if url.endswith("/chat/completions") and body.get("model") in self.responses_only:
            return _Resp(404, body=REFUSAL)
        if url.endswith("/responses"):
            if body.get("stream"):
                return _Resp(200, RESPONSES_STREAM)
            return _Resp(200, body=json.dumps({"model": body["model"], "output": [
                {"type": "message", "content": [{"type": "output_text", "text": "A red square."}]}]}))
        if body.get("stream"):
            return _Resp(200, CHAT_STREAM)
        return _Resp(200, body=json.dumps({"model": body["model"], "choices": [
            {"message": {"role": "assistant", "content": "A red square."}}]}))

    def stream(self, method, url, **kwargs):
        return _Stream(self.answer(url, kwargs.get("json") or {}))

    async def post(self, url, **kwargs):
        return self.answer(url, kwargs.get("json") or {})


@pytest.fixture
def provider(monkeypatch):
    p = _Provider(responses_only={"gpt-6-preview"})
    monkeypatch.setattr(llm_core, "_client_for", lambda _u: p)
    monkeypatch.setattr(llm_core, "_is_host_dead", lambda _u: False)
    monkeypatch.setattr(llm_core, "get_context_length", lambda *a, **k: 128000)
    monkeypatch.setattr(llm_core, "_get_cached_response", lambda *a, **k: None)
    monkeypatch.setattr(llm_core, "httpx_post_kimi_aware",
                        lambda url, headers, **kw: p.answer(url, kw.get("json") or {}))
    return p


def _stream(url, model):
    async def run():
        out = []
        async for chunk in llm_core.stream_llm(url, model, PICTURE_TURN,
                                               headers={"Authorization": "Bearer k"}):
            out.append(chunk)
        return out
    return asyncio.run(run())


def _text(chunks):
    text = ""
    for chunk in chunks:
        for line in chunk.splitlines():
            if line.startswith("data:") and line[5:].strip() not in ("", "[DONE]"):
                data = json.loads(line[5:])
                if isinstance(data.get("delta"), str) and not data.get("thinking"):
                    text += data["delta"]
    return text


def test_a_picture_to_gpt5_pro_streams_from_responses(provider):
    chunks = _stream("https://api.openai.com/v1/chat/completions", "gpt-5-pro")
    url, body = provider.calls[0]
    assert len(provider.calls) == 1
    assert url == "https://api.openai.com/v1/responses"
    assert body["input"][0]["content"][1] == {"type": "input_image", "image_url": PNG}
    assert _text(chunks) == "A red square."
    assert any('"type": "usage"' in c for c in chunks)
    assert not any("event: error" in c for c in chunks)


def test_a_picture_to_gpt5_stays_on_chat_completions(provider):
    chunks = _stream("https://api.openai.com/v1/chat/completions", "gpt-5")
    url, body = provider.calls[0]
    assert url == "https://api.openai.com/v1/chat/completions"
    assert body["messages"][-1]["content"][1] == {"type": "image_url", "image_url": {"url": PNG}}
    assert _text(chunks) == "A red square."


def test_a_new_responses_only_model_is_sent_again_after_openais_404(provider):
    chunks = _stream("https://api.openai.com/v1/chat/completions", "gpt-6-preview")
    assert [u for u, _ in provider.calls] == [
        "https://api.openai.com/v1/chat/completions",
        "https://api.openai.com/v1/responses",
    ]
    assert _text(chunks) == "A red square."
    assert not any("event: error" in c for c in chunks)
    # and the next turn goes straight there
    _stream("https://api.openai.com/v1/chat/completions", "gpt-6-preview")
    assert provider.calls[-1][0] == "https://api.openai.com/v1/responses"


@pytest.mark.parametrize("url", [
    "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
    "https://api.x.ai/v1/chat/completions",
    "https://api.mistral.ai/v1/chat/completions",
    "https://openrouter.ai/api/v1/chat/completions",
])
def test_openai_compatible_providers_get_the_picture_as_image_url(provider, url):
    chunks = _stream(url, "vision-model")
    sent_url, body = provider.calls[0]
    assert sent_url == url
    parts = body["messages"][-1]["content"]
    assert {"type": "image_url", "image_url": {"url": PNG}} in parts
    assert _text(chunks) == "A red square."


def test_a_non_streamed_call_to_a_pro_model_reads_responses(provider):
    text = asyncio.run(llm_core.llm_call_async(
        "https://api.openai.com/v1/chat/completions", "o3-pro", PICTURE_TURN,
        headers={"Authorization": "Bearer k"}))
    assert text == "A red square."
    assert provider.calls[0][0] == "https://api.openai.com/v1/responses"


def test_the_vision_describer_reaches_a_pro_model(provider):
    # `analyze_image_with_vl` uses the synchronous `llm_call`.
    text = llm_core.llm_call("https://api.openai.com/v1/chat/completions", "gpt-5-pro",
                             PICTURE_TURN, headers={"Authorization": "Bearer k"})
    assert text == "A red square."
    url, body = provider.calls[0]
    assert url == "https://api.openai.com/v1/responses"
    assert body["input"][0]["content"][1]["type"] == "input_image"


def test_the_sync_call_learns_from_the_404_too(provider):
    text = llm_core.llm_call("https://api.openai.com/v1/chat/completions", "gpt-6-preview",
                             PICTURE_TURN, headers={"Authorization": "Bearer k"})
    assert text == "A red square."
    assert [u for u, _ in provider.calls][-1] == "https://api.openai.com/v1/responses"


def test_a_404_names_the_address_and_model():
    msg = llm_core._format_upstream_error(
        404, '{"error":{"message":"The model `gpt-x` does not exist"}}',
        "https://api.openai.com/v1/chat/completions", model="gpt-x")
    assert msg.startswith("OpenAI returned 404 at /v1/chat/completions for model 'gpt-x'")
    assert "does not exist" in msg


# ── streamed tool calls over Responses ──────────────────────────────────────

def test_responses_function_calls_come_back_as_pantheon_tool_calls():
    t = responses.StreamTranslator()
    out = []
    for evt in [
        {"type": "response.output_item.added", "output_index": 1,
         "item": {"type": "function_call", "call_id": "call_9", "name": "read_file", "arguments": ""}},
        {"type": "response.function_call_arguments.delta", "output_index": 1, "delta": '{"path":'},
        {"type": "response.function_call_arguments.delta", "output_index": 1, "delta": '"a.txt"}'},
        {"type": "response.output_item.done", "output_index": 1,
         "item": {"type": "function_call", "call_id": "call_9", "name": "read_file",
                  "arguments": '{"path":"a.txt"}'}},
        {"type": "response.completed", "response": {"usage": {"input_tokens": 1, "output_tokens": 2}}},
    ]:
        out += t.feed(evt)
    assert t.done
    calls = [json.loads(e[6:]) for e in out if '"tool_calls"' in e][0]["calls"]
    assert calls == [{"id": "call_9", "name": "read_file", "arguments": '{"path":"a.txt"}'}]
    assert out[-1] == "data: [DONE]\n\n"
