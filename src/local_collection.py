# SPDX-License-Identifier: AGPL-3.0-or-later
"""
local_collection.py

A vector index that is arithmetic rather than infrastructure.

`P13-21`. Semantic memory search runs against a ChromaDB **service** — a
separate process, probed with a 2s TCP connect — so a working install degrades
to lexical retrieval whenever that process is not running. `B61` made that
visible; this makes it unnecessary.

**The embedding model was never the service.** `fastembed` is local ONNX, ships
in `requirements.txt`, and reaches no network once cached. Only the *index* was
remote — and for a personal Brain an index is a matrix multiply:

    memories      brute-force cosine, numpy      index size
        100                    0.13 ms              0.2 MB
      1,000                    0.18 ms              1.5 MB
     10,000                    0.82 ms             15.4 MB
    100,000                   12.29 ms            153.6 MB
  1,000,000                  135.29 ms           1536.0 MB

Ten thousand memories is years of daily use and costs under a millisecond a
query with nothing running. **The vector database earns its place at a scale no
single-operator deployment reaches**, and below that it is a second process that
can fail, a degraded path, and a class of bug.

**`Law 1`: ChromaDB is not removed.** It stays for deployments that want it and
for `P0-05`. What changes is that it stops being the *only* way to get an index,
so an unreachable service degrades to semantic search rather than to keyword
matching.

**This is a cache, not a store.** Every vector here is derivable from
`memory.json`, so a missing, truncated or unreadable file is rebuilt rather than
mourned — which is why nothing below tries hard to preserve it, and why a schema
change is a delete rather than a migration. `D-2026-08-26-08`'s "data is
disposable" applies with unusual force to a file whose entire content is a
function of another file.

The surface is Chroma's, deliberately and only as far as `memory_vector` and
`rag_vector` actually use it: `add`, `get`, `query`, `delete`, `count`. Matching
a subset of somebody's API is how one index becomes two implementations behind
one interface instead of two code paths (`Law 13`).
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

# Vectors are float32 on disk. float64 doubles the file for precision no cosine
# similarity survives to use.
_DTYPE = "float32"


class LocalCollection:
    """A Chroma-shaped collection held in memory and mirrored to one file."""

    def __init__(self, path: str, name: str, metadata: Optional[Dict[str, Any]] = None):
        self.name = name
        self.metadata = dict(metadata or {})
        self._path = path
        self._lock = threading.RLock()
        self._ids: List[str] = []
        self._docs: List[str] = []
        self._metas: List[Dict[str, Any]] = []
        self._vectors = None  # numpy array, or None while empty
        self._load()

    # ── persistence ───────────────────────────────────────────────────────────

    def _load(self) -> None:
        """Read the cache, or start empty. Never raise over a cache."""
        try:
            import numpy as np
        except ImportError:  # pragma: no cover - numpy is a hard dependency
            return
        if not os.path.exists(self._path):
            return
        try:
            with np.load(self._path, allow_pickle=False) as data:
                vectors = data["vectors"]
                rows = json.loads(str(data["rows"].item()))
            # `rows["ids"]` and not `rows`: `len()` on the payload counts its
            # *keys*. The first version of this line compared four keys against
            # N vectors and passed only when N happened to be four — it was
            # discarding the whole index on every restart and rebuilding it,
            # silently, because a cache miss is not an error here.
            if len(rows["ids"]) != len(vectors):
                raise ValueError(f"{len(rows['ids'])} ids against {len(vectors)} vectors")
        except Exception as e:
            # A corrupt cache is not an error, it is a cache miss. Every vector
            # in it is derivable from memory.json.
            logger.info("Rebuilding local vector index (%s): %s", self.name, e)
            return
        self._ids = list(rows["ids"])
        self._docs = list(rows["docs"])
        self._metas = list(rows["metas"])
        self._vectors = vectors
        # The lane's embedding fingerprint lives here, because
        # `_get_or_reset_collection` reads `collection.metadata` to decide
        # whether the model changed. Without persisting it, every restart would
        # look like a model change and rebuild an index that was fine.
        if isinstance(rows.get("metadata"), dict):
            self.metadata = rows["metadata"]

    def _persist(self) -> None:
        """Write the cache atomically, or carry on without one."""
        try:
            import numpy as np
        except ImportError:  # pragma: no cover
            return
        try:
            os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
            payload = json.dumps({"ids": self._ids, "docs": self._docs,
                                  "metas": self._metas, "metadata": self.metadata})
            vectors = (self._vectors if self._vectors is not None
                       else np.zeros((0, 0), dtype=_DTYPE))
            # Written to a sibling and renamed: a half-written index that loads
            # is worse than one that does not, because it would answer queries
            # with a subset and nothing would say so.
            fd, tmp = tempfile.mkstemp(dir=os.path.dirname(self._path) or ".", suffix=".npz")
            os.close(fd)
            try:
                # `savez` appends `.npz` unless the name already ends in it,
                # which is why the suffix above is `.npz` and not `.tmp` — the
                # first version left a zero-byte `.tmp` behind on every write.
                np.savez(tmp, vectors=vectors, rows=np.array(payload))
                os.replace(tmp, self._path)
            except Exception:
                try:
                    os.remove(tmp)
                # The write already failed and that is what gets reported below.
                # A cleanup that also fails must not replace the real error with
                # its own — the operator needs the disk-full, not the unlink.
                except OSError:
                    pass
                raise
        except Exception as e:
            logger.warning("Could not persist local vector index (%s): %s", self.name, e)

    # ── the Chroma surface ────────────────────────────────────────────────────

    def count(self) -> int:
        with self._lock:
            return len(self._ids)

    def add(self, ids: Sequence[str], embeddings: Sequence[Sequence[float]],
            documents: Optional[Sequence[str]] = None,
            metadatas: Optional[Sequence[Dict[str, Any]]] = None) -> None:
        import numpy as np

        with self._lock:
            docs = list(documents or [""] * len(ids))
            metas = list(metadatas or [{}] * len(ids))
            incoming = np.asarray(embeddings, dtype=_DTYPE)
            if incoming.ndim == 1:
                incoming = incoming.reshape(1, -1)
            # Normalised once, on the way in. Cosine similarity between unit
            # vectors is a dot product, so every later query is one matrix
            # multiply with no per-query division.
            norms = np.linalg.norm(incoming, axis=1, keepdims=True)
            incoming = incoming / np.where(norms == 0, 1.0, norms)

            if self._vectors is not None and self._vectors.size and \
                    self._vectors.shape[1] != incoming.shape[1]:
                # A changed embedding model. Chroma refuses; this rebuilds,
                # because the cache is derivable and refusing would strand the
                # operator with an index they cannot use and cannot replace.
                logger.info("Embedding dimension changed for %s (%d -> %d); resetting index",
                            self.name, self._vectors.shape[1], incoming.shape[1])
                self._ids, self._docs, self._metas, self._vectors = [], [], [], None

            for n, mid in enumerate(ids):
                if mid in self._ids:
                    at = self._ids.index(mid)
                    self._docs[at] = docs[n]
                    self._metas[at] = metas[n]
                    self._vectors[at] = incoming[n]
                    continue
                self._ids.append(mid)
                self._docs.append(docs[n])
                self._metas.append(metas[n])
                self._vectors = (incoming[n:n + 1] if self._vectors is None
                                 else np.vstack([self._vectors, incoming[n:n + 1]]))
            self._persist()

    def get(self, ids: Optional[Sequence[str]] = None,
            include: Optional[Sequence[str]] = None) -> Dict[str, Any]:
        with self._lock:
            wanted = list(ids) if ids is not None else list(self._ids)
            rows = [(self._ids.index(m), m) for m in wanted if m in self._ids]
            out: Dict[str, Any] = {"ids": [m for _at, m in rows]}
            fields = set(include or ())
            if "documents" in fields:
                out["documents"] = [self._docs[at] for at, _m in rows]
            if "metadatas" in fields:
                out["metadatas"] = [self._metas[at] for at, _m in rows]
            if "embeddings" in fields and self._vectors is not None:
                out["embeddings"] = [self._vectors[at].tolist() for at, _m in rows]
            return out

    def delete(self, ids: Sequence[str]) -> None:
        import numpy as np

        with self._lock:
            keep = [n for n, mid in enumerate(self._ids) if mid not in set(ids)]
            if len(keep) == len(self._ids):
                return
            self._ids = [self._ids[n] for n in keep]
            self._docs = [self._docs[n] for n in keep]
            self._metas = [self._metas[n] for n in keep]
            self._vectors = self._vectors[keep] if (self._vectors is not None and keep) else None
            self._persist()

    def query(self, query_embeddings: Sequence[Sequence[float]], n_results: int = 8,
              include: Optional[Sequence[str]] = None) -> Dict[str, Any]:
        """Nearest neighbours, as Chroma returns them: distance = 1 - cosine."""
        import numpy as np

        with self._lock:
            if self._vectors is None or not len(self._ids):
                return {"ids": [[]], "distances": [[]], "documents": [[]], "metadatas": [[]]}
            q = np.asarray(query_embeddings, dtype=_DTYPE)
            if q.ndim == 1:
                q = q.reshape(1, -1)
            norms = np.linalg.norm(q, axis=1, keepdims=True)
            q = q / np.where(norms == 0, 1.0, norms)

            similarity = q @ self._vectors.T
            k = max(0, min(int(n_results), len(self._ids)))
            ids, dists, docs, metas = [], [], [], []
            for row in similarity:
                # `argpartition` is O(n) against `argsort`'s O(n log n), which
                # matters only at the scale where this file stops being the
                # right answer — but the top-k still has to be ordered.
                top = np.argpartition(-row, k - 1)[:k] if k < len(row) else np.arange(len(row))
                top = top[np.argsort(-row[top])]
                ids.append([self._ids[i] for i in top])
                dists.append([float(1.0 - row[i]) for i in top])
                docs.append([self._docs[i] for i in top])
                metas.append([self._metas[i] for i in top])
            out = {"ids": ids, "distances": dists}
            fields = set(include or ())
            if "documents" in fields or not fields:
                out["documents"] = docs
            if "metadatas" in fields or not fields:
                out["metadatas"] = metas
            return out


class LocalIndexClient:
    """A Chroma-client shape over a directory of `LocalCollection` files."""

    def __init__(self, directory: str):
        self._dir = directory
        self._open: Dict[str, LocalCollection] = {}
        self._lock = threading.RLock()

    def get_collection(self, name: str) -> LocalCollection:
        """Chroma raises when a collection does not exist, and callers depend on
        that: `_get_or_reset_collection` uses the exception as its "first run"
        branch. Returning an empty collection instead would make every start
        look like a fingerprint match against nothing."""
        with self._lock:
            if name in self._open:
                return self._open[name]
            if not os.path.exists(self._file_for(name)):
                raise KeyError(f"collection {name!r} does not exist")
            return self.get_or_create_collection(name)

    def _file_for(self, name: str) -> str:
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in name)
        return os.path.join(self._dir, f"{safe}.npz")

    def get_or_create_collection(self, name: str, metadata: Optional[Dict[str, Any]] = None,
                                 **_kwargs) -> LocalCollection:
        with self._lock:
            if name not in self._open:
                self._open[name] = LocalCollection(self._file_for(name), name, metadata)
            elif metadata:
                self._open[name].metadata = dict(metadata)
            return self._open[name]

    # `delete_collection` is what a lane rebuild reaches for when the embedding
    # fingerprint changes. Deleting a derivable cache needs no ceremony.
    def delete_collection(self, name: str) -> None:
        with self._lock:
            self._open.pop(name, None)
            try:
                os.remove(self._file_for(name))
            # Deleting a cache that is already gone is the outcome we wanted.
            # There is nothing to report and nothing a caller could do.
            except FileNotFoundError:
                pass
            except OSError as e:
                logger.warning("Could not delete local collection %s: %s", name, e)
