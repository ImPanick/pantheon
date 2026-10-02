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
servable_max_tokens`) — never above what was asked, never below the preset's own
number, and never at all to a server that took the number.

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


@pytest.fixture(scope="module")
def world(pantheon):
    """A signed-in person and the scripted model on three loopback endpoints:
    served as vLLM serves a 32,768 window, as vLLM serves one too small for the
    preset, and as a server that takes any length."""
    import httpx

    client = httpx.Client(base_url=pantheon.base, timeout=180)
    seed.setup_admin(client, secrets.token_urlsafe(18))
    log: list = []
    with demo_model.DemoModel(log=log, conversations=SCRIPT, max_model_len=WINDOW) as vllm, \
            demo_model.DemoModel(log=log, conversations=SCRIPT, max_model_len=9_000) as small, \
            demo_model.DemoModel(log=log, conversations=SCRIPT) as accepts:
        endpoints = {}
        for name, model in (("vllm", vllm), ("small", small), ("accepts", accepts)):
            out = seed._ok(client.post("/api/model-endpoints", data={
                "name": f"Demo model ({name})", "base_url": model.base_url,
                "supports_tools": "true", "require_models": "true"}), name)
            endpoints[name] = out["id"]
        yield client, endpoints, log
    client.close()


def _turn(world, key, endpoint="vllm", preset="brainstorm"):
    """One Agent-mode turn. Returns the requests the model was sent for it (in
    order), the events, the saved reply and the run's id."""
    client, endpoints, log = world
    sess = seed._ok(client.post("/api/session", data={"endpoint_id": endpoints[endpoint],
                                                      "model": seed.DEMO_MODEL_ID}), "chat")
    form = {"message": WORDS[key], "session": sess.get("session_id") or sess.get("id"),
            "mode": "agent", "plan_mode": "false", "selected_model": seed.DEMO_MODEL_ID,
            "selected_endpoint_id": endpoints[endpoint], "allow_bash": "false",
            "allow_web_search": "false", "preset_id": preset}
    start = len(log)
    resp = client.post("/api/chat_stream", data=form)
    assert resp.status_code == 200, resp.text[:400]
    events = list(seed._sse_events(resp.text))
    sent = [e for e in log[start:] if e["conv"] == key]
    said = "".join(e["delta"] for e in events if isinstance(e.get("delta"), str))
    return {"sent": sent, "events": events, "said": said, "session": form["session"]}


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


def test_the_force_answer_salvage_is_sent_again_too(world):
    """The other door a lifted length goes through: a turn going round in circles
    until the loop breaker forces an answer that still has no prose, whose
    one non-streaming synthesis call (`llm_call_async`) is refused and sent
    again the same way — so the turn does not end on the canned apology."""
    turn = _turn(world, "circles")
    refused = [e for e in turn["sent"] if not e["stream"] and e.get("refused")]
    assert len(refused) == 1 and refused[0]["max_tokens"] == LIFT, turn["sent"]
    window, prompt = _stated(refused[0]["refused"])
    after = turn["sent"][turn["sent"].index(refused[0]) + 1]
    assert not after["stream"] and after["max_tokens"] == window - prompt
    assert not after.get("refused")
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


def test_a_window_with_less_room_than_the_preset_is_not_talked_below_it(world):
    """The preset is the floor (`D-2026-09-08-02`): when what the server can
    serve is less than the preset's own number, the request is not sent again
    asking for less — the turn fails as it did, on the server's own words.
    Going below the preset is a call neither ruling makes."""
    turn = _turn(world, "small", endpoint="small")
    streamed = [e for e in turn["sent"] if e["stream"]]
    assert [e["max_tokens"] for e in streamed] == [LIFT]
    window, prompt = _stated(streamed[0]["refused"])
    assert 0 < window - prompt < 4096
    assert any("is too large" in json.dumps(e) for e in _errors(turn))


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


@pytest.mark.parametrize("raw, sent, floor, want", [
    (json.dumps({"error": {"message": NEW, "code": 400}}), LIFT, 4096, 24_930),   # v0.10.1, v0.11.0
    (json.dumps({"object": "error", "message": OLD, "code": 400}), LIFT, 4096, 24_930),  # v0.6.6, v0.8.5
    (NEW, LIFT, 30_000, None),          # less room than the preset: not talked below it
    (NEW, 4096, 4096, None),            # unlifted: never sent again
    (NEW, LIFT, None, None),            # a caller that gave no floor: as before
    ("max_tokens is too large: 1000000. This model supports at most 16384 completion "
     "tokens, whereas you provided 1000000.", LIFT, 4096, None),   # says no window
    ("This model's maximum context length is 32768 tokens. However, your request has "
     "40000 input tokens. Please reduce the length of the input messages.", LIFT, 4096, None),
])
def test_what_the_server_said_it_can_serve(raw, sent, floor, want):
    assert llm_core.servable_max_tokens(400, raw, sent, floor) == want
    assert llm_core.servable_max_tokens(500, raw, sent, floor) is None
