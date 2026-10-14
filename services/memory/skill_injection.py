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
    `INDEX_PREAMBLE_NO_FETCH`. The preview endpoint leaves it True, because it
    is answering *"what can the model see"* and not building a turn.
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


def _render_one_body(sk: Dict) -> str:
    """One matched skill, in the shape the prompt has always used.

    `B1362`. Moved verbatim out of `agent_loop._build_system_prompt` — the
    headings, the `_(learned from X)_` tag, the numbered procedure and the
    semicolon-joined pitfalls are the wording the model has been reading, and a
    budget is not an excuse to reword a prompt in the same change.
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
    proc = sk.get("procedure") or []
    if proc:
        lines.append("Procedure:")
        for i, step in enumerate(proc, 1):
            lines.append(f"  {i}. {step}")
    pitfalls = sk.get("pitfalls") or []
    if pitfalls:
        lines.append("Pitfalls: " + "; ".join(str(p) for p in pitfalls))
    return "\n".join(lines)


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

    def assemble(bodies: List[str], omitted: int, cut: bool) -> str:
        parts = list(head) + bodies
        if omitted or cut:
            what = (MATCHED_CUT_WHAT_OMITTED.format(omitted=omitted) if omitted
                    else MATCHED_CUT_WHAT_SHORT)
            parts.append(note_tpl.format(what=what))
        return "\n".join(parts)

    bodies = [_render_one_body(s) for s in entries]
    block = assemble(bodies, 0, False)
    applied = [str(s.get("name")) for s in entries]
    truncated = False
    omitted = 0
    if budget_chars and len(block) > int(budget_chars):
        budget = int(budget_chars)
        keep = 0
        # Drop whole bodies from the tail until the head, the note and what is
        # left fit. `keep == 0` still renders the first body's opening lines:
        # a heading with nothing under it says the match found nothing, which is
        # a worse answer than a short procedure (the same call `P8-21` made for
        # the catalogue's last surviving entry).
        for n in range(len(bodies), 0, -1):
            if len(assemble(bodies[:n], len(bodies) - n, False)) <= budget:
                keep = n
                break
        if keep == len(bodies):
            keep -= 1   # the untruncated form was already over budget
        omitted = len(bodies) - keep
        truncated = True
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
                       "skill_bodies_applied": applied})
    return block
