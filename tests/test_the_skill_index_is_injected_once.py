# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B60` — one skills index per request, and gates that actually gate.

The index is a catalogue of procedures the agent is told to consult. In agent
mode it was assembled **twice** — once by `chat_processor.build_context_preface`
and once by `agent_loop._build_base_prompt` — and both landed in the same
message array, because `agent_mode` is true only on the route whose `else`
branch calls `stream_agent_loop`.

A duplicated catalogue is the small half. The large half is that the two copies
were gated differently, and *between them every gate was defeated*:

  * `requires_toolsets` / `fallback_for_toolsets` — the loop's copy hides a
    procedure whose tools are switched off. The preface's passed
    `active_toolsets=None` and advertised it anyway.
  * the `skills_enabled` preference — honoured by the preface, ignored by the
    loop's index. **Turning skills off did not turn the index off.**
  * `incognito` and `allow_tool_preprocessing` — honoured by the preface and
    never plumbed into `stream_agent_loop` at all.
  * low signal — `_is_casual_low_signal` in the preface, `_intent.low_signal`
    in the loop. Two predicates, so each turn one of them was wrong.
  * `guide_only` — only the loop.

So the fix is not "delete one". It is one injection, at the site that already
gates on toolsets, taking a single `suppress_skills` the route computes from all
six. These tests measure the whole message array of one request, because that is
the only place the duplication was ever visible — each site on its own looked
correct, which is why it survived this long.
"""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import src.agent_loop as agent_loop
import src.constants as constants
from services.memory.skills import SkillsManager
from src.chat_processor import ChatProcessor


def _write_skill(root: Path, name: str, *, category="general", requires=""):
    d = root / category / name
    d.mkdir(parents=True, exist_ok=True)
    fm = ["---", f"name: {name}", "description: a test procedure", "version: 1.0.0",
          f"category: {category}", "tags: []"]
    if requires:
        fm.append(f"requires_toolsets: [{requires}]")
    fm += ["status: published", "confidence: 0.9", "source: learned",
           "created: 2026-01-01T00:00:00Z", "---", "",
           "## When to Use", "- a test", "", "## Procedure", "1. do it", ""]
    (d / "SKILL.md").write_text("\n".join(fm), encoding="utf-8")


REQUEST = ("Please rotate and prune the application log files on the server, "
           "then summarise what you removed.")


@pytest.fixture
def skills(tmp_path, monkeypatch):
    root = tmp_path / "skills"
    _write_skill(root, "tidy-logs", category="ops")
    _write_skill(root, "needs-bash", category="ops", requires="bash")
    monkeypatch.setattr(constants, "DATA_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(agent_loop, "_cached_base_prompt", None, raising=False)
    monkeypatch.setattr(agent_loop, "_cached_base_prompt_key", None, raising=False)
    return SkillsManager(str(tmp_path))


def _preface(skills_manager, *, agent_mode=True, incognito=False):
    """The messages the chat preface contributes, from the real builder.

    Constructed with `__new__` and only the attributes this method touches:
    `ChatProcessor.__init__` reaches for a database, and the memory / RAG / web
    passes are turned off by argument, so nothing else is consulted. A
    hand-written stand-in for the block would be a test of my own string.
    """
    cp = ChatProcessor.__new__(ChatProcessor)
    cp.skills_manager = skills_manager
    for attr in ("memory_manager", "rag", "web_search", "document_manager"):
        setattr(cp, attr, None)
    sess = SimpleNamespace(messages=[], model="m", id="s")
    preface, _, _ = ChatProcessor.build_context_preface(
        cp, REQUEST, sess, use_web=False, use_rag=False, use_memory=False,
        agent_mode=agent_mode, incognito=incognito, owner=None,
    )
    return preface


def _request_messages(monkeypatch, preface, **loop_kwargs):
    """Every message one agent request actually sends, preface included."""
    monkeypatch.setattr(agent_loop, "get_setting", lambda k, d=None: d, raising=False)
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: None, raising=False)
    monkeypatch.setattr(agent_loop, "estimate_tokens", lambda *a, **k: 10, raising=False)
    monkeypatch.setattr(agent_loop, "blocked_tools_for_owner", lambda o: set(),
                        raising=False)
    seen = {}

    async def capture(*a, **k):
        factory = k.get("candidate_request_factory")
        if factory is not None:
            req = await factory(0, "http://local.test/v1", "small-local-model", None)
            seen["messages"] = (req or {}).get("messages") or []
        yield f"data: {json.dumps({'delta': 'Done.'})}\n\n"
        yield "data: [DONE]\n\n"

    async def fake_execute(block, *a, **k):
        return (block.tool_type, {"output": "ok", "exit_code": 0})

    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", capture, raising=False)
    monkeypatch.setattr(agent_loop, "execute_tool_block", fake_execute, raising=False)

    messages = list(preface) + [{"role": "user", "content": REQUEST}]

    async def drain():
        async for _ in agent_loop.stream_agent_loop(
            "http://local.test/v1", "small-local-model", messages,
            max_rounds=1, relevant_tools={"bash"}, **loop_kwargs,
        ):
            pass

    asyncio.run(drain())
    return seen.get("messages") or []


def _index_blocks(messages):
    return [m for m in messages
            if "Available skills" in str(m.get("content", ""))]


def _skill_messages(messages):
    """Every message the skills path contributes — the index *and* the matched
    procedures, which share one wrapper and must share one suppression."""
    return [m for m in messages
            if (m.get("metadata") or {}).get("source") == "skills"]


def test_one_request_carries_one_skills_index(skills, monkeypatch):
    # The headline. Two catalogues of the same procedures, in one prompt, every
    # agent turn — and neither site could see it, because each one looked
    # correct on its own.
    messages = _request_messages(monkeypatch, _preface(skills))
    blocks = _index_blocks(messages)
    assert len(blocks) == 1, (
        f"{len(blocks)} skills indexes in one request: "
        + " || ".join(str(b.get("content", ""))[:90] for b in blocks)
    )


def test_the_surviving_index_is_the_one_that_gates_on_toolsets(skills, monkeypatch):
    # `needs-bash` declares `requires_toolsets: [bash]`. With bash disabled the
    # agent cannot run it, and advertising it is an instruction to attempt
    # something that is switched off.
    messages = _request_messages(monkeypatch, _preface(skills),
                                 disabled_tools={"bash"})
    blob = json.dumps(messages)
    assert "tidy-logs" in blob, "the ungated procedure vanished with the gated one"
    assert "needs-bash" not in blob, (
        "a procedure whose required toolset is off is still being advertised"
    )


def test_the_suppression_the_route_computes_actually_suppresses(skills, monkeypatch):
    # The flag exists so the four conditions only the route knows can reach the
    # one site that assembles the index. None of them could before: whichever
    # copy honoured a condition, the other shipped anyway.
    messages = _request_messages(monkeypatch, _preface(skills),
                                 suppress_skills=True)
    assert _index_blocks(messages) == []


def test_suppression_covers_the_matched_procedures_as_well_as_the_catalogue(
        skills, monkeypatch):
    # The index and the matched skills ride one wrapper. A suppression that
    # stopped the catalogue and left the procedures would be the same defect
    # one level down — half a gate is what `B60` was.
    messages = _request_messages(monkeypatch, _preface(skills),
                                 suppress_skills=True)
    assert _skill_messages(messages) == []


def test_the_loop_keeps_its_own_low_signal_read(skills, monkeypatch):
    # `suppress_skills` carries what only the route knows. The loop's own
    # intent read is the other half, and dropping it would put a catalogue in
    # front of a model answering "do the thing".
    monkeypatch.setattr(agent_loop, "get_setting", lambda k, d=None: d, raising=False)
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: None, raising=False)
    monkeypatch.setattr(agent_loop, "estimate_tokens", lambda *a, **k: 10, raising=False)
    monkeypatch.setattr(agent_loop, "blocked_tools_for_owner", lambda o: set(),
                        raising=False)
    seen = {}

    async def capture(*a, **k):
        factory = k.get("candidate_request_factory")
        if factory is not None:
            req = await factory(0, "http://local.test/v1", "small-local-model", None)
            seen["messages"] = (req or {}).get("messages") or []
        yield f"data: {json.dumps({'delta': 'Done.'})}\n\n"
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", capture, raising=False)

    async def drain():
        async for _ in agent_loop.stream_agent_loop(
            "http://local.test/v1", "small-local-model",
            [{"role": "user", "content": "do the thing"}],
            max_rounds=1, relevant_tools={"bash"}, suppress_skills=False,
        ):
            pass

    asyncio.run(drain())
    assert seen.get("messages"), "no request was built, so this asserts nothing"
    assert _skill_messages(seen["messages"]) == []


@pytest.mark.parametrize("kwargs, expected, why", [
    (dict(incognito=False, uprefs={}, allow_tool_preprocessing=True,
          casual_low_signal=False), True, "the ordinary turn"),
    (dict(incognito=True, uprefs={}, allow_tool_preprocessing=True,
          casual_low_signal=False), False, "incognito never reached the loop at all"),
    (dict(incognito=False, uprefs={"skills_enabled": False},
          allow_tool_preprocessing=True, casual_low_signal=False), False,
     "the preference the loop's copy ignored"),
    (dict(incognito=False, uprefs={}, allow_tool_preprocessing=False,
          casual_low_signal=False), False, "a path that must not retrieve at all"),
    (dict(incognito=False, uprefs={}, allow_tool_preprocessing=True,
          casual_low_signal=True), False, "a greeting pulls no catalogue"),
    (dict(incognito=False, uprefs={"skills_enabled": True},
          allow_tool_preprocessing=True, casual_low_signal=False), True,
     "the preference set on explicitly"),
])
def test_each_ground_the_route_owns_is_a_ground(kwargs, expected, why):
    # The four conditions, named and executable. They were four lines inside a
    # 200-line context builder, gating a copy of the index that another copy
    # shipped regardless — so each of them was, in effect, off.
    from routes.chat_helpers import skills_may_ship
    assert skills_may_ship(**kwargs) is expected, why


def test_the_route_hands_that_decision_to_the_only_site_left(skills):
    # The two halves have to be connected or the extraction is decoration.
    route = (Path(__file__).resolve().parent.parent
             / "routes" / "chat_routes.py").read_text(encoding="utf-8")
    assert "suppress_skills=not ctx.skills_enabled" in route
    from routes.chat_helpers import ChatContext
    assert "skills_enabled" in ChatContext.__dataclass_fields__
    # …and the context is built from the decision rather than from a constant.
    # There is no seam to execute here — `build_chat_context` wants a request
    # object, a handler and a processor — so this reads the one line that
    # connects them, and says so rather than pretending otherwise.
    helpers = (Path(__file__).resolve().parent.parent
               / "routes" / "chat_helpers.py").read_text(encoding="utf-8")
    assert "skills_enabled=skills_enabled," in helpers
    assert "skills_enabled = skills_may_ship(" in helpers


def test_the_preface_no_longer_assembles_an_index_of_its_own(skills):
    # Stated directly as well as measured, because this is the subtraction: the
    # preface's copy is gone, and every gate it uniquely honoured now reaches
    # the surviving one through `suppress_skills`.
    preface = _preface(skills)
    assert _index_blocks(preface) == []


def test_the_loop_still_says_what_it_injected(skills, monkeypatch):
    # `P4-16` must keep working across this fix — the report now has one source
    # instead of two, and that is the only difference.
    monkeypatch.setattr(agent_loop, "get_setting", lambda k, d=None: d, raising=False)
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: None, raising=False)
    monkeypatch.setattr(agent_loop, "estimate_tokens", lambda *a, **k: 10, raising=False)
    monkeypatch.setattr(agent_loop, "blocked_tools_for_owner", lambda o: set(),
                        raising=False)

    async def fake_stream(*a, **k):
        yield f"data: {json.dumps({'delta': 'Done.'})}\n\n"
        yield "data: [DONE]\n\n"

    async def fake_execute(block, *a, **k):
        return (block.tool_type, {"output": "ok", "exit_code": 0})

    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", fake_stream, raising=False)
    monkeypatch.setattr(agent_loop, "execute_tool_block", fake_execute, raising=False)

    async def drain():
        return [c async for c in agent_loop.stream_agent_loop(
            "http://local.test/v1", "small-local-model",
            [{"role": "user", "content": REQUEST}],
            max_rounds=1, relevant_tools={"bash"},
        )]

    events = []
    for chunk in asyncio.run(drain()):
        if chunk.startswith("data: ") and not chunk.startswith("data: [DONE]"):
            try:
                events.append(json.loads(chunk[6:]))
            except json.JSONDecodeError:
                pass
    reported = [e for e in events if e.get("type") == "skills_injected"]
    assert reported, "the report stopped working"
    names = {s["name"] for s in reported[0]["data"]}
    assert "tidy-logs" in names
    assert all(s["via"] == ["agent"] for s in reported[0]["data"]), (
        "the report still claims a site that no longer injects anything"
    )
