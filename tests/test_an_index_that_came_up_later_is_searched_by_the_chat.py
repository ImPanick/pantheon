# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1532` — the chat uses a document index that came up after start.

`app.py` built `rag_manager = get_rag_manager()` once and `PersonalDocsManager`
kept it; nothing updated `personal_docs_manager.rag_manager`, while
`personal_routes._rag()` asked the singleton each time. With the index down at
start, the RAG window worked once the index came up, and the chat's retrieval
stayed off until a restart. Now `PersonalDocsManager.rag_manager` reads the
index as it stands (`rag_singleton.rag_instance`) unless one was handed in.

Driven (`Law 20`): the real `PersonalDocsManager` over a temp directory, built
the way `src/app_initializer.py` builds it from `app.py`'s boot answer; the
real `rag_singleton.get_rag_manager` — the call every RAG route makes — first
failing (the index down) and then succeeding (it came up); and the real
`ChatProcessor.build_context_preface` for a turn with the RAG chip on. Only
the vector store is a stand-in (`src.rag_vector.VectorRAG`), because ChromaDB
and an embedding model are what "down" and "up" mean.
"""
from __future__ import annotations

import sys
import types
from types import SimpleNamespace

import pytest

import src.rag_singleton as rag_singleton


class _Index:
    """The vector store once it is up."""
    healthy = True

    def __init__(self, persist_directory=None):
        self.searched = []

    def get_stats(self):
        return {"documents": 1}

    def search(self, message, k=5, owner=None):
        self.searched.append(message)
        return [{"similarity": 0.9, "metadata": {"filename": "lease.pdf"},
                 "document": "Pets are allowed with a deposit."}]


class _Down(_Index):
    healthy = False


@pytest.fixture
def index(monkeypatch):
    """`src.rag_vector` as the singleton imports it; `index.up()` brings it up."""
    module = types.ModuleType("src.rag_vector")
    module.VectorRAG = _Down
    monkeypatch.setitem(sys.modules, "src.rag_vector", module)
    monkeypatch.setattr(rag_singleton, "rag_instance", None)
    monkeypatch.setattr(rag_singleton, "_last_attempt", float("-inf"))

    def up():
        module.VectorRAG = _Index
        monkeypatch.setattr(rag_singleton, "_last_attempt", float("-inf"))   # past the retry throttle
    index_ = SimpleNamespace(up=up)
    return index_


def _turn(docs):
    from src.chat_processor import ChatProcessor

    memory = SimpleNamespace(load=lambda owner=None: [], increment_uses=lambda ids: None)
    processor = ChatProcessor(memory_manager=memory, personal_docs_manager=docs)
    _, sources, _ = processor.build_context_preface(
        message="what did the lease say about pets?", session=SimpleNamespace(),
        use_rag=True, use_memory=False)
    return processor, sources


def test_an_index_down_at_start_and_up_later_is_searched_without_a_restart(index, tmp_path):
    from src.personal_docs import PersonalDocsManager

    at_boot = rag_singleton.get_rag_manager()              # `app.py`'s one call
    assert at_boot is None, "the index was meant to be down at start"
    docs = PersonalDocsManager(str(tmp_path), at_boot)     # `initialize_managers`

    processor, sources = _turn(docs)
    assert sources == [] and processor._last_rag_off.startswith("RAG is off"), \
        "with the index down, the turn says so (B1287)"

    index.up()
    assert rag_singleton.get_rag_manager() is not None     # what the RAG window's route asks

    processor, sources = _turn(docs)
    assert [s["filename"] for s in sources] == ["lease.pdf"], "the chat did not search the index"
    assert processor._last_rag_off == ""
    assert rag_singleton.rag_instance.searched == ["what did the lease say about pets?"]


def test_a_turn_does_not_start_an_init_attempt(index, tmp_path, monkeypatch):
    """`B1287`'s rule stands: the chat reads the index as it is; bringing it up
    is the RAG routes' (`get_rag_manager`), not a turn's."""
    from src.personal_docs import PersonalDocsManager

    docs = PersonalDocsManager(str(tmp_path), None)
    index.up()
    started = []
    monkeypatch.setattr(rag_singleton, "get_rag_manager", lambda: started.append(1))
    _turn(docs)
    assert started == []


def test_a_manager_handed_in_is_the_one_used(index, tmp_path):
    from src.personal_docs import PersonalDocsManager

    mine = _Index()
    docs = PersonalDocsManager(str(tmp_path), mine)
    _turn(docs)
    assert mine.searched == ["what did the lease say about pets?"]


def test_the_stats_line_and_the_health_card_read_the_index_as_it_stands(index, monkeypatch):
    """The same boot-time copy in `routes/diagnostics_routes.py`: Settings'
    *Knowledge index* stats (`GET /api/rag/stats`) and the services card said
    the index was unavailable until a restart."""
    import asyncio

    import routes.diagnostics_routes as diag
    from src import service_health

    monkeypatch.setattr(diag, "require_admin", lambda request: None)
    seen = []

    async def health(rag_manager=None, memory_vector=None):
        seen.append(rag_manager)
        return {}

    monkeypatch.setattr(service_health, "collect_service_health", health)
    at_boot = rag_singleton.get_rag_manager()
    router = diag.setup_diagnostics_routes(at_boot, at_boot is not None, None, None)
    route = {r.path: r.endpoint for r in router.routes}

    assert asyncio.run(route["/api/rag/stats"](None)) == {"error": "RAG system not available"}
    index.up()
    assert asyncio.run(route["/api/rag/stats"](None)) == {"documents": 1}
    asyncio.run(route["/api/diagnostics/services"](None))
    assert seen == [rag_singleton.rag_instance] and seen[0] is not None
