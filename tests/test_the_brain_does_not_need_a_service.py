# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P13-21` — semantic memory without a vector database.

`B61` made a silent degradation visible: semantic search runs against a ChromaDB
**service**, so a working install drops to lexical retrieval whenever that
process is not running. This removes the reason.

**The embedding model was never the service.** `fastembed` is local ONNX, ships
in `requirements.txt`, and reaches no network once cached. Only the *index* was
remote — and for a personal Brain an index is a matrix multiply. Measured with
numpy over 384-dimension vectors: **0.13ms at 100 memories, 0.82ms at 10,000**
(15MB), 12ms at 100,000, 135ms at a million. Ten thousand memories is years of
daily use.

**`Law 1`: ChromaDB is not removed and is still tried first.** What changes is
that an unreachable service degrades to semantic search rather than to keyword
matching — `recall@5 1.00` against `0.77` on the golden set.

**And the two deployments this rescues are the ones nobody was watching**
(`B64`): `launch-windows.ps1` mentions chroma zero times, and `start-macos.sh`
force-installs a heavier package to avoid a failure mode `src/chroma_client.py`
cannot have, because `HttpClient` is the only client it ever builds. Docker —
the maintainer's own deployment — is the one that already worked, which is
exactly why the gap stayed invisible.
"""

import json
import os
from pathlib import Path

import numpy as np
import pytest

from src import embedding_lanes
from src.local_collection import LocalCollection, LocalIndexClient

_REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def client(tmp_path):
    return LocalIndexClient(str(tmp_path))


def _unit(*rows):
    m = np.array(rows, dtype="float32")
    return (m / np.linalg.norm(m, axis=1, keepdims=True)).tolist()


# ── the Chroma surface, only as far as callers actually use it ────────────────


def test_it_answers_the_five_methods_the_callers_use(client):
    # `memory_vector` and `rag_vector` call exactly these. Matching a subset of
    # somebody's API on purpose is how one index becomes two implementations
    # behind one interface instead of two code paths (`Law 13`).
    col = client.get_or_create_collection("c", {"embedding_fingerprint": "f"})
    for name in ("add", "get", "query", "delete", "count"):
        assert callable(getattr(col, name)), f"{name} is missing"


def test_nearest_neighbours_come_back_in_chroma_distance(client):
    # ChromaDB cosine distance is 1 - similarity, and `memory_vector` converts
    # it straight back. Returning raw similarity here would invert every score
    # in the product and nothing would crash.
    col = client.get_or_create_collection("c")
    col.add(ids=["a", "b", "c"], embeddings=_unit([1, 0, 0], [0, 1, 0], [1, 1, 0]),
            documents=["A", "B", "C"], metadatas=[{}] * 3)
    out = col.query(query_embeddings=[[1, 0, 0]], n_results=3, include=["distances"])
    assert out["ids"][0][0] == "a"
    assert out["distances"][0][0] == pytest.approx(0.0, abs=1e-5)
    assert out["distances"][0] == sorted(out["distances"][0]), "results must be nearest-first"


def test_an_empty_collection_answers_with_empty_lists_not_an_error(client):
    # `memory_vector.search` indexes `results["ids"][0]` unconditionally.
    out = client.get_or_create_collection("c").query(query_embeddings=[[1, 0, 0]], n_results=5)
    assert out["ids"] == [[]] and out["distances"] == [[]]


def test_asking_for_more_than_it_holds_returns_what_it_holds(client):
    col = client.get_or_create_collection("c")
    col.add(ids=["a"], embeddings=_unit([1, 0, 0]), documents=["A"], metadatas=[{}])
    assert col.query(query_embeddings=[[1, 0, 0]], n_results=50)["ids"] == [["a"]]


def test_re_adding_an_id_replaces_it_rather_than_duplicating(client):
    col = client.get_or_create_collection("c")
    col.add(ids=["a"], embeddings=_unit([1, 0, 0]), documents=["first"], metadatas=[{}])
    col.add(ids=["a"], embeddings=_unit([0, 1, 0]), documents=["second"], metadatas=[{}])
    assert col.count() == 1
    assert col.get(ids=["a"], include=["documents"])["documents"] == ["second"]
    assert col.query(query_embeddings=[[0, 1, 0]], n_results=1, include=["distances"]
                     )["distances"][0][0] == pytest.approx(0.0, abs=1e-5)


def test_delete_removes_the_vector_and_not_just_the_id(client):
    # Dropping the id while leaving the row would shift every later vector by
    # one and silently return the wrong memory for every query after it.
    col = client.get_or_create_collection("c")
    col.add(ids=["a", "b", "c"], embeddings=_unit([1, 0, 0], [0, 1, 0], [0, 0, 1]),
            documents=["A", "B", "C"], metadatas=[{}] * 3)
    col.delete(ids=["a"])
    assert col.count() == 2
    assert col.query(query_embeddings=[[0, 0, 1]], n_results=1, include=["distances"]
                     )["ids"] == [["c"]]


def test_get_on_an_unknown_id_returns_nothing_rather_than_raising(client):
    col = client.get_or_create_collection("c")
    col.add(ids=["a"], embeddings=_unit([1, 0, 0]), documents=["A"], metadatas=[{}])
    assert col.get(ids=["nope"])["ids"] == []


def test_get_collection_raises_for_one_that_does_not_exist(client):
    # Chroma raises, and `_get_or_reset_collection` uses that exception as its
    # "first run" branch. Returning an empty collection would make every start
    # look like a fingerprint match against nothing.
    with pytest.raises(Exception):
        client.get_collection("never-created")


# ── it is a cache, and behaves like one ───────────────────────────────────────


def test_it_survives_a_restart(tmp_path):
    a = LocalIndexClient(str(tmp_path))
    col = a.get_or_create_collection("c", {"embedding_fingerprint": "f1"})
    col.add(ids=["a", "b"], embeddings=_unit([1, 0, 0], [0, 1, 0]),
            documents=["A", "B"], metadatas=[{}] * 2)
    reopened = LocalIndexClient(str(tmp_path)).get_collection("c")
    assert reopened.count() == 2
    assert reopened.query(query_embeddings=[[0, 1, 0]], n_results=1)["ids"] == [["b"]]


def test_the_embedding_fingerprint_survives_a_restart(tmp_path):
    """`_get_or_reset_collection` reads `collection.metadata` to decide whether
    the embedding model changed. Without persisting it, every restart looks like
    a model change and rebuilds an index that was fine.

    The first version of the loader compared `len(rows)` — the number of *keys*
    in the payload — against the number of vectors, so it threw the whole index
    away on every start and rebuilt it silently, because a cache miss is not an
    error here. It passed the smoke test only because the counts coincided."""
    a = LocalIndexClient(str(tmp_path))
    a.get_or_create_collection("c", {"embedding_fingerprint": "f1", "embedding_dimension": 3}).add(
        ids=["a"], embeddings=_unit([1, 0, 0]), documents=["A"], metadatas=[{}])
    reopened = LocalIndexClient(str(tmp_path)).get_collection("c")
    assert reopened.metadata.get("embedding_fingerprint") == "f1"
    assert reopened.count() == 1, "the index was discarded on reload"


def test_a_corrupt_cache_is_a_miss_and_not_a_crash(tmp_path):
    # Every vector is derivable from memory.json, so a truncated file is
    # rebuilt rather than mourned.
    a = LocalIndexClient(str(tmp_path))
    col = a.get_or_create_collection("c")
    col.add(ids=["a"], embeddings=_unit([1, 0, 0]), documents=["A"], metadatas=[{}])
    Path(col._path).write_bytes(b"not an npz file at all")
    reopened = LocalIndexClient(str(tmp_path)).get_collection("c")
    assert reopened.count() == 0
    reopened.add(ids=["z"], embeddings=_unit([0, 0, 1]), documents=["Z"], metadatas=[{}])
    assert reopened.count() == 1, "it must still be usable after a bad load"


def test_writing_leaves_no_temporary_file_behind(tmp_path):
    # The index is written to a sibling and renamed, because a half-written
    # index that loads is worse than one that does not — it would answer with a
    # subset and nothing would say so. The first version left a zero-byte `.tmp`
    # on every single write.
    col = LocalIndexClient(str(tmp_path)).get_or_create_collection("c")
    for n in range(4):
        col.add(ids=[f"m{n}"], embeddings=_unit([n + 1, 0, 0]), documents=["x"], metadatas=[{}])
    assert sorted(p.name for p in tmp_path.iterdir()) == ["c.npz"]


def test_a_changed_embedding_dimension_resets_rather_than_refusing(client):
    # Chroma refuses a dimension change; refusing here would strand an operator
    # with an index they can neither use nor replace, over a cache.
    col = client.get_or_create_collection("c")
    col.add(ids=["a"], embeddings=_unit([1, 0, 0]), documents=["A"], metadatas=[{}])
    col.add(ids=["b"], embeddings=_unit([1, 0, 0, 0]), documents=["B"], metadatas=[{}])
    assert col.count() == 1
    assert col.query(query_embeddings=[[1, 0, 0, 0]], n_results=1)["ids"] == [["b"]]


def test_a_zero_vector_does_not_divide_by_zero(client):
    col = client.get_or_create_collection("c")
    col.add(ids=["z"], embeddings=[[0.0, 0.0, 0.0]], documents=["Z"], metadatas=[{}])
    out = col.query(query_embeddings=[[0.0, 0.0, 0.0]], n_results=1, include=["distances"])
    assert out["ids"] == [["z"]]
    assert not np.isnan(out["distances"][0][0])


# ── the choice between the two indexes ────────────────────────────────────────


def test_chromadb_is_still_tried_first(monkeypatch):
    """`Law 1`. The service is not removed — it is preferred when it answers."""
    sentinel = object()
    monkeypatch.setattr("src.chroma_client.get_chroma_client", lambda: sentinel)
    assert embedding_lanes.index_client() is sentinel
    assert embedding_lanes.index_backend() == embedding_lanes.INDEX_CHROMA


def test_an_unreachable_service_falls_back_to_the_in_process_index(monkeypatch, tmp_path):
    def _refuse():
        raise RuntimeError("ChromaDB is not reachable at localhost:8100")

    monkeypatch.setattr("src.chroma_client.get_chroma_client", _refuse)
    monkeypatch.setattr("src.constants.DATA_DIR", str(tmp_path))
    client = embedding_lanes.index_client()
    assert isinstance(client, LocalIndexClient)
    assert embedding_lanes.index_backend() == embedding_lanes.INDEX_LOCAL


def test_which_index_answered_is_never_a_guess(monkeypatch, tmp_path):
    # `B61`'s rule, one layer down: the product may not be vague about which
    # store served a search.
    monkeypatch.setattr("src.constants.DATA_DIR", str(tmp_path))
    monkeypatch.setattr("src.chroma_client.get_chroma_client", lambda: object())
    embedding_lanes.index_client()
    first = embedding_lanes.index_backend()
    monkeypatch.setattr("src.chroma_client.get_chroma_client",
                        lambda: (_ for _ in ()).throw(RuntimeError("down")))
    embedding_lanes.index_client()
    assert embedding_lanes.index_backend() != first
    assert embedding_lanes.index_backend() in (
        embedding_lanes.INDEX_CHROMA, embedding_lanes.INDEX_LOCAL)


def test_the_legacy_migration_stays_chroma_only():
    """It backfills from a *legacy Chroma* collection, and the in-process index
    has none — it did not exist before the lanes did. Routing it through the
    fallback would have it hunt for a file that can never be there and swallow
    the exception, which is a slower way of doing nothing."""
    source = (_REPO / "src" / "embedding_lanes.py").read_text(encoding="utf-8")
    body = source[source.index("def migrate_legacy_collection"):]
    body = body[:body.index("\ndef ", 1)] if "\ndef " in body[1:] else body
    code = "\n".join(ln for ln in body.splitlines() if not ln.lstrip().startswith("#"))
    assert "get_chroma_client()" in code
    assert "index_client()" not in code


# ── the crossover is documented where an operator reads it ────────────────────


def test_the_operator_is_told_when_the_service_is_worth_running():
    """The row's `Verify` asks for the crossover documented with the number that
    justifies it. A claim that ChromaDB is unnecessary needs the scale at which
    that stops being true, or it is marketing."""
    env = (_REPO / ".env.example").read_text(encoding="utf-8")
    assert "10,000 memories" in env and "0.82 ms" in env
    assert "1,000,000 memories" in env, "the scale where the service wins must be named"
    assert "data/vectors" in env, "an operator needs to know what to delete"


def test_unnormalised_vectors_are_normalised_on_the_way_in(client):
    """Cosine similarity between unit vectors is a dot product, so vectors are
    normalised once at write time and every later query is one matrix multiply
    with no per-query division.

    The tests above all hand in unit vectors, so a mutation deleting the
    normalisation survived every one of them — the fixtures were doing the
    work the code was supposed to do."""
    col = client.get_or_create_collection("c")
    # The two must NOT be orthogonal, or magnitude cannot flip the order and the
    # fixture proves nothing — which is how the first version of this test let
    # the mutation through. `[3, 4, 0]` sits at cosine 0.6 from the query and is
    # five hundred units long; `[1, 0, 0]` is the exact direction and is one.
    # Unnormalised, the long one scores 300 against 1 and wins the wrong way.
    col.add(ids=["near", "far_but_long"], embeddings=[[1.0, 0.0, 0.0], [300.0, 400.0, 0.0]],
            documents=["N", "F"], metadatas=[{}] * 2)
    out = col.query(query_embeddings=[[5.0, 0.0, 0.0]], n_results=2, include=["distances"])
    assert out["ids"][0][0] == "near", "magnitude beat direction — vectors are not normalised"
    assert out["distances"][0][0] == pytest.approx(0.0, abs=1e-5), (
        "an unnormalised query vector also has to be scaled, or the distance is meaningless")
    assert out["distances"][0][1] == pytest.approx(0.4, abs=1e-5), (
        "cosine 0.6 must read as distance 0.4 whatever the vector's length")


def test_a_failed_write_cleans_up_after_itself(client, monkeypatch, tmp_path):
    # The index is written to a sibling and renamed. If the write throws, the
    # sibling has to go — otherwise a disk that is full or flaky accumulates a
    # temporary file per attempt, which is a slow leak nobody looks for.
    col = client.get_or_create_collection("c")
    col.add(ids=["a"], embeddings=_unit([1, 0, 0]), documents=["A"], metadatas=[{}])
    before = sorted(p.name for p in tmp_path.iterdir())

    def _boom(*a, **k):
        raise OSError("no space left on device")

    monkeypatch.setattr(np, "savez", _boom)
    col.add(ids=["b"], embeddings=_unit([0, 1, 0]), documents=["B"], metadatas=[{}])
    assert sorted(p.name for p in tmp_path.iterdir()) == before, (
        "a failed write left its temporary file behind")


class _FakeEmbedder:
    """Enough of an embedding client for `_create_lane`."""

    model = "fake-model"
    url = ""

    def get_sentence_embedding_dimension(self):
        return 3

    def encode(self, texts, normalize_embeddings=True):
        return np.array([[float(len(t)), 1.0, 0.0] for t in texts], dtype="float32")


def test_the_lane_builder_itself_works_with_no_service(monkeypatch, tmp_path):
    """The recipe, not the ingredient. `index_client` can be perfect and
    `build_embedding_lanes` still reach for `get_chroma_client` directly — a
    mutation doing exactly that survived every test of the chooser."""
    monkeypatch.setattr("src.chroma_client.get_chroma_client",
                        lambda: (_ for _ in ()).throw(RuntimeError("not reachable")))
    monkeypatch.setattr("src.constants.DATA_DIR", str(tmp_path))
    monkeypatch.setattr(embedding_lanes, "_build_custom_client", lambda: _FakeEmbedder())
    monkeypatch.setattr(embedding_lanes, "_build_fastembed_client",
                        lambda: (_ for _ in ()).throw(RuntimeError("no model here")))

    lanes = embedding_lanes.build_embedding_lanes("pantheon_memories_test")
    assert lanes, "no lane was built without ChromaDB — the fallback is not wired in"
    assert isinstance(lanes[0].collection, LocalCollection)
    assert embedding_lanes.index_backend() == embedding_lanes.INDEX_LOCAL

    # And the lane is usable, not merely constructed.
    lane = lanes[0]
    lane.collection.add(ids=["m1"], embeddings=lane.encode(["hello"]),
                        documents=["hello"], metadatas=[{}])
    assert lane.count() == 1
    assert lane.collection.query(query_embeddings=lane.encode(["hello"]),
                                 n_results=1)["ids"] == [["m1"]]
