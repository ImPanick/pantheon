# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P8-12` — everything wrong with a skill, before it is saved, with no model call.

**The row's premise was wrong and is corrected on the row.** It says the
necessity and retrieval-precision judges "are pure functions of
`(skill, siblings)` … callable with no refactor". Measured 2026-09-18 against
`routes/skills_routes.py`: `_eval_skill_necessity` and
`_eval_skill_retrieval_precision` are `async` and each take
`(skill_md, others, url, model, headers)` and make an `llm_call_async` with a
120-second and a 90-second timeout. Neither is pure; neither can run while a
person waits for a save to complete.

What *is* pure is the cheap half the audit already runs around them — the
broad-tag prefilter that decides whether the expensive judge is worth calling,
the generic/trivial regex, and the duplicate-similarity comparison — plus the
structural facts nothing was checking at all. That is what `lint_skill` is, and
these tests measure it the way an author meets it: a half-written skill in, a
list of things to fix out, instantly.

`test_the_lint_and_the_nightly_audit_share_one_duplicate_comparison` is the one
that matters for `Law 14`: the lint and the nightly audit have to be using
**one** comparison, because two would be two answers to "is this a duplicate?"
that drift apart and leave a user told one thing at save time and the opposite
the next morning. Its fixture is tuned to sit in the middle of the band rather
than at the top of it, so moving the shared constant moves the answer — a pair
of near-identical skills scores 0.96 and would satisfy any threshold, which
would have made that test measure nothing.
"""

import json

import pytest

from routes.skills_routes import _skill_duplicate_blocker
from services.memory.skill_lint import (
    ADVISORY,
    DUPLICATE_SIMILARITY,
    PROBLEM,
    lint_skill,
    skill_similarity,
)
from services.memory.skills import SkillsManager
from src.tools.system import do_manage_skills

COMPLETE = {
    "name": "rotate-nginx-logs",
    "description": "Rotate and prune nginx access logs on a full disk",
    "category": "ops",
    "tags": ["nginx", "logrotate", "disk"],
    "when_to_use": "When /var/log has filled up and nginx is still writing to it",
    "procedure": ["Run logrotate -f /etc/logrotate.d/nginx",
                  "Confirm nginx reopened its handles with lsof"],
    "pitfalls": ["Deleting the open file frees no space until nginx reopens it"],
    "verification": ["df -h /var shows the space back"],
}


def _codes(result):
    return {f["code"] for f in result["findings"]}


def test_a_complete_skill_is_clean():
    result = lint_skill(COMPLETE, [])
    assert result["verdict"] == "clean", result["findings"]
    assert result["findings"] == []


def test_the_empty_sections_the_schema_supports_are_named_one_by_one():
    # `P8-17`'s finding from the author's side: the format has had Pitfalls and
    # Verification all along and the things that write skills leave them empty,
    # so nobody is ever told they are missing.
    result = lint_skill({"name": "half-written"}, [])
    assert result["verdict"] == "problems"
    assert {"missing-description", "missing-when-to-use", "missing-procedure"} <= _codes(result)
    assert {"missing-pitfalls", "missing-verification", "no-tags"} <= _codes(result)
    for f in result["findings"]:
        assert f["fix"], f"{f['code']} says what is wrong and not what to do about it"
        assert f["severity"] in (PROBLEM, ADVISORY)


def test_the_three_that_make_a_skill_unusable_outrank_the_rest():
    # A skill with no procedure is not a skill. A skill with no Pitfalls is a
    # thinner skill. The verdict has to be able to say which it is looking at,
    # which is why severity is an enum beside an enum rather than one boolean
    # standing in for both (`Law 10`).
    result = lint_skill({"name": "x", "description": "d", "when_to_use": "w",
                         "procedure": ["one"], "tags": ["t"], "category": "ops"}, [])
    assert result["verdict"] == "advisories"
    assert result["counts"][PROBLEM] == 0
    assert result["counts"][ADVISORY] > 0


def test_a_description_nobody_can_read_is_flagged_at_the_length_the_api_truncates():
    long_one = dict(COMPLETE, description="x" * 201)
    assert "description-too-long" in _codes(lint_skill(long_one, []))
    assert "description-too-long" not in _codes(
        lint_skill(dict(COMPLETE, description="x" * 200), []))


def test_a_name_that_will_be_rewritten_says_so_before_it_is(tmp_path):
    # `slugify` runs on save, so "Rotate Nginx Logs" becomes
    # "rotate-nginx-logs" and the person who typed it finds out afterwards.
    result = lint_skill(dict(COMPLETE, name="Rotate Nginx Logs"), [])
    assert "name-not-a-slug" in _codes(result)
    assert "rotate-nginx-logs" in " ".join(f["message"] for f in result["findings"])


def test_broad_trigger_metadata_is_flagged_without_calling_a_model(monkeypatch):
    # The audit's own prefilter, reachable at authoring time. If this ever
    # reaches for a model it will hang a save, so the call is removed outright.
    import src.llm_core as llm_core

    async def _explode(*a, **k):  # pragma: no cover - the point is it is not called
        raise AssertionError("the lint called a model")

    monkeypatch.setattr(llm_core, "llm_call_async", _explode, raising=False)
    result = lint_skill(dict(COMPLETE, tags=["network", "system", "python"]), [])
    assert "broad-retrieval" in _codes(result)


def test_the_lint_and_the_nightly_audit_share_one_duplicate_comparison(tmp_path):
    # `Law 14`. Two similarity functions would be two answers to the same
    # question — the save saying "fine" and the audit demoting it overnight.
    sm = SkillsManager(str(tmp_path), library_root="")
    # Deliberately *similar*, not near-identical. Two copies of the same words
    # score 0.96 and would be flagged by any threshold at all, so a fixture like
    # that measures nothing about where the line actually is. This pair scores
    # 0.58 — comfortably over the 0.38 both sides use and comfortably under a
    # careless one — so moving the constant moves the answer.
    sm.add_skill(name="rotate-nginx-logs", description=COMPLETE["description"],
                 category="ops", tags=COMPLETE["tags"],
                 when_to_use=COMPLETE["when_to_use"],
                 procedure=COMPLETE["procedure"], source="user",
                 status="published", owner=None)
    sm.add_skill(name="clear-nginx-logs",
                 description="Clear nginx access logs on a full disk",
                 category="ops", tags=["nginx", "disk"],
                 when_to_use="When /var/log has filled up",
                 procedure=["Run logrotate for nginx",
                            "Check nginx handles with lsof"],
                 source="user", status="published", owner=None)

    library = sm.load(owner=None)

    # The two ask different questions of the same comparison, and that is worth
    # stating: the lint asks "does this overlap something?" and flags both
    # halves of a pair, while the audit's blocker asks "is this the one that
    # loses?" and returns the keeper's name only for the loser. What must agree
    # is the comparison underneath — which pairs are close enough to count.
    for name in ("rotate-nginx-logs", "clear-nginx-logs"):
        subject = next(s for s in library if s["name"] == name)
        siblings = [s for s in library if s["name"] != name]
        assert "duplicate-of" in _codes(lint_skill(subject, siblings)), (
            f"the lint did not see that {name} overlaps its sibling"
        )
        assert skill_similarity(subject, siblings[0]) >= DUPLICATE_SIMILARITY

    # …and the audit reaches the same conclusion through the same function.
    # Raising `DUPLICATE_SIMILARITY` has to move both of these or they are not
    # one comparison, whatever the imports say.
    # Both are published with equal confidence and no uses, so the audit's
    # tie-break is the last term in `_score`: the shorter name keeps.
    assert _skill_duplicate_blocker(sm, "rotate-nginx-logs", None) == "clear-nginx-logs"
    assert _skill_duplicate_blocker(sm, "clear-nginx-logs", None) is None


def test_two_unrelated_skills_are_not_called_duplicates(tmp_path):
    other = {"name": "draft-quarterly-update", "description": "Write the investor letter",
             "category": "writing", "tags": ["writing"],
             "when_to_use": "Every quarter before the board meeting",
             "procedure": ["Pull the numbers", "Draft the letter"]}
    assert "duplicate-of" not in _codes(lint_skill(COMPLETE, [other]))


# ---------------------------------------------------------------------------
# Reachable without reading this file
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_person_can_ask_for_the_lint_before_anything_is_saved(tmp_path, monkeypatch):
    # The pre-save case, which is the row's whole point: the skill does not
    # exist yet and nothing is written by asking.
    import src.constants as constants
    monkeypatch.setattr(constants, "DATA_DIR", str(tmp_path), raising=False)

    out = await do_manage_skills(json.dumps({
        "action": "lint", "name": "half-written", "description": "",
        "procedure": [],
    }), owner=None)
    assert "error" not in out, out
    assert "3 problem(s)" in out["results"], out["results"]
    assert "No description" in out["results"]
    assert "No Procedure" in out["results"]

    sm = SkillsManager(str(tmp_path), library_root="")
    assert sm.load(owner=None) == [], "a lint wrote something"


@pytest.mark.asyncio
async def test_the_lint_reads_a_stored_skill_when_given_only_a_name(tmp_path, monkeypatch):
    import src.constants as constants
    monkeypatch.setattr(constants, "DATA_DIR", str(tmp_path), raising=False)
    sm = SkillsManager(str(tmp_path), library_root="")
    sm.add_skill(name="bare-skill", description="a bare skill", procedure=["one"],
                 source="user", owner=None)

    out = await do_manage_skills(json.dumps({"action": "lint", "name": "bare-skill"}),
                                 owner=None)
    assert "error" not in out, out
    assert "bare-skill" in out["results"]
    assert "verification" in out["results"].lower()

    missing = await do_manage_skills(json.dumps({"action": "lint", "name": "nope"}),
                                     owner=None)
    assert missing.get("exit_code") == 1
