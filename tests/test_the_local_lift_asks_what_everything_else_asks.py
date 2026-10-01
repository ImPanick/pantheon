# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B929` — the local-inference lift knows "local" the way the product does.

The lift (`H08`'s step cap, `P3-21`'s token ceiling, the stream timeout and the
`runtime_limits.unlimited()` truncation sites) decided "is this the owner's own
hardware" with a classifier of its own, `_is_local_openai_compat_url`, while the
local concurrency gate, llama.cpp cache affinity, the context-window probe and
the local MiniMax profile all ask `model_context.is_local_endpoint`. Measured on
the tree before this row, the two disagreed on six of the nine shapes below:
the lift's classifier required a `/v1` path, so an agent run on the owner's own
Ollama (`http://localhost:11434/api/chat`, what a registered Ollama base builds
to) was held to 20 steps while the same model behind LM Studio's `/v1` was
lifted; it did not know Tailscale or `::1`; it matched `10.` as text, so a
public host called `10.example.com` was lifted; and it ignored the endpoint
kind a person chose in Settings.

Driven, not read (`Law 20`): the pre-run promise (`agent_run_limits`), the
real loop's first `agent_budget` frame, what the loop hands the model and what
`runtime_limits.unlimited()` answers inside a run, and the composer's route.
"""

import asyncio
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import core.database as core_database
import routes.chat_routes as chat_routes
import src.agent_loop as agent_loop
import src.runtime_limits as runtime_limits
from core.database import Base, ModelEndpoint
from src.endpoint_resolver import build_chat_url, normalize_base
from src.model_context import is_local_endpoint
from test_the_run_limits_are_said_before_it_runs import (  # noqa: E402
    _first_budget_frame, _limits, _limits_endpoint,
)

#: What a registered Ollama base builds to — the URL a send uses.
OLLAMA_NATIVE = build_chat_url(normalize_base("http://localhost:11434"))
CLOUD = "https://api.example.com/v1/chat/completions"

# (id, url, local?) — `local?` is the product's answer, written out so a change
# to either classifier, not just a disagreement between them, is caught.
_SHAPES = [
    ("ollama-native", OLLAMA_NATIVE, True),
    ("ollama-native-on-the-lan", "http://192.168.1.20:11434/api/chat", True),
    ("llama-cpp-without-v1", "http://127.0.0.1:8080/chat/completions", True),
    ("lm-studio-v1", "http://localhost:1234/v1/chat/completions", True),
    ("tailscale", "http://100.100.1.2:1234/v1/chat/completions", True),
    ("ipv6-loopback", "http://[::1]:8080/v1/chat/completions", True),
    ("a-public-host-that-starts-with-10", "http://10.example.com/v1/chat/completions", False),
    ("ollama-cloud", "https://ollama.com/api/chat", False),
    ("cloud", CLOUD, False),
]


@pytest.fixture
def unpinned(monkeypatch):
    """A cap nobody typed, and the shipped lift switches: the lift is decided
    by the endpoint alone."""
    monkeypatch.setattr(agent_loop, "_setting_pinned", lambda key: False)
    monkeypatch.setattr(runtime_limits, "_FORCE_UNLIMITED", False)
    monkeypatch.setattr(runtime_limits, "_LIFT_WHEN_LOCAL", True)


@pytest.fixture
def registered(monkeypatch):
    """Endpoints a person registered, in a database of our own — the one
    `is_local_endpoint` reads the endpoint kind from, and the one the composer's
    route resolves a selection against."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine, autoflush=False)
    db = TestSession()
    db.add_all([
        ModelEndpoint(id="ep-ollama", name="Ollama", base_url="http://localhost:11434",
                      owner="alice", is_enabled=True),
        # A LiteLLM-style proxy on this machine that forwards to a cloud
        # provider: the person said so by choosing the kind.
        ModelEndpoint(id="ep-proxy", name="Proxy", base_url="http://localhost:4000/v1",
                      owner="alice", is_enabled=True, endpoint_kind="api"),
        # The owner's own GPU box behind a public hostname: also said by kind.
        ModelEndpoint(id="ep-gpu", name="GPU box", base_url="https://gpu.example.net/v1",
                      owner="alice", is_enabled=True, endpoint_kind="local"),
    ])
    db.commit()
    db.close()
    monkeypatch.setattr(core_database, "SessionLocal", TestSession)
    monkeypatch.setattr(chat_routes, "SessionLocal", TestSession)
    monkeypatch.setattr(chat_routes, "effective_user", lambda request: "alice")
    import src.settings as settings
    monkeypatch.setattr(settings, "get_setting", lambda key, default=None: default)
    return TestSession


# ── one classifier ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("_id,url,local", _SHAPES, ids=[s[0] for s in _SHAPES])
def test_a_run_is_lifted_exactly_where_the_product_calls_the_endpoint_local(
        unpinned, _id, url, local):
    assert is_local_endpoint(url) is local
    limits = agent_loop.agent_run_limits(url, 20, 0)
    if local:
        assert (limits["round_limit_source"], limits["round_limit"]) == ("local_lift", 100_000)
    else:
        assert (limits["round_limit_source"], limits["round_limit"]) == ("configured", 20)
    assert agent_loop.run_is_unlimited(url) is local


# ── the row's Verify: the real loop, on the owner's own Ollama ──────────────

def test_an_ollama_native_runs_first_budget_frame_says_local_lift(monkeypatch, unpinned):
    frame = _first_budget_frame(monkeypatch, OLLAMA_NATIVE, max_rounds=20, max_tool_calls=0)
    assert (frame["round_limit_source"], frame["round_limit"]) == ("local_lift", 100_000)
    assert frame["round_limit_configured"] == 20
    # And the promise before the run is the same answer (`P7-10`).
    before = agent_loop.agent_run_limits(OLLAMA_NATIVE, 20, 0)
    assert {k: frame[k] for k in before} == before


def _what_the_model_was_handed(monkeypatch, url, *, max_tokens):
    """The real loop, with only the model scripted. Records the `max_tokens` the
    loop hands the model and what `runtime_limits.unlimited()` — read by every
    truncation site — answers while the run is going."""
    seen = {}
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: None, raising=False)
    monkeypatch.setattr(agent_loop, "estimate_tokens", lambda *a, **k: 10, raising=False)
    monkeypatch.setattr(agent_loop, "blocked_tools_for_owner", lambda owner: set(), raising=False)
    monkeypatch.setattr(agent_loop, "_local_max_tokens_ceiling", lambda: 1_000_000)

    async def fake_stream(candidates, messages, **kwargs):
        seen["max_tokens"] = kwargs.get("max_tokens")
        seen["unlimited"] = runtime_limits.unlimited()
        yield f"data: {json.dumps({'delta': 'Done.'})}\n\n"
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", fake_stream, raising=False)

    async def _go():
        return [c async for c in agent_loop.stream_agent_loop(
            url, "m", [{"role": "user", "content": "go"}],
            max_tokens=max_tokens, max_rounds=20, max_tool_calls=0,
            relevant_tools={"update_plan"})]

    asyncio.run(_go())
    return seen


@pytest.mark.parametrize("url,lifted", [
    (OLLAMA_NATIVE, True),
    ("http://127.0.0.1:8080/chat/completions", True),
    (CLOUD, False),
], ids=["ollama-native", "llama-cpp-without-v1", "cloud"])
def test_inside_the_run_the_whole_lift_follows_the_same_answer(monkeypatch, unpinned, url, lifted):
    """Not just the step cap: the token ceiling the model is handed and the
    truncation switch the tools read come from the same classification."""
    seen = _what_the_model_was_handed(monkeypatch, url, max_tokens=4096)
    assert seen["unlimited"] is lifted
    assert seen["max_tokens"] == (1_000_000 if lifted else 4096)


# ── the kind a person chose in Settings is part of the answer ──────────────

@pytest.mark.parametrize("url,source", [
    # `api` on this machine: a proxy to somebody's cloud, held to the setting.
    ("http://localhost:4000/v1/chat/completions", "configured"),
    # `local` behind a public hostname: the owner's box, lifted.
    ("https://gpu.example.net/v1/chat/completions", "local_lift"),
], ids=["api-kind-on-localhost", "local-kind-on-a-public-host"])
def test_the_endpoint_kind_a_person_set_decides(unpinned, registered, url, source):
    assert agent_loop.agent_run_limits(url, 20, 0)["round_limit_source"] == source
    assert is_local_endpoint(url) is (source == "local_lift")


# ── the composer says it before the send ───────────────────────────────────

def test_the_composer_promises_the_lift_for_a_registered_ollama(unpinned, registered):
    """`P7-10`'s hint reports what the loop will enforce. For a registered
    Ollama base it said *Up to 20 steps*, truthfully, because the loop held the
    run to 20; now the loop lifts it, and so does the promise."""
    answer = _limits(_limits_endpoint(), endpoint_id="ep-ollama", endpoint_url="")
    assert (answer["round_limit_source"], answer["round_limit"]) == ("local_lift", 100_000)
