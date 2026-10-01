# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1007` — a signed reply and an annotated PDF leave Pantheon under the document's own name.

Both were named by `_slug`, which kept `[A-Za-z0-9._-]` and dropped every other
letter: measured on `4e65b71` through the routes below, a form titled
`Q3 Board Pack – final (v2)` replied with `Q3_Board_Pack_final_v2_signed.pdf`
and exported as `Q3_Board_Pack_final_v2_annotated.pdf`; one titled
`схема договора` as `form_signed.pdf` and `form_annotated.pdf`. The reply was
also staged without the mailbox's own helpers, re-deriving the compose
directory and token format beside `B1000`'s.

Driven through the real document router over `P21-03`'s harness (a real upload
store, a real SQLite file): the PDF is imported through `import-pdf`, exported
through `GET …/export-pdf`, and replied to through `POST …/prepare-signed-reply`,
whose staged attachment is then built into an outgoing part by the mailbox's
own `_attach_compose_uploads` and read back by a mail parser (`Law 20`). The one
stand-in is the form filler: `src/pdf_forms.fill_fields` needs PyMuPDF, an
optional dependency this environment does not carry, so it copies the PDF
through unchanged — what it would write into the pages is not this row.
"""
from email import message_from_bytes, policy
from email.mime.multipart import MIMEMultipart
from urllib.parse import unquote

import pytest

import core.database as cdb
import routes.email_helpers as EH
from routes.document.document_helpers import _pdf_export_name
from src.file_names import attachment_disposition
from tests.test_an_uploaded_document_keeps_its_name import NAME, env  # noqa: F401
from tests.test_attachment_extension_registers import _minimal_pdf

CYRILLIC = "схема договора"


def _form(env, title):
    """A PDF imported through the library, then titled *title* — the export
    and the reply read the document's title, not the file's."""
    r = env.client.post("/api/documents/import-pdf",
                        files={"file": ("scan.pdf", _minimal_pdf("form"), "application/pdf")})
    assert r.status_code == 200, r.text
    doc_id = r.json()["id"]
    db = env.Session()
    try:
        row = db.query(cdb.Document).filter(cdb.Document.id == doc_id).one()
        row.title = title
        row.source_email_uid = "7"
        row.source_email_folder = "INBOX"
        db.commit()
    finally:
        db.close()
    return doc_id


def _filename_star(header: str) -> str:
    value = header.split("filename*=", 1)[1]
    assert value.startswith("UTF-8''"), header
    return unquote(value[len("UTF-8''"):])


@pytest.fixture(autouse=True)
def _filler(monkeypatch):
    import shutil
    import src.pdf_forms as pdf_forms

    monkeypatch.setattr(pdf_forms, "fill_fields",
                        lambda src, dst, values: shutil.copyfile(src, dst))


@pytest.fixture
def compose(env, tmp_path, monkeypatch):
    staged = tmp_path / "compose"
    staged.mkdir()
    monkeypatch.setattr(EH, "COMPOSE_UPLOADS_DIR", staged)
    return staged


@pytest.mark.parametrize("title,expected", [
    (NAME, f"{NAME} (annotated).pdf"),
    (CYRILLIC, f"{CYRILLIC} (annotated).pdf"),
], ids=["board-pack", "cyrillic"])
def test_the_annotated_export_downloads_under_the_title(env, title, expected):
    doc_id = _form(env, title)
    r = env.client.get(f"/api/document/{doc_id}/export-pdf")
    assert r.status_code == 200, r.text
    assert r.content.startswith(b"%PDF")
    header = r.headers["content-disposition"]
    assert header == attachment_disposition(expected), header
    assert header.startswith("attachment;"), "never inline (`FORBIDDEN.md` Part 2)"
    assert _filename_star(header) == expected


@pytest.mark.parametrize("title,expected", [
    (NAME, f"{NAME} (signed).pdf"),
    (CYRILLIC, f"{CYRILLIC} (signed).pdf"),
], ids=["board-pack", "cyrillic"])
def test_the_signed_reply_is_sent_under_the_title(env, compose, title, expected):
    doc_id = _form(env, title)
    r = env.client.post(f"/api/document/{doc_id}/prepare-signed-reply")
    assert r.status_code == 200, r.text
    attachment = r.json()["attachment"]
    assert attachment["filename"] == expected
    token = attachment["token"]
    key, _, stored = token.partition("_")
    assert len(key) == 32 and (compose / token).is_file(), "staged where the mailbox sends from"
    assert stored == EH.stored_name(expected)
    # What the recipient receives: the mailbox's own part builder, read back.
    outer = MIMEMultipart()
    EH._attach_compose_uploads(outer, [token])
    parsed = message_from_bytes(outer.as_bytes(), policy=policy.default)
    [part] = list(parsed.iter_attachments())
    assert part.get_filename() == expected
    assert part.get_content_disposition() == "attachment"


def test_a_name_that_cannot_be_stored_as_given_is_kept_beside_it(env, compose):
    """`Minutes: what we agreed?` is the person's title; the file on disk is
    `Minutes_ what we agreed_ (signed).pdf`, and the recipient still gets the
    title — `B1000`'s kept name, written by the same helper."""
    doc_id = _form(env, "Minutes: what we agreed?")
    attachment = env.client.post(f"/api/document/{doc_id}/prepare-signed-reply").json()["attachment"]
    assert attachment["filename"] == "Minutes: what we agreed? (signed).pdf"
    assert attachment["token"].split("_", 1)[1] == "Minutes_ what we agreed_ (signed).pdf"
    assert EH._compose_upload_name(attachment["token"]) == "Minutes: what we agreed? (signed).pdf"


@pytest.mark.parametrize("title,expected", [
    ("", "form (signed).pdf"),
    (None, "form (signed).pdf"),
    ("Scan.PDF", "Scan (signed).pdf"),
    ("Q3/Q4 plan", "Q3_Q4 plan (signed).pdf"),
    ("invoice‮FDP.exe", "invoiceFDP.exe (signed).pdf"),
    ("x" * 300, "x" * (255 - len(" (signed).pdf")) + " (signed).pdf"),
], ids=["empty", "none", "pdf-in-title", "slash", "bidi", "long"])
def test_the_name_rules(title, expected):
    """A title that is nothing gets the old fallback; a `.pdf` it already ends
    in is not doubled; a `/` is part of a title, not a folder; a bidi override
    is not drawn; a long title is cut and the suffix kept."""
    assert _pdf_export_name(title, "signed") == expected
