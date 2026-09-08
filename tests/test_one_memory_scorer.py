# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P13-14` — one memory scorer, and the properties that keep it one.

This tree carried two. `ChatProcessor._hybrid_retrieve` — BM25 with corpus IDF,
an optional vector score, recency as a tiebreaker — fed the chat preface and
nothing else. `MemoryManager.get_relevant_memories` — Jaccard token overlap plus
four hand-written keyword lists — fed the Brain panel's search and debug
endpoints, the agent's own MCP `memory_search`, the memory provider's fallback,
and `ai_interaction`. **The better one served the fewer surfaces, and the agent
got the worse one.**

Measured before anything was removed, on `.pantheon/fixtures/retrieval_probe.json`
with no vector service: Jaccard `recall@5 0.40, MRR 0.319`; BM25 `0.63, 0.633`.

This is `Law 13`/`Law 14`, not a `Law 1` subtraction — the capability survives
and improves, and what goes is a duplicate implementation. The obligation that
comes with that is the one `P3-10` accepted when it deleted
`calendar/reminders.js`: the safety case must be executable. These tests are it.
"""

import ast
import re
from pathlib import Path

import pytest

from src import memory_retrieval
from src.chat_processor import ChatProcessor
from src.memory import MemoryManager

_REPO = Path(__file__).resolve().parents[1]


def _corpus():
    return [
        {"id": "dark", "text": "User prefers dark mode in every editor.",
         "category": "preference", "timestamp": 1735689600},
        {"id": "coffee", "text": "User likes dark roast coffee beans.",
         "category": "preference", "timestamp": 1735689600},
        {"id": "office", "text": "The office is at 12 Bridge Street, Leeds.",
         "category": "contact", "timestamp": 1735689600},
        {"id": "deploy", "text": "Deploys with Docker Compose on Sunday evenings.",
         "category": "fact", "timestamp": 1735689600},
        {"id": "cert", "text": "Remind me to renew the certificate in March.",
         "category": "fact", "timestamp": 1735689600},
    ]


def _manager():
    return MemoryManager.__new__(MemoryManager)


def _processor(vector=None):
    proc = ChatProcessor.__new__(ChatProcessor)
    proc.memory_vector = vector
    return proc


# ── there is one scorer ───────────────────────────────────────────────────────


def test_both_entry_points_return_the_same_memories_in_the_same_order():
    # The property the row exists to establish. The Brain, the agent and the
    # provider come in through `MemoryManager`; the chat preface comes in
    # through `_hybrid_retrieve`. The day these disagree, a second scorer has
    # grown back.
    rows = _corpus()
    for query in ["dark mode", "where is the office", "what do I need to renew",
                  "coffee", "Docker Compose"]:
        via_manager = [m["id"] for m in _manager().get_relevant_memories(query, rows, max_items=5)]
        via_preface = [m["id"] for m in _processor()._hybrid_retrieve(query, rows, k=5)]
        assert via_manager == via_preface, f"the two paths disagree on {query!r}"


def test_no_second_scorer_survives_in_the_module_that_used_to_hold_one():
    # `src/memory.py` held the Jaccard implementation. Its public functions
    # remain (`Law 1`), but nothing in it may score a query against a memory
    # again — that is what "one scorer" means, and a returning copy would look
    # exactly like a helpful local optimisation.
    source = (_REPO / "src" / "memory.py").read_text(encoding="utf-8")
    code = "\n".join(ln for ln in source.splitlines() if not ln.lstrip().startswith("#"))
    tree = ast.parse(code)
    body = {node.name: ast.get_source_segment(code, node)
            for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    for name in ("get_relevant_memories", "explain_relevant_memories"):
        assert name in body, f"{name} disappeared; five callers depend on it"
        assert "memory_retrieval" in body[name] or "explain_relevant_memories" in body[name], \
            f"{name} scores on its own again"
        for smell in ("intersection", "base_similarity", "final_score *="):
            assert smell not in body[name], f"{name} has grown its own scoring again: {smell}"


def test_the_tokenizer_has_one_definition():
    # `chat_processor` re-exports rather than reimplements. Two tokenizers that
    # drift is the same defect as two scorers, one layer down, and it would show
    # up as retrieval that behaves differently depending on which door you came
    # through.
    assert ChatProcessor.__module__
    from src import chat_processor
    assert chat_processor._content_tokens is memory_retrieval.content_tokens
    assert chat_processor._STOPWORDS is memory_retrieval.STOPWORDS


# ── what was carried across rather than lost with the old scorer ──────────────


def test_a_verbatim_match_wins_however_common_its_words_are():
    # `Law 1`. The deleted scorer had an exact-phrase rule and no amount of IDF
    # weighting reproduces it: "12 Bridge Street" is three tokens of which two
    # are unremarkable, so BM25 alone ranks it below memories that merely share
    # a rare word.
    rows = _corpus()
    ranked = _manager().explain_relevant_memories("12 Bridge Street", rows, max_items=5)
    assert ranked, "a verbatim phrase returned nothing"
    assert ranked[0]["memory"]["id"] == "office"
    assert ranked[0]["reason"] == "the query appears in this memory word for word"
    assert ranked[0]["score"] >= 0.8


def test_a_verbatim_match_is_not_gated_out_before_it_is_considered():
    # The ordering bug this guards. The relevance gates run before the verbatim
    # check, so a phrase that scores nothing on BM25 would be dropped before
    # anything noticed it was a verbatim match.
    rows = [{"id": "x", "text": "the thing is a thing", "timestamp": 1735689600},
            {"id": "y", "text": "something else entirely", "timestamp": 1735689600}]
    ranked = _manager().get_relevant_memories("the thing is a thing", rows, max_items=5)
    assert [m["id"] for m in ranked] == ["x"]


def test_a_verbatim_match_survives_a_query_that_is_all_stopwords():
    # The gap this test found. `content_tokens` strips the query to nothing, and
    # the empty-query bail-out returned before anything looked for a verbatim
    # match — so the exact-phrase rule was unconditional everywhere except the
    # one path where it was the *only* thing that could have matched.
    rows = [{"id": "q", "text": "who am i, really", "timestamp": 1735689600},
            {"id": "z", "text": "unrelated", "timestamp": 1735689600}]
    assert memory_retrieval.content_tokens("who am i") == []
    assert [m["id"] for m in _manager().get_relevant_memories("who am i", rows, max_items=5)] == ["q"]


@pytest.mark.parametrize("query, expect, intent", [
    ("what is my name", "identity", "identity"),
    ("what is the office address", "contact", "contact"),
    ("what do I prefer", "preference", "preference"),
    ("what do I need to remind myself about", "task", "task"),
])
def test_every_intent_boost_can_actually_fire(query, expect, intent):
    # `P13-14`. The surviving scorer tested `@` for contact and *nothing* for
    # preference or task, so those boosts fired only when extraction had filed
    # the memory under exactly the right category — and extraction files almost
    # everything as `fact`. A boost gated on a category almost nothing carries
    # is a boost that fires for nobody, which is the same defect as the four
    # dead keyword lists reached from the other side.
    assert memory_retrieval.query_intent(query) == intent
    memory = {"id": "m", "timestamp": 1735689600, "category": "fact",
              "text": {"identity": "Her name is Ada Lovelace.",
                       "contact": "Her phone number is 0113 496 0000.",
                       "preference": "She prefers the aisle seat.",
                       "task": "Remind her about the deadline."}[expect]}
    assert memory_retrieval._intent_boost(intent, memory) > 1.0, \
        "the memory's own words must be able to earn the boost, not just its filed category"


def test_a_task_question_finds_a_task_memory_filed_as_a_plain_fact():
    # The same point, end to end rather than on the helper.
    rows = _corpus()
    ranked = _manager().explain_relevant_memories(
        "what do I need to remind myself about", rows, max_items=5)
    top = {r["memory"]["id"]: r for r in ranked}
    assert "cert" in top, "the task memory was not returned"
    assert "task question" in top["cert"]["reason"]


# ── the honest failures ───────────────────────────────────────────────────────


def test_a_query_of_nothing_but_stopwords_returns_nothing_rather_than_guessing():
    # "who am i" is the canonical memory question and every one of its words is
    # a stopword, so a lexical engine has no query left at all. The old scorer
    # answered it by admitting anything `_is_identity_memory` matched at a flat
    # 0.9 — and that predicate is any two consecutive capitalised words, so
    # "Docker Compose" qualified. Returning nothing is the honest answer, and
    # `B61` is what makes the reason visible.
    assert memory_retrieval.content_tokens("who am i") == []
    assert _manager().get_relevant_memories("who am i", _corpus(), max_items=5) == []


def test_a_live_index_answers_a_query_the_words_cannot():
    # And the other half: with a vector store, the same query is answerable.
    # This is the argument for `P13-16` stated as a test rather than as prose.
    class _Vector:
        healthy = True

        def search(self, query, k=5):
            return [{"memory_id": "office", "score": 0.71}]

    ranked = _manager().get_relevant_memories("who am i", _corpus(), max_items=5,
                                              vector=_Vector())
    assert [m["id"] for m in ranked] == ["office"]


def test_the_threshold_parameter_is_documented_as_ignored():
    # Five call sites pass `threshold=0.05`. The scorer behind this has three
    # gates a single floor cannot express, so the parameter is a compatibility
    # surface — and a parameter that silently does nothing is exactly the class
    # of quiet lie `B61` was filed about, so it has to say so where a reader
    # looks.
    doc = MemoryManager.get_relevant_memories.__doc__
    assert "accepted and ignored" in doc
    rows = _corpus()
    wide = _manager().get_relevant_memories("dark mode", rows, threshold=0.0, max_items=5)
    narrow = _manager().get_relevant_memories("dark mode", rows, threshold=0.99, max_items=5)
    assert wide == narrow, "the parameter is documented as ignored and is not"


def test_recency_can_never_outrank_relevance():
    # It is capped at 5% for a reason: "most recent" is what a memory system
    # degrades into when nothing else works, and it feels like relevance while
    # being nothing of the kind.
    import time
    rows = [{"id": "old", "text": "User prefers dark mode in every editor.",
             "category": "preference", "timestamp": 0},
            {"id": "new", "text": "Completely unrelated note about tarmac.",
             "category": "fact", "timestamp": int(time.time())}]
    ranked = [m["id"] for m in _manager().get_relevant_memories("dark mode", rows, max_items=5)]
    assert ranked[:1] == ["old"], "a fresh irrelevant memory outranked an old relevant one"


# ── the small corpus, which is everyone's first week ──────────────────────────


@pytest.mark.parametrize("size", [1, 2, 3, 5, 9, 10, 20])
def test_a_relevant_memory_is_found_however_few_memories_exist(size):
    """`P13-14`. IDF asks how surprising a term is in general and estimates it
    from how many documents contain it, so on a tiny corpus it has no sample and
    collapses: a term unique to one memory scores 0.288 at N=1 and 2.639 at
    N=20, a factor of nine, against a fixed relevance gate. **On a corpus of one
    or two, nothing cleared it and retrieval returned nothing at all.**

    A person's first week with this product is exactly the small-corpus case,
    and "the Brain remembers nothing until you have given it twenty things" is
    not a behaviour anyone chose.

    Found by the full suite, not by the golden set — whose fixture carries
    twenty memories and therefore could not see it. A measurement harness has a
    shape, and its shape is a blind spot."""
    rows = [{"id": "target", "text": "Alice prefers markdown notes",
             "category": "preference", "timestamp": 1735689600}]
    rows += [{"id": f"filler{n}", "text": f"Unrelated observation number {n} about tarmac",
              "category": "fact", "timestamp": 1735689600} for n in range(size - 1)]
    found = [m["id"] for m in _manager().get_relevant_memories("markdown preference", rows, max_items=5)]
    assert "target" in found, f"a corpus of {size} returned {found or 'nothing'}"


def test_the_idf_floor_leaves_a_realistic_corpus_exactly_as_it_was():
    """The floor is a fix for small corpora and must be invisible above ten,
    because a smoothing constant that quietly re-ranks everybody's memories
    would be a behaviour change hiding inside a bug fix."""
    rows = _corpus() + [{"id": f"f{n}", "text": f"Filler memory {n} about nothing much",
                         "category": "fact", "timestamp": 1735689600} for n in range(15)]
    assert len(rows) > memory_retrieval._MIN_IDF_CORPUS
    ranked = [m["id"] for m in _manager().get_relevant_memories("dark mode", rows, max_items=5)]
    assert ranked[0] == "dark"


def test_average_document_length_is_measured_not_smoothed():
    """Only IDF gets the floor. Average length is a fact about the corpus in
    hand — there is nothing to estimate and nothing to smooth — and padding it
    would normalise every memory against documents that do not exist."""
    source = (_REPO / "src" / "memory_retrieval.py").read_text(encoding="utf-8")
    code = "\n".join(ln for ln in source.splitlines() if not ln.lstrip().startswith("#"))
    assert "avg_len = max(sum(len(t) for t in tokens_by_id.values()) / len(memories), 1)" in code
    assert "n_docs = max(len(memories), _MIN_IDF_CORPUS)" in code


def test_a_verbatim_match_survives_words_too_common_to_score():
    """The gate ordering, on the path that actually exercises it. The earlier
    all-stopword test takes a different branch entirely, so a mutation removing
    the verbatim escape from the relevance gate survived it.

    Here every memory shares the query's words, so IDF flattens them to almost
    nothing and BM25 puts the exact match below the floor — which is precisely
    the case the exact-phrase rule exists for."""
    # The fillers carry the same *words* and not the same *phrase* — the first
    # version of this fixture wrote "build cache size" into all sixteen, so
    # every one of them was a verbatim match and the test was measuring tie
    # order rather than the gate.
    rows = [{"id": f"n{n}", "text": f"the build note {n} about cache and about size",
             "timestamp": 1735689600} for n in range(15)]
    rows.append({"id": "exact", "text": "build cache size", "timestamp": 1735689600})
    ranked = _manager().explain_relevant_memories("build cache size", rows, max_items=5)
    ids = [r["memory"]["id"] for r in ranked]
    assert "exact" in ids, f"the verbatim match was gated out; got {ids}"
    assert ranked[0]["memory"]["id"] == "exact"
    assert ranked[0]["reason"] == "the query appears in this memory word for word"


def test_recency_cannot_reorder_two_memories_that_both_matched():
    """`_W_RECENCY` is 0.05 and that number is load-bearing. The earlier recency
    test let the irrelevant memory be filtered by the relevance gate before
    weighting ever ran, so a mutation raising recency to a primary signal
    survived it. Both memories clear the gate here, and only the weights decide
    the order."""
    import time
    now = time.time()
    rows = [{"id": "old-and-right", "text": "The deployment key lives in the vault.",
             "timestamp": int(now - 4000 * 86400)},
            {"id": "new-and-vague", "text": "Deployment notes, unfinished.",
             "timestamp": int(now)}]
    ranked = _manager().explain_relevant_memories(
        "where is the deployment key", rows, max_items=5)
    ids = [r["memory"]["id"] for r in ranked]
    assert set(ids) == {"old-and-right", "new-and-vague"}, \
        f"both must clear the gate for this test to mean anything, got {ids}"
    assert ids[0] == "old-and-right", \
        "an eleven-year-old exact answer lost to a fresh vague note; recency is not a tiebreaker"


@pytest.mark.parametrize("intent", ["identity", "contact", "preference", "task"])
def test_a_memory_that_answers_a_different_kind_of_question_gets_no_boost(intent):
    """The other half of the boost tests. Asserting that a matching memory is
    boosted proves nothing on its own — a function returning the boost
    unconditionally passes every one of those — so this asserts the negative,
    which is what makes the positive mean something."""
    unrelated = {"id": "u", "timestamp": 1735689600, "category": "fact",
                 "text": "The tarmac was resurfaced in spring."}
    assert memory_retrieval._intent_boost(intent, unrelated) == 1.0


def test_no_boost_applies_when_the_question_has_no_shape():
    assert memory_retrieval.query_intent("resurface the tarmac") is None
    memory = {"id": "m", "timestamp": 1735689600, "category": "identity",
              "text": "Her name is Ada Lovelace."}
    assert memory_retrieval._intent_boost(None, memory) == 1.0
