# SPDX-License-Identifier: AGPL-3.0-or-later
# services/memory/skill_injection.py
"""The one renderer for the skill index the model is shown.

`P8-06`. The index block was assembled inline in `agent_loop._build_base_prompt`
and nowhere else, so `GET /api/skills/index` — the endpoint whose whole purpose
is answering *"what does the model actually have access to?"* — could only ever
return the **list**, leaving anything that wanted the **text** to write a second
copy of the renderer. A preview built on a second copy is not a preview; it is a
drawing of one, and the two drift the first time the prompt wording is edited
(`Law 7`, `Law 14`).

So the renderer lives here, both callers import it, and the endpoint returns the
string the loop injects rather than a re-implementation of it.

**What reaches the prompt is narrower than what the index carries.** The block is
built from `name`, `description` and `category`, plus `status` as a `*(draft)*`
badge — and nothing else. `source` and `teacher_model` ride in the index dict for
`P4-16`'s receipt and never reach a prompt line; the procedure, pitfalls and
verification never leave disk until `manage_skills action=view` fetches them.
`INJECTED_FIELDS` / `WITHHELD_FIELDS` state that in a form a caller can read,
and `WITHHELD_FIELDS` is **derived from the schema** rather than restated, so a
field added to `Skill` shows up as withheld without anybody remembering to.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from .skill_format import Skill

# The header and the per-entry shape are the prompt contract. They live in one
# string each so the endpoint and the loop cannot disagree about a comma.
INDEX_HEADING = "## Available skills"
_INDEX_DRAFT_NOTE = (
    "Entries tagged `(draft)` were written by the "
    "teacher-escalation loop after a prior failure — treat them as authoritative "
    "guidance; if you follow one and it works, that's a good signal the procedure "
    "is correct."
)
INDEX_PREAMBLE = (
    "Procedures the assistant should consult before doing domain work. "
    "Fetch the full procedure with `manage_skills` action=view name=<name> "
    "when one looks relevant. " + _INDEX_DRAFT_NOTE
)

#: `B1360`. The same catalogue, for a turn that cannot call `manage_skills`.
#:
#: The route puts `manage_skills` in `disabled_tools` on an explicit web turn
#: (`routes/chat_routes.py` — a lookup must not drift into personal tools) and
#: in incognito, and the person's privileges can withhold it
#: (`can_manage_memory`). None of that lifts here. What changed is that the
#: block stops instructing a call that the product will refuse: measured live on
#: 8802, the model read *"fetch the full procedure with `manage_skills`"*, called
#: it, and got back `tool_blocked` / *"Tool is disabled for this request."* —
#: while the same prompt said *"Every tool this prompt names is available for
#: this turn… do not look for one that is not listed."* (`B1309`). Two
#: sentences a model cannot both obey is `Law 10` on the wire.
INDEX_PREAMBLE_NO_FETCH = (
    "Procedures the assistant should consult before doing domain work. "
    "The full text of these cannot be fetched on this turn, so work from the "
    "lines below and from any procedure quoted in full further down. "
    + _INDEX_DRAFT_NOTE
)

#: `B1376`. Which of the two preambles a rendering with no turn behind it —
#: `GET /api/skills/index` — took, said in the words a person reads. The
#: preview and the injection otherwise differ by exactly that one sentence.
INDEX_ASSUMES_FETCH = (
    "Shown as a turn that can open a skill gets it. A turn without the skills "
    "tool — an explicit web search, or incognito — gets the same list with its "
    "first sentence saying the full text cannot be fetched."
)
INDEX_ASSUMES_NO_FETCH = (
    "Shown as a turn without the skills tool gets it — an explicit web search, "
    "or incognito — so its first sentence says the full text cannot be fetched."
)

#: The matched-skill half of the block. `B1362`. This text was eleven inline
#: `lines.append(...)` calls in `agent_loop._build_system_prompt`, which is why
#: it had no budget: a block assembled where nothing measures it is a block
#: nothing measures. It lives beside the catalogue's renderer now, for the
#: reason this module exists at all.
MATCHED_HEADING = "## Relevant skills for this request"
_MATCHED_LEAD = (
    "These skills are matched to your current request. Each is a "
    "procedure proven to work. Follow them step by step."
)
MATCHED_PREAMBLE = (
    _MATCHED_LEAD + " To see the full SKILL.md (more detail, pitfalls, "
    "verification steps), call `manage_skills` with action='view' and the "
    "skill name."
)
MATCHED_PREAMBLE_NO_FETCH = (
    _MATCHED_LEAD + " The full SKILL.md cannot be fetched on this turn, so "
    "what is below is all of it you have."
)

#: `B1362`. What the model is told when a matched procedure did not fit. The
#: catalogue has said this since `P8-21`; the bodies said nothing, and they are
#: the expensive half — measured on `0bd089d`, one long skill rendered 23,606
#: characters (~7,085 tokens) and twelve rendered 257,813 (~77,347), inside no
#: budget at all, leaving `context_compactor.trim_for_context` to drop whatever
#: it reached first with no note to the model or the person.
#: The one phrase every form of the note carries, so a reader — a model, a
#: person or a test — has one thing to look for.
MATCHED_CAP_PHRASE = ("the matched-skill text is capped so it cannot crowd out "
                      "the conversation")
MATCHED_TRUNCATION_NOTE = (
    "\n_{what}: " + MATCHED_CAP_PHRASE
    + ". Fetch one in full with `manage_skills` action=view name=<name>._"
)
MATCHED_TRUNCATION_NOTE_NO_FETCH = "\n_{what}: " + MATCHED_CAP_PHRASE + "._"
#: `Law 10`: "0 further procedures were left out" is not what happened when a
#: single matched procedure was cut at a line boundary, and a note that says the
#: wrong one of the two is worse than a shorter note.
MATCHED_CUT_WHAT_OMITTED = ("{omitted} further matched procedure(s) were left out "
                            "of this block, and any procedure above may be cut short")
MATCHED_CUT_WHAT_SHORT = "The procedure above is cut short"

#: `B1375`, on the owner's ruling. **What the model is told about one skill
#: whose procedure was shortened rather than dropped.**
#:
#: `B1362` gave these bodies a budget and bounded them by dropping whole
#: skills from the tail. That is a real improvement over the trimmer eating the
#: conversation, and it is still a choice between two losses: with twelve
#: matched procedures against a 12,000-character budget, ten of them reached
#: the model as a count — *"10 further matched procedure(s) were left out"* —
#: and the model could not even know what they were called, let alone decide
#: whether it wanted one.
#:
#: So a skill that does not fit whole is shortened to its opening steps instead
#: of dropped. Every matched skill keeps its name, its description, its *when
#: to use* and the start of its procedure, and this line says exactly how much
#: is missing and how to get it. The procedure is a **list**, so these are real
#: steps and the count is exact — not a character cut dressed up as steps.
MATCHED_STEPS_ELIDED = ("  _…{remaining} more step(s) in the full SKILL.md. "
                        "`manage_skills` action=view name={name}._")
MATCHED_STEPS_ELIDED_NO_FETCH = ("  _…{remaining} more step(s) not shown, and the "
                                 "full SKILL.md cannot be fetched on this turn._")
#: And what the block-level note says when that is what happened. `Law 10`:
#: *"left out"* and *"shortened"* are different events and a note that reports
#: the wrong one is worse than a shorter note — the same call
#: `MATCHED_CUT_WHAT_SHORT` was added for.
MATCHED_CUT_WHAT_SHORTENED = ("{shortened} matched procedure(s) are shown as their "
                              "opening steps only")

#: The fields `render_skill_index_block` actually reads. `status` only decides
#: whether the `*(draft)*` badge is drawn; its value is never printed.
INJECTED_FIELDS: tuple = ("name", "description", "category", "status")


# Not withheld and not injected: `id` and `path` are storage, and the four
# back-compat aliases are second spellings of fields that ARE injected or are
# listed under their modern names. Calling `title` withheld would be false —
# it is `description`, which is the second thing on every index line.
_NOT_A_FIELD = ("id", "path", "title", "problem", "solution", "steps")


def _withheld_fields() -> tuple:
    """Every field a skill carries that the index block does not show.

    Derived from `Skill.to_dict()` so the list cannot go stale: adding a field
    to the schema adds it here, and `P8-07`'s "verification and body text are
    never injected" stays true by construction instead of by memory.
    """
    probe = Skill(name="probe").to_dict()
    return tuple(
        k for k in probe
        if k not in INJECTED_FIELDS and k not in _NOT_A_FIELD and not k.startswith("_")
    )


WITHHELD_FIELDS: tuple = _withheld_fields()


#: What the model is told when the catalogue did not fit. `P8-21`. A truncated
#: list with no note is worse than a long one: a model shown 40 of 300 skills
#: concludes the other 260 do not exist, and stops asking.
INDEX_TRUNCATION_NOTE = (
    "\n_{omitted} more skills are installed and not listed here — the catalogue "
    "is capped so it cannot crowd out the conversation. Ask for the rest with "
    "`manage_skills` action=list, or search them with action=search._"
)


def _index_value(entry: Dict) -> tuple:
    """Rank for deciding what survives a cut. `opens` first, then `uses`.

    `P8-21`. `uses` is written by the retriever itself — every skill it shows
    the model is counted, whether or not the model did anything with it — so
    ranking by it keeps whatever keyword luck matched most often and calls that
    evidence. `opens` is `manage_skills action=view`: the model reading the
    whole procedure after seeing the line, which is a decision rather than a
    side effect. Name last so a tie is stable rather than walk-order.
    """
    return (int(entry.get("opens") or 0), int(entry.get("uses") or 0),
            str(entry.get("name") or ""))


def _render(entries: Sequence[Dict], note: str = "", *, can_fetch: bool = True) -> str:
    lines: List[str] = [INDEX_HEADING,
                        INDEX_PREAMBLE if can_fetch else INDEX_PREAMBLE_NO_FETCH]
    by_cat: Dict[str, list] = {}
    for s in entries:
        by_cat.setdefault(s.get("category") or "general", []).append(s)
    for cat in sorted(by_cat):
        lines.append(f"\n**{cat}**")
        for s in by_cat[cat]:
            badge = " *(draft)*" if s.get("status") == "draft" else ""
            lines.append(f"- `{s['name']}` — {s.get('description') or ''}{badge}")
    if note:
        lines.append(note)
    return "\n\n" + "\n".join(lines)


def render_skill_index_block(index: Optional[Sequence[Dict]],
                             *, budget_chars: Optional[int] = None,
                             owner=None, report: Optional[Dict] = None,
                             can_fetch: bool = True) -> str:
    """The exact text injected as the skills catalogue, or `""` for none.

    `index` is what `SkillsManager.index_for()` returns. The leading blank line
    is part of the block: the loop concatenates it straight onto a prompt, so
    moving the separator out of here would move the bug out of reach of the
    preview along with it.

    **`P8-21`.** The block used to be unbounded. Measured 2026-09-19 with the
    bundled library published: 286 entries, 80,610 characters, 24,187 tokens —
    four times the default `agent_input_token_budget`, on every request that
    assembles a prompt, participating in no budget anywhere. `budget_chars`
    resolves from `context_skill_index_chars` when it is not passed, so both
    callers — the loop and `GET /api/skills/index` — are bounded by the same
    number without either of them asking, and the preview stays a preview.

    Entries are dropped **whole**, lowest-value first, and what is left renders
    in the ordinary category order, so a truncated block has the same shape as a
    full one. `report`, when a dict is passed, is filled in with
    `skill_index_chars`, `skill_index_truncated` and `skill_index_omitted` —
    an out-parameter rather than a second return value for the reason
    `_build_base_prompt`'s own `skill_index_used` gives: the stubs in this suite
    pin the return type.

    **`B1360`.** `can_fetch` is whether `manage_skills` is callable on the turn
    this block is being built for. False swaps the preamble for one that does
    not instruct a call the product will refuse — see
    `INDEX_PREAMBLE_NO_FETCH`. The preview endpoint has no turn, so it takes it
    as a query parameter (default True) and says which it assumed (`B1376`).
    """
    entries = [s for s in (index or []) if isinstance(s, dict) and s.get("name")]
    if not entries:
        if isinstance(report, dict):
            report.update({"skill_index_chars": 0, "skill_index_truncated": False,
                           "skill_index_omitted": 0, "skill_index_listed": []})
        return ""

    if budget_chars is None:
        try:
            from src.context_budget import SKILL_INDEX_BUDGET, resolve_prompt_budget
            budget_chars = resolve_prompt_budget(SKILL_INDEX_BUDGET, owner)
        except Exception:
            budget_chars = None

    block = _render(entries, can_fetch=can_fetch)
    listed = [str(e.get("name")) for e in entries]
    omitted = 0
    if budget_chars and len(block) > int(budget_chars):
        # Cheapest thing that is still correct: rank once, then bisect on how
        # many survive. The note's own length depends on the count it reports,
        # so it is re-rendered inside the test rather than added afterwards.
        ranked = sorted(entries, key=_index_value, reverse=True)
        lo, hi = 1, len(ranked)
        keep = 0
        while lo <= hi:
            mid = (lo + hi) // 2
            note = INDEX_TRUNCATION_NOTE.format(omitted=len(ranked) - mid)
            if len(_render(ranked[:mid], note, can_fetch=can_fetch)) <= int(budget_chars):
                keep, lo = mid, mid + 1
            else:
                hi = mid - 1
        if keep == 0:
            # The budget cannot hold the heading plus one entry. A heading with
            # nothing under it states that the library is empty, which is a
            # worse lie than an over-budget block, so one entry always survives.
            keep = 1
        omitted = len(ranked) - keep
        survivors = {id(e) for e in ranked[:keep]}
        listed = [str(e.get("name")) for e in entries if id(e) in survivors]
        block = _render([e for e in entries if id(e) in survivors],
                        INDEX_TRUNCATION_NOTE.format(omitted=omitted) if omitted else "",
                        can_fetch=can_fetch)

    if isinstance(report, dict):
        report.update({"skill_index_chars": len(block),
                       "skill_index_truncated": bool(omitted),
                       "skill_index_omitted": omitted,
                       # `B1365`. The names that actually reached the block.
                       # `P4-16`'s receipt was built from the list handed IN,
                       # so a catalogue cut to fit still told the person their
                       # model had seen all 286 of them.
                       "skill_index_listed": listed})
    return block


def _render_one_body(sk: Dict, *, max_steps: Optional[int] = None,
                    can_fetch: bool = True) -> str:
    """One matched skill, in the shape the prompt has always used.

    `B1362`. Moved verbatim out of `agent_loop._build_system_prompt` — the
    headings, the `_(learned from X)_` tag, the numbered procedure and the
    semicolon-joined pitfalls are the wording the model has been reading, and a
    budget is not an excuse to reword a prompt in the same change.

    `B1375`. `max_steps` renders the procedure's **first N steps** and one line
    saying how many remain and how to fetch them. The procedure is a list, so
    the count is exact; nothing here cuts a step in half. Everything above the
    procedure — the name, the description, the *when to use* — is always kept,
    because those are what the model needs to decide whether it wants the rest.
    The pitfalls go with the elided steps: a pitfall about step 9 read without
    step 9 is worse than no pitfall.
    """
    lines: List[str] = []
    src_tag = ""
    if sk.get("source") == "teacher-escalation":
        tm = sk.get("teacher_model") or "teacher"
        src_tag = f" _(learned from {tm})_"
    lines.append(f"\n### {sk.get('name', '?')}{src_tag}")
    if sk.get("description"):
        lines.append(str(sk["description"]))
    if sk.get("when_to_use"):
        lines.append(f"_When to use:_ {sk['when_to_use']}")
    proc = [str(step) for step in (sk.get("procedure") or [])]
    shown = proc if max_steps is None else proc[:max(int(max_steps), 0)]
    remaining = len(proc) - len(shown)
    if shown:
        lines.append("Procedure:")
        for i, step in enumerate(shown, 1):
            lines.append(f"  {i}. {step}")
    if remaining > 0:
        tpl = MATCHED_STEPS_ELIDED if can_fetch else MATCHED_STEPS_ELIDED_NO_FETCH
        lines.append(tpl.format(remaining=remaining, name=sk.get("name", "?")))
    pitfalls = sk.get("pitfalls") or []
    if pitfalls and remaining <= 0:
        lines.append("Pitfalls: " + "; ".join(str(p) for p in pitfalls))
    return "\n".join(lines)


def _step_count(sk: Dict) -> int:
    return len(sk.get("procedure") or [])


def render_matched_skills_block(skills: Optional[Sequence[Dict]],
                                *, budget_chars: Optional[int] = None,
                                owner=None, report: Optional[Dict] = None,
                                can_fetch: bool = True) -> str:
    """The matched-skill bodies, bounded, saying so when they were cut.

    `B1362`. These bodies are the expensive half of the skills message and the
    only half with no budget. Measured on `0bd089d` with the real builder: one
    long matched skill rendered **23,606 characters (~7,085 tokens)** and twelve
    rendered **257,813 (~77,347)** — against a default `agent_input_token_budget`
    of 6,000 — inside no budget anywhere, so the only thing that ever cut them
    was `context_compactor.trim_for_context`, from the front of the
    conversation, silently, taking the person's earlier turns with it. The
    catalogue beside them has been budgeted and has said when it was cut since
    `P8-21`; this is the same arrangement for the other half.

    Whole skills are dropped first, lowest-ranked last (the caller hands them in
    best-first, so the tail goes), and the **last** surviving body is cut at a
    line boundary rather than dropped if that is what it takes to fit — because a
    procedure's first steps are worth more than nothing, and the note says a
    procedure above may be short. `report`, when a dict is passed, is filled in
    with `skill_bodies_chars`, `skill_bodies_truncated`, `skill_bodies_omitted`
    and `skill_bodies_applied` — the names of the skills whose text actually
    reached the model, which is what `P4-16`'s receipt needs and what it could
    not say before (`B1363`).

    The floor: the heading, the preamble and the note are ~470 characters, and
    `context_skill_body_chars` may be set as low as 200, so a budget under that
    yields a block slightly over it rather than a heading with nothing beneath
    — the same call `P8-21` made for the catalogue's last surviving entry, for
    the same reason (an empty heading states that the match found nothing).
    """
    entries = [s for s in (skills or []) if isinstance(s, dict) and s.get("name")]
    if not entries:
        if isinstance(report, dict):
            report.update({"skill_bodies_chars": 0, "skill_bodies_truncated": False,
                           "skill_bodies_omitted": 0, "skill_bodies_applied": []})
        return ""

    if budget_chars is None:
        try:
            from src.context_budget import SKILL_BODY_BUDGET, resolve_prompt_budget
            budget_chars = resolve_prompt_budget(SKILL_BODY_BUDGET, owner)
        except Exception:
            budget_chars = None

    head = [MATCHED_HEADING, MATCHED_PREAMBLE if can_fetch else MATCHED_PREAMBLE_NO_FETCH]
    note_tpl = MATCHED_TRUNCATION_NOTE if can_fetch else MATCHED_TRUNCATION_NOTE_NO_FETCH

    def assemble(bodies: List[str], omitted: int, cut: bool,
                 shortened: int = 0) -> str:
        parts = list(head) + bodies
        if omitted or cut or shortened:
            if omitted:
                what = MATCHED_CUT_WHAT_OMITTED.format(omitted=omitted)
            elif shortened:
                what = MATCHED_CUT_WHAT_SHORTENED.format(shortened=shortened)
            else:
                what = MATCHED_CUT_WHAT_SHORT
            parts.append(note_tpl.format(what=what))
        return "\n".join(parts)

    bodies = [_render_one_body(s) for s in entries]
    block = assemble(bodies, 0, False)
    applied = [str(s.get("name")) for s in entries]
    shortened: List[str] = []
    truncated = False
    omitted = 0
    if budget_chars and len(block) > int(budget_chars):
        budget = int(budget_chars)
        truncated = True

        # `B1375`, on the owner's ruling. **Shorten before dropping.**
        #
        # This used to drop whole bodies from the tail until the rest fit, so
        # with twelve matched procedures against a 12,000-character budget ten
        # of them reached the model as the number ten — it could not know what
        # they were called, and so could not decide whether it wanted one. The
        # ladder now has a rung in between: every matched skill keeps its name,
        # description and *when to use*, and its procedure is cut to its first
        # N steps with a line saying how many remain and how to fetch them.
        #
        # One `N` for every skill rather than a share each, and the reason is
        # the failure it avoids: a per-skill share spends the whole budget on
        # whichever procedure happens to be longest, so the twelfth match gets
        # nothing while the first gets forty steps. A single N is also one
        # number a reader can check against the block.
        #
        # Walked downwards from the longest procedure, which is the only bound
        # that matters — `max_steps` above that is the whole body and `assemble`
        # is cheap (a join over a dozen strings).
        longest = max((_step_count(s) for s in entries), default=0)
        for n in range(longest - 1, 0, -1):
            trial = [_render_one_body(s, max_steps=n, can_fetch=can_fetch)
                     for s in entries]
            cut_names = [str(s.get("name")) for s in entries if _step_count(s) > n]
            if len(assemble(trial, 0, False, shortened=len(cut_names))) <= budget:
                block = assemble(trial, 0, False, shortened=len(cut_names))
                applied = [str(s.get("name")) for s in entries]
                shortened = cut_names
                break
        else:
            # Even one step each does not fit, so fall back to dropping whole
            # bodies from the tail — `B1362`'s behaviour, unchanged, and the
            # floor this row does not move. `keep == 0` still renders the first
            # body's opening lines: a heading with nothing under it says the
            # match found nothing, which is a worse answer than a short
            # procedure (the same call `P8-21` made for the catalogue's last
            # surviving entry).
            keep = 0
            for n in range(len(bodies), 0, -1):
                if len(assemble(bodies[:n], len(bodies) - n, False)) <= budget:
                    keep = n
                    break
            if keep == len(bodies):
                keep -= 1   # the untruncated form was already over budget
            omitted = len(bodies) - keep
            applied = [str(s.get("name")) for s in entries[:max(keep, 1)]]
            if keep == 0:
                # Cut the single best match at a line boundary.
                room = budget - len(assemble([], omitted - 1, True))
                kept_lines: List[str] = []
                used = 0
                for line in bodies[0].split("\n"):
                    if used + len(line) + 1 > max(room, 0):
                        break
                    kept_lines.append(line)
                    used += len(line) + 1
                if not kept_lines:
                    kept_lines = [bodies[0].split("\n", 2)[1] if "\n" in bodies[0] else bodies[0]]
                block = assemble(["\n".join(kept_lines)], omitted - 1, True)
            else:
                block = assemble(bodies[:keep], omitted, False)

    if isinstance(report, dict):
        report.update({"skill_bodies_chars": len(block),
                       "skill_bodies_truncated": bool(truncated),
                       "skill_bodies_omitted": int(omitted),
                       "skill_bodies_applied": applied,
                       # `B1375`. Which procedures reached the model as their
                       # opening steps. `applied` says whose text arrived and
                       # `omitted` how many did not; neither could say *this
                       # one arrived, in part*, which is now the common case.
                       "skill_bodies_shortened": list(shortened)})
    return block


# ── A skill the person invoked by name — `B1374` ─────────────────────────────
#
# `/skill-name` used to be answered by `POST /api/skills/{name}/invoke` with one
# string — *"Apply the skill below to my request… --- BEGIN SKILL ---\n{md}\n---
# END SKILL ---\n\nRequest: …"* — that the composer sent **as the person's own
# message**. So the skill's text arrived in the one shape `UNTRUSTED_CONTEXT_
# POLICY` tells the model is *"the request you are answering"*, and the markers
# `_escape_guard_markers` neutralises on every other surface were not applied: a
# SKILL.md holding `<<<END_USER_SAVED_MATERIAL>>>` or `--- END SKILL ---` could
# close its own fence and carry on speaking as the person. Every other skills
# surface was already framed — the catalogue and the matched bodies in
# `own_context_message` (`B1328`), the skill under test and a workflow's Skill
# step in `untrusted_context_message` (`P8-18`). This is the last door, and it
# goes through the same envelope and the same escaper as the matched block.

#: Pantheon's own note for the turn, beside the framed skill: which skill the
#: person ran, for which message. The name is a stored slug, never free text.
INVOKED_SKILL_NOTE = (
    "The user ran /{name} for the message that follows: apply the skill `{name}` "
    "— its procedure, pitfalls and verification are in their saved material just "
    "above — to that request."
)

#: What the composer sends as the person's message when they typed only the
#: command. Their words, not the skill's.
INVOKED_SKILL_EMPTY_REQUEST = "Use the {name} skill."


def invokable_skill(skills_manager, owner, name: str) -> Optional[Dict]:
    """The index entry `name` may be invoked as, or None. One rule for
    `POST /api/skills/{name}/invoke` and for the turn that carries it: what
    the person's catalogue lists (`index_for`) is what a slash may name."""
    want = str(name or "").strip()
    if not want:
        return None
    for entry in skills_manager.index_for(owner=owner):
        if (entry.get("name") or "").strip() == want:
            return entry
    return None


def invoked_skill_messages(skills_manager, owner, name: str) -> List[Dict]:
    """The framed skill and the turn's note, for the person's `/name` turn.

    `[]` when the skill is not one this person may invoke or its source cannot
    be read — the turn then carries the person's request alone, which is what
    they typed.
    """
    from src.prompt_security import own_context_message, turn_note_message

    entry = invokable_skill(skills_manager, owner, name)
    if entry is None:
        return []
    skill_name = entry.get("name")
    # `B1419`. The index offers shipped skills; their source is the library's.
    md = skills_manager.read_skill_md(skill_name, owner=owner, include_library=True)
    if not md:
        return []
    return [
        own_context_message(f"the skill {skill_name}, which the user invoked by name", md),
        turn_note_message(INVOKED_SKILL_NOTE.format(name=skill_name)),
    ]
