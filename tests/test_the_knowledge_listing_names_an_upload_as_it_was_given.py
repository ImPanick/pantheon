# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1644` — the Knowledge listing (`GET /api/personal`) shows an upload under
the name it was uploaded under.

Measured before the fix: `POST /api/personal/upload` stores each file under the
storable form of its name (`file_names.stored_name`: `Q3: Board Pack?.md` is
`Q3_ Board Pack_.md` on disk, a second `notes.md` is `notes (2).md`) and gives
its chunks the person's own name (`P21-03`), which `B1641` also records by the
stored path (`PersonalDocsManager.name_files`). The listing is built by
`_refresh_index_locked`, which named each file `<folder basename>/<relpath>`
and never read the record, so the Knowledge panel listed
`ada/Q3_ Board Pack_.md` for a file the chat's sources called
`Q3: Board Pack?.md`. And an upload into a folder already tracked — the
person's second — was not listed at all until a reload: `add_directory` lists
a folder only the first time.

Driven (`Law 20`): files uploaded through the real upload route, the listing
read through the real `GET /api/personal`, on the real `VectorRAG` the upload
writes to (the install fixture of `B1639`'s test), in this process and in the
next one (a fresh manager read back from its files).
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from test_the_knowledge_index_refills_itself import install  # noqa: F401 — fixture

BOARD = "Q3: Board Pack?.md"
NOTES = "notes.md"


def _app(manager, owner: str) -> FastAPI:
    """The real personal router, as `owner` (an operator)."""
    import routes.personal_routes as personal_routes
    from core.middleware import require_operator
    from src.auth_helpers import require_user
    app = FastAPI()

    @app.middleware("http")
    async def _who(request, call_next):
        request.state.current_user = owner   # what `require_privilege` reads
        return await call_next(request)

    app.include_router(personal_routes.setup_personal_routes(manager, None, True))
    app.dependency_overrides[require_user] = lambda: owner
    app.dependency_overrides[require_operator] = lambda: None
    return app


def _upload(manager, owner: str, files) -> None:
    with TestClient(_app(manager, owner)) as client:
        r = client.post("/api/personal/upload",
                        files=[("files", (name, text.encode("utf-8"), "text/markdown")) for name, text in files])
    assert r.status_code == 200 and r.json()["success"], r.text
    assert r.json()["uploaded"] == [name for name, _t in files], r.json()


def _listed(manager, owner: str = "ada"):
    """`GET /api/personal`'s files in the uploads folder, as the panel reads
    them: name, and the file on disk it stands for. (The install's own
    `Trips` and `Recipes` notes are listed too, beside them.)"""
    with TestClient(_app(manager, owner)) as client:
        r = client.get("/api/personal")
    assert r.status_code == 200, r.text
    return sorted((f["name"], f["path"].rsplit("/", 1)[-1]) for f in r.json()["files"]
                  if "/personal_uploads/" in f["path"])


@pytest.fixture
def uploads(install, monkeypatch):  # noqa: F811 — the imported fixture
    """`ada`'s uploads through the route, in two requests: a name a stored
    name cannot hold, and the same name twice (the second into the folder the
    first one listed)."""
    import routes.personal_routes as personal_routes
    from src.personal_docs import PersonalDocsManager
    monkeypatch.setattr(personal_routes, "UPLOADS_DIR", str(install.root / "personal_uploads"))
    manager = PersonalDocsManager(str(install.personal_dir))
    _upload(manager, "ada", [(BOARD, "Booked the beach holiday trip for the offsite."),
                             (NOTES, "Fresh pasta recipe for a weeknight dinner.")])
    _upload(manager, "ada", [(NOTES, "Bake the pasta for Sunday dinner.")])
    return manager


#: `ada`'s three uploads as the listing shows them, each beside its stored file.
AS_GIVEN = sorted([(f"ada/{BOARD}", "Q3_ Board Pack_.md"), (f"ada/{NOTES}", "notes.md"),
                   (f"ada/{NOTES}", "notes (2).md")])


def test_the_listing_names_each_upload_as_it_was_uploaded(uploads):
    assert _listed(uploads) == AS_GIVEN


def test_the_next_start_lists_them_under_the_same_names(install, uploads):  # noqa: F811
    from src.personal_docs import PersonalDocsManager
    assert _listed(PersonalDocsManager(str(install.personal_dir))) == AS_GIVEN


def test_a_file_nobody_named_is_listed_under_its_own_name(install, uploads):  # noqa: F811
    """A file in a listed folder that was not uploaded through the route — put
    there by hand — has no recorded name and keeps its own."""
    from src.personal_docs import PersonalDocsManager
    [folder] = uploads.get_indexed_directories()
    with open(f"{folder}/minutes.md", "w", encoding="utf-8") as fh:
        fh.write("Minutes of the planning meeting.")
    assert _listed(PersonalDocsManager(str(install.personal_dir))) == sorted(
        AS_GIVEN + [("ada/minutes.md", "minutes.md")])


def test_without_the_record_the_listing_shows_the_stored_names(install, uploads):  # noqa: F811
    """The control: the listing as it was named, with no record to read."""
    from src.personal_docs import PersonalDocsManager
    (install.personal_dir / ".indexed_file_names.json").unlink()
    assert _listed(PersonalDocsManager(str(install.personal_dir))) == sorted(
        [("ada/Q3_ Board Pack_.md", "Q3_ Board Pack_.md"), ("ada/notes.md", "notes.md"),
         ("ada/notes (2).md", "notes (2).md")])
