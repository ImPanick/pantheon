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


def test_the_identity_shortcut_admits_that_it_skipped_scoring(explain, brain):
    """This is the reason most worth surfacing: on an identity query these are
    admitted at 0.9 WITHOUT being scored, ahead of anything matched on words.
    A person looking at the list cannot tell that from the ranking alone, and
    it is precisely the behaviour `B40` was hiding."""
    row = explain("who am I", brain)[0]
    assert "without scoring" in row["reason"]
    assert row["score"] == 0.9


def test_a_boost_says_which_boost_and_why(explain):
    mems = [{"text": "prefers dark mode in every editor", "id": "p"}]
    row = explain("does he prefer dark mode", mems)[0]
    assert "30% boost" in row["reason"]
    assert "preference question" in row["reason"]


def test_the_query_type_is_reportable_on_its_own():
    assert classify_query("what is the build timeout") == "fact"
    assert classify_query("who am I") == "identity"
    assert classify_query("Afrog Labs") is None


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
    assert result["query_type"] == "fact"
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
