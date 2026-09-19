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
INDEX_PREAMBLE = (
    "Procedures the assistant should consult before doing domain work. "
    "Fetch the full procedure with `manage_skills` action=view name=<name> "
    "when one looks relevant. Entries tagged `(draft)` were written by the "
    "teacher-escalation loop after a prior failure — treat them as authoritative "
    "guidance; if you follow one and it works, that's a good signal the procedure "
    "is correct."
)

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


def _render(entries: Sequence[Dict], note: str = "") -> str:
    lines: List[str] = [INDEX_HEADING, INDEX_PREAMBLE]
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
                             owner=None, report: Optional[Dict] = None) -> str:
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
    """
    entries = [s for s in (index or []) if isinstance(s, dict) and s.get("name")]
    if not entries:
        if isinstance(report, dict):
            report.update({"skill_index_chars": 0, "skill_index_truncated": False,
                           "skill_index_omitted": 0})
        return ""

    if budget_chars is None:
        try:
            from src.context_budget import SKILL_INDEX_BUDGET, resolve_prompt_budget
            budget_chars = resolve_prompt_budget(SKILL_INDEX_BUDGET, owner)
        except Exception:
            budget_chars = None

    block = _render(entries)
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
            if len(_render(ranked[:mid], note)) <= int(budget_chars):
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
        block = _render([e for e in entries if id(e) in survivors],
                        INDEX_TRUNCATION_NOTE.format(omitted=omitted) if omitted else "")

    if isinstance(report, dict):
        report.update({"skill_index_chars": len(block),
                       "skill_index_truncated": bool(omitted),
                       "skill_index_omitted": omitted})
    return block
