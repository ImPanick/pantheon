# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1327` and the two stalls measuring it found. `D-2026-10-09-01` §3.

The owner's ruling, verbatim: *"Agents should agent."* §3 spells it out — the
wording that pushes the model to do the work and report is the one that ships,
and *an agent that asks a question it could have answered, or stops to check
something it was told to do, is the defect*.

Measured on `a5ee5f8` before any of this, with the product booted on port 8792
against a recording OpenAI-compatible model and a real stdio MCP server (the
recipe is `/work/notes/fx6-tools.md`), five tasks that each need several steps:
**0 of 5 finished the work.** Four ended with the model asking whether to take
a step it had already been told to take — *"Should I read the other two files
as well?"*, *"Would you like me to go ahead and look up the release date
too?"*, *"Do you want me to fetch the full page?"* — and one ended with a
checklist and *"Let me know if you'd like me to run it."* Not one of them hit a
round cap, a tool budget, the loop-breaker or the force-answer salvage: the
turns gave up with 45 of 50 rounds unused.

Three things ship, and this file drives each of them:

* **the acting rules** (`_ACT_RULES`), one definition interpolated into both
  `_AGENT_RULES` and `_API_AGENT_RULES`, asserted through the real
  `_assemble_prompt` on both paths — the shipped text, not a grep (`Law 20`);
* **the question-instead-of-work supervisor**, the mirror of the
  intent-without-action supervisor: a round that ends by offering to take a
  step, with no call, buys one push;
* **`ask_user` before anything was looked at**: the tool keeps its
  turn-ending contract, and the first question on a turn where nothing has run
  yet buys one round of looking.

`ask_user` is not removed and is not weakened at a real fork: three cases below
hold the card shipping after a tool has run, after a second ask, and on a turn
with no other tool.
"""

from __future__ import annotations

import asyncio
import json

import pytest

import src.agent_loop as al
from src.agent_loop import TOOL_SECTIONS


# ── the prompt, built the way the product builds it ───────────────────────

ALL_TOOLS = set(TOOL_SECTIONS.keys())


def _fenced_prompt(tools=None):
    return al._assemble_prompt(ALL_TOOLS if tools is None else set(tools), compact=False)


def _native_prompt(tools=None):
    return al._assemble_prompt(ALL_TOOLS if tools is None else set(tools), compact=True)


#: The three condensed lines `B1309` left in place and `D-2026-10-09-01` §3
#: replaced. One definition of each rule is left (`Law 7`), so these must be
#: gone from both assembled prompts rather than living beside the new wording.
CONDENSED = (
    "- After a tool succeeds, do not second-guess it; reply with one short confirmation",
    "- After a tool fails, retry with a concrete fix or state what is blocking you.",
    "- Finish only when the user's concrete request is actually done, or clearly state",
)


@pytest.mark.parametrize("build", [_fenced_prompt, _native_prompt])
def test_the_acting_rules_ship_on_both_paths(build):
    prompt = build()
    assert "BIAS TOWARD ACTION" in prompt
    assert "DO NOT HAND THE WORK BACK AS A QUESTION" in prompt
    assert "YOU DECLARE WHEN THE JOB IS DONE" in prompt
    assert "three ways to end a turn" in prompt


@pytest.mark.parametrize("build", [_fenced_prompt, _native_prompt])
def test_a_turn_ends_by_having_done_the_work(build):
    """Where the two wordings disagreed, the brief named the arm to keep: DONE
    means the concrete thing exists or succeeded, checked before declaring it."""
    prompt = build()
    assert "(1) DONE" in prompt
    assert "actually exists or succeeded" in prompt
    assert "(2) BLOCKED" in prompt
    assert "single most useful next step" in prompt
    assert "asking a question you could have answered" in prompt


@pytest.mark.parametrize("build", [_fenced_prompt, _native_prompt])
@pytest.mark.parametrize("line", CONDENSED)
def test_the_condensed_wording_does_not_ship_beside_the_chosen_one(build, line):
    assert line not in build()


@pytest.mark.parametrize("build", [_fenced_prompt, _native_prompt])
def test_the_prompt_does_not_promise_plenty_of_rounds(build):
    """Dropped from the dead copy's wording, with the measurement: a person can
    set `agent_max_rounds` to 1 (`AGENT_MAX_ROUNDS_RANGE = (1, 200)`), so
    *"you have plenty of rounds"* is a claim the install can falsify."""
    from src.run_limits import AGENT_MAX_ROUNDS_RANGE

    assert AGENT_MAX_ROUNDS_RANGE[0] == 1
    assert "plenty of rounds" not in build()


def test_the_fork_line_goes_when_ask_user_is_not_offered():
    """The rule that names `ask_user` is pruned on a turn without it; the rule
    that names no tool is not. `prune_rules_to_available_tools`' own shape."""
    without = _fenced_prompt(ALL_TOOLS - {"ask_user"})
    assert "At a real fork, ask with `ask_user`" not in without
    assert "DO NOT HAND THE WORK BACK AS A QUESTION" in without
    with_it = _fenced_prompt(ALL_TOOLS)
    assert "At a real fork, ask with `ask_user`" in with_it


def _native_schema(name):
    from src.tool_schemas import FUNCTION_TOOL_SCHEMAS

    for entry in FUNCTION_TOOL_SCHEMAS:
        function = entry.get("function") or {}
        if function.get("name") == name:
            return function.get("description") or ""
    raise AssertionError(f"{name} has no function schema")


def test_ask_user_is_told_to_look_first_on_both_paths():
    assert "LOOK BEFORE YOU ASK" in TOOL_SECTIONS["ask_user"]
    assert "LOOK BEFORE YOU ASK" in _native_schema("ask_user")
    for text in (TOOL_SECTIONS["ask_user"], _native_schema("ask_user")):
        assert "already asked for" in text


def test_update_plan_says_writing_the_plan_is_not_doing_the_work():
    for text in (TOOL_SECTIONS["update_plan"], _native_schema("update_plan")):
        assert "not doing the work" in text


# ── the loop, driven ──────────────────────────────────────────────────────


def _patch_common(monkeypatch):
    monkeypatch.setattr(al, "get_setting", lambda key, default=None: default, raising=False)
    monkeypatch.setattr(al, "get_mcp_manager", lambda: None, raising=False)
    monkeypatch.setattr(al, "estimate_tokens", lambda *a, **k: 10, raising=False)


def _run(monkeypatch, round_texts, *, results=None, max_rounds=6,
         relevant_tools=None, plan_mode=False, user="read the three files and tell me which defines it"):
    """Drive the real loop. `round_texts` is what the model writes per round
    (the last entry repeats); `results` maps a tool name to the dict
    `execute_tool_block` returns for it."""
    seen_requests: list = []
    texts = list(round_texts)

    async def _fake_stream(_candidates, messages, **kwargs):
        seen_requests.append([
            {"role": m.get("role"), "content": str(m.get("content") or "")}
            for m in messages
        ])
        text = texts[len(seen_requests) - 1] if len(seen_requests) <= len(texts) else texts[-1]
        yield f'data: {json.dumps({"delta": text})}\n\n'
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(al, "stream_llm_with_fallback", _fake_stream, raising=False)

    async def _fake_exec(block, *a, **k):
        payload = (results or {}).get(block.tool_type, {"output": "ok", "exit_code": 0})
        return (block.tool_type, dict(payload))

    monkeypatch.setattr(al, "execute_tool_block", _fake_exec, raising=False)

    gen = al.stream_agent_loop(
        "http://x/v1", "m",
        [{"role": "user", "content": user}],
        max_rounds=max_rounds,
        relevant_tools=set(relevant_tools) if relevant_tools else {"read_file"},
        plan_mode=plan_mode,
    )

    async def _drain():
        return [chunk async for chunk in gen]

    chunks = asyncio.run(_drain())
    events = []
    for chunk in chunks:
        if chunk.startswith("data: ") and not chunk.startswith("data: [DONE]"):
            try:
                events.append(json.loads(chunk[6:]))
            except Exception:
                pass
    return seen_requests, events


NUDGE = "instead of doing it"
HANDBACK = "Should I read the other two files as well?"
READ_CALL = '```read_file\n{"path": "/tmp/beta.py"}\n```'
# A system-owned call, so this stays a loop-control test: a workspace read in
# this bare harness has no approved workspace and is correctly held by the
# approval gate before it runs (`tool_blocked`), which would make the assertion
# about the gate rather than about the push.
PLAN_CALL = '```update_plan\n{"plan": "- [x] read alpha\\n- [ ] read beta"}\n```'


def _tools_called(events):
    return [e.get("tool") for e in events if e.get("tool")]


def _system_text(request):
    return "\n".join(m["content"] for m in request if m["role"] == "system")


def test_a_turn_handed_back_as_a_question_is_pushed_once(monkeypatch):
    _patch_common(monkeypatch)
    requests, events = _run(monkeypatch, [HANDBACK, READ_CALL, "Done: gamma.py defines it."])
    assert len(requests) >= 2, requests
    assert NUDGE in _system_text(requests[1]), _system_text(requests[1])
    # The round after the push made the call it had been asking about.
    assert "read_file" in _tools_called(events), events


def test_the_round_after_the_push_runs(monkeypatch):
    """The push is not just a message: the call made on the next round reaches
    the dispatcher and returns a result."""
    _patch_common(monkeypatch)
    requests, events = _run(
        monkeypatch, [HANDBACK, PLAN_CALL, "Done."],
        relevant_tools={"read_file", "update_plan"},
    )
    assert NUDGE in _system_text(requests[1])
    assert any(e.get("type") == "tool_start" and e.get("tool") == "update_plan"
               for e in events), events


def test_the_push_happens_once_and_then_the_turn_ends(monkeypatch):
    _patch_common(monkeypatch)
    requests, events = _run(monkeypatch, [HANDBACK])
    assert len(requests) == 2, [len(requests), requests]
    pushes = sum(1 for r in requests if NUDGE in _system_text(r))
    assert pushes == 1, pushes
    # Pushed once and it asked again: the turn ends the way it did before, with
    # no new stop kind invented for it.
    assert not any(e.get("type") in ("intent_nudge_exhausted", "loop_breaker_triggered")
                   for e in events), events


def test_a_finished_answer_that_says_let_me_know_is_not_pushed(monkeypatch):
    """The false positive that would make this mechanism worse than nothing: a
    turn that did the work and signs off politely. No action is offered, so no
    arm of the pattern matches."""
    _patch_common(monkeypatch)
    requests, _ = _run(
        monkeypatch,
        ["I read all three. gamma.py defines ROUND_CAP = 50. "
         "Let me know if you need anything else."],
    )
    assert len(requests) == 1, _system_text(requests[-1])


def test_plan_mode_may_end_on_a_question(monkeypatch):
    """Plan mode's job is proposing un-taken actions, and
    `PLAN_MODE_DIRECTIVE` orders it to ask when the request is ambiguous. The
    supervisor is exempt there for the same reason the intent one is."""
    _patch_common(monkeypatch)
    requests, _ = _run(monkeypatch, [HANDBACK], plan_mode=True)
    assert len(requests) == 1, _system_text(requests[-1])


ASK_BLOCK = ('```ask_user\n'
             '{"question": "Which server would you like me to look at?", '
             '"options": [{"label": "The running one"}, {"label": "All of them"}]}\n'
             '```')
ASK_RESULT = {"ask_user": {"question": "Which server would you like me to look at?",
                           "options": [{"label": "The running one"}],
                           "multi": False}}
LOOK_FIRST = "before running anything"


def test_ask_user_before_anything_ran_buys_one_round_of_looking(monkeypatch):
    _patch_common(monkeypatch)
    requests, events = _run(
        monkeypatch,
        [ASK_BLOCK, PLAN_CALL, "Done."],
        results={"ask_user": ASK_RESULT},
        relevant_tools={"read_file", "ask_user", "update_plan"},
    )
    assert len(requests) >= 2, requests
    assert LOOK_FIRST in _system_text(requests[1]), _system_text(requests[1])
    # The card was not raised on that round, and the work happened after.
    assert not any(e.get("type") == "ask_user" for e in events), events
    assert any(e.get("type") == "tool_start" and e.get("tool") == "update_plan"
               for e in events), events


def test_a_second_ask_ships_the_card(monkeypatch):
    """Pushed once and it still wants to ask: that is a real fork, and the card
    ships exactly as it did before. The cost of a genuine question is one
    round."""
    _patch_common(monkeypatch)
    requests, events = _run(
        monkeypatch,
        [ASK_BLOCK, ASK_BLOCK],
        results={"ask_user": ASK_RESULT},
        relevant_tools={"read_file", "ask_user"},
    )
    assert any(e.get("type") == "ask_user" for e in events), events
    assert len(requests) == 2, len(requests)


def test_ask_user_after_a_tool_ran_still_ends_the_turn(monkeypatch):
    """The model looked, then asked. Nothing about that is the defect, and the
    turn ends on the card on the very next round."""
    _patch_common(monkeypatch)
    requests, events = _run(
        monkeypatch,
        [READ_CALL, ASK_BLOCK],
        results={"ask_user": ASK_RESULT},
        relevant_tools={"read_file", "ask_user"},
    )
    assert any(e.get("type") == "ask_user" for e in events), events
    # On the round right after the tool, not a round later: the model looked,
    # so there is nothing to push it to look at.
    assert len(requests) == 2, len(requests)


def test_a_turn_with_no_other_tool_may_ask_at_once(monkeypatch):
    """Nothing to look with: a question is the only move left, so it ships."""
    _patch_common(monkeypatch)
    requests, events = _run(
        monkeypatch,
        [ASK_BLOCK],
        results={"ask_user": ASK_RESULT},
        relevant_tools={"ask_user", "update_plan"},
    )
    assert any(e.get("type") == "ask_user" for e in events), events
    assert len(requests) == 1, len(requests)


def test_the_verifier_tells_the_model_to_fix_the_work_not_to_ask(monkeypatch):
    """The brief's third suspect, measured rather than read: a FAIL verdict
    sends the model back to the tools. It is also default OFF
    (`agent_verifier_subagent`), which is why it ended none of the five
    measured turns."""
    _patch_common(monkeypatch)
    monkeypatch.setattr(
        al, "get_setting",
        lambda key, default=None: True if key == "agent_verifier_subagent" else default,
        raising=False,
    )

    async def _fail(*a, **k):
        return al.VerifierVerdict("fail", issues=("the third file was never read",))

    monkeypatch.setattr(al, "_run_verifier_subagent", _fail, raising=False)
    # The verifier only fires after a tool that produces a checkable artifact
    # (`_VERIFIER_EFFECTFUL_TOOLS`), so the turn has to write something first.
    write = ('```create_document\n{"title": "notes", "content": "x"}\n```')
    requests, _ = _run(
        monkeypatch,
        [write, "Done: gamma.py defines it.", "Done for real."],
        results={"create_document": {"output": "created", "doc_id": "d1",
                                     "title": "notes", "version": 1,
                                     "action": "create", "content": "x"}},
        relevant_tools={"create_document"},
    )
    injected = "\n".join(_system_text(r) for r in requests)
    assert "Fix these now using tools" in injected, injected[-600:]
    assert "the third file was never read" in injected
