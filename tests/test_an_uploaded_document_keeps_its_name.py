# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P21-03` — an uploaded document keeps its name, through every door.

The owner, 2026-10-01: *"it must transfer the document name. Not rename the
document to some random base64 string - because then the user can't even
back-reference their own documents easily."*

Reproduced on the tree before this row, by driving the doors below: a file
called `Q3 Board Pack – final (v2).odt` attached to a chat became a document
titled ``a1d9182aca87476e8e1c9754dbf13105`` — the upload id, read back off the
stored path. The other doors each had their own spelling: the chip, the model's
label, the PDF auto-document and the download said `Q3_Board_Pack_final_v2`;
the mailbox said `Q3 Board Pack _ final _v2_`; `import-pdf` titled
`../../evil.pdf` as `../../evil`; and every stored file on disk was a 32-hex id
or carried a random ten-hex suffix.

Every test drives the code — routes through ``TestClient`` over a real router,
the real ``UploadHandler`` on a temp directory, a real SQLite file — and none
reads a source file (`Law 20`). The chat send turn is ``build_user_content``
called the way the chat route calls it, because that is where the
auto-document is made.
"""
import asyncio
import contextlib
import io
import json
import os
import re
import sqlite3
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import unquote

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

import core.database as cdb
import src.database as sdb
from src import file_names
from src.file_names import (
    attachment_disposition,
    display_name,
    document_title,
    stored_name,
    upload_display_name,
)
from src.upload_handler import UploadHandler
from tests.test_attachment_extension_registers import _minimal_pdf, _odt_document

NAME = "Q3 Board Pack – final (v2)"
OWNER = "alice"


# ── the harness: the real routers over one temp store ───────────────────────


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Real upload, document, personal and email routers on a temp DB + store."""
    import routes.document.document_routes as droutes
    import routes.email_routes as email_routes
    import routes.personal_routes as personal_routes
    import routes.upload_routes as upload_routes
    from routes.email_helpers import require_owner
    from src import tool_utils

    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}",
                           connect_args={"check_same_thread": False},
                           poolclass=NullPool)
    cdb.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    for mod in (cdb, sdb, droutes, upload_routes):
        monkeypatch.setattr(mod, "SessionLocal", Session)

    handler = UploadHandler(str(tmp_path / "base"), str(tmp_path / "uploads"))
    handler.upload_rate_limit = 10_000
    handler.upload_burst_limit = 10_000
    monkeypatch.setattr(tool_utils, "_upload_handler", handler)

    monkeypatch.setattr("src.auth_helpers.require_privilege", lambda request, priv: OWNER)
    monkeypatch.setattr("src.auth_helpers.get_current_user", lambda request: OWNER)
    monkeypatch.setattr(droutes, "get_current_user", lambda request: OWNER)
    monkeypatch.setattr(upload_routes, "effective_user", lambda request: OWNER)
    monkeypatch.setattr(personal_routes, "require_privilege", lambda request, priv: OWNER)
    monkeypatch.setattr(personal_routes, "UPLOADS_DIR", str(tmp_path / "personal"))

    indexed = []

    class _Rag:
        def _split_into_chunks(self, text, chunk_size=500):
            return [text]

        def add_document(self, chunk, meta):
            indexed.append(meta)
            return True

    monkeypatch.setattr(personal_routes, "get_rag_manager", lambda: _Rag())

    extract = tmp_path / "mail-extract"
    monkeypatch.setattr(email_routes, "attachment_extract_dir", lambda folder, uid: extract)

    app = FastAPI()
    upload_router, _cleanup = upload_routes.setup_upload_routes(handler)
    app.include_router(upload_router)
    app.include_router(droutes.setup_document_routes(None, handler))
    manager = type("M", (), {"add_directory": lambda *a, **k: None})()
    app.include_router(personal_routes.setup_personal_routes(manager, _Rag(), True))
    app.include_router(email_routes.setup_email_routes())
    app.dependency_overrides[require_owner] = lambda: OWNER
    # The router's `Depends` holds the function `email_routes` imported. A test
    # earlier in a full run can drop `routes.email_helpers` from `sys.modules`,
    # and then the import above is a different function and the override misses
    # it: every mail route answered 401 and seven office-file cases failed only
    # in the whole suite. Override the one the routes actually use too.
    app.dependency_overrides[email_routes.require_owner] = lambda: OWNER

    db = Session()
    db.add(cdb.Session(id="chat-1", name="chat", owner=OWNER,
                       endpoint_url="http://127.0.0.1:1", model="m"))
    db.commit()
    db.close()

    class Env:
        pass

    e = Env()
    e.client = TestClient(app)
    e.handler = handler
    e.Session = Session
    e.engine = engine
    e.indexed = indexed
    e.tmp = tmp_path
    e.email_routes = email_routes
    return e


def _upload(env, name, body, mime="application/octet-stream"):
    r = env.client.post("/api/upload", files=[("files", (name, body, mime))])
    assert r.status_code == 200, r.text
    return r.json()["files"][0]


def _doc(env, doc_id):
    db = env.Session()
    try:
        return db.query(cdb.Document).filter(cdb.Document.id == doc_id).first()
    finally:
        db.close()


def _library_titles(env, search=None):
    params = {"limit": 50}
    if search:
        params["search"] = search
    r = env.client.get("/api/documents/library", params=params)
    assert r.status_code == 200, r.text
    return {d["title"]: d for d in r.json()["documents"]}


def _disposition_name(header: str) -> str:
    """The name a browser saves the download as: RFC 6266 `filename*` wins."""
    m = re.search(r"filename\*=UTF-8''([^;]+)", header, re.IGNORECASE)
    assert m, header
    return unquote(m.group(1))


def _agent_list(env, search=None):
    from src.agent_tools.document_tools import ManageDocumentTool

    args = {"action": "list"}
    if search:
        args["search"] = search
    return asyncio.run(ManageDocumentTool().execute(json.dumps(args), {"owner": OWNER}))


def _send(env, upload):
    """The chat send turn: `ChatHandler.preprocess_message`, which both chat
    routes call, over a chat owned by the person who attached the file.

    Returns ``(documents it opened, what the model is sent, the attachment
    metadata saved with the message)``.
    """
    from types import SimpleNamespace

    from src.chat_handler import ChatHandler

    sess = SimpleNamespace(id="chat-1", owner=OWNER, model="m", endpoint_url="")
    opened = []
    handler = ChatHandler(None, None, None, None, None, env.handler)
    _msg, content, _ctx, _yt, meta = asyncio.run(handler.preprocess_message(
        "read this", [upload["id"]], sess, auto_opened_docs=opened))
    said = content if isinstance(content, str) else "".join(
        b.get("text", "") for b in content if isinstance(b, dict))
    return opened, said, meta


def _auto_document(env, upload):
    opened, said, meta = _send(env, upload)
    assert len(opened) == 1, opened
    return _doc(env, opened[0]["doc_id"]), said


# ── the owner's report, reproduced and closed ───────────────────────────────


@pytest.mark.parametrize("name,search", [
    (NAME, "Board Pack"),
    # A name the disk cannot hold as given (`:` and `?`): the title is still
    # the person's, not the stored file's `Minutes_ what we agreed_`.
    ("Minutes: what we agreed?", "agreed"),
])
def test_an_office_file_dropped_into_a_chat_is_not_titled_with_its_upload_id(env, name, search):
    """The owner's report. Measured before the row: `a1d9182aca87476e8e1c9754dbf13105`."""
    up = _upload(env, name + ".odt", _odt_document("Board minutes"))
    doc, _ = _auto_document(env, up)
    assert doc.title == name
    assert doc.source_name == name + ".odt"
    assert up["id"].split(".")[0] not in doc.title
    # Found in the library, and by the agent, under that name.
    assert name in _library_titles(env, search)
    listed = _agent_list(env, search)
    assert [d["title"] for d in listed["documents"]] == [name]
    assert listed["documents"][0]["source_name"] == name + ".odt"
    assert f"from `{name}.odt`" in listed["response"]


def test_a_pdf_dropped_into_a_chat_keeps_its_name_and_its_upload_key(env):
    """Title and source are the person's name; the PDF marker still carries the
    upload **id** — since the file is stored under its own name, a marker read
    off the stored path would point at nothing."""
    up = _upload(env, NAME + ".pdf", _minimal_pdf("board"), "application/pdf")
    doc, said = _auto_document(env, up)
    assert doc.title == NAME
    assert doc.source_name == NAME + ".pdf"
    assert f'upload_id="{up["id"]}"' in doc.current_content
    assert f"[PDF attached: {NAME}" in said
    r = env.client.get(f"/api/document/{doc.id}")
    assert r.status_code == 200 and r.json()["source_name"] == NAME + ".pdf"


# ── the chat attachment itself ───────────────────────────────────────────────


def test_a_chat_attachment_is_shown_stored_and_downloaded_under_its_name(env):
    up = _upload(env, NAME + ".pdf", _minimal_pdf("x"), "application/pdf")
    assert up["name"] == NAME + ".pdf"          # the chip, the image alt text
    row = env.handler.get_upload_info(up["id"])
    assert row["display_name"] == NAME + ".pdf"
    assert row["original_name"] == NAME + ".pdf"
    # On disk: `<date>/<id>/<the name>` — readable, and still keyed by the id.
    path = Path(row["path"])
    assert path.name == NAME + ".pdf" == row["stored_name"]
    assert path.parent.name == up["id"]
    from src.upload_handler import upload_path_matches_id
    assert upload_path_matches_id(str(path), up["id"])
    # The download: the name, `attachment`, nosniff.
    d = env.client.get(f"/api/upload/{up['id']}")
    assert d.status_code == 200
    cd = d.headers["content-disposition"]
    assert cd.startswith("attachment;")
    assert _disposition_name(cd) == NAME + ".pdf"
    assert "filename*=UTF-8''" in cd
    assert d.headers["x-content-type-options"] == "nosniff"
    assert d.content == _minimal_pdf("x")


def test_the_agent_is_handed_the_name_and_a_readable_path(env):
    from routes.chat_helpers import build_uploaded_file_manifest
    from src.attachment_refs import attachment_refs_from_metadata, persistable_message_content

    up = _upload(env, NAME + ".md", b"# minutes\n", "text/markdown")
    manifest = build_uploaded_file_manifest([up["id"]], env.handler, OWNER)
    assert manifest[0]["name"] == NAME + ".md"
    assert manifest[0]["id"] == up["id"]
    assert manifest[0]["path"] and Path(manifest[0]["path"]).name == NAME + ".md"
    # The send turn: what the model reads, and what is saved with the message —
    # which is what the chip says after a reload and what "open as document"
    # titles the document with.
    _opened, said, meta = _send(env, up)
    assert f"=== File: {NAME}.md ===" in said
    assert meta[0]["name"] == NAME + ".md"
    line = persistable_message_content([{"type": "text", "text": "hi"}], {"attachments": meta})
    assert f"[Attachment: {NAME}.md | id={up['id']}" in line
    assert attachment_refs_from_metadata({"attachments": meta})[0]["name"] == NAME + ".md"


def test_an_attachment_opened_as_text_is_titled_by_the_server_and_keeps_its_source(env):
    """The browser-side imports (library text files, *Import from device*, a
    text attachment opened as a document) send `source_name` and no title."""
    r = env.client.post("/api/document", json={
        "source_name": NAME + ".md", "content": "# minutes", "language": "markdown"})
    assert r.status_code == 200, r.text
    assert r.json()["title"] == NAME
    assert r.json()["source_name"] == NAME + ".md"
    # A title the caller sends is kept as sent; the source still rides along.
    r = env.client.post("/api/document", json={
        "title": f"{NAME} - Sheet1", "source_name": NAME + ".xlsx", "content": "a,b"})
    assert r.json()["title"] == f"{NAME} - Sheet1"
    assert r.json()["source_name"] == NAME + ".xlsx"
    # A document typed from scratch has no source.
    r = env.client.post("/api/document", json={"title": "Notes", "content": "x"})
    assert r.json()["source_name"] is None
    assert {NAME, f"{NAME} - Sheet1"} <= set(_library_titles(env))


def test_the_chat_image_reaches_the_gallery_under_its_name_and_its_hex_key(env):
    """`GENERATED_IMAGE_RE` stays the gallery's key (`FORBIDDEN.md` Part 2); the
    person's name goes beside it, in the field the gallery shows."""
    from PIL import Image
    from src.generated_images import GENERATED_IMAGE_RE

    buf = io.BytesIO()
    Image.new("RGB", (4, 4)).save(buf, "PNG")
    up = _upload(env, NAME + ".png", buf.getvalue(), "image/png")
    db = env.Session()
    try:
        img = db.query(cdb.GalleryImage).filter(cdb.GalleryImage.id == up["gallery_id"]).first()
    finally:
        db.close()
    assert img.prompt == NAME + ".png"
    assert GENERATED_IMAGE_RE.fullmatch(img.filename)


# ── the import routes ────────────────────────────────────────────────────────


@pytest.mark.parametrize("route,ext,body", [
    ("import-pdf", ".pdf", _minimal_pdf("imported")),
    ("import-office", ".odt", _odt_document("imported prose")),
], ids=["import-pdf", "import-office"])
def test_the_import_routes_title_and_store_the_file_by_its_name(env, route, ext, body):
    r = env.client.post(f"/api/documents/{route}",
                        files={"file": (NAME + ext, body, "application/octet-stream")})
    assert r.status_code == 200, r.text
    doc = r.json()
    assert doc["title"] == NAME
    assert doc["source_name"] == NAME + ext
    assert NAME in _library_titles(env, "Board")
    # The stored upload behind it is readable and downloads under the name.
    rows = [row for row in env.handler._load_upload_index().values()
            if row.get("display_name") == NAME + ext]
    assert len(rows) == 1 and Path(rows[0]["path"]).name == NAME + ext
    d = env.client.get(f"/api/upload/{rows[0]['id']}")
    assert _disposition_name(d.headers["content-disposition"]) == NAME + ext


@pytest.mark.parametrize("route,ext,body", [
    ("import-pdf", ".pdf", _minimal_pdf("evil")),
    ("import-office", ".odt", _odt_document("evil prose")),
], ids=["import-pdf", "import-office"])
def test_an_import_named_with_a_folder_is_titled_without_it(env, route, ext, body):
    """Measured before the row: `../../evil.pdf` was titled `../../evil`."""
    r = env.client.post(f"/api/documents/{route}",
                        files={"file": ("../../evil" + ext, body, "application/octet-stream")})
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "evil"
    assert r.json()["source_name"] == "evil" + ext


def test_importing_the_same_file_under_another_name_titles_it_by_that_name(env):
    """`save_upload` hands back the first copy's row for identical bytes; the
    title must come from what THIS import was called."""
    body = _minimal_pdf("same bytes")
    env.client.post("/api/documents/import-pdf", files={"file": ("first.pdf", body, "application/pdf")})
    r = env.client.post("/api/documents/import-pdf", files={"file": ("second.pdf", body, "application/pdf")})
    assert r.json()["title"] == "second"
    assert r.json()["source_name"] == "second.pdf"


# ── the mailbox ──────────────────────────────────────────────────────────────


def _email_with(name_header: str, payload: bytes) -> bytes:
    """A real MIME message whose attachment's filename is *name_header*."""
    msg = EmailMessage()
    msg["Subject"] = "board pack"
    msg["Message-ID"] = "<m@x>"
    msg.set_content("see attached")
    msg.add_attachment(payload, maintype="application", subtype="octet-stream",
                       filename=name_header)
    return msg.as_bytes()


def _open_from_mailbox(env, monkeypatch, raw: bytes):
    @contextlib.contextmanager
    def fake_imap(account_id=None, owner=""):
        yield type("C", (), {"select": lambda self, *a, **k: None})()

    monkeypatch.setattr(env.email_routes, "_imap", fake_imap)
    monkeypatch.setattr(env.email_routes, "_imap_uid_fetch",
                        lambda *a, **k: ("OK", [(None, raw)]))
    r = env.client.post("/api/email/attachment-as-doc/42/0")
    assert r.status_code == 200, r.text
    assert r.json().get("doc_id"), r.json()
    return _doc(env, r.json()["doc_id"])


def test_a_pdf_from_the_mailbox_is_titled_stored_and_downloaded_by_its_name(env, monkeypatch):
    """Measured before the row: titled `Q3 Board Pack _ final _v2_`, copied to
    `<date>/<uuid>.pdf` with no upload record, downloaded as `<uuid>.pdf`."""
    doc = _open_from_mailbox(env, monkeypatch, _email_with(NAME + ".pdf", _minimal_pdf("mail")))
    assert doc.title == NAME
    assert doc.source_name == NAME + ".pdf"
    upload_id = re.search(r'upload_id="([^"]+)"', doc.current_content).group(1)
    row = env.handler.get_upload_info(upload_id)
    assert row is not None, "the mailbox PDF still has no upload record"
    assert row["owner"] == OWNER and row["display_name"] == NAME + ".pdf"
    assert Path(row["path"]).name == NAME + ".pdf"
    d = env.client.get(f"/api/upload/{upload_id}")
    assert d.status_code == 200
    assert _disposition_name(d.headers["content-disposition"]) == NAME + ".pdf"
    assert NAME in _library_titles(env, "Board")


def test_a_text_attachment_from_the_mailbox_is_owned_and_leaves_other_documents_alone(env, monkeypatch):
    """Two defects in one helper, both measured: the document had no owner (so
    the library, which matches `owner == user`, could not show it), and opening
    it soft-deleted every active document in the database — everyone's."""
    db = env.Session()
    for i in range(3):
        db.add(cdb.Document(id=f"bob-{i}", title=f"bob {i}", current_content="x",
                            owner="bob", is_active=True))
    db.add(cdb.Document(id="alice-0", title="kept", current_content="x",
                        owner=OWNER, is_active=True))
    db.commit()
    db.close()

    doc = _open_from_mailbox(env, monkeypatch, _email_with(NAME + ".txt", b"plain body\n"))
    assert doc.title == NAME and doc.source_name == NAME + ".txt"
    assert doc.owner == OWNER
    assert {NAME, "kept"} <= set(_library_titles(env))
    db = env.Session()
    try:
        assert all(d.is_active for d in db.query(cdb.Document).all())
    finally:
        db.close()


def test_an_rfc_2047_encoded_attachment_name_is_decoded_not_shown_as_base64(env, monkeypatch):
    """What a mail client sends for a non-ASCII name — `=?UTF-8?B?…?=`, which is
    base64. The title is the name it encodes."""
    import base64

    encoded = "=?UTF-8?B?" + base64.b64encode((NAME + ".txt").encode()).decode() + "?="
    msg = EmailMessage()
    msg["Subject"] = "t"
    msg.set_content("body")
    msg.add_attachment(b"notes\n", maintype="text", subtype="plain")
    att = list(msg.iter_attachments())[0]
    del att["Content-Disposition"]
    att["Content-Disposition"] = f'attachment; filename="{encoded}"'
    doc = _open_from_mailbox(env, monkeypatch, msg.as_bytes())
    assert doc.title == NAME
    assert "UTF-8" not in doc.title and "=?" not in doc.title


# ── the personal / RAG store ─────────────────────────────────────────────────


def test_a_personal_upload_is_stored_under_its_name_with_a_suffix_only_on_collision(env):
    """Measured before the row: `Q3_Board_Pack_final_v2-85e79bb862.pdf`, renamed
    even with nothing to collide with."""
    for _ in range(2):
        r = env.client.post("/api/personal/upload",
                            files={"files": (NAME + ".txt", b"board notes\n", "text/plain")})
        assert r.status_code == 200, r.text
        assert r.json()["uploaded"] == [NAME + ".txt"]
    stored = sorted(os.listdir(env.tmp / "personal" / OWNER))
    assert stored == [f"{NAME} (2).txt", f"{NAME}.txt"]
    assert {m["filename"] for m in env.indexed} == {NAME + ".txt"}
    assert {m["stored_filename"] for m in env.indexed} == set(stored)


# ── hostile names, through the chat door and the download ───────────────────

LONG = "x" * 296 + ".txt"


@pytest.mark.parametrize("raw,shown,on_disk", [
    ("../../evil.txt", "evil.txt", "evil.txt"),
    ("C:\\Users\\me\\evil.txt", "evil.txt", "evil.txt"),
    ("CON.txt", "CON.txt", "CON_.txt"),
    ("nul", "nul", "nul_"),
    ("invoice\u202eFDP.exe", "invoiceFDP.exe", "invoiceFDP.exe"),
    (".env", ".env", "env"),
    ("report. ", "report.", "report"),
    ("a:b*c?<d>|.txt", "a:b*c?<d>|.txt", "a_b_c__d__.txt"),
])
def test_a_hostile_name_is_made_safe_and_the_original_is_what_is_shown(env, raw, shown, on_disk):
    up = _upload(env, raw, b"hostile bytes " + raw.encode("utf-8", "replace"))
    assert up["name"] == shown
    row = env.handler.get_upload_info(up["id"])
    path = Path(row["path"])
    assert path.name == on_disk
    # Never anywhere but its own directory under the upload root.
    assert path.parent.name == up["id"]
    assert os.path.commonpath([str(path.resolve()), str(Path(env.handler.upload_dir).resolve())]) \
        == str(Path(env.handler.upload_dir).resolve())
    d = env.client.get(f"/api/upload/{up['id']}")
    assert d.status_code == 200
    cd = d.headers["content-disposition"]
    assert cd.startswith("attachment;"), cd
    assert "\r" not in cd and "\n" not in cd and "\u202e" not in unquote(cd)
    assert _disposition_name(cd) == shown
    assert d.headers["x-content-type-options"] == "nosniff"


def test_control_characters_never_reach_a_name(env):
    """A browser percent-encodes controls in a multipart filename, so this is
    driven through `save_upload` — the mailbox and the agent hand names over
    without that encoding."""
    from types import SimpleNamespace

    meta = env.handler.save_upload(
        SimpleNamespace(filename="tab\there\x00\x1b[31m\u2028.txt", file=io.BytesIO(b"c")),
        "127.0.0.1", owner=OWNER)
    assert meta["display_name"] == "tab here[31m .txt"
    assert Path(meta["path"]).name == "tab here[31m .txt"
    assert attachment_disposition(meta["display_name"]).isprintable()


def test_a_300_character_name_is_capped_and_keeps_its_extension(env):
    up = _upload(env, LONG, b"long")
    assert len(up["name"]) <= file_names.DISPLAY_NAME_MAX_CHARS
    assert up["name"].endswith(".txt")
    on_disk = Path(env.handler.get_upload_info(up["id"])["path"]).name
    assert len(on_disk.encode()) <= file_names.STORED_NAME_MAX_BYTES
    assert on_disk.endswith(".txt") and on_disk.startswith("xxxx")
    assert env.client.get(f"/api/upload/{up['id']}").status_code == 200


def test_a_name_on_the_sensitive_list_is_stored_as_given_and_the_list_still_holds(env):
    """`_resolve_tool_path`'s sensitive names (`FORBIDDEN.md` Part 2) are not
    renamed around: `id_rsa` is stored as `id_rsa`, the agent's file tools still
    refuse it, and the manifest therefore hands the agent no path to it."""
    from routes.chat_helpers import build_uploaded_file_manifest
    from src.tool_execution import _resolve_tool_path

    up = _upload(env, "id_rsa", b"-----BEGIN KEY-----\n")
    path = env.handler.get_upload_info(up["id"])["path"]
    assert Path(path).name == "id_rsa"
    with pytest.raises(ValueError):
        _resolve_tool_path(path)
    manifest = build_uploaded_file_manifest([up["id"]], env.handler, OWNER)
    assert manifest[0]["name"] == "id_rsa" and manifest[0]["path"] is None


def test_an_svg_named_readably_still_goes_through_the_svg_gate(env):
    """A readable name can only widen the SVG gate: the download is asked of
    both the ASCII name and the person's, and is still `attachment`."""
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    up = _upload(env, NAME + ".svg", svg, "image/svg+xml")
    assert "gallery_id" not in up            # `IMAGE_EXTS` excludes svg
    d = env.client.get(f"/api/upload/{up['id']}")
    assert d.headers["content-disposition"].startswith("attachment")
    assert d.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in d.headers.get("content-security-policy", "")


def test_an_svg_whose_ascii_name_lost_its_extension_still_goes_through_the_svg_gate(env):
    """`схема.svg` folds to `svg` in ASCII — no extension — so a gate asked only
    of the ASCII name lets it out as plain bytes. Asked of the person's name too,
    it is caught."""
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    up = _upload(env, "\u0441\u0445\u0435\u043c\u0430.svg", svg, "image/svg+xml")
    assert up["name"] == "\u0441\u0445\u0435\u043c\u0430.svg"
    d = env.client.get(f"/api/upload/{up['id']}")
    assert d.headers["content-disposition"].startswith("attachment")
    assert "sandbox" in d.headers.get("content-security-policy", "")


# ── the key stays the key ────────────────────────────────────────────────────


def test_a_download_does_not_walk_the_store_when_the_row_knows_the_path(env, monkeypatch):
    """The index row's path is believed when it is inside the root and inside
    the id's own directory, so a download is one lookup, not a walk over every
    upload ever made — which is what finding a file NAMED `<id>` used to cost
    once the file stopped being named that."""
    import routes.upload_routes as upload_routes
    import src.upload_handler as uh

    up = _upload(env, NAME + ".txt", b"direct")

    def no_walk(*a, **k):
        raise AssertionError("walked the whole upload store")

    monkeypatch.setattr(upload_routes.os, "walk", no_walk)
    monkeypatch.setattr(uh.os, "walk", no_walk)
    d = env.client.get(f"/api/upload/{up['id']}")
    assert d.status_code == 200 and d.content == b"direct"


@pytest.mark.parametrize("stale", ["missing", "inside-but-gone"])
def test_a_row_whose_path_is_gone_is_found_again_by_the_id_directory(env, stale):
    """A row with no path, or one naming a file inside the root that is not
    there, falls back to the walk — which looks for the id, so it finds the
    `<id>/` directory and the file the row says is in it. (A path OUTSIDE the
    root is refused outright, as it always was.)"""
    up = _upload(env, NAME + ".txt", b"moved")
    index = env.handler._load_upload_index(fail_on_error=True)
    for row in index.values():
        if stale == "missing":
            row.pop("path")
        else:
            row["path"] = str(Path(env.handler.upload_dir) / "1999" / "01" / "01" / "gone.txt")
    env.handler._atomic_write_json(os.path.join(env.handler.upload_dir, "uploads.json"), index)
    info = env.handler.resolve_upload(up["id"], owner=OWNER)
    assert info and Path(info["path"]).name == NAME + ".txt"
    assert Path(info["path"]).parent.name == up["id"]
    d = env.client.get(f"/api/upload/{up['id']}")
    assert d.status_code == 200 and d.content == b"moved"


def test_an_index_row_pointing_at_another_uploads_file_is_refused(env):
    """The id is bound to the file by where it sits on disk, not by the index
    alone: a row whose path leads into a different upload's directory does not
    resolve, by reservation or by download."""
    mine = _upload(env, "mine.txt", b"mine")
    other = _upload(env, "other.txt", b"other")
    index = env.handler._load_upload_index(fail_on_error=True)
    other_path = env.handler.get_upload_info(other["id"])["path"]
    for row in index.values():
        if row["id"] == mine["id"]:
            row["path"] = other_path
    env.handler._atomic_write_json(os.path.join(env.handler.upload_dir, "uploads.json"), index)
    assert env.handler.reserve_upload(mine["id"], owner=OWNER) is None
    # The download does not believe the row either: it finds `mine`'s own
    # directory and serves `mine`, never `other`.
    d = env.client.get(f"/api/upload/{mine['id']}")
    assert d.status_code == 200 and d.content == b"mine"


def test_an_upload_from_before_the_row_still_resolves_and_downloads_under_its_name(env):
    """`Law 1`: a file stored as `<date>/<id>` with a row that has no
    `display_name` — every upload until today — still resolves, and is now
    downloaded and shown under the person's name, recovered from the
    `original_name` every row has always carried."""
    upload_root = Path(env.handler.upload_dir)
    legacy_id = "b" * 32 + ".pdf"
    legacy = upload_root / "2026" / "09" / "30" / legacy_id
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"%PDF-1.4 legacy")
    stamp = "2026-09-30T10:00:00"
    env.handler._atomic_write_json(str(upload_root / "uploads.json"), {
        f"{OWNER}:h": {"id": legacy_id, "path": str(legacy), "mime": "application/pdf",
                       "size": 15, "name": "Q3_Board_Pack_final_v2.pdf",
                       "original_name": NAME + ".pdf", "hash": "h", "owner": OWNER,
                       "uploaded_at": stamp, "created_at": stamp, "last_accessed": stamp}})
    info = env.handler.resolve_upload(legacy_id, owner=OWNER)
    assert info["path"] == str(legacy)
    assert upload_display_name(info) == NAME + ".pdf"
    d = env.client.get(f"/api/upload/{legacy_id}")
    assert d.status_code == 200 and d.content == b"%PDF-1.4 legacy"
    assert _disposition_name(d.headers["content-disposition"]) == NAME + ".pdf"


def test_cleanup_sweeps_an_expired_upload_in_its_id_directory_and_keeps_a_referenced_one(env):
    """Retention reads the id off the directory, so a readable name changes
    nothing about what is kept: referenced stays, unreferenced and old goes,
    and its emptied directory goes with it."""
    old = "2020-01-01T00:00:00"
    kept = _upload(env, "kept.txt", b"kept")
    swept = _upload(env, "swept.txt", b"swept")
    upload_root = Path(env.handler.upload_dir)
    index = env.handler._load_upload_index(fail_on_error=True)
    moved = {}
    for row in index.values():
        src = Path(row["path"])
        dest = upload_root / "2020" / "01" / "01" / row["id"] / src.name
        dest.parent.mkdir(parents=True)
        src.rename(dest)
        row["path"] = str(dest)
        row["uploaded_at"] = row["created_at"] = row["last_accessed"] = old
        moved[row["id"]] = dest
    env.handler._atomic_write_json(str(upload_root / "uploads.json"), index)
    removed = env.handler.cleanup_old_uploads({kept["id"]}, set())
    assert removed == 1
    assert moved[kept["id"]].is_file()
    assert not moved[swept["id"]].exists()
    assert not moved[swept["id"]].parent.exists()
    assert env.handler.get_upload_info(swept["id"]) is None


# ── the migration ────────────────────────────────────────────────────────────


def test_the_migration_adds_the_column_and_leaves_existing_documents_as_they_were(tmp_path, monkeypatch):
    db_path = tmp_path / "old.db"
    con = sqlite3.connect(db_path)
    con.execute("CREATE TABLE documents (id VARCHAR PRIMARY KEY, session_id VARCHAR, "
                "title VARCHAR NOT NULL, language VARCHAR, current_content TEXT NOT NULL, "
                "version_count INTEGER, is_active BOOLEAN, owner VARCHAR)")
    con.execute("INSERT INTO documents VALUES ('d1', NULL, 'Old report', 'markdown', "
                "'# body', 3, 1, 'alice')")
    con.commit()
    con.close()
    engine = create_engine(f"sqlite:///{db_path}", poolclass=NullPool)
    monkeypatch.setattr(cdb, "engine", engine)

    cdb._migrate_add_document_source_name_column()
    cdb._migrate_add_document_source_name_column()   # idempotent

    with engine.connect() as conn:
        cols = [r[1] for r in conn.execute(text("PRAGMA table_info(documents)"))]
        row = conn.execute(text("SELECT id, title, language, current_content, "
                                "version_count, is_active, owner, source_name "
                                "FROM documents")).one()
    assert cols.count("source_name") == 1
    assert tuple(row) == ("d1", "Old report", "markdown", "# body", 3, 1, "alice", None)


def test_an_existing_document_reads_back_with_no_source_and_its_title_unchanged(env):
    db = env.Session()
    db.add(cdb.Document(id="old-1", title="Typed by hand", current_content="x", owner=OWNER))
    db.commit()
    db.close()
    r = env.client.get("/api/document/old-1")
    assert r.json()["title"] == "Typed by hand"
    assert r.json()["source_name"] is None


# ── the naming rules themselves ──────────────────────────────────────────────


@pytest.mark.parametrize("raw,title", [
    (NAME + ".pdf", NAME),
    ("archive.tar.gz", "archive.tar"),
    ("Budget v1.5", "Budget v1.5"),          # `.5` is not an extension
    ("Minutes 2026.10", "Minutes 2026.10"),
    ("v1.2 notes", "v1.2 notes"),
    (".env", ".env"),
    ("dir/sub/report.docx", "report"),
    ("", "Untitled"),
    ("..", "Untitled"),
])
def test_the_title_is_the_name_without_its_extension(raw, title):
    assert document_title(raw) == title


@pytest.mark.parametrize("raw,expected", [
    ('a"b".txt', "a_b_.txt"),
    (".CON.txt", "CON_.txt"),             # the dot goes first, then the device check
    ("COM1.tar.gz", "COM1_.tar.gz"),
    ("lpt9", "lpt9_"),
    ("CONSOLE.txt", "CONSOLE.txt"),       # only the exact device name
    ("-rf", "rf"),
    ("...", "upload"),
    ("Résumé\u0301.pdf", "Résumé\u0301.pdf"),
])
def test_the_stored_name_is_the_name_made_storable(raw, expected):
    import unicodedata

    assert stored_name(raw) == unicodedata.normalize("NFC", expected)


def test_names_are_nfc_normalised_so_one_name_is_one_name():
    decomposed = "Re\u0301sume\u0301.pdf"
    assert display_name(decomposed) == "Résumé.pdf"
    assert stored_name(decomposed) == "Résumé.pdf"


def test_the_download_header_is_always_attachment_and_rfc_6266():
    for raw in (NAME + ".pdf", "x.svg", "../../etc/passwd", "a\r\nX-Evil: 1.txt", ""):
        cd = attachment_disposition(raw)
        assert cd.startswith("attachment; filename=\"")
        assert "filename*=UTF-8''" in cd
        assert "\r" not in cd and "\n" not in cd
    assert _disposition_name(attachment_disposition("../../etc/passwd")) == "passwd"
    assert _disposition_name(attachment_disposition(NAME + ".pdf")) == NAME + ".pdf"
