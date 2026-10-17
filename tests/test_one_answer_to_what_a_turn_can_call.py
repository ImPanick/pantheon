# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1348` … `B1351` (fx11-cap): one answer to *"what can this turn call?"*

The owner, 2026-10-14: *"The LLM's use of tools is still very much
intermittent... even with its own MCP's provided."* `fx9`/`fx10` answered the
**selection** half. This file is about the other half — a tool that reaches the
turn's set and still cannot be called — and about the set that decides it.

`stream_agent_loop` built a plain `set` named `disabled_tools`, wrote to it from
ten places and read it in thirteen, each reader writing the subtraction out
again. Measured on `747cda6` by driving the real loop with
`relevant_tools={"ask_user","update_plan"}`, real accounts from
`tests/helpers/signed_in.people`, and a spy on `_assemble_prompt`:

```
privilege                cap   notes
anonymous                 53   `manage_memory` capped — and it is in
                               `tool_index.ALWAYS_AVAILABLE`, which four
                               selection sites pinned unconditionally
registered non-admin      53   identical to anonymous
admin                      2   `computer`, `generate_image`
delegated credential      54   + `manage_documents` (`B995`)
plan mode (admin)         56
guide-only (admin)        85
```

and three things that set could not say:

* the loop's set and the prompt's set were **different sets** —
  `_build_base_prompt` added `generate_image` to a local copy, so the prompt
  withheld a tool the native schema list (which filters by the loop's set) then
  sent (`B1349`);
* nothing recorded **why** a name was withheld, so `_pan_notes_finetune_mode`'s
  `difference_update` lifted a privilege cap: on a `pantheon-qwen3` notes turn
  an anonymous visitor's cap went 52 → 50 and `manage_calendar`/`manage_tasks`
  were named in the prompt and sent as schemas, with every call refused by the
  dispatcher's own gate (`B1348`);
* a name could be in `relevant_tools` **and** in the cap at once, and only
  `B1366`'s two gates ever noticed (`B1350`).

Everything below drives the product (`Law 20`): the real `stream_agent_loop`,
real accounts, the model and the dispatcher scripted at the two seams
`tests/helpers/tool_suite_probe.drive_turn` uses and nothing else. Every
expected set is derived from `src/tool_security.py`'s own registers rather than
retyped (`Law 6`).
"""

from __future__ import annotations

import asyncio
import json

import pytest

import src.agent_loop as al
import src.tool_security as ts
from src.tool_index import ALWAYS_AVAILABLE
from src.tool_policy import (
    LIFTABLE_REASONS,
    TurnToolAccess,
    WITHHELD_BY_CALLER,
    WITHHELD_BY_FEATURE,
    WITHHELD_BY_PLAN_MODE,
    WITHHELD_BY_POLICY,
    WITHHELD_BY_PRIVILEGE,
    WITHHELD_BY_STEP_TOOLS,
    WITHHELD_BY_TURN,
    WITHHELD_UNATTRIBUTED,
    build_effective_tool_policy,
    turn_tool_access,
)
from tests.helpers.signed_in import ADMIN, MEMBER, signed_in


# ── the harness: the real loop, two seams, every input stated ───────────────

#: Every tool the suite planner would consider, so a turn's cap is the only
#: thing deciding what is offered.
WIDE = {"ask_user", "update_plan", "manage_memory", "read_file", "bash",
        "manage_skills", "manage_calendar", "manage_tasks", "manage_notes",
        "generate_image", "web_search", "create_document"}


class Turn:
    """What one turn of the real loop was handed and what it sent."""

    def __init__(self):
        self.prompts: list = []      # (tool_names, disabled) per `_assemble_prompt`
        self.loop_caps: list = []    # the loop's own set, per `_build_base_prompt`
        # `B1399`. The live object, not a copy of its members: the reasons are
        # the thing under test once `caller` is liftable, and `set(...)` drops
        # them. `loop_caps` stays as it was, because every case above reads it.
        self.loop_access: list = []
        self.schemas: list = []      # the `tools` array per request
        self.events: list = []

    @property
    def cap(self) -> set:
        return set(self.loop_caps[0]) if self.loop_caps else set()

    @property
    def prompt_cap(self) -> set:
        return set(self.prompts[0][1]) if self.prompts else set()

    @property
    def selected(self) -> set:
        """The names the prompt was asked to describe — `relevant_tools` plus
        the loop's two irreducible primitives."""
        return set(self.prompts[0][0]) if self.prompts else set()

    @property
    def text(self) -> str:
        return self.prompts[0][2] if self.prompts else ""

    def offered(self) -> set:
        return self.selected - self.prompt_cap

    def sent(self) -> set:
        return set(self.schemas[0]) if self.schemas else set()


def run_turn(monkeypatch, tmp_path, *, owner, user="what is the capital of france?",
             relevant_tools=("ask_user", "update_plan"), model="mistral-7b",
             plan_mode=False, guide_only=False, delegated=False,
             image_gen=False, skills=False, settings=None,
             disabled_tools=None) -> Turn:
    """Drive `stream_agent_loop` once. Nothing is inherited from the container.

    `signed_in` is the one way a test in this tree is a person
    (`D-2026-10-07-02` §2), so `owner_is_admin_or_single_user` in the loop and
    `_owner_is_admin` in the dispatcher answer about the same two accounts.
    `owner=None` is the anonymous turn — nobody signed in — which is what the
    brief's own measurement drove.
    """
    signed_in(monkeypatch, tmp_path / "auth")
    rec = Turn()

    stored = dict(settings or {})
    stored.setdefault("image_gen_enabled", bool(image_gen))

    def fake_setting(key, default=None):
        return stored.get(key, default)

    monkeypatch.setattr(al, "get_setting", fake_setting, raising=False)
    monkeypatch.setattr(al, "get_mcp_manager", lambda: None, raising=False)
    monkeypatch.setattr(al, "estimate_tokens", lambda *a, **k: 10, raising=False)
    # `B1366`'s lesson, restated: a loop-control test that inherits this is a
    # test about the tree's `data/` directory, which carries 286 skills.
    monkeypatch.setattr(al, "_skills_pref_enabled", lambda o: bool(skills), raising=False)

    real_assemble = al._assemble_prompt

    def assemble_spy(tool_names, disabled_tools=None, compact=False, suite_notice=""):
        out = real_assemble(tool_names, disabled_tools, compact, suite_notice)
        rec.prompts.append((set(tool_names or ()), set(disabled_tools or ()), out))
        return out

    monkeypatch.setattr(al, "_assemble_prompt", assemble_spy, raising=False)

    real_base = al._build_base_prompt

    def base_spy(disabled_tools, *a, **k):
        rec.loop_caps.append(set(disabled_tools or ()))
        rec.loop_access.append(disabled_tools)
        return real_base(disabled_tools, *a, **k)

    monkeypatch.setattr(al, "_build_base_prompt", base_spy, raising=False)

    async def scripted(_candidates, messages, **kwargs):
        rec.schemas.append(sorted(
            (t.get("function") or {}).get("name")
            for t in (kwargs.get("tools") or [])
            if (t.get("function") or {}).get("name")))
        yield "data: " + json.dumps({"delta": "Done."}) + "\n\n"
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(al, "stream_llm_with_fallback", scripted, raising=False)

    async def boundary(block, *a, **k):
        return block.tool_type, {"output": "ok", "exit_code": 0}

    monkeypatch.setattr(al, "execute_tool_block", boundary, raising=False)

    policy = None
    if guide_only:
        policy = build_effective_tool_policy(last_user_message="do not use any tools")

    async def collect():
        async for chunk in al.stream_agent_loop(
            "http://127.0.0.1:1/v1", model,
            [{"role": "user", "content": user}],
            max_rounds=1,
            owner=owner,
            relevant_tools=set(relevant_tools) if relevant_tools else None,
            plan_mode=plan_mode,
            delegated_credential=delegated,
            tool_policy=policy,
            # `B1399`. A caller that already attributed its names hands the
            # `TurnToolAccess` over and the loop keeps it; this lets a case
            # drive that seam instead of asserting it off the source.
            **({"disabled_tools": disabled_tools} if disabled_tools is not None else {}),
        ):
            if chunk.startswith("data: ") and not chunk.startswith("data: [DONE]"):
                try:
                    rec.events.append(json.loads(chunk[6:]))
                except Exception:
                    pass

    asyncio.run(collect())
    assert rec.prompts, "the loop never assembled a prompt"
    return rec


# ── group A — question 1: the cap at each privilege ─────────────────────────

def test_the_anonymous_and_the_non_admin_cap_is_the_non_admin_register(monkeypatch, tmp_path):
    """The 53 names on the brief's anonymous turn, derived rather than retyped.

    `owner=None` is not an admin and neither is a registered member, so both
    get `NON_ADMIN_BLOCKED_TOOLS` plus the two per-turn gates this install has:
    no workstation (`computer`) and no image backend (`generate_image`).
    """
    expected = (set(ts.NON_ADMIN_BLOCKED_TOOLS)
                | {"computer"} | set(ts.setting_disabled_tools(lambda k, d=None: d)))
    anon = run_turn(monkeypatch, tmp_path / "a", owner=None)
    member = run_turn(monkeypatch, tmp_path / "b", owner=MEMBER)
    assert anon.cap == expected, sorted(expected ^ anon.cap)
    assert member.cap == anon.cap, sorted(member.cap ^ anon.cap)
    # The brief's number, stated with its scope so a future reader can re-derive
    # it: 51 non-admin names + `computer` + `generate_image`.
    assert len(anon.cap) == len(ts.NON_ADMIN_BLOCKED_TOOLS) + 2


def test_an_admin_is_capped_only_by_what_this_install_cannot_do(monkeypatch, tmp_path):
    admin = run_turn(monkeypatch, tmp_path, owner=ADMIN)
    assert admin.cap == {"computer", "generate_image"}, sorted(admin.cap)
    assert not (admin.cap & set(ts.NON_ADMIN_BLOCKED_TOOLS))


def test_a_delegated_credential_is_the_non_admin_cap_plus_its_own(monkeypatch, tmp_path):
    """`B70`/`B995`. The token's owner IS an admin — minting is admin-only — so
    the cap cannot come from the owner, and it does not."""
    token = run_turn(monkeypatch, tmp_path / "t", owner=ADMIN, delegated=True)
    admin = run_turn(monkeypatch, tmp_path / "a", owner=ADMIN)
    assert token.cap == (admin.cap | set(ts.NON_ADMIN_BLOCKED_TOOLS)
                         | set(ts.DELEGATED_CREDENTIAL_ONLY_BLOCKED_TOOLS))
    assert "manage_documents" in token.cap and "manage_documents" not in admin.cap


def test_plan_mode_and_guide_only_cap_more_than_the_non_admin_policy(monkeypatch, tmp_path):
    """Both are `FORBIDDEN.md` Part 2 controls and both must stay the widest
    caps there are: plan mode's inverse allowlist, guide-only's whole register."""
    plan = run_turn(monkeypatch, tmp_path / "p", owner=ADMIN, plan_mode=True)
    guide = run_turn(monkeypatch, tmp_path / "g", owner=ADMIN, guide_only=True)
    assert set(ts.plan_mode_disabled_tools()) <= plan.cap
    assert "update_plan" in plan.cap and "bash" in plan.cap
    from src.tool_policy import known_tool_names
    assert set(known_tool_names()) <= guide.cap
    assert len(guide.cap) > len(plan.cap) > 2


# ── group B — question 2: is `ALWAYS_AVAILABLE` ever capped? ────────────────

def test_always_available_names_one_tool_the_privilege_cap_withholds():
    """The disagreement, stated as the fact it is.

    `ALWAYS_AVAILABLE` is the three tools the selector pins unconditionally.
    One of them, `manage_memory`, is in `NON_ADMIN_BLOCKED_TOOLS`. Two parts of
    the product therefore disagree about the same tool on every non-admin turn,
    and this case pins **which one is right**: the cap. `manage_memory` writes
    the long-term memory every later turn is fed, and `FORBIDDEN.md` Part 2 as
    amended by `D-2026-10-09-01` names it a privileged effect at the write —
    the place the memory-laundering path is gated. A pin that reached past that
    would widen what a non-admin may run (`Law 1`).
    """
    assert set(ALWAYS_AVAILABLE) == {"manage_memory", "ask_user", "update_plan"}
    assert set(ALWAYS_AVAILABLE) & set(ts.NON_ADMIN_BLOCKED_TOOLS) == {"manage_memory"}
    assert "manage_memory" in ts.NON_ADMIN_BLOCKED_REASONS


@pytest.mark.parametrize("owner,delegated", [(None, False), (MEMBER, False), (ADMIN, True)])
def test_the_cap_wins_and_the_pin_yields(monkeypatch, tmp_path, owner, delegated):
    """So the cap holds, and the *pin* is the thing that becomes
    privilege-aware. `_always_available_for_turn` is the one place that asks."""
    turn = run_turn(monkeypatch, tmp_path, owner=owner, delegated=delegated)
    assert "manage_memory" in turn.cap
    assert "manage_memory" not in turn.offered()
    assert "manage_memory" not in al._always_available_for_turn(turn.cap)
    assert al._always_available_for_turn(turn.cap) == {"ask_user", "update_plan"}


def test_the_pin_is_whole_for_an_admin(monkeypatch, tmp_path):
    """`Law 1`: nothing is taken from the person the pin was written for."""
    turn = run_turn(monkeypatch, tmp_path, owner=ADMIN)
    assert al._always_available_for_turn(turn.cap) == set(ALWAYS_AVAILABLE)


# ── group C — question 3: both sets at once, and the order of the writers ───

@pytest.mark.parametrize("owner,delegated,plan_mode", [
    (None, False, False),
    (MEMBER, False, False),
    (ADMIN, False, False),
    (ADMIN, True, False),
    (ADMIN, False, True),
])
def test_a_name_is_never_in_the_turns_selection_and_its_cap_at_once(
        monkeypatch, tmp_path, owner, delegated, plan_mode):
    """`B1350`. The invariant, driven at every privilege with a selection set
    that deliberately names capped tools — the brief's own measurement shape.

    On `747cda6` an anonymous turn's selection held `manage_skills` while the
    cap held it too, and the prompt the model got never contained the string.
    """
    turn = run_turn(monkeypatch, tmp_path, owner=owner, delegated=delegated,
                    plan_mode=plan_mode, relevant_tools=WIDE)
    assert not (turn.selected & turn.cap), sorted(turn.selected & turn.cap)


def test_every_name_the_prompt_was_asked_to_describe_is_in_the_prompt(
        monkeypatch, tmp_path):
    """The reader's half of the same invariant: with no overlap left, the
    prompt names every tool it was handed, so `selected` and `offered` agree."""
    turn = run_turn(monkeypatch, tmp_path, owner=None, relevant_tools=WIDE)
    assert turn.offered() == turn.selected
    for name in turn.offered():
        assert f"`{name}`" in turn.text, name


def test_a_per_turn_clamp_cannot_lift_a_privilege_cap(monkeypatch, tmp_path):
    """`B1348`. The `pantheon-qwen3` notes clamp, which is a bare
    `difference_update` on `747cda6`.

    Measured there: a non-admin's cap went 52 → 50 on this exact turn and
    `manage_calendar`/`manage_tasks` reached the prompt and the schema list,
    while `execute_tool_block`'s own gate refused every call — two tools
    offered and then refused, which is the owner's *"intermittent"* in its
    purest form.
    """
    notes = "add a note to buy milk and put it on my todo list"
    for owner in (None, MEMBER):
        turn = run_turn(monkeypatch, tmp_path / f"n{owner}", owner=owner,
                        model="pantheon-qwen3-8b", user=notes, relevant_tools=WIDE)
        for name in ("manage_calendar", "manage_tasks"):
            assert name in turn.cap, (owner, name, sorted(turn.cap))
            assert name not in turn.offered(), (owner, name)
            assert f"`{name}`" not in turn.text, (owner, name)
        # `manage_notes` is not in the non-admin register, so it is still there:
        # the clamp lost nothing it was entitled to.
        assert "manage_notes" not in turn.cap
        assert "manage_notes" in turn.offered()


def test_the_notes_clamp_still_does_its_job_for_an_admin(monkeypatch, tmp_path):
    """`Law 1`. For an admin none of the three is withheld, so none is lifted
    and all three are offered, exactly as before."""
    turn = run_turn(monkeypatch, tmp_path, owner=ADMIN, model="pantheon-qwen3-8b",
                    user="add a note to buy milk and put it on my todo list",
                    relevant_tools=WIDE)
    for name in ("manage_notes", "manage_calendar", "manage_tasks"):
        assert name not in turn.cap, name
        assert name in turn.offered(), name


def test_the_order_the_writers_run_in_is_no_longer_load_bearing_for_a_lift():
    """A lift that runs after a privilege withholding and one that runs before
    it reach the same answer — which is what makes the ten writers' order safe
    for this one operation. (It is still load-bearing for the suite planner's
    *candidates*, which is `B1353` in the note, not a thing this fixes.)"""
    after = TurnToolAccess({"manage_calendar"}, because=WITHHELD_BY_PRIVILEGE)
    after.lift({"manage_calendar"}, because="clamp")
    before = TurnToolAccess()
    before.lift({"manage_calendar"}, because="clamp")
    before.withhold({"manage_calendar"}, because=WITHHELD_BY_PRIVILEGE)
    assert after == before == {"manage_calendar"}


# ── group D — question 4: one place, and one predicate ─────────────────────

@pytest.mark.parametrize("owner,delegated,plan_mode,image_gen", [
    (None, False, False, False),
    (MEMBER, False, False, False),
    (ADMIN, False, False, False),
    (ADMIN, False, False, True),
    (ADMIN, True, False, False),
    (ADMIN, False, True, False),
])
def test_the_prompt_and_the_loop_read_one_set(
        monkeypatch, tmp_path, owner, delegated, plan_mode, image_gen):
    """`B1349`. They were two sets. `_build_base_prompt` did
    `disabled = set(disabled_tools or [])` and then added `generate_image` to
    that copy, so on `747cda6` `_assemble_prompt` was handed 53 names on an
    anonymous turn while the loop's own set held 52 — and the native schema
    filter, which reads the loop's set, sent the schema the prompt withheld."""
    turn = run_turn(monkeypatch, tmp_path, owner=owner, delegated=delegated,
                    plan_mode=plan_mode, image_gen=image_gen, relevant_tools=WIDE)
    assert turn.prompt_cap == turn.cap, sorted(turn.prompt_cap ^ turn.cap)


def test_the_image_tool_follows_the_setting_on_its_only_channel(monkeypatch, tmp_path):
    """The consequence, end to end, on the one name the two sets differed by.

    `generate_image` was one of two members of `TOOL_SECTIONS` with **no**
    `FUNCTION_TOOL_SCHEMAS` entry (`H09`), so the fenced prompt was its only
    channel and `fenced_tool_names` — the receipt's own answer — was where to
    look. On `747cda6` the loop's set did not hold it, so every reader that
    read the loop's set (the schema filter, the dispatcher's refusal, the
    receipt) disagreed with the prompt that had just withheld it.

    `B1357` / `D-2026-10-14-01` §1 gave it a schema, so the fenced prompt is no
    longer its *only* channel and the test name is now historical. What this
    case measures is unchanged and is the part that matters: **one setting
    decides both channels.** The compact prompt's line moved with it, from "on
    neither turn" to "exactly the turn that can call it", which is a stronger
    statement of the same subject.
    """
    off = run_turn(monkeypatch, tmp_path / "off", owner=ADMIN, image_gen=False,
                   relevant_tools=WIDE)
    assert "generate_image" in off.cap
    assert "generate_image" not in al.fenced_tool_names(off.selected, off.cap)
    assert "```generate_image" not in al._assemble_prompt(
        off.selected, off.cap, compact=False)
    on = run_turn(monkeypatch, tmp_path / "on", owner=ADMIN, image_gen=True,
                  relevant_tools=WIDE)
    assert "generate_image" not in on.cap
    assert "generate_image" in al.fenced_tool_names(on.selected, on.cap)
    assert "```generate_image" in al._assemble_prompt(
        on.selected, on.cap, compact=False)
    # The compact prompt named it on neither turn while it had no schema to
    # name (`H09`). It has one now, so the compact prompt names it on exactly
    # the turn whose setting allows it — which is this case's subject reaching
    # the one channel it previously could not.
    assert "`generate_image`" not in off.text, off.text[-400:]
    assert "`generate_image`" in on.text, on.text[-400:]


def test_no_schema_is_sent_for_a_tool_this_turn_cannot_call(monkeypatch, tmp_path):
    """The schema filter's half. It read the loop's set and asked the literal
    name; it asks the turn's one predicate now, so the array and the prompt
    carry the same tools."""
    for owner, delegated in ((None, False), (MEMBER, False), (ADMIN, True), (ADMIN, False)):
        turn = run_turn(monkeypatch, tmp_path / f"s{owner}{delegated}", owner=owner,
                        delegated=delegated, relevant_tools=WIDE)
        assert not (turn.sent() & turn.cap), sorted(turn.sent() & turn.cap)
        assert turn.sent() <= turn.offered(), sorted(turn.sent() - turn.offered())


def test_the_image_setting_has_one_definition():
    """`Law 7`. Three readers, two different defaults, one of them the stored
    one. `setting_disabled_tools` is the rule; the loop and
    `_build_base_prompt` both ask it."""
    from src.settings import DEFAULT_SETTINGS

    assert DEFAULT_SETTINGS["image_gen_enabled"] is False
    assert ts.setting_disabled_tools(lambda k, d=None: d) == {"generate_image"}
    assert ts.setting_disabled_tools(lambda k, d=None: True) == set()
    # `edit_image` is deliberately not withheld: the prompt's rule never did.
    assert "edit_image" not in ts.setting_disabled_tools(lambda k, d=None: False)


def test_the_one_predicate_is_alias_aware_everywhere(monkeypatch, tmp_path):
    """`B1351`. The dispatcher asked every policy-equivalent spelling
    (`email_tool_policy_names`) and the prompt and the schema filter asked the
    literal name — which is why the open-email-draft writer spells both by
    hand. One cap entry in the qualified spelling now withholds the bare one
    from the prompt too."""
    access = turn_tool_access({"mcp__email__read_email"})
    assert access.blocks("read_email")
    assert access.blocks("mcp__email__read_email")
    assert access.allowed_among({"read_email", "ls"}) == {"ls"}
    turn = run_turn(monkeypatch, tmp_path, owner=ADMIN,
                    relevant_tools={"read_email", "ask_user", "update_plan"})
    # The loop itself writes both spellings for the open-draft rule, so the
    # product's own behaviour is unchanged; what this pins is the predicate.
    assert al._assemble_prompt({"read_email"}, {"mcp__email__read_email"}) \
        == al._assemble_prompt({"read_email"}, {"read_email"})
    assert turn.prompt_cap == turn.cap


def test_the_turns_access_is_still_a_set():
    """`Law 14`: the loop's ~40 plain set operations are untouched."""
    access = TurnToolAccess({"bash"}, because=WITHHELD_BY_PRIVILEGE)
    access.update({"ls"})
    access.add("grep")
    assert isinstance(access, set)
    assert "bash" in access and sorted(access) == ["bash", "grep", "ls"]
    assert {"bash", "web_search"} - access == {"web_search"}
    assert frozenset(access) == frozenset({"bash", "grep", "ls"})
    assert access.allowed_among(["bash", "web_search"]) == {"web_search"}


@pytest.mark.parametrize("because", [
    WITHHELD_BY_POLICY, WITHHELD_BY_PRIVILEGE, WITHHELD_BY_FEATURE,
    WITHHELD_BY_PLAN_MODE, WITHHELD_BY_STEP_TOOLS,
])
def test_a_clamp_cannot_lift_these_reasons(because):
    """The `Law 1` guarantee as a property of the type: a privilege, a policy,
    a switched-off feature, plan mode and a step's own list (`P22-16`) stay."""
    assert because not in LIFTABLE_REASONS
    for lift in (lambda a: a.lift({"bash"}, because="clamp"),
                 lambda a: a.discard("bash"),
                 lambda a: a.difference_update({"bash"}),
                 lambda a: a.__isub__({"bash"}),
                 lambda a: a.clear()):
        access = TurnToolAccess({"bash"}, because=because)
        lift(access)
        assert "bash" in access, because


@pytest.mark.parametrize("because", [WITHHELD_BY_TURN, WITHHELD_UNATTRIBUTED])
def test_a_clamp_lifts_what_a_turn_put_there(because):
    """`Law 1` the other way: every path that worked before this type existed
    still works. A bare `.update()` is unattributed and liftable, which is
    exactly how `difference_update` behaved on a plain set."""
    access = TurnToolAccess({"manage_notes"}, because=because)
    assert access.lift({"manage_notes"}, because="clamp") == {"manage_notes"}
    assert "manage_notes" not in access


def test_a_name_withheld_twice_needs_both_reasons_liftable():
    access = TurnToolAccess({"bash"}, because=WITHHELD_BY_TURN)
    access.withhold({"bash"}, because=WITHHELD_BY_PRIVILEGE)
    assert access.reasons_for("bash") == frozenset({WITHHELD_BY_TURN, WITHHELD_BY_PRIVILEGE})
    access.lift({"bash"}, because="clamp")
    assert "bash" in access


def test_the_turns_access_is_passed_through_not_rebuilt():
    """`turn_tool_access` hands back the loop's own object, or a reader would
    quietly make a privilege entry liftable again."""
    access = TurnToolAccess({"bash"}, because=WITHHELD_BY_PRIVILEGE)
    assert turn_tool_access(access) is access
    wrapped = turn_tool_access({"bash"})
    assert wrapped.reasons_for("bash") == frozenset({WITHHELD_UNATTRIBUTED})
    assert turn_tool_access(None) == set()


def test_an_unknown_withholding_reason_is_refused():
    """`Law 10`: an enum, and a name outside it is an error rather than a
    silently-liftable entry."""
    with pytest.raises(ValueError):
        TurnToolAccess({"bash"}, because="because-i-said-so")


def test_the_caller_s_own_set_is_recorded_as_the_caller_s(monkeypatch, tmp_path):
    """The route's deliberate sets cannot be lifted by a per-turn clamp.

    **Rewritten 2026-10-17 and the property is the same one.** This asserted
    `WITHHELD_BY_CALLER not in LIFTABLE_REASONS`, which was the *mechanism* that
    held the property at the time — and it is the assertion that caught
    `D-2026-10-17-01` §1's approved recommendation and proved it wrong, because
    `caller` then held the route's deliberate restrictions in the same bucket as
    a neutral starting set.

    `D-2026-10-17-02` §2 fixed the bucket instead of widening the rule:
    `routes/chat_routes.py` composes through `RouteWithholds`, so incognito's
    `manage_skills` is `policy` and the neutral remainder is `caller`. `caller`
    is liftable now and **a name the chat route switched off still cannot be
    lifted** — for a better reason. Both halves are asserted here, because
    *liftable* alone would be the defect and *unliftable* alone is no longer
    true.
    """
    turn = run_turn(monkeypatch, tmp_path, owner=ADMIN, relevant_tools=WIDE)
    assert WITHHELD_BY_CALLER in LIFTABLE_REASONS

    from src.tool_policy import RouteWithholds, WITHHELD_BY_POLICY

    deliberate = RouteWithholds().deny({"manage_skills"}, WITHHELD_BY_POLICY)
    access = deliberate.finish({"manage_skills", "manage_notes"})
    access.difference_update({"manage_skills", "manage_notes"})
    assert "manage_skills" in access, (
        "a restriction the route made deliberately was lifted by a clamp")
    assert "manage_notes" in access, (
        "the policy layer's own additions are `policy` too, so this one has to "
        "survive a clamp as well — if it did not, `finish` is attributing them "
        "as the caller's")

    neutral = TurnToolAccess({"manage_calendar"}, because=WITHHELD_BY_CALLER)
    neutral.difference_update({"manage_calendar"})
    assert "manage_calendar" not in neutral, (
        "a neutral caller set is not liftable, so `#6020`'s notes clamp is "
        "still dead code")
    assert turn.prompt_cap == turn.cap


# ── the one writer that runs after both invariant points ───────────────────

def test_a_skill_cannot_unlock_a_tool_this_turn_may_not_call(monkeypatch, tmp_path, caplog):
    """`B1352` (fx11-cap). A skill's `requires_toolsets` are unioned into
    `_relevant_tools` **mid-run**, after `manage_skills action=view` returns —
    the one writer that runs after both of the loop's "never a name this turn
    cannot call" points. It was filtered by `known_tool_names()` and by nothing
    else, so a capped name went back into the set a round later and the
    `[tool-rag] skill '…' unlocked tools for next round` line named a tool every
    call of would be refused. `P22-16`'s *"the selection below never widens
    past it"*, through a door that opens one round late.
    """
    from services.memory.skills import SkillsManager

    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    SkillsManager(str(data_dir)).add_skill(
        name="read-the-logs",
        description="Read the logs and say what broke.",
        category="ops",
        when_to_use="when something broke",
        procedure=["Run `bash` over the log.", "Say what broke."],
        requires_toolsets=["bash", "ls"],
        status="published",
        source="user",
        owner=ADMIN,
    )
    monkeypatch.setattr("src.constants.DATA_DIR", str(data_dir), raising=False)

    rec = Turn()
    signed_in(monkeypatch, tmp_path / "auth")
    monkeypatch.setattr(al, "get_setting", lambda k, d=None: d, raising=False)
    monkeypatch.setattr(al, "get_mcp_manager", lambda: None, raising=False)
    monkeypatch.setattr(al, "estimate_tokens", lambda *a, **k: 10, raising=False)
    monkeypatch.setattr(al, "_skills_pref_enabled", lambda o: False, raising=False)

    real_assemble = al._assemble_prompt

    def assemble_spy(tool_names, disabled_tools=None, compact=False, suite_notice=""):
        out = real_assemble(tool_names, disabled_tools, compact, suite_notice)
        rec.prompts.append((set(tool_names or ()), set(disabled_tools or ()), out))
        return out

    monkeypatch.setattr(al, "_assemble_prompt", assemble_spy, raising=False)

    # The OpenAI `tool_calls` channel, in the shape
    # `tests/helpers/tool_suite_probe.reply_shapes` calls `native` — a frame fed
    # to the loop's own reader, so the call is parsed by the product.
    rounds = iter([
        {"type": "tool_calls", "calls": [{
            "name": "manage_skills",
            "arguments": json.dumps({"action": "view", "name": "read-the-logs"}),
        }]},
        {"delta": "Done."},
    ])

    async def scripted(_c, _messages, **kwargs):
        yield "data: " + json.dumps(next(rounds, {"delta": "Done."})) + "\n\n"
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(al, "stream_llm_with_fallback", scripted, raising=False)

    async def boundary(block, *a, **k):
        return block.tool_type, {"output": "ok: read-the-logs", "exit_code": 0}

    monkeypatch.setattr(al, "execute_tool_block", boundary, raising=False)

    async def collect():
        async for _chunk in al.stream_agent_loop(
            "http://127.0.0.1:1/v1", "mistral-7b",
            [{"role": "user", "content": "read the logs and say what broke"}],
            max_rounds=3,
            owner=ADMIN,
            relevant_tools={"manage_skills", "ask_user", "update_plan"},
            # The route's own withholding — incognito and the explicit web turn
            # both do exactly this (`routes/chat_routes.py`).
            disabled_tools={"bash"},
        ):
            pass

    import logging

    with caplog.at_level(logging.INFO, logger="src.agent_loop"):
        asyncio.run(collect())

    unlocked = [r.getMessage() for r in caplog.records
                if "unlocked tools for next round" in r.getMessage()]
    assert unlocked, [r.getMessage() for r in caplog.records][-8:]
    said = unlocked[-1]
    # `ls` was not capped, so the unlock still does its job (`Law 1`).
    assert "'ls'" in said, said
    # `bash` was — by the route, the way incognito and the explicit web turn
    # withhold `manage_skills` — so it is neither unlocked nor announced.
    assert "'bash'" not in said, said
    assert rec.prompts and "bash" in rec.prompts[0][1]
