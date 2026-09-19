# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P8-20` / `B792` — the retriever could not clear its own threshold.

`get_relevant_skills` scored with `_jaccard`, whose denominator is the union
of the query's tokens and the whole skill's, so a skill got harder to find the
more it said. On the 286 skills this product ships, every one of the 30
hand-labelled natural queries below returned **nothing** at the agent loop's
threshold of 0.25 (`src/agent_loop.py:3153`, again at `:5017`).

These tests drive `SkillsManager.get_relevant_skills` and never read the
source of the thing they are testing (`Law 20`). The library case is a real
`SkillsManager` over the real vendored `library/ecc/skills`.

Two properties are pinned, and the second is the one that makes the change
safe:

  * the labelled queries now retrieve their skill, and
  * **no (query, skill) pair scores lower than it did before** — `Law 1` as an
    executable invariant, checked against `_jaccard` itself over the whole
    library rather than against a remembered number.
"""
import sys
import tempfile
from unittest.mock import MagicMock

import pytest

for _mod in ("sqlalchemy", "sqlalchemy.orm", "sqlalchemy.ext",
             "sqlalchemy.ext.declarative"):
    if _mod not in sys.modules:
        try:
            __import__(_mod)
        except ImportError:
            sys.modules[_mod] = MagicMock()

from services.memory.skills import (  # noqa: E402
    SkillsManager, _aim, _coverage, _jaccard, _relevance, _subtokens,
)

# The threshold the agent loop actually passes. Hard-coded here on purpose:
# if someone lowers it to paper over a retrieval problem, these tests should
# keep measuring the number the product shipped with.
LOOP_THRESHOLD = 0.25

# 30 short natural requests and the bundled skill each one is plainly about.
LABELLED = [
    ("make my website meet WCAG accessibility standards", "accessibility"),
    ("write pytest tests for my python module", "python-testing"),
    ("patterns for writing good python code", "python-patterns"),
    ("set up a postgres database schema", "postgres-patterns"),
    ("build a fastapi endpoint", "fastapi-patterns"),
    ("write a dockerfile and compose file", "docker-patterns"),
    ("deploy to kubernetes", "kubernetes-patterns"),
    ("review this code for security problems", "security-review"),
    ("do a git workflow with branches and commits", "git-workflow"),
    ("write react components", "react-patterns"),
    ("test my react components", "react-testing"),
    ("improve search engine optimization for my site", "seo"),
    ("write an article", "article-writing"),
    ("do market research on competitors", "market-research"),
    ("design an api contract", "api-design"),
    ("rust error handling patterns", "rust-patterns"),
    ("write rust tests", "rust-testing"),
    ("golang testing", "golang-testing"),
    ("redis caching patterns", "redis-patterns"),
    ("database migrations", "database-migrations"),
    ("write an architecture decision record", "architecture-decision-records"),
    ("handle errors properly", "error-handling"),
    ("swiftui layout patterns", "swiftui-patterns"),
    ("vue composition api patterns", "vue-patterns"),
    ("end to end browser testing", "e2e-testing"),
    ("track my cloud costs", "cost-tracking"),
    ("build an mcp server", "mcp-server-patterns"),
    ("django security hardening", "django-security"),
    ("test driven development workflow", "tdd-workflow"),
    ("scan my repo for secrets", "security-scan"),
]


@pytest.fixture(scope="module")
def library():
    """The real 286-file library, published so the confidence gate is not
    what this file is measuring.

    Bundled skills parse as `status: draft` at the parser's default
    confidence 0.8 and the shipped injection floor is 0.85, so on a stock
    install they are dropped *before* scoring — that is `B581`/`B590`, a
    separate defect from the one under test, and flipping status here isolates
    the scorer instead of hiding behind it.
    """
    with tempfile.TemporaryDirectory() as d:
        sm = SkillsManager(d)
        skills = sm.load_all()
        for s in skills:
            s["status"] = "published"
        assert len(skills) >= 280, f"library did not load: {len(skills)}"
        return sm, skills


def _names(sm, skills, query, threshold=LOOP_THRESHOLD, k=5):
    return [s["name"] for s in sm.get_relevant_skills(
        query, skills=skills, threshold=threshold, max_items=k,
        min_confidence=0.0)]


def _indexed(sk):
    """The text `get_relevant_skills` scores against, rebuilt field for field."""
    from services.memory.skills import _tokenize
    return _tokenize(" ".join([
        sk.get("name", ""), sk.get("description", ""), sk.get("when_to_use", ""),
        " ".join(sk.get("tags", []) or []),
        " ".join(sk.get("procedure", []) or []),
    ]))


# ---------------------------------------------------------------------------
# The row: a person asks in their own words and is handed the skill.
# ---------------------------------------------------------------------------

def test_the_labelled_queries_are_no_longer_all_empty(library):
    """Before this change, 29 of these 30 returned `[]` and the 30th returned
    the wrong skill. Nothing may return `[]` now."""
    sm, skills = library
    empty = [q for q, _ in LABELLED if not _names(sm, skills, q)]
    assert empty == [], f"{len(empty)} queries still retrieve nothing: {empty}"


def test_recall_at_five_over_the_labelled_set(library):
    """26 of 30 at the time of writing, from 0 of 30. The floor is set below
    the measurement so an unrelated library update does not fail the suite,
    and well above the 0 this replaced."""
    sm, skills = library
    hits = [want for q, want in LABELLED if want in _names(sm, skills, q)]
    assert len(hits) >= 24, (
        f"recall@5 fell to {len(hits)}/30; misses="
        f"{[w for _, w in LABELLED if w not in hits]}")


def test_precision_at_one_over_the_labelled_set(library):
    """The right skill is *first*, not merely present — 20 of 30 measured,
    from 0."""
    sm, skills = library
    top = [want for q, want in LABELLED if _names(sm, skills, q)[:1] == [want]]
    assert len(top) >= 17, f"precision@1 fell to {len(top)}/30"


def test_a_hyphenated_skill_name_matches_its_own_words(library):
    """`_tokenize` splits on whitespace, so `golang-testing` was one token and
    the query "golang testing" matched its name on neither word. 275 of the
    286 bundled names are hyphenated."""
    sm, skills = library
    assert "golang-testing" in _names(sm, skills, "golang testing")


# ---------------------------------------------------------------------------
# `Law 1` as an invariant: the new score is never smaller than the old one.
# ---------------------------------------------------------------------------

def test_no_pair_in_the_library_scores_lower_than_before(library):
    """`_relevance` must dominate `_jaccard` for every (query, skill) pair.

    This is the whole safety argument for the change, so it is measured over
    the real corpus — 30 labelled queries plus 6 degenerate ones against all
    286 skills — instead of asserted in prose.
    """
    _sm, skills = library
    queries = [q for q, _ in LABELLED] + [
        "what do I do now", "the and or of to", "a", "", "zzz qqq", "how"]
    index = [(s["name"], _indexed(s)) for s in skills]
    from services.memory.skills import _tokenize
    lowered, pairs, raised = [], 0, 0
    for q in queries:
        qt = _tokenize(q)
        aim = _aim(qt)
        for name, toks in index:
            pairs += 1
            before, after = _jaccard(qt, toks), _relevance(qt, aim, toks)
            if after < before - 1e-12:
                lowered.append((q, name, before, after))
            elif after > before + 1e-12:
                raised += 1
    assert pairs > 10000, f"corpus too small to mean anything: {pairs}"
    assert lowered == [], f"{len(lowered)} pairs scored lower, e.g. {lowered[:3]}"
    assert raised > 500, f"only {raised} pairs improved — the fix is not firing"


def test_a_skill_that_matched_before_still_matches(library):
    """The concrete half of the invariant, driven through the manager: a long
    query that cleared 0.25 on the union measure still clears it."""
    sm = SkillsManager(tempfile.mkdtemp())
    tiny = [{"name": "greet", "description": "say hello", "when_to_use": "",
             "tags": [], "procedure": [], "status": "published"}]
    # {say, hello} vs {greet, say, hello} -> 2/3 on the old measure.
    assert _names(sm, tiny, "say hello") == ["greet"]


# ---------------------------------------------------------------------------
# The pieces, driven directly.
# ---------------------------------------------------------------------------

def test_coverage_ignores_how_much_the_skill_says():
    """The defect in one assertion: the same query, the same match, against a
    short skill and a ten-times-longer one."""
    aim = {"deploy", "kubernetes"}
    short = {"deploy", "kubernetes"}
    long_ = short | {f"word{i}" for i in range(100)}
    assert _coverage(aim, short) == 1.0
    assert _coverage(aim, long_) == 1.0
    # ... whereas the measure it replaces collapses.
    assert _jaccard(aim, short) == 1.0
    assert _jaccard(aim, long_) < 0.02


def test_a_query_of_nothing_but_stopwords_aims_at_nothing():
    """Otherwise "what do I do now" would score every skill containing "do"."""
    from services.memory.skills import _tokenize
    assert _aim(_tokenize("what do I do now")) == set()
    assert _coverage(set(), {"anything"}) == 0.0


def test_a_stopword_only_query_retrieves_nothing_new(library):
    """And the manager-level consequence of that."""
    sm, skills = library
    assert _names(sm, skills, "what do I do now") == []


def test_a_hyphenated_query_reaches_a_skill_that_spells_it_out(library):
    """The mirror of the name case, and the reason `_aim` expands too.

    A person types the compound — "e2e-testing" — and the skill says the same
    thing with a space in it. Expanding only the skill side leaves the query
    holding one token that appears nowhere, and the match is 0.
    """
    sm = SkillsManager(tempfile.mkdtemp())
    skills = [{"name": "browser-qa", "description": "e2e testing in a browser",
               "when_to_use": "", "tags": [], "procedure": [],
               "status": "published"}]
    assert _names(sm, skills, "e2e-testing") == ["browser-qa"]


def test_a_short_part_of_a_hyphenated_name_still_counts(library):
    """`api`, `ui`, `db`, `qa`, `io`, `seo`, `mcp` — the parts that carry the
    most meaning in this library are the shortest ones, so the length floor on
    a sub-token has to be `> 1`, the same floor `_tokenize` itself applies, and
    not something rounder."""
    sm = SkillsManager(tempfile.mkdtemp())
    skills = [{"name": "api-design", "description": "contract first interfaces",
               "when_to_use": "", "tags": [], "procedure": [],
               "status": "published"}]
    assert _names(sm, skills, "api") == ["api-design"]


def test_subtokens_keeps_the_whole_token(library):
    """The tag boost tests `tag_tokens <= query_tokens`, so a tag that stopped
    containing itself would stop boosting."""
    assert _subtokens({"golang-testing"}) == {"golang-testing", "golang", "testing"}
    assert _subtokens({"a-b"}) == {"a-b"}          # one-character parts dropped
    assert _subtokens({"plain"}) == {"plain"}


def test_the_tag_boost_still_fires(library):
    """`tests/test_skills_tag_token_match.py` owns the substring case; this
    pins that the expansion did not break the whole-token one."""
    sm = SkillsManager(tempfile.mkdtemp())
    skills = [{"name": "git-helper", "description": "version control stuff",
               "when_to_use": "", "tags": ["git"], "procedure": [],
               "status": "published"}]
    assert "git-helper" in _names(sm, skills, "help me with git rebase")
