# SPDX-License-Identifier: AGPL-3.0-or-later
# services/memory/skill_lint.py
"""What is wrong with this skill, answered before it is saved.

`P8-12`. **Premise corrected 2026-09-18.** The row says the necessity and
retrieval-precision judges "are pure functions of `(skill, siblings)` … callable
with no refactor". Measured against the source: they are not. `_eval_skill_necessity`
and `_eval_skill_retrieval_precision` in `routes/skills_routes.py` are `async`
functions that each take `(skill_md, others, url, model, headers)` and make a
120-second and a 90-second `llm_call_async` respectively. Neither is pure and
neither is callable from a save handler that has to answer while a person waits.

What *is* pure, and what this module is built from, is the cheap half the audit
already runs **around** those two calls and never exposed to an author:

  * `_should_check_retrieval_precision` — the broad-tag prefilter that decides
    whether the expensive judge is worth running at all. A pure function of the
    skill alone.
  * `_audit_generic_blocker` — the "is this trivial?" regex over tags, verdict
    prose and necessity reasons. Pure.
  * the duplicate-similarity core inside `_skill_duplicate_blocker` — token
    overlap against every sibling, at the same `0.38` the audit uses. Pure once
    the sibling list is handed in rather than loaded.

All three lived in `routes/skills_routes.py`, which is the wrong layer for
something a manager, a tool handler and a route all want. They live here now and
`skills_routes` imports them back under their old private names, so there is one
implementation rather than a second one written for the author-facing path
(`Law 14` — a second similarity function is exactly the fork this codebase
already has four of).

The structural checks are the other half, and they come from `P8-17`: the schema
supports pitfalls, verification, when-to-use and category, and the things that
write skills kept leaving them empty. A lint that says so at authoring time is
what makes the gap visible to the person who can fix it.

**Nothing here blocks a save.** `verdict` is an enum — `clean` · `advisories` ·
`problems` — rather than an `ok` boolean, because a boolean verdict in this repo
has already been read in both directions at once (`Law 10`).
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Sequence

from .skill_format import slugify

# The audit's duplicate threshold. One constant, used by the nightly blocker and
# by the author-facing lint, so "is this a duplicate?" has one answer.
DUPLICATE_SIMILARITY = 0.38

# A description longer than this is truncated by `SkillAddRequest` (max_length=200)
# and pushes every other entry down the index block.
MAX_DESCRIPTION = 200

_STOPWORDS = frozenset({"the", "and", "with", "for", "from", "using"})
_TOKEN_SPLIT_RE = re.compile(r"[^a-z0-9]+")
_TRAILING_INDEX_RE = re.compile(r"-\d+\b")
_NAME_SUFFIX_RE = re.compile(r"-\d+$")

_GENERIC_RE = re.compile(
    r"\b(too[-\s]?generic|generic|trivial|capable assistant|without a saved|"
    r"not need|unnecessary|irrelevant)\b",
    re.I,
)

# Tags broad enough to over-select. The audit's prefilter list, unchanged.
BROAD_TAGS = frozenset({
    "arch", "arch linux", "linux", "network", "networking", "wifi",
    "installation", "install", "system", "ssh", "document", "documents",
    "search", "email", "calendar", "gpu", "server", "python",
})


# ---------------------------------------------------------------------------
# The pure predicates the audit already ran, now reachable from anywhere
# ---------------------------------------------------------------------------

def skill_tokens(sk: Dict) -> set:
    """Comparison tokens for one skill. The audit's `_tokens`, unmoved in spirit."""
    if not isinstance(sk, dict):
        return set()
    text = " ".join([
        str(sk.get("name") or ""),
        str(sk.get("description") or ""),
        str(sk.get("when_to_use") or ""),
        " ".join(sk.get("procedure") or []),
        " ".join(sk.get("tags") or []),
    ]).lower()
    text = _TRAILING_INDEX_RE.sub("", text)
    return {t for t in _TOKEN_SPLIT_RE.split(text) if len(t) > 2 and t not in _STOPWORDS}


def skill_similarity(a: Dict, b: Dict) -> float:
    """Jaccard overlap of two skills' comparison tokens. 0.0 when either is empty."""
    A, B = skill_tokens(a), skill_tokens(b)
    if not A or not B:
        return 0.0
    return len(A & B) / max(1, len(A | B))


def base_name(n) -> str:
    """`open-pr-2` → `open-pr`. The dedup suffix `add_skill` appends is not identity."""
    return _NAME_SUFFIX_RE.sub("", str(n or ""))


def should_check_retrieval_precision(skill: Optional[Dict]) -> bool:
    """Cheap prefilter for the expensive retrieval-precision judge.

    Skills with broad tags like "network" or "document" are the ones most likely
    to over-inject. Narrow command/vendor tags alone are fine.
    """
    if not isinstance(skill, dict):
        return False
    tags = {str(t or "").strip().lower() for t in (skill.get("tags") or [])}
    if tags & BROAD_TAGS:
        return True
    text = " ".join([
        str(skill.get("name") or ""),
        str(skill.get("description") or ""),
        str(skill.get("when_to_use") or ""),
    ]).lower()
    return sum(1 for t in BROAD_TAGS if t in text) >= 2


def audit_flag_text(*parts) -> str:
    text_parts: List[str] = []
    for part in parts:
        if isinstance(part, dict):
            text_parts.extend(str(v or "") for v in part.values())
        elif isinstance(part, (list, tuple, set)):
            text_parts.extend(str(v or "") for v in part)
        else:
            text_parts.append(str(part or ""))
    return " ".join(text_parts).lower()


def audit_generic_blocker(skill: Optional[Dict], necessity: Optional[Dict],
                          verdict_data: Optional[Dict]) -> Optional[str]:
    """Return a short reason when a generic/trivial skill must stay draft."""
    if isinstance(necessity, dict):
        reason = str(necessity.get("reason") or "")
        if necessity.get("necessary") is False and _GENERIC_RE.search(reason):
            return reason or "Generic or unnecessary skill"

    if isinstance(skill, dict):
        tag_text = audit_flag_text(skill.get("tags") or [])
        if _GENERIC_RE.search(tag_text):
            return "Skill is tagged generic"

    if isinstance(verdict_data, dict):
        verdict_text = audit_flag_text(
            verdict_data.get("summary"),
            verdict_data.get("issues") or [],
        )
        if _GENERIC_RE.search(verdict_text):
            return "Audit flagged the skill as generic or unnecessary"
    return None


# ---------------------------------------------------------------------------
# The lint itself
# ---------------------------------------------------------------------------

PROBLEM = "problem"
ADVISORY = "advisory"


def _finding(code: str, severity: str, field: str, message: str, fix: str) -> Dict:
    return {"code": code, "severity": severity, "field": field,
            "message": message, "fix": fix}


def lint_skill(skill: Optional[Dict], siblings: Optional[Sequence[Dict]] = None) -> Dict:
    """Everything wrong with `skill`, judged against `siblings`, with no model call.

    `skill` is a skill dict — `Skill.to_dict()`, a `/api/skills/add` body, or the
    half-filled thing an editor holds mid-typing. `siblings` is the rest of the
    library as the same caller can see it; pass `[]` when there is nothing to
    compare against and the duplicate check simply finds nothing.
    """
    if not isinstance(skill, dict):
        return {"verdict": "problems", "counts": {PROBLEM: 1, ADVISORY: 0},
                "findings": [_finding("not-a-skill", PROBLEM, "", "Not a skill object.",
                                      "Send the skill's fields as a JSON object.")]}

    findings: List[Dict] = []
    name = str(skill.get("name") or "").strip()
    description = str(skill.get("description") or skill.get("title") or "").strip()
    when = str(skill.get("when_to_use") or skill.get("problem") or "").strip()
    procedure = [str(x) for x in (skill.get("procedure") or skill.get("steps") or []) if str(x).strip()]
    pitfalls = [str(x) for x in (skill.get("pitfalls") or []) if str(x).strip()]
    verification = [str(x) for x in (skill.get("verification") or []) if str(x).strip()]
    tags = [str(t).strip() for t in (skill.get("tags") or []) if str(t).strip()]
    category = str(skill.get("category") or "").strip()

    # --- the three that make a skill unusable -----------------------------
    if not name:
        findings.append(_finding(
            "missing-name", PROBLEM, "name",
            "No name. The name is the identity, the directory and the API id.",
            "Give it a short kebab-case name, e.g. `rotate-nginx-logs`."))
    elif slugify(name) != name:
        findings.append(_finding(
            "name-not-a-slug", ADVISORY, "name",
            f"Saving will rewrite this name to `{slugify(name)}`.",
            "Use the slug form yourself so the name you see is the name you get."))

    if not description:
        findings.append(_finding(
            "missing-description", PROBLEM, "description",
            "No description. The index line the model reads is the name and this "
            "sentence — without it the entry is a bare name with nothing after the dash.",
            "One line saying what the procedure does."))
    elif len(description) > MAX_DESCRIPTION:
        findings.append(_finding(
            "description-too-long", ADVISORY, "description",
            f"{len(description)} characters; the API truncates at {MAX_DESCRIPTION}.",
            "Shorten it to one line — the rest belongs in When to Use."))

    if not when:
        findings.append(_finding(
            "missing-when-to-use", PROBLEM, "when_to_use",
            "No When to Use. Retrieval matches the request against this text, so a "
            "skill without it is only found when the request happens to echo its name.",
            "Describe the situation that should trigger it, in the words a user would use."))

    if not procedure:
        findings.append(_finding(
            "missing-procedure", PROBLEM, "procedure",
            "No Procedure. There is nothing for the model to follow.",
            "Add the numbered steps, in the order they are performed."))

    # --- the ones the schema supports and the writers keep leaving empty ---
    if not verification:
        findings.append(_finding(
            "missing-verification", ADVISORY, "verification",
            "No Verification. Nothing says how to tell the procedure worked.",
            "Add one check per expected outcome."))
    if not pitfalls:
        findings.append(_finding(
            "missing-pitfalls", ADVISORY, "pitfalls",
            "No Pitfalls. The failure modes you already know are the part a "
            "re-derivation will not recover.",
            "Add the mistakes worth warning about, and how to get out of each."))
    if not tags:
        findings.append(_finding(
            "no-tags", ADVISORY, "tags",
            "No tags. A whole-token tag match is the strongest retrieval signal there is.",
            "Add three to five keywords a user would actually type."))
    if not category or category == "general":
        findings.append(_finding(
            "default-category", ADVISORY, "category",
            "Category is `general`, so this skill sorts into the catch-all group "
            "in the index the model reads.",
            "Name the area — `dev`, `email`, `system`, whatever groups it with its neighbours."))

    # --- retrieval precision, from the audit's own prefilter ----------------
    if should_check_retrieval_precision(skill):
        broad = sorted({t.lower() for t in tags} & BROAD_TAGS)
        findings.append(_finding(
            "broad-retrieval", ADVISORY, "tags",
            "Broad trigger metadata"
            + (f" ({', '.join(broad)})" if broad else "")
            + " — this will be selected for adjacent requests it does not answer.",
            "Narrow the tags and the When to Use wording to the case you mean."))

    generic = audit_generic_blocker(skill, None, None)
    if generic:
        findings.append(_finding(
            "generic", ADVISORY, "tags", generic,
            "The nightly audit keeps skills flagged this way as drafts. Say what is "
            "specific and non-obvious about the procedure, or drop it."))

    # --- duplicates, at the threshold the audit uses ------------------------
    for other in (siblings or []):
        if not isinstance(other, dict):
            continue
        other_name = str(other.get("name") or other.get("id") or "").strip()
        if not other_name or other_name == name:
            continue
        same_base = bool(name) and base_name(name) == base_name(other_name)
        score = skill_similarity(skill, other)
        if same_base or score >= DUPLICATE_SIMILARITY:
            findings.append(_finding(
                "duplicate-of", PROBLEM, "name",
                f"Overlaps `{other_name}`"
                + (" (same base name)" if same_base else f" ({int(round(score * 100))}% token overlap)")
                + ". The nightly audit demotes the lower-priority one of a pair to draft.",
                f"Edit `{other_name}` instead, or narrow this one so the two do not compete."))
            break

    counts = {
        PROBLEM: sum(1 for f in findings if f["severity"] == PROBLEM),
        ADVISORY: sum(1 for f in findings if f["severity"] == ADVISORY),
    }
    if counts[PROBLEM]:
        verdict = "problems"
    elif counts[ADVISORY]:
        verdict = "advisories"
    else:
        verdict = "clean"
    return {"verdict": verdict, "counts": counts, "findings": findings}


def format_lint(result: Optional[Dict]) -> str:
    """The lint as text, for the tool channel and the log. Empty when clean."""
    if not isinstance(result, dict):
        return ""
    findings = result.get("findings") or []
    if not findings:
        return "Lint: clean — nothing to fix."
    lines = []
    for f in findings:
        mark = "!" if f.get("severity") == PROBLEM else "-"
        field = f.get("field") or ""
        lines.append(f"{mark} {field}: {f.get('message', '')} → {f.get('fix', '')}".strip())
    counts = result.get("counts") or {}
    head = (f"Lint: {counts.get(PROBLEM, 0)} problem(s), "
            f"{counts.get(ADVISORY, 0)} advisory(ies).")
    return head + "\n" + "\n".join(lines)
