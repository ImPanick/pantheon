# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1639` — the Knowledge index refills itself when its collection comes back
empty, as memories, chat search and the tool index already did.

Measured before the fix: `pantheon_rag` was embedded only by
`index_personal_documents`, when a folder was added. After ChromaDB's volume
was lost — `B1626`'s one-time recreate, or any other way — the folders the
Knowledge index still listed answered nothing by meaning until each was added
again by hand, and nothing said so. Now `app.py`'s start calls
`personal_docs.start_refill`: on its own thread, it asks for the index through
`get_rag_manager()` — whose lanes are built behind the embedder's own download
gate (`Law 16`) — and, when the index holds nothing, reads every listed folder
into it again: under the account the folder was added by (recorded since this
row, so the chat's owner-scoped search finds it), or, for a folder listed
before owners were recorded, the install's first admin (`P27-02`'s rule for
records from before per-account ownership); never a file the person took out
of the index; never a folder removed meanwhile.

Driven (`Law 20`): the real route adds a folder, the real `VectorRAG` embeds
it into a real in-process index (`LocalIndexClient`) with a small concept
embedder standing in for the configured embedding server (a model is a
download this environment refuses — the real gate refuses it here too). The
index's files are then deleted, as a lost volume deletes them, and "the next
start" is a fresh `PersonalDocsManager` and a fresh index from the singleton,
with `start_refill` run as `app.py` runs it.
"""
from __future__ import annotations

import ast
import hashlib
import math
import re
import shutil
import threading
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]

_CONCEPTS = {"holiday": 0, "vacation": 0, "beach": 0, "flight": 0, "trip": 0,
             "recipe": 1, "pasta": 1, "dinner": 1, "bake": 1}
_DIM = 2 + 61


class ConceptEmbedder:
    """The configured embedding server, standing in: two concepts and a hashed
    spread for every other word."""
    model = "concept-test"
    url = "test://concepts"

    def get_sentence_embedding_dimension(self):
        return _DIM

    def encode(self, texts, normalize_embeddings=True):
        out = []
        for text in texts:
            v = [0.0] * _DIM
            for word in re.findall(r"[a-z]+", str(text).lower()):
                if word in _CONCEPTS:
                    v[_CONCEPTS[word]] += 3.0
                else:
                    v[2 + int(hashlib.sha1(word.encode()).hexdigest(), 16) % 61] += 1.0
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / n for x in v])
        return out


class _Auth:
    """The user database: `ada` set the install up, `alice` and `bob` joined."""
    def list_users(self):
        return [{"username": "ada", "is_admin": True}, {"username": "alice", "is_admin": False},
                {"username": "bob", "is_admin": False}]


@pytest.fixture
def install(monkeypatch, tmp_path):
    """An install whose index is the in-process one under `vectors/`, whose
    embedding server is the concept embedder, and whose local model is not on
    disk and may not be fetched — the gate as it stands on a fresh install."""
    from src import auth_manager_access, embedding_lanes, rag_singleton

    vectors = tmp_path / "vectors"
    monkeypatch.setattr(embedding_lanes, "index_client", lambda: _local_index(vectors))
    monkeypatch.setattr(embedding_lanes, "fastembed_model_is_cached", lambda: False)
    monkeypatch.setattr(embedding_lanes, "model_download_allowed", lambda: False)
    monkeypatch.setattr(embedding_lanes, "_build_custom_client", lambda: ConceptEmbedder())
    monkeypatch.setattr(rag_singleton, "RAG_DIR", str(tmp_path / "rag"))
    monkeypatch.setattr(rag_singleton, "rag_instance", None)
    monkeypatch.setattr(rag_singleton, "_last_attempt", 0.0)
    monkeypatch.setattr(auth_manager_access, "shared_auth_manager", lambda: _Auth())

    personal = tmp_path / "personal"
    trips = personal / "Trips"
    trips.mkdir(parents=True)
    (trips / "lisbon.md").write_text("Booked the beach holiday in Lisbon for May; the flight leaves at nine.",
                                     encoding="utf-8")
    (trips / "old-plan.md").write_text("An old holiday plan on the beach, taken out of the index.",
                                       encoding="utf-8")
    recipes = personal / "Recipes"
    recipes.mkdir()
    (recipes / "pasta.md").write_text("Fresh pasta recipe for a weeknight dinner.", encoding="utf-8")

    class Install:
        root = tmp_path
        personal_dir = personal

        @staticmethod
        def next_start():
            """The index's files gone, as a lost volume takes them, and a fresh
            process: no index yet, and the manager read back from its files."""
            from src.personal_docs import PersonalDocsManager
            shutil.rmtree(vectors, ignore_errors=True)
            _OPEN.clear()
            rag_singleton.rag_instance = None
            rag_singleton._last_attempt = 0.0
            return PersonalDocsManager(str(personal))

    _OPEN.clear()
    yield Install
    _OPEN.clear()


#: One `LocalIndexClient` per directory per "process", as `index_client`
#: hands every caller the one client of a running app.
_OPEN: dict = {}


def _local_index(directory: Path):
    from src.local_collection import LocalIndexClient
    if str(directory) not in _OPEN:
        directory.mkdir(parents=True, exist_ok=True)
        _OPEN[str(directory)] = LocalIndexClient(str(directory))
    return _OPEN[str(directory)]


def _add_through_the_route(install, manager, folder: str, owner: str):
    """`POST /api/personal/add_directory`, as `owner`, through the real router."""
    import routes.personal_routes as personal_routes
    from core.middleware import require_operator
    from src.auth_helpers import require_user

    app = FastAPI()
    app.include_router(personal_routes.setup_personal_routes(manager, None, True))
    app.dependency_overrides[require_user] = lambda: owner
    app.dependency_overrides[require_operator] = lambda: None
    with TestClient(app) as client:
        r = client.post("/api/personal/add_directory", json={"directory": str(install.personal_dir / folder)})
    assert r.status_code == 200 and r.json()["success"], r.text
    return r.json()


def _found(query: str, owner: str):
    """The chat's search by meaning (`chat_processor`): the person's own
    chunks, nearest first — each as the file it came from."""
    from src.rag_singleton import get_rag_manager
    rag = get_rag_manager()
    return [Path(r["metadata"]["source"]).name for r in rag.search(query, k=5, owner=owner)]


@pytest.fixture
def listed(install, monkeypatch):
    """Two folders added through the route — `Trips` by alice, `Recipes` by
    bob — and one file of alice's taken out of the index by hand."""
    import routes.personal_routes as personal_routes
    from src.personal_docs import PersonalDocsManager
    monkeypatch.setattr(personal_routes, "PERSONAL_DIR", str(install.personal_dir))
    manager = PersonalDocsManager(str(install.personal_dir))
    _add_through_the_route(install, manager, "Trips", "alice")
    _add_through_the_route(install, manager, "Recipes", "bob")
    from src.rag_singleton import get_rag_manager
    old_plan = str(install.personal_dir / "Trips" / "old-plan.md")
    get_rag_manager().delete_by_source(old_plan)
    manager.exclude_file(old_plan)
    assert _found("vacation", "alice")[0] == "lisbon.md"
    assert "old-plan.md" not in _found("vacation", "alice")
    return manager


# ── the row ─────────────────────────────────────────────────────────────────

def test_an_emptied_index_is_refilled_at_the_next_start_and_finds_by_meaning(install, listed):
    from src.personal_docs import start_refill

    manager = install.next_start()
    assert _found("vacation", "alice") == [], "premise: the emptied index answers nothing by meaning"
    start_refill(manager).join(timeout=60)
    # "vacation" is in no word of the file; by meaning it is found, as its owner.
    assert _found("vacation", "alice")[0] == "lisbon.md"
    assert _found("dinner ideas", "bob")[0] == "pasta.md"
    # Each person's folder is theirs again, and only theirs.
    assert "pasta.md" not in _found("pasta recipe", "alice")
    assert "lisbon.md" not in _found("beach holiday", "bob")
    # A file taken out of the index by hand stays out.
    assert "old-plan.md" not in _found("old holiday plan", "alice")


def test_without_the_refill_the_listed_folders_stay_silent(install, listed):
    """The control: the next start as it was — the folders listed, the
    index empty, and nothing reading them back."""
    manager = install.next_start()
    from src.rag_singleton import get_rag_manager
    assert manager.get_indexed_directories() and get_rag_manager().get_stats()["document_count"] == 0
    assert _found("vacation", "alice") == []


def test_an_index_that_still_holds_chunks_is_left_as_it_is(install, listed):
    from src.personal_docs import PersonalDocsManager
    from src.rag_singleton import get_rag_manager
    held = get_rag_manager().document_count()
    result = PersonalDocsManager(str(install.personal_dir)).refill_vector_index()
    assert result["refilled"] == [] and get_rag_manager().document_count() == held


def test_a_folder_listed_before_owners_were_recorded_is_the_first_admins(install, listed):
    """A list from an older build has no owners file: each folder is read
    under the install's first admin, never left to nobody."""
    (install.personal_dir / ".indexed_directory_owners.json").unlink()
    manager = install.next_start()
    result = manager.refill_vector_index()
    assert len(result["refilled"]) == 2 and result["chunks"] >= 2, result
    assert _found("vacation", "ada")[0] == "lisbon.md"
    assert _found("vacation", "alice") == []


def test_a_folder_no_longer_there_is_named_and_the_rest_are_read(install, listed):
    shutil.rmtree(install.personal_dir / "Recipes")
    manager = install.next_start()
    result = manager.refill_vector_index()
    assert result["missing"] == [str(install.personal_dir / "Recipes")]
    assert "not there any more" in result["sentence"]
    assert _found("vacation", "alice")[0] == "lisbon.md"


def test_a_renamed_account_refills_under_its_new_name(install, listed):
    from routes.personal_routes import rename_personal_upload_owner
    rename_personal_upload_owner("alice", "alicia", personal_docs_manager=listed)
    manager = install.next_start()
    manager.refill_vector_index()
    assert _found("vacation", "alicia")[0] == "lisbon.md"


# ── behind the gate, off the loop, wired at start ───────────────────────────

def test_with_no_embedder_nothing_is_read_and_no_model_is_fetched(install, listed, monkeypatch):
    """The download gate the lanes already ask: with no embedding server and
    no model on disk, no index starts, so no folder is walked and no model is
    fetched — and the log says why, in the sentence the RAG window says."""
    from src import embedding_lanes, embeddings
    built = []
    monkeypatch.setattr(embedding_lanes, "_build_custom_client",
                        lambda: (_ for _ in ()).throw(RuntimeError("HTTP embedding lane unavailable")))
    monkeypatch.setattr(embeddings, "FastEmbedClient", lambda *a, **k: built.append(1))
    manager = install.next_start()
    walked = []
    monkeypatch.setattr("src.rag_vector.walk_index_candidates", lambda *a, **k: walked.append(a) or iter(()))
    result = manager.refill_vector_index()
    assert result["refilled"] == [] and walked == [] and built == []
    assert "the embedding model is not downloaded" in result["sentence"], result


def test_the_refill_runs_on_its_own_thread_and_the_start_does_not_wait(install, listed, monkeypatch):
    from src import rag_vector
    from src.personal_docs import start_refill
    manager = install.next_start()
    release, ran_on = threading.Event(), []
    real = rag_vector.VectorRAG.index_personal_documents

    def slow(self, *a, **k):
        ran_on.append(threading.get_ident())
        release.wait(30)
        return real(self, *a, **k)

    monkeypatch.setattr(rag_vector.VectorRAG, "index_personal_documents", slow)
    worker = start_refill(manager)
    assert worker.is_alive() and worker.daemon, "the start returned while the folders are read"
    release.set()
    worker.join(timeout=60)
    assert ran_on and threading.get_ident() not in ran_on
    assert _found("vacation", "alice")[0] == "lisbon.md"


def test_the_app_starts_the_refill_with_its_own_knowledge_index():
    """Wiring (`Law 13`), read in its scope: `app.py`'s start event calls
    `start_refill` with the manager its routes were built with."""
    tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
    start = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "_startup_event")
    calls = [n for n in ast.walk(start) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == "start_refill"]
    assert len(calls) == 1 and [a.id for a in calls[0].args] == ["personal_docs_mgr"]
    routes = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
              and n.func.id == "setup_personal_routes"]
    assert routes and routes[0].args[0].id == "personal_docs_mgr"
