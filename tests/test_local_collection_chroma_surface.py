# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B470` — the in-process index implements a subset of the surface its callers use.

`P13-21` replaced a ChromaDB *service* with `src/local_collection.py` so that a
downed index degrades to semantic search instead of keyword matching. It proved
that end to end for **memory**, and memory calls `add`, `get(ids=)`, `query`,
`delete` and `count`. Three other call sites do not:

* `src/tool_index.py` calls **`upsert`**, which did not exist. `AttributeError`
  failed every lane, `index_builtin_tools` raised, `get_tool_index()` returned
  `None`, and agent-mode tool selection fell back to `ToolIndex._KEYWORD_HINTS`
  — the exact `B61` degradation `P13-21` exists to remove, on the one consumer
  it did not measure.
* `src/rag_vector.py:search` reaches `LocalCollection.query` through
  `embedding_lanes.query_lanes`, which passes **`where=`** unconditionally.
  `TypeError` on every call, caught, and `search` returned
  `_keyword_search_fallback`. RAG semantic search has never once run on this
  index.
* `src/rag_vector.py:rename_owner` scans with **`get(where=)`** and writes with
  **`update(ids=, metadatas=)`**. Both raised, both were counted into
  `failed_count`, and a renamed account kept its documents under the old owner.

**Why the hole was invisible, and why this file derives instead of listing.**
`tests/test_the_brain_does_not_need_a_service.py` already asserts the surface —
`test_it_answers_the_five_methods_the_callers_use`, whose comment reads *"`memory_vector`
and `rag_vector` call exactly these"*. Five names, written down by hand, and the
sixth caller was never in the sentence. That is `Law 13`: a contract held in one
place and its implementation in another drift the moment somebody adds a call
site. So `test_every_call_site_in_the_tree_is_answerable` reads the *call sites*
and asks the real class — nothing here names a method, and a seventh consumer
added tomorrow is checked the day it lands.
"""

import ast
import inspect
import pathlib

import numpy as np
import pytest

from src.local_collection import LocalCollection, LocalIndexClient

_REPO = pathlib.Path(__file__).resolve().parents[1]

# The stdlib module, not a collection object. Without this the walk below picks
# up `collections.Counter()` and `collections.deque(maxlen=…)`.
_NOT_A_COLLECTION = {"collections"}


def _call_sites():
    """`(method, frozenset(kwargs), "file:line")` for every call in `src/` whose
    receiver is a collection — `lane.collection.query(...)`, `self.collection.get(...)`,
    `collection.update(...)`.

    Deliberately broader than the modules known to use the index today: the
    finding this file records is a caller nobody remembered.
    """
    for path in sorted(_REPO.glob("src/*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            receiver = node.func.value
            if isinstance(receiver, ast.Attribute):
                name = receiver.attr
            elif isinstance(receiver, ast.Name):
                name = receiver.id
            else:
                continue
            if name in _NOT_A_COLLECTION or "collection" not in name.lower():
                continue
            kwargs = frozenset(k.arg for k in node.keywords if k.arg)
            yield node.func.attr, kwargs, f"{path.name}:{node.lineno}"


def _unit(*rows):
    m = np.array(rows, dtype="float32")
    return (m / np.linalg.norm(m, axis=1, keepdims=True)).tolist()


@pytest.fixture
def client(tmp_path):
    return LocalIndexClient(str(tmp_path))


# ── the contract, derived ─────────────────────────────────────────────────────


def test_the_walk_finds_the_call_sites_it_is_supposed_to_find():
    # A derivation that quietly matches nothing would make every assertion
    # below vacuous — the failure mode of deriving instead of listing. This is
    # the floor, not the contract: the four call sites `B470` was found on.
    sites = {(m, kw) for m, kw, _where in _call_sites()}
    assert ("upsert", frozenset({"ids", "documents", "embeddings", "metadatas"})) in sites
    assert ("query", frozenset({"query_embeddings", "n_results", "include", "where"})) in sites
    assert ("get", frozenset({"where"})) in sites
    assert ("update", frozenset({"ids", "metadatas"})) in sites


def test_every_call_site_in_the_tree_is_answerable():
    """Every method the product calls on a collection exists here, and takes the
    keywords the call passes."""
    missing = []
    for method, kwargs, where in _call_sites():
        impl = getattr(LocalCollection, method, None)
        if impl is None or not callable(impl):
            missing.append(f"{where}: LocalCollection has no `{method}`")
            continue
        accepted = set(inspect.signature(impl).parameters)
        unknown = sorted(kwargs - accepted)
        if unknown:
            missing.append(
                f"{where}: LocalCollection.{method} does not accept {unknown}"
            )
    assert not missing, (
        "The in-process index does not answer what the product asks it "
        "(`B470`):\n  " + "\n  ".join(missing)
    )


# ── and the behaviour behind each name ────────────────────────────────────────


def test_upsert_replaces_rather_than_duplicating(client):
    # `tool_index.index_builtin_tools` upserts the whole registry on every
    # build. Appending instead would grow the index without bound and return
    # the same tool several times in one top-k.
    col = client.get_or_create_collection("c")
    col.upsert(ids=["a"], embeddings=_unit([1, 0, 0]), documents=["first"],
               metadatas=[{"tool_type": "builtin"}])
    col.upsert(ids=["a"], embeddings=_unit([0, 1, 0]), documents=["second"],
               metadatas=[{"tool_type": "builtin"}])
    assert col.count() == 1
    assert col.get(ids=["a"], include=["documents"])["documents"] == ["second"]


def test_get_filters_on_metadata(client):
    # `tool_index` prunes stale `builtin_*` rows by asking for exactly the
    # builtins. A `where` that was ignored would return MCP tools too and the
    # prune would delete them.
    col = client.get_or_create_collection("c")
    col.add(ids=["a", "b"], embeddings=_unit([1, 0, 0], [0, 1, 0]),
            documents=["A", "B"],
            metadatas=[{"tool_type": "builtin"}, {"tool_type": "mcp"}])
    assert col.get(where={"tool_type": "builtin"})["ids"] == ["a"]
    assert col.get(where={"tool_type": "mcp"})["ids"] == ["b"]
    assert col.get(where={"tool_type": "nothing"})["ids"] == []


def test_query_filters_before_the_top_k_and_not_after(client):
    """The bug a `where` applied to the result window would have.

    Five documents, one of them the owner's, and the owner's is the *worst*
    match. Ask for the owner's nearest 2: filtering the global top-2 returns
    nothing, filtering first returns the one document that exists.
    """
    col = client.get_or_create_collection("c")
    col.add(
        ids=["n1", "n2", "n3", "n4", "mine"],
        embeddings=_unit([1, 0, 0], [0.99, 0.1, 0], [0.98, 0.2, 0], [0.97, 0.3, 0], [0, 0, 1]),
        documents=["n1", "n2", "n3", "n4", "mine"],
        metadatas=[{"owner": "them"}] * 4 + [{"owner": "me"}],
    )
    out = col.query(query_embeddings=[[1, 0, 0]], n_results=2,
                    where={"owner": "me"}, include=["documents", "distances"])
    assert out["ids"][0] == ["mine"], "a `where` applied after the top-k returns nothing here"
    assert out["documents"][0] == ["mine"]


def test_query_without_a_where_is_unchanged(client):
    col = client.get_or_create_collection("c")
    col.add(ids=["a", "b"], embeddings=_unit([1, 0, 0], [0, 1, 0]),
            documents=["A", "B"], metadatas=[{}, {}])
    assert col.query(query_embeddings=[[1, 0, 0]], n_results=2)["ids"][0] == ["a", "b"]


def test_a_where_that_matches_nothing_is_an_empty_result_not_an_error(client):
    col = client.get_or_create_collection("c")
    col.add(ids=["a"], embeddings=_unit([1, 0, 0]), documents=["A"], metadatas=[{"owner": "me"}])
    out = col.query(query_embeddings=[[1, 0, 0]], n_results=5, where={"owner": "nobody"})
    assert out["ids"] == [[]] and out["distances"] == [[]]


@pytest.mark.parametrize("operator_form", [{"owner": {"$eq": "me"}}, {"owner": ["me"]}])
def test_an_operator_where_raises_instead_of_matching_nothing(client, operator_form):
    # Chroma's `$eq` / `$and` forms are not implemented. Treating one as a flat
    # equality silently matches nothing — which, on the `get` path, means
    # `tool_index` prunes every builtin it holds. Refusing is the safe answer.
    col = client.get_or_create_collection("c")
    col.add(ids=["a"], embeddings=_unit([1, 0, 0]), documents=["A"], metadatas=[{"owner": "me"}])
    with pytest.raises(ValueError):
        col.get(where=operator_form)
    with pytest.raises(ValueError):
        col.query(query_embeddings=[[1, 0, 0]], n_results=1, where=operator_form)


def test_update_rewrites_metadata_without_touching_the_vector(client):
    # `rag_vector.rename_owner`. Re-embedding a corpus to change an owner
    # string would be a rebuild, not a rename.
    col = client.get_or_create_collection("c")
    col.add(ids=["a"], embeddings=_unit([1, 0, 0]), documents=["A"],
            metadatas=[{"owner": "old", "source": "/x"}])
    before = col.query(query_embeddings=[[1, 0, 0]], n_results=1, include=["distances"])
    col.update(ids=["a"], metadatas=[{"owner": "new", "source": "/x"}])
    after = col.query(query_embeddings=[[1, 0, 0]], n_results=1, include=["distances"])
    assert col.get(ids=["a"], include=["metadatas"])["metadatas"] == [{"owner": "new", "source": "/x"}]
    assert col.get(ids=["a"], include=["documents"])["documents"] == ["A"]
    assert after["distances"] == before["distances"]


def test_update_skips_an_id_it_does_not_hold(client):
    col = client.get_or_create_collection("c")
    col.add(ids=["a"], embeddings=_unit([1, 0, 0]), documents=["A"], metadatas=[{"owner": "old"}])
    col.update(ids=["a", "ghost"], metadatas=[{"owner": "new"}, {"owner": "new"}])
    assert col.get()["ids"] == ["a"]


def test_update_survives_a_reopen(client, tmp_path):
    col = client.get_or_create_collection("c")
    col.add(ids=["a"], embeddings=_unit([1, 0, 0]), documents=["A"], metadatas=[{"owner": "old"}])
    col.update(ids=["a"], metadatas=[{"owner": "new"}])
    reopened = LocalIndexClient(str(tmp_path)).get_collection("c")
    assert reopened.get(ids=["a"], include=["metadatas"])["metadatas"] == [{"owner": "new"}]
