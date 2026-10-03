# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1106` — a local MiniMax, its *Local reply ceiling* typed at its server's
window and no preset, was refused and never sent again.

With no preset a chat door's number is 0 (`local_door_max_tokens(0, …)` leaves
an unset length unset), and the local MiniMax profile then fills the payload's
length with the typed ceiling (`_apply_local_generation_stability` →
`_minimax_profile_max_tokens`, `B934`) — after both doors had read the caller's
0. So `stream_llm`'s resend asked `servable_max_tokens(…, sent=0)`, which never
fires; `llm_call_async` set no `_length_key` to act on; and `fitted_max_tokens`
(`B1089`) had nothing to fit. **Measured on `7a7f9b2`** through the real app
against the showcase's scripted model listed as `MiniMax-M2` and served as vLLM
serves a 32,768 window, 32,768 typed, no preset: Chat mode sent
`max_tokens: 32768`, was refused, and showed no reply; `/api/chat` answered 400.

Both doors now read the length the payload will carry before they fit it, write
its receipt or build it — through `_sent_sampling`, the receipt's one rule for
what the local profile does to a request (`B933`, `Law 7`) — so the resend, the
fit and the receipt all see the number that is sent.

`Law 20`: nothing above the model's socket is faked. `capture.Server` boots this
checkout's `app.py`; each turn goes through `/api/chat_stream` or `/api/chat`
into the real route, wrapper and payload builders, which open a real socket to
`demo_model.DemoModel` — listed under a MiniMax name, on loopback (so the local
profile applies), served with a window. Each turn gets a server of its own
unless it is the point of the case to share one.
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
MINIMAX = "MiniMax-M2"
ANSWER = "Keep the write-ahead log on its own disk."
PLAIN = "OK"   # the scripted model's answer to a request neither streamed nor sent tools
WORDS = {
    "typed": "Write a design note for a write-ahead log's segment size.",
    "api": "Write a design note for a write-ahead log's checkpoint rule.",
    "first": "Write a design note for a write-ahead log's fsync batching.",
    "second": "Write a design note for a write-ahead log's recovery scan.",
    "takes": "Write a design note for a write-ahead log's compaction.",
}
SCRIPT = [{"key": key, "title": key, "turns": [{"user": words, "steps": [{"say": ANSWER}]}]}
          for key, words in WORDS.items()]


@pytest.fixture(scope="module")
def pantheon(tmp_path_factory):
    import capture

    data = tmp_path_factory.mktemp("minimax-no-preset") / "data"
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
    """A signed-in person with 32,768 typed as the *Local reply ceiling*;
    `endpoint(window)` serves the scripted model, listed as MiniMax, on a
    loopback port of its own."""
    import httpx

    client = httpx.Client(base_url=pantheon.base, timeout=180)
    seed.setup_admin(client, secrets.token_urlsafe(18))
    seed._ok(client.post("/api/auth/settings", json={"local_inference_max_tokens": WINDOW}),
             "ceiling")
    log: list = []
    with contextlib.ExitStack() as models:
        def endpoint(window=None):
            model = models.enter_context(demo_model.DemoModel(
                log=log, conversations=SCRIPT, max_model_len=window, model_id=MINIMAX))
            return seed._ok(client.post("/api/model-endpoints", data={
                "name": f"MiniMax box ({model.port})", "base_url": model.base_url,
                "supports_tools": "true", "require_models": "true"}), "endpoint")["id"]

        yield client, endpoint, log
    client.close()


def _turn_requests(log, start, key):
    """What the model was sent for this turn — not the chat's title, asked on
    the side with the person's words in it."""
    def side(entry):
        system = " ".join(str(m.get("content")) for m in entry["messages"]
                          if m.get("role") == "system")
        return any(pattern.search(system) for pattern, _answer in demo_model._SIDE)

    return [e for e in log[start:] if e["conv"] == key and not side(e)]


def _session(client, endpoint_id):
    sess = seed._ok(client.post("/api/session", data={"endpoint_id": endpoint_id,
                                                      "model": MINIMAX}), "chat")
    return sess.get("session_id") or sess.get("id")


def _chat_stream(world, key, endpoint_id):
    """One Chat-mode turn with no preset."""
    client, _, log = world
    form = {"message": WORDS[key], "session": _session(client, endpoint_id), "mode": "chat",
            "plan_mode": "false", "selected_model": MINIMAX,
            "selected_endpoint_id": endpoint_id, "preset_id": ""}
    start = len(log)
    resp = client.post("/api/chat_stream", data=form)
    assert resp.status_code == 200, resp.text[:400]
    events = list(seed._sse_events(resp.text))
    said = "".join(e["delta"] for e in events if isinstance(e.get("delta"), str))
    return _turn_requests(log, start, key), events, said


def _api_chat(world, key, endpoint_id):
    client, _, log = world
    start = len(log)
    resp = client.post("/api/chat", json={"message": WORDS[key],
                                          "session": _session(client, endpoint_id),
                                          "preset_id": "", "selected_endpoint_id": endpoint_id})
    return _turn_requests(log, start, key), resp


def _stated(refusal):
    window = int(re.search(r"maximum context length is (\d+) tokens", refusal).group(1))
    prompt = int(re.search(r"your request has (\d+) input tokens", refusal).group(1))
    return window, prompt


def _errors(events):
    return [e for e in events
            if e.get("type") == "error" or ("type" not in e and "status" in e and "text" in e)]


def _refused_then_resent(sent):
    """Asked for the profile's length (the typed ceiling), refused, sent once
    more asking for exactly what the server said it can serve, answered."""
    assert len(sent) == 2, [(e["max_tokens"], bool(e.get("refused"))) for e in sent]
    refused, resent = sent
    assert refused["max_tokens"] == WINDOW and refused.get("refused")
    window, prompt = _stated(refused["refused"])
    assert resent["max_tokens"] == window - prompt < WINDOW
    assert not resent.get("refused")
    assert resent["messages"] == refused["messages"]
    return resent["max_tokens"]


def test_a_chat_turn_with_no_preset_on_a_local_minimax_answers(world):
    """The row's `Verify:` — with 32,768 typed and no preset, a Chat-mode turn
    on a local MiniMax against a 32,768-window vLLM answers."""
    _, endpoint, _ = world
    sent, events, said = _chat_stream(world, "typed", endpoint(WINDOW))
    assert all(e["stream"] for e in sent)
    _refused_then_resent(sent)
    assert said == ANSWER and not _errors(events), events[-3:]


def test_api_chat_with_no_preset_on_a_local_minimax_answers(world):
    """`/api/chat` — `llm_call_async`, whose `_length_key` was never set for a
    length the profile filled: HTTP 400 before, the reply now."""
    _, endpoint, _ = world
    sent, resp = _api_chat(world, "api", endpoint(WINDOW))
    assert resp.status_code == 200, resp.text[:400]
    assert all(not e["stream"] for e in sent)
    _refused_then_resent(sent)
    assert resp.json()["response"] == PLAIN


def test_the_next_turn_is_fitted_to_the_window_the_server_stated(world):
    """`B1089`'s fit, which saw a 0 and fitted nothing: the second turn on the
    same server is asked for what fits on the first request — no refusal —
    and never for more than the profile's length."""
    _, endpoint, _ = world
    shared = endpoint(WINDOW)
    first, _events, said = _chat_stream(world, "first", shared)
    _refused_then_resent(first)
    assert said == ANSWER
    second, events, said = _chat_stream(world, "second", shared)
    assert len(second) == 1, [(e["max_tokens"], bool(e.get("refused"))) for e in second]
    assert not second[0].get("refused")
    assert 0 < second[0]["max_tokens"] < WINDOW
    assert said == ANSWER and not _errors(events)


def test_a_server_that_takes_the_length_is_sent_it_once(world):
    """What does not move: a local MiniMax that does not hold a request to a
    window is sent the profile's length — the typed ceiling — once, as before."""
    _, endpoint, _ = world
    sent, events, said = _chat_stream(world, "takes", endpoint(None))
    assert [e["max_tokens"] for e in sent] == [WINDOW]
    assert not sent[0].get("refused")
    assert said == ANSWER and not _errors(events)
