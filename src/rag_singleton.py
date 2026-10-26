# SPDX-License-Identifier: AGPL-3.0-or-later
"""
RAG singleton instance for the application.
"""
import os
import logging
import time
from pathlib import Path

from src.constants import RAG_DIR
from src.runtime_paths import get_app_root

logger = logging.getLogger(__name__)

rag_instance = None
_last_attempt = 0.0
_RETRY_INTERVAL = 30  # seconds between re-init attempts

# `B1250`. A dead index is a standing condition, and each retry said it again:
# measured on `299bd50`, the five-line block — `embedding_lanes`' *ChromaDB
# unreachable* and two *lane unavailable* lines, `rag_vector`'s *VectorRAG init
# failed*, and this module's *will retry later* — every `_RETRY_INTERVAL`
# while anyone used the Brain or the chat, 23 blocks in 40 minutes. Each of
# those lines now goes through `log_once` under a key starting with this
# prefix (`P23-07`'s rule: the first saying is news, the rest at DEBUG), and an
# index that comes up clears them all, so a later failure is news again.
LOG_ONCE_PREFIX = "rag-init:"


def get_rag_manager():
    """Lazy ChromaDB-backed VectorRAG initializer.

    Returns the VectorRAG instance on first successful init, None if ChromaDB
    isn't reachable / available. Failed init attempts are throttled to once
    per _RETRY_INTERVAL seconds so a missing ChromaDB doesn't busy-retry on
    every request — callers (personal-doc routes etc.) get None back and
    return a clean 503 to the user instead.

    Historical note: this used to be hardcoded to ``return None`` with a
    comment about chromadb 1.4.1 / pydantic 2.12 being mutually incompatible.
    That compat issue is resolved in current pinned versions
    (chromadb 1.5.x + pydantic 2.13.x), so the real initializer is back.
    """
    global rag_instance, _last_attempt

    if rag_instance is not None:
        return rag_instance

    now = time.monotonic()
    if now - _last_attempt < _RETRY_INTERVAL:
        return None  # too soon to retry — last attempt failed

    _last_attempt = now

    from src.log_once import clear_prefix, log_once

    try:
        from src.rag_vector import VectorRAG

        persist_dir = RAG_DIR

        rag_instance = VectorRAG(persist_directory=persist_dir)
        if not rag_instance.healthy:
            log_once(logger, logging.WARNING, LOG_ONCE_PREFIX + "unhealthy",
                     "VectorRAG created but not healthy, will retry every %ss "
                     "(said once; the retries log at DEBUG)", _RETRY_INTERVAL)
            rag_instance = None
        else:
            logger.info("Initialized VectorRAG with ChromaDB")
            clear_prefix(LOG_ONCE_PREFIX)

    except ImportError as e:
        log_once(logger, logging.WARNING, f"{LOG_ONCE_PREFIX}import:{e}",
                 "VectorRAG not available: %s", e)
        rag_instance = None
    except Exception as e:
        log_once(logger, logging.ERROR, f"{LOG_ONCE_PREFIX}init:{type(e).__name__}:{e}",
                 "Failed to initialize RAG: %s", e)
        rag_instance = None

    return rag_instance


def rag_unavailable_reason(retry: bool = True) -> str:
    """`BRAIN-M-4` / `BRAIN-M-5` (P23-02). Why RAG is off, as the sentence a
    person reads — `""` while it is up. The upload's refusal said "is the
    embedding service running?" while the log at the same moment said the
    embedding model was not downloaded, and the list said nothing at all: the
    Brain's RAG tab read "Drop files above to add to RAG" over a dead index,
    and Settings' *Reload Index* reported "0 documents" (measured on
    `32df791`). Asks `get_rag_manager()` — throttled, so at most one init
    attempt per `_RETRY_INTERVAL`.

    `retry=False` (`B1287`) reads the index as it stands and starts no init
    attempt: the chat asks on every turn with the RAG chip on, and a turn is
    not where an index is brought up.
    """
    if (get_rag_manager() if retry else rag_instance) is not None:
        return ""
    try:
        from src.embedding_lanes import fastembed_model_is_cached, model_download_allowed
        if not fastembed_model_is_cached() and not model_download_allowed() \
                and not (os.environ.get("EMBEDDING_URL") or "").strip():
            return ("RAG is off: the embedding model is not downloaded — "
                    "Settings › System › Download models from the internet.")
    except Exception:
        pass   # the lane probe failing is itself "did not start"; the sentence below says so
    return "RAG is off: the document index did not start. The server log says why."

