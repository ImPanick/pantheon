# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1509` — `_MIN_KEYWORD` is a live knob, the keyword-lane twin of `B714`.

Measured on the tree this row started from: with no vector lane the relevance
is `_W_KEYWORD_ALONE × keyword`, and it was held to `_MIN_FINAL` — the vector
lane's floor, 0.11 — so the keyword-only engine admitted a memory at
`keyword > 0.116`, above `_MIN_KEYWORD = 0.08`. A memory scoring 0.10 on its
keywords was refused, and lowering `_MIN_KEYWORD` changed nothing.

Now that engine's floor is the keyword lane's own gate in its terms: a memory
is admitted exactly when its keyword score clears `_MIN_KEYWORD`, and lowering
the constant moves the admission. With vectors nothing changed. The golden set
is unchanged (`.pantheon/retrieval_eval.py`, the keyword-only call paths).

Driven through the real `memory_retrieval.retrieve`, with the BM25 score the
case states (`_bm25` answers it) and, for the vector lane, the stub
`tests/test_two_stage_retrieval_selects.py` uses.
"""
from __future__ import annotations

import pytest

from src import memory_retrieval as mr
from tests.test_two_stage_retrieval_selects import Vector

NOW = 2_000_000_000.0
QUERY = "what should I bring on the trip"
MEMORY = {"id": "m", "text": "Passport renewal is due in March", "timestamp": NOW - 3600,
          "category": "fact"}


@pytest.fixture
def keyword(monkeypatch):
    """Make the keyword lane score the memory exactly `score`."""
    def set_score(score):
        monkeypatch.setattr(mr, "_bm25", lambda *a, **k: (score * mr._KEYWORD_SCALE, {"trip"}))
    return set_score


def _admitted(vector=None):
    rows = mr.retrieve(QUERY, [dict(MEMORY)], k=5, vector=vector, now=NOW)
    return [r["id"] for r in rows] == ["m"]


def test_the_keyword_only_engine_admits_exactly_above_the_keyword_gate(keyword):
    """Red before: 0.10 cleared `_MIN_KEYWORD` and was refused by the vector
    lane's floor."""
    keyword(mr._MIN_KEYWORD + 0.02)
    assert _admitted() is True
    keyword(mr._MIN_KEYWORD - 0.005)
    assert _admitted() is False


def test_lowering_the_keyword_gate_moves_a_keyword_only_admission(keyword, monkeypatch):
    keyword(0.06)
    assert _admitted() is False
    monkeypatch.setattr(mr, "_MIN_KEYWORD", 0.05)
    assert _admitted() is True


def test_raising_it_moves_one_the_other_way(keyword, monkeypatch):
    keyword(0.15)
    assert _admitted() is True
    monkeypatch.setattr(mr, "_MIN_KEYWORD", 0.2)
    assert _admitted() is False


def test_with_vectors_the_combined_floor_is_unchanged(keyword):
    """`B714`'s floor still decides on the healthy engine: a memory with
    keyword evidence alone is admitted at `_MIN_FINAL / _W_KEYWORD`."""
    vector = Vector({QUERY: {"m": 0.0}})
    keyword(mr._MIN_FINAL / mr._W_KEYWORD + 0.01)
    assert _admitted(vector) is True
    keyword(mr._MIN_FINAL / mr._W_KEYWORD - 0.01)
    assert _admitted(vector) is False


def test_with_vectors_the_keyword_gate_still_lets_a_mixed_memory_be_scored(keyword, monkeypatch):
    """Where `_MIN_KEYWORD` already was a knob: a cosine under `_MIN_VECTOR`
    with some keyword evidence is scored on both lanes only past this gate."""
    vector = Vector({QUERY: {"m": 0.19}})
    keyword(0.07)
    assert _admitted(vector) is False
    monkeypatch.setattr(mr, "_MIN_KEYWORD", 0.05)
    assert _admitted(vector) is True
