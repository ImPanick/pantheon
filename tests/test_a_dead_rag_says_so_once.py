# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1250` — a dead RAG logged its five-line init block every 30 seconds.

Measured on `299bd50` with no embedding model: `src.embedding_lanes` *ChromaDB
unreachable* (INFO), *No fastembed lane* / *lane unavailable* (WARNING),
`src.rag_vector` *VectorRAG init failed* (ERROR) and `src.rag_singleton` *will
retry later* (WARNING) — one block every `_RETRY_INTERVAL` (30 s) whenever a
request called `get_rag_manager()`, 23 blocks in 40 minutes. `P23-07` made
standing conditions say themselves once per process (`src/log_once.py`); this
one was outside it.

Driven through the real `get_rag_manager` → `VectorRAG` → `build_embedding_lanes`
chain, with the two far ends that are absent on such an install made absent:
ChromaDB refuses the connection, and the embedding model is not on disk and
may not be fetched (`ModelDownloadNotPermitted`, the real refusal). The clock
is moved past the retry interval between asks — the row's hour of Brain opens,
in twelve asks.
"""
from __future__ import annotations

import logging

import pytest

import src.embedding_lanes as lanes
import src.rag_singleton as rag_singleton
from src.log_once import clear_prefix

_LOGGERS = ("src.embedding_lanes", "src.rag_vector", "src.rag_singleton")


@pytest.fixture
def dead_index(monkeypatch, tmp_path):
    import src.chroma_client
    import src.constants

    def refused():
        raise ConnectionError("Could not connect to ChromaDB at localhost:8000")

    def no_model():
        raise lanes.ModelDownloadNotPermitted("the local embedding model is not downloaded")

    monkeypatch.setattr(src.chroma_client, "get_chroma_client", refused)
    monkeypatch.setattr(lanes, "_build_custom_client", lambda: None)
    monkeypatch.setattr(lanes, "_build_fastembed_client", no_model)
    monkeypatch.setattr(src.constants, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(rag_singleton, "RAG_DIR", str(tmp_path / "rag"))
    monkeypatch.setattr(rag_singleton, "rag_instance", None)
    monkeypatch.setattr(rag_singleton, "_last_attempt", 0.0)
    clock = {"now": 1000.0}
    monkeypatch.setattr(rag_singleton.time, "monotonic", lambda: clock["now"])
    clear_prefix(rag_singleton.LOG_ONCE_PREFIX)
    clear_prefix("embedding-lanes:")
    yield clock
    clear_prefix(rag_singleton.LOG_ONCE_PREFIX)
    clear_prefix("embedding-lanes:")


def _said(caplog, level=logging.INFO):
    return [(r.name, r.levelname, r.getMessage()) for r in caplog.records
            if r.name in _LOGGERS and r.levelno >= level]


def test_an_hour_of_asks_with_no_embedding_model_logs_one_block(dead_index, caplog):
    """The row's `Verify:` — twelve retries, past the interval each time."""
    caplog.set_level(logging.DEBUG)
    for _ in range(12):
        assert rag_singleton.get_rag_manager() is None
        dead_index["now"] += rag_singleton._RETRY_INTERVAL + 1

    said = _said(caplog)
    kinds = [(name, level) for name, level, _ in said]
    assert kinds == [
        ("src.embedding_lanes", "INFO"),        # ChromaDB unreachable; local index
        ("src.embedding_lanes", "WARNING"),     # no fastembed lane
        ("src.rag_vector", "ERROR"),            # VectorRAG init failed
        ("src.rag_singleton", "WARNING"),       # not healthy, will retry
    ], said
    # The retries were made, and said at DEBUG: the condition is not hidden.
    retried = [r for r in caplog.records
               if r.name == "src.rag_vector" and "VectorRAG init failed" in r.getMessage()]
    assert len(retried) == 12 and {r.levelname for r in retried[1:]} == {"DEBUG"}


def test_the_block_is_said_again_after_the_index_has_come_up(dead_index, caplog, monkeypatch):
    """Once up, a later failure is news: the keys are cleared when it starts."""
    import src.rag_vector

    real = src.rag_vector.VectorRAG
    rag_singleton.get_rag_manager()                          # down, and said
    dead_index["now"] += rag_singleton._RETRY_INTERVAL + 1

    class _Healthy:
        healthy = True

        def __init__(self, persist_directory):
            pass

    monkeypatch.setattr(src.rag_vector, "VectorRAG", _Healthy)
    assert rag_singleton.get_rag_manager() is not None       # it came up
    monkeypatch.setattr(src.rag_vector, "VectorRAG", real)
    monkeypatch.setattr(rag_singleton, "rag_instance", None)  # and went down again
    dead_index["now"] += rag_singleton._RETRY_INTERVAL + 1

    caplog.clear()
    caplog.set_level(logging.DEBUG)
    rag_singleton.get_rag_manager()
    assert [(n, lv) for n, lv, _ in _said(caplog)] == [
        ("src.rag_vector", "ERROR"), ("src.rag_singleton", "WARNING")], _said(caplog)
