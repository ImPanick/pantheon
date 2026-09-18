# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P13-16` — recall wide, then select, where the selecting is arithmetic.

The row asked for a model to do the selecting and its own 2026-09-10 correction
asked for the cheap candidate to be measured first: *"a score-gap cutoff is a
real and much cheaper candidate that has to be measured against the model call
before the model call is justified."* It was measured, and it wins the half it
can win — **volume** — while provably losing the half it cannot: a relative
floor is scale-free, so it keeps the top of a list of rubbish exactly the way
it keeps the top of a list of good answers.

Both halves are asserted here. The first group is the selection step doing its
job; the last group is the boundary, and it exists so nobody later mistakes this
for the whole row.

Driven through `src/memory_retrieval.retrieve` / `.explain`, the one scorer
(`P13-14`) behind every memory surface. The vector index is a stub with scores
written into the test rather than the real model: the property under test is
what the selector does with a score distribution, and a stub states the
distribution instead of hoping the embedding model produces it.
"""

import pytest

from src import memory_retrieval


def mem(mid, text, **extra):
    row = {"id": mid, "text": text, "timestamp": 1780000000, "category": "fact"}
    row.update(extra)
    return row


def ids(rows):
    return [row["id"] for row in rows]


class Vector:
    """The smallest thing `_vector_scores` accepts: healthy, and it searches.

    Scores are supplied per query so a test can state the distribution it is
    about — "one strong answer and three weak ones", "four equally weak ones" —
    rather than depending on what an embedding model happens to produce for a
    sentence somebody wrote in a fixture.
    """

    healthy = True

    def __init__(self, scores):
        self._scores = scores

    def search(self, query, k=8):
        rows = [{"memory_id": mid, "score": s}
                for mid, s in sorted(self._scores.get(query, {}).items(),
                                     key=lambda kv: -kv[1])]
        return rows[:k]


CORPUS = [
    mem("m1", "User is allergic to shellfish"),
    mem("m2", "User drives a diesel van for site visits"),
    mem("m3", "User keeps notes in Obsidian"),
    mem("m4", "User's cat is called Bramble"),
]


# ── the selection step ────────────────────────────────────────────────────────

def test_a_weak_candidate_beside_a_strong_one_does_not_take_a_slot():
    # The row's whole subject. Everything below scores above the relevance
    # gates, so before this all four were injected; only the first answers the
    # question and the other three are context the model has to ignore.
    vector = Vector({"can I eat prawns": {"m1": 0.90, "m2": 0.30,
                                          "m3": 0.28, "m4": 0.26}})
    got = ids(memory_retrieval.retrieve("can I eat prawns", CORPUS, k=5,
                                        vector=vector))
    assert got == ["m1"], got


def test_a_close_second_is_kept_because_it_might_be_the_answer():
    # The other side of the same rule, and the reason the floor is relative:
    # two candidates that scored nearly the same are two candidates the scorer
    # cannot separate, and dropping one of them is guessing.
    vector = Vector({"what do I drive": {"m2": 0.90, "m1": 0.85, "m3": 0.20}})
    got = ids(memory_retrieval.retrieve("what do I drive", CORPUS, k=5,
                                        vector=vector))
    assert got == ["m2", "m1"], got


def test_the_floor_is_relative_and_not_a_second_absolute_threshold():
    # Same *shape* at a lower scale: the best answer is weaker in absolute
    # terms, and its close companion still belongs beside it. An absolute floor
    # cannot express this, which is why `_MIN_VECTOR` was not simply raised.
    vector = Vector({"what do I drive": {"m2": 0.42, "m1": 0.40, "m3": 0.09}})
    got = ids(memory_retrieval.retrieve("what do I drive", CORPUS, k=5,
                                        vector=vector))
    assert got == ["m2", "m1"], got


def test_the_best_answer_is_never_dropped():
    # A floor computed from the top score can never cut the top score. Asserted
    # rather than assumed, because the obvious off-by-one — `>` instead of
    # `>=`, or a floor computed from the second — empties the result.
    vector = Vector({"any allergies": {"m1": 0.55}})
    assert ids(memory_retrieval.retrieve("any allergies", CORPUS, k=5,
                                         vector=vector)) == ["m1"]


def test_a_memory_scoring_exactly_the_floor_is_kept():
    # The boundary, and it is asserted on the selector itself rather than
    # through the blend: `final` carries a recency tiebreaker computed from the
    # clock, so a ratio arranged at the input does not survive to the output and
    # a test that pretended otherwise would be pinning today's date. The rule is
    # stated in words — "at least half what the best one scored" — and `>`
    # instead of `>=` makes that sentence false in the one case a reader would
    # check it against.
    a, b = mem("a", "x"), mem("b", "y")
    ranked = [(1.0, a, ""), (memory_retrieval._RELATIVE_FLOOR, b, "")]
    assert [row[1]["id"] for row in memory_retrieval._select(ranked)] == ["a", "b"]


def test_a_memory_scoring_a_hair_under_the_floor_is_dropped():
    # The other side of the same line, so the pair cannot both be satisfied by
    # a selector that keeps everything.
    a, b = mem("a", "x"), mem("b", "y")
    ranked = [(1.0, a, ""), (memory_retrieval._RELATIVE_FLOOR - 0.001, b, "")]
    assert [row[1]["id"] for row in memory_retrieval._select(ranked)] == ["a"]


def test_selection_never_reorders_what_survives():
    # It removes; it does not rank. A selector that also reordered would be a
    # second ranking to reconcile with the first.
    vector = Vector({"any allergies": {"m1": 0.90, "m2": 0.80, "m3": 0.70}})
    assert ids(memory_retrieval.retrieve("any allergies", CORPUS, k=5,
                                         vector=vector)) == ["m1", "m2", "m3"]


def test_what_was_cut_is_reported_rather_than_silently_gone():
    # `B61`'s discipline on this row's step: a retrieval that quietly returns
    # fewer memories than it scored is indistinguishable from an index that had
    # nothing, and they are opposite problems.
    vector = Vector({"can I eat prawns": {"m1": 0.90, "m2": 0.30,
                                          "m3": 0.28, "m4": 0.26}})
    report = {}
    memory_retrieval.retrieve("can I eat prawns", CORPUS, k=5,
                              vector=vector, report=report)
    assert report["selection_dropped"] == 3
    assert report["selection_floor"] == memory_retrieval._RELATIVE_FLOOR


def test_a_run_that_cut_nothing_reports_zero_rather_than_nothing():
    # Written before every early return, for the reason `B61` gives: a key that
    # is absent on some paths makes every reader write a default, and the
    # default is the answer nobody measured.
    report = {}
    memory_retrieval.retrieve("", CORPUS, k=5, report=report)
    assert report["selection_dropped"] == 0


# ── the rules it must not undo ────────────────────────────────────────────────

def test_a_contradiction_partner_still_surfaces_below_the_floor():
    # `P13-02`: a contradiction is pulled in from the whole live corpus
    # precisely because it may share no words with the question, so it arrives
    # with a low score by construction. A selection step applied after the edge
    # rules would delete exactly the rows the edge rules exist to add.
    corpus = [
        mem("yes", "User is allergic to shellfish",
            edges=[{"type": "contradicts", "target": "no"}]),
        mem("no", "User had prawns last night and was fine"),
        mem("van", "User drives a diesel van"),
    ]
    vector = Vector({"can I eat prawns": {"yes": 0.90, "van": 0.30}})
    got = ids(memory_retrieval.retrieve("can I eat prawns", corpus, k=5,
                                        vector=vector))
    assert got[0] == "yes"
    assert "no" in got, got


def test_verbatim_matches_are_all_kept():
    # Every verbatim row carries the same score, so the floor cannot separate
    # them. Asserted so the rule is not quietly narrowed later: a query typed
    # word for word into two memories has two right answers.
    corpus = [mem("a", "the build timeout is 900 seconds"),
              mem("b", "the build timeout is what tripped CI")]
    assert set(ids(memory_retrieval.retrieve("the build timeout", corpus, k=5))) \
        == {"a", "b"}


def test_the_lexical_path_keeps_every_memory_it_used_to_find():
    # The golden set's `manager` / `preface` numbers are `0.77 / 0.767` and this
    # row must not move them. Asserted as the property rather than as the
    # figure: every probe the lexical scorer answered before, it still answers.
    import json
    from pathlib import Path
    corpus = json.loads((Path(__file__).resolve().parents[1] / ".pantheon"
                         / "fixtures" / "retrieval_probe.json").read_text())
    answered = 0
    for probe in corpus["probes"]:
        got = ids(memory_retrieval.retrieve(probe["query"],
                                            [dict(m) for m in corpus["memories"]], k=5))
        if set(got) & set(probe["expect"]):
            answered += 1
    assert answered >= 23, f"lexical recall fell to {answered}/30 — it was 23/30"


# ── the boundary: what arithmetic cannot do, stated so nobody assumes it can ──

def test_a_relative_floor_cannot_tell_the_best_of_nothing_from_the_best_of_something():
    """The measurement that keeps the model half of `P13-16` open.

    An off-topic question still ranks *something* — every memory gets a cosine
    — and the floor is computed from whatever won, so a query whose best match
    is rubbish keeps that rubbish exactly the way a good query keeps its answer.
    This is why the absolute gates were NOT lowered to let stage one widen:
    measured on the golden set with the in-process index, dropping them takes
    recall from 0.933 to 1.000 and off-topic injection from 0.12 to 1.50
    memories per query.
    """
    vector = Vector({"who won the 1998 world cup": {"m1": 0.30, "m2": 0.29,
                                                    "m3": 0.28, "m4": 0.27}})
    got = ids(memory_retrieval.retrieve("who won the 1998 world cup", CORPUS,
                                        k=5, vector=vector))
    assert got == ["m1", "m2", "m3", "m4"], (
        "the floor started rejecting on an absolute scale — re-derive the row, "
        "because that is the job it is documented as not doing")


def test_the_absolute_gates_are_still_what_refuses_an_unrelated_question():
    # The same query with scores below `_MIN_VECTOR`: nothing comes back, and
    # it is the absolute gate that did it, not the selection step.
    vector = Vector({"who won the 1998 world cup": {"m1": 0.10, "m2": 0.09}})
    assert memory_retrieval.retrieve("who won the 1998 world cup", CORPUS,
                                     k=5, vector=vector) == []


# ── the instrument, because a precision claim needs a column to live in ───────
#
# `P13-13`'s harness reported recall@k and MRR, and a selection step cannot move
# either: it removes rows *below* the one that was found. So the row's claim had
# nowhere to be measured, and its own correction quoted `precision 0.20` — which
# on a corpus where every probe names one right answer is `recall@k / k` and
# says nothing about any engine. These assertions hold the two columns that do.

import importlib.util
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "retrieval_eval_p1316", _REPO / ".pantheon" / "retrieval_eval.py")
retrieval_eval = importlib.util.module_from_spec(_spec)
sys.modules["retrieval_eval_p1316"] = retrieval_eval
_spec.loader.exec_module(retrieval_eval)


def _corpus():
    return {"probes": [{"query": "q1", "expect": ["a"]},
                       {"query": "q2", "expect": ["b"]}],
            "memories": [{"id": "a"}, {"id": "b"}, {"id": "c"}]}


def test_the_report_says_how_many_memories_it_took_to_get_that_recall():
    # Two engines with identical recall and MRR and different appetites. Before
    # this column they were indistinguishable in the report, and the whole of
    # `P13-16` is the difference between them.
    lean = retrieval_eval.score(_corpus(), {"q1": ["a"], "q2": ["b"]}, 5)
    greedy = retrieval_eval.score(_corpus(), {"q1": ["a", "c"], "q2": ["b", "c"]}, 5)
    assert lean["recall@5"] == greedy["recall@5"] == 1.0
    assert lean["mrr"] == greedy["mrr"] == 1.0
    assert lean["returned"] == 1.0 and greedy["returned"] == 2.0
    assert lean["precision"] == 1.0 and greedy["precision"] == 0.5


def test_precision_is_over_what_was_returned_and_not_over_k():
    # The correction this row inherited read `precision@5 0.20` as "four of the
    # five memories injected are irrelevant". On a one-answer corpus an engine
    # that returns exactly k scores recall/k whatever it does — so the number
    # has to be over the list the engine CHOSE, not over the cutoff.
    out = retrieval_eval.score(_corpus(), {"q1": ["a"], "q2": ["b"]}, 5)
    assert out["precision"] == 1.0, "precision is being computed against k"


def test_returned_counts_the_list_the_cutoff_actually_allowed():
    # `k` is the slot budget, so a ranker handing back twenty rows still only
    # injects five. Counting the whole ranking would make every engine look
    # greedier than the product is and would move this column for a change that
    # cannot reach a prompt.
    out = retrieval_eval.score(_corpus(), {"q1": ["a", "c", "b"], "q2": ["b"]}, 1)
    assert out["returned"] == 1.0


def test_an_engine_that_returns_nothing_is_not_reported_as_perfectly_precise():
    out = retrieval_eval.score(_corpus(), {"q1": [], "q2": []}, 5)
    assert out["precision"] == 0.0 and out["returned"] == 0.0


def test_the_product_path_with_its_own_index_is_one_of_the_engines():
    # `manager` and `preface` pass `vector=None`, which stopped describing the
    # product at `P13-21`: an unreachable ChromaDB now degrades to in-process
    # vectors, and two of three shipped deployments never had a service at all.
    # Without this engine the harness measures no configuration the product has.
    assert "local" in retrieval_eval.ENGINES
    assert "local" not in retrieval_eval.CALL_PATHS, (
        "`local` has a vector index, so it cannot be held to the rule that the "
        "two lexical call paths return identical rankings")
