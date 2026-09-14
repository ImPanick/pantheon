# SPDX-License-Identifier: AGPL-3.0-or-later
"""The three extension registers chat ingest reads, driven end to end.

`B05` said `upload_handler.is_document_file`'s extension list must be a subset
of `document_processor._is_text_file`. Measured, that rule is false and must
never be made true: the 34 accepted extensions minus the 28 text ones are
`.docx .epub .pdf .pptx .xls .xlsx`, and putting `.pdf` in the text arm would
feed a binary stream to the model as source code. The true rule is a union of
three registers — `TEXT_EXTS`, `MARKITDOWN_EXTS`, `PDF_EXTS` — and it is now an
identity (`INGESTIBLE_EXTS`) rather than a relation something has to police.

These tests drive `build_user_content` and `UploadHandler.is_document_file`
rather than reading either file, because the thing that matters is whether the
bytes reach the model, not what the sets look like.
"""
import io
import zipfile

import pytest

from src.document_processor import (
    INGESTIBLE_EXTS,
    TEXT_EXTS,
    _is_text_file,
    build_user_content,
)
from src.markitdown_runtime import MARKITDOWN_EXTS
from src.pdf_runtime import PDF_EXTS
from src.upload_handler import UploadHandler

SENTINEL = "SENTINELattachmentBODY7f3a"

# The measured baseline, spelled out rather than imported. A test that takes its
# expectations from the register it is testing proves only that the code agrees
# with itself: dropping `.tsx` from TEXT_EXTS also drops it from the sweep, and
# nothing fails. These 34 are what upload acceptance was measured to be, and
# eleven of them (`.go .bash .tsx .jsx .php .yaml .yml .rs .sql .rb .xml`) were
# silently discarded until `P2-06` — losing one again is a regression, not a
# refactor. Nothing in production reads this list; it is a pin, not a register.
EXPECTED_TEXT = frozenset({
    ".txt", ".py", ".html", ".htm", ".md", ".json", ".csv", ".log", ".js", ".nix",
    ".bash", ".c", ".cpp", ".css", ".go", ".h", ".java", ".jsx", ".php", ".rb",
    ".rs", ".sh", ".sql", ".ts", ".tsx", ".xml", ".yaml", ".yml",
})
# Accepted, and never readable as text: the six the row wanted moved into the
# text arm. `_process_text_file` would hand the model a binary stream.
EXPECTED_BINARY_DOC = frozenset({".docx", ".epub", ".pdf", ".pptx", ".xls", ".xlsx"})
EXPECTED_ACCEPTED = EXPECTED_TEXT | EXPECTED_BINARY_DOC

# The banner emitted when nothing can read the file. No accepted extension may
# ever produce it — that is the whole point of deriving the accepted set from
# the extractors.
NO_EXTRACTOR = "No extractor covers this file type"

# Extensions no register names, measured by driving build_user_content: each
# one uploads fine, renders a chip, and delivers zero bytes.
UNREGISTERED = (
    ".markdown", ".tsv", ".rst", ".toml", ".ini", ".conf", ".env", ".ipynb",
    ".doc", ".odt", ".rtf",
)


def _handler(tmp_path):
    return UploadHandler(str(tmp_path), str(tmp_path / "uploads"))


def _render(tmp_path, handler, name, body: bytes, mime=None):
    """Drive the real build_user_content over one real file on disk."""
    path = tmp_path / "uploads" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    resolved = {"fid": {"path": str(path), "name": name, "mime": mime}}
    out = build_user_content(
        "please read this", ["fid"], str(tmp_path / "uploads"), handler,
        owner="tester", resolved_uploads=resolved,
    )
    if isinstance(out, str):
        return out
    return "".join(b.get("text", "") for b in out if isinstance(b, dict))


def _minimal_pdf(text: str) -> bytes:
    """A real one-page PDF with one text run, so pypdf has something to find."""
    stream = f"BT /F1 24 Tf 72 700 Td ({text}) Tj ET".encode()
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objs, 1):
        offsets.append(len(out))
        out += str(i).encode() + b" 0 obj\n" + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 " + str(len(objs) + 1).encode() + b"\n0000000000 65535 f \n"
    for off in offsets:
        out += ("%010d 00000 n \n" % off).encode()
    out += (b"trailer\n<< /Size " + str(len(objs) + 1).encode() + b" /Root 1 0 R >>\n"
            b"startxref\n" + str(xref).encode() + b"\n%%EOF\n")
    return bytes(out)


def _minimal_docx(text: str) -> bytes:
    """A .docx both extraction paths can read.

    markitdown handles it when the optional dep is installed; the bundled
    pure-Python <w:t> extractor handles it when it is not. The sentinel carries
    no underscores because markitdown escapes them on the way out.
    """
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    doc = (f'<?xml version="1.0"?><w:document xmlns:w="{ns}"><w:body>'
           f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", doc)
    return buf.getvalue()


# --------------------------------------------------------------------------
# The union is an identity, not a subset relation
# --------------------------------------------------------------------------

def test_accepted_extensions_are_exactly_the_three_registers(tmp_path):
    handler = _handler(tmp_path)
    probes = sorted(
        EXPECTED_ACCEPTED | set(INGESTIBLE_EXTS) | set(UNREGISTERED)
        | {".zip", ".exe", ".svg"}
    )
    # No content_type: this asks the extension half alone, so a register that
    # loses an entry cannot hide behind the MIME arm rescuing the same file.
    accepted = {ext for ext in probes if handler.is_document_file("probe" + ext)}
    assert accepted == EXPECTED_ACCEPTED
    assert set(INGESTIBLE_EXTS) == EXPECTED_ACCEPTED
    assert set(TEXT_EXTS) == EXPECTED_TEXT
    assert set(MARKITDOWN_EXTS | PDF_EXTS) == EXPECTED_BINARY_DOC
    assert len(INGESTIBLE_EXTS) == len(TEXT_EXTS) + len(MARKITDOWN_EXTS) + len(PDF_EXTS)


def test_upload_classifier_reads_the_register_rather_than_a_copy(tmp_path, monkeypatch):
    """Derivation, proved by moving the register and watching the classifier move.

    A re-hardcoded list in upload_handler passes the set-equality test above
    until the two drift; it cannot pass this one at all.
    """
    handler = _handler(tmp_path)
    assert not handler.is_document_file("thing.zzz")
    monkeypatch.setattr(
        "src.upload_handler.INGESTIBLE_EXTS", INGESTIBLE_EXTS | {".zzz"}
    )
    assert handler.is_document_file("thing.zzz")


def test_text_gate_reads_the_register_rather_than_a_copy(monkeypatch):
    assert not _is_text_file("thing.zzz")
    monkeypatch.setattr("src.document_processor.TEXT_EXTS", TEXT_EXTS | {".zzz"})
    assert _is_text_file("thing.zzz")


def test_binary_document_formats_are_never_in_the_text_arm():
    """The invariant `B05` asked for, and why it must stay unsatisfied.

    `_process_text_file` reads the file as UTF-8 and wraps it in a code fence.
    Admitting a PDF or an Office zip here would put a binary stream in the
    prompt, which is worse than the banner it would replace.
    """
    for ext in sorted(EXPECTED_BINARY_DOC):
        assert not _is_text_file("report" + ext), ext
        assert ext in INGESTIBLE_EXTS, ext


def test_bare_dotfile_names_still_count_as_text():
    """Suffix matching, not splitext: `.md` alone has no splitext extension."""
    assert _is_text_file(".md")
    assert _is_text_file("/tmp/.gitignore.yml")


# --------------------------------------------------------------------------
# No accepted extension delivers zero bytes
# --------------------------------------------------------------------------

@pytest.mark.parametrize("ext", sorted(EXPECTED_TEXT))
def test_every_text_extension_puts_its_bytes_in_the_message(tmp_path, ext):
    handler = _handler(tmp_path)
    rendered = _render(tmp_path, handler, "notes" + ext, SENTINEL.encode())
    assert SENTINEL in rendered, ext
    assert NO_EXTRACTOR not in rendered, ext


def test_pdf_extension_puts_its_bytes_in_the_message(tmp_path):
    handler = _handler(tmp_path)
    rendered = _render(
        tmp_path, handler, "report.pdf", _minimal_pdf(SENTINEL),
        mime="application/pdf",
    )
    assert SENTINEL in rendered
    assert NO_EXTRACTOR not in rendered


def test_docx_extension_puts_its_bytes_in_the_message(tmp_path):
    handler = _handler(tmp_path)
    rendered = _render(tmp_path, handler, "memo.docx", _minimal_docx(SENTINEL))
    assert SENTINEL in rendered
    assert NO_EXTRACTOR not in rendered


@pytest.mark.parametrize("ext", sorted(EXPECTED_ACCEPTED))
def test_no_accepted_extension_renders_an_anonymous_dead_end(tmp_path, ext):
    """Every accepted extension either delivers content or says which file and why.

    `.xlsx .pptx .xls .epub` reach the optional-markitdown banner on an install
    without it — that banner names the file and names the install command, which
    is the acceptable half. What may never happen is the `no extractor` banner,
    because the accepted set is derived from the extractors.
    """
    handler = _handler(tmp_path)
    name = "attachment" + ext
    body = _minimal_pdf(SENTINEL) if ext == ".pdf" else (
        _minimal_docx(SENTINEL) if ext == ".docx" else SENTINEL.encode()
    )
    rendered = _render(tmp_path, handler, name, body)
    assert NO_EXTRACTOR not in rendered, ext
    assert SENTINEL in rendered or name in rendered, (ext, rendered)


# --------------------------------------------------------------------------
# What happens to a file nothing can read
# --------------------------------------------------------------------------

@pytest.mark.parametrize("ext", UNREGISTERED)
def test_unreadable_attachment_banner_names_the_file(tmp_path, ext):
    """The upload is accepted, the bytes are dropped — say so, and say which file.

    There is deliberately no upload type blocklist, so these all upload fine and
    render a chip. The banner is persisted as the user's own message, so it is
    already on screen; before this it read `[Attached non-text file]`, which
    named no file and did not say the contents were gone.
    """
    handler = _handler(tmp_path)
    name = "document" + ext
    rendered = _render(tmp_path, handler, name, SENTINEL.encode())
    assert name in rendered, ext
    assert "contents not read" in rendered, ext
    assert NO_EXTRACTOR in rendered, ext
    assert "[Attached non-text file]" not in rendered, ext
    assert SENTINEL not in rendered, ext


def test_two_unreadable_attachments_are_told_apart(tmp_path):
    """The old banner was identical for every file; two of them were one line twice."""
    handler = _handler(tmp_path)
    up = tmp_path / "uploads"
    up.mkdir(parents=True, exist_ok=True)
    (up / "first.rst").write_bytes(b"one")
    (up / "second.toml").write_bytes(b"two")
    resolved = {
        "a": {"path": str(up / "first.rst"), "name": "first.rst", "mime": None},
        "b": {"path": str(up / "second.toml"), "name": "second.toml", "mime": None},
    }
    out = build_user_content(
        "two files", ["a", "b"], str(up), handler,
        owner="tester", resolved_uploads=resolved,
    )
    text = out if isinstance(out, str) else "".join(
        b.get("text", "") for b in out if isinstance(b, dict))
    assert "first.rst" in text and "second.toml" in text


def test_mime_can_rescue_an_extension_no_register_names(tmp_path):
    """Why a set-only check could never have been the whole invariant.

    `is_document_file` also accepts on MIME, and the text arm is
    `mime.startswith("text/") or _is_text_file(path)`. A sniff of `text/plain`
    carries an unknown extension all the way through to the model.
    """
    handler = _handler(tmp_path)
    assert ".frobnicate" not in INGESTIBLE_EXTS
    rendered = _render(
        tmp_path, handler, "notes.frobnicate", SENTINEL.encode(), mime="text/plain",
    )
    assert SENTINEL in rendered
    assert NO_EXTRACTOR not in rendered


def test_mime_classified_document_with_no_extractor_names_the_file(tmp_path):
    """The other way into a dead end: MIME says document, no register says how."""
    handler = _handler(tmp_path)
    rendered = _render(
        tmp_path, handler, "book.bin", b"not really an epub",
        mime="application/epub+zip",
    )
    assert "book.bin" in rendered
    assert "contents not read" in rendered
    assert "[Attached document file]" not in rendered
