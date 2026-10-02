# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1029` — Agent mode with a length-naming preset answers on a local vLLM.

Agent mode lifts a preset's `max_tokens` on local inference to the machine's
ceiling (`D-2026-09-08-02`: 1,000,000 unless an operator typed one, the preset a
floor). vLLM's OpenAI server refuses a request whose prompt plus `max_tokens`
exceeds its window, with a 400 before a token is generated — read from vLLM's
`OpenAIServing._validate_input` at v0.6.6, v0.8.5, v0.10.1 and v0.11.0, the same
rule in all four. **Measured before the fix** through the real app against a
model served that way (window 32,768): Agent mode with Brainstorm sent
1,000,000, the server refused it, and the turn ended on the server's 400; no
preset, and Chat mode with Brainstorm, answered.

The refusal says the window and the prompt's size, so the request is sent once
more asking for exactly what the server can serve (`llm_core.
servable_max_tokens`) — never above what was asked, and never at all to a server
that took the number. Below the preset's own number too, since the owner's call
(`D-2026-10-02-01` §2: *"the preset stops being a floor in that one case"*).

`Law 20`: nothing above the model's socket is faked. `capture.Server` boots this
checkout's `app.py` on a throwaway data directory; every turn goes through
`/api/chat_stream` into the real agent loop, fallback wrapper and payload
builders, which open a real socket to the showcase's scripted model
(`demo_model.DemoModel`) served the way vLLM serves one (`max_model_len`): its
`/v1/models` reports the window, and its check is vLLM's rule over its own
approximate token count.
"""
from __future__ import annotations

import json
import re
import secrets
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "showcase"))

import demo_model  # noqa: E402
import seed  # noqa: E402
import src.llm_core as llm_core  # noqa: E402
from src.agent_loop import LOCAL_MAX_TOKENS_DEFAULT as LIFT  # noqa: E402

WINDOW = 32_768
ANSWER = "Allocate, coalesce, spill, rewrite."
PLAN = json.dumps({"plan": "- [ ] list the stages"})
FENCED = "```update_plan\n" + PLAN + "\n```"

# Each turn names a task, so the agent takes its tool path rather than the short
# answer it gives small talk (`_direct_low_signal`), which never lifts.
WORDS = {
    "brainstorm": "Write a detailed design document for a compiler's register allocator.",
    "reason": "Write a detailed design document for a garbage collector's marking phase.",
    "code_analyze": "Write a detailed design document for a linker's relocation pass.",
    "accepts": "Write a detailed design document for an assembler's symbol table.",
    "typed": "Write a detailed design document for a scheduler's ready queue.",
    "small": "Write a detailed design document for a parser's error recovery.",
    "circles": "Write a detailed design document for a cache's eviction policy.",
}
SCRIPT = [{"key": key, "title": key,
           "turns": [{"user": words, "steps": [{"say": ANSWER}]}]}
          for key, words in WORDS.items() if key != "circles"]
# The same call every round until the loop breaker forces an answer, which the
# model writes as a call again and no prose: the salvage (`llm_call_async`).
SCRIPT.append({"key": "circles", "title": "circles", "turns": [{
    "user": WORDS["circles"],
    "steps": [{"call": "update_plan", "args": PLAN, "say": FENCED}] * 12}]})


@pytest.fixture(scope="module")
def pantheon(tmp_path_factory):
    import capture

    data = tmp_path_factory.mktemp("b1029") / "data"
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


WINDOWS = {"vllm": WINDOW, "small": 9_000, "accepts": None}


@pytest.fixture(scope="module")
def world(pantheon):
    """A signed-in person and the scripted model, served as vLLM serves a 32,768
    window (`vllm`), as vLLM serves one too small for the preset (`small`), or
    as a server that takes any length (`accepts`) — on a loopback port of its
    own for every turn. A server that stated its window is remembered
    (`B1089`), so a turn that must meet the server for the first time
    meets a new one."""
    import contextlib

    import httpx

    client = httpx.Client(base_url=pantheon.base, timeout=180)
    seed.setup_admin(client, secrets.token_urlsafe(18))
    log: list = []
    with contextlib.ExitStack() as models:
        def endpoint(kind):
            model = models.enter_context(demo_model.DemoModel(
                log=log, conversations=SCRIPT, max_model_len=WINDOWS[kind]))
            return seed._ok(client.post("/api/model-endpoints", data={
                "name": f"Demo model ({kind}, {model.port})", "base_url": model.base_url,
                "supports_tools": "true", "require_models": "true"}), kind)["id"]

        yield client, endpoint, log
    client.close()


def _turn(world, key, endpoint="vllm", preset="brainstorm"):
    """One Agent-mode turn, on a server met for the first time. Returns the
    requests the model was sent for it (in order), the events, the saved reply
    and the run's id."""
    client, new_endpoint, log = world
    endpoint_id = new_endpoint(endpoint)
    sess = seed._ok(client.post("/api/session", data={"endpoint_id": endpoint_id,
                                                      "model": seed.DEMO_MODEL_ID}), "chat")
    form = {"message": WORDS[key], "session": sess.get("session_id") or sess.get("id"),
            "mode": "agent", "plan_mode": "false", "selected_model": seed.DEMO_MODEL_ID,
            "selected_endpoint_id": endpoint_id, "allow_bash": "false",
            "allow_web_search": "false", "preset_id": preset}
    start = len(log)
    resp = client.post("/api/chat_stream", data=form)
    assert resp.status_code == 200, resp.text[:400]
    events = list(seed._sse_events(resp.text))
    sent = [e for e in log[start:] if e["conv"] == key]
    said = "".join(e["delta"] for e in events if isinstance(e.get("delta"), str))
    return {"sent": sent, "events": events, "said": said, "session": form["session"]}


def _side(entry):
    """A request Pantheon makes on the side — the chat's title — rather than
    the turn's own, by the scripted model's own patterns (`demo_model._SIDE`)."""
    system = " ".join(str(m.get("content")) for m in entry["messages"] if m.get("role") == "system")
    return any(pattern.search(system) for pattern, _answer in demo_model._SIDE)


def _stated(refusal):
    """What the server said: its window and the prompt's size."""
    window = int(re.search(r"maximum context length is (\d+) tokens", refusal).group(1))
    prompt = int(re.search(r"your request has (\d+) input tokens", refusal).group(1))
    return window, prompt


def _errors(turn):
    """The turn's error events: typed ones, and the model's own refusal as the
    stream passes it on (`{"status", "text", "raw"}`, no type)."""
    return [e for e in turn["events"]
            if e.get("type") == "error" or ("type" not in e and "status" in e and "text" in e)]


# ── the row ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("preset, floor", [("brainstorm", 4096), ("reason", 6000),
                                           ("code_analyze", 8000)])
def test_an_agent_turn_with_a_length_naming_preset_answers(world, preset, floor):
    """The row's `Verify:`, for each preset that names a length. The lifted
    request is refused; the same request is sent once more asking for exactly
    what the server said it can serve, and the person gets the answer."""
    turn = _turn(world, preset, preset=preset)
    refused, resent = [e for e in turn["sent"] if e["stream"]][:2]
    assert refused["max_tokens"] == LIFT and refused.get("refused")
    window, prompt = _stated(refused["refused"])
    assert window == WINDOW
    assert resent["max_tokens"] == window - prompt and floor <= resent["max_tokens"] < LIFT
    assert not resent.get("refused")
    assert resent["messages"] == refused["messages"] and resent["tools"] == refused["tools"]
    assert len([e for e in turn["sent"] if e["stream"]]) == 2
    assert turn["said"] == ANSWER and not _errors(turn)
    assert any(e.get("type") == "message_saved" for e in turn["events"])


def test_the_receipt_says_what_the_answer_was_generated_under(world, pantheon):
    """`P4-25`'s receipt records the turn's first request; when that request was
    refused and sent again, its `max_tokens` is the one the model answered. The
    run's id is read from the server's own database (no route hands it out),
    the receipt through its route."""
    import sqlite3

    client, _, _ = world
    turn = _turn(world, "brainstorm")
    resent = [e for e in turn["sent"] if e["stream"]][1]
    with sqlite3.connect(pantheon.data_dir / "app.db") as db:
        runs = {r for (r,) in db.execute(
            "SELECT run_id FROM events WHERE kind = 'run_config' AND session_id = ?",
            (turn["session"],))}
    assert len(runs) == 1, runs
    receipt = seed._ok(client.get(f"/api/diagnostics/receipt/{runs.pop()}"), "receipt")
    assert receipt["config"]["sampling"]["max_tokens"] == resent["max_tokens"]


def test_the_force_answer_salvage_is_sent_what_fits(world):
    """The other door a lifted length goes through: a turn going round in
    circles until the loop breaker forces an answer that still has no prose,
    whose one non-streaming synthesis call (`llm_call_async`) is lifted too.
    The turn's first round taught the server's window, so the salvage asks for
    what fits it and is not refused (`B1089`; before it, it was
    refused and sent again) — and the turn does not end on the canned apology.
    `llm_call_async`'s own resend is held by `/api/chat`
    (`test_the_chat_doors_are_asked_for_what_the_server_can_serve.py`) and by
    the door cases below."""
    turn = _turn(world, "circles")
    salvage = [e for e in turn["sent"] if not e["stream"] and not _side(e)]
    assert len(salvage) == 1, [(e["stream"], e["max_tokens"]) for e in turn["sent"]]
    first = turn["sent"][0]
    window, _prompt = _stated(first["refused"])
    assert 4096 < salvage[0]["max_tokens"] < window and not salvage[0].get("refused")
    assert any(e.get("type") == "loop_breaker_triggered" for e in turn["events"])
    assert "couldn't pull a clean answer together" not in turn["said"]


# ── what does not move ──────────────────────────────────────────────────────

def test_a_server_that_takes_the_number_is_asked_once(world):
    """A local server that does not hold a request to its window (llama.cpp,
    Ollama, LM Studio) is sent the lift, once, exactly as before."""
    turn = _turn(world, "accepts", endpoint="accepts")
    streamed = [e for e in turn["sent"] if e["stream"]]
    assert [e["max_tokens"] for e in streamed] == [LIFT]
    assert turn["said"] == ANSWER


def test_a_window_with_less_room_than_the_preset_is_asked_for_what_it_has(world):
    """`D-2026-10-02-01` §2, the owner's call: when what the server can serve is
    less than the preset's own number, the request is sent once more asking for
    exactly that — the preset stops being a floor in that one case. Measured
    before it (window 9,000, Brainstorm): refused at 1,000,000, not sent again,
    and the turn ended on the server's 400 with no reply."""
    turn = _turn(world, "small", endpoint="small")
    refused, resent = [e for e in turn["sent"] if e["stream"]][:2]
    assert refused["max_tokens"] == LIFT and refused.get("refused")
    window, prompt = _stated(refused["refused"])
    assert resent["max_tokens"] == window - prompt and 0 < resent["max_tokens"] < 4096
    assert not resent.get("refused") and resent["messages"] == refused["messages"]
    assert turn["said"] == ANSWER and not _errors(turn)


def test_a_typed_ceiling_is_still_the_most_it_asks(world):
    """`D-2026-10-01-04`: the operator's ceiling wins. One the window holds is
    sent once and never raised; one the window does not hold is talked down to
    what the server can serve, which is below it."""
    client, _, _ = world

    def type_ceiling(value):
        seed._ok(client.post("/api/auth/settings", json={"local_inference_max_tokens": value}),
                 "ceiling")

    try:
        type_ceiling(16_384)
        held = _turn(world, "typed")
        assert [e["max_tokens"] for e in held["sent"] if e["stream"]] == [16_384]
        assert held["said"] == ANSWER
        type_ceiling(WINDOW)
        talked_down = _turn(world, "typed")
        refused, resent = [e for e in talked_down["sent"] if e["stream"]][:2]
        assert refused["max_tokens"] == WINDOW and refused.get("refused")
        window, prompt = _stated(refused["refused"])
        assert resent["max_tokens"] == window - prompt < WINDOW
        assert talked_down["said"] == ANSWER
    finally:
        type_ceiling(LIFT)


# ── the rule, as the server words it ────────────────────────────────────────

NEW = ("'max_tokens' or 'max_completion_tokens' is too large: 1000000. This model's "
       "maximum context length is 32768 tokens and your request has 7838 input tokens "
       "(1000000 > 32768 - 7838).")
OLD = ("This model's maximum context length is 32768 tokens. However, you requested "
       "1007838 tokens (7838 in the messages, 1000000 in the completion). Please reduce "
       "the length of the messages or completion.")


@pytest.mark.parametrize("raw, sent, want", [
    (json.dumps({"error": {"message": NEW, "code": 400}}), LIFT, 24_930),   # v0.10.1, v0.11.0
    (json.dumps({"object": "error", "message": OLD, "code": 400}), LIFT, 24_930),  # v0.6.6, v0.8.5
    (NEW.replace("7838", "31598"), LIFT, 1_170),   # less room than any preset (§2)
    (NEW, 30_000, 24_930),              # an unlifted request is talked down too (§2)
    (NEW, 24_930, None),                # never asked for more than was sent
    ("max_tokens is too large: 1000000. This model supports at most 16384 completion "
     "tokens, whereas you provided 1000000.", LIFT, None),   # says no window
    ("This model's maximum context length is 32768 tokens. However, your request has "
     "40000 input tokens. Please reduce the length of the input messages.", LIFT, None),
])
def test_what_the_server_said_it_can_serve(raw, sent, want):
    assert llm_core.servable_max_tokens(400, raw, sent) == want
    assert llm_core.servable_max_tokens(500, raw, sent) is None


# ── who is sent again: a caller that passes `max_tokens_floor` ──────────────

class _Refusing:
    """The model's socket, for the two doors called directly: vLLM's refusal for
    anything above `room`, and an answer otherwise."""

    def __init__(self, room):
        self.room, self.asked = room, []

    def refusal(self, payload):
        asked = payload.get("max_tokens")
        self.asked.append(asked)
        if asked and asked > self.room:
            return (f"'max_tokens' or 'max_completion_tokens' is too large: {asked}. This "
                    f"model's maximum context length is {WINDOW} tokens and your request has "
                    f"{WINDOW - self.room} input tokens ({asked} > {WINDOW} - "
                    f"{WINDOW - self.room}).")
        return None


@pytest.fixture
def refusing(monkeypatch):
    from types import SimpleNamespace

    model = _Refusing(room=1_170)

    async def post(client, url, headers, json=None, **kwargs):
        said = model.refusal(json)
        if said:
            return SimpleNamespace(is_success=False, status_code=400, text=said, headers={})
        return SimpleNamespace(is_success=True, status_code=200, text="", headers={},
                               json=lambda: {"choices": [{"message": {"content": ANSWER}}]})

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

    monkeypatch.setattr(llm_core, "httpx_post_kimi_aware_async", post)
    monkeypatch.setattr(llm_core, "_get_http_client", lambda: SimpleNamespace(
        stream=lambda method, url, json=None, headers=None, **kw: _Stream(json)))
    monkeypatch.setattr(llm_core, "_is_host_dead", lambda url: False)
    monkeypatch.setattr(llm_core, "note_model_activity", lambda *a, **k: None)
    # What one case's server stated is not carried into the next (`B1089`).
    monkeypatch.setattr(llm_core, "_stated_windows", {})
    llm_core._response_cache.clear()
    yield model
    llm_core._response_cache.clear()


async def _call(door, **kwargs):
    url, msgs = "http://127.0.0.1:8000/v1", [{"role": "user", "content": "hi"}]
    if door == "llm_call_async":
        try:
            return await llm_core.llm_call_async(url, "vllm-model", msgs, max_retries=1, **kwargs)
        except Exception as error:   # the refusal, raised as an HTTPException
            return f"refused: {getattr(error, 'status_code', error)}"
    out = ""
    async for chunk in llm_core.stream_llm(url, "vllm-model", msgs, **kwargs):
        out += chunk
    return out


@pytest.mark.asyncio
@pytest.mark.parametrize("door", ["stream_llm", "llm_call_async"])
async def test_a_caller_that_passes_the_preset_is_sent_below_it(refusing, door):
    """The preset 4096 sent unlifted, a server with 1,170 left: sent again at
    1,170 (`D-2026-10-02-01` §2), and answered."""
    said = await _call(door, max_tokens=4096, max_tokens_floor=4096)
    assert refusing.asked == [4096, 1_170]
    assert ANSWER in said


@pytest.mark.asyncio
@pytest.mark.parametrize("door", ["stream_llm", "llm_call_async"])
async def test_a_caller_that_passes_nothing_is_sent_once(refusing, door):
    """Every caller that does not pass `max_tokens_floor` — a title, a memory
    pass, a background job — is refused exactly as before."""
    said = await _call(door, max_tokens=4096)
    assert refusing.asked == [4096]
    assert ANSWER not in said and "400" in said
