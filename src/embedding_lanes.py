# SPDX-License-Identifier: AGPL-3.0-or-later
"""
embedding_lanes.py

Helpers for keeping FastEmbed fallback vectors separate from user-configured
embedding vectors. ChromaDB fixes a collection's dimension on first insert, so
different embedding models must never share one collection.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import logging
import os
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

logger = logging.getLogger(__name__)

LANE_FASTEMBED = "fastembed"
LANE_CUSTOM = "custom"


@dataclass
class EmbeddingLane:
    name: str
    client: Any
    collection: Any
    collection_name: str
    model: str
    url: str
    dimension: int
    fingerprint: str

    @property
    def healthy(self) -> bool:
        return self.collection is not None and self.client is not None

    def encode(self, texts: Sequence[str]) -> List[List[float]]:
        vecs = self.client.encode(list(texts), normalize_embeddings=True)
        return vecs.tolist() if hasattr(vecs, "tolist") else [list(v) for v in vecs]

    def count(self) -> int:
        try:
            return int(self.collection.count())
        except Exception:
            return 0

    def stats(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "collection": self.collection_name,
            "model": self.model,
            "url": self.url,
            "dimension": self.dimension,
            "fingerprint": self.fingerprint,
            "count": self.count(),
            "healthy": self.healthy,
        }


def reset_embedding_lane_state() -> None:
    """Reset process-local embedding lane state after endpoint config changes."""
    try:
        from src.embeddings import reset_http_embed_state
        reset_http_embed_state()
    except Exception:
        pass


def collection_name(base_name: str, lane_name: str) -> str:
    return f"{base_name}_{lane_name}"


def _fingerprint(lane_name: str, url: str, model: str, dimension: int) -> str:
    raw = f"{lane_name}\n{url}\n{model}\n{dimension}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _metadata(lane_name: str, url: str, model: str, dimension: int, fingerprint: str) -> Dict[str, Any]:
    return {
        "hnsw:space": "cosine",
        "embedding_lane": lane_name,
        "embedding_url": url,
        "embedding_model": model,
        "embedding_dimension": dimension,
        "embedding_fingerprint": fingerprint,
    }


def _load_custom_endpoint() -> Dict[str, str]:
    try:
        from src.embeddings import _load_persisted_endpoint
        persisted = _load_persisted_endpoint()
    except Exception:
        persisted = {}

    url = persisted.get("url") or os.environ.get("EMBEDDING_URL", "")
    if not url:
        return {}

    model = persisted.get("model") or os.environ.get("EMBEDDING_MODEL", "")
    api_key = persisted.get("api_key") or os.environ.get("EMBEDDING_API_KEY", "")
    if persisted.get("api_key"):
        try:
            from src.secret_storage import decrypt
            api_key = decrypt(api_key)
        except Exception:
            logger.warning("Could not decrypt saved embedding endpoint API key")
            api_key = ""

    return {"url": url, "model": model, "api_key": api_key}


def fastembed_model_is_cached() -> bool:
    """Is the ONNX model already on disk? Then using it costs no network.

    Checked by looking for the file rather than by asking fastembed, because
    fastembed's answer to "is it there?" is to fetch it — which is the thing
    being decided.
    """
    import glob

    from src.constants import FASTEMBED_CACHE_DIR

    try:
        return bool(glob.glob(os.path.join(FASTEMBED_CACHE_DIR, "**", "*.onnx"), recursive=True))
    except OSError:
        return False


def model_download_allowed() -> bool:
    """Has someone said Pantheon may fetch a model? Ships False (`Law 16`).

    Note the default is falsy, which is what makes the env fallback below
    reachable — see `H06`/`B20` for the numeric-default case where the same
    shape is dead code.
    """
    try:
        from src.settings import get_setting

        if bool(get_setting("allow_model_download", False)):
            return True
    except Exception:
        pass
    return (os.environ.get("PANTHEON_ALLOW_MODEL_DOWNLOAD") or "").strip().lower() in (
        "1", "true", "yes",
    )


class ModelDownloadNotPermitted(RuntimeError):
    """Constructing this client would fetch a model, and nobody asked for that."""


def _build_fastembed_client():
    """Build the local ONNX embedding client, downloading the model if needed.

    The `Law 16` gate lives **here**, at the one function that actually reaches
    the network, and not in `build_embedding_lanes` where the lane list is
    assembled. That distinction matters and cost a red suite to learn: the lane
    assembler is exercised by fourteen tests that stub this function to check
    dimension separation, legacy backfill and dual-write. Gating there refused
    lanes in tests that were never going to download anything, because a stub
    does not download. Gating here means the rule binds exactly where the cost
    is, and a caller holding a real client is unaffected.
    """
    from src.embeddings import FastEmbedClient

    if not fastembed_model_is_cached() and not model_download_allowed():
        raise ModelDownloadNotPermitted(
            "the local embedding model is not downloaded, and Pantheon does not fetch "
            "models on its own. Point EMBEDDING_URL at a local embedding server (Ollama "
            "serves one), or set allow_model_download to fetch ~90MB from HuggingFace once."
        )

    client = FastEmbedClient()
    client.get_sentence_embedding_dimension()
    return client


def _build_custom_client():
    from src.embeddings import EmbeddingClient, get_embedding_client

    client = get_embedding_client()
    if isinstance(client, EmbeddingClient):
        return client
    raise RuntimeError("HTTP embedding lane unavailable")


def _encode_with_client(client: Any, texts: Sequence[str]) -> List[List[float]]:
    vecs = client.encode(list(texts), normalize_embeddings=True)
    return vecs.tolist() if hasattr(vecs, "tolist") else [list(v) for v in vecs]


def _get_or_reset_collection(chroma_client, name: str, metadata: Dict[str, Any], client: Any):
    try:
        collection = chroma_client.get_collection(name)
    except Exception:
        return chroma_client.get_or_create_collection(name=name, metadata=metadata)

    current = collection.metadata or {}
    if not (
        current.get("embedding_fingerprint") not in (None, metadata["embedding_fingerprint"])
        or current.get("embedding_dimension") not in (None, metadata["embedding_dimension"])
        or current.get("embedding_lane") not in (None, metadata["embedding_lane"])
    ):
        return collection

    logger.info(
        "Recreating Chroma collection %s for embedding lane change (%s -> %s)",
        name,
        current.get("embedding_fingerprint"),
        metadata["embedding_fingerprint"],
    )
    preserved = {"ids": [], "documents": [], "metadatas": [], "embeddings": []}
    try:
        preserved = collection.get(include=["documents", "metadatas", "embeddings"]) or preserved
    except Exception as e:
        raise RuntimeError(f"Could not preserve documents before resetting {name}: {e}") from e

    ids = preserved.get("ids") or []
    docs = preserved.get("documents") or []
    metas = preserved.get("metadatas") or []
    prepared_batches = []
    if ids and docs:
        try:
            for start in range(0, len(ids), 100):
                batch_ids = ids[start:start + 100]
                batch_docs = docs[start:start + 100]
                batch_metas = metas[start:start + 100]
                if len(batch_metas) < len(batch_ids):
                    batch_metas += [{}] * (len(batch_ids) - len(batch_metas))
                prepared_batches.append((
                    batch_ids,
                    batch_docs,
                    batch_metas,
                    _encode_with_client(client, batch_docs),
                ))
        except Exception as e:
            raise RuntimeError(f"Could not re-embed preserved rows for {name}: {e}") from e

    chroma_client.delete_collection(name)
    collection = chroma_client.get_or_create_collection(name=name, metadata=metadata)

    try:
        for batch_ids, batch_docs, batch_metas, embeddings in prepared_batches:
            collection.add(
                ids=batch_ids,
                documents=batch_docs,
                metadatas=batch_metas,
                embeddings=embeddings,
            )
    except Exception as e:
        logger.warning("Could not write reset collection %s; restoring previous rows: %s", name, e)
        try:
            chroma_client.delete_collection(name)
            restored = chroma_client.get_or_create_collection(name=name, metadata=current)
            # chromadb returns embeddings as a numpy ndarray, whose truth value
            # is ambiguous — `preserved.get("embeddings") or []` and a bare
            # `if ... and old_embeddings:` both raise ValueError, which aborts
            # the restore and loses the rows the reset was supposed to keep.
            # Use explicit None/len checks instead.
            old_embeddings = preserved.get("embeddings")
            if old_embeddings is None:
                old_embeddings = []
            if ids and docs and len(old_embeddings):
                for start in range(0, len(ids), 100):
                    batch_ids = ids[start:start + 100]
                    batch_docs = docs[start:start + 100]
                    batch_metas = metas[start:start + 100]
                    batch_embeddings = old_embeddings[start:start + 100]
                    if hasattr(batch_embeddings, "tolist"):
                        batch_embeddings = batch_embeddings.tolist()
                    if len(batch_metas) < len(batch_ids):
                        batch_metas += [{}] * (len(batch_ids) - len(batch_metas))
                    restored.add(
                        ids=batch_ids,
                        documents=batch_docs,
                        metadatas=batch_metas,
                        embeddings=batch_embeddings,
                    )
        except Exception as restore_error:
            logger.warning("Could not restore previous collection %s: %s", name, restore_error)
        raise RuntimeError(f"Could not write reset collection {name}: {e}") from e
    if prepared_batches:
        logger.info("Re-embedded %s rows after resetting %s", len(ids), name)

    return collection


def _create_lane(chroma_client, base_name: str, lane_name: str, client: Any) -> EmbeddingLane:
    dimension = int(client.get_sentence_embedding_dimension())
    model = getattr(client, "model", "")
    url = getattr(client, "url", "")
    fp = _fingerprint(lane_name, url, model, dimension)
    name = collection_name(base_name, lane_name)
    metadata = _metadata(lane_name, url, model, dimension, fp)
    collection = _get_or_reset_collection(chroma_client, name, metadata, client)
    return EmbeddingLane(
        name=lane_name,
        client=client,
        collection=collection,
        collection_name=name,
        model=model,
        url=url,
        dimension=dimension,
        fingerprint=fp,
    )


# Which index backed the lanes this process built. Read by diagnostics and by
# `B61`'s reporting, set by `index_client()` below. A module-level note rather
# than a return value because `build_embedding_lanes` already returns the thing
# callers want and widening it would touch every caller for a label.
_INDEX_BACKEND = "none"

INDEX_CHROMA = "chromadb"
INDEX_LOCAL = "in-process"


def index_backend() -> str:
    """`chromadb`, `in-process`, or `none`. Which store answered."""
    return _INDEX_BACKEND


def index_client():
    """The vector index: ChromaDB when it is reachable, otherwise in-process.

    `P13-21`. The embedding model was never the service — `fastembed` is local
    ONNX and ships in `requirements.txt`. Only the *index* was remote, and for a
    personal Brain an index is a matrix multiply: brute-force cosine is 0.82ms
    over ten thousand memories, which is years of daily use.

    **`Law 1`: ChromaDB is not removed and is still tried first.** It stays for
    deployments that want it and for `P0-05`. What changes is that an
    unreachable service now degrades to *semantic search* rather than to
    keyword matching — `recall@5 1.00` against `0.77` on the golden set.

    **The two deployments this actually rescues are the ones nobody was
    watching** (`B64`): `launch-windows.ps1` mentions chroma zero times, and
    `start-macos.sh` swaps in a heavier package to avoid a failure mode
    `src/chroma_client.py` cannot have, since `HttpClient` is the only client it
    ever builds. Docker — the maintainer's own deployment — is the one that
    already worked, which is exactly why the gap stayed invisible.
    """
    global _INDEX_BACKEND
    from src.chroma_client import get_chroma_client

    try:
        client = get_chroma_client()
        _INDEX_BACKEND = INDEX_CHROMA
        return client
    except Exception as e:
        from src.constants import DATA_DIR
        from src.local_collection import LocalIndexClient

        # `info` and not `warning`: on two of three shipped deployments there is
        # no ChromaDB to reach and never was, so this is the normal path rather
        # than a fault. It still says which store answered, because `B61` is
        # about never letting that be a guess.
        logger.info("ChromaDB unreachable (%s); using the in-process vector index", e)
        _INDEX_BACKEND = INDEX_LOCAL
        return LocalIndexClient(os.path.join(DATA_DIR, "vectors"))


def build_embedding_lanes(base_name: str) -> List[EmbeddingLane]:
    """Return healthy lanes in retrieval preference order: custom, fastembed."""
    chroma_client = index_client()
    lanes: List[EmbeddingLane] = []

    try:
        custom = _build_custom_client()
        if custom is not None:
            lanes.append(_create_lane(chroma_client, base_name, LANE_CUSTOM, custom))
    except Exception as e:
        logger.warning("Custom embedding lane unavailable for %s: %s", base_name, e)

    # `_build_fastembed_client` refuses rather than downloading when the model is
    # absent and nobody has permitted a fetch (`P16-05`). Until 2026-09-01 it
    # simply fetched — ~90MB of ONNX from HuggingFace, on the **first chat
    # message of a fresh install**, with the local HTTP lane above already
    # answering. `fastembed` is a hard requirement so the path was never
    # skipped, and this lane is documented as the "zero config fallback": a
    # fallback that always runs is not a fallback.
    try:
        fastembed = _build_fastembed_client()
        lanes.append(_create_lane(chroma_client, base_name, LANE_FASTEMBED, fastembed))
    except ModelDownloadNotPermitted as e:
        # Not a failure — a choice. Memory and RAG degrade to unavailable, which
        # `memory_vector` and `rag_vector` already handle, and the log says which
        # of the two remedies to apply.
        (logger.warning if not lanes else logger.info)(
            "No fastembed lane for %s: %s", base_name, e
        )
    except Exception as e:
        logger.warning("FastEmbed lane unavailable for %s: %s", base_name, e)

    return lanes


def migrate_legacy_collection(base_name: str, lanes: Sequence[EmbeddingLane]) -> None:
    """Backfill empty lanes from a legacy unsuffixed collection, if present."""
    if not lanes:
        return

    try:
        # `get_chroma_client` and deliberately not `index_client` (`P13-21`).
        # This backfills from a *legacy Chroma* collection, and the in-process
        # index has no such thing to migrate from — it did not exist before the
        # lanes did. Routing it through the fallback would have it hunt for an
        # unsuffixed local file that can never be there, and swallow the
        # exception, which is a slower way of doing nothing.
        from src.chroma_client import get_chroma_client

        chroma_client = get_chroma_client()
        legacy = chroma_client.get_collection(base_name)
        data = legacy.get(include=["documents", "metadatas"])
    except Exception:
        return

    ids = data.get("ids") or []
    docs = data.get("documents") or []
    metas = data.get("metadatas") or []
    if not ids or not docs:
        return

    for lane in lanes:
        try:
            existing = lane.collection.get(ids=ids)
            existing_ids = set(existing.get("ids") or [])
        except Exception:
            existing_ids = set()
        all_metas = list(metas or [])
        if len(all_metas) < len(ids):
            all_metas += [{}] * (len(ids) - len(all_metas))
        missing = [
            (row_id, doc, meta)
            for row_id, doc, meta in zip(ids, docs, all_metas)
            if row_id not in existing_ids
        ]
        if not missing:
            continue

        for start in range(0, len(missing), 100):
            batch = missing[start:start + 100]
            batch_ids = [row_id for row_id, _doc, _meta in batch]
            batch_docs = [doc for _row_id, doc, _meta in batch]
            batch_metas = [meta or {} for _row_id, _doc, meta in batch]
            if len(batch_metas) < len(batch_ids):
                batch_metas += [{}] * (len(batch_ids) - len(batch_metas))
            try:
                embeddings = lane.encode(batch_docs)
                lane.collection.add(
                    ids=batch_ids,
                    documents=batch_docs,
                    metadatas=batch_metas,
                    embeddings=embeddings,
                )
            except Exception as e:
                logger.warning(
                    "Could not backfill %s lane from legacy collection %s: %s",
                    lane.name,
                    base_name,
                    e,
                )
                break
        else:
            logger.info("Backfilled %s %s lane rows from legacy collection %s", len(missing), lane.name, base_name)


def lane_count(lanes: Sequence[EmbeddingLane]) -> int:
    return max((lane.count() for lane in lanes), default=0)


def dedupe_results(results: Iterable[Dict[str, Any]], id_key: str = "id", limit: Optional[int] = None) -> List[Dict[str, Any]]:
    seen = set()
    out: List[Dict[str, Any]] = []
    for row in results:
        row_id = row.get(id_key)
        if not row_id or row_id in seen:
            continue
        seen.add(row_id)
        out.append(row)
        if limit is not None and len(out) >= limit:
            break
    return out


def query_lanes(
    lanes: Sequence[EmbeddingLane],
    query: str,
    n_results: Callable[[EmbeddingLane], int],
    include: Sequence[str],
    where: Optional[Dict[str, Any]] = None,
    raise_if_all_failed: bool = False,
) -> List[tuple[EmbeddingLane, Dict[str, Any]]]:
    out: List[tuple[EmbeddingLane, Dict[str, Any]]] = []
    attempted = 0
    failures: List[str] = []
    for lane in lanes:
        try:
            count = lane.count()
            if count == 0:
                continue
            attempted += 1
            n = min(n_results(lane), count)
            if n <= 0:
                continue
            results = lane.collection.query(
                query_embeddings=lane.encode([query]),
                n_results=n,
                where=where,
                include=list(include),
            )
            out.append((lane, results))
        except Exception as e:
            failures.append(f"{lane.name}: {e}")
            logger.warning("%s lane query failed for %s: %s", lane.name, lane.collection_name, e)
    if raise_if_all_failed and attempted and not out and failures:
        raise RuntimeError("; ".join(failures))
    return out
