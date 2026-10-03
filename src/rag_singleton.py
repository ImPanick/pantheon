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

    try:
        from src.rag_vector import VectorRAG

        persist_dir = RAG_DIR

        rag_instance = VectorRAG(persist_directory=persist_dir)
        if not rag_instance.healthy:
            logger.warning("VectorRAG created but not healthy, will retry later")
            rag_instance = None
        else:
            logger.info("Initialized VectorRAG with ChromaDB")

    except ImportError as e:
        logger.warning(f"VectorRAG not available: {e}")
        rag_instance = None
    except Exception as e:
        logger.error(f"Failed to initialize RAG: {e}")
        rag_instance = None

    return rag_instance


def rag_unavailable_reason() -> str:
    """`BRAIN-M-4` / `BRAIN-M-5` (P23-02). Why RAG is off, as the sentence a
    person reads — `""` while it is up. The upload's refusal said "is the
    embedding service running?" while the log at the same moment said the
    embedding model was not downloaded, and the list said nothing at all: the
    Brain's RAG tab read "Drop files above to add to RAG" over a dead index,
    and Settings' *Reload Index* reported "0 documents" (measured on
    `32df791`). Asks `get_rag_manager()` — throttled, so at most one init
    attempt per `_RETRY_INTERVAL`.
    """
    if get_rag_manager() is not None:
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

