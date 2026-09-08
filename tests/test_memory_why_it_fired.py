# SPDX-License-Identifier: AGPL-3.0-or-later
"""H11 — a person can ask why a memory would fire, without sending the message.

`POST /api/memory/debug` has been live, owner-scoped, and documented as *"Debug
which memories would be triggered for a query"*, with no caller anywhere in
`static/`. It could only ever answer the WHICH: `get_relevant_memories` computed
a score and a keyword boost and dropped both on its final line, returning a bare
list of memories.

The row's corrected scope is narrower than its headline and this follows it. The
retrieval trace for a message you HAVE sent already exists (`P13-10`, the
`.memory-used-pill`). What did not exist is asking about a query you have not
sent — and that is the one worth having, because retrieval decides what the agent
sees, and until you can interrogate it a wrong answer and a wrong memory look
identical from the outside. Building this is what surfaced `B40`.
"""
import ast
import pathlib
import re

import pytest

from src.memory import MemoryManager, classify_query, QUERY_KEYWORD_GROUPS

ROOT = pathlib.Path(__file__).resolve().parent.parent
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
MEMJS = (ROOT / "static" / "js" / "memory.js").read_text(encoding="utf-8")
ROUTES = (ROOT / "routes" / "memory" / "memory_routes.py").read_text(encoding="utf-8")


@pytest.fixture
def brain():
    return [{"text": t, "id": i} for i, t in enumerate([
        "Joseph Jeffrey works at Afrog Labs",
        "the build timeout is 900 seconds",
        "prefers dark mode in every editor",
    ])]


@pytest.fixture
def explain():
    manager = MemoryManager.__new__(MemoryManager)
    return manager.explain_relevant_memories


# ── the answer itself ──

def test_every_result_carries_a_score_and_a_reason(explain, brain):
    rows = explain("what is the build timeout", brain)
    assert rows, "precondition: something is retrieved"
    for row in rows:
        assert set(row) == {"memory", "score", "reason"}
        assert isinstance(row["score"], float)
        assert row["reason"].strip(), "a reason that is blank explains nothing"


def test_the_reason_names_the_words_that_matched(explain, brain):
    """"Relevant" is not an explanation. The words are."""
    row = explain("what is the build timeout", brain)[0]
    assert "shares" in row["reason"]
    assert "timeout" in row["reason"]


def test_a_verbatim_match_says_so(explain, brain):
    row = explain("Afrog Labs", brain)[0]
    assert "word for word" in row["reason"]


def test_the_identity_shortcut_is_gone_and_nothing_is_admitted_unscored(explain, brain):
    """`P13-14` removed the shortcut this test used to pin, and that removal is
    the decided outcome of `P13-11`(a) and (b) rather than a regression.

    The shortcut admitted any memory `_is_identity_memory` matched at a flat 0.9
    on any identity query, ahead of everything scored on words — and that
    predicate is any two consecutive capitalised words, so "deploys with Docker
    Compose on Sunday" qualified. `P13-11` asked whether to narrow it; the owner
    chose to replace the scorer instead, which makes the question moot.

    "who am I" is now the sharper illustration of the same area: every one of its
    words is a stopword, so a lexical engine has no query left at all and
    correctly returns nothing rather than inventing an identity match. That is
    the strongest single argument for `P13-16`, and it is why `B61` had to make
    a downed vector service visible."""
    assert explain("who am I", brain) == []
    for row in explain("what does Joseph Jeffrey do", brain):
        assert "without scoring" not in row["reason"]
        assert row["score"] != 0.9 or "word for word" in row["reason"]


def test_a_boost_says_which_boost_and_why(explain):
    # A corpus, not a single row. `P13-14`'s scorer weights a term by how rare
    # it is across the memories, and in a corpus of one every term appears in
    # every document — so nothing is distinctive, everything scores near the
    # floor, and the test would be measuring the fixture rather than the boost.
    # The previous version passed on Jaccard because Jaccard has no corpus.
    mems = [{"text": "prefers dark mode in every editor", "id": "p"},
            {"text": "the build timeout is 900 seconds", "id": "b"},
            {"text": "deploys on Sunday evenings", "id": "d"},
            {"text": "the office is at 12 Bridge Street", "id": "o"}]
    row = explain("does he prefer dark mode", mems)[0]
    assert row["memory"]["id"] == "p"
    # `P13-14`. The boost is now stated as a multiplier on the wording score
    # rather than as a percentage of a Jaccard similarity, because that is what
    # it is: the reason has to describe the arithmetic that actually ran.
    assert "preference question" in row["reason"]
    assert "×1.2" in row["reason"]


def test_a_verbatim_match_says_so_and_says_nothing_else(explain):
    """`P13-14` carried the exact-phrase rule across rather than losing it with
    the scorer it lived in (`Law 1`). It is the one case where wording is not a
    proxy for relevance but is the relevance, and no amount of IDF weighting
    reproduces it — a common word inside a verbatim phrase still carries a low
    IDF. Stated alone, because listing contributing terms beside it would
    misdescribe why the memory was chosen."""
    mems = [{"text": "the office is at 12 Bridge Street", "id": "o"}]
    row = explain("12 Bridge Street", mems)[0]
    assert row["reason"] == "the query appears in this memory word for word"
    assert row["score"] >= 0.8


def test_a_task_question_still_boosts_a_task_memory(explain):
    """Also carried across. The deleted scorer boosted task-shaped memories 30%
    on task-shaped questions, and dropping that while moving would have been a
    silent behaviour change wearing a refactor's clothes."""
    mems = [{"text": "remind me to renew the certificate", "id": "t"},
            {"text": "the renew script lives in scripts/", "id": "s"}]
    rows = {r["memory"]["id"]: r for r in explain("what do I need to remind myself about", mems)}
    assert "t" in rows, "the task memory was not returned at all"
    assert "task question" in rows["t"]["reason"]


def test_the_query_type_is_reportable_on_its_own():
    """`classify_query` still answers. `P13-14` is what it no longer *drives*."""
    assert classify_query("what is the build timeout") == "fact"
    assert classify_query("who am I") == "identity"
    assert classify_query("Afrog Labs") is None


def test_the_debug_route_reports_the_intent_that_actually_ranked():
    """`P13-14`. The route used to report `classify_query`, and after the scorer
    moved that would have been a classifier reporting on a ranking it no longer
    drives. A diagnostic that agrees with the truth by coincidence is worse than
    none, because it is believed.

    The two disagree in a knowable way: `classify_query` has a `fact` group
    matching "what", "when", "where" and "how" — most questions — and the
    ranking deliberately has no such group, because a boost that fires for
    everything is not a boost."""
    from src import memory_retrieval

    assert classify_query("what is the build timeout") == "fact"
    assert memory_retrieval.query_intent("what is the build timeout") is None
    assert memory_retrieval.query_intent("what is my name") == "identity"
    # Comments stripped before matching. The route explains *why* it stopped
    # using `classify_query`, so a naive substring test fails on the prose that
    # documents the very change it is checking — `Law 20`, and my own trap.
    code = "\n".join(ln for ln in ROUTES.splitlines() if not ln.lstrip().startswith("#"))
    assert "classify_query" not in code, "the route is back on the classifier that does not rank"
    assert "memory_retrieval.query_intent(query)" in code


def test_the_keyword_groups_are_inspectable():
    """They ARE the classifier, and `B40` is what happens when nobody can see
    them. Identity must stay first: that ordering is the documented intent."""
    names = [name for name, _ in QUERY_KEYWORD_GROUPS]
    assert names[0] == "identity"
    assert set(names) == {"identity", "contact", "preference", "task", "fact"}


# ── the contract the five existing callers rely on ──

def test_get_relevant_memories_still_returns_bare_memories(brain):
    manager = MemoryManager.__new__(MemoryManager)
    got = manager.get_relevant_memories("what is the build timeout", brain)
    assert all(isinstance(m, dict) and "text" in m and "score" not in m for m in got)


def test_the_two_functions_agree_on_selection_and_order(brain):
    manager = MemoryManager.__new__(MemoryManager)
    for query in ("what is the build timeout", "who am I", "Afrog Labs", "nothing here"):
        bare = manager.get_relevant_memories(query, brain)
        rich = [row["memory"] for row in manager.explain_relevant_memories(query, brain)]
        assert bare == rich, f"the two paths disagree for {query!r}"


# ── the route ──

def _route_body(name):
    """The source of one route handler, so an assertion cannot drift onto a
    neighbour. The first version of the test below matched substrings across
    the WHOLE FILE and passed while the keys had been added to
    `search_memories` instead — the route two functions down that happens to
    return `{"memories": ..., "total": ...}` as well. That shipped a NameError
    into `/api/memory/search` and a green test beside it."""
    tree = ast.parse(ROUTES)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(ROUTES, node)
    raise AssertionError(f"no route handler named {name}")


def _debug_route(monkeypatch, tmp_path, texts, user="bob"):
    """The real handler, called. Source-text assertions cannot tell whether the
    keys still hold the right values — a `[:0]` on the original list survived
    the substring version of this test."""
    from unittest.mock import MagicMock
    import routes.memory_routes as memory_routes
    manager = MemoryManager(str(tmp_path))
    entries = [manager.add_entry(t, owner=user) for t in texts]
    manager.save(entries)
    monkeypatch.setattr(memory_routes, "get_current_user", lambda request: user)
    router = memory_routes.setup_memory_routes(manager, MagicMock())
    handler = next(r.endpoint for r in router.routes
                   if r.path == "/api/memory/debug" and "POST" in r.methods)
    return handler, entries


def test_the_debug_route_adds_without_changing(monkeypatch, tmp_path):
    """`relevant_memories` keeps its exact shape and contents — anything
    already reading this endpoint must be unaffected — and the new keys sit
    beside it."""
    handler, entries = _debug_route(
        monkeypatch, tmp_path,
        # Two memories must come back, not one: a mutation truncating
        # `memories` to `[:1]` survived a fixture where only one matched.
        ["the build timeout is 900 seconds", "the build cache is 2 GB",
         "prefers dark mode in every editor"])
    result = handler(request=None, query="what is the build timeout")
    assert len(result["memories"]) >= 2, "precondition: more than one match"

    assert result["relevant_memories"], "the original key must still carry results"
    assert result["relevant_count"] == len(result["relevant_memories"])
    assert all(set(row) == {"text", "category"} for row in result["relevant_memories"]), \
        "the original rows must keep their exact shape"

    assert [m["text"] for m in result["memories"]] == \
        [row["text"] for row in result["relevant_memories"]], \
        "the two lists must describe the same memories in the same order"
    # `P13-14`. `None` is the honest answer and the old `"fact"` was not: the
    # ranking applies no intent boost to "what is the build timeout", and the
    # classifier that answered `"fact"` has a group matching "what", "when",
    # "where" and "how" — which is most questions. A boost that fires for
    # everything is not a boost, and a diagnostic reporting one that did not
    # fire is worse than silence because it is believed.
    assert result["query_type"] is None
    assert result["query_type"] != classify_query("what is the build timeout"), \
        "the route must report the intent that ranked, not the classifier that did not"
    assert len(result["explanations"]) == len(result["memories"])
    ids = {m["id"] for m in result["memories"]}
    assert all(row["id"] in ids for row in result["explanations"]), \
        "every explanation must line up with a returned memory"



def test_the_search_route_was_not_touched():
    """It returns `{"memories", "total", "query"}` and is two functions below
    `/debug`, which is exactly why the first version of the test above matched
    it by accident."""
    body = _route_body("search_memories")
    assert "explain_relevant_memories" not in body
    assert "explanations" not in body
    assert 'return {"memories": relevant, "total": len(relevant), "query": query}' in body


# ── the door ──

def test_the_search_box_has_a_would_fire_mode():
    assert 'id="memory-search-mode"' in INDEX
    assert 'value="fire"' in INDEX
    assert 'id="memory-fire-note"' in INDEX


def test_the_mode_is_wired_at_init():
    """`initRag` is what happens to a function nobody calls."""
    assert "initMemorySearchMode();" in MEMJS
    assert re.search(r"function initMemorySearchMode\(", MEMJS)


def test_it_calls_the_route_that_had_no_caller():
    assert "'/api/memory/debug'" in MEMJS


def test_the_server_order_is_not_re_sorted_locally():
    """The order IS the answer. Re-sorting by date or pinned-ness — which is
    what the normal path does two lines later — would throw away the only thing
    this mode is for."""
    fn = MEMJS.split("function getFilteredMemories()", 1)[1].split("\n}", 1)[0]
    fire = fn.split("if (_fireResult)", 1)[1].split("}", 1)[0]
    assert "_fireResult.order.map" in fire
    assert "sort(" not in fire


def test_a_stale_response_cannot_overwrite_a_newer_one():
    """Typing produces overlapping requests. Without a sequence guard the list
    flickers back to an earlier answer, which in a diagnostic is worse than no
    answer at all."""
    fn = MEMJS.split("async function _runFireQuery", 1)[1].split("\n}", 1)[0]
    assert "_fireSeq" in fn
    assert fn.count("if (seq !== _fireSeq) return;") >= 2


def test_the_reason_is_rendered_with_textcontent():
    """Server-supplied prose on a row built from user-supplied memory text."""
    block = MEMJS.split("const fired = _fireResult", 1)[1].split("meta.appendChild(reasonSpan);", 1)[0]
    assert not re.search(r"\.innerHTML\b", block)
    assert block.count("textContent") >= 2
