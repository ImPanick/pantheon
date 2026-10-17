# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1375` — a matched procedure that does not fit arrives short, not absent.

`B1362` gave the matched-skill bodies a budget, because they had none: measured
on `0bd089d`, one long matched skill rendered **23,606 characters (~7,085
tokens)** and twelve rendered **257,813 (~77,347)** against a default
`agent_input_token_budget` of 6,000, and the only thing that ever cut them was
`context_compactor.trim_for_context` eating the conversation from the front.

Bounding them was right and it was still **a choice between two losses**, which
is why the row was filed for the owner rather than decided by an agent: cut the
procedures and tell the model they are short, or let them through whole and
spend the person's earlier turns. The owner took the third answer the row
described — *hand the model the procedure's first N steps plus `manage_skills
action=view` and let it fetch the rest only if it needs them* — and this is it.

**What actually changes, measured.** Twelve matched procedures of twenty steps
each against the shipped 12,000-character budget:

  * before — **two** bodies whole, and the other **ten** reached the model as
    the number ten. It could not know what they were called, so it could not
    decide whether it wanted one;
  * after — **twelve** bodies, each with its name, description, *when to use*
    and first nine steps, and a line per skill saying how many steps remain and
    the exact call that fetches them.

Four decisions in here are worth their own cases, because each is a thing that
could reasonably have gone the other way:

  * **one `N` for every skill, not a share each.** A per-skill share spends the
    budget on whichever procedure happens to be longest, so the twelfth match
    gets nothing while the first gets forty steps. One N is also one number a
    reader can check against the block.
  * **the head of a body is never cut.** Name, description and *when to use*
    are what the model needs to decide whether it wants the rest, so they
    survive at every budget that renders the body at all.
  * **pitfalls go with the steps they are about.** A pitfall concerning step 9,
    read without step 9, is worse than no pitfall.
  * **the drop branch is kept as the floor.** When there is nothing to shorten —
    one enormous step — whole bodies still drop from the tail, which is
    `B1362`'s behaviour and `P8-21`'s rule that a heading with nothing under it
    is a worse answer than a short procedure.
"""

from __future__ import annotations

import pytest

from services.memory import skill_injection

#: A step long enough that twenty of them cannot fit any realistic budget.
STEP = ("Open the vendor console, select the affected tenant, confirm the region "
        "matches the one in the ticket, and copy the correlation id into the "
        "incident channel before touching anything else. ")


def _skill(i: int, steps: int) -> dict:
    return {"name": f"skill-{i}",
            "description": f"what skill {i} is for",
            "when_to_use": f"when situation {i} arises",
            "procedure": [f"step {j}: {STEP}" for j in range(1, steps + 1)],
            "pitfalls": [f"the pitfall of skill {i}"]}


BUDGET = 12_000


def _sections(block: str) -> dict:
    """`{skill name: its lines}` — the block split at its own `###` headings.

    Counting steps by looking for the skill's name inside a step line does not
    work and the first draft of this file did exactly that: a step reads
    `step 7: Open the vendor console…` and carries no name at all, so every
    count came back zero and every assertion below it passed for the wrong
    reason.
    """
    out: dict = {}
    current = None
    for line in block.split("\n"):
        if line.startswith("### "):
            current = line[4:].split(" _(", 1)[0].strip()
            out[current] = []
        elif current is not None:
            out[current].append(line)
    return out


def _steps_shown(lines: list) -> int:
    return sum(1 for line in lines if line.strip()[:2].rstrip(".").isdigit()
               and line.strip().split(".", 1)[0].strip().isdigit()
               and line.startswith("  "))


@pytest.fixture(scope="module")
def twelve():
    return [_skill(i, 20) for i in range(1, 13)]


# ── the row's own measurement ──────────────────────────────────────────────


def test_every_matched_skill_reaches_the_model_by_name(twelve):
    """The change, stated as the property that was false before."""
    report: dict = {}
    block = skill_injection.render_matched_skills_block(
        twelve, budget_chars=BUDGET, report=report)
    assert len(block) <= BUDGET
    named = [s["name"] for s in twelve if f"### {s['name']}" in block]
    assert named == [s["name"] for s in twelve], (
        f"only {len(named)} of {len(twelve)} matched skills are named in the block")
    assert report["skill_bodies_omitted"] == 0
    assert report["skill_bodies_applied"] == [s["name"] for s in twelve]
    assert report["skill_bodies_truncated"] is True


def test_each_shortened_skill_says_how_much_is_missing_and_how_to_get_it(twelve):
    report: dict = {}
    block = skill_injection.render_matched_skills_block(
        twelve, budget_chars=BUDGET, report=report)
    assert report["skill_bodies_shortened"] == [s["name"] for s in twelve]
    sections = _sections(block)
    assert set(sections) == {s["name"] for s in twelve}
    for sk in twelve:
        lines = sections[sk["name"]]
        shown = _steps_shown(lines)
        assert 0 < shown < len(sk["procedure"]), (
            f"{sk['name']} shows {shown} of {len(sk['procedure'])} steps")
        remaining = len(sk["procedure"]) - shown
        marker = skill_injection.MATCHED_STEPS_ELIDED.format(
            remaining=remaining, name=sk["name"]).strip()
        assert any(marker == line.strip() for line in lines), (
            f"{sk['name']} shows {shown} steps and does not say the other "
            f"{remaining} are fetchable; its lines end: {lines[-2:]}")


def test_the_block_note_says_shortened_rather_than_left_out(twelve):
    """`Law 10`. *Left out* and *shortened* are different events, and a note
    that reports the wrong one is worse than a shorter note."""
    block = skill_injection.render_matched_skills_block(twelve, budget_chars=BUDGET)
    assert skill_injection.MATCHED_CUT_WHAT_SHORTENED.format(shortened=12) in block
    assert "further matched procedure" not in block
    assert skill_injection.MATCHED_CAP_PHRASE in block


# ── the four decisions ─────────────────────────────────────────────────────


def test_one_step_count_covers_every_skill(twelve):
    """Not a share each: the longest procedure must not eat the budget."""
    block = skill_injection.render_matched_skills_block(twelve, budget_chars=BUDGET)
    remaining = {int(line.split("…", 1)[1].split(" more", 1)[0])
                 for line in block.split("\n") if "more step(s)" in line}
    assert len(remaining) == 1, (
        f"different skills were cut to different lengths: {sorted(remaining)} "
        "steps remaining — one N for all of them is the rule")


def test_a_procedure_shorter_than_the_cut_is_left_whole():
    """One N, applied to procedures of different lengths. The rule is a
    property, not a list: a skill with at most N steps is whole and keeps its
    pitfalls; one with more carries a marker and loses them.

    The first draft asserted the exact set `["skill-2"]` and failed, because at
    that budget N landed on 3 and the four-step skill was shortened too. The
    set depends on the budget; the property does not.
    """
    mixed = [_skill(1, 3), _skill(2, 30), _skill(3, 4)]
    report: dict = {}
    block = skill_injection.render_matched_skills_block(
        mixed, budget_chars=3_000, report=report)
    shortened = set(report["skill_bodies_shortened"])
    assert "skill-2" in shortened, "the 30-step procedure was not shortened"
    assert "skill-1" not in shortened, "the 3-step procedure should be the last cut"
    sections = _sections(block)
    cut = {name: _steps_shown(lines) for name, lines in sections.items()}
    n = min(cut[name] for name in shortened)
    for sk in mixed:
        whole = len(sk["procedure"]) <= n
        assert (sk["name"] in shortened) is not whole, (
            f"{sk['name']} has {len(sk['procedure'])} steps against N={n} "
            f"and is {'' if sk['name'] in shortened else 'not '}shortened")
        # A pitfall travels with a whole body and goes with the elided steps.
        assert (f"the pitfall of skill {sk['name'].split('-')[1]}" in block) is whole, (
            "a pitfall about a step the model cannot see is worse than none")


def test_the_head_of_a_body_is_never_cut(twelve):
    """Name, description and *when to use* are how the model decides whether it
    wants the rest, so they survive wherever the body is rendered at all."""
    report: dict = {}
    block = skill_injection.render_matched_skills_block(
        twelve, budget_chars=BUDGET, report=report)
    for sk in twelve:
        assert sk["description"] in block, f"{sk['name']} lost its description"
        assert sk["when_to_use"] in block, f"{sk['name']} lost its when-to-use"


def test_nothing_is_shortened_while_everything_fits():
    """The budget binds or it does not; a short procedure is never trimmed to
    look like a long one."""
    report: dict = {}
    block = skill_injection.render_matched_skills_block(
        [_skill(1, 3)], budget_chars=BUDGET, report=report)
    assert report["skill_bodies_truncated"] is False
    assert report["skill_bodies_shortened"] == []
    assert report["skill_bodies_omitted"] == 0
    assert skill_injection.MATCHED_CAP_PHRASE not in block
    assert "more step(s)" not in block
    assert "the pitfall of skill 1" in block


def test_the_drop_branch_is_still_the_floor():
    """Nothing to shorten — one enormous step each — so whole bodies drop from
    the tail, `B1362`'s behaviour unchanged. This row adds a rung above the
    floor; it does not remove the floor."""
    bodies = [{"name": f"p{i}", "description": "d", "procedure": ["Z" * 2000]}
              for i in range(4)]
    report: dict = {}
    block = skill_injection.render_matched_skills_block(
        bodies, budget_chars=5_000, report=report)
    assert report["skill_bodies_omitted"] > 0
    assert report["skill_bodies_shortened"] == []
    assert f"{report['skill_bodies_omitted']} further matched procedure" in block
    assert len(block) <= 5_000


# ── the honest wording when no fetch is possible ───────────────────────────


def test_the_marker_promises_no_fetch_that_cannot_happen(twelve):
    """`can_fetch=False` is the turn where `manage_skills` is not offered. The
    whole point of this row is *fetch the rest if you need it*, so the one
    thing the marker must not do there is name a call the model cannot make."""
    block = skill_injection.render_matched_skills_block(
        twelve, budget_chars=BUDGET, can_fetch=False)
    assert "more step(s) not shown" in block
    assert "manage_skills" not in block, (
        "the no-fetch block offers a call this turn cannot make")
    named = [s["name"] for s in twelve if f"### {s['name']}" in block]
    assert named == [s["name"] for s in twelve], (
        "progressive disclosure still beats dropping bodies when nothing can "
        "be fetched — the model sees what exists instead of a count")


def test_the_receipt_distinguishes_whole_from_shortened(twelve):
    """`Law 10`, and the reason `skill_bodies_shortened` exists. Under this row
    nearly every match is `applied`, so `applied` alone would answer *yes* for
    a procedure the turn saw nine steps of out of twenty."""
    report: dict = {}
    skill_injection.render_matched_skills_block(
        twelve[:1] + [_skill(99, 2)], budget_chars=2_000, report=report)
    assert set(report["skill_bodies_applied"]) >= set(report["skill_bodies_shortened"])
    assert "skill-99" in report["skill_bodies_applied"]
    assert "skill-99" not in report["skill_bodies_shortened"], (
        "a two-step procedure that fitted whole is reported as shortened")
