# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1795`. A ZIP export dropped the extension of any title with a dot in it.

`POST /api/documents/export-zip` (the Library's export of more than five
documents) named each file `title + extension`, unless the title had a dot
anywhere, which it took to mean the title already carried one: `Notes 11.07`,
`v1.2 plan` and `config.local` were zipped with no extension at all, and a
repeated `script.py` became `script.py-1`, the number after the extension.

Now the language's extension is added unless the title already ends in it, or
in another spelling of the same language (`.yaml` for yaml, `.tsx` for
typescript, `.csv` for csv, which the zip's own map has no entry for), and a
repeated name is numbered before its extension. What a real extension is comes
from `src/file_names.split_extension` (so `Budget v1.5` is not cut at its dot)
and which language a suffix names from `attachment_language`, `B100`'s one
answer; a name is also unique without regard to case, so `Notes` and `notes`
cannot overwrite each other when the archive is unpacked on macOS or Windows.

Ported from upstream Odysseus 9efedc8b (#6848) with its tests, adapted: its
rule as written appended a second extension to `data.csv`, `config.yaml` or
`App.tsx`, which Pantheon names correctly today, and its email case needs a
mapping Pantheon does not have.
"""
import io
import zipfile

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.database import Base, Document
from routes.document import document_routes


@pytest.fixture
def exports(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'documents.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(document_routes, "SessionLocal", factory)
    app = FastAPI()

    @app.middleware("http")
    async def fixture_user(request: Request, call_next):
        request.state.current_user = "alice"
        return await call_next(request)

    app.include_router(document_routes.setup_document_routes(None))

    def add(doc_id, title, language, content="body\n", owner="alice"):
        with factory() as db:
            db.add(Document(id=doc_id, title=title, language=language,
                            current_content=content, owner=owner, is_active=True))
            db.commit()

    with TestClient(app) as client:
        yield client, add
    engine.dispose()


def _names(client, ids):
    response = client.post("/api/documents/export-zip", json={"ids": ids})
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        return archive.namelist(), {name: archive.read(name) for name in archive.namelist()}


@pytest.mark.parametrize("title,language,filename", [
    # Upstream's table.
    ("config.local", "python", "config.local.py"),
    ("report.v2", "markdown", "report.v2.md"),
    ("data.2024", "json", "data.2024.json"),
    ("module.ts", "typescript", "module.ts"),
    ("SCRIPT.PY", "python", "SCRIPT.PY"),
    ("résumé.v2", "text", "résumé.v2.txt"),
    ("unknown.v2", "unknown", "unknown.v2.txt"),
    ("draft", None, "draft.txt"),
    ("project/report.v2", "markdown", "projectreport.v2.md"),
    # Pantheon's own titles: a date or a version is not an extension ...
    ("Notes 11.07", "markdown", "Notes 11.07.md"),
    ("v1.2 plan", "text", "v1.2 plan.txt"),
    ("Budget v1.5", "markdown", "Budget v1.5.md"),
    # ... and a title already named for its language keeps its own suffix,
    # where upstream's rule as written added a second one.
    ("data.csv", "csv", "data.csv"),
    ("logo.svg", "svg", "logo.svg"),
    ("config.yaml", "yaml", "config.yaml"),
    ("App.tsx", "typescript", "App.tsx"),
    ("Main.kt", "kotlin", "Main.kt"),
])
def test_export_uses_the_language_extension_even_for_dotted_titles(exports, title, language, filename):
    client, add = exports
    body = "Original text: α\n"
    add("doc", title, language, body)
    names, files = _names(client, ["doc"])
    assert names == [filename]
    assert files[filename].decode() == body


@pytest.mark.parametrize("title", ["config.local", "config.local.py"])
def test_duplicate_names_keep_the_extension_at_the_end(exports, title):
    client, add = exports
    for i in range(3):
        add(str(i), title, "python", f"body {i}")
    names, files = _names(client, ["0", "1", "2"])
    assert set(names) == {"config.local.py", "config.local-1.py", "config.local-2.py"}
    assert {body.decode() for body in files.values()} == {"body 0", "body 1", "body 2"}


def test_added_extension_collides_safely_with_an_existing_extension(exports):
    client, add = exports
    add("a", "report.v2", "markdown", "first")
    add("b", "report.v2.md", "markdown", "second")
    names, files = _names(client, ["a", "b"])
    assert set(names) == {"report.v2.md", "report.v2-1.md"}
    assert set(files.values()) == {b"first", b"second"}


def test_names_that_differ_only_in_case_stay_two_files_when_unpacked(exports):
    """macOS and Windows unpack `Notes.md` and `notes.md` into one file."""
    client, add = exports
    add("a", "Notes", "markdown", "first")
    add("b", "notes", "markdown", "second")
    names, files = _names(client, ["a", "b"])
    assert len({name.casefold() for name in names}) == 2, names
    assert set(files.values()) == {b"first", b"second"}
