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


def render_skill_index_block(index: Optional[Sequence[Dict]]) -> str:
    """The exact text injected as the skills catalogue, or `""` for none.

    `index` is what `SkillsManager.index_for()` returns. The leading blank line
    is part of the block: the loop concatenates it straight onto a prompt, so
    moving the separator out of here would move the bug out of reach of the
    preview along with it.
    """
    entries = [s for s in (index or []) if isinstance(s, dict) and s.get("name")]
    if not entries:
        return ""
    lines: List[str] = [INDEX_HEADING, INDEX_PREAMBLE]
    by_cat: Dict[str, list] = {}
    for s in entries:
        by_cat.setdefault(s.get("category") or "general", []).append(s)
    for cat in sorted(by_cat):
        lines.append(f"\n**{cat}**")
        for s in by_cat[cat]:
            badge = " *(draft)*" if s.get("status") == "draft" else ""
            lines.append(f"- `{s['name']}` — {s.get('description') or ''}{badge}")
    return "\n\n" + "\n".join(lines)
