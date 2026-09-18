# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P13-02` — typed edges between memories, as data rather than as a picture.

The boxed decision at the top of `P13` cut the graph visual and kept the graph:
*"a `supersedes` edge makes retrieval correct whether or not anyone ever looks
at it, and a recorded `contradicts` is worth having even if it is only ever
read by a query."* The row states the test that follows from it — **"an edge
that only exists to be drawn is not worth storing"** — so every assertion below
is about what comes back from a search, and there is not one about a layout.

Driven through `src/memory_retrieval.retrieve` / `.explain`, which is the ONE
scorer (`P13-14`) behind the Brain's search and debug endpoints, the agent's
MCP `memory_search`, the memory provider's fallback, `ai_interaction` and the
chat preface. An edge honoured at one call site and not the others would be
worse than none.
"""

import pytest

from src import memory_edges, memory_retrieval


def mem(mid, text, **extra):
    row = {"id": mid, "text": text, "timestamp": 1780000000, "category": "fact"}
    row.update(extra)
    return row


def edge(kind, target):
    return {"type": kind, "target": target}


def ids(rows):
    return [row["id"] for row in rows]


# ── supersedes: the memory stops surfacing ──

def test_a_superseded_memory_does_not_come_back():
    corpus = [
        mem("new", "User lives in Berlin", edges=[edge("supersedes", "old")]),
        mem("old", "User lives in Berlin"),
        mem("van", "User drives a diesel van"),
    ]
    assert "old" not in ids(memory_retrieval.retrieve("berlin", corpus, k=5))
    assert "new" in ids(memory_retrieval.retrieve("berlin", corpus, k=5))


def test_a_superseded_memory_does_not_come_back_on_a_verbatim_match_either():
    """The exact-phrase rule has its own early return, which is exactly the
    kind of second path an edge rule gets forgotten on. `P13-14` found the same
    shape of hole in the verbatim rule itself."""
    corpus = [
        mem("new", "the office moved to 12 Bridge Street",
            edges=[edge("supersedes", "old")]),
        mem("old", "12 Bridge Street"),
    ]
    # A query of pure stopwords plus the address takes the no-content-tokens
    # path, where only a verbatim match can score at all.
    assert ids(memory_retrieval.retrieve("12 Bridge Street", corpus, k=5)) == ["new"]


def test_an_edge_pointing_at_a_memory_that_no_longer_exists_does_nothing():
    """A relation to something deleted is not a relation. The `P13` preamble's
    whole lesson from PandAtlas is that an edge has to be earned."""
    corpus = [mem("new", "User lives in Berlin", edges=[edge("supersedes", "gone")])]
    assert ids(memory_retrieval.retrieve("berlin", corpus, k=5)) == ["new"]


def test_a_self_superseding_memory_does_not_erase_itself():
    corpus = [mem("a", "User lives in Berlin", edges=[edge("supersedes", "a")])]
    assert ids(memory_retrieval.retrieve("berlin", corpus, k=5)) == ["a"]


def test_a_junk_edge_is_skipped_rather_than_raised_on():
    """`memory.json` is a file a person can open and edit, so reading it is
    parsing, not validating our own output."""
    corpus = [
        mem("a", "User lives in Berlin", edges=[
            "not a dict", {"type": "invented"}, {"type": "supersedes"},
            {"type": "supersedes", "target": None}, edge("supersedes", "b"),
        ]),
        mem("b", "User lives in Munich"),
    ]
    assert ids(memory_retrieval.retrieve("berlin", corpus, k=5)) == ["a"]


# ── contradicts: both sides surface, and the conflict is named ──

def test_a_contradiction_surfaces_the_other_side_even_with_no_words_in_common():
    """The reason to record a contradiction at all: the other side is often
    unreachable by the query that found the first one. *"allergic to
    shellfish"* and *"had prawns and was fine"* share nothing but the fact they
    disagree about."""
    corpus = [
        mem("allergy", "User is allergic to shellfish",
            edges=[edge("contradicts", "prawns")]),
        mem("prawns", "User had prawns and was fine"),
        mem("van", "User drives a diesel van"),
    ]
    returned = ids(memory_retrieval.retrieve("allergic", corpus, k=5))
    assert returned[:2] == ["allergy", "prawns"], (
        "the other half of the contradiction did not surface beside it")


def test_the_conflict_is_named_in_the_reason():
    corpus = [
        mem("berlin", "User lives in Berlin", edges=[edge("contradicts", "munich")]),
        mem("munich", "User lives in Munich"),
    ]
    rows = {row["memory"]["id"]: row["reason"]
            for row in memory_retrieval.explain("where does the user live", corpus, k=5)}
    assert "contradicted by" in rows["berlin"]
    assert "Munich" in rows["berlin"]
    assert "contradicts" in rows["munich"]


def test_the_conflict_is_still_named_when_the_other_side_does_not_fit():
    """The slot budget may hide the other side. It may not hide that there is
    one — a model handed one half of a contradiction as fact is the whole
    failure this edge exists to prevent."""
    corpus = [
        mem("berlin", "User lives in Berlin", edges=[edge("contradicts", "munich")]),
        mem("munich", "User lives in Munich"),
    ]
    rows = memory_retrieval.explain("where does the user live", corpus, k=1)
    assert len(rows) == 1
    assert "contradicted by" in rows[0]["reason"]


def test_a_contradiction_is_read_from_either_end():
    """Stored once, on one side. Two stored copies of one relation is two
    records of one fact, and the day an edit reaches one of them they disagree
    (`Law 7`)."""
    corpus = [
        mem("berlin", "User lives in Berlin"),
        mem("munich", "User lives in Munich", edges=[edge("contradicts", "berlin")]),
    ]
    returned = ids(memory_retrieval.retrieve("berlin", corpus, k=5))
    assert set(returned) == {"berlin", "munich"}


def test_a_pulled_in_contradiction_keeps_its_own_score():
    """`H11`'s discipline. A memory that surfaced because of a relation did not
    match the question, and reporting the score of whatever pulled it in would
    be a number that explains nothing."""
    corpus = [
        mem("allergy", "User is allergic to shellfish",
            edges=[edge("contradicts", "prawns")]),
        mem("prawns", "User had prawns and was fine"),
    ]
    rows = {row["memory"]["id"]: row["score"]
            for row in memory_retrieval.explain("allergic", corpus, k=5)}
    assert rows["allergy"] > rows["prawns"]


# ── derived_from: one slot, not two ──

def test_a_memory_and_the_one_it_was_derived_from_do_not_both_take_a_slot():
    corpus = [
        mem("summary", "User lives in Berlin and works there",
            edges=[edge("derived_from", "source")]),
        mem("source", "User lives in Berlin"),
        mem("van", "User drives a diesel van"),
    ]
    returned = ids(memory_retrieval.retrieve("berlin", corpus, k=5))
    assert "summary" in returned and "source" not in returned


def test_a_source_nothing_derived_outranked_is_returned_normally():
    """Not a suppression of the source in general. It is only redundant when
    the memory made out of it is in the same answer."""
    corpus = [
        mem("summary", "User drives a diesel van", edges=[edge("derived_from", "source")]),
        mem("source", "User lives in Berlin"),
    ]
    assert ids(memory_retrieval.retrieve("berlin", corpus, k=5)) == ["source"]


# ── co_occurs: reorders inside the qualified set, never promotes into it ──

def test_a_co_occurring_memory_is_pulled_up_beside_what_it_accompanies():
    corpus = [
        mem("compose", "User deploys with Docker Compose",
            edges=[edge("co_occurs", "sunday")]),
        mem("filler", "User deploys the frontend nightly"),
        mem("sunday", "User deploys on Sunday evenings"),
    ]
    returned = ids(memory_retrieval.retrieve("deploys", corpus, k=2))
    assert returned == ["compose", "sunday"], (
        "the companion did not come up beside the memory that names it")


def test_co_occurs_never_promotes_a_memory_that_did_not_qualify():
    """No invented constant, and that restraint is the row's own test applied
    to the row's own list. A boost would need a number, and `P13-13`'s golden
    set is the instrument that would have to justify one."""
    corpus = [
        mem("compose", "User deploys with Docker Compose",
            edges=[edge("co_occurs", "cheese")]),
        mem("cheese", "User dislikes blue cheese"),
    ]
    assert ids(memory_retrieval.retrieve("deploys", corpus, k=5)) == ["compose"]


def test_a_corpus_of_memories_with_no_ids_still_comes_back_whole():
    """Found while writing `_apply_edges`, before any test did.

    The new selection step dedupes by id, and a set with `None` in it makes
    every id-less memory look like the same memory: the first is returned and
    every other one is silently dropped. `MemoryManager._validate_entries`
    assigns ids, so this cannot happen through the store — but five call sites
    hand this scorer lists they built themselves, and two test doubles in this
    repo do exactly that.
    """
    corpus = [
        {"text": "User likes pizza", "timestamp": 1780000000},
        {"text": "User likes pasta", "timestamp": 1780000000},
    ]
    assert len(memory_retrieval.retrieve("likes", corpus, k=5)) == 2


# ── the index itself ──

def test_the_index_reads_symmetric_edges_from_both_ends():
    corpus = [mem("a", "x", edges=[edge("contradicts", "b")]), mem("b", "y")]
    index = memory_edges.build_edge_index(corpus)
    assert index["contradicts"]["a"] == {"b"}
    assert index["contradicts"]["b"] == {"a"}


@pytest.mark.parametrize("kind", memory_edges.EDGE_TYPES)
def test_the_index_never_reports_a_relation_to_something_that_is_not_there(kind):
    """The index is a public read of the graph — `P13-07`'s Brain page will ask
    it what contradicts a memory — and a relation to an id nobody holds is the
    `≈1.0 edges per node` starburst the `P13` preamble is about: it looks like
    structure and points at nothing.

    Asserted on the index rather than only through a search, because the four
    types reach different downstream guards and a test that only drove
    retrieval would pass for `supersedes` by accident: excluding an id that is
    not in the corpus excludes nothing.
    """
    index = memory_edges.build_edge_index([mem("a", "x", edges=[edge(kind, "gone")])])
    assert index["superseded"] == set()
    assert index[memory_edges.EDGE_CONTRADICTS] == {}
    assert index[memory_edges.EDGE_CO_OCCURS] == {}
    assert index[memory_edges.EDGE_DERIVED_FROM] == {}


def test_attach_refuses_what_is_not_a_relation():
    a, b = mem("a", "x"), mem("b", "y")
    by_id = {"a": a, "b": b}
    assert memory_edges.attach(a, "invented", "b", by_id) is False
    assert memory_edges.attach(a, "contradicts", "a", by_id) is False
    assert memory_edges.attach(a, "contradicts", "nowhere", by_id) is False
    assert a.get("edges") in (None, [])


def test_attach_is_idempotent_including_across_the_mirror():
    a, b = mem("a", "x"), mem("b", "y")
    by_id = {"a": a, "b": b}
    assert memory_edges.attach(a, "contradicts", "b", by_id) is True
    assert memory_edges.attach(a, "contradicts", "b", by_id) is False
    assert memory_edges.attach(b, "contradicts", "a", by_id) is False
    assert len(a["edges"]) == 1 and not b.get("edges")


def test_live_is_the_one_definition_of_stale():
    corpus = [mem("new", "x", edges=[edge("supersedes", "old")]), mem("old", "x")]
    assert ids(memory_edges.live(corpus)) == ["new"]
    assert memory_edges.superseded_ids(corpus) == {"old"}


@pytest.mark.parametrize("kind", memory_edges.EDGE_TYPES)
def test_every_declared_edge_type_changes_what_retrieval_returns(kind):
    """The row's test, applied to the row's own list rather than to one example.

    Each type is exercised with the same two memories and the same query; the
    assertion is only that the result differs from the no-edge baseline. A type
    added to `EDGE_TYPES` without a rule in `_apply_edges` fails here, which is
    the check that stops this growing a fifth name that only exists to be drawn.
    """
    def answer(edges):
        corpus = [
            mem("a", "User deploys with Docker Compose", edges=edges),
            mem("b", "User deploys on Sunday evenings"),
        ]
        # Ids AND reasons: two of the four types change which memories come
        # back and two change what is said about them, and "an edge that only
        # exists to be drawn" means neither. A comparison on ids alone would
        # pass `contradicts` and `co_occurs` for the wrong reason.
        return [(row["memory"]["id"], row["reason"])
                for row in memory_retrieval.explain("deploys", corpus, k=2)]

    assert answer([]) != answer([edge(kind, "b")]), (
        f"{kind!r} is declared but changes nothing about what is returned")
