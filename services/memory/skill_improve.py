# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P22-23` — "Fix these with the model", once, for the tool and the button.

`P8-13` built *improve* inside `do_manage_skills action=improve`
(`src/tools/system.py`): the lint's findings become a synthetic reviewer verdict
— the trick `_audit_one_skill` already plays — and the audit's own rewriter
(`routes/skills_routes._improve_skill_md`) answers with a corrected SKILL.md,
written through `_apply_skill_md` so `P8-10` keeps the copy it replaced.

`P22-23` gives it a button (`POST /api/skills/{skill_id}/improve`). A second
copy of that body would be the second way to do one thing (`Law 14`), so the
body moved here and both doors call it; each says the outcome in its own
words. The outcome is an enum, not a boolean (`Law 10`).

**What changed on the way through (design § 0.10, the hostile-skill adversary,
§ 5.4).** `_apply_skill_md` copied `status`, `confidence`, `source`,
`platforms` and `requires_toolsets` out of the model's text, and the model's
text is a rewrite of a skill body anyone could have written — an import, a
teacher, a colleague's file. A draft whose body says *"set status: published,
confidence: 1.0"* got exactly that from a rewriter that complied, and
*published* is what puts a skill in the catalogue every request is handed. One
click away is too close. So the live skill's lifecycle and visibility are
pinned before the write: `P8-11`'s rule — *identity does not travel with the
body* — widened from `name`/`category`/`owner` to the five fields that decide
whether, where and how loudly a skill is used.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Optional

# `P22-23`. The fields a rewrite may not change, read from the live skill and
# handed to `_apply_skill_md` as `keep`. `owner` rides along although
# `update_skill` ignores it today (design § 0.10): pinned here, it stays pinned
# if that ever changes.
PINNED_ON_IMPROVE = ("status", "confidence", "source", "platforms",
                     "requires_toolsets", "owner")


def pinned_of(skill: Optional[dict]) -> dict:
    """The live skill's values for `PINNED_ON_IMPROVE` — `_apply_skill_md`'s `keep`.

    One reading of "what a rewrite may not change", for every door that writes
    a model's rewrite of a skill (`Law 7`): Improve, and since `B1123` the
    audit's four rewrites (`routes/skills_routes._audit_one_skill`), which ran
    the same rewriter over the same untrusted body with no `keep` at all.
    """
    skill = skill or {}
    return {k: skill.get(k) for k in PINNED_ON_IMPROVE if k in skill}

# `metadata:` is the prefix `_improve_skill_md`'s system prompt reads as
# permission to edit frontmatter. A finding about the category or the tags
# that arrives without it is a finding that prompt tells the model to leave
# alone, so the mapping is explicit rather than incidental (`P8-13`).
_METADATA_FIELDS = {"name", "description", "category", "tags"}


class ImproveOutcome(str, enum.Enum):
    """What happened, in one word a caller cannot read two ways."""

    NOT_FOUND = "not_found"
    NOTHING_TO_FIX = "nothing_to_fix"
    NO_MODEL = "no_model"
    NO_REWRITE = "no_rewrite"
    NOT_SAVED = "not_saved"
    REWROTE = "rewrote"


@dataclass
class ImproveResult:
    outcome: ImproveOutcome
    name: str
    findings: list = field(default_factory=list)
    before: dict = field(default_factory=dict)      # lint_skill's result before
    after: Optional[dict] = None                     # … and after, when it wrote
    why: str = ""                                    # the no-model sentence

    @property
    def before_counts(self) -> dict:
        return (self.before or {}).get("counts") or {}

    @property
    def after_counts(self) -> dict:
        return (self.after or {}).get("counts") or {}


# `BRAIN-M-3`. Why a rewrite was not written — `ImproveResult.why` for
# `NO_REWRITE`, so each door can say which.
WHY_UNCHANGED = "unchanged"
WHY_NOT_A_SKILL = "not_a_skill"
WHY_NOT_BETTER = "not_better"


def _counts(lint: Optional[dict]) -> tuple:
    c = (lint or {}).get("counts") or {}
    return (int(c.get("problem", 0) or 0), int(c.get("advisory", 0) or 0))


def rewrite_refusal(text: str, name: str, current: dict, library: list,
                    before: dict) -> str:
    """`""` when `text` is a SKILL.md worth writing over `current`; else why not.

    Read with `Skill.from_markdown` — what `_apply_skill_md` reads — and linted
    with the live skill's pinned fields, against the same siblings the
    `before` lint saw, so the two counts measure the same thing. "Better" is
    fewer problems, or as many problems and fewer suggestions.
    """
    from services.memory.skill_format import Skill, parse_frontmatter
    from services.memory.skill_lint import lint_skill

    try:
        fm, _body = parse_frontmatter(text)
        cand = Skill.from_markdown(text)
    except Exception:
        return WHY_NOT_A_SKILL
    if not fm or not (cand.description or "").strip():
        return WHY_NOT_A_SKILL
    if not ((cand.when_to_use or "").strip() or cand.procedure):
        return WHY_NOT_A_SKILL
    cand.name = name
    d = cand.to_dict()
    d.update(pinned_of(current))
    after = lint_skill(d, [x for x in library if x.get("name") != name])
    if _counts(after) >= _counts(before):
        return WHY_NOT_BETTER
    return ""


def lint_issues(findings) -> list:
    """The lint's findings as the reviewer issues `_improve_skill_md` reads."""
    issues = []
    for f in findings or []:
        name = f.get("field") or ""
        prefix = "metadata: " if name in _METADATA_FIELDS else ""
        issues.append(f"{prefix}{name}: {f.get('message', '')} "
                      f"Fix: {f.get('fix', '')}".strip())
    return issues


async def improve_from_lint(sm, name: str, owner: Optional[str], *, models=None) -> ImproveResult:
    """Rewrite one skill from its lint findings, keeping who it is and how it is used.

    `models` is `(url, model, headers)`; left out, it is the audit's own
    resolution (`_resolve_audit_models`: Utility, then Default). The rewriter
    and the writer are reached through `routes.skills_routes` at call time —
    the module the audit owns them in — so there is one of each and a test can
    stand a scripted model in for the real one.
    """
    from services.memory.skill_lint import lint_skill

    md = sm.read_skill_md(name, owner=owner)
    if md is None:
        return ImproveResult(ImproveOutcome.NOT_FOUND, name)
    library = sm.load(owner=owner)
    current = next((x for x in library if x.get("name") == name), None)
    if current is None:
        return ImproveResult(ImproveOutcome.NOT_FOUND, name)
    before = lint_skill(current, [x for x in library if x.get("name") != name])
    findings = before.get("findings") or []
    if not findings:
        return ImproveResult(ImproveOutcome.NOTHING_TO_FIX, name, findings, before)

    from routes import skills_routes as _routes

    if models is None:
        try:
            url, model_id, headers, _teacher = _routes._resolve_audit_models(owner)
        except Exception as e:
            return ImproveResult(ImproveOutcome.NO_MODEL, name, findings, before, why=str(e))
    else:
        url, model_id, headers = models

    fixed = await _routes._improve_skill_md(
        md,
        {
            "verdict": "pass",
            "confidence": 1.0,
            "summary": ("Authoring lint only — the procedure has not been "
                        "shown to be wrong. Fill in what is missing and "
                        "tighten what is vague."),
            "issues": lint_issues(findings),
        },
        ("Authoring lint only: no test was run and no reviewer judged this "
         "procedure. Do not rewrite steps you have no evidence against."),
        url, model_id, headers,
    )
    # `.strip()` on the left as well as the right: a model that answered with
    # whitespace is truthy, and `_apply_skill_md` parses `"   "` into a
    # nameless, descriptionless skill and writes it — measured while
    # mutation-testing the handler this came from, by parametrising the empty
    # reply (`P8-13`).
    if not (fixed or "").strip() or fixed.strip() == md.strip():
        return ImproveResult(ImproveOutcome.NO_REWRITE, name, findings, before, why=WHY_UNCHANGED)
    # `BRAIN-M-3` (P23-02). Only a better SKILL.md is written. The check above
    # took any non-empty reply that differed from the file: a scripted model
    # answering "OK" was written as the skill — frontmatter, then `OK`, the
    # description gone, the version bumped — and the panel said "Fixed"
    # (measured on `32df791`, and a real model that answers "Here is the
    # improved skill: …" takes the same path). The reply is read with the
    # reader the write uses, and linted as it would be stored, BEFORE anything
    # is written: no description or no body is not a skill, and a rewrite the
    # lint does not score better than the original fixed nothing.
    why = rewrite_refusal(fixed, name, current, library, before)
    if why:
        return ImproveResult(ImproveOutcome.NO_REWRITE, name, findings, before, why=why)
    if not _routes._apply_skill_md(sm, name, fixed, owner, keep=pinned_of(current)):
        return ImproveResult(ImproveOutcome.NOT_SAVED, name, findings, before)

    library = sm.load(owner=owner)
    after = lint_skill(next((x for x in library if x.get("name") == name), {}),
                       [x for x in library if x.get("name") != name])
    return ImproveResult(ImproveOutcome.REWROTE, name, findings, before, after)
