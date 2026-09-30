# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P7-13` — the trust rungs, defined as a ladder in one place.

`D-2026-09-08-05`: *"we make our own trust rungs."* The row asked whether an
order exists among `ask_every_time`, `allow_listed` and `gate_on_untrusted`,
because two callers already talked as if one did — a role profile *"may only
raise strictness"* (a sentence in `agent_loop.py` and in nobody's code), and a
turn that says "ask me before using tools" is raised to *"the strictest rung"*
(an assumption about one name). Nothing said what stricter meant.

The owner's test for an order is the only checkable one: **a rung is a set of
conditions under which the assistant stops and asks, and rung N's set is a
strict superset of rung N−1's.** `TRUST_LADDER` writes each rung down that way,
and `decision_for` now asks the set, not the name.

What is proven here, by driving the code (`Law 20`):

  * the ladder is one — every rung once, each a strict superset of the one
    below, the floor in all — and a ladder that is not one cannot be declared;
  * **the sets are the gate**: over every known tool and a spread of contents,
    in every combination of taint, blanket yes and standing rule, the gate asks
    exactly when the situation the case is in belongs to the rung's set;
  * the order is read off the sets (`is_stricter`, `stricter_of`,
    `rung_direction`), and the role-profile rule and the "ask me first" raise
    both combine rungs through it — the role rule through the real loop;
  * the chat side names which way a move of the rung went, and moving it
    looser from chat already cannot happen without the person: every rung with
    a looser one below it asks before `manage_settings` in a clean chat, and
    every rung asks once untrusted content is in — the one exception is an
    allow rule the person saved for that very call;
  * the settings ladder draws the rungs in the ladder's order.

The two existing oracles — `test_trust_rung_gate.py` (every verdict and sentence
the default rung gave before `P7-03`) and `test_the_assistant_cannot_give_itself
_more_reach.py` (every other verdict the gate gave before `P7-02`) — are what
prove rewriting `decision_for` onto the sets changed no decision.
"""

import asyncio
import itertools
import json
import shutil

import pytest

import src.agent_tools  # noqa: F401  (break the agent_tools <-> tool_parsing import cycle)
import src.agent_loop as agent_loop
import src.settings as settings
import src.tool_capabilities as T
from src.tool_capabilities import (
    FLOOR_STOP_CONDITIONS,
    KNOWN_CAPABILITY_TOOLS,
    POST_EXTERNAL_BLOCKED_EFFECTS,
    RUNG_BLOCKED_EFFECTS,
    RUNG_LOOSER,
    RUNG_STRICTER,
    RUNG_UNCHANGED,
    TRUST_LADDER,
    StopCondition,
    ToolRunSecurityContext,
    TrustRung,
    capabilities_for_action,
    is_stricter,
    rung_consults_allow_rules,
    rung_direction,
    rung_rank,
    self_escalation_for,
    stop_conditions,
    stricter_of,
    strictest_rung,
    validate_trust_ladder,
)
from test_trust_ladder_js import _IMPORT, _ladder, ladder_sandbox  # noqa: E402,F401

RUNGS = [rung for rung, _ in TRUST_LADDER]
GATE, LISTED, EVERY = TrustRung.GATE_ON_UNTRUSTED, TrustRung.ALLOW_LISTED, TrustRung.ASK_EVERY_TIME


# ── it is a ladder ──────────────────────────────────────────────────────────

def test_every_rung_is_the_one_below_it_plus_something():
    assert RUNGS == [GATE, LISTED, EVERY]
    for (_, below), (_, above) in zip(TRUST_LADDER, TRUST_LADDER[1:]):
        assert above > below, "a rung that is not a strict superset is a second switch"
    for _, conditions in TRUST_LADDER:
        assert FLOOR_STOP_CONDITIONS <= conditions
    assert [rung_rank(r) for r in RUNGS] == [0, 1, 2]
    assert strictest_rung() is EVERY


def test_what_separates_each_rung_from_the_one_below_is_named():
    """The owner's test applied, and the answer written down: allow-listed adds
    asking in a clean chat and refusing a blanket yes after untrusted content;
    ask-every-time adds asking despite a standing rule."""
    assert stop_conditions(LISTED) - stop_conditions(GATE) == {
        StopCondition.IN_A_CLEAN_CHAT, StopCondition.AFTER_UNTRUSTED_DESPITE_A_YES}
    assert stop_conditions(EVERY) - stop_conditions(LISTED) == {
        StopCondition.DESPITE_A_STANDING_RULE}
    assert stop_conditions(GATE) == FLOOR_STOP_CONDITIONS == {
        StopCondition.MORE_REACH, StopCondition.AFTER_UNTRUSTED}


@pytest.mark.parametrize("broken,why", [
    (((GATE, FLOOR_STOP_CONDITIONS), (LISTED, FLOOR_STOP_CONDITIONS),
      (EVERY, FLOOR_STOP_CONDITIONS | {StopCondition.IN_A_CLEAN_CHAT})),
     "two rungs with the same set are two names for one switch"),
    (((GATE, frozenset({StopCondition.MORE_REACH})), (LISTED, stop_conditions(LISTED)),
      (EVERY, stop_conditions(EVERY))),
     "a rung below the floor lifts the post-external gate"),
    (((GATE, stop_conditions(GATE)), (EVERY, stop_conditions(EVERY))),
     "a rung missing from the ladder"),
    (((EVERY, stop_conditions(EVERY)), (LISTED, stop_conditions(LISTED)),
      (GATE, stop_conditions(GATE))),
     "the order inverted"),
    (((GATE, stop_conditions(GATE)),
      (LISTED, FLOOR_STOP_CONDITIONS | {StopCondition.DESPITE_A_STANDING_RULE}),
      (EVERY, FLOOR_STOP_CONDITIONS | {StopCondition.IN_A_CLEAN_CHAT})),
     "two rungs that cannot be ordered"),
], ids=["equal", "below-the-floor", "missing", "inverted", "unordered"])
def test_a_ladder_that_is_not_one_cannot_be_declared(broken, why):
    with pytest.raises(ValueError):
        validate_trust_ladder(broken)


# ── the sets are the gate ───────────────────────────────────────────────────

def _contents(tool):
    """A spread of arguments per tool: nothing, plain text, and every action
    the multiplexed tools distinguish, so a read and a delete of one tool are
    both in the sweep."""
    out = ["", "status", "rm -rf /tmp/x"]
    for table in (T._PRIVATE_ACTION_READS, T._PRIVATE_ACTION_WRITES, T._ACTION_DESTRUCTIVE):
        for action in sorted(table.get(tool, ())):
            out.append(json.dumps({"action": action}))
    if tool == "ui_control":
        out += ["toggle bash on", "toggle bash off", "set_mode agent", "set_theme dark"]
    return out


def _cases():
    tools = sorted(KNOWN_CAPABILITY_TOOLS) + ["mcp__unknown__thing"]
    for tool in tools:
        for content in _contents(tool):
            yield tool, content


def _situation(tool, content, *, tainted, bypass, rule):
    """Which condition this case is in, worked out from the case alone — never
    from the gate under test."""
    if self_escalation_for(tool, content) is not None:
        return StopCondition.MORE_REACH
    capabilities = capabilities_for_action(tool, content)
    gated = POST_EXTERNAL_BLOCKED_EFFECTS if tainted else RUNG_BLOCKED_EFFECTS
    if capabilities.known and not (capabilities.effects & gated):
        return None   # nothing consequential: no rung asks
    if tainted:
        return StopCondition.AFTER_UNTRUSTED_DESPITE_A_YES if bypass else StopCondition.AFTER_UNTRUSTED
    return StopCondition.DESPITE_A_STANDING_RULE if rule else StopCondition.IN_A_CLEAN_CHAT


def test_the_gate_asks_exactly_when_the_rung_holds_the_situation():
    """The property that makes the ladder the behaviour rather than a claim
    about it, over every combination: rung × taint × blanket yes × standing
    rule × tool × content."""
    checked = asked = 0
    for rung, tainted, bypass, rule in itertools.product(RUNGS, (False, True), (False, True), (False, True)):
        context = ToolRunSecurityContext(
            external_untrusted_context_seen=tainted,
            approval_gate_bypassed=bypass,
            rung=rung,
            allow_rule_lookup=(lambda tool, content, _rule=rule: _rule),
        )
        for tool, content in _cases():
            situation = _situation(tool, content, tainted=tainted, bypass=bypass, rule=rule)
            expected_ask = situation is not None and situation in stop_conditions(rung)
            decision = context.decision_for(tool, content)
            assert (not decision.allowed) == expected_ask, (rung.value, tainted, bypass, rule, tool, content)
            checked += 1
            asked += expected_ask
    # Measured on this tree: 349 tool × content cases, 8,376 decisions, 4,640
    # of them asks. Floors rather than equalities, so a tool added tomorrow
    # does not fail this; a corpus that shrinks does.
    assert checked >= 8376 and asked >= 4640, (checked, asked)


def test_the_armed_gate_is_the_one_that_asks_in_a_clean_chat():
    for rung in RUNGS:
        clean = ToolRunSecurityContext(rung=rung)
        assert clean.gate_is_armed is (StopCondition.IN_A_CLEAN_CHAT in stop_conditions(rung))
        assert ToolRunSecurityContext(rung=rung, external_untrusted_context_seen=True).gate_is_armed
    assert T._RUNGS_THAT_ASK_UNTAINTED == {LISTED, EVERY}


def test_only_the_rung_a_standing_rule_can_answer_for_reads_the_rules():
    assert [r for r in RUNGS if rung_consults_allow_rules(r)] == [LISTED]


# ── the order, read off the sets ────────────────────────────────────────────

@pytest.mark.parametrize("a,b", list(itertools.product(RUNGS, RUNGS)))
def test_stricter_means_asks_in_every_case_the_other_does_and_more(a, b):
    assert is_stricter(a, b) is (stop_conditions(a) > stop_conditions(b))
    assert stricter_of(a, b) is (a if rung_rank(a) >= rung_rank(b) else b)
    expected = RUNG_STRICTER if is_stricter(b, a) else RUNG_LOOSER if is_stricter(a, b) else RUNG_UNCHANGED
    assert rung_direction(a, b) == expected


# ── the role-profile rule, in code ─────────────────────────────────────────

@pytest.fixture
def role(monkeypatch):
    def install(answer):
        settings.set_role_limit_provider(answer)
    yield install
    settings.clear_role_limit_provider()


@pytest.mark.parametrize("stored,floor", list(itertools.product(RUNGS, RUNGS)))
def test_a_role_may_raise_the_rung_and_never_lower_it(role, stored, floor):
    role(lambda key, owner: floor.value if key == "trust_rung" and owner == "alice" else None)
    assert agent_loop.apply_role_floor(stored, "alice") is stricter_of(stored, floor)
    assert agent_loop.apply_role_floor(stored, "bob") is stored, "no floor for a role that says nothing"


@pytest.mark.parametrize("answer", [
    lambda key, owner: "ask-every-time", lambda key, owner: 3, lambda key, owner: {},
    lambda key, owner: (_ for _ in ()).throw(RuntimeError("role store down")),
], ids=["misspelt", "a-number", "a-dict", "raises"])
def test_a_role_that_names_no_rung_sets_no_floor(role, answer):
    role(answer)
    for stored in RUNGS:
        assert agent_loop.apply_role_floor(stored, "alice") is stored


def _rung_the_run_used(monkeypatch, *, stored, owner, message="Please read the README."):
    from src.tool_policy import build_effective_tool_policy

    seen = {}
    real = agent_loop.ToolRunSecurityContext

    def capture(*args, **kwargs):
        seen["rung"] = kwargs.get("rung")
        return real(*args, **kwargs)

    async def fake_stream(*args, **kwargs):
        yield f"data: {json.dumps({'delta': 'done'})}\n\n"
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(agent_loop, "ToolRunSecurityContext", capture)
    monkeypatch.setattr(agent_loop, "get_setting",
                        lambda key, default=None: stored.value if key == "trust_rung" else default,
                        raising=False)
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: None, raising=False)
    monkeypatch.setattr(agent_loop, "estimate_tokens", lambda *a, **k: 10, raising=False)
    monkeypatch.setattr(agent_loop, "blocked_tools_for_owner", lambda o: set(), raising=False)
    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", fake_stream, raising=False)

    async def _go():
        return [c async for c in agent_loop.stream_agent_loop(
            "http://local.test/v1", "m", [{"role": "user", "content": message}],
            max_rounds=1, relevant_tools={"bash"}, owner=owner,
            tool_policy=build_effective_tool_policy(last_user_message=message))]

    asyncio.run(_go())
    return seen["rung"]


def test_through_the_loop_a_role_floor_raises_the_run(monkeypatch, role):
    role(lambda key, owner: "allow_listed" if (key, owner) == ("trust_rung", "alice") else None)
    assert _rung_the_run_used(monkeypatch, stored=GATE, owner="alice") is LISTED
    assert _rung_the_run_used(monkeypatch, stored=EVERY, owner="alice") is EVERY
    assert _rung_the_run_used(monkeypatch, stored=GATE, owner="bob") is GATE


def test_asking_to_be_asked_first_raises_to_the_top_of_the_ladder(monkeypatch, role):
    role(lambda key, owner: None)
    for stored in RUNGS:
        assert _rung_the_run_used(monkeypatch, stored=stored, owner="alice",
                                  message="Ask me before using tools.") is strictest_rung()


# ── the chat side ───────────────────────────────────────────────────────────

@pytest.fixture
def chat_tool(monkeypatch):
    from src.agent_tools import admin_tools

    store = dict(settings.DEFAULT_SETTINGS)
    monkeypatch.setattr(settings, "load_settings", lambda: dict(store))
    monkeypatch.setattr(settings, "save_settings", lambda updated: (store.clear(), store.update(updated)))

    def call(value):
        return asyncio.run(admin_tools.do_manage_settings(
            json.dumps({"action": "set", "key": "trust_rung", "value": value})))

    return store, call


@pytest.mark.parametrize("before,after", list(itertools.product(RUNGS, RUNGS)))
def test_moving_the_rung_from_chat_says_which_way_it_went(chat_tool, before, after):
    store, call = chat_tool
    store["trust_rung"] = before.value
    result = call(after.value)
    assert result["exit_code"] == 0
    assert store["trust_rung"] == after.value, "still writable (`D-2026-09-12-01`)"
    reply = result["response"]
    assert reply.startswith(f"Set trust_rung = {after.value}. ")
    direction = rung_direction(before, after)
    if direction == RUNG_UNCHANGED:
        assert reply.endswith(f"It was already {after.value}.")
        return
    word = "stricter" if direction == RUNG_STRICTER else "looser"
    assert f"That is {word} than {before.value}" in reply
    moved = stop_conditions(after) ^ stop_conditions(before)
    for condition in moved:
        assert T.STOP_CONDITION_WORDS[condition] in reply
    for condition in stop_conditions(after) & stop_conditions(before):
        assert T.STOP_CONDITION_WORDS[condition] not in reply


def _set_rung(value):
    return json.dumps({"action": "set", "key": "trust_rung", "value": value})


@pytest.mark.parametrize("current,target", [
    (a, b) for a, b in itertools.product(RUNGS, RUNGS) if rung_direction(a, b) == RUNG_LOOSER
])
def test_loosening_from_chat_already_waits_for_the_person(current, target):
    """The direction `P7-13` asked about, named — and already closed by the
    rung itself. In a clean chat, in a tainted one, and after a blanket yes,
    the gate stops before `manage_settings` loosens the rung. The one door is
    a standing rule the person saved for this very call, on the rung that reads
    rules, in a clean chat: their own standing yes."""
    content = _set_rung(target.value)
    for tainted, bypass in itertools.product((False, True), (False, True)):
        context = ToolRunSecurityContext(rung=current, external_untrusted_context_seen=tainted,
                                         approval_gate_bypassed=bypass)
        assert context.decision_for("manage_settings", content).allowed is False, (tainted, bypass)
    covered = ToolRunSecurityContext(rung=current, allow_rule_lookup=lambda t, c: True)
    assert covered.decision_for("manage_settings", content).allowed is (current is LISTED)


def test_tightening_from_the_default_rung_is_not_held_up():
    """The other direction, unasked where it always was: an assistant that can
    make itself ask more is one a person can ask to."""
    for target in (LISTED, EVERY):
        assert ToolRunSecurityContext(rung=GATE).decision_for(
            "manage_settings", _set_rung(target.value)).allowed is True


# ── the settings ladder draws the rungs in the ladder's order ──────────────

@pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")
def test_the_settings_ladder_is_drawn_in_the_ladders_order(ladder_sandbox):
    drawn = _ladder(_IMPORT + """
        const m = await import('./trustLadder.js');
        console.log(JSON.stringify(m.TRUST_RUNGS.map((r) => r.value)));
    """, ladder_sandbox)
    assert drawn == [rung.value for rung in RUNGS]
