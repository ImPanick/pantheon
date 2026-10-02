# SPDX-License-Identifier: AGPL-3.0-or-later
"""w8-agent's B-NEW-5 — the force-answer salvage is shaped and trimmed as a round is.

When an Agent-mode run's forced, tool-free round still writes no prose, the
loop makes one non-streaming synthesis call over what the turn gathered (the
salvage, `src/agent_loop.py`'s `_force_answer` block). Every round's request is
built per candidate (`_candidate_request`): the tool pictures as that model can
take them (`tool_result_images.for_model`, `P20-04`), then trimmed to that
route's window (`_trim_route_request_messages`). The salvage was sent
`list(messages)` and its instruction — the whole transcript, pictures and all.

**Measured before this** (`0e64d2b`), through the real app against the
showcase's scripted model served as vLLM serves a 20,000 window: after a chat
whose earlier reply ran to 58,036 characters, an Agent turn going round in
circles had every round trimmed to the window (at most 17,737 characters, the
long reply left out), and its salvage was sent 13 messages, 80,975 characters —
refused outright (`your request has 20244 input tokens`), which no length can
fix, so the turn ended on the canned apology. The salvage now goes through the
same two steps, for the candidate it is sent to.

`Law 20`: the window cases go through the real app (`capture.Server`,
`/api/chat_stream`, the real loop, wrappers and payload builders, a real socket
to `demo_model.DemoModel`). The picture cases need a tool that returns one,
which this world has none of, so they run the real chat route, agent loop and
fallback wrapper in-process (`B1050`'s harness) with a tool picture already in
the conversation, faking only the sockets — the model's, and the endpoint's own
answer to "can this model see" (`endpoint_supports_vision`), so its name decides.
"""
from __future__ import annotations

import contextlib
import json
import secrets
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import routes.chat_routes as chat_routes
import src.agent_loop as agent_loop
import src.chat_helpers as chat_helpers
import src.llm_core as llm_core
import src.model_context as model_context
import src.settings as settings
from src import tool_result_images
from test_foreground_model_routing import _RouteRequest, _chat_stream_endpoint  # noqa: E402
from test_pr6020_rebase_regressions import _install_route_probe  # noqa: E402
from test_the_operator_s_token_ceiling_wins_on_every_door import (  # noqa: E402,F401
    BRAINSTORM,
    LOCAL,
    OTHER,
    REAL_GET_SETTING,
    TASK,
    ceiling,          # a fixture
)
from test_the_salvage_asks_the_model_that_answered import (  # noqa: E402,F401
    SYNTH,
    chain,            # a fixture: the model's socket, scripted
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "showcase"))

import demo_model  # noqa: E402
import seed  # noqa: E402

WINDOW = 20_000
APOLOGY = "couldn't pull a clean answer together"
INSTRUCTION = "Using ONLY the information already gathered above"
LONG = "\n\n".join(f"Section {i}. " + "The journal appends, fsyncs, then publishes. " * 40
                   for i in range(32))
PLAN = json.dumps({"plan": "\n".join(f"- [ ] stage {i}: " + "y" * 90 for i in range(30))})
FENCED = "```update_plan\n" + PLAN + "\n```"
WORDS = {
    "appendix": "Write out the long appendix for the journal.",
    "long": "Write a detailed design document for a journal's commit path.",
    "short": "Write a detailed design document for a journal's checkpoint.",
}
CIRCLES = [{"call": "update_plan", "args": PLAN, "say": FENCED}] * 12
SCRIPT = [
    {"key": "long", "title": "long", "turns": [
        {"user": WORDS["appendix"], "steps": [{"say": LONG}]},
        {"user": WORDS["long"], "steps": CIRCLES}]},
    {"key": "short", "title": "short", "turns": [{"user": WORDS["short"], "steps": CIRCLES}]},
]


# ── through the real app ────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def pantheon(tmp_path_factory):
    import capture

    data = tmp_path_factory.mktemp("salvage-trim") / "data"
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
    """A signed-in person; `endpoint()` serves the scripted model as vLLM serves
    a 20,000 window, on a loopback port of its own."""
    import httpx

    client = httpx.Client(base_url=pantheon.base, timeout=180)
    seed.setup_admin(client, secrets.token_urlsafe(18))
    log: list = []
    with contextlib.ExitStack() as models:
        def endpoint():
            model = models.enter_context(demo_model.DemoModel(
                log=log, conversations=SCRIPT, max_model_len=WINDOW))
            return seed._ok(client.post("/api/model-endpoints", data={
                "name": f"Demo model ({model.port})", "base_url": model.base_url,
                "supports_tools": "true", "require_models": "true"}), "endpoint")["id"]

        yield SimpleNamespace(client=client, endpoint=endpoint, log=log)
    client.close()


def _side(entry):
    """The chat's title and the post-turn passes (`demo_model._SIDE`)."""
    system = " ".join(str(m.get("content")) for m in entry["messages"] if m.get("role") == "system")
    return any(pattern.search(system) for pattern, _answer in demo_model._SIDE)


def _send(world, endpoint_id, session, words, mode):
    form = {"message": words, "session": session, "mode": mode, "plan_mode": "false",
            "selected_model": seed.DEMO_MODEL_ID, "selected_endpoint_id": endpoint_id,
            "allow_bash": "false", "allow_web_search": "false", "preset_id": "brainstorm"}
    resp = world.client.post("/api/chat_stream", data=form)
    assert resp.status_code == 200, resp.text[:400]
    return "".join(e["delta"] for e in seed._sse_events(resp.text) if isinstance(e.get("delta"), str))


def _forced_turn(world, key, *, after_long_reply):
    """An Agent-mode turn going round in circles until the loop breaker forces
    an answer with no prose — after a long earlier reply in the same chat, or
    not. Returns its streamed rounds, its salvage and what was said."""
    endpoint_id = world.endpoint()
    sess = seed._ok(world.client.post("/api/session", data={
        "endpoint_id": endpoint_id, "model": seed.DEMO_MODEL_ID}), "chat")
    session = sess.get("session_id") or sess.get("id")
    if after_long_reply:
        assert len(_send(world, endpoint_id, session, WORDS["appendix"], "chat")) == len(LONG)
    start = len(world.log)
    said = _send(world, endpoint_id, session, WORDS[key], "agent")
    sent = [e for e in world.log[start:] if e["conv"] == key and not _side(e)]
    rounds = [e for e in sent if e["stream"]]
    salvage = [e for e in sent if not e["stream"]]
    assert len(salvage) == 1, [(e["stream"], len(e["messages"])) for e in sent]
    return rounds, salvage[0], said


def _text(message):
    content = message.get("content")
    return content if isinstance(content, str) else json.dumps(content)


def test_a_forced_answer_after_a_long_chat_is_sent_a_request_inside_the_window(world):
    """The row's `Verify:`. The rounds are trimmed to the window and leave the
    long earlier reply out; the salvage is trimmed the same way — the person's
    words and its instruction kept, the long reply left out — and the server
    answers it, so the turn ends on the synthesis, not the apology."""
    rounds, salvage, said = _forced_turn(world, "long", after_long_reply=True)
    assert rounds and all(LONG not in json.dumps(e["messages"]) for e in rounds)
    assert not salvage.get("refused"), salvage.get("refused")
    assert LONG[:200] not in json.dumps(salvage["messages"])
    assert WORDS["long"] in json.dumps(salvage["messages"])
    assert _text(salvage["messages"][-1]).startswith(INSTRUCTION)
    assert APOLOGY not in said


def test_with_nothing_to_trim_the_salvage_is_the_forced_round_and_its_instruction(world):
    """What does not move: a short turn's salvage is exactly the forced round's
    request with the instruction after it — every message the turn holds, as
    before, built by the same two steps."""
    rounds, salvage, said = _forced_turn(world, "short", after_long_reply=False)
    forced = rounds[-1]
    assert not forced["tools"] and not salvage.get("refused")
    assert salvage["messages"][:-1] == forced["messages"]
    assert _text(salvage["messages"][-1]).startswith(INSTRUCTION)
    assert APOLOGY not in said


# ── the pictures: the real route, loop and wrapper, sockets faked ───────────

def _picture_message():
    """A tool picture as the loop puts one in front of the model
    (`tool_result_images.images_message`): a screenshot from `computer`."""
    import base64

    png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64).decode()
    return tool_result_images.images_message([{
        "tool_name": "computer", "content": "{}",
        "result": {"images": [{"data": png, "mimeType": "image/png"}]}}])


async def _forced_turn_with_a_picture(chain, monkeypatch, model):
    """One Agent-mode turn through the real chat route, loop, fallback wrapper
    and payload builders, with a tool picture in the conversation, going round
    in circles until the loop breaker forces an answer. Returns what was sent."""
    monkeypatch.setattr(model_context, "_query_context_length", lambda url, m: (32_768, True))
    monkeypatch.setattr(model_context, "_context_cache", {})
    # The endpoint's own answer to "can this model see" is a request to it.
    monkeypatch.setattr(chat_helpers, "endpoint_supports_vision", lambda url, m: None)
    messages = list(TASK) + [_picture_message()]
    _install_route_probe(monkeypatch)
    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", llm_core.stream_llm_with_fallback)
    captured: dict = {}
    endpoint = _chat_stream_endpoint(monkeypatch, "agent", captured, model=model,
                                     endpoint_url=LOCAL, capture_completion=True,
                                     context_overrides={"preset": BRAINSTORM, "messages": messages,
                                                        "route_messages": messages})
    monkeypatch.setattr(settings, "get_setting", REAL_GET_SETTING)
    monkeypatch.setattr(chat_routes, "stream_agent_loop", agent_loop.stream_agent_loop)
    response = await endpoint(_RouteRequest("agent"))
    text = ""
    async for chunk in response.body_iterator:
        text += chunk if isinstance(chunk, str) else chunk.decode()
    assert '"type": "loop_breaker_triggered"' in text and SYNTH in text
    return chain.sent


def _tool_rounds(sent):
    """The rounds built per candidate. Round 1's request is built before the
    loop from the conversation as it arrived (`_initial_route_request_messages`),
    where a real turn never has a tool picture — pictures come from tool rounds,
    and a resumed turn is built per round (`B1069`) — so only this setup, which
    puts one there, would find it unshaped."""
    return [p for kind, _h, p, _hd in sent if kind == "stream"][1:]


def _pictures(payload):
    return sum(1 for m in payload["messages"] if isinstance(m.get("content"), list)
               for p in m["content"] if isinstance(p, dict) and p.get("type") == "image_url")


def _says_it_cannot_see(payload):
    return any(tool_result_images.NO_VISION_SENTENCE in _text(m) for m in payload["messages"])


@pytest.mark.asyncio
async def test_a_model_that_cannot_see_is_not_sent_the_pictures(chain, monkeypatch, ceiling):
    """The rounds put a tool picture into words for a model that cannot see; so
    does its salvage, which used to send the picture itself."""
    ceiling(None)
    sent = await _forced_turn_with_a_picture(chain, monkeypatch, OTHER)
    rounds = _tool_rounds(sent)
    (salvage,) = [p for kind, _h, p, _hd in sent if kind == "post"]
    assert rounds and all(_pictures(p) == 0 and _says_it_cannot_see(p) for p in rounds)
    assert _pictures(salvage) == 0 and _says_it_cannot_see(salvage)


@pytest.mark.asyncio
async def test_a_model_that_can_see_is_sent_them(chain, monkeypatch, ceiling):
    """What does not move: a model that can see gets the picture on every
    round, and in its salvage."""
    ceiling(None)
    sent = await _forced_turn_with_a_picture(chain, monkeypatch, "qwen2.5-vl-7b-instruct")
    rounds = _tool_rounds(sent)
    (salvage,) = [p for kind, _h, p, _hd in sent if kind == "post"]
    assert rounds and all(_pictures(p) == 1 for p in rounds)
    assert _pictures(salvage) == 1 and not _says_it_cannot_see(salvage)
