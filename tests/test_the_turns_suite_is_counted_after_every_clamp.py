# SPDX-License-Identifier: AGPL-3.0-or-later
"""A turn's suite is counted after every clamp, and a failed plan is not a bare turn.

`fx11-order`. Two defects, both found by driving the real loop against the
`pantheon-qwen3` finetune's own routes and reading what the turn says about
itself rather than what it offers.

**1 — the ordering.** `plan_turn_tool_suite` runs at `src/agent_loop.py:6847`
and computes `candidates = (selectable_tool_names() | mcp) - disabled_tools`.
The `pantheon-qwen3` general-no-tool clamp writes `known_tool_names()` into
`disabled_tools` at `:7253`, **after** it. Measured on `bbe6958` by driving the
real loop with `model="pantheon-qwen3-8b"` and spying on
`plan_turn_tool_suite`, `_assemble_prompt` and `src.events.record_run_config`:

    cell                           plan      cap@plan  cap@prompt  receipt   notice
    mcp=up   admin  general       81/81      2         85          0/81      0/2
    mcp=absent admin general      79/79      2         85          0/79      —
    mcp=up   user   general       31/31      53        85          0/31      —
    mcp=up   admin  notes         81/81      2         2           5/81      19/81
    mcp=up   admin  CONTROL       81/81      2         2           81/81     —

So on a general-no-tool turn the two records of *"how many tools did this
person have"* — the receipt an operator reads and the sentence the prompt
builder writes — differ by **79**, on the same turn, from the same plan
(`Law 7`: one source of truth; `Law 10`: a field with two readings). The
receipt's own `candidates` is documented as *"every name the person's
privileges allow this turn"* and the turn's cap withheld 85 of them.

**Two things the brief for this lane had wrong, and `Law 3` cuts both ways:**

  * **Of the three writers that run after the planner, only one moves the
    cap.** The notes clamp (`:7249`) and the answering route's notes clamp
    (`:8789`) are `TurnToolAccess.lift()` calls, and after `fx11-cap` they lift
    **0 names** in all eight cells driven here — for an admin none of the three
    managers is withheld, and for a non-admin `lift()` refuses the privilege
    reason. `cap@plan == cap@prompt` on every notes row above.
  * **The partial-suite notice does not reach the model on such a turn.**
    `_build_route_request_state` replaces `route_messages` wholesale with
    `_minimal_pantheon_general_messages` for any `pantheon-qwen3` route, so the
    assembled prompt — notice and all — is discarded. The notice reaches the
    model on a `pantheon-qwen3` turn only in **plan mode**, which is the one
    state that stands the fixed prompt down while the clamps still run. Both
    facts are pinned below, because a later lane that removes the fixed-prompt
    branch must meet them.

**2 — the fallback.** `_tool_suite`'s exception handler says it *"fails back
onto the path that was here before: the selectors below still run"*. There is
one selector below it, not several: `_TOOL_RETRIEVAL_SELECTS_THE_TURN` is
`False`, so the vector block is skipped and only the keyword fallback runs.
Measured on `bbe6958` with `plan_turn_tool_suite` raising, the probe's ordinary
turn, `emb=down mcp=up win=large mode=agent`:

    who     planner ok            planner raises
    admin   81 offered, 76 array  **4** offered, 6 array
    user    31 offered, 31 array  **2** offered, 2 array

A fallback written for the regime where retrieval chose the turn is **twenty
times narrower** than the thing it falls back from, and the one record an
operator could read it in is not written at all: `_tool_suite = None` skips the
receipt entirely.

`Law 1` throughout: nothing here lifts a gate. The general-no-tool clamp still
withholds every name `known_tool_names()` holds, the notes clamp still cannot
lift a privilege, and the conservative retry is the planner's own
`window_unknown` branch — the candidates it draws from already have every cap
subtracted.
"""
import asyncio
import os

import pytest

from tests.helpers import tool_suite_probe as probe

QWEN = probe.FINETUNE_MODELS["large"]

GENERAL = probe.ORDINARY_TURN
NOTES = "add a note to buy milk and put it on my todo list"

#: `Law 6`. Measured on `bbe6958` by the script in `/work/notes/fx11-order.md`.
#: Quoted so a reader sees what the cases were written from; the assertions
#: below are written against the product's own registers, not against these.
MEASURED_ON_BBE6958 = {
    ("general", "admin", "up"): dict(plan=81, cap_at_plan=2, cap_at_prompt=85,
                                     receipt_candidates=81, notice=(0, 2)),
    ("general", "admin", "absent"): dict(plan=79, cap_at_plan=2, cap_at_prompt=85,
                                         receipt_candidates=79, notice=None),
    ("general", "user", "up"): dict(plan=31, cap_at_plan=53, cap_at_prompt=85,
                                    receipt_candidates=31, notice=None),
}

#: What the keyword fallback offers an admin on the ordinary turn when the
#: planner raises, and what the planner offers when it does not.
FALLBACK_ON_BBE6958 = {"admin": (81, 4), "user": (31, 2)}


# ── one world, every turn driven once ───────────────────────────────────────

@pytest.fixture(scope="module")
def measured(tmp_path_factory):
    """Drive every turn this file asks about, once, in one event loop.

    A `probe_world` owns a real stdio MCP server whose session belongs to the
    loop that opened it (`B880`), so the whole collection runs inside a single
    `asyncio.run`. The cases below read the cache.
    """
    scratch = str(tmp_path_factory.mktemp("order"))

    async def collect():
        out = {}
        async with probe.probe_world(scratch, mcp_states=("up", "absent")) as world:
            import src.agent_loop as al

            def cell(who, mcp):
                return probe.Cell(embeddings="down", mcp=mcp, window="large",
                                  mode="agent", privilege=who)

            for who in ("admin", "user"):
                for mcp in ("up", "absent"):
                    out[("general", who, mcp)] = await probe.suite_order(
                        world, cell(who, mcp), GENERAL, model=QWEN)
                out[("notes", who, "up")] = await probe.suite_order(
                    world, cell(who, "up"), NOTES, model=QWEN)
                out[("notes_plan", who, "absent")] = await probe.suite_order(
                    world, cell(who, "absent"), NOTES, model=QWEN, plan_mode=True)
                out[("control", who, "up")] = await probe.suite_order(
                    world, cell(who, "up"), GENERAL)

            # The fallback: the planner raises, and then raises twice.
            real_plan = al.plan_turn_tool_suite
            calls = {"n": 0}

            def raise_once(*a, **k):
                calls["n"] += 1
                if calls["n"] == 1:
                    raise RuntimeError("probe: the planner could not read a window")
                return real_plan(*a, **k)

            def raise_always(*a, **k):
                raise RuntimeError("probe: the planner could not read a window")

            for who in ("admin", "user"):
                out[("plan_ok", who, "up")] = await probe.offer_channel_gap(
                    world, cell(who, "up"))
                calls["n"] = 0
                al.plan_turn_tool_suite = raise_once
                try:
                    out[("plan_raises", who, "up")] = await probe.suite_order(
                        world, cell(who, "up"), GENERAL)
                finally:
                    al.plan_turn_tool_suite = real_plan
                al.plan_turn_tool_suite = raise_always
                try:
                    out[("plan_raises_twice", who, "up")] = await probe.suite_order(
                        world, cell(who, "up"), GENERAL)
                finally:
                    al.plan_turn_tool_suite = real_plan
        return out

    return asyncio.run(collect())


# ── 1. the ordering: one denominator, taken after every clamp ───────────────

@pytest.mark.parametrize("who,mcp", [("admin", "up"), ("admin", "absent"),
                                     ("user", "up"), ("user", "absent")])
def test_the_receipt_counts_only_what_the_turn_could_call(measured, who, mcp):
    """`candidates` is *"every name the person's privileges allow this turn"*.

    On a general-no-tool turn the cap withholds every name
    `known_tool_names()` holds, so the honest denominator is what survives it —
    the operator-registered MCP names and nothing else. Red on `bbe6958` with
    79, 81 and 31.
    """
    order = measured[("general", who, mcp)]
    # The honest denominator, computed here from the product's own two objects:
    # what the plan counted, minus what the cap held when the prompt was built.
    honest = len(set(order.plan_withheld) | set(order.receipt.get("withheld") or [])
                 | set(order.receipt.get("capped_after_plan") or [])
                 | set(order.prompt_tool_names)) - len(
        set(order.cap_at_prompt_names) & (
            set(order.plan_withheld) | set(order.receipt.get("withheld") or [])
            | set(order.receipt.get("capped_after_plan") or [])))
    got = int(order.receipt.get("candidates") or 0)
    assert got == honest, (
        f"the receipt says this turn had {got} tools; the plan counted "
        f"{order.plan_candidates} and the cap held {order.cap_at_prompt} names "
        f"by the time the prompt was built, leaving {honest}")
    assert got < order.plan_candidates, (
        "the clamp withheld every known tool after the plan, so the receipt's "
        "denominator cannot still be the plan's")


@pytest.mark.parametrize("who,mcp", [("admin", "up"), ("admin", "absent"),
                                     ("user", "up"), ("user", "absent")])
def test_the_receipt_and_the_notice_state_one_denominator(measured, who, mcp):
    """`Law 7`. Two records of one fact, so they cannot differ.

    Red on `bbe6958` for `mcp=up admin`: the notice said *"0 of your 2"* and
    the receipt said `candidates: 81`.
    """
    order = measured[("general", who, mcp)]
    if order.notice_numbers is None:
        pytest.skip("no notice computed on this cell; the other cases cover it")
    assert order.notice_numbers[1] == int(order.receipt.get("candidates") or 0)


@pytest.mark.parametrize("who", ["admin", "user"])
def test_what_the_cap_withheld_after_the_plan_is_named_not_lost(measured, who):
    """`Law 1` — the 79 names the old receipt listed are still in the record.

    They move to a key that says what they are, because a `withheld` list
    longer than `candidates` has two readings and neither is checkable.
    """
    order = measured[("general", who, "up")]
    capped = order.receipt.get("capped_after_plan")
    assert capped, "the names the clamp withheld after the plan are not recorded"
    assert len(capped) == order.plan_candidates - int(order.receipt["candidates"])
    from src.tool_policy import known_tool_names
    # `B1397` widened the clamp by the turn's own MCP names, so what it
    # withheld after the plan is the built-in register plus `mcp__*` spellings
    # and nothing else.
    assert {n for n in set(capped) - set(known_tool_names())
            if not n.startswith("mcp__")} == set()


@pytest.mark.parametrize("who", ["admin", "user"])
def test_an_ordinary_turns_receipt_does_not_move(measured, who):
    """The guard, and `Law 6`'s before/after: a turn with no clamp after the
    plan reports exactly what it reported on `bbe6958` — the whole suite, no
    `capped_after_plan`, `reason=whole_suite`."""
    order = measured[("control", who, "up")]
    assert int(order.receipt["candidates"]) == order.plan_candidates
    assert int(order.receipt["offered"]) == order.plan_offered
    assert order.receipt["reason"] == "whole_suite"
    assert not order.receipt.get("capped_after_plan")
    assert not order.receipt.get("withheld")


@pytest.mark.parametrize("who", ["admin", "user"])
def test_the_notes_clamp_moves_no_denominator(measured, who):
    """`Law 3`, against the brief for this lane. The notes clamp is a `lift()`
    and after `fx11-cap` it lifts nothing, so the cap is the same size at the
    plan and at the prompt and the receipt's denominator is the plan's."""
    order = measured[("notes", who, "up")]
    assert order.cap_at_plan == order.cap_at_prompt
    assert int(order.receipt["candidates"]) == order.plan_candidates


# ── 2. where the notice does and does not reach the model ───────────────────

@pytest.mark.parametrize("who", ["admin", "user"])
def test_the_notice_does_not_reach_a_finetunes_prompt(measured, who):
    """`Law 3`. The brief said the notice is in the prompt on this turn. It is
    not: `_build_route_request_state` replaces `route_messages` with
    `_minimal_pantheon_general_messages` for every `pantheon-qwen3` route, so
    the assembled prompt is discarded. Pinned, so that a lane which removes the
    fixed-prompt branch has to decide what the notice then says."""
    order = measured[("general", who, "up")]
    assert order.notice_reached_model is False
    assert "tool set is partial" not in order.prompt


@pytest.mark.parametrize("who", ["admin", "user"])
def test_the_notice_reaches_the_model_in_plan_mode_and_agrees_with_the_receipt(
        measured, who):
    """Plan mode is the one `pantheon-qwen3` state that keeps the assembled
    prompt, so it is the turn where the sentence is read by the model. Its two
    numbers are the receipt's denominator and the count of what the prompt
    actually named."""
    order = measured[("notes_plan", who, "absent")]
    assert order.notice_reached_model is True
    assert order.notice_numbers is not None
    assert order.notice_numbers[1] == int(order.receipt["candidates"])


@pytest.mark.parametrize("who,mcp", [("admin", "up"), ("user", "up"),
                                     ("admin", "absent"), ("user", "absent")])
def test_nothing_is_offered_on_a_general_no_tool_turn(measured, who, mcp):
    """The guard the whole lane rests on (`Law 1`): the cost of the ordering
    was a record, never an offer. The array is empty and the prompt builder is
    handed no name, before and after."""
    order = measured[("general", who, mcp)]
    assert order.array == []
    assert order.prompt_tool_names == []


# ── 3. the fallback when the plan raises ────────────────────────────────────

@pytest.mark.parametrize("who", ["admin", "user"])
def test_a_planner_exception_does_not_drop_the_turn_to_its_floor(measured, who):
    """Red on `bbe6958`: 81 offered became **4**, and 31 became **2**.

    The retry is the planner's own `window_unknown` branch, so what it offers
    is a plan and not a floor — and it is bounded by the conservative room the
    product already applies to an endpoint that reports no window.
    """
    order = measured[("plan_raises", who, "up")]
    floor = measured[("plan_raises_twice", who, "up")]
    assert len(order.prompt_tool_names) > len(floor.prompt_tool_names), (
        f"a planner exception left this turn with {order.prompt_tool_names}, "
        f"the same floor the keyword selector gives ({floor.prompt_tool_names})")
    assert order.plan_reason == "window_unknown", (
        "the retry must be the planner's own conservative branch, and say so")
    # And bounded by it: a retry that offered every candidate would be a turn
    # built against a window nobody read, which is what the branch exists to
    # avoid. `partial` is the planner's own word for that.
    whole = measured[("plan_ok", who, "up")]
    assert order.plan_partial is True
    assert len(order.prompt_tool_names) < len(whole.offered), (
        "the conservative retry must narrow, not offer the whole suite against "
        f"an unread window: {len(order.prompt_tool_names)} vs {len(whole.offered)}")


@pytest.mark.parametrize("who", ["admin", "user"])
def test_a_planner_exception_still_writes_a_receipt(measured, who):
    """`Law 10`, in the one record an operator reads to find out why a tool was
    withheld. Red on `bbe6958`: `_tool_suite = None` skipped the receipt, so
    the turn that narrowed most wrote nothing down."""
    order = measured[("plan_raises", who, "up")]
    assert order.receipt, "no suite receipt on the turn whose plan failed"
    assert order.receipt["reason"] in ("window_unknown", "route")


@pytest.mark.parametrize("who", ["admin", "user"])
def test_the_last_resort_is_still_the_keyword_selector(measured, who):
    """`Law 1`. The path that was there before survives: when the retry fails
    too, the keyword fallback runs exactly as it did, and the turn is not left
    with no tools."""
    order = measured[("plan_raises_twice", who, "up")]
    assert order.receipt == {}
    assert order.prompt_tool_names, "the keyword fallback must still floor the turn"
    from src.tool_index import ALWAYS_AVAILABLE
    assert set(ALWAYS_AVAILABLE) & set(order.prompt_tool_names)


@pytest.mark.parametrize("who", ["admin", "user"])
def test_the_fallback_offers_nothing_the_turn_may_not_call(measured, who):
    """`Law 1`, the direction that matters: a retry is not a widening. Every
    name it offers is a name the turn's own cap allows."""
    from src.tool_policy import selectable_tool_names
    from src.tool_security import NON_ADMIN_BLOCKED_TOOLS
    for key in (("plan_raises", who, "up"), ("plan_raises_twice", who, "up")):
        order = measured[key]
        offered = set(order.prompt_tool_names)
        unknown = offered - set(selectable_tool_names())
        assert not {n for n in unknown if not n.startswith("mcp__")}, unknown
        if who == "user":
            assert not (offered & set(NON_ADMIN_BLOCKED_TOOLS)), (
                "the retry offered a non-admin a tool their privileges refuse: "
                f"{sorted(offered & set(NON_ADMIN_BLOCKED_TOOLS))}")


# ── 4. `Law 1` — the gates the reordering must not have touched ─────────────

@pytest.mark.parametrize("who", ["admin", "user"])
def test_the_general_no_tool_clamp_still_withholds_every_known_tool(measured, who):
    """The clamp itself is untouched: at prompt time the cap holds every name
    `known_tool_names()` returns, whatever the receipt now says."""
    from src.tool_policy import known_tool_names
    order = measured[("general", who, "up")]
    assert order.cap_at_prompt >= len(set(known_tool_names()))


def test_the_general_no_tool_clamp_withholds_the_operators_mcp_tools_too(measured):
    """`B1397`. `known_tool_names()` holds no `mcp__*` spelling, so with a real
    MCP server up the clamp's cap held 85 names and neither probe tool — the
    route clamp's literal was the only thing withholding them. Red before the
    clamp withheld the turn's own MCP names as well.

    The MCP names are read off the control turn (same admin, same server, no
    clamp), where the whole suite is offered, so the test does not name them
    itself.
    """
    control = measured[("control", "admin", "up")]
    mcp_names = {n for n in control.prompt_tool_names if n.startswith("mcp__")}
    assert mcp_names, "the probe's MCP server offered nothing on the control turn"
    order = measured[("general", "admin", "up")]
    assert mcp_names <= set(order.cap_at_prompt_names), (
        f"the no-tool clamp left {sorted(mcp_names - set(order.cap_at_prompt_names))} "
        "outside the turn's cap")
    # And still nothing is offered (`Law 1`: a narrowing of nothing).
    assert order.array == []


def test_the_notes_clamp_still_cannot_lift_a_privilege(measured):
    """`fx11-cap`'s `B1348`, re-asked here because this lane reorders records
    around that clamp: a non-admin's notes turn is not offered
    `manage_calendar` or `manage_tasks`."""
    order = measured[("notes", "user", "up")]
    # Asked of the cap and of the request, not of `_assemble_prompt`'s first
    # argument: `_ADMIN_PROMPT_FORCE_INCLUDE` puts `manage_tasks` there on any
    # turn whose text trips `_ADMIN_KEYWORDS`, and the prompt builder's own
    # subtraction is what removes it (`fx11-cap`'s `B1350`).
    assert {"manage_calendar", "manage_tasks"} <= set(order.cap_at_prompt_names)
    assert "manage_calendar" not in order.array
    assert "manage_tasks" not in order.array


def test_lift_still_refuses_a_privilege():
    """The guarantee is a property of the type and must stay one — a unit case,
    because the whole reordering is only safe while this holds."""
    from src.tool_policy import (TurnToolAccess, WITHHELD_BY_PRIVILEGE,
                                 WITHHELD_BY_TURN)

    access = TurnToolAccess()
    access.withhold({"manage_tasks"}, because=WITHHELD_BY_PRIVILEGE)
    access.withhold({"manage_notes"}, because=WITHHELD_BY_TURN)
    access.lift({"manage_tasks", "manage_notes"}, because="a probe")
    assert "manage_tasks" in access
    assert "manage_notes" not in access


# ── 5. the tally, as a unit ─────────────────────────────────────────────────

def test_the_stored_row_keeps_both_lists(monkeypatch):
    """`Law 20` — call the thing.

    Every case above reads the dict the loop *handed* `record_run_config`,
    which cannot tell whether the receipt actually stores it. This one drives
    the recorder and reads the row it wrote: both lists are there, sorted and
    de-duplicated, and `capped_after_plan` is absent from no suite row.
    """
    import src.events as ev

    written = []
    monkeypatch.setattr(ev, "record_event",
                        lambda *a, **k: written.append(k) or True)
    ev.record_run_config(suite={
        "offered": 1, "candidates": 2, "withheld": ["b", "b", ""],
        "capped_after_plan": ["z", "a", "a", ""], "reason": "route",
    })
    stored = written[0]["detail"]["suite"]
    assert stored["withheld"] == ["b"]
    assert stored["capped_after_plan"] == ["a", "z"], (
        "the names the clamp withheld after the plan have to survive the store, "
        f"not just the call: {stored}")
    written.clear()
    ev.record_run_config(suite={"offered": 0, "candidates": 0})
    assert written[0]["detail"]["suite"]["capped_after_plan"] == []


def test_the_tally_is_taken_against_the_cap_it_is_given():
    """One function answers both records, so it is asked directly too."""
    import src.agent_loop as al
    from src.tool_index import ToolSuite
    from src.tool_policy import TurnToolAccess, WITHHELD_BY_TURN

    suite = ToolSuite(candidates=frozenset({"a", "b", "c"}),
                      offered=frozenset({"a", "b", "c"}), reason="whole_suite")
    cap = TurnToolAccess()
    cap.withhold({"b", "c"}, because=WITHHELD_BY_TURN)
    tally = al._suite_tally(suite, {"a"}, cap)
    assert tally["candidates"] == ["a"]
    assert tally["offered"] == ["a"]
    assert tally["withheld"] == []
    assert tally["capped_after_plan"] == ["b", "c"]
    assert tally["reason"] == "route"
    assert al._suite_tally(None, {"a"}, cap) is None
