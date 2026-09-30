# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P7-12` — the agent may raise its own loop caps, for the run, with a governor.

`D-2026-09-08-04`: *"Yes. If its needed, the idea is to be able to allow full
automation. Full automation only works if the LLM in agent mode can define its
own parameters (with failsafes and safeguards.. a smarter 'loop detection' than
PewDiePie put in)."* Measured on the tree this row started from:

  * `manage_settings set agent_max_rounds 42` **wrote 42 to settings.json**. The
    run that asked got nothing — the loop had read its cap already — and every
    later session inherited the emergency: the one-way ratchet the decision's
    non-negotiable failsafe forbids;
  * a raise of a number the owner typed went through unasked, which
    *"a number the owner typed is not raised by the agent without saying so"*
    (and `D-2026-09-10-02`, *"never raise it"*) rules out;
  * loop detection counted a repeated call only in a round that wrote nothing,
    over the last six rounds, so a model that narrates ("Checking again.") or
    cycles over a longer period met only the fifteen-call backstop.

Now: a raise lands on the running loop and nothing is saved; a raise of an
owner-typed cap asks every time through `P7-02`'s one mechanism
(`self_escalation_for`); a lowering is saved as it always was; the loop's
information ledger stops a run that brings nothing new — no new call, no new
result, no new words — in four rounds; and the meter, and the promise before
the run, say all of it. Driven, not read (`Law 20`).
"""

import asyncio
import importlib
import itertools
import json
import shutil

import pytest

import src.agent_tools  # noqa: F401  (break the agent_tools <-> tool_parsing import cycle)
import src.agent_loop as agent_loop
import src.tool_execution as tool_execution
from src.run_limits import (
    ALREADY_ALLOWED, CAPS_FROM_CALLER, CAPS_FROM_SETTINGS, NO_RUN, NOT_THIS_RUN, RAISED,
    RunLimits, bind_run_limits,
)
from src.tool_approvals import ToolApprovalStore, tool_approval_store
from src.tool_capabilities import (
    ToolRunSecurityContext, TrustRung, capabilities_for_action, capabilities_for_tool,
)
from test_the_run_limits_are_said_before_it_runs import (  # noqa: E402
    _PREAMBLE as _HINT_PREAMBLE, sandbox as hint_sandbox,  # noqa: F401
)
from test_the_prep_steps_are_timed_live import (  # noqa: E402
    _METER_PREAMBLE, meter_sandbox,  # noqa: F401
)
from test_tool_effect_surfaces_js import _run  # noqa: E402

node_only = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")
RUNGS = list(TrustRung)


@pytest.fixture
def stored(tmp_path, monkeypatch):
    """A settings store of our own, read the way the product reads it: the pin
    (`setting_is_explicit`) opens this file."""
    monkeypatch.setenv("PANTHEON_DATA_DIR", str(tmp_path))
    import src.constants
    import src.settings as settings
    importlib.reload(src.constants)
    importlib.reload(settings)

    def write(values=None):
        (tmp_path / "settings.json").write_text(json.dumps(values or {}), encoding="utf-8")
        settings._invalidate_caches()
        return settings

    yield write
    monkeypatch.delenv("PANTHEON_DATA_DIR", raising=False)
    importlib.reload(src.constants)
    importlib.reload(settings)


def _set(key, value):
    return json.dumps({"action": "set", "key": key, "value": value})


def _manage(content, limits=None):
    from src.agent_tools.admin_tools import do_manage_settings

    async def go():
        if limits is not None:
            bind_run_limits(limits)
        return await do_manage_settings(content)

    return asyncio.run(go())


def _run_limits(round_limit=20, source="configured", configured=20, tool_calls=0,
                caps=CAPS_FROM_SETTINGS):
    return RunLimits(round_limit=round_limit, round_limit_source=source,
                     round_limit_configured=configured, tool_call_limit=tool_calls,
                     caps_source=caps)


# ── failsafe 1: a raise is the run's, and is never saved ────────────────────

@pytest.mark.parametrize("key", ["agent_max_rounds", "max steps", "step limit", "Max Rounds"])
def test_a_raise_lands_on_the_run_that_asked_and_is_never_saved(stored, key):
    settings = stored({})
    limits = _run_limits()
    result = _manage(_set(key, 60), limits)

    assert (limits.round_limit, limits.round_limit_source) == (60, "raised_for_run")
    assert limits.changed is True
    assert result["run_limit"] == {"key": "agent_max_rounds", "outcome": RAISED,
                                   "limit": 60, "saved": False}
    assert result["response"] == (
        "Raised this run's step limit to 60 steps. Nothing was saved: the next "
        "message is held to 20 steps again. Only a person can change that, in "
        "Settings › Agent Tools.")
    assert settings.load_settings().get("agent_max_rounds") == 20
    assert not settings.setting_is_explicit("agent_max_rounds"), "nothing was written"


def test_the_most_a_run_can_be_given_is_what_a_person_could_type(stored):
    stored({})
    limits = _run_limits()
    result = _manage(_set("agent_max_rounds", 5000), limits)
    assert limits.round_limit == 200
    assert "the most a run can be given is 200 steps" in result["response"]


def test_a_lowering_is_saved_as_it_always_was(stored):
    """Standing itself down is not the ratchet (`Law 1`)."""
    settings = stored({})
    limits = _run_limits()
    result = _manage(_set("agent_max_rounds", 12), limits)
    assert result["response"] == "Set agent_max_rounds = 12."
    assert settings.load_settings()["agent_max_rounds"] == 12
    assert (limits.round_limit, limits.changed) == (20, False)


def test_a_reset_that_would_raise_is_the_runs_too(stored):
    """`reset` writes the shipped default — a raise when the cap sits below it."""
    settings = stored({"agent_max_rounds": 8})
    limits = _run_limits(round_limit=8, configured=8)
    _manage(json.dumps({"action": "reset", "key": "agent_max_rounds"}), limits)
    assert limits.round_limit == 20
    assert settings.load_settings()["agent_max_rounds"] == 8


def test_the_tool_call_limit_is_raised_or_removed_for_the_run(stored):
    settings = stored({"agent_max_tool_calls": 10})
    limits = _run_limits(tool_calls=10)
    raised = _manage(_set("max tool calls", 30), limits)
    assert (limits.tool_call_limit, limits.tool_call_limit_source) == (30, "raised_for_run")
    assert raised["response"].startswith("Raised this run's tool-call limit to 30 tool calls.")
    removed = _manage(_set("agent_max_tool_calls", 0), limits)
    assert limits.tool_call_limit == 0
    assert removed["response"].startswith("Removed this run's tool-call limit.")
    assert settings.load_settings()["agent_max_tool_calls"] == 10


@pytest.mark.parametrize("limits,outcome,words", [
    (None, NO_RUN, "there is no run here to raise"),
    (_run_limits(caps=CAPS_FROM_CALLER, round_limit=8, configured=8), NOT_THIS_RUN,
     "was set by what started it, not by Settings"),
    (_run_limits(round_limit=100_000, source="local_lift"), ALREADY_ALLOWED,
     "can already go to 100,000 steps (the limit is lifted for a local model)"),
], ids=["no-run", "a-task's-own-cap", "lifted-already"])
def test_a_raise_that_does_not_apply_says_so_and_saves_nothing(stored, limits, outcome, words):
    settings = stored({})
    before = None if limits is None else (limits.round_limit, limits.round_limit_source)
    result = _manage(_set("agent_max_rounds", 60), limits)
    assert result["run_limit"]["outcome"] == outcome
    assert words in result["response"]
    assert "Nothing was saved" in result["response"] or "nothing was changed or saved" in result["response"]
    if limits is not None:
        assert (limits.round_limit, limits.round_limit_source) == before
    assert settings.load_settings()["agent_max_rounds"] == 20


# ── failsafe 2: a number the owner typed is raised only with them ───────────

def test_raising_a_cap_the_owner_typed_asks_at_every_rung(stored):
    stored({"agent_max_rounds": 30, "agent_max_tool_calls": 10})
    for rung, tainted, bypass in itertools.product(RUNGS, (False, True), (False, True)):
        context = ToolRunSecurityContext(rung=rung, external_untrusted_context_seen=tainted,
                                         approval_gate_bypassed=bypass)
        for content in (_set("agent_max_rounds", 60), _set("max tool calls", 20),
                        json.dumps({"action": "reset", "key": "agent_max_tool_calls"})):
            assert context.decision_for("manage_settings", content).allowed is False
            assert context.asks_for("manage_settings", content) is True


def test_the_card_says_whose_limit_and_how_far(stored):
    stored({"agent_max_rounds": 30})
    decision = ToolRunSecurityContext().decision_for("manage_settings", _set("agent_max_rounds", 60))
    assert decision.reason == (
        "The assistant wants to raise the step limit you set, 30 steps, to 60 steps "
        "for this run. Only you can raise a limit you set, so it asks every time — "
        "even after you have allowed other actions.")
    assert decision.tripped_effects == ("admin_change",)


def test_a_cap_nobody_typed_is_raised_without_asking_on_the_default_rung(stored):
    """Full automation, as decided. The strict rungs still ask — not because
    of this row, but because `manage_settings` changes settings, which they
    ask about in a clean chat anyway."""
    stored({})
    content = _set("agent_max_rounds", 60)
    assert ToolRunSecurityContext().decision_for("manage_settings", content).allowed is True
    strict = ToolRunSecurityContext(rung=TrustRung.ASK_EVERY_TIME).decision_for(
        "manage_settings", content)
    assert strict.allowed is False and "confirm every effectful action" in strict.reason


@pytest.mark.parametrize("content", [
    _set("agent_max_rounds", 12), _set("agent_max_rounds", 30), _set("tts_voice", "af_sky"),
    json.dumps({"action": "get", "key": "agent_max_rounds"}), _set("agent_max_rounds", "lots"),
], ids=["lower", "same", "another-key", "a-read", "junk"])
def test_nothing_else_manage_settings_does_is_held_up_by_this(stored, content):
    stored({"agent_max_rounds": 30})
    assert ToolRunSecurityContext().decision_for("manage_settings", content).allowed is True


def test_the_card_seals_exactly_the_actions_own_effects(stored):
    """The escalation grants `admin_change`, which the tool already has, so an
    approval matches whatever the pin says by the time it is answered."""
    stored({"agent_max_rounds": 30})
    content = _set("agent_max_rounds", 60)
    assert capabilities_for_action("manage_settings", content).effects == \
        capabilities_for_tool("manage_settings").effects


def test_an_approved_raise_runs_once_on_the_run_it_resumes(stored, monkeypatch):
    stored({"agent_max_rounds": 30})
    monkeypatch.setattr(tool_execution, "_owner_is_admin", lambda owner: True)
    content = _set("agent_max_rounds", 60)
    store = ToolApprovalStore()
    context = ToolRunSecurityContext()
    decision = context.decision_for("manage_settings", content)
    pending = store.create(owner="alice", session_id="p7-12", origin_run_id=context.run_id,
                           tool_name="manage_settings", content=content, workspace=None,
                           external_untrusted_context_seen=False,
                           capabilities=capabilities_for_action("manage_settings", content),
                           gate_decision=decision)
    grant = store.consume(pending.approval_id, decision="approve_task", owner="alice",
                          session_id="p7-12")
    limits = _run_limits(round_limit=30, configured=30)

    async def replay():
        bind_run_limits(limits)
        from src.agent_tools import ToolBlock
        return await tool_execution.execute_tool_block(
            ToolBlock("manage_settings", content), session_id="p7-12", owner="alice",
            security_context=ToolRunSecurityContext(approval_gate_bypassed=True),
            exact_approval=grant)

    _, result = asyncio.run(replay())
    assert result["run_limit"]["outcome"] == RAISED
    assert limits.round_limit == 60


# ── through the real loop ───────────────────────────────────────────────────

def _drive(monkeypatch, replies, *, outputs=None):
    """The real loop and the real `manage_settings`; every other tool answers
    from `outputs` (a function of the call count), so a test controls whether a
    round brings anything new."""
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: None, raising=False)
    monkeypatch.setattr(agent_loop, "estimate_tokens", lambda *a, **k: 10, raising=False)
    monkeypatch.setattr(agent_loop, "blocked_tools_for_owner", lambda owner: set(), raising=False)
    monkeypatch.setattr(tool_execution, "_owner_is_admin", lambda owner: True)
    # The admin check the loop actually runs is the one in the globals of the
    # `execute_tool_block` it holds. In a full-suite run another file can leave
    # `src.tool_execution` re-imported, so the module this file imported and the
    # one that function reads are no longer the same object; patch the one that
    # is read. Measured: without this line, four of these cases failed in the
    # suite with "Tool 'manage_settings' requires an admin user." and passed alone.
    monkeypatch.setitem(agent_loop.execute_tool_block.__globals__, "_owner_is_admin",
                        lambda owner: True)
    scripted = iter(replies)

    async def fake_stream(*args, **kwargs):
        yield f"data: {json.dumps({'delta': next(scripted, 'Done.')})}\n\n"
        yield "data: [DONE]\n\n"

    real = agent_loop.execute_tool_block
    calls = {"n": 0}

    async def execute(block, *args, **kwargs):
        if block.tool_type == "manage_settings":
            return await real(block, *args, **kwargs)
        calls["n"] += 1
        text = outputs(calls["n"]) if outputs else "ok"
        return (block.tool_type, {"output": text, "exit_code": 0})

    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", fake_stream, raising=False)
    monkeypatch.setattr(agent_loop, "execute_tool_block", execute, raising=False)


def _events(**kwargs):
    kwargs.setdefault("relevant_tools", {"update_plan", "manage_settings"})
    kwargs.setdefault("owner", "alice")
    kwargs.setdefault("session_id", "p7-12-loop")

    async def go():
        return [c async for c in agent_loop.stream_agent_loop(
            "http://x/v1", "m", [{"role": "user", "content": "work"}], **kwargs)]

    out = []
    for chunk in asyncio.run(go()):
        if chunk.startswith("data: {"):
            out.append(json.loads(chunk[6:]))
    return out


def _plan(i):
    return '```update_plan\n{"plan":"- [ ] step %d"}\n```' % i


def _raise_to(n):
    return '```manage_settings\n{"action":"set","key":"agent_max_rounds","value":%d}\n```' % n


def _budget(events):
    return [e for e in events if e.get("type") == "agent_budget"]


def test_through_the_loop_a_raise_lengthens_the_run_that_asked(stored, monkeypatch):
    settings = stored({})
    _drive(monkeypatch, [_raise_to(22)] + [_plan(i) for i in range(2, 40)])
    events = _events(max_rounds=20, loop_caps_source=CAPS_FROM_SETTINGS)
    budget = _budget(events)
    assert budget[0]["round_limit"] == 20
    raised = next(e for e in budget if e["round_limit_source"] == "raised_for_run")
    assert (raised["round"], raised["round_limit"]) == (1, 22), "said the moment it was granted"
    assert max(e["round"] for e in budget) == 22, "it ran past 20"
    stop = next(e for e in events if e.get("type") == "rounds_exhausted")
    assert stop["rounds"] == 22
    assert settings.load_settings()["agent_max_rounds"] == 20, "and nothing was saved"


def test_through_the_loop_a_task_s_own_cap_is_not_moved(stored, monkeypatch):
    stored({})
    # More than Settings' 20, so a raise; a number under 20 would be a lowering
    # of the setting, which is saved as it always was.
    _drive(monkeypatch, [_raise_to(60)] + [_plan(i) for i in range(2, 20)])
    events = _events(max_rounds=3)   # a caller's cap: a task, a skill test
    assert {e["round_limit"] for e in _budget(events)} == {3}
    output = next(e for e in events if e.get("type") == "tool_output" and e["tool"] == "manage_settings")
    assert "was set by what started it, not by Settings" in output["output"]


def test_through_the_loop_an_owner_typed_cap_waits_for_the_person(stored, monkeypatch):
    settings = stored({"agent_max_rounds": 3})
    session = "p7-12-owner"
    _drive(monkeypatch, [_raise_to(6), "I will wait."])
    first = _events(max_rounds=3, loop_caps_source=CAPS_FROM_SETTINGS, session_id=session)
    assert {e["round_limit"] for e in _budget(first)} == {3}, "nothing moved before the yes"
    card = next(e["ask_user"] for e in first if e.get("type") == "tool_output"
                and (e.get("ask_user") or {}).get("kind") == "tool_approval")
    assert "raise the step limit you set, 3 steps, to 6 steps" in card["description"]

    grant = tool_approval_store.consume(card["approval_id"], decision="approve_task",
                                        owner="alice", session_id=session)
    _drive(monkeypatch, [_plan(i) for i in range(1, 20)])
    resumed = _events(max_rounds=3, loop_caps_source=CAPS_FROM_SETTINGS, session_id=session,
                      exact_approval=grant)
    budget = _budget(resumed)
    assert (budget[0]["round_limit"], budget[0]["round_limit_source"]) == (6, "raised_for_run")
    assert max(e["round"] for e in budget) == 6
    assert settings.load_settings()["agent_max_rounds"] == 3


# ── failsafe 3: the governor ────────────────────────────────────────────────

def _stops(events):
    return [e for e in events if e.get("type") == "loop_breaker_triggered"]


def test_a_narrated_loop_is_stopped_in_four_rounds(monkeypatch):
    """The same call, the same result and the same sentence, round after round.
    The stall detector resets on any text, so before this it ran to the cap."""
    _drive(monkeypatch, ["Checking the build again.\n" + _plan(1)] * 30)
    events = _events(max_rounds=30)
    stop = _stops(events)
    assert [s["kind"] for s in stop] == ["no_new_information"]
    assert stop[0]["round"] == 5 and stop[0]["rounds_without_new_information"] == 4
    assert stop[0]["message"].startswith("Stopped: 4 rounds in a row brought nothing new")
    assert not any(e.get("type") == "rounds_exhausted" for e in events)


def test_a_cycle_longer_than_the_stall_detectors_window_is_stopped(monkeypatch):
    """Seven calls in turn, forever, writing nothing: the stall detector keeps
    the last six round signatures, so the seventh is always "new" to it."""
    cycle = [_plan(i) for i in range(7)]
    _drive(monkeypatch, cycle * 6, outputs=lambda n: f"state {n % 7}")
    events = _events(max_rounds=40)
    stop = _stops(events)
    assert [s["kind"] for s in stop] == ["no_new_information"]
    assert stop[0]["round"] == 11


def test_a_run_that_keeps_learning_is_not_stopped(monkeypatch):
    """Round-count is not a loop signal: the same call whose result changes is
    a run making progress, narrated or not."""
    _drive(monkeypatch, ["Checking the build again.\n" + _plan(1)] * 12,
           outputs=lambda n: f"build {n * 7}% done")
    events = _events(max_rounds=12)
    assert _stops(events) == []
    assert any(e.get("type") == "rounds_exhausted" for e in events)


def test_a_raised_cap_is_still_governed(stored, monkeypatch):
    """The precondition, end to end: given 200 steps by itself, a stuck agent is
    stopped by the ledger, not by the cap."""
    stored({})
    _drive(monkeypatch, [_raise_to(200)] + ["Checking the build again.\n" + _plan(1)] * 60)
    events = _events(max_rounds=20, loop_caps_source=CAPS_FROM_SETTINGS)
    assert max(e["round_limit"] for e in _budget(events)) == 200
    stop = _stops(events)
    assert [s["kind"] for s in stop] == ["no_new_information"]
    # The raise (round 1), one new call (round 2), then three rounds with
    # nothing new: stopped at round 6, not at 200.
    assert stop[0]["round"] == 6


# ── the meter says it, and so does the promise before the run ──────────────

_RAISED = {"type": "agent_budget", "round": 21, "round_limit": 60,
           "round_limit_source": "raised_for_run", "round_limit_configured": 20,
           "tool_calls": 4, "tool_call_limit": 30, "tool_call_limit_source": "raised_for_run"}


@node_only
def test_the_meter_says_the_run_was_given_more_and_nothing_was_saved(meter_sandbox):
    out = _run(meter_sandbox, _METER_PREAMBLE, """
        const meter = m.createAgentMeter({ document, setInterval: () => 1, clearInterval: () => {} });
        meter.update(%s);
        meter.update({ ...%s, tool_call_limit: null });
        const first = read(meter.node);
        console.log(JSON.stringify({ first }));
    """ % (json.dumps(_RAISED), json.dumps(_RAISED)))
    shown = out["first"]
    assert shown["steps"] == "Step 21 of 60 · raised for this run"
    assert shown["tools"] == "Tool calls 4 · limit removed for this run"
    assert shown["note"] == ("Raised to 60 steps for this run — nothing saved · "
                             "Tool-call limit removed for this run — nothing saved")
    assert "raised this run's step limit from 20 to 60, for this run only; nothing was saved" \
        in shown["budgetTitle"]
    assert [b["hidden"] for b in shown["bars"] if b["kind"] == "steps"] == [False], \
        "a raised limit is a real number, so it keeps its bar"


@node_only
@pytest.mark.parametrize("raise_,expect", [
    ("without_asking", "stops after step 20 and offers Continue. The assistant may raise it "
                       "for one run, up to 200 steps, without asking; it is stopped sooner if "
                       "a few rounds in a row bring nothing new."),
    ("asks_you", "The assistant has to ask you before it raises a step limit you set."),
])
def test_before_the_run_the_hint_says_who_may_raise_it(hint_sandbox, raise_, expect):
    payload = {"round_limit": 20, "round_limit_source": "configured", "round_limit_configured": 20,
               "tool_call_limit": 10, "round_limit_raise": raise_, "round_limit_raise_ceiling": 200,
               "tool_call_limit_raise": "asks_you"}
    out = _run(hint_sandbox, _HINT_PREAMBLE, """
        console.log(JSON.stringify(m.limitsPreview(%s)));
    """ % json.dumps(payload))
    assert expect in out["title"]
    assert out["title"].endswith("It has to ask you before it raises the tool-call limit. "
                                 "Both are set in Settings › Agent Tools.")


def test_the_promise_and_the_card_agree_about_whose_limit_it_is(stored, monkeypatch):
    """The route says *asks you* exactly when the gate would ask."""
    import routes.chat_routes as chat_routes
    from test_the_run_limits_are_said_before_it_runs import _limits, _limits_endpoint

    monkeypatch.setattr(chat_routes, "effective_user", lambda request: "alice")
    for values in ({}, {"agent_max_rounds": 30}):
        stored(values)
        answer = _limits(_limits_endpoint(), endpoint_id="", endpoint_url="")
        asks = not ToolRunSecurityContext().decision_for(
            "manage_settings", _set("agent_max_rounds", 150)).allowed
        assert answer["round_limit_raise"] == ("asks_you" if asks else "without_asking")
