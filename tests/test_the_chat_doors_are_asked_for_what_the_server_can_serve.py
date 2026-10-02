# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1029`'s resend on the chat doors — `B1087`.

`D-2026-10-01-04` made a *Local reply ceiling* a person typed apply on every
door (`B934`, `local_door_max_tokens`), so a person who types their server's
window as its reply ceiling has every chat request ask for the whole window.
vLLM refuses a request whose prompt plus `max_tokens` exceeds its window, with a
400 that states the window and the prompt's size. `B1029` sent such a request
once more asking for exactly what the server can serve — on the agent path
only, as that row asked. **Measured before this** (`0e64d2b`), through the real
app against the showcase's scripted model served as vLLM serves a 32,768 window,
with 32,768 typed: Chat mode with Brainstorm sent 32,768, was refused
(`32768 > 32768 - 496`) and showed no reply; `/api/chat` answered HTTP 400.

The chat doors now pass the preset's own number as `max_tokens_floor` — the
opt-in to `llm_core`'s one rule (`Law 7`) — on chat-mode streaming and on
`/api/chat`; with fallbacks on, the wrappers merge it into the request
`_chat_candidate_request_factory` builds for every candidate. With the owner's call (`D-2026-10-02-01` §2) that includes a
window with less room than the preset: Chat mode with Brainstorm on a 4,500
window was refused at 4096 and is now sent what fits.

`Law 20`: nothing above the model's socket is faked. `capture.Server` boots this
checkout's `app.py` on a throwaway data directory; every turn goes through
`/api/chat_stream` or `/api/chat` into the real route, fallback wrapper and
payload builders, which open a real socket to `demo_model.DemoModel` served
with a window (`max_model_len`). Each turn gets an endpoint of its own, so
nothing one server said is carried into another test.
"""
from __future__ import annotations

import contextlib
import re
import secrets
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "showcase"))

import demo_model  # noqa: E402
import seed  # noqa: E402

WINDOW = 32_768
BRAINSTORM = 4096
ANSWER = "Hash the key, probe linearly, grow at seventy percent."
# The scripted model answers a request that is neither streamed nor sent tools
# plainly, as it answers a chat's title (`demo_model._SIDE`): that is
# `/api/chat`'s own request, which never streams.
PLAIN = "OK"
WORDS = {
    "typed": "Write a detailed design note for a hash table's probing scheme.",
    "api": "Write a detailed design note for a ring buffer's wraparound.",
    "chain": "Write a detailed design note for a trie's node layout.",
    "api_chain": "Write a detailed design note for a skip list's levels.",
    "small": "Write a detailed design note for a bloom filter's hash count.",
    "accepts": "Write a detailed design note for a B-tree's split rule.",
    "fits": "Write a detailed design note for a heap's sift-down.",
}
SCRIPT = [{"key": key, "title": key, "turns": [{"user": words, "steps": [{"say": ANSWER}]}]}
          for key, words in WORDS.items()]


@pytest.fixture(scope="module")
def pantheon(tmp_path_factory):
    import capture

    data = tmp_path_factory.mktemp("chat-doors") / "data"
    data.mkdir()
    server = capture.Server(sys.executable, data, capture._free_port(),
                            extra_env={"PANTHEON_DISABLE_MCP": "1"})
    try:
        server.start(timeout=150)
    except RuntimeError as e:
        server.stop()
        pytest.fail(f"{e}\n{server.log_path.read_text(encoding='utf-8', errors='replace')[-3000:]}")
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture(scope="module")
def world(pantheon):
    """A signed-in person; `endpoint(window)` serves the scripted model on a
    loopback port of its own (as vLLM serves `window`, or taking any length)."""
    import httpx

    client = httpx.Client(base_url=pantheon.base, timeout=180)
    seed.setup_admin(client, secrets.token_urlsafe(18))
    log: list = []
    with contextlib.ExitStack() as models:
        def endpoint(window=None):
            model = models.enter_context(demo_model.DemoModel(
                log=log, conversations=SCRIPT, max_model_len=window))
            return seed._ok(client.post("/api/model-endpoints", data={
                "name": f"Demo model ({model.port})", "base_url": model.base_url,
                "supports_tools": "true", "require_models": "true"}), "endpoint")["id"]

        yield client, endpoint, log
    client.close()


@pytest.fixture
def typed(world):
    """Type a *Local reply ceiling*, and put the shipped one back after."""
    client, _, _ = world

    def type_ceiling(value):
        seed._ok(client.post("/api/auth/settings", json={"local_inference_max_tokens": value}),
                 "ceiling")

    yield type_ceiling
    type_ceiling(1_000_000)


@pytest.fixture
def fallbacks_on(world):
    """Foreground fallbacks on, to a server that takes any length — so every
    chat request goes through `_chat_candidate_request_factory`."""
    client, endpoint, _ = world
    backup = endpoint()

    def pref(key, value):
        seed._ok(client.put(f"/api/prefs/{key}", json={"value": value}), key)

    pref("foreground_model_fallbacks", [{"endpoint_id": backup, "model": seed.DEMO_MODEL_ID}])
    pref("foreground_fallback_enabled", True)
    yield backup
    pref("foreground_fallback_enabled", False)
    pref("foreground_model_fallbacks", [])


def _turn_requests(log, start, key):
    """What the model was sent for this turn — not the chat's title, which
    Pantheon asks for on the side with the person's words in it."""
    def side(entry):
        system = " ".join(str(m.get("content")) for m in entry["messages"]
                          if m.get("role") == "system")
        return any(pattern.search(system) for pattern, _answer in demo_model._SIDE)

    return [e for e in log[start:] if e["conv"] == key and not side(e)]


def _session(world, endpoint_id):
    client, _, _ = world
    sess = seed._ok(client.post("/api/session", data={"endpoint_id": endpoint_id,
                                                      "model": seed.DEMO_MODEL_ID}), "chat")
    return sess.get("session_id") or sess.get("id")


def _chat_stream(world, key, endpoint_id, preset="brainstorm"):
    """One Chat-mode turn. Returns what the model was sent for it, the events
    and the reply as streamed."""
    client, _, log = world
    form = {"message": WORDS[key], "session": _session(world, endpoint_id), "mode": "chat",
            "plan_mode": "false", "selected_model": seed.DEMO_MODEL_ID,
            "selected_endpoint_id": endpoint_id, "preset_id": preset}
    start = len(log)
    resp = client.post("/api/chat_stream", data=form)
    assert resp.status_code == 200, resp.text[:400]
    events = list(seed._sse_events(resp.text))
    said = "".join(e["delta"] for e in events if isinstance(e.get("delta"), str))
    return _turn_requests(log, start, key), events, said


def _api_chat(world, key, endpoint_id, preset="brainstorm"):
    """One `/api/chat` turn. Returns what the model was sent and the response."""
    client, _, log = world
    start = len(log)
    resp = client.post("/api/chat", json={"message": WORDS[key],
                                          "session": _session(world, endpoint_id),
                                          "preset_id": preset,
                                          "selected_endpoint_id": endpoint_id})
    return _turn_requests(log, start, key), resp


def _stated(refusal):
    """What the server said: its window and the prompt's size."""
    window = int(re.search(r"maximum context length is (\d+) tokens", refusal).group(1))
    prompt = int(re.search(r"your request has (\d+) input tokens", refusal).group(1))
    return window, prompt


def _refused_then_resent(sent, asked):
    """The one shape every door must have: asked for `asked`, refused, sent once
    more asking for exactly what the server said it can serve, answered."""
    assert len(sent) == 2, [(e["max_tokens"], bool(e.get("refused"))) for e in sent]
    refused, resent = sent
    assert refused["max_tokens"] == asked and refused.get("refused")
    window, prompt = _stated(refused["refused"])
    assert resent["max_tokens"] == window - prompt < asked
    assert not resent.get("refused")
    assert resent["messages"] == refused["messages"] and resent["stream"] == refused["stream"]
    return resent["max_tokens"]


def _errors(events):
    return [e for e in events
            if e.get("type") == "error" or ("type" not in e and "status" in e and "text" in e)]


# ── the row ─────────────────────────────────────────────────────────────────

def test_a_chat_turn_with_the_window_typed_as_the_ceiling_answers(world, typed):
    """The row's `Verify:`: with 32,768 typed, a Chat-mode Brainstorm turn
    against a 32,768-window vLLM answers."""
    _, endpoint, _ = world
    typed(WINDOW)
    sent, events, said = _chat_stream(world, "typed", endpoint(WINDOW))
    assert all(e["stream"] and not e["tools"] for e in sent)
    _refused_then_resent(sent, WINDOW)
    assert said == ANSWER and not _errors(events)
    assert any(e.get("type") == "message_saved" for e in events)


def test_api_chat_with_the_window_typed_as_the_ceiling_answers(world, typed):
    """`/api/chat` — the non-streaming door (`llm_call_async_with_route_fallback`
    → `llm_call_async`): HTTP 400 before, the reply now."""
    _, endpoint, _ = world
    typed(WINDOW)
    sent, resp = _api_chat(world, "api", endpoint(WINDOW))
    assert resp.status_code == 200, resp.text[:400]
    assert all(not e["stream"] for e in sent)
    _refused_then_resent(sent, WINDOW)
    assert resp.json()["response"] == PLAIN


@pytest.mark.parametrize("door", ["chat_stream", "api_chat"])
def test_with_fallbacks_on_each_candidate_is_sent_again_too(world, typed, fallbacks_on, door):
    """With fallbacks on, every candidate's request is built by
    `_chat_candidate_request_factory` and the wrapper merges the door's kwargs
    into it: the selected server is sent the request again and answers it, and
    the fallback is never needed."""
    _, endpoint, log = world
    typed(WINDOW)
    selected = endpoint(WINDOW)
    if door == "chat_stream":
        sent, events, said = _chat_stream(world, "chain", selected)
        assert said == ANSWER and not _errors(events)
        assert not any(e.get("type") == "fallback" for e in events)
    else:
        sent, resp = _api_chat(world, "api_chain", selected)
        assert resp.status_code == 200 and resp.json()["response"] == PLAIN, resp.text[:400]
    _refused_then_resent(sent, WINDOW)


def test_less_room_than_the_preset_is_asked_for_what_it_has(world):
    """`D-2026-10-02-01` §2 on the chat door, nothing typed: Brainstorm's own
    4096, unlifted, on a 4,500 window — refused before with no reply; now sent
    once more asking for what fits, below the preset."""
    _, endpoint, _ = world
    sent, events, said = _chat_stream(world, "small", endpoint(4_500))
    assert _refused_then_resent(sent, BRAINSTORM) < BRAINSTORM
    assert said == ANSWER and not _errors(events)


# ── what does not move ──────────────────────────────────────────────────────

def test_a_server_that_takes_the_number_is_asked_once(world, typed):
    """A local server that does not hold a request to its window (llama.cpp,
    Ollama, LM Studio) is sent the typed ceiling, once, exactly as before."""
    _, endpoint, _ = world
    typed(WINDOW)
    sent, _events, said = _chat_stream(world, "accepts", endpoint(None))
    assert [e["max_tokens"] for e in sent] == [WINDOW]
    assert said == ANSWER


def test_a_request_the_window_holds_is_sent_once(world):
    """Nothing typed, a window with room: the preset's own 4096, once."""
    _, endpoint, _ = world
    sent, _events, said = _chat_stream(world, "fits", endpoint(WINDOW))
    assert [e["max_tokens"] for e in sent] == [BRAINSTORM]
    assert said == ANSWER
