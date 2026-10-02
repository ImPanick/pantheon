# SPDX-License-Identifier: AGPL-3.0-or-later
"""w8-agent's B-NEW-4 — the force-answer salvage is sent the rounds' temperature.

When an Agent-mode run's forced, tool-free round still writes no prose, the
loop makes one non-streaming synthesis call over what the turn gathered (the
salvage, `src/agent_loop.py`'s `_force_answer` block). Every round asks
`pan_qwen_route_temperature` what its candidate is sent (`B935`): a
`pantheon-qwen3` finetune is held at 0.2 unless the person chose the number, and
a number the person chose is theirs on every candidate. The salvage asked
nothing and sent a fixed 0.3. **Measured before this** (`0e64d2b`), through the
real app against the showcase's scripted model under a `pantheon-qwen3` name:
with no preset the rounds were sent 0.2 and the salvage 0.3, past the cap; with
Brainstorm's 0.9 chosen, the rounds 0.9 and the salvage 0.3, over the choice
(a notes-shaped turn going round in circles until the loop breaker forced an
answer that still had no prose).

The salvage's 0.3 is its own default, so it now goes through the same rule: a
qwen candidate gets 0.2, a chosen number is the person's, and anything else
keeps 0.3 (`D-2026-08-26-06`: a default never overrides a choice).

`Law 20`: `capture.Server` boots this checkout's `app.py`; each turn goes
through `/api/chat_stream` into the real loop, wrapper and payload builders and
a real socket to `demo_model.DemoModel`, listed under the model's name.
"""
from __future__ import annotations

import contextlib
import json
import secrets
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "showcase"))

import demo_model  # noqa: E402
import seed  # noqa: E402

QWEN = "pantheon-qwen3-demo"
PLAN = json.dumps({"plan": "- [ ] list the stages"})
FENCED = "```update_plan\n" + PLAN + "\n```"
APOLOGY = "couldn't pull a clean answer together"
# A notes-shaped request: the one kind a `pantheon-qwen3` finetune is handed
# tools for in Agent mode (`_route_finetune_modes`' notes mode) — anything else
# takes its short-answer or document path and never reaches a tool round.
WORDS = {
    ("qwen", None): "Make a todo checklist for releasing the lock-free queue.",
    ("qwen", "brainstorm"): "Make a todo checklist for releasing the lock-free map.",
    ("other", None): "Make a todo checklist for releasing the lock-free stack.",
    ("other", "brainstorm"): "Make a todo checklist for releasing the lock-free set.",
}
# The same call every round until the loop breaker forces an answer, which the
# model writes as a call again and no prose: the salvage. The finetune is sent
# no tool schema (it is trained to write its calls), so the calls are written
# into the reply as fenced blocks (`fenced`) on an endpoint that does not
# declare tools, where Pantheon's parser runs them.
SCRIPT = [{"key": f"{family}-{preset}", "title": f"{family}-{preset}", "fenced": True, "turns": [{
    "user": words,
    "steps": [{"call": "update_plan", "args": {"plan": "- [ ] x"}, "say": FENCED}] * 12}]}
    for (family, preset), words in WORDS.items()]


@pytest.fixture(scope="module")
def pantheon(tmp_path_factory):
    import capture

    data = tmp_path_factory.mktemp("salvage-temperature") / "data"
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
    """A signed-in person and the scripted model on two loopback endpoints: one
    listing a `pantheon-qwen3` name, one listing its own."""
    import httpx

    client = httpx.Client(base_url=pantheon.base, timeout=180)
    seed.setup_admin(client, secrets.token_urlsafe(18))
    log: list = []
    with contextlib.ExitStack() as models:
        endpoints = {}
        for family, name in (("qwen", QWEN), ("other", demo_model.MODEL_ID)):
            model = models.enter_context(demo_model.DemoModel(
                log=log, conversations=SCRIPT, model_id=name))
            endpoints[family] = (seed._ok(client.post("/api/model-endpoints", data={
                "name": f"Demo model ({family})", "base_url": model.base_url,
                "supports_tools": "false", "require_models": "true"}), family)["id"], name)
        yield SimpleNamespace(client=client, endpoints=endpoints, log=log)
    client.close()


def _side(entry):
    """The chat's title, asked on the side (`demo_model._SIDE`)."""
    system = " ".join(str(m.get("content")) for m in entry["messages"] if m.get("role") == "system")
    return any(pattern.search(system) for pattern, _answer in demo_model._SIDE)


def _forced_turn(world, family, preset):
    """One Agent-mode turn that ends in the salvage. Returns the rounds' and the
    salvage's temperatures and what was said."""
    endpoint_id, model = world.endpoints[family]
    sess = seed._ok(world.client.post("/api/session", data={"endpoint_id": endpoint_id,
                                                            "model": model}), "chat")
    form = {"message": WORDS[(family, preset)], "session": sess.get("session_id") or sess.get("id"),
            "mode": "agent", "plan_mode": "false", "selected_model": model,
            "selected_endpoint_id": endpoint_id, "allow_bash": "false",
            "allow_web_search": "false"}
    if preset:
        form["preset_id"] = preset
    start = len(world.log)
    resp = world.client.post("/api/chat_stream", data=form)
    assert resp.status_code == 200, resp.text[:400]
    said = "".join(e["delta"] for e in seed._sse_events(resp.text) if isinstance(e.get("delta"), str))
    sent = [e for e in world.log[start:] if e["conv"] == f"{family}-{preset}" and not _side(e)]
    rounds = {e["temperature"] for e in sent if e["stream"]}
    salvage = [e["temperature"] for e in sent if not e["stream"]]
    assert len(salvage) == 1, [(e["stream"], e["temperature"]) for e in sent]
    assert APOLOGY not in said
    return rounds, salvage[0]


def test_a_qwen_candidate_s_salvage_is_held_at_its_cap(world):
    """The row's `Verify:`: a forced answer on a `pantheon-qwen3` candidate is
    sent ≤ 0.2 — what its rounds are sent."""
    rounds, salvage = _forced_turn(world, "qwen", None)
    assert rounds == {0.2} and salvage == 0.2


@pytest.mark.parametrize("family", ["qwen", "other"])
def test_a_temperature_the_person_chose_is_the_salvage_s_too(world, family):
    """Brainstorm's 0.9 is a choice (`explicit_sampling_params`): every round is
    sent it on any model, and so is the salvage."""
    rounds, salvage = _forced_turn(world, family, "brainstorm")
    assert rounds == {0.9} and salvage == 0.9


def test_where_nobody_chose_any_other_model_s_salvage_keeps_its_own_default(world):
    """No preset, not a qwen finetune: the rounds are sent the caller's 1.0 and
    the salvage its own 0.3, as before."""
    rounds, salvage = _forced_turn(world, "other", None)
    assert rounds == {1.0} and salvage == 0.3
