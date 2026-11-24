# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2152`. `P14-02`'s retrieval hit rate for the document index was recorded
by `src/rag_manager.RAGManager.search`, a wrapper the running product never
built: `rag_singleton.get_rag_manager` hands out `VectorRAG` itself. So no
`retrieval` row named `rag` was ever written, and `/metrics` and a run's
receipt counted memory retrievals alone. The event is recorded by
`VectorRAG.search` now, the search every caller runs.

Driven through the real `search`, with the store's lanes faked at the seam
the search reads them through (`query_lanes`)."""
from __future__ import annotations

import pytest

import src.rag_vector as rv


class _Lane:
    name = "custom"

    def __init__(self, n):
        self._n = n

    def count(self):
        return self._n


@pytest.fixture
def recorded(monkeypatch):
    rows = []

    def _record(kind, **kw):
        rows.append({"kind": kind, **kw})
        return True

    monkeypatch.setattr("src.events.record_event", _record)
    return rows


def _store(lanes, healthy=True):
    store = rv.VectorRAG.__new__(rv.VectorRAG)
    store._healthy = healthy
    store._lanes = lanes
    store._collection = object()
    return store


def test_a_search_that_finds_something_is_recorded_as_ok(monkeypatch, recorded):
    lane = _Lane(3)

    def _query_lanes(lanes, query, **kw):
        assert kw["where"] == {"owner": "alice"}
        yield lane, {"ids": [["d1"]], "distances": [[0.1]],
                     "documents": [["the lease runs to May"]],
                     "metadatas": [[{"owner": "alice"}]]}

    monkeypatch.setattr(rv, "query_lanes", _query_lanes)
    hits = _store([lane]).search("the lease", k=4, owner="alice")

    assert [h["id"] for h in hits] == ["d1"]
    (row,) = [r for r in recorded if r["kind"] == "retrieval"]
    assert row["name"] == "rag" and row["owner"] == "alice"
    assert row["outcome"] == "ok"
    assert row["detail"] == {"asked": 4, "returned": 1}


def test_an_index_with_nothing_in_it_is_unavailable_not_empty(monkeypatch, recorded):
    assert _store([_Lane(0)]).search("anything", owner="bob") == []
    (row,) = [r for r in recorded if r["kind"] == "retrieval"]
    assert row["outcome"] == "unavailable"


def test_a_store_that_is_down_is_unavailable(recorded):
    assert _store([], healthy=False).search("anything", owner="bob") == []
    (row,) = [r for r in recorded if r["kind"] == "retrieval"]
    assert row["outcome"] == "unavailable" and row["owner"] == "bob"


def test_a_miss_is_recorded_as_empty(monkeypatch, recorded):
    lane = _Lane(2)
    monkeypatch.setattr(rv, "query_lanes", lambda *a, **k: iter([
        (lane, {"ids": [[]], "distances": [[]], "documents": [[]], "metadatas": [[]]})]))
    assert _store([lane]).search("nothing like it", owner="bob") == []
    (row,) = [r for r in recorded if r["kind"] == "retrieval"]
    assert row["outcome"] == "empty"


def test_a_broken_recorder_never_breaks_a_search(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("recorder down")

    monkeypatch.setattr("src.events.record_event", _boom)
    assert _store([], healthy=False).search("anything") == []
