# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reasoning effort — one ladder (Auto, Low … Max), each model's own switch.

Panick, 2026-11-01: *"We need reasoning effort (where supported with thinking
models) - with Low/Med/High/Extra/Max."* The composer shows the selector only
where the selected model takes a level (`effort_support`), and a level reaches
the model through its own field, or through words in the system prompt where
its field stops short (`src/reasoning_effort.py`).

The payload half runs the real `stream_llm` builders and stops at the socket:
the client is replaced by one that records the body and answers one chunk.
"""
from __future__ import annotations

import asyncio
import json

import pytest

import src.llm_core as llm_core
from src import reasoning_effort as effort

LMSTUDIO = "http://localhost:1234/v1"
OLLAMA = "http://localhost:11434"
ANTHROPIC = "https://api.anthropic.com/v1"
OPENAI = "https://api.openai.com/v1"


# ── which models show the selector ─────────────────────────────────────────

@pytest.mark.parametrize("url,model,mech", [
    (LMSTUDIO, "openai/gpt-oss-20b", "openai_reasoning_effort"),
    (OLLAMA, "gpt-oss:20b", "ollama_think_level"),
    (LMSTUDIO, "qwen/qwen3-30b-a3b", "qwen3_switch"),
    (LMSTUDIO, "deepseek-r1-distill-qwen-14b", "instruction"),
    (LMSTUDIO, "google/gemma-3-12b", "instruction"),
    (ANTHROPIC, "claude-opus-5-5", "anthropic"),
    (ANTHROPIC, "claude-sonnet-4-6", "anthropic"),
    (OPENAI, "gpt-5.1", "openai_reasoning_effort"),
    (OPENAI, "o3-mini", "openai_reasoning_effort"),
    ("https://openrouter.ai/api/v1", "openai/o4-mini", "openrouter_reasoning"),
    ("https://api.mistral.ai/v1", "magistral-medium-latest", "mistral_reasoning_effort"),
])
def test_a_thinking_model_shows_the_selector(url, model, mech):
    support = effort.effort_support(url, model)
    assert support["supported"] is True
    assert support["mechanism"] == mech
    assert [lvl["id"] for lvl in support["levels"]] == list(effort.LEVELS)
    assert all(lvl["how"] for lvl in support["levels"])


@pytest.mark.parametrize("url,model", [
    (LMSTUDIO, "qwen/qwen3-coder-30b"),          # Qwen3-Coder never thinks
    (LMSTUDIO, "qwen3-30b-a3b-instruct-2507"),
    (OPENAI, "gpt-4o"),
    (ANTHROPIC, "claude-3-5-sonnet-20241022"),
    (ANTHROPIC, "claude-haiku-4-5"),
    (LMSTUDIO, "llama-3.1-8b-instruct"),
    (LMSTUDIO, ""),
])
def test_a_model_without_thinking_hides_it(url, model):
    assert effort.effort_support(url, model)["supported"] is False


def test_claude_levels_follow_what_each_model_takes():
    def native(model):
        return {l["id"]: l["native"] for l in effort.effort_support(ANTHROPIC, model)["levels"]}
    assert native("claude-opus-5-5") == {"low": "low", "medium": "medium", "high": "high",
                                         "extra": "xhigh", "max": "max"}
    assert native("claude-opus-4-6")["extra"] == "high"
    assert native("claude-opus-4-6")["max"] == "max"
    assert native("claude-opus-4-5")["max"] == "high"


def test_ultrathink_runs_one_turn_at_max():
    assert effort.turn_level("low", "ultrathink: why is this slow?") == "max"
    assert effort.turn_level("", "please UltraThink this") == "max"
    assert effort.turn_level("high", "ultrathinking is not the keyword") == "high"
    assert effort.turn_level("bogus", "hi") == effort.AUTO
    assert effort.turn_level("xhigh", "hi") == "extra"


# ── what each server is sent ──────────────────────────────────────────────

class _Resp:
    status_code = 200

    async def aiter_lines(self):
        yield 'data: {"choices":[{"index":0,"delta":{"content":"Ready."}}]}'
        yield "data: [DONE]"

    async def aread(self):
        return b""

    async def aiter_bytes(self):
        yield b""


class _Stream:
    def __init__(self, sink, kwargs):
        sink.append(kwargs.get("json"))

    async def __aenter__(self):
        return _Resp()

    async def __aexit__(self, *a):
        return False


class _Client:
    def __init__(self, sink):
        self.sink = sink

    def stream(self, method, url, **kwargs):
        return _Stream(self.sink, kwargs)


def _sent(monkeypatch, url, model, level, workload="foreground"):
    sink = []
    monkeypatch.setattr(llm_core, "_client_for", lambda _u: _Client(sink))
    monkeypatch.setattr(llm_core, "_is_host_dead", lambda _u: False)
    monkeypatch.setattr(llm_core, "get_context_length", lambda *a, **k: 32768)

    async def run():
        with effort.turn_scope(level):
            async for _ in llm_core.stream_llm(
                url, model, [{"role": "system", "content": "You are Pantheon."},
                             {"role": "user", "content": "hi"}],
                workload=workload,
            ):
                pass

    asyncio.run(run())
    assert sink, "no request was made"
    return sink[0]


def _system(body):
    msgs = body.get("messages") or []
    return next((m.get("content") for m in msgs if m.get("role") == "system"), "") or ""


def test_gpt_oss_on_lm_studio_gets_its_own_field(monkeypatch):
    body = _sent(monkeypatch, LMSTUDIO, "openai/gpt-oss-20b", "low")
    assert body["reasoning_effort"] == "low"
    assert "Reasoning effort" not in _system(body)


def test_gpt_oss_at_max_is_high_plus_words(monkeypatch):
    body = _sent(monkeypatch, LMSTUDIO, "openai/gpt-oss-20b", "max")
    assert body["reasoning_effort"] == "high"
    assert "Reasoning effort: maximum" in _system(body)


def test_gpt_oss_on_ollama_gets_a_think_level(monkeypatch):
    body = _sent(monkeypatch, OLLAMA, "gpt-oss:20b", "medium")
    assert body["think"] == "medium"


def test_qwen3_is_switched_on_and_told_how_hard(monkeypatch):
    body = _sent(monkeypatch, LMSTUDIO, "qwen/qwen3-30b-a3b", "extra")
    assert body["chat_template_kwargs"] == {"enable_thinking": True}
    assert "/think" in _system(body)
    assert "Reasoning effort: extra high" in _system(body)


def test_claude_gets_output_config_effort(monkeypatch):
    body = _sent(monkeypatch, ANTHROPIC, "claude-opus-5-5", "extra")
    assert body["output_config"] == {"effort": "xhigh"}


def test_auto_sends_nothing(monkeypatch):
    body = _sent(monkeypatch, LMSTUDIO, "openai/gpt-oss-20b", effort.AUTO)
    assert "reasoning_effort" not in body
    assert "Reasoning effort" not in _system(body)


def test_background_calls_keep_the_models_default(monkeypatch):
    body = _sent(monkeypatch, LMSTUDIO, "openai/gpt-oss-20b", "max", workload="background")
    assert "reasoning_effort" not in body
    assert "Reasoning effort" not in _system(body)


def test_a_model_without_a_switch_is_left_alone(monkeypatch):
    body = _sent(monkeypatch, LMSTUDIO, "qwen/qwen3-coder-30b", "max")
    assert "reasoning_effort" not in body
    assert "chat_template_kwargs" not in body
    assert "Reasoning effort" not in _system(body)
