# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B935` — the `pantheon-qwen3` default temperature cap guards all three doors.

The finetune destabilises above 0.2, and until this row only the agent loop
knew: chat-mode streaming and `/api/chat` handed a qwen3 model the preset's
temperature — 1.0 with no preset — as sent. The owner's call: *the default cap
applies in every mode, and a temperature the person chose is always honoured*,
which is the rule `P2-13` gave the agent path.

So there is still one rule, `agent_loop.pan_qwen_route_temperature`, and the
chat routes now call it: for the selected model's base temperature, and per
candidate inside `_chat_candidate_request_factory`, so a mixed fallback chain
leaks the cap in neither direction on these doors either.

`Law 20`: each door is driven through the real chat route. The two chat doors
go all the way to the payload builders with only the socket faked, so what is
asserted is the temperature on the wire; the agent door runs the real agent loop
under `test_pr6020_rebase_regressions`'s probe, which records what the loop
hands the model layer.
"""
import asyncio
import json
from types import SimpleNamespace

import pytest

import routes.chat_routes as chat_routes
import src.agent_loop as agent_loop
import src.foreground_model_routing as foreground_model_routing
import src.llm_core as llm_core
from src.request_models import ChatRequest
from test_foreground_model_routing import (  # noqa: E402
    _RouteRequest,
    _chat_endpoint,
    _chat_stream_endpoint,
)
from test_pr6020_rebase_regressions import PAN_QWEN, _install_route_probe  # noqa: E402

NO_CHOICE = SimpleNamespace(temperature=1.0, max_tokens=128, character_name=None,
                            explicit_params=frozenset())
CHOSEN = SimpleNamespace(temperature=0.9, max_tokens=128, character_name=None,
                         explicit_params=frozenset({"temperature"}))


# ── the socket, and nothing above it, is faked ───────────────────────────────

class _Resp:
    is_success = True
    status_code = 200
    text = ""

    def json(self):
        return {"choices": [{"message": {"content": "answer"}}]}


@pytest.fixture
def wire(monkeypatch):
    """Every chat-completions payload posted, as `(url, payload)`. A URL listed
    in `wire.down` answers 503 before any content, so a fallback chain moves on."""
    sent, down = [], set()

    async def async_post(client, url, headers, json=None, **kwargs):
        sent.append((url, json))
        if any(d in url for d in down):
            return SimpleNamespace(is_success=False, status_code=503, text="down")
        return _Resp()

    class _Stream:
        def __init__(self, url, payload):
            self.url, self.payload = url, payload

        async def __aenter__(self):
            sent.append((self.url, self.payload))
            status = 503 if any(d in self.url for d in down) else 200
            return SimpleNamespace(status_code=status, aiter_lines=self._lines,
                                   aread=self._aread)

        async def __aexit__(self, *exc):
            return False

        async def _lines(self):
            yield 'data: {"choices": [{"delta": {"content": "hi"}}]}'
            yield "data: [DONE]"

        async def _aread(self):
            return b"down"

    monkeypatch.setattr(llm_core, "httpx_post_kimi_aware_async", async_post)
    monkeypatch.setattr(llm_core, "_get_http_client", lambda: SimpleNamespace(
        stream=lambda method, url, json=None, **kw: _Stream(url, json)))
    monkeypatch.setattr(llm_core, "_is_host_dead", lambda url: False)
    monkeypatch.setattr(llm_core, "note_model_activity", lambda *a, **k: None)
    llm_core._response_cache.clear()

    async def no_compaction(session, url, model, messages, headers=None, owner=None, **kwargs):
        return list(messages), 4096, False

    monkeypatch.setattr(chat_routes, "maybe_compact", no_compaction)
    monkeypatch.setattr(chat_routes, "trim_for_context", lambda messages, budget: list(messages))
    wire_state = SimpleNamespace(sent=sent, down=down)
    yield wire_state
    llm_core._response_cache.clear()


def _fallback_to(monkeypatch, model):
    """Turn the foreground fallback policy on, with one backup candidate."""
    monkeypatch.setattr(foreground_model_routing, "_load_policy_preferences",
                        lambda owner=None: {
                            "foreground_fallback_enabled": True,
                            "foreground_model_fallbacks": [{"endpoint_id": "backup",
                                                            "model": model}],
                        })
    monkeypatch.setattr(foreground_model_routing, "resolve_fallback_entries",
                        lambda entries, owner=None, require_exact_model=False: [
                            ("https://backup.example/v1", model, {})])


# ── the chat-mode door ───────────────────────────────────────────────────────

async def _chat_mode(monkeypatch, model, preset, backup=None):
    endpoint = _chat_stream_endpoint(monkeypatch, "chat", {}, model=model,
                                     context_overrides={"preset": preset})
    if backup:
        # After the helper, which installs a strict policy of its own.
        _fallback_to(monkeypatch, backup)
    monkeypatch.setattr(chat_routes, "stream_llm_with_fallback",
                        llm_core.stream_llm_with_fallback)
    response = await endpoint(_RouteRequest("chat"))
    async for _ in response.body_iterator:
        pass


@pytest.mark.asyncio
@pytest.mark.parametrize("model, preset, sent", [
    (PAN_QWEN, NO_CHOICE, 0.2), (PAN_QWEN, CHOSEN, 0.9),
    ("gpt-4o", NO_CHOICE, 1.0), ("gpt-4o", CHOSEN, 0.9),
], ids=["qwen-default", "qwen-chosen", "other-default", "other-chosen"])
async def test_chat_mode_sends_the_capped_default_and_the_chosen_value(
        wire, monkeypatch, model, preset, sent):
    await _chat_mode(monkeypatch, model, preset)
    (url, payload), = wire.sent
    assert payload["model"] == model
    assert payload["temperature"] == sent


@pytest.mark.asyncio
@pytest.mark.parametrize("primary, backup, want", [
    ("gpt-4o", PAN_QWEN, (1.0, 0.2)), (PAN_QWEN, "gpt-4o", (0.2, 1.0)),
], ids=["other-then-qwen", "qwen-then-other"])
async def test_chat_mode_fallback_chain_leaks_the_cap_in_neither_direction(
        wire, monkeypatch, primary, backup, want):
    wire.down.add("selected.example")
    await _chat_mode(monkeypatch, primary, NO_CHOICE, backup=backup)
    assert [(p["model"], p["temperature"]) for _u, p in wire.sent] == \
        [(primary, want[0]), (backup, want[1])]


@pytest.mark.asyncio
async def test_chat_mode_fallback_chain_carries_a_choice_to_every_candidate(wire, monkeypatch):
    wire.down.add("selected.example")
    await _chat_mode(monkeypatch, "gpt-4o", CHOSEN, backup=PAN_QWEN)
    assert [(p["model"], p["temperature"]) for _u, p in wire.sent] == \
        [("gpt-4o", 0.9), (PAN_QWEN, 0.9)]


# ── the `/api/chat` door ─────────────────────────────────────────────────────

async def _nonstream(monkeypatch, model, preset):
    endpoint, _saved = _chat_endpoint(monkeypatch, model=model)
    context = SimpleNamespace(
        user="alice", messages=[{"role": "user", "content": "hello"}],
        route_messages=[{"role": "user", "content": "hello"}], context_length=4096,
        uprefs={}, preset=preset)

    async def build(*args, **kwargs):
        return context

    monkeypatch.setattr(chat_routes, "build_chat_context", build)
    await endpoint(_RouteRequest("chat"), ChatRequest(message="hello", session="session-1"))


@pytest.mark.asyncio
@pytest.mark.parametrize("model, preset, sent", [
    (PAN_QWEN, NO_CHOICE, 0.2), (PAN_QWEN, CHOSEN, 0.9),
    ("gpt-4o", NO_CHOICE, 1.0), ("gpt-4o", CHOSEN, 0.9),
], ids=["qwen-default", "qwen-chosen", "other-default", "other-chosen"])
async def test_api_chat_sends_the_capped_default_and_the_chosen_value(
        wire, monkeypatch, model, preset, sent):
    monkeypatch.setattr(foreground_model_routing, "_load_policy_preferences",
                        lambda owner=None: {})
    await _nonstream(monkeypatch, model, preset)
    (url, payload), = wire.sent
    assert payload["model"] == model
    assert payload["temperature"] == sent


@pytest.mark.asyncio
@pytest.mark.parametrize("primary, backup, want", [
    ("gpt-4o", PAN_QWEN, (1.0, 0.2)), (PAN_QWEN, "gpt-4o", (0.2, 1.0)),
], ids=["other-then-qwen", "qwen-then-other"])
async def test_api_chat_fallback_chain_leaks_the_cap_in_neither_direction(
        wire, monkeypatch, primary, backup, want):
    _fallback_to(monkeypatch, backup)
    wire.down.add("selected.example")
    await _nonstream(monkeypatch, primary, NO_CHOICE)
    # The selected route is retried before the chain moves on; every attempt
    # carries the same payload, so compare the distinct ones in order.
    distinct = []
    for _u, p in wire.sent:
        if (p["model"], p["temperature"]) not in distinct:
            distinct.append((p["model"], p["temperature"]))
    assert distinct == [(primary, want[0]), (backup, want[1])]


# ── the agent door, through the route and the real loop ──────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("model, preset, sent", [
    (PAN_QWEN, NO_CHOICE, 0.2), (PAN_QWEN, CHOSEN, 0.9),
    ("gpt-4o", NO_CHOICE, 1.0), ("gpt-4o", CHOSEN, 0.9),
], ids=["qwen-default", "qwen-chosen", "other-default", "other-chosen"])
async def test_the_agent_door_sends_the_capped_default_and_the_chosen_value(
        monkeypatch, model, preset, sent):
    _, stream_calls = _install_route_probe(monkeypatch)
    endpoint = _chat_stream_endpoint(monkeypatch, "agent", {}, model=model,
                                     context_overrides={"preset": preset})
    monkeypatch.setattr(chat_routes, "stream_agent_loop", agent_loop.stream_agent_loop)
    response = await endpoint(_RouteRequest("agent"))
    async for _ in response.body_iterator:
        pass
    assert stream_calls, "the agent loop never reached the model layer"
    assert stream_calls[0]["temperature"] == sent


# ── the factory itself keeps its old shape when asked for nothing ────────────

def test_the_factory_asks_for_no_temperature_unless_given_one(monkeypatch):
    async def no_compaction(session, url, model, messages, headers=None, owner=None, **kwargs):
        return list(messages), 4096, False

    monkeypatch.setattr(chat_routes, "maybe_compact", no_compaction)
    monkeypatch.setattr(chat_routes, "trim_for_context", lambda messages, budget: list(messages))
    factory, _state = chat_routes._chat_candidate_request_factory(
        [{"role": "user", "content": "hi"}], 4096, session=SimpleNamespace())
    request = asyncio.run(factory(0, "https://x.example/v1", PAN_QWEN, {}))
    assert set(request) == {"messages"}
