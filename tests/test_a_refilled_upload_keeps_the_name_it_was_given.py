# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1641` — an upload refilled into the Knowledge index keeps the name it was
uploaded under.

Measured before the fix: `POST /api/personal/upload` gives each chunk the
person's own name for the file as `filename` (`P21-03`) and stores the bytes
under the storable form of it (`file_names.stored_name`) — `Q3: Board Pack?.md`
is `Q3_ Board Pack_.md` on disk, and a second `notes.md` is `notes (2).md`. The
index was the only place that name was kept, so when `B1639`'s refill read the
uploads folder back into an index that came back empty,
`VectorRAG.index_personal_documents` named every chunk by the stored basename,
and the chat's sources (`chat_processor`'s `rag_sources`, read from
`filename`) showed a name nobody gave the file.

Now the upload route records each name beside the folder's owner
(`PersonalDocsManager.name_files`, `.indexed_file_names.json`), kept through an
account's rename and dropped with its folder, and the refill hands it to the
indexer, which writes `filename` and `stored_filename` as the upload did.

Driven (`Law 20`) as `tests/test_the_knowledge_index_refills_itself.py` drives
the refill — the real route, the real `VectorRAG` on a real in-process index,
the concept embedder for the embedding server, the index's files deleted as a
lost volume deletes them, and the next start's `start_refill` — with the files
uploaded through the real upload route.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from test_the_knowledge_index_refills_itself import install  # noqa: F401 — fixture

BOARD = "Q3: Board Pack?.md"
NOTES = "notes.md"


@pytest.fixture
def uploads(install, monkeypatch):  # noqa: F811 — the imported fixture
    """`ada`'s uploads through the route: a name with characters a stored name
    cannot hold, and the same name twice."""
    import routes.personal_routes as personal_routes
    from src.personal_docs import PersonalDocsManager
    monkeypatch.setattr(personal_routes, "UPLOADS_DIR", str(install.root / "personal_uploads"))
    manager = PersonalDocsManager(str(install.personal_dir))
    _upload(manager, "ada", [(BOARD, "Booked the beach holiday trip for the offsite; the flight leaves at nine."),
                             (NOTES, "Fresh pasta recipe for a weeknight dinner.")])
    _upload(manager, "ada", [(NOTES, "Bake the pasta for Sunday dinner.")])
    return manager


def _upload(manager, owner: str, files):
    """`POST /api/personal/upload`, as `owner`, through the real router."""
    import routes.personal_routes as personal_routes
    app = FastAPI()

    @app.middleware("http")
    async def _who(request, call_next):
        request.state.current_user = owner
        return await call_next(request)

    app.include_router(personal_routes.setup_personal_routes(manager, None, True))
    with TestClient(app) as client:
        r = client.post("/api/personal/upload",
                        files=[("files", (name, text.encode("utf-8"), "text/markdown")) for name, text in files])
    assert r.status_code == 200 and r.json()["success"], r.text
    assert r.json()["uploaded"] == [name for name, _t in files], r.json()


def _sources(query: str, owner: str):
    """What the chat's search by meaning hands back for `owner`, nearest
    first: each chunk's `filename` (what `rag_sources` shows) and the file it
    was read from."""
    from src.rag_singleton import get_rag_manager
    return [(r["metadata"].get("filename"), Path(r["metadata"]["source"]).name)
            for r in get_rag_manager().search(query, k=5, owner=owner)]


#: Every chunk of `ada`'s three uploads, as the upload route named them.
AS_UPLOADED = sorted([(NOTES, "notes (2).md"), (NOTES, "notes.md"), (BOARD, "Q3_ Board Pack_.md")])


def _refill(install):
    from src.personal_docs import start_refill
    manager = install.next_start()
    assert _sources("vacation", "ada") == [], "premise: the emptied index answers nothing"
    start_refill(manager).join(timeout=60)
    return manager


def test_the_upload_is_named_as_it_was_given_and_stored_otherwise(uploads):
    """The premise, as the upload wrote it."""
    assert _sources("vacation", "ada")[0] == (BOARD, "Q3_ Board Pack_.md")
    assert sorted(_sources("dinner", "ada")) == AS_UPLOADED


def test_a_refill_gives_each_upload_the_name_it_was_uploaded_under(install, uploads):  # noqa: F811
    _refill(install)
    assert _sources("vacation", "ada")[0] == (BOARD, "Q3_ Board Pack_.md")
    assert sorted(_sources("dinner", "ada")) == AS_UPLOADED
    from src.rag_singleton import get_rag_manager
    hit = get_rag_manager().search("vacation", k=1, owner="ada")[0]["metadata"]
    assert hit["stored_filename"] == "Q3_ Board Pack_.md", hit


def test_without_the_record_a_refill_named_each_upload_by_its_stored_name(install, uploads):  # noqa: F811
    """The control: the refill as it was, with nowhere to read the name from."""
    (install.personal_dir / ".indexed_file_names.json").unlink(missing_ok=True)
    _refill(install)
    assert _sources("vacation", "ada")[0] == ("Q3_ Board Pack_.md", "Q3_ Board Pack_.md")
    assert sorted(_sources("dinner", "ada")) == [("Q3_ Board Pack_.md", "Q3_ Board Pack_.md"),
                                                 ("notes (2).md", "notes (2).md"), ("notes.md", "notes.md")]


def test_a_renamed_account_keeps_its_uploads_names(install, uploads):  # noqa: F811
    from routes.personal_routes import rename_personal_upload_owner
    moved = rename_personal_upload_owner("ada", "adah", personal_docs_manager=uploads)
    assert moved["moved_files"] == 3
    _refill(install)
    assert _sources("vacation", "adah")[0] == (BOARD, "Q3_ Board Pack_.md")


def test_a_folder_taken_off_the_list_takes_its_names_with_it(install, uploads):  # noqa: F811
    from src.personal_docs import PersonalDocsManager
    [folder] = uploads.get_indexed_directories()
    assert len(uploads.names_under(folder)) == 3
    uploads.remove_directory(folder)
    assert PersonalDocsManager(str(install.personal_dir)).names_under(folder) == {}
