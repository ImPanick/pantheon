# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P8-15` — what a new skill overlaps, said to the person typing it.

**Three premises re-measured 2026-09-19, and two of them had moved.**

1. The row says similarity "is already computed client-side for a badge and
   server-side at audit — neither runs when you type". That was true when the
   row was written and is **stale**: `P8-12` landed `POST /api/skills/lint`
   and a panel that runs it on blur of every field. What is still missing is
   not *a* check, it is a check that says anything useful — the shipped one
   stops at the first sibling it meets in `load()` order and calls it a
   duplicate.

2. `B731` says the client's `0.38` and the server's `0.82` "answer the same
   question and differ by more than a factor of two". They are computed on
   **two different token sets**, so they were never on one scale:
   `skills._tokenize` splits on whitespace, keeps two-character words and
   keeps stopwords, while `skill_lint.skill_tokens` splits on non-alphanumerics,
   drops stopwords and strips a trailing `-<n>`. Measured over the 36,654
   bundled pairs that score above zero on both, the first runs **1.65×** the
   second (median; mean 1.75). On the scales actually in use the two thresholds
   were a factor of ~1.3 apart, not 2.2. Unifying the function is what makes
   `B731`'s own arithmetic true.

3. And the word is wrong. Over all **40,755** pairs of the bundled library
   (286 skills, 2026-09-19) **24** pairs reach 0.38 and **zero** reach 0.82 on
   either scale — the corpus maximum is 0.700. All 24 are the same skill shape
   for a different technology: `python-patterns | golang-patterns`,
   `django-security | laravel-security`, `csharp-testing | fsharp-testing`.
   Nothing that anyone would call a duplicate. So the finding names the score
   and the neighbour and lets the author judge, and only a shared **base name**
   — which is identity, because it is the suffix `add_skill` itself appends —
   is stated as a problem.

The tests below drive the real path: the manager's own writer, the lint the
`/lint` route calls, and `add_skill` through the tool handler the Workshop's
form and the agent both reach.
"""

import json

import pytest

from services.memory.skill_lint import (
    ADVISORY,
    DUPLICATE_REFUSAL,
    DUPLICATE_SIMILARITY,
    PROBLEM,
    describe_overlaps,
    lint_skill,
    skill_overlaps,
    skill_similarity,
)
from services.memory.skills import SkillsManager
from src.tools.system import do_manage_skills


def _codes(result):
    return {f["code"] for f in result["findings"]}


def _finding(result, code):
    return next(f for f in result["findings"] if f["code"] == code)


NGINX = {
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


def _near(name, extra=""):
    return {
        "name": name,
        "description": "Clear nginx access logs on a full disk " + extra,
        "category": "ops",
        "tags": ["nginx", "disk"],
        "when_to_use": "When /var/log has filled up",
        "procedure": ["Run logrotate for nginx", "Check nginx handles with lsof"],
    }


def _far(name):
    return {"name": name, "description": "Write the investor letter",
            "category": "writing", "tags": ["writing"],
            "when_to_use": "Every quarter before the board meeting",
            "procedure": ["Pull the numbers", "Draft the letter"]}


# ---------------------------------------------------------------------------
# The finding names the closest neighbour, not the first one in the list
# ---------------------------------------------------------------------------

def test_the_overlap_named_is_the_strongest_one_not_the_first_one_seen():
    """The shipped lint `break`s on its first hit, so which sibling it names is
    an accident of `load()` order — and `load()` order is directory-walk order.
    A person shown the wrong neighbour edits the wrong skill."""
    weak = _near("clear-nginx-logs", extra="on a box that is out of inodes as well")
    strong = _near("prune-nginx-logs")
    strong["description"] = NGINX["description"]
    strong["when_to_use"] = NGINX["when_to_use"]

    # `weak` first: whatever the lint names FIRST must be the closer of the two.
    result = lint_skill(NGINX, [weak, strong])
    assert "duplicate-of" in _codes(result)
    finding = _finding(result, "duplicate-of")
    assert finding["message"].index("prune-nginx-logs") < finding["message"].index(
        "clear-nginx-logs"), finding["message"]
    assert finding["fix"].startswith("If the two answer the same request, edit "
                                     "`prune-nginx-logs`"), finding["fix"]
    assert skill_similarity(NGINX, strong) > skill_similarity(NGINX, weak)


def test_the_finding_states_the_score_so_the_author_can_judge_it():
    """`24 of 24` overlapping pairs in the bundled library are not duplicates.
    A verdict the author cannot check is a verdict they have to trust; a number
    is one they can argue with."""
    result = lint_skill(NGINX, [_near("clear-nginx-logs")])
    message = _finding(result, "duplicate-of")["message"]
    score = skill_similarity(NGINX, _near("clear-nginx-logs"))
    assert f"{int(round(score * 100))}%" in message, message


def test_topic_overlap_is_an_advisory_and_a_shared_base_name_is_a_problem():
    """Measured over 40,755 bundled pairs: 24 reach 0.38 and every one of them
    is a different technology's version of the same procedure. A shared base
    name is the opposite — it is the `-2` suffix `add_skill` appends when a name
    is taken, so it is identity rather than topic."""
    topic = lint_skill(NGINX, [_near("clear-nginx-logs")])
    assert _finding(topic, "duplicate-of")["severity"] == ADVISORY

    same_base = lint_skill(NGINX, [_far("rotate-nginx-logs-2")])
    assert _finding(same_base, "same-base-name")["severity"] == PROBLEM


def test_every_neighbour_above_the_floor_is_listed_not_just_one():
    result = lint_skill(NGINX, [_near("clear-nginx-logs"), _near("prune-nginx-logs")])
    message = _finding(result, "duplicate-of")["message"]
    assert "clear-nginx-logs" in message and "prune-nginx-logs" in message, message


def test_an_unrelated_sibling_is_not_reported_at_all():
    assert "duplicate-of" not in _codes(lint_skill(NGINX, [_far("draft-quarterly-update")]))


# ---------------------------------------------------------------------------
# One comparison — `Law 14`, and `B731`'s actual repair
# ---------------------------------------------------------------------------

def test_creation_time_dedup_and_the_lint_use_one_similarity_function(tmp_path):
    """`B731`: the two numbers were on two token sets, so they could not be
    compared at all. They are one scale now — `skill_lint.skill_similarity` —
    and the two thresholds are two answers to two different questions on it:
    0.38 is *worth a look*, 0.82 is *the same skill*."""
    sm = SkillsManager(str(tmp_path), library_root="")
    sm.add_skill(source="learned", owner=None, status="published", **NGINX)

    # A near-identical LLM-authored second copy is refused, as it always was…
    twin = dict(NGINX)
    twin["name"] = "rotate-the-nginx-logs"
    again = sm.add_skill(source="learned", owner=None, **twin)
    assert again.get("_deduped") is True
    assert again.get("_duplicate_of") == "rotate-nginx-logs"
    # …and the score it was refused at is reported on the same scale the author
    # was shown, rather than on a second one nobody can see.
    assert again.get("_duplicate_score") >= DUPLICATE_REFUSAL

    # A merely-similar one is not refused, on either scale.
    other = sm.add_skill(source="learned", owner=None, **_near("clear-nginx-logs"))
    assert not other.get("_deduped")


def test_the_two_thresholds_are_ordered_and_on_the_same_scale():
    assert 0 < DUPLICATE_SIMILARITY < DUPLICATE_REFUSAL <= 1.0


def test_describe_overlaps_prints_the_number_beside_the_name():
    """`describe_overlaps` is what the tool channel and the same-base finding
    both render through, so its percentage needs an assertion of its own —
    without one, a mutation that prints every score as 0% survives."""
    assert describe_overlaps([{"name": "a", "score": 0.71, "same_base": False}]) == "`a` (71%)"
    assert describe_overlaps([{"name": "b", "score": 0.4, "same_base": True}]) == "`b` (same base name)"
    assert describe_overlaps([{"name": "a", "score": 0.7, "same_base": False},
                              {"name": "b", "score": 0.44, "same_base": False}]) == "`a` (70%), `b` (44%)"
    assert describe_overlaps(None) == "" and describe_overlaps([]) == ""


def test_skill_overlaps_ranks_and_honours_its_floor():
    rows = skill_overlaps(NGINX, [_far("a"), _near("clear-nginx-logs"),
                                  _near("prune-nginx-logs")])
    assert [r["name"] for r in rows][0] in ("clear-nginx-logs", "prune-nginx-logs")
    assert all(r["score"] >= DUPLICATE_SIMILARITY for r in rows)
    assert rows == sorted(rows, key=lambda r: r["score"], reverse=True)
    assert skill_overlaps(NGINX, [_near("clear-nginx-logs")], floor=0.99) == []


# ---------------------------------------------------------------------------
# The exemption the row points at: `source="user"` skips dedup, silently
# ---------------------------------------------------------------------------

def test_a_hand_written_near_duplicate_is_still_created_and_no_longer_silent(tmp_path):
    """`add_skill` exempts `source="user"` from dedup on purpose — a person
    asked for it, and `P9-12`'s undo path depends on that exemption to restore
    a deleted member of a duplicate pair. The defect is not the exemption, it is
    that nothing said a word: the Workshop form posts `source: "user"`
    (`SkillAddRequest.source`), so **every** skill added by hand took the exempt
    branch and the author was never told what they had just copied."""
    sm = SkillsManager(str(tmp_path), library_root="")
    sm.add_skill(source="user", owner=None, status="published", **NGINX)

    twin = dict(NGINX)
    twin["name"] = "rotate-the-nginx-logs"
    made = sm.add_skill(source="user", owner=None, **twin)

    assert not made.get("_deduped"), "a person's own skill must still be created"
    assert made["name"] == "rotate-the-nginx-logs"
    overlaps = made.get("_overlaps") or []
    assert [o["name"] for o in overlaps][:1] == ["rotate-nginx-logs"]
    assert overlaps[0]["score"] >= DUPLICATE_REFUSAL


@pytest.mark.asyncio
async def test_the_tool_channel_says_what_the_new_skill_overlaps(tmp_path, monkeypatch):
    """`Law 20` — driven through the handler the agent and the form both reach,
    not through the function underneath it."""
    monkeypatch.setattr("src.constants.DATA_DIR", str(tmp_path))
    sm = SkillsManager(str(tmp_path), library_root="")
    sm.add_skill(source="user", owner=None, status="published", **NGINX)
    monkeypatch.setattr("services.memory.skills.SkillsManager",
                        lambda *a, **k: SkillsManager(str(tmp_path), library_root=""))

    payload = dict(NGINX)
    payload.update({"action": "add", "name": "rotate-the-nginx-logs",
                    "source": "user", "status": "draft"})
    result = await do_manage_skills(json.dumps(payload), owner=None)
    text = result.get("results", "")
    assert "rotate-the-nginx-logs" in text
    assert "rotate-nginx-logs" in text
    assert "overlap" in text.lower(), text
    # …and by how much, in the words `describe_overlaps` renders. A neighbour
    # named without a number is a warning nobody can size.
    assert "%)" in text and "(0%)" not in text, text


@pytest.mark.asyncio
async def test_a_refused_duplicate_says_how_close_it_was(tmp_path, monkeypatch):
    """The refusal used to name the survivor and nothing else, so an agent told
    "a near-identical skill already exists" had no way to judge whether the
    store had just thrown away a genuinely different procedure."""
    monkeypatch.setattr("src.constants.DATA_DIR", str(tmp_path))
    sm = SkillsManager(str(tmp_path), library_root="")
    sm.add_skill(source="user", owner=None, status="published", **NGINX)
    monkeypatch.setattr("services.memory.skills.SkillsManager",
                        lambda *a, **k: SkillsManager(str(tmp_path), library_root=""))

    payload = dict(NGINX)
    payload.update({"action": "add", "name": "rotate-the-nginx-logs",
                    "source": "learned", "status": "draft"})
    text = (await do_manage_skills(json.dumps(payload), owner=None)).get("results", "")
    assert "near-identical" in text, text
    assert "% token overlap" in text and "(0% token overlap)" not in text, text


def test_nothing_reaches_disk_because_a_draft_was_linted(tmp_path):
    sm = SkillsManager(str(tmp_path), library_root="")
    sm.add_skill(source="user", owner=None, status="published", **NGINX)
    before = sorted(p.name for p in (tmp_path / "skills").rglob("*"))
    lint_skill(dict(NGINX, name="rotate-nginx-logs-2"), sm.load(owner=None))
    assert sorted(p.name for p in (tmp_path / "skills").rglob("*")) == before


def test_a_numbered_clone_is_told_both_things_not_one_of_them():
    """`rotate-nginx-logs-2` beside `rotate-nginx-logs` is the same name *and*
    the same words. The two findings answer different questions, so the lists
    they are drawn from are deliberately not a partition."""
    clone = dict(NGINX, name="rotate-nginx-logs-2")
    codes = _codes(lint_skill(clone, [dict(NGINX)]))
    assert {"same-base-name", "duplicate-of"} <= codes, codes


def test_nothing_in_the_shipped_library_reaches_the_refusal_threshold():
    """The measurement that makes the unification safe, pinned so it stays true.

    `add_skill` moved from `_tokenize`/`_jaccard` to `skill_similarity` — a
    different token set at the same numeral. That is only a no-op because the
    bundled library's maximum pairwise similarity is **0.700**, well under the
    0.82 refusal, so no pair crossed it before and none crosses it now. If a
    future library ships a pair that does, this fails and the next person gets
    to decide deliberately rather than discover it in a bug report.
    """
    import itertools
    import tempfile

    sm = SkillsManager(tempfile.mkdtemp())
    library = sm.load_all()
    if len(library) < 50:            # a checkout with the library removed
        pytest.skip("bundled library not present")
    worst = max(skill_similarity(a, b)
                for a, b in itertools.combinations(library, 2))
    assert worst < DUPLICATE_REFUSAL, f"corpus maximum is now {worst:.3f}"
    assert worst == pytest.approx(0.700, abs=0.02), (
        f"the bundled corpus maximum moved to {worst:.3f} — re-measure the "
        "24-pair precision figure on the P8-15 row before trusting it"
    )
