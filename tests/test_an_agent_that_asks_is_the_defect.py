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

**`B1412`, added 2026-10-22 from the owner's own screenshot.** The nudge held
the question by *discarding* it, and a model that did not ask again left the
turn with no card, no tool bubble and no line — on a plan step, that reads as a
hang rather than as a decision. The question is now kept and released when the
turn ends having looked at nothing and done nothing; both conditions are
load-bearing, because a question released after the model looked is a guess
about something the looking may already have answered. The ruling is untouched:
the round is still spent and the model is still told to look. What changes is
that silence stops being one of the outcomes.
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


def _patch_common(monkeypatch, *, skills=False, blocked=()):
    monkeypatch.setattr(al, "get_setting", lambda key, default=None: default, raising=False)
    monkeypatch.setattr(al, "get_mcp_manager", lambda: None, raising=False)
    monkeypatch.setattr(al, "estimate_tokens", lambda *a, **k: 10, raising=False)
    # `B1366`. Two things this harness used to leave to the environment, and
    # each of them decided on its own whether `B1327`'s gate fired. Both are
    # stated here now, because a loop-control test that inherits them is a test
    # about the container it ran in (`Law 19`).
    #
    # `blocked_tools_for_owner(None)` is the **non-admin** cap: measured on
    # `b4e5fe1` it returned 53 names, `read_file`, `bash` and `manage_skills`
    # among them. Every turn in this file is the owner's own admin turn — the
    # privilege the five measured tasks ran at — so the default is an empty cap
    # and a test that wants the non-admin surface asks for it.
    monkeypatch.setattr(al, "blocked_tools_for_owner",
                        lambda owner: set(blocked), raising=False)
    # `B1360` adds `manage_skills` to the selection set whenever the owner has
    # **any** active skill, and this tree's `data/` carries 286 of them. So "a
    # turn with no other tool" was not reachable in this harness at all: the
    # product put a tool in the set behind the test's back. Off by default, and
    # the test below that is *about* that interaction turns it on.
    monkeypatch.setattr(al, "_skills_pref_enabled",
                        lambda owner: bool(skills), raising=False)
    # `B1426`. "Any active skill" used to be met by those 286, which are
    # vendored drafts the catalogue never lists; it no longer counts them. So
    # the library this file's skills case is about is stated: one published
    # procedure of the person's own.
    if skills:
        monkeypatch.setattr(al, "_skills_for_turn",
                            lambda sm, owner, disabled_tools=None: [
                                {"name": "tidy-logs", "status": "published",
                                 "requires_toolsets": []}], raising=False)


def _run(monkeypatch, round_texts, *, results=None, max_rounds=6,
         relevant_tools=None, plan_mode=False, disabled_tools=None,
         user="read the three files and tell me which defines it"):
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
        # `B1366`. The route's own withholding, which the loop subtracts only
        # when it assembles the prompt — so a turn can hold a name it cannot use.
        disabled_tools=set(disabled_tools) if disabled_tools else None,
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


def test_plan_mode_is_told_to_ground_the_plan_before_asking(monkeypatch):
    """`B1345` / `D-2026-10-14-01` §3, asserted through the shipped prompt.

    The directive used to end *"Ask first, then plan."* while the same prompt,
    four paragraphs up, hands the model 25 read-only tools and tells it to
    ground the plan with them — the ask-before-looking shape `B1327` fixed for
    execution turns, stated as policy in the one mode that stated it.

    `B1345`'s own `Verify:` line named `test_plan_mode_may_end_on_a_question`
    above as the case that would redden on this change. It does not and should
    not: that case holds the **supervisor exemption**, which the ruling leaves
    alone, and the directive's wording was in fact guarded by nothing. This is
    that guard, and it reads the real assembled system text rather than the
    constant (`Law 20`), because what matters is what the model is sent.
    """
    _patch_common(monkeypatch)
    requests, _ = _run(monkeypatch, [HANDBACK], plan_mode=True)
    system = _system_text(requests[-1])

    # Plan mode is really on — otherwise this case measures nothing.
    assert "PLAN MODE" in system, system[:400]
    # Ground first, then ask.
    assert "GROUND IT FIRST, THEN ASK" in system, system
    assert "Look first, then ask, then plan." in system, system
    # The instruction it replaced is gone, in both its halves.
    assert "Ask first, then plan." not in system
    # And nothing was taken away: the tool is still offered, and the reason a
    # guess is worse than a question is still stated.
    assert "`ask_user` is available in plan mode" in system
    assert "invisible" in system


def test_plan_mode_still_keeps_its_read_only_tools_and_its_exemption(monkeypatch):
    """The other half of §3's narrowness, so the change cannot creep.

    The ruling moves one paragraph of wording. It does not touch the allowlist
    that makes grounding possible in the first place, and it does not remove
    `ask_user` from it — if either moved, "ground it first" would be an order
    the mode cannot carry out.
    """
    from src.tool_security import PLAN_MODE_READONLY_TOOLS

    assert "ask_user" in PLAN_MODE_READONLY_TOOLS
    for name in ("read_file", "grep", "glob", "ls"):
        assert name in PLAN_MODE_READONLY_TOOLS, name
    # The mutating tools the directive promises are disabled still are.
    for name in ("bash", "python", "write_file", "edit_file", "send_email"):
        assert name not in PLAN_MODE_READONLY_TOOLS, name


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


# ── `B1412`: the held question is deferred, not destroyed ──────────────────


def test_a_held_question_ships_when_the_turn_looked_at_nothing(monkeypatch):
    """The owner's screenshot, as a case.

    `B1327` buys one round of looking and the card ships if the model asks
    again. **A capable model asks again. `gpt-oss-20b` does not** — told to
    "look first", it writes prose — and the question it had already composed
    was thrown away with `tool_blocks = []`. Measured on the shipped loop
    before this: **0 `ask_user` events and 0 `tool_start` events** reached the
    browser on a turn executing an approved plan whose first step was *"ask
    for preference"*, so the plan sat on step one with a spinner and nothing
    on screen said a decision was owed.

    A supervisor that silently discards the only user-facing act of a turn is
    indistinguishable from a hang (`Law 13`, `Law 15`). The ruling is
    untouched — the round is still spent, the model is still told to look —
    but silence stops being one of the outcomes.
    """
    _patch_common(monkeypatch)
    requests, events = _run(
        monkeypatch,
        [ASK_BLOCK, "I'll go with plain HTML and CSS."],
        results={"ask_user": ASK_RESULT},
        relevant_tools={"read_file", "ask_user", "update_plan"},
    )
    assert LOOK_FIRST in _system_text(requests[1]), _system_text(requests[1])
    assert len(requests) == 2, len(requests)
    cards = [e for e in events if e.get("type") == "ask_user"]
    assert len(cards) == 1, events
    # Through the one path that builds every other card, so the persisted
    # event, the tool bubble and the card cannot drift apart (`Law 14`).
    assert any(e.get("type") == "tool_start" and e.get("tool") == "ask_user"
               for e in events), events
    assert cards[0]["data"]["question"], cards[0]


def test_a_held_question_is_stale_once_the_model_has_looked(monkeypatch):
    """Both release conditions are load-bearing and neither is slack.

    If the model ran anything, the nudge did its job: the question was a guess
    about something the looking may have just answered, and putting it on
    screen afterwards is the exact defect `B1327` exists to stop. So a turn
    that looked gets no card, even though a question was held earlier in it.
    """
    _patch_common(monkeypatch)
    requests, events = _run(
        monkeypatch,
        [ASK_BLOCK, READ_CALL, "alpha.py defines it."],
        results={"ask_user": ASK_RESULT},
        relevant_tools={"read_file", "ask_user"},
    )
    assert any(e.get("type") == "tool_start" and e.get("tool") == "read_file"
               for e in events), events
    assert not any(e.get("type") == "ask_user" for e in events), events


def test_a_released_question_is_not_a_second_card(monkeypatch):
    """The model asked, was pushed, and asked again — so the card ships on
    round two by the ordinary path. The held copy must not ship a second one:
    two cards for one question is a worse answer than none."""
    _patch_common(monkeypatch)
    _, events = _run(
        monkeypatch,
        [ASK_BLOCK, ASK_BLOCK],
        results={"ask_user": ASK_RESULT},
        relevant_tools={"read_file", "ask_user"},
    )
    assert len([e for e in events if e.get("type") == "ask_user"]) == 1, events


def test_the_card_the_person_sees_carries_its_options(monkeypatch):
    """`Law 15` for this surface. A released card is only worth shipping if it
    is the same card: the question, and the options a person clicks. The
    browser's free-text *Other* box is drawn from the card itself, so the
    payload has to arrive whole for it to have anything to sit under."""
    _patch_common(monkeypatch)
    _, events = _run(
        monkeypatch,
        [ASK_BLOCK, "Prose instead of asking again."],
        results={"ask_user": ASK_RESULT},
        relevant_tools={"read_file", "ask_user"},
    )
    card = next(e for e in events if e.get("type") == "ask_user")["data"]
    assert card["question"] == "Which server would you like me to look at?"
    assert [o["label"] for o in card["options"]] == ["The running one"]


def test_the_nudge_and_the_release_ask_one_question(monkeypatch):
    """`Law 7`. The release's whole argument is that it applies *the same test
    the nudge applied one round earlier*, so the two read one predicate.
    Driven rather than read: narrow what "nothing has been looked at" means and
    BOTH sites have to move together — the nudge stops firing, so there is
    nothing held and nothing to release."""
    _patch_common(monkeypatch)
    # `B1413` narrowed the predicate to the call counter; one argument now.
    monkeypatch.setattr(al, "_nothing_looked_at", lambda calls: False)
    requests, events = _run(
        monkeypatch,
        [ASK_BLOCK, "Prose instead of asking again."],
        results={"ask_user": ASK_RESULT},
        relevant_tools={"read_file", "ask_user"},
    )
    # No nudge, so the card ships on round one by the ordinary path — and the
    # release never runs, because nothing was ever held.
    assert LOOK_FIRST not in _system_text(requests[-1]), _system_text(requests[-1])
    assert len([e for e in events if e.get("type") == "ask_user"]) == 1, events


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


def test_a_turn_making_distinct_calls_is_not_cut_short(monkeypatch):
    """The brief's fourth suspect, answered rather than assumed: does the
    force-answer salvage cut a turn that was still working?

    No. The loop-breaker needs four circling rounds, fifteen identical calls,
    or four rounds that bring nothing new (`ROUNDS_WITHOUT_NEW_INFORMATION`);
    five *distinct* calls are progress and ride through. Measured the same way
    on the booted product: across the five tasks the deepest turn used 5 of 50
    rounds and no `loop_breaker_triggered` or `no_new_information` frame was
    emitted once.
    """
    _patch_common(monkeypatch)
    calls = [f'```update_plan\n{{"plan": "- [x] step {n}"}}\n```' for n in range(1, 6)]
    _, events = _run(
        monkeypatch, calls + ["Done: all five steps."],
        relevant_tools={"update_plan"}, max_rounds=8,
    )
    assert not any(e.get("type") in ("loop_breaker_triggered", "no_new_information",
                                     "rounds_exhausted")
                   for e in events), [e.get("type") for e in events]
    assert sum(1 for e in events
               if e.get("type") == "tool_start" and e.get("tool") == "update_plan") == 5


# ── `B1366`. "Nothing to look with" means the turn's offer ─────────────────
#
# `B1327`'s gate above asked `set(relevant_tools) - {"ask_user",
# "update_plan"}`, and that set is not what the turn offers the model. Measured
# on `b4e5fe1` by driving the loop with `relevant_tools={"ask_user",
# "update_plan"}` and nothing else:
#
#   gate read            {ask_user, manage_skills, update_plan}
#   prompt the model got 5,091 chars, string "manage_skills" absent
#   disabled_tools       53 names, `manage_skills` among them
#
# `manage_skills` is added to `relevant_tools` whenever the owner has **any**
# active skill (`B1360`, 286 of them in `data/`), which is a fact about their
# library and not about this request; and `disabled_tools` is only subtracted
# later, inside `_assemble_prompt`. So the turn was pushed to "look first" with
# nothing to look with, and `ask_user`'s card was withheld for a round the
# model could do nothing with.


def test_the_looking_test_reads_the_turns_offer_not_the_raw_selection():
    """The predicate, directly: three decisions and the full-suite case."""
    look = al._turn_has_something_to_look_with
    # Selection did not run — the turn carries the whole suite.
    assert look(None) is True
    assert look(None, {"read_file"}) is True
    # Only the two tools that cannot look at anything.
    assert look({"ask_user", "update_plan"}) is False
    # A tool that can look.
    assert look({"ask_user", "update_plan", "read_file"}) is True
    # The same tool, disabled at the route: the prompt will not name it and the
    # dispatcher would refuse it, so it is not something to look with.
    assert look({"ask_user", "update_plan", "read_file"}, {"read_file"}) is False
    # The measured case: injected behind the request's back *and* disabled.
    assert look({"ask_user", "update_plan", "manage_skills"},
                {"manage_skills"}) is False
    # Injected and **not** disabled is a real tool, and still counts.
    assert look({"ask_user", "update_plan", "manage_skills"}, set()) is True


def test_the_two_tools_that_cannot_look_are_named_once():
    """`Law 7`. The gate reads one definition of "cannot look", not a literal
    repeated at the call site — which is how `B1360` moved `manage_skills` into
    the selection set without anything noticing this gate had an opinion."""
    assert al._CANNOT_LOOK == frozenset({"ask_user", "update_plan"})
    import inspect
    gate = inspect.getsource(al.stream_agent_loop)
    assert "_turn_has_something_to_look_with(_relevant_tools, disabled_tools)" in gate
    # The old literal is gone from the gate.
    assert '- {"ask_user", "update_plan"}' not in gate


def test_a_disabled_tool_does_not_buy_a_round_of_looking(monkeypatch):
    """End to end, through the real loop: a turn whose only other tool is
    disabled ships the card at once, exactly as a turn with no other tool does.

    Red on `b4e5fe1` (2 requests, the nudge fired)."""
    _patch_common(monkeypatch)
    requests, events = _run(
        monkeypatch,
        [ASK_BLOCK],
        results={"ask_user": ASK_RESULT},
        relevant_tools={"ask_user", "update_plan", "read_file"},
        disabled_tools={"read_file"},
    )
    assert any(e.get("type") == "ask_user" for e in events), events
    assert len(requests) == 1, _system_text(requests[-1])[-400:]


def test_an_enabled_tool_still_buys_a_round_of_looking(monkeypatch):
    """The other direction, so the fix is not a way of switching `B1327` off:
    the same turn with `read_file` enabled is still pushed to look first."""
    _patch_common(monkeypatch)
    requests, _ = _run(
        monkeypatch,
        [ASK_BLOCK, READ_CALL, "Done."],
        results={"ask_user": ASK_RESULT},
        relevant_tools={"ask_user", "update_plan", "read_file"},
    )
    assert len(requests) >= 2, len(requests)
    assert LOOK_FIRST in _system_text(requests[1]), _system_text(requests[1])[-400:]


def test_a_skill_library_is_something_to_look_with(monkeypatch):
    """The `B1360` interaction, asserted rather than inherited.

    With skills on, `manage_skills` goes into the selection set and is **not**
    capped for the owner, so the turn really does hold a tool that can answer a
    procedure question — and the nudge firing is correct. This is the half of
    the old red that was the product being right; the other half was the gate
    reading a name the route had disabled."""
    _patch_common(monkeypatch, skills=True)
    requests, _ = _run(
        monkeypatch,
        [ASK_BLOCK, '```manage_skills\n{"action": "list"}\n```', "Done."],
        results={"ask_user": ASK_RESULT, "manage_skills": {"output": "no skills"}},
        relevant_tools={"ask_user", "update_plan"},
    )
    assert len(requests) >= 2, len(requests)
    assert LOOK_FIRST in _system_text(requests[1]), _system_text(requests[1])[-300:]


def test_the_same_skill_library_capped_for_this_person_is_not(monkeypatch):
    """And the cap decides it. `manage_skills` is in the non-admin blocklist,
    so the same turn at that privilege has nothing to look with and the card
    ships at once — which is what a non-admin turn measured on `b4e5fe1` was
    doing while the gate counted the tool anyway."""
    _patch_common(monkeypatch, skills=True, blocked={"manage_skills"})
    requests, events = _run(
        monkeypatch,
        [ASK_BLOCK],
        results={"ask_user": ASK_RESULT},
        relevant_tools={"ask_user", "update_plan"},
    )
    assert any(e.get("type") == "ask_user" for e in events), events
    assert len(requests) == 1, _system_text(requests[-1])[-400:]


def test_plan_mode_resolves_a_format_conflict_instead_of_looping():
    """`audit-P1-plan-loop`. GPT-6.1's audit: a weak model spent four minutes
    reconciling a request's formatting demands against plan mode's checklist
    requirement, never emitting a plan. The directive now resolves the conflict
    outright — the checklist wins, a requested shape becomes a step, one pass —
    so there is nothing to loop on."""
    from src.agent_loop import PLAN_MODE_DIRECTIVE
    d = PLAN_MODE_DIRECTIVE
    assert "THE CHECKLIST WINS" in d
    assert "do NOT reason back and forth" in d.replace("—", "-")
    assert "One pass, then stop." in d
    # It tells the model to fold a requested output shape into a step, not to
    # format the plan itself that way.
    assert "one of the checklist steps" in d


# ── `B1413`: which half of "nothing has been looked at" decides ────────────
#
# The predicate was `total_tool_calls == 0 and not tool_events`, and a mutation
# dropping either half left every case above green, because the harness had
# neither a call the gate refused nor a resumed approval. These are those two
# cases, plus the one case that does tell the halves apart: a call for a tool
# that does not exist (`B1383`), which is persisted as a refused row and never
# counted, because nothing ran. Measured with each half alone (the table is in
# `_nothing_looked_at`'s docstring): the gate-refused and resumed cases were
# decided the same by both, and only the unknown-name case split them — the
# `tool_events` half answering "looked" for a turn that had looked at nothing.
# So the counter is the predicate.

_ASK_CALL = {"name": "ask_user", "arguments": json.dumps({
    "question": "Which server would you like me to look at?",
    "options": [{"label": "The running one"}, {"label": "All of them"}]})}


def _run_native(monkeypatch, script, *, relevant_tools, exact_approval=None,
                owner=None, session_id=None):
    """`_run`, with native calls: each script entry is a list of calls or a
    string of prose. Returns (requests' system text, events)."""
    seen: list = []
    steps = iter(script)
    monkeypatch.setattr(al, "_agent_route_tool_mode",
                        lambda *a, **k: (True, False, False), raising=False)

    async def _fake_stream(_candidates, messages, **kwargs):
        seen.append("\n".join(str(m.get("content") or "") for m in messages
                               if m.get("role") == "system"))
        step = next(steps, "Done.")
        if isinstance(step, list):
            yield f'data: {json.dumps({"type": "tool_calls", "calls": step})}\n\n'
        else:
            yield f'data: {json.dumps({"delta": step})}\n\n'
        yield "data: [DONE]\n\n"

    async def _fake_exec(block, *a, **k):
        if block.tool_type == "ask_user":
            return (block.tool_type, dict(ASK_RESULT))
        return (block.tool_type, {"output": "ok", "exit_code": 0})

    monkeypatch.setattr(al, "stream_llm_with_fallback", _fake_stream, raising=False)
    monkeypatch.setattr(al, "execute_tool_block", _fake_exec, raising=False)
    kwargs = {}
    if exact_approval is not None:
        kwargs.update(exact_approval=exact_approval, owner=owner,
                      session_id=session_id, workspace=None)

    async def _drain():
        return [c async for c in al.stream_agent_loop(
            "http://x/v1", "m",
            [{"role": "user", "content": "check which server is running and tail it"}],
            max_rounds=6, relevant_tools=set(relevant_tools), **kwargs)]

    events = []
    for chunk in asyncio.run(_drain()):
        if chunk.startswith("data: {"):
            try:
                events.append(json.loads(chunk[6:]))
            except Exception:
                pass
    return seen, events


def test_a_call_the_gate_refused_counts_as_having_looked(monkeypatch):
    """The row's first case. The gate refuses `read_file` for this person; the
    call is counted at the top of the per-block loop and the question that
    follows ships on the next round, unpushed — as it did before `B1413`."""
    _patch_common(monkeypatch, blocked={"read_file"})
    read = {"name": "read_file", "arguments": json.dumps({"path": "/etc/hostname"})}
    requests, events = _run_native(monkeypatch, [[read], [_ASK_CALL]],
                                   relevant_tools={"read_file", "grep", "ask_user"})
    assert any(e.get("type") == "tool_blocked" and e.get("tool") == "read_file"
               for e in events), events
    assert len(requests) == 2, len(requests)
    assert not any(LOOK_FIRST in r for r in requests)
    assert len([e for e in events if e.get("type") == "ask_user"]) == 1


def test_a_turn_resumed_from_an_approved_card_has_looked(monkeypatch):
    """The row's second case, `B1069`'s. The approved call runs before round 1
    of the continuation, and the counter counts it (it always has: the replay
    increments it beside its persisted event) — so a question on the
    continuation's first round ships at once."""
    from src.tool_approvals import ToolApprovalStore
    from src.tool_capabilities import capabilities_for_action

    _patch_common(monkeypatch)
    store = ToolApprovalStore()
    pending = store.create(
        owner="alice", session_id="s1", origin_run_id="r1", tool_name="bash",
        content="printf hi", workspace=None, external_untrusted_context_seen=True,
        requested_round=1, capabilities=capabilities_for_action("bash", "printf hi"))
    grant = store.consume(pending.approval_id, decision="approve",
                          owner="alice", session_id="s1")
    assert grant is not None
    requests, events = _run_native(
        monkeypatch, [[_ASK_CALL]], relevant_tools={"read_file", "grep", "ask_user"},
        exact_approval=grant, owner="alice", session_id="s1")
    assert any(e.get("type") == "tool_start" and e.get("approved") for e in events), events
    assert len(requests) == 1, len(requests)
    assert not any(LOOK_FIRST in r for r in requests)
    assert len([e for e in events if e.get("type") == "ask_user"]) == 1


def test_a_call_for_a_tool_that_does_not_exist_is_not_looking(monkeypatch):
    """The case that told the halves apart. Nothing ran — the name is refused
    before dispatch (`B1383`) — so the question that follows is pushed to look
    first, and released at the end because the turn still looked at nothing.
    Red with the `tool_events` half: the refused row read as "looked", the
    nudge stood down, and the card shipped on a turn that had looked at
    nothing."""
    _patch_common(monkeypatch)
    unknown = {"name": "definitely_not_a_pantheon_tool", "arguments": "{}"}
    requests, events = _run_native(
        monkeypatch, [[unknown], [_ASK_CALL], "I'll look at the running one."],
        relevant_tools={"read_file", "grep", "ask_user"})
    assert any(LOOK_FIRST in r for r in requests), requests[-1][-400:]
    assert len([e for e in events if e.get("type") == "ask_user"]) == 1, events
