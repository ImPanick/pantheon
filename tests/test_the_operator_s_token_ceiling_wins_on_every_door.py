# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B934` — a local token ceiling the operator typed reaches every door.

`local_inference_max_tokens` (`P3-21`, `D-2026-09-08-02`) is how many tokens this
machine will generate for one local reply. Measured before this row (`w5-local`):
only the agent path read it, so with 32,768 typed a preset's 4096 went out as
4096 in chat mode and `/api/chat` and as 32,768 in Agent mode; and a local
MiniMax with no preset was sent a literal 2048 on all three doors, the agent's
included — the typed number never reached it anywhere.

The owner's call (`D-2026-10-01-04`): *the operator's ceiling wins everywhere.*
A typed ceiling applies on chat mode, Agent mode and `/api/chat` and replaces the
local-MiniMax 2048; an install where nobody typed one sends exactly what it sent.

`Law 20`: each door is driven through the real chat route down to the payload
builders with only the socket faked — the agent door through the real agent
loop (its prompt builder and tool discovery stubbed, as `B935`'s tests do) and
the real fallback wrapper — so every number asserted is the one on the wire.
"""
import json
from types import SimpleNamespace

import pytest

import routes.chat_routes as chat_routes
import src.agent_loop as agent_loop
import src.foreground_model_routing as foreground_model_routing
import src.llm_core as llm_core
import src.runtime_limits as runtime_limits
import src.settings as settings
from src.request_models import ChatRequest
from test_foreground_model_routing import (  # noqa: E402
    _RouteRequest,
    _chat_endpoint,
    _chat_stream_endpoint,
)
from test_pr6020_rebase_regressions import _install_route_probe  # noqa: E402
from test_the_qwen3_cap_guards_every_door import wire  # noqa: E402,F401  (a fixture)

LOCAL = "http://127.0.0.1:8080/v1"
CLOUD = "https://selected.example/v1"
MINIMAX = "MiniMax-M2-4bit-mlx"
OTHER = "qwen2.5-coder-32b"
BRAINSTORM = SimpleNamespace(temperature=1.0, max_tokens=4096, character_name=None,
                             explicit_params=frozenset())
NO_PRESET = SimpleNamespace(temperature=1.0, max_tokens=0, character_name=None,
                            explicit_params=frozenset())
DOORS = ("chat", "api", "agent")
#: `_chat_stream_endpoint` stubs `get_setting` to answer every key's default;
#: this row is about one setting, so its doors read the real store.
REAL_GET_SETTING = settings.get_setting


@pytest.fixture
def ceiling(tmp_path, monkeypatch):
    """The settings store, read the way the product reads it: `setting_is_explicit`
    opens this file. `ceiling(None)` is an install nobody typed into (no file at
    all); `ceiling("materialised")` is one where a save wrote every default."""
    path = tmp_path / "settings.json"
    monkeypatch.setattr(settings, "SETTINGS_FILE", str(path))

    def write(value):
        if value is None:
            path.unlink(missing_ok=True)
        elif value == "materialised":
            path.write_text(json.dumps(settings.DEFAULT_SETTINGS), encoding="utf-8")
        else:
            path.write_text(json.dumps({"local_inference_max_tokens": value}), encoding="utf-8")
        settings._invalidate_caches()

    write(None)
    yield write
    settings._invalidate_caches()


# ── the three doors, each to the wire ────────────────────────────────────────

async def _drain(response):
    async for _ in response.body_iterator:
        pass


async def _chat_mode(monkeypatch, url, model, preset, backup=None):
    endpoint = _chat_stream_endpoint(monkeypatch, "chat", {}, model=model, endpoint_url=url,
                                     context_overrides={"preset": preset})
    monkeypatch.setattr(settings, "get_setting", REAL_GET_SETTING)
    if backup:
        # After the helper, which installs a strict policy of its own.
        _fallback_to(monkeypatch, *backup)
    monkeypatch.setattr(chat_routes, "stream_llm_with_fallback",
                        llm_core.stream_llm_with_fallback)
    await _drain(await endpoint(_RouteRequest("chat")))


async def _api_chat(monkeypatch, url, model, preset):
    endpoint, _saved = _chat_endpoint(monkeypatch, model=model, endpoint_url=url)
    context = SimpleNamespace(
        user="alice", messages=[{"role": "user", "content": "hello"}],
        route_messages=[{"role": "user", "content": "hello"}], context_length=4096,
        uprefs={}, preset=preset)

    async def build(*args, **kwargs):
        return context

    monkeypatch.setattr(chat_routes, "build_chat_context", build)
    await endpoint(_RouteRequest("chat"), ChatRequest(message="hello", session="session-1"))


#: A turn the agent loop works on. "hello" is a low-signal turn, which the loop
#: answers on a short path of its own (`min(max_tokens or 128, 128)`), and that
#: is not the door this row is about.
TASK = [{"role": "user", "content": "Write a detailed design document for a compiler's "
                                    "register allocator, covering every stage."}]


async def _agent_mode(monkeypatch, url, model, preset):
    _install_route_probe(monkeypatch)
    # The probe stands in for the model layer; put the real one back, so the
    # loop's own lift and the payload builders both run.
    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", llm_core.stream_llm_with_fallback)
    endpoint = _chat_stream_endpoint(monkeypatch, "agent", {}, model=model, endpoint_url=url,
                                     context_overrides={"preset": preset, "messages": TASK,
                                                        "route_messages": TASK})
    monkeypatch.setattr(settings, "get_setting", REAL_GET_SETTING)
    monkeypatch.setattr(chat_routes, "stream_agent_loop", agent_loop.stream_agent_loop)
    await _drain(await endpoint(_RouteRequest("agent")))


async def _door(door, monkeypatch, url, model, preset, *, strict=True):
    if strict:
        monkeypatch.setattr(foreground_model_routing, "_load_policy_preferences",
                            lambda owner=None: {})
    run = {"chat": _chat_mode, "api": _api_chat, "agent": _agent_mode}[door]
    await run(monkeypatch, url, model, preset)


def _first_payload(wire):
    assert wire.sent, "nothing reached the wire"
    return wire.sent[0][1]


async def _sent_max_tokens(door, wire, monkeypatch, url, model, preset):
    await _door(door, monkeypatch, url, model, preset)
    payload = _first_payload(wire)
    assert payload["model"] == model
    return payload.get("max_tokens", "unset")


# ── nobody typed a ceiling: every door sends what it sent ────────────────────

#: `w5-local`'s measured table for an untouched install, door by door.
UNTOUCHED = [
    (OTHER, BRAINSTORM, {"chat": 4096, "api": 4096, "agent": 1_000_000}),
    (OTHER, NO_PRESET, {"chat": "unset", "api": "unset", "agent": "unset"}),
    (MINIMAX, BRAINSTORM, {"chat": 4096, "api": 4096, "agent": 1_000_000}),
    (MINIMAX, NO_PRESET, {"chat": 2048, "api": 2048, "agent": 2048}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("install", [None, "materialised"], ids=["no-file", "materialised"])
@pytest.mark.parametrize("door", DOORS)
@pytest.mark.parametrize("model, preset, want", UNTOUCHED,
                         ids=["other-preset", "other-none", "minimax-preset", "minimax-none"])
async def test_an_untouched_install_sends_what_it_sent(wire, monkeypatch, ceiling, install,
                                                       door, model, preset, want):
    ceiling(install)
    assert await _sent_max_tokens(door, wire, monkeypatch, LOCAL, model, preset) == want[door]


@pytest.mark.asyncio
@pytest.mark.parametrize("door", DOORS)
@pytest.mark.parametrize("model, preset", [(OTHER, BRAINSTORM), (MINIMAX, NO_PRESET)],
                         ids=["other-preset", "minimax-none"])
async def test_an_untouched_install_sends_the_same_bytes(wire, monkeypatch, ceiling, door,
                                                         model, preset):
    """Byte for byte: the whole payload, against the same request with this
    row's two rules taken out (the preset's number on the chat doors, 2048 in
    the profile) — so nothing else in the request moved either."""
    ceiling("materialised")
    await _door(door, monkeypatch, LOCAL, model, preset)
    now = json.dumps(_first_payload(wire), sort_keys=True)
    wire.sent.clear()
    llm_core._response_cache.clear()   # `/api/chat` would answer the repeat from it
    monkeypatch.setattr(chat_routes, "local_door_max_tokens", lambda asked, url: asked)
    monkeypatch.setattr(llm_core, "_minimax_profile_max_tokens",
                        lambda: llm_core.MINIMAX_PROFILE_MAX_TOKENS)
    await _door(door, monkeypatch, LOCAL, model, preset)
    assert json.dumps(_first_payload(wire), sort_keys=True) == now


# ── a typed ceiling: the same number on every door ───────────────────────────

TYPED = [
    (32_768, OTHER, BRAINSTORM, 32_768),
    (32_768, OTHER, NO_PRESET, "unset"),       # nothing named, nothing guarded: as before
    (32_768, MINIMAX, BRAINSTORM, 32_768),
    (32_768, MINIMAX, NO_PRESET, 32_768),      # the 2048, replaced
    (1_024, MINIMAX, NO_PRESET, 1_024),        # replaced downwards too
    (1_024, OTHER, BRAINSTORM, 4096),          # the preset is a floor, never cut
    (0, MINIMAX, NO_PRESET, 2048),             # 0 is "no lift", not a length
    (0, OTHER, BRAINSTORM, 4096),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("door", DOORS)
@pytest.mark.parametrize("typed, model, preset, want", TYPED, ids=[
    "32k-other-preset", "32k-other-none", "32k-minimax-preset", "32k-minimax-none",
    "1k-minimax-none", "1k-preset-is-a-floor", "0-minimax-none", "0-other-preset"])
async def test_a_typed_ceiling_is_sent_on_every_door(wire, monkeypatch, ceiling, door,
                                                     typed, model, preset, want):
    ceiling(typed)
    assert await _sent_max_tokens(door, wire, monkeypatch, LOCAL, model, preset) == want


@pytest.mark.asyncio
@pytest.mark.parametrize("door", DOORS)
@pytest.mark.parametrize("preset, want", [(BRAINSTORM, 4096), (NO_PRESET, "unset")],
                         ids=["preset", "none"])
async def test_a_cloud_endpoint_never_gets_it(wire, monkeypatch, ceiling, door, preset, want):
    ceiling(32_768)
    assert await _sent_max_tokens(door, wire, monkeypatch, CLOUD, OTHER, preset) == want


@pytest.mark.asyncio
@pytest.mark.parametrize("door", ["chat", "api"])
async def test_with_the_local_lift_switched_off_nothing_moves(wire, monkeypatch, ceiling, door):
    """`PANTHEON_UNLIMITED_LOCAL=0` keeps caps on local inference; the ceiling
    is the lift's number, so it neither lifts a preset nor replaces the 2048."""
    ceiling(32_768)
    monkeypatch.setattr(runtime_limits, "_LIFT_WHEN_LOCAL", False)
    assert await _sent_max_tokens(door, wire, monkeypatch, LOCAL, OTHER, BRAINSTORM) == 4096
    wire.sent.clear()
    assert await _sent_max_tokens(door, wire, monkeypatch, LOCAL, MINIMAX, NO_PRESET) == 2048


# ── a fallback chain: each candidate its own number ──────────────────────────

def _fallback_to(monkeypatch, url, model):
    monkeypatch.setattr(foreground_model_routing, "_load_policy_preferences",
                        lambda owner=None: {
                            "foreground_fallback_enabled": True,
                            "foreground_model_fallbacks": [{"endpoint_id": "backup",
                                                            "model": model}],
                        })
    monkeypatch.setattr(foreground_model_routing, "resolve_fallback_entries",
                        lambda entries, owner=None, require_exact_model=False: [
                            (url, model, {})])


async def _chain(door, wire, monkeypatch, primary_url, backup_url):
    wire.down.add(primary_url.split("//")[1].split("/")[0])
    if door == "chat":
        await _chat_mode(monkeypatch, primary_url, OTHER, BRAINSTORM,
                         backup=(backup_url, OTHER))
    else:
        _fallback_to(monkeypatch, backup_url, OTHER)
        await _api_chat(monkeypatch, primary_url, OTHER, BRAINSTORM)
    distinct = []
    for url, payload in wire.sent:
        if (url, payload.get("max_tokens")) not in distinct:
            distinct.append((url, payload.get("max_tokens")))
    return distinct


@pytest.mark.asyncio
@pytest.mark.parametrize("door", ["chat", "api"])
async def test_a_cloud_fallback_is_not_sent_the_local_number(wire, monkeypatch, ceiling, door):
    ceiling(32_768)
    sent = await _chain(door, wire, monkeypatch, LOCAL, CLOUD.replace("selected", "backup"))
    assert [m for _u, m in sent] == [32_768, 4096], sent


@pytest.mark.asyncio
@pytest.mark.parametrize("door", ["chat", "api"])
async def test_a_local_fallback_is_sent_the_local_number(wire, monkeypatch, ceiling, door):
    ceiling(32_768)
    sent = await _chain(door, wire, monkeypatch, CLOUD, "http://192.168.1.20:8000/v1")
    assert [m for _u, m in sent] == [4096, 32_768], sent


# ── the receipt says what was sent ──────────────────────────────────────────

def test_the_receipt_records_the_typed_ceiling_it_sent(ceiling):
    """`B933`'s receipt runs the profile itself, so it moved with it."""
    ceiling(32_768)
    assert llm_core._sent_sampling(LOCAL, MINIMAX, 1.0, 0)["max_tokens"] == 32_768
    ceiling(None)
    assert llm_core._sent_sampling(LOCAL, MINIMAX, 1.0, 0)["max_tokens"] == 2048


# ── one reader ──────────────────────────────────────────────────────────────

def test_the_agent_path_reads_the_same_ceiling(ceiling):
    """The agent's reader adds only its own default for an untyped ceiling."""
    ceiling(None)
    assert llm_core.typed_local_max_tokens_ceiling() is None
    assert agent_loop._local_max_tokens_ceiling() == 1_000_000
    for typed in (0, 4_242, 32_768):
        ceiling(typed)
        assert llm_core.typed_local_max_tokens_ceiling() == typed
        assert agent_loop._local_max_tokens_ceiling() == typed
    ceiling("materialised")
    assert llm_core.typed_local_max_tokens_ceiling() is None
    ceiling(-3)
    assert llm_core.typed_local_max_tokens_ceiling() is None
