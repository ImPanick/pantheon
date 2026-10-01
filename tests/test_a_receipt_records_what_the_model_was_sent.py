# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B933` — a run receipt records the sampling the model was sent.

`_capture_run_config` says it records *"the resolved configuration … caps
applied"*, and it ran at the top of `llm_call`, `llm_call_async` and
`stream_llm` with the caller's `temperature` and `max_tokens` — before the local
MiniMax profile (`_apply_local_generation_stability`) rewrote the payload. So a
chat with no preset on a local MiniMax was receipted at 1.0 and sent 0.2, a
missing `max_tokens` was receipted as 0 and sent as 2048, and the profile's
penalties and stop strings — knobs `record_run_config` has room for — were in
no receipt at all.

Now the capture runs the profile itself on the two values, against the URL the
payload goes to (`_sent_sampling`), so the receipt and the payload read one
rule. Driven, not read (`Law 20`): the three entry points and both chat routes
down to the payload builders, with only the socket faked, and the receipt read
back from the events table.
"""
import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import core.database as core_db
import routes.chat_routes as chat_routes
import src.foreground_model_routing as foreground_model_routing
import src.llm_core as llm_core
from core.database import Base, Event, ModelEndpoint
from src import events as ev
from src.request_models import ChatRequest
from test_foreground_model_routing import (  # noqa: E402
    _RouteRequest,
    _chat_endpoint,
    _chat_stream_endpoint,
)
from test_the_qwen3_cap_guards_every_door import wire  # noqa: F401,E402

MINIMAX = "example-org/MiniMax-M2.7-BF16-mlx-4Bit"
LOCAL = "http://192.168.1.22:8091/v1/chat/completions"
NO_PRESET = SimpleNamespace(temperature=1.0, max_tokens=0, character_name=None,
                            explicit_params=frozenset())

#: The knobs a receipt keeps (`events.record_run_config`).
_RECEIPT_KNOBS = ("temperature", "top_p", "top_k", "max_tokens", "presence_penalty",
                  "frequency_penalty", "repetition_penalty", "seed", "stop",
                  "reasoning_effort", "num_ctx")

#: What the local MiniMax profile sends when nobody chose anything.
_PROFILE = {"temperature": 0.2, "max_tokens": 2048, "top_p": 0.9, "top_k": 20,
            "repetition_penalty": 1.12, "frequency_penalty": 0.08,
            "presence_penalty": 0.02, "stop": ["<|im_end|>", "<|endoftext|>", "</s>"]}


@pytest.fixture
def receipts(tmp_path, monkeypatch):
    """An events table of our own, and a fresh run for each test."""
    engine = create_engine(f"sqlite:///{tmp_path}/events.db",
                           connect_args={"check_same_thread": False})
    # The two tables these paths read: the receipt's, and the endpoint kinds
    # `is_local_endpoint` consults. The whole schema costs seconds a test.
    Base.metadata.create_all(bind=engine, tables=[Event.__table__, ModelEndpoint.__table__])
    maker = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr(core_db, "SessionLocal", maker)
    monkeypatch.setattr(ev, "_last_prune", 0.0)
    ev._turn_started.set(None)
    ev._run_id.set(None)
    llm_core._run_config_recorded.set(False)
    llm_core._run_config_had_tools.set(False)

    def sampling():
        db = maker()
        try:
            run_ids = {e.run_id for e in db.query(Event).filter(Event.kind == "run_config")}
        finally:
            db.close()
        assert len(run_ids) == 1, f"expected one run with a config, got {run_ids}"
        return ev.receipt(run_ids.pop())["config"]["sampling"]

    yield sampling
    ev._turn_started.set(None)
    ev._run_id.set(None)
    llm_core._run_config_recorded.set(False)
    llm_core._run_config_had_tools.set(False)
    engine.dispose()


@pytest.fixture
def every_socket(wire, monkeypatch):
    """`wire` fakes the two async sockets; the synchronous `llm_call` posts
    through `httpx.post`, which is faked here into the same list."""

    def sync_post(url, headers=None, json=None, timeout=None):
        wire.sent.append((url, json))
        return SimpleNamespace(is_success=True, status_code=200, text="",
                               json=lambda: {"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(llm_core.httpx, "post", sync_post)
    return wire


def _on_the_wire(payload):
    """The receipt's knobs, read off a payload as it was posted."""
    if "options" in payload:   # Ollama's native shape
        options = payload["options"]
        return {"temperature": options.get("temperature"),
                "max_tokens": options.get("num_predict", 0)}
    seen = {k: payload[k] for k in _RECEIPT_KNOBS if k in payload}
    seen.setdefault("max_tokens", 0)
    return seen


# ── the row's Verify: a local MiniMax chat with no preset, through the routes ─

@pytest.mark.asyncio
async def test_chat_mode_on_a_local_minimax_with_no_preset_is_receipted_at_what_it_sent(
        receipts, wire, monkeypatch):
    endpoint = _chat_stream_endpoint(monkeypatch, "chat", {}, model=MINIMAX,
                                     endpoint_url=LOCAL,
                                     context_overrides={"preset": NO_PRESET})
    monkeypatch.setattr(chat_routes, "stream_llm_with_fallback",
                        llm_core.stream_llm_with_fallback)
    response = await endpoint(_RouteRequest("chat"))
    async for _ in response.body_iterator:
        pass
    (_url, payload), = wire.sent
    assert payload["temperature"] == 0.2
    assert receipts() == _PROFILE


@pytest.mark.asyncio
async def test_api_chat_on_a_local_minimax_with_no_preset_is_receipted_at_what_it_sent(
        receipts, wire, monkeypatch):
    monkeypatch.setattr(foreground_model_routing, "_load_policy_preferences",
                        lambda owner=None: {})
    endpoint, _saved = _chat_endpoint(monkeypatch, model=MINIMAX, endpoint_url=LOCAL)
    context = SimpleNamespace(
        user="alice", messages=[{"role": "user", "content": "hello"}],
        route_messages=[{"role": "user", "content": "hello"}], context_length=4096,
        uprefs={}, preset=NO_PRESET)

    async def build(*args, **kwargs):
        return context

    monkeypatch.setattr(chat_routes, "build_chat_context", build)
    await endpoint(_RouteRequest("chat"), ChatRequest(message="hello", session="session-1"))
    (_url, payload), = wire.sent
    assert payload["temperature"] == 0.2
    assert receipts() == _PROFILE


# ── every entry point, every shape: the receipt is the wire ─────────────────

def _llm_call(url, model, **kw):
    try:
        llm_core.llm_call(url, model, [{"role": "user", "content": "hi"}], **kw)
    except Exception:
        pass   # a shape the faked reply does not parse; the request was sent


def _llm_call_async(url, model, **kw):
    async def go():
        try:
            await llm_core.llm_call_async(url, model, [{"role": "user", "content": "hi"}],
                                          session_id="s1", **kw)
        except Exception:
            pass
    asyncio.run(go())


def _stream_llm(url, model, **kw):
    async def go():
        try:
            async for _ in llm_core.stream_llm(url, model, [{"role": "user", "content": "hi"}],
                                               session_id="s1", **kw):
                pass
        except Exception:
            pass
    asyncio.run(go())


_DOORS = [_llm_call, _llm_call_async, _stream_llm]
_CHOSEN = frozenset({"temperature"})

# (id, url, model, temperature, max_tokens, explicit_params, what the receipt says)
_CASES = [
    ("local-minimax-no-preset", LOCAL, MINIMAX, 1.0, 0, frozenset(), _PROFILE),
    ("local-minimax-chosen", LOCAL, MINIMAX, 0.9, 0, _CHOSEN,
     {**_PROFILE, "temperature": 0.9}),
    ("local-minimax-preset-max-tokens", LOCAL, MINIMAX, 1.0, 6000, frozenset(),
     {**_PROFILE, "max_tokens": 6000}),
    ("local-minimax-internal-greedy", LOCAL, MINIMAX, 0, 200, frozenset(),
     {**_PROFILE, "max_tokens": 200}),
    ("cloud-minimax", "https://api.minimax.io/v1/chat/completions", MINIMAX, 1.0, 0,
     frozenset(), {"temperature": 1.0, "max_tokens": 0}),
    ("local-other-model", LOCAL, "qwen2.5-7b-instruct", 0.7, 512, frozenset(),
     {"temperature": 0.7, "max_tokens": 512}),
    ("ollama-native-minimax", "http://localhost:11434/api/chat", MINIMAX, 1.0, 0,
     frozenset(), {"temperature": 1.0, "max_tokens": 0}),
]


@pytest.mark.parametrize("door", _DOORS, ids=["llm_call", "llm_call_async", "stream_llm"])
@pytest.mark.parametrize("_id,url,model,temperature,max_tokens,explicit,expected", _CASES,
                         ids=[c[0] for c in _CASES])
def test_the_receipt_says_what_the_request_carried(
        receipts, every_socket, door, _id, url, model, temperature, max_tokens,
        explicit, expected):
    ev.mark_turn_start()
    door(url, model, temperature=temperature, max_tokens=max_tokens,
         explicit_params=explicit)
    (_url, payload), = every_socket.sent
    recorded = receipts()
    assert recorded == expected
    assert recorded == _on_the_wire(payload)
