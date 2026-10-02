# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1089` — a server that stated its window is asked for what fits.

`B1029` answers a window-enforcing server's length refusal by sending the
request once more asking for what the server said it can serve — one request at
a time. So against vLLM every lifted request was refused once before it was
answered: **measured on `0e64d2b`**, through the real app against the
showcase's scripted model served as vLLM serves a 32,768 window, a ten-round
Agent turn (nine tool rounds and the answer) made **20** streamed requests, 10
of them refused — and vLLM logs each refusal with a traceback.

The refusal states the window and how many tokens the server counted in the
prompt. `llm_core` now keeps both, per endpoint and model (the window, and the
server's tokens per character of the request's JSON), and a later request
whose caller opts in (`max_tokens_floor`) asks for at most what fits —
`fitted_max_tokens`. An estimate, so it never takes a request below the
caller's own number (only the server's own words do, `D-2026-10-02-01` §2), it
never asks above what the caller asked, a low estimate is caught by the resend
and re-learned, and what a server said lapses after
`STATED_WINDOW_TTL_SECONDS`.

`Law 20`: the turns go through the real app (`capture.Server`, `/api/chat_stream`
and `/api/chat`, the real loop, wrappers and payload builders, a real socket to
`demo_model.DemoModel` with a window). What the scripted model cannot show — a
server whose count is not a fixed rate of characters, a lapse, two models on one
server — is driven through `llm_core.stream_llm` itself with only its socket
faked.
"""
from __future__ import annotations

import contextlib
import json
import re
import secrets
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "showcase"))

import demo_model  # noqa: E402
import seed  # noqa: E402
import src.llm_core as llm_core  # noqa: E402
from src.agent_loop import LOCAL_MAX_TOKENS_DEFAULT as LIFT  # noqa: E402

WINDOW = 32_768
BRAINSTORM = 4096
ANSWER = "Read the journal, replay the tail, publish."
ROUNDS = 10    # nine tool rounds, then the answer
WORDS = {
    "ten": "Write a detailed design document for a journal's recovery path.",
    "first": "Write a detailed design document for a log's segment rotation.",
    "later": "Write a detailed design document for a log's compaction pass.",
    "chat_one": "Write a detailed design note for a page cache's readahead.",
    "chat_two": "Write a detailed design note for a page cache's writeback.",
    "api_one": "Write a detailed design note for a page cache's eviction.",
    "api_two": "Write a detailed design note for a page cache's dirty list.",
    "small_one": "Write a detailed design document for a tiny allocator's arenas.",
    "small_two": "Write a detailed design document for a tiny allocator's bins.",
    "takes_one": "Write a detailed design document for a mutex's fast path.",
    "takes_two": "Write a detailed design document for a mutex's slow path.",
}
SCRIPT = [{"key": key, "title": key, "turns": [{"user": words, "steps": [{"say": ANSWER}]}]}
          for key, words in WORDS.items() if key != "ten"]
SCRIPT.append({"key": "ten", "title": "ten", "turns": [{"user": WORDS["ten"], "steps": [
    {"call": "update_plan", "args": {"plan": f"- [x] stage {i}"}} for i in range(ROUNDS - 1)
] + [{"say": ANSWER}]}]})


# ── through the real app ────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def pantheon(tmp_path_factory):
    import capture

    data = tmp_path_factory.mktemp("stated-window") / "data"
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

        yield SimpleNamespace(client=client, endpoint=endpoint, log=log, data=pantheon.data_dir)
    client.close()


def _side(entry):
    """The chat's title, asked on the side (`demo_model._SIDE`)."""
    system = " ".join(str(m.get("content")) for m in entry["messages"] if m.get("role") == "system")
    return any(pattern.search(system) for pattern, _answer in demo_model._SIDE)


def _session(world, endpoint_id):
    sess = seed._ok(world.client.post("/api/session", data={
        "endpoint_id": endpoint_id, "model": seed.DEMO_MODEL_ID}), "chat")
    return sess.get("session_id") or sess.get("id")


def _turn(world, key, endpoint_id, mode="agent"):
    """One turn through `/api/chat_stream`: what the model was sent for it (the
    title aside), the reply and the session."""
    session = _session(world, endpoint_id)
    form = {"message": WORDS[key], "session": session, "mode": mode, "plan_mode": "false",
            "selected_model": seed.DEMO_MODEL_ID, "selected_endpoint_id": endpoint_id,
            "allow_bash": "false", "allow_web_search": "false", "preset_id": "brainstorm"}
    start = len(world.log)
    resp = world.client.post("/api/chat_stream", data=form)
    assert resp.status_code == 200, resp.text[:400]
    events = list(seed._sse_events(resp.text))
    said = "".join(e["delta"] for e in events if isinstance(e.get("delta"), str))
    sent = [e for e in world.log[start:] if e["conv"] == key and not _side(e)]
    return sent, said, session


def _stated(refusal):
    window = int(re.search(r"maximum context length is (\d+) tokens", refusal).group(1))
    prompt = int(re.search(r"your request has (\d+) input tokens", refusal).group(1))
    return window, prompt


def _asked(sent):
    return [(e["max_tokens"], bool(e.get("refused"))) for e in sent]


@pytest.fixture
def typed(world):
    def type_ceiling(value):
        seed._ok(world.client.post("/api/auth/settings",
                                   json={"local_inference_max_tokens": value}), "ceiling")

    yield type_ceiling
    type_ceiling(LIFT)


def test_a_ten_round_agent_turn_makes_eleven_requests_not_twenty(world):
    """The row's `Verify:`. The first round is refused and sent again (`B1029`);
    every later round asks for what fits the window the server stated — above
    the preset, below the lift — and none is refused."""
    sent, said, _ = _turn(world, "ten", world.endpoint(WINDOW))
    streamed = [e for e in sent if e["stream"]]
    assert len(streamed) == ROUNDS + 1, _asked(streamed)
    assert [bool(e.get("refused")) for e in streamed] == [True] + [False] * ROUNDS
    window, prompt = _stated(streamed[0]["refused"])
    assert streamed[1]["max_tokens"] == window - prompt
    later = [e["max_tokens"] for e in streamed[2:]]
    assert all(BRAINSTORM < asked < window - prompt for asked in later), later
    # The prompt grows every round, so what fits shrinks with it.
    assert later == sorted(later, reverse=True) and len(set(later)) == len(later)
    assert said == ANSWER


def test_a_later_turn_is_asked_for_what_fits_from_its_first_request(world):
    """What a server stated is kept per endpoint and model, not per turn: a
    later chat on the same server is sent what fits at once — and its receipt
    (`P4-25`) says the number it was sent."""
    endpoint_id = world.endpoint(WINDOW)
    first, _, _ = _turn(world, "first", endpoint_id)
    assert _asked([e for e in first if e["stream"]])[0] == (LIFT, True)
    later, said, session = _turn(world, "later", endpoint_id)
    streamed = [e for e in later if e["stream"]]
    assert len(streamed) == 1 and not streamed[0].get("refused")
    assert BRAINSTORM < streamed[0]["max_tokens"] < WINDOW
    assert said == ANSWER
    with sqlite3.connect(world.data / "app.db") as db:
        runs = {r for (r,) in db.execute(
            "SELECT run_id FROM events WHERE kind = 'run_config' AND session_id = ?", (session,))}
    assert len(runs) == 1, runs
    receipt = seed._ok(world.client.get(f"/api/diagnostics/receipt/{runs.pop()}"), "receipt")
    assert receipt["config"]["sampling"]["max_tokens"] == streamed[0]["max_tokens"]


@pytest.mark.parametrize("door", ["chat", "api"])
def test_the_chat_doors_learn_the_window_and_are_asked_for_what_fits(world, typed, door):
    """32,768 typed (`B1087`): a first chat turn through either door
    is refused and sent again, and teaches the window; the next turn through the
    same door on the same server is sent what fits, once."""
    typed(WINDOW)
    endpoint_id = world.endpoint(WINDOW)
    first = _door_turn(world, door, f"{door}_one", endpoint_id)
    assert [refused for _asked_, refused in _asked(first)] == [True, False]
    second = _door_turn(world, door, f"{door}_two", endpoint_id)
    assert len(second) == 1 and not second[0].get("refused")
    assert second[0]["stream"] is (door == "chat")
    assert BRAINSTORM < second[0]["max_tokens"] < WINDOW


def _door_turn(world, door, key, endpoint_id):
    if door == "chat":
        sent, said, _ = _turn(world, key, endpoint_id, mode="chat")
        assert said == ANSWER
        return sent
    start = len(world.log)
    resp = world.client.post("/api/chat", json={
        "message": WORDS[key], "session": _session(world, endpoint_id),
        "preset_id": "brainstorm", "selected_endpoint_id": endpoint_id})
    assert resp.status_code == 200, resp.text[:400]
    return [e for e in world.log[start:] if e["conv"] == key and not _side(e)]


def test_an_estimate_never_asks_below_the_preset(world):
    """A 9,000 window with less room than Brainstorm's 4096: what fits is below
    the preset, so the estimate is not trusted there — the later turn is sent
    as asked and the server's own words answer it, exactly (§2)."""
    endpoint_id = world.endpoint(9_000)
    first, said_first, _ = _turn(world, "small_one", endpoint_id)
    later, said, _ = _turn(world, "small_two", endpoint_id)
    for sent, spoken in ((first, said_first), (later, said)):
        refused, resent = [e for e in sent if e["stream"]]
        assert refused["max_tokens"] == LIFT and refused.get("refused")
        window, prompt = _stated(refused["refused"])
        assert resent["max_tokens"] == window - prompt < BRAINSTORM
        assert spoken == ANSWER


def test_a_server_that_takes_the_number_is_never_asked_for_less(world):
    """llama.cpp, Ollama, LM Studio: never refused, never in the table, sent the
    lift every time."""
    endpoint_id = world.endpoint(None)
    for key in ("takes_one", "takes_two"):
        sent, said, _ = _turn(world, key, endpoint_id)
        assert _asked([e for e in sent if e["stream"]]) == [(LIFT, False)] and said == ANSWER


# ── through `stream_llm`, its socket faked ──────────────────────────────────

URL = "http://10.0.0.7:8000/v1"


class _Server:
    """A server holding requests to `window`, counting a prompt at a token per
    four characters of its JSON plus `per_message` for each message — a chat
    template's markup, which no fixed rate of characters predicts."""

    def __init__(self, window=8_192, per_message=40):
        self.window, self.per_message, self.asked = window, per_message, []

    def count(self, payload):
        return (len(json.dumps(payload["messages"])) // 4
                + self.per_message * len(payload["messages"]))

    def refusal(self, payload):
        asked, prompt = payload.get("max_tokens"), self.count(payload)
        self.asked.append(asked)
        if asked and prompt + asked > self.window:
            return (f"'max_tokens' or 'max_completion_tokens' is too large: {asked}. This "
                    f"model's maximum context length is {self.window} tokens and your request "
                    f"has {prompt} input tokens ({asked} > {self.window} - {prompt}).")
        return None


@pytest.fixture
def server(monkeypatch):
    model = _Server()

    class _Stream:
        def __init__(self, payload):
            self.payload, self.said = payload, None

        async def __aenter__(self):
            self.said = model.refusal(self.payload)
            return SimpleNamespace(status_code=400 if self.said else 200,
                                   aread=self._aread, aiter_lines=self._lines)

        async def __aexit__(self, *exc):
            return False

        async def _aread(self):
            return (self.said or "").encode()

        async def _lines(self):
            yield "data: " + json.dumps({"choices": [{"delta": {"content": ANSWER}}]})
            yield "data: [DONE]"

    monkeypatch.setattr(llm_core, "_get_http_client", lambda: SimpleNamespace(
        stream=lambda method, url, json=None, headers=None, **kw: _Stream(json)))
    monkeypatch.setattr(llm_core, "_is_host_dead", lambda url: False)
    monkeypatch.setattr(llm_core, "note_model_activity", lambda *a, **k: None)
    monkeypatch.setattr(llm_core, "_stated_windows", {})
    return model


def _messages(n):
    return [{"role": "user" if i % 2 == 0 else "assistant", "content": f"part {i} " + "x" * 200}
            for i in range(n)]


async def _stream(messages, model="vllm-model", **kwargs):
    out = ""
    async for chunk in llm_core.stream_llm(URL, model, messages, **kwargs):
        out += chunk
    return out


@pytest.mark.asyncio
async def test_a_low_estimate_is_caught_and_the_rate_learned_again(server):
    """Learned on a two-message request, the rate under-counts a thirty-message
    one (the template's markup per message): that request is refused and sent
    again at exactly what fits, the rate is learned from it, and the next
    request like it is sent what fits and answered once."""
    ask = {"max_tokens": LIFT, "max_tokens_floor": BRAINSTORM}
    await _stream(_messages(2), **ask)
    assert server.asked[0] == LIFT and len(server.asked) == 2
    server.asked.clear()
    long = _messages(30)
    await _stream(long, **ask)
    fitted, resent = server.asked
    exact = server.window - server.count({"messages": long})
    assert exact < fitted < LIFT and resent == exact
    server.asked.clear()
    said = await _stream(_messages(30), **ask)
    assert len(server.asked) == 1 and server.asked[0] <= exact and ANSWER in said


@pytest.mark.asyncio
async def test_what_a_server_stated_lapses(server, monkeypatch):
    """After `STATED_WINDOW_TTL_SECONDS` the server is met as for the first time:
    a restarted server may have another window."""
    monkeypatch.setattr(llm_core, "STATED_WINDOW_TTL_SECONDS", 0)
    for _ in range(2):
        server.asked.clear()
        await _stream(_messages(2), max_tokens=LIFT, max_tokens_floor=BRAINSTORM)
        assert server.asked[0] == LIFT and len(server.asked) == 2


@pytest.mark.asyncio
async def test_only_a_caller_that_opts_in_is_asked_for_less(server):
    """A caller that passes no `max_tokens_floor` — a title, a memory pass — is
    sent what it asked and refused as before, whatever the server stated."""
    await _stream(_messages(2), max_tokens=LIFT, max_tokens_floor=BRAINSTORM)
    server.asked.clear()
    said = await _stream(_messages(2), max_tokens=LIFT)
    assert server.asked == [LIFT] and ANSWER not in said


@pytest.mark.asyncio
async def test_never_above_what_the_caller_asked(server):
    """A window with room for more than the caller asked: sent exactly what it
    asked — the preset's 4096, or a typed ceiling — never raised to the window."""
    await _stream(_messages(2), max_tokens=LIFT, max_tokens_floor=BRAINSTORM)
    server.asked.clear()
    await _stream(_messages(2), max_tokens=BRAINSTORM, max_tokens_floor=BRAINSTORM)
    assert server.asked == [BRAINSTORM]


@pytest.mark.asyncio
async def test_what_a_server_stated_is_kept_per_model(server):
    """Another model on the same server has a window of its own."""
    await _stream(_messages(2), max_tokens=LIFT, max_tokens_floor=BRAINSTORM)
    server.asked.clear()
    await _stream(_messages(2), model="other-model", max_tokens=LIFT,
                  max_tokens_floor=BRAINSTORM)
    assert server.asked[0] == LIFT and len(server.asked) == 2
