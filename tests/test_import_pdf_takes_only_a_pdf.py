# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1154` (f-import) — `POST /api/documents/import-pdf` makes a document only
out of a PDF, and says what anything else is.

Measured on the tree before this row, through this route with the real files
below: a `.docx`, a PNG, a `.txt` and a PNG named `scan.pdf` each answered
**200** and became a "PDF" document whose body was *"[PDF processing failed:
Stream has ended unexpectedly]"* and whose ``pdf_source`` marker pointed the
page view at a file that is not a PDF. `import-office` refuses a format it has
no reader for before a byte is written (`B233`); this route checked nothing.

Every case drives the real routers (the `P21-03` harness: real
``UploadHandler`` on a temp store, real SQLite file) with real LibreOffice files
from ``tests/helpers/office_fixtures.py`` (`Law 20`); the browser case runs the
Library's per-file import under node against them on a loopback socket.
"""
import json
from pathlib import Path

import pytest

import core.database as cdb
from tests.helpers.office_fixtures import office_fixture
from tests.test_a_file_imported_from_device_opens_readable import _device, live  # noqa: F401
from tests.test_an_uploaded_document_keeps_its_name import env  # noqa: F401
from tests.test_attachment_extension_registers import _minimal_pdf

PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"


def _post(env, name, body, mime="application/octet-stream"):
    return env.client.post("/api/documents/import-pdf", files={"file": (name, body, mime)})


def _stored(env) -> list:
    """Every file the upload store holds, and every row its index has."""
    root = Path(env.handler.upload_dir)
    files = [p for p in root.rglob("*") if p.is_file() and not p.name.startswith("uploads.json")]
    return files + list(env.handler._load_upload_index().values())


def _charged(env) -> int:
    return sum(len(v) for v in env.handler.upload_rate_log.values())


def _documents(env) -> int:
    db = env.Session()
    try:
        return db.query(cdb.Document).count()
    finally:
        db.close()


# (file name, bytes, what the refusal must say it is)
NOT_A_PDF = [
    ("Launch plan.docx", office_fixture(".docx"), "is not a PDF: it is a .docx file"),
    ("Regional sales.xlsx", office_fixture(".xlsx"), "is not a PDF: it is a .xlsx file"),
    ("Launch deck.pptx", office_fixture(".pptx"), "is not a PDF: it is a .pptx file"),
    ("Team photo.png", PNG, "is not a PDF: it is a .png file"),
    ("Shopping list.txt", b"Eggs, milk.\n", "is not a PDF: it is a .txt file"),
    ("Landing page.html", b"<!doctype html><p>hi</p>", "is not a PDF: it is a .html file"),
    # The mis-named file a person actually has: a scan saved as an image.
    ("scan.pdf", PNG, "is not a PDF: it is a PNG image"),
    ("Minutes 1997.pdf", office_fixture(".doc"), "is not a PDF: it is a legacy Office file (.doc, .xls or .ppt)"),
    ("broken.pdf", b"not a pdf at all", "is not a PDF: its contents do not begin with a PDF header"),
]


@pytest.mark.parametrize("name,body,said", NOT_A_PDF, ids=[n for n, _, _ in NOT_A_PDF])
def test_a_file_that_is_not_a_pdf_is_refused_saying_what_it_is(env, name, body, said):  # noqa: F811
    r = _post(env, name, body)
    assert r.status_code == 415, r.text
    assert r.json()["detail"] == f"{name} {said}."
    # Refused at the door: nothing stored, nothing charged, no document.
    assert _stored(env) == []
    assert _charged(env) == 0
    assert _documents(env) == 0


def test_a_real_pdf_still_imports_as_a_pdf_document(env):  # noqa: F811
    r = _post(env, "Signed lease – 2026.pdf", _minimal_pdf("PDFSENTINEL lease"), "application/pdf")
    assert r.status_code == 200, r.text
    doc = r.json()
    assert doc["title"] == "Signed lease – 2026"
    content = doc.get("current_content") or doc.get("content") or ""
    assert '<!-- pdf_source upload_id="' in content and "PDFSENTINEL" in content
    assert _charged(env) == 1 and _documents(env) == 1


@pytest.mark.parametrize("name,body", [
    # The bytes decide, not the name: a PDF saved without its extension.
    ("Scanned contract", _minimal_pdf("NOEXTSENTINEL")),
    # Readers accept the header anywhere in the first 1024 bytes.
    ("Prefixed.pdf", b"\r\n" * 40 + _minimal_pdf("PREFIXSENTINEL")),
])
def test_a_pdf_the_name_or_a_prefix_hides_still_imports(env, name, body):  # noqa: F811
    r = _post(env, name, body)
    assert r.status_code == 200, r.text
    content = r.json().get("current_content") or ""
    assert "SENTINEL" in content


def test_a_refusal_is_not_charged_against_the_upload_rate(env):  # noqa: F811
    env.handler.upload_rate_limit = 1
    env.handler.upload_burst_limit = 1
    assert _post(env, "scan.pdf", PNG).status_code == 415
    assert _post(env, "scan.pdf", PNG).status_code == 415
    # The one upload the window allows is still there for the real PDF.
    assert _post(env, "real.pdf", _minimal_pdf("RATESENTINEL")).status_code == 200


def test_the_library_door_says_it_in_words(live):  # noqa: F811
    """A scan saved as PNG and named `.pdf`, picked in *Import from device*."""
    shown = _device(live, "scan.pdf", PNG, "application/pdf")
    assert shown["pickerOpened"] and shown["tabs"] == []
    assert any("scan.pdf is not a PDF: it is a PNG image." in m for m in shown["errors"]), \
        shown["errors"]
    assert _documents(live) == 0
