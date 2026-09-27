# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P2-13` — a temperature the person chose reaches their local model.

Two clamps hold temperature at 0.2 on local inference: MiniMax on a local
endpoint (`llm_core._apply_local_generation_stability`) and the
`pantheon-qwen3` finetune (`agent_loop._pan_qwen_temperature_cap`). Both are
real — those families loop above 0.2 — and both overwrote the value whatever it
was, because a payload dict cannot say whether 0.9 was chosen or defaulted. So a
person who picked a warmer character and pointed it at their own box got 0.2
and nothing said so.

`D-2026-08-26-06` decided the remedy: *"thread an `explicit_params` set from
the payload builder; the clamp becomes a setdefault for everything else. Keep
the Anthropic ceiling."* The row adds the property that must survive: *"the two
qwen tests exist to prove a mixed fallback chain leaks temperature in neither
direction."* The four assertions it names —
`tests/test_llm_core_temperature_reasoning.py` and
`tests/test_pr6020_rebase_regressions.py` — still pass untouched, because they
drive the path where nobody chose, and that path keeps the clamp byte for byte.
This file is the other half.

**What the clamp protected, and why nothing it blocked runs unsafely now:** it
is a quality guard, not a security control — the harm it prevents is a model
looping on the person's own GPU. It still applies to everything nobody chose:
every background job, every internal call, and chat with no preset. What it no
longer does is overrule a choice. The cloud ceilings that are provider rules —
Anthropic refuses above 1.0, reasoning models refuse any value — do not read
the signal and are asserted here unchanged.

`Law 20`: every test drives the code — the real preset reader, the real payload
builders under a faked socket, the real agent loop and chat routes.
"""
import asyncio
from types import SimpleNamespace

import pytest

import routes.chat_helpers as chat_helpers
import routes.chat_routes as chat_routes
import src.foreground_model_routing as foreground_model_routing
import src.llm_core as llm_core
from routes.chat_helpers import extract_preset
from src.chat_handler import ChatHandler
from src.model_context import is_local_endpoint
from src.preset_manager import PresetManager
from src.request_models import ChatRequest
from test_foreground_model_routing import (  # noqa: E402
    _RouteRequest,
    _chat_endpoint,
    _chat_stream_endpoint,
)
from test_pr6020_rebase_regressions import (  # noqa: E402
    PAN_QWEN,
    _install_route_probe,
    _run_probe,
)

MINIMAX = "example-org/MiniMax-M2.7-BF16-mlx-4Bit"
LOCAL = "http://192.168.1.22:8091/v1/chat/completions"
CHOSEN = frozenset({"temperature"})


def test_the_endpoint_under_test_is_local():
    """The premise every MiniMax test below rests on, measured rather than
    monkeypatched: a LAN address is a local endpoint."""
    assert is_local_endpoint(LOCAL)


# ── where the choice comes from ──────────────────────────────────────────────

@pytest.fixture
def handler(tmp_path):
    return ChatHandler(None, None, None, None, PresetManager(str(tmp_path)), None)


def _set_custom(handler, **fields):
    handler.preset_manager.update_custom(
        temperature=fields.get("temperature", 1.0),
        max_tokens=fields.get("max_tokens", 0),
        system_prompt=fields.get("system_prompt", "You are Nietzsche."),
        name=fields.get("name", ""),
        enabled=fields.get("enabled", True),
    )


def test_no_preset_is_no_choice(handler):
    info = extract_preset(handler, None)
    assert info.temperature == 1.0
    assert info.explicit_params == frozenset()


@pytest.mark.parametrize("temperature", [1.2, 0.9, 0.4, 0.0])
def test_a_temperature_the_person_dialled_in_is_a_choice(handler, temperature):
    _set_custom(handler, temperature=temperature)
    info = extract_preset(handler, "custom")
    assert info.temperature == temperature
    assert info.explicit_params == CHOSEN


def test_a_shipped_preset_that_names_a_temperature_is_a_choice(handler):
    """Picking Brainstorm or Reason is picking their temperature."""
    assert extract_preset(handler, "brainstorm").explicit_params == CHOSEN
    assert extract_preset(handler, "reason").explicit_params == CHOSEN


def test_a_disabled_preset_is_no_choice(handler):
    _set_custom(handler, temperature=0.9, enabled=False)
    info = extract_preset(handler, "custom")
    assert info.temperature == 1.0
    assert info.explicit_params == frozenset()


def test_the_default_value_is_indistinguishable_from_no_choice(handler):
    """The stated cost, pinned so nobody mistakes it for a bug: 1.0 is what no
    choice resolves to, so a slider left at 1.0 asks for nothing."""
    _set_custom(handler, temperature=1.0)
    assert extract_preset(handler, "custom").explicit_params == frozenset()


def test_max_tokens_is_never_a_choice(handler):
    """`D-2026-09-08-02`: on local inference `max_tokens` is the machine's."""
    _set_custom(handler, temperature=0.9, max_tokens=8000)
    assert "max_tokens" not in extract_preset(handler, "custom").explicit_params
    assert chat_helpers.explicit_sampling_params("not a number") == frozenset()


# ── the three payload builders, on the wire ─────────────────────────────────

class _Resp:
    is_success = True
    status_code = 200
    text = ""

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


_OPENAI_OK = {"choices": [{"message": {"content": "OK"}}]}
_ANTHROPIC_OK = {"content": [{"type": "text", "text": "OK"}], "stop_reason": "end_turn"}


@pytest.fixture
def wire(monkeypatch):
    """Every payload the three builders post, in order. The socket is the only
    thing faked."""
    posted = []
    llm_core._response_cache.clear()

    def sync_post(url, headers=None, json=None, timeout=None):
        posted.append(json)
        return _Resp(_ANTHROPIC_OK if "anthropic" in url else _OPENAI_OK)

    async def async_post(client, url, headers, json=None, **kwargs):
        posted.append(json)
        return _Resp(_OPENAI_OK)

    class _Stream:
        def __init__(self, payload):
            self.payload = payload

        async def __aenter__(self):
            posted.append(self.payload)
            return SimpleNamespace(status_code=200, aiter_lines=self._lines,
                                   aread=self._aread)

        async def __aexit__(self, *exc):
            return False

        async def _lines(self):
            yield 'data: {"choices": [{"delta": {"content": "hi"}}]}'
            yield "data: [DONE]"

        async def _aread(self):
            return b""

    monkeypatch.setattr(llm_core.httpx, "post", sync_post)
    monkeypatch.setattr(llm_core, "httpx_post_kimi_aware_async", async_post)
    monkeypatch.setattr(llm_core, "_get_http_client", lambda: SimpleNamespace(
        stream=lambda method, url, json=None, **kw: _Stream(json)))
    monkeypatch.setattr(llm_core, "_is_host_dead", lambda url: False)
    monkeypatch.setattr(llm_core, "note_model_activity", lambda *a, **k: None)
    yield posted
    llm_core._response_cache.clear()


_MSG = [{"role": "user", "content": "Say OK"}]


def _sync(explicit, temperature=0.9, url=LOCAL, model=MINIMAX, max_tokens=5):
    return llm_core.llm_call(url, model, _MSG, temperature=temperature,
                             max_tokens=max_tokens, explicit_params=explicit)


def _nonstream_route(explicit, temperature=0.9):
    """`/api/chat`'s door: the route-fallback wrapper forwards its kwargs."""
    return asyncio.run(llm_core.llm_call_async_with_route_fallback(
        [(LOCAL, MINIMAX, {})], _MSG, fallback_statuses=set(),
        temperature=temperature, max_tokens=5, explicit_params=explicit))


def _stream_route(explicit, temperature=0.9):
    """Chat mode's door: `stream_llm_with_fallback` → `stream_llm`."""
    async def drain():
        return [c async for c in llm_core.stream_llm_with_fallback(
            [(LOCAL, MINIMAX, {})], _MSG, temperature=temperature, max_tokens=5,
            explicit_params=explicit)]
    return asyncio.run(drain())


@pytest.mark.parametrize("door", [_sync, _nonstream_route, _stream_route],
                         ids=["llm_call", "llm_call_async", "stream_llm"])
def test_a_chosen_temperature_reaches_a_local_minimax(wire, door):
    door(CHOSEN)
    assert wire[-1]["temperature"] == 0.9


@pytest.mark.parametrize("door", [_sync, _nonstream_route, _stream_route],
                         ids=["llm_call", "llm_call_async", "stream_llm"])
def test_without_a_choice_the_clamp_is_what_it_was(wire, door):
    """The other half of the decision, and the row's surviving property:
    everything nobody chose gets the profile exactly as before."""
    door(frozenset())
    sent = wire[-1]
    assert sent["temperature"] == 0.2
    before = {"model": MINIMAX, "temperature": 0.9, "max_tokens": 5}
    llm_core._apply_local_generation_stability(before, LOCAL, MINIMAX)
    for key, value in before.items():
        assert sent[key] == value, key


def test_the_rest_of_the_profile_still_fills_in_under_a_choice(wire):
    """Only the parameter the person chose is left alone. `max_tokens` is
    still filled where the payload has none — the machine's number, never the
    preset's (`D-2026-09-08-02`)."""
    _sync(CHOSEN, max_tokens=0)
    sent = wire[-1]
    assert sent["temperature"] == 0.9
    assert (sent["top_p"], sent["top_k"], sent["repetition_penalty"]) == (0.9, 20, 1.12)
    assert sent["stop"] == ["<|im_end|>", "<|endoftext|>", "</s>"]
    assert sent["max_tokens"] == 2048


def test_a_choice_and_a_default_do_not_share_a_cached_answer(wire):
    """Same messages, same number, two different payloads on the wire — so
    two cache entries. A second call with no choice still hits the cache."""
    _sync(frozenset())
    _sync(CHOSEN)
    _sync(frozenset())
    assert [p["temperature"] for p in wire] == [0.2, 0.9]


# ── provider rules are not defaults, and do not read the signal ─────────────

def test_the_anthropic_ceiling_holds_for_a_choice(wire):
    _sync(CHOSEN, temperature=1.2, url="https://api.anthropic.com/v1/messages",
          model="claude-3-5-sonnet-20241022")
    assert wire[-1]["temperature"] == 1.0


def test_a_reasoning_model_still_refuses_any_temperature(wire):
    _sync(CHOSEN, temperature=0.4, url="https://api.openai.com/v1/chat/completions",
          model="o3-mini")
    assert "temperature" not in wire[-1]


def test_a_cloud_model_gets_a_choice_or_a_default_unchanged(wire):
    for explicit in (CHOSEN, frozenset()):
        _sync(explicit, temperature=1.2, url="https://api.openai.com/v1/chat/completions",
              model="gpt-4o")
        assert wire[-1]["temperature"] == 1.2


# ── the qwen finetune, through the real agent loop ──────────────────────────

def test_a_chosen_temperature_reaches_a_qwen_primary(monkeypatch):
    _, stream_calls = _install_route_probe(monkeypatch)
    _run_probe([{"role": "user", "content": "Add buy milk to my notes."}],
               relevant_tools={"manage_notes"}, temperature=1.2,
               explicit_params=CHOSEN)
    assert stream_calls[0]["temperature"] == 1.2
    # Forwarded, so a MiniMax candidate under the loop honours it too.
    assert stream_calls[0]["explicit_params"] == CHOSEN


@pytest.mark.parametrize("primary, fallback", [
    ("gpt-4o", PAN_QWEN), (PAN_QWEN, "gpt-4o"), (PAN_QWEN, PAN_QWEN),
])
def test_a_chosen_temperature_reaches_every_candidate(monkeypatch, primary, fallback):
    """It is the person's number, not the primary's, so a fallback getting it
    is not a leak."""
    _, stream_calls = _install_route_probe(monkeypatch)
    _run_probe([{"role": "user", "content": "Explain the CAP theorem."}],
               model=primary, relevant_tools={"bash"}, temperature=1.2,
               fallbacks=[("https://fallback.example/v1", fallback, {})],
               explicit_params=CHOSEN)
    assert stream_calls[0]["temperature"] == 1.2
    factory = stream_calls[0]["candidate_request_factory"]
    request = asyncio.run(factory(1, "https://fallback.example/v1", fallback, {}))
    assert request["kwargs"]["temperature"] == 1.2


@pytest.mark.parametrize("primary, fallback, want_primary, want_fallback", [
    ("gpt-4o", PAN_QWEN, 1.2, 0.2),
    (PAN_QWEN, "gpt-4o", 0.2, 1.2),
])
def test_without_a_choice_a_mixed_chain_leaks_in_neither_direction(
        monkeypatch, primary, fallback, want_primary, want_fallback):
    """The property the row says must survive, stated here as well as in the
    two tests it names."""
    _, stream_calls = _install_route_probe(monkeypatch)
    _run_probe([{"role": "user", "content": "Explain the CAP theorem."}],
               model=primary, relevant_tools={"bash"}, temperature=1.2,
               fallbacks=[("https://fallback.example/v1", fallback, {})])
    assert stream_calls[0]["temperature"] == want_primary
    factory = stream_calls[0]["candidate_request_factory"]
    request = asyncio.run(factory(1, "https://fallback.example/v1", fallback, {}))
    assert request["kwargs"]["temperature"] == want_fallback


# ── the chat routes carry the preset's choice to all three doors ────────────

_CHOSEN_PRESET = SimpleNamespace(temperature=0.9, max_tokens=128, character_name=None,
                                 explicit_params=CHOSEN)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["chat", "agent"])
async def test_the_stream_route_threads_the_preset_choice(monkeypatch, mode):
    captured = {}
    endpoint = _chat_stream_endpoint(monkeypatch, mode, captured,
                                     context_overrides={"preset": _CHOSEN_PRESET})
    seen = {}

    async def capture_chat(candidates, messages, **kwargs):
        seen.update(kwargs)
        yield 'data: {"delta": "done"}\n\n'
        yield "data: [DONE]\n\n"

    async def capture_agent(url, model, messages, **kwargs):
        seen.update(kwargs)
        yield 'data: {"delta": "done"}\n\n'
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(chat_routes, "stream_llm_with_fallback", capture_chat)
    monkeypatch.setattr(chat_routes, "stream_agent_loop", capture_agent)
    response = await endpoint(_RouteRequest(mode))
    async for _ in response.body_iterator:
        pass
    assert seen["temperature"] == 0.9
    assert seen["explicit_params"] == CHOSEN


@pytest.mark.asyncio
async def test_the_nonstream_route_threads_the_preset_choice(monkeypatch):
    seen = {}

    async def capture_call(url, model, messages, **kwargs):
        seen.update(kwargs)
        return "answer"

    monkeypatch.setattr(llm_core, "llm_call_async", capture_call)
    monkeypatch.setattr(foreground_model_routing, "_load_policy_preferences",
                        lambda owner=None: {})
    endpoint, _saved = _chat_endpoint(monkeypatch)
    context = SimpleNamespace(
        user="alice", messages=[{"role": "user", "content": "hello"}],
        route_messages=[{"role": "user", "content": "hello"}], context_length=100,
        uprefs={}, preset=_CHOSEN_PRESET)

    async def fake_build_context(*args, **kwargs):
        return context

    monkeypatch.setattr(chat_routes, "build_chat_context", fake_build_context)
    await endpoint(_RouteRequest("chat"), ChatRequest(message="hello", session="session-1"))
    assert seen["temperature"] == 0.9
    assert seen["explicit_params"] == CHOSEN
