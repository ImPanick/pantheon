# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B714` — `_MIN_VECTOR` and `_MIN_FINAL` are one gate, and the clock is not in it.

The row: `_MIN_VECTOR = 0.20` gated a raw cosine and `_MIN_FINAL = 0.12` gated
`0.55 × vector + 0.40 × keyword + tiebreak`, the tiebreak being the 5%
recency/durability term. For a memory sharing no words with the question the
second reduced to `vector > (0.12 − tiebreak) / 0.55` — **0.127 for a memory
saved today and 0.205 for one saved years ago** — so the admission floor moved
with a memory's age, and on a corpus of older memories `_MIN_FINAL` was what
refused, which is why lowering `_MIN_VECTOR` to 0.15, 0.10, 0.05 and 0.0 left
the golden set identical (`P13-16`'s measurement).

Both halves of the row's `Verify:` are taken. The admission test reads the
relevance terms without the tiebreak (`_rank`'s `relevance`), and `_MIN_FINAL`
is expressed in terms of the vector lane's own gate (`_W_VECTOR × _MIN_VECTOR`),
so a memory sharing no words is admitted exactly when its cosine clears
`_MIN_VECTOR`, at any age. The golden set is unchanged: every engine's
per-query lists out of `.pantheon/retrieval_eval.py` were identical before and
after, the in-process index on a cached `bge-small-en-v1.5` (2026-10-26).

Driven through the real `memory_retrieval.retrieve` with a vector stub whose
scores the case states (the stub `tests/test_two_stage_retrieval_selects.py`
uses).

`Verify:` the two constants are reconciled … and the golden set is unchanged
either way.
"""
from __future__ import annotations

import pytest

from src import memory_retrieval as mr
from tests.test_two_stage_retrieval_selects import Vector

NOW = 2_000_000_000.0
QUERY = "what should I bring on the trip"
TODAY, YEARS_AGO = NOW - 3600, NOW - 6 * 365 * 86400


def _admitted(cosine, saved_at):
    # Shares no word with the question: the vector lane is the only evidence,
    # which is the case the row measured.
    memory = {"id": "m", "text": "Passport renewal is due in March", "timestamp": saved_at,
              "category": "fact"}
    rows = mr.retrieve(QUERY, [memory], k=5, vector=Vector({QUERY: {"m": cosine}}), now=NOW)
    return [r["id"] for r in rows] == ["m"]


def test_the_combined_floor_is_the_vector_gate_expressed_once():
    assert mr._MIN_FINAL == pytest.approx(mr._W_VECTOR * mr._MIN_VECTOR)


@pytest.mark.parametrize("cosine", [mr._MIN_VECTOR + 0.005, mr._MIN_VECTOR + 0.012])
def test_two_memories_differing_only_in_age_get_the_same_verdict(cosine):
    """Red before: just above `_MIN_VECTOR`, the memory saved today was
    admitted on its tiebreak and the one saved six years ago was refused."""
    assert _admitted(cosine, TODAY) is True
    assert _admitted(cosine, YEARS_AGO) is True


def test_below_the_vector_gate_neither_is_admitted():
    assert _admitted(mr._MIN_VECTOR - 0.005, TODAY) is False
    assert _admitted(mr._MIN_VECTOR - 0.005, YEARS_AGO) is False


def test_the_tiebreak_still_orders_what_is_admitted():
    """Recency stayed a tiebreaker: two equal cosines, the newer one first."""
    rows = mr.retrieve(QUERY, [
        {"id": "old", "text": "Passport renewal is due in March", "timestamp": YEARS_AGO},
        {"id": "new", "text": "Passport renewal is due in April", "timestamp": TODAY},
    ], k=5, vector=Vector({QUERY: {"old": 0.6, "new": 0.6}}), now=NOW)
    assert [r["id"] for r in rows] == ["new", "old"]
