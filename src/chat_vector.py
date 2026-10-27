# SPDX-License-Identifier: AGPL-3.0-or-later
"""A person's chats, searchable by meaning — the vector half of `P9-15c`.

The keyword half ships: FTS5 and `LIKE` in `src/session_search.py`. The row's
corrected premise is that **no Chroma collection indexed chat messages**, so a
search that shares no word with the message it wants found nothing. This is
that collection, built the way `src/memory_vector.py` builds memory's — the
same lanes (`embedding_lanes.build_embedding_lanes`: the configured embedding
server first, the local FastEmbed model second), on ChromaDB when it answers
and the in-process index when it does not (`embedding_lanes.index_client`).

THREE THINGS IT IS CAREFUL ABOUT.

**It never fetches a model and never blocks a chat.** The lanes are the ones
memory and RAG already use, so `Law 16`'s download gate holds here as there
(`ensure_fastembed_download_permitted`): with no embedding server set up and no
local model on disk there are no lanes, `search` answers `None`, and
`session_search` searches by keyword and says why (`status`). Indexing happens
on a worker thread fed by `index_soon`, which only enqueues an id.

**It keeps no message text.** A row is the message's id, its vector and
`{owner, session_id}` — never the words, so a chat a person deletes does not
live on in the index's file. Every hit is read back from `chat_messages`
through the keyword search's own filters (owner, archived, roles) before
anyone sees it, so a vector whose message is gone, or someone else's, returns
nothing.

**It catches up on its own.** `backfill` walks every message and embeds the
ones the index does not hold — when the lanes first come up, and again
whenever they come back. It is idempotent, so a restart halfway resumes where
the index stands rather than from a cursor that can go stale.

**It runs where the app runs.** `start()` — called once by `app.py` — is what
switches it on; the lanes are built, retried and backfilled on its own worker
thread, never on a request's. A process that never calls it (a script, a test
that persists a message) gets the keyword search exactly as before (`Law 1`).
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

COLLECTION_NAME = "pantheon_chat_messages"

#: The roles a person searches — what `session_search.SEARCH_ROLES` reads.
SEARCH_ROLES = ("user", "assistant")

#: Characters of a message that are embedded. A chat message can be pages
#: long; its meaning is mostly in its start, and a bounded input keeps one
#: long paste from costing a batch.
EMBED_CHARS = 1000

#: Cosine similarity below which a nearest neighbour is not a match. A vector
#: search always answers with its nearest rows, related or not; this keeps a
#: query from pulling in every chat that merely exists.
MEANING_FLOOR = 0.3

#: Messages embedded per batch, and the pause between batches, so a backfill
#: over a long history shares the machine with the person using it.
_BATCH = 32
_BATCH_PAUSE_SECONDS = 0.05

#: How long a failed lane build is believed before it is tried again.
_RETRY_SECONDS = 60.0

#: What the person reads when the search could not look by meaning, and what
#: they can do about it (`Law 15`).
KEYWORD_ONLY_SENTENCE = (
    "Searched by keyword only: no embedding model is set up, so nothing can be "
    "found by meaning. An admin can point Pantheon at a local embedding server "
    "in Settings → Embeddings.")


#: The same, in the seconds after a start before the lanes have been tried.
STARTING_SENTENCE = ("Searched by keyword only: search by meaning is still starting. "
                     "Try again in a moment.")


class ChatVectorIndex:
    """The collection, its worker, and the answer to "can it search by meaning"."""

    def __init__(self) -> None:
        self._lanes: List[Any] = []
        self._tried_at: Optional[float] = None
        self._lock = threading.Lock()
        self._queue: "queue.Queue[Any]" = queue.Queue(maxsize=5000)
        self._worker: Optional[threading.Thread] = None
        self._backfill = {"running": False, "indexed": 0, "missing": 0}
        self._started = False

    # ── the lanes ─────────────────────────────────────────────────────────

    def start(self) -> None:
        """Switch it on: build the lanes and catch up, on the worker. Once per
        process (`app.py`); a second call only wakes the worker."""
        self._started = True
        self._enqueue(("warm",))

    def lanes(self) -> List[Any]:
        """The lanes the worker has built — never built here, so a request
        never waits on a model load or an index connection."""
        return self._lanes

    def _build(self) -> None:
        """Build the lanes if there are none and the last try is old enough.
        Worker thread only. A newly healthy index is backfilled."""
        if self._lanes:
            return
        now = time.monotonic()
        if self._tried_at is not None and now - self._tried_at < _RETRY_SECONDS:
            return
        self._tried_at = now
        try:
            from src.embedding_lanes import build_embedding_lanes
            lanes = build_embedding_lanes(COLLECTION_NAME)
        except Exception as e:  # noqa: BLE001 — no lanes is a state, said by `status`
            logger.info("chat search by meaning unavailable: %s", e)
            lanes = []
        with self._lock:
            self._lanes = lanes
        if lanes:
            self.backfill()

    @property
    def healthy(self) -> bool:
        return bool(self._lanes)

    def status(self) -> Dict[str, Any]:
        """`{"meaning": bool, "sentence": str, "indexing": {...}}` — whether a
        search now looks by meaning, and the sentence that says so."""
        if not self.healthy:
            starting = self._started and self._tried_at is None
            return {"meaning": False,
                    "sentence": STARTING_SENTENCE if starting else KEYWORD_ONLY_SENTENCE,
                    "indexing": dict(self._backfill)}
        b = dict(self._backfill)
        if b["running"] and b["missing"]:
            sentence = (f"Searched by keyword and by meaning. Older chats are still being "
                        f"indexed ({b['indexed']:,} of {b['missing']:,} done), so a match by "
                        f"meaning in one of them may not show yet.")
        else:
            sentence = "Searched by keyword and by meaning."
        return {"meaning": True, "sentence": sentence, "indexing": b}

    # ── writing ───────────────────────────────────────────────────────────

    def _enqueue(self, item) -> None:
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            # The backfill finds whatever this drops: it embeds every message
            # the index does not hold.
            return
        self._ensure_worker()

    def _ensure_worker(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        self._worker = threading.Thread(target=self._run, name="chat-vector-index", daemon=True)
        self._worker.start()

    def index_soon(self, message_id: str) -> None:
        """Embed one saved message off the caller's thread, once `start()` has
        switched the index on. Never raises."""
        if message_id and self._started:
            self._enqueue(("message", message_id))

    def _run(self) -> None:
        """The worker: build the lanes (and retry them while absent), catch up,
        then embed each message as it is saved. Lives with the process."""
        while True:
            try:
                item = self._queue.get(timeout=_RETRY_SECONDS)
            except queue.Empty:
                item = ("warm",)
            try:
                self._build()
                if item[0] == "message":
                    self.index_messages([item[1]])
            except Exception as e:  # noqa: BLE001 — a worker that dies stops indexing for good
                logger.warning("chat index: %s failed: %s", item[0], e)

    def _rows(self, db, message_ids: List[str]) -> List[Dict[str, Any]]:
        from core.database import ChatMessage, Session

        rows = (db.query(ChatMessage.id, ChatMessage.content, ChatMessage.session_id, Session.owner)
                .join(Session, ChatMessage.session_id == Session.id)
                .filter(ChatMessage.id.in_(message_ids), ChatMessage.role.in_(SEARCH_ROLES))
                .all())
        return [{"id": mid, "text": (content or "").strip()[:EMBED_CHARS],
                 "session_id": sid, "owner": owner or ""}
                for mid, content, sid, owner in rows if (content or "").strip()]

    def _held(self, lane, ids: List[str]) -> set:
        try:
            return set(lane.collection.get(ids=list(ids)).get("ids") or [])
        except Exception:
            return set()

    def index_messages(self, message_ids: List[str], db=None) -> int:
        """Embed these messages into every lane that lacks them. Returns how
        many rows were written. Quietly nothing when there are no lanes."""
        lanes = self.lanes()
        if not lanes or not message_ids:
            return 0
        from core.database import SessionLocal

        owns = db is None
        db = db or SessionLocal()
        try:
            rows = self._rows(db, list(message_ids))
        finally:
            if owns:
                db.close()
        written = 0
        for lane in lanes:
            have = self._held(lane, [r["id"] for r in rows])
            todo = [r for r in rows if r["id"] not in have]
            if not todo:
                continue
            try:
                lane.collection.add(
                    ids=[r["id"] for r in todo],
                    embeddings=lane.encode([r["text"] for r in todo]),
                    metadatas=[{"owner": r["owner"], "session_id": r["session_id"]} for r in todo],
                )
                written += len(todo)
            except Exception as e:  # noqa: BLE001 — the next backfill tries again
                logger.warning("chat index: %s lane could not add %d message(s): %s",
                               lane.name, len(todo), e)
        return written

    def backfill(self, db=None) -> Dict[str, int]:
        """Embed every searchable message the index does not hold yet.

        Walks `chat_messages` in batches by `(timestamp, id)`, asks each lane
        which ids it already has, and embeds the rest — so it is safe to run
        again at any time and a run cut short resumes where the index stands.
        """
        lanes = self.lanes()
        if not lanes:
            return {"indexed": 0, "missing": 0}
        from core.database import ChatMessage, SessionLocal

        owns = db is None
        db = db or SessionLocal()
        self._backfill = {"running": True, "indexed": 0, "missing": 0}
        try:
            ids = [mid for (mid,) in db.query(ChatMessage.id)
                   .filter(ChatMessage.role.in_(SEARCH_ROLES))
                   .order_by(ChatMessage.timestamp, ChatMessage.id).all()]
            missing: List[str] = []
            for start in range(0, len(ids), 500):
                chunk = ids[start:start + 500]
                held = set.intersection(*[self._held(lane, chunk) for lane in lanes])
                missing.extend(mid for mid in chunk if mid not in held)
            self._backfill["missing"] = len(missing)
            for start in range(0, len(missing), _BATCH):
                self.index_messages(missing[start:start + _BATCH], db=db)
                self._backfill["indexed"] = min(len(missing), start + _BATCH)
                time.sleep(_BATCH_PAUSE_SECONDS)
            return {"indexed": self._backfill["indexed"], "missing": len(missing)}
        finally:
            self._backfill["running"] = False
            if owns:
                db.close()

    def forget_session(self, session_id: str) -> None:
        """Take a deleted chat's rows out of the index. Never raises."""
        if not session_id or not self._lanes:
            return
        for lane in self._lanes:
            try:
                held = lane.collection.get(where={"session_id": session_id}).get("ids") or []
                if held:
                    lane.collection.delete(ids=list(held))
            except Exception as e:  # noqa: BLE001 — the hits are filtered at read anyway
                logger.debug("chat index: could not forget %s in %s: %s", session_id, lane.name, e)

    # ── reading ───────────────────────────────────────────────────────────

    def search(self, query: str, k: int, owner: Optional[str], *,
               restrict: bool = True) -> Optional[List[Dict[str, Any]]]:
        """`[{message_id, score}]`, best first, at or above `MEANING_FLOOR` —
        or None when there is no index to ask. With `restrict`, only `owner`'s
        rows are searched; either way the caller reads every hit back through
        its own filters before anyone sees it."""
        lanes = self.lanes()
        if not lanes:
            return None
        from src.embedding_lanes import dedupe_results, query_lanes

        where = {"owner": owner or ""} if restrict else None
        hits: List[Dict[str, Any]] = []
        for lane, res in query_lanes(lanes, query, lambda _lane: k, include=["distances"],
                                     where=where):
            for idx, mid in enumerate((res.get("ids") or [[]])[0]):
                score = 1.0 - float(res["distances"][0][idx])
                if score >= MEANING_FLOOR:
                    hits.append({"message_id": mid, "score": round(score, 4)})
        hits.sort(key=lambda h: -h["score"])
        return dedupe_results(hits, id_key="message_id", limit=k)


_INDEX: Optional[ChatVectorIndex] = None
_INDEX_LOCK = threading.Lock()


def chat_index() -> ChatVectorIndex:
    """The process's one chat index (`Law 14`: one collection, one worker)."""
    global _INDEX
    with _INDEX_LOCK:
        if _INDEX is None:
            _INDEX = ChatVectorIndex()
        return _INDEX
