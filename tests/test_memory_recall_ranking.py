# SPDX-License-Identifier: AGPL-3.0-or-later
"""B40 — the Brain ranked memories by "contains two capitalised words".

Found while building `H11`, the row that shows a person *why* a memory fired,
which is exactly the view that makes this impossible to miss.

The chain, all of it measured rather than read:

  * `identity_words` contains `"i"`, `"am"`, `"me"` and `"my"`, and the check was
    `word in query_lower` — a **substring** test. "what **i**s the weather" is an
    identity question. So is "expla**i**n the code" and "what ti**me**". Ten out
    of ten ordinary queries classified as identity, so the contact, preference
    and task boosts underneath had never run.
  * a memory counts as an "identity memory" if it contains any two consecutive
    capitalised words — "Bridge Street", "Docker Compose", "Hacker News".
  * for an identity query every identity memory is admitted at **0.9**, ahead of
    anything scored on actual similarity. With the classifier saying identity to
    everything, that was every query.
  * and identity memories were **excluded from scoring entirely** otherwise, so
    a memory could not be found by its own verbatim text.

It is not a corner: `MemoryVectorStore` needs ChromaDB, which is an **optional**
dependency, so on an install without it `_vector_available()` is False and this
keyword scorer is the only memory retrieval there is.

These tests are written as retrieval outcomes — "the memory that answers the
question comes back" — rather than as assertions about scores, because the
scores are an implementation detail and the outcome is the promise.
"""
import re

import pytest

from src.memory import MemoryManager


def _is_identity_memory(text) -> bool:
    """`B40`'s identity predicate, as `src/memory.py` held it: two consecutive
    capitalised words, or a self-naming phrase. An oracle for this file only."""
    lowered = (text or "").lower()
    return bool(re.search(r"\b[A-Z][a-z]+ [A-Z][a-z]+\b", text or "")
                or any(w in lowered for w in ("name is", "i'm", "i am", "called",
                                              "my name", "named", "call me")))


@pytest.fixture
def brain():
    """A believable brain: eight memories that happen to contain two capitalised
    words, and one that answers a question."""
    texts = [
        "Joseph Jeffrey works at Afrog Labs",
        "the office is at 12 Bridge Street",
        "deploys with Docker Compose on Sunday",
        "reads Hacker News every morning",
        "uses Visual Studio Code as an editor",
        "lives near Regents Park",
        "flies with British Airways",
        "runs Ubuntu Server on the NAS",
        "the build timeout is 900 seconds",
    ]
    return [{"text": t, "id": i} for i, t in enumerate(texts)]


@pytest.fixture
def recall():
    manager = MemoryManager.__new__(MemoryManager)
    return lambda q, mems, k=5: [m["id"] for m in
                                 manager.get_relevant_memories(q, mems, max_items=k)]


# ── the outcome ──

def test_the_memory_that_answers_the_question_is_retrieved(brain, recall):
    """Before: `[0, 1, 2, 3, 4]` — five memories about names and places, and the
    one containing the answer nowhere in the result at all."""
    got = recall("what is the build timeout", brain)
    assert 8 in got, f"the answering memory was not retrieved: {got}"
    assert got[0] == 8, f"and it should lead: {got}"


def test_a_memory_can_be_found_by_its_own_verbatim_text(brain, recall):
    """"Afrog Labs" is a substring of memory 0 and returned nothing, because
    identity memories never reached the exact-phrase rule that exists three
    lines further down and says a verbatim match is highly relevant."""
    assert recall("Afrog Labs", brain)[:1] == [0]


def test_a_named_person_can_be_asked_about_by_name(brain, recall):
    assert 0 in recall("where does Joseph Jeffrey work", brain)


def test_an_identity_query_still_gets_identity_memories_first(brain, recall):
    """The deliberate half, kept. The original comment says identity memories
    are admitted regardless of similarity for identity queries; that is a choice
    and this fix does not touch it — it just stops every query being one."""
    got = recall("who am I", brain)
    assert all(_is_identity_memory(brain[i]["text"]) for i in got), got


def test_a_preference_query_finds_the_preference(recall):
    """The boosts have never run in production. This is one of them working.

    Phrased in the third person on purpose. "do **I** prefer dark mode" still
    classifies as identity, because a standalone "I" is a real identity signal
    and identity is checked first — so a first-person preference question goes
    to the identity branch and the preference boost still does not fire. That is
    the group ORDER rather than the substring bug, it is a retrieval-quality
    judgement rather than a defect, and it is filed as `P13-11` instead of being
    changed here."""
    mems = [
        {"text": "Marcus Aurelius wrote Meditations", "id": "noise"},
        {"text": "prefers dark mode in every editor", "id": "answer"},
    ]
    assert recall("does he prefer dark mode or light", mems)[:1] == ["answer"]


# (`B1485`: the old keyword classifier — `_query_type`, `_matches_keyword` and
# `QUERY_KEYWORD_GROUPS` — and the `_is_identity_memory` predicate stayed in
# `src/memory.py` after the scorer moved to `src/memory_retrieval.py`, reached
# only by the tests that were here. They are gone; the predicate lives on below
# as this file's oracle for what "an identity memory" meant to `B40`.)


# ── the contract its five callers rely on ──

def test_the_return_shape_is_unchanged(brain):
    """Five production callers unpack this as a plain list of memory dicts.
    The scoring changed; the contract must not have."""
    manager = MemoryManager.__new__(MemoryManager)
    got = manager.get_relevant_memories("what is the build timeout", brain, max_items=3)
    assert isinstance(got, list) and len(got) <= 3
    assert all(isinstance(m, dict) and "text" in m for m in got)


def test_empty_inputs_still_return_empty(brain):
    manager = MemoryManager.__new__(MemoryManager)
    assert manager.get_relevant_memories("", brain) == []
    assert manager.get_relevant_memories("anything", []) == []
    assert manager.get_relevant_memories("   ", brain) == []
