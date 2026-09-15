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
import os
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

# Extensions no register names. `B05` measured all of these delivering zero
# bytes; `B76` split them by the only thing that decides whether they can be
# read, which is the bytes and not the suffix.
#
# Rescued by the decode gate — plain text that `_process_text_file` could always
# have handled, and that only the register was stopping. `.svg` is here because
# it is XML and was classified as neither image nor document. `.rtf` is here
# because RTF is ASCII markup: the model reading `{\rtf1\ansi …}` gets the prose
# out of it, which beats a banner.
DECODES_AS_TEXT = (
    ".markdown", ".tsv", ".rst", ".toml", ".ini", ".conf", ".env", ".ipynb",
    ".patch", ".diff", ".cfg", ".properties", ".swift", ".kt", ".lua", ".pl",
    ".vue", ".scss", ".less", ".gradle", ".ps1", ".r", ".svg", ".rtf",
)

# The honest other half: rich formats with genuinely binary containers and no
# extractor. These keep the banner, and the banner is true.
BINARY_NO_EXTRACTOR = (".doc", ".odt")

UNREGISTERED = DECODES_AS_TEXT + BINARY_NO_EXTRACTOR


def _ole2_doc(text: str) -> bytes:
    """A .doc header as Word actually writes it: OLE2 magic, then NUL padding.

    Driving the real gate means handing it real bytes (`Law 20`). The previous
    fixture wrote the ASCII sentinel into a file named `.doc` and asserted a
    banner — which pinned the *suffix* as the reason, the exact premise `B76`
    refutes. A file whose bytes are text is text whatever it is called.
    """
    return b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 512 + text.encode()


def _odt(text: str) -> bytes:
    """A real ODF zip — a container, so NUL bytes and no decodable prefix."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mimetype", "application/vnd.oasis.opendocument.text")
        z.writestr("content.xml", f"<office:body>{text}</office:body>")
    return buf.getvalue()


def _unreadable_body(ext: str, text: str) -> bytes:
    if ext == ".doc":
        return _ole2_doc(text)
    if ext == ".odt":
        return _odt(text)
    return text.encode()


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

@pytest.mark.parametrize("ext", BINARY_NO_EXTRACTOR)
def test_unreadable_attachment_banner_names_the_file(tmp_path, ext):
    """The upload is accepted, the bytes are dropped — say so, and say which file.

    There is deliberately no upload type blocklist, so these all upload fine and
    render a chip. The banner is persisted as the user's own message, so it is
    already on screen; before this it read `[Attached non-text file]`, which
    named no file and did not say the contents were gone.

    `B76` narrowed this list from eleven to two. The other nine were never
    unreadable — they were unnamed.
    """
    handler = _handler(tmp_path)
    name = "document" + ext
    rendered = _render(tmp_path, handler, name, _unreadable_body(ext, SENTINEL))
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


# --------------------------------------------------------------------------
# `B76` — the gate asks the bytes, not the suffix
# --------------------------------------------------------------------------

@pytest.mark.parametrize("ext", DECODES_AS_TEXT)
def test_a_text_file_reaches_the_model_whatever_it_is_called(tmp_path, ext):
    """The row's `Verify`, and the reason the register was not extended.

    Each of these was measured delivering **zero bytes** before `B76`. None of
    them is in any register now either — `is_document_file` still says no. The
    bytes are what changed the answer.
    """
    handler = _handler(tmp_path)
    assert not handler.is_document_file("probe" + ext), (
        f"{ext} was appended to a register — that is the defect, not the fix"
    )
    rendered = _render(tmp_path, handler, "notes" + ext, SENTINEL.encode())
    assert SENTINEL in rendered, ext
    assert NO_EXTRACTOR not in rendered, ext


def test_the_gate_is_the_bytes_and_not_the_name(tmp_path):
    """The same suffix, two files, two answers — which a suffix list cannot give.

    A register can only ever answer per-extension. This is the assertion that
    fails if someone replaces the probe with a longer list.
    """
    handler = _handler(tmp_path)
    text = _render(tmp_path, handler, "a.wibble", SENTINEL.encode())
    binary = _render(tmp_path, handler, "b.wibble", b"\x89PNG\r\n\x1a\n\x00\x00IHDR")
    assert SENTINEL in text
    assert NO_EXTRACTOR in binary and "b.wibble" in binary


@pytest.mark.parametrize("body", [
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x01\x00",   # png
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01",                   # jpeg
    b"\x1f\x8b\x08\x00\x00\x00\x00\x00",                       # gzip
    b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00",             # pe/exe
    bytes(range(256)) * 4,                                     # dense binary
])
def test_binary_bytes_still_get_the_banner(tmp_path, body):
    """`Law 1`'s other direction: the gate opening must not open for everything.

    Every one of these carries a NUL in its first bytes, which is the check
    doing the real work — a zip of pure ASCII scores 0.02 on the replacement
    ratio and would sail through it.
    """
    handler = _handler(tmp_path)
    rendered = _render(tmp_path, handler, "payload.unknown", body)
    assert NO_EXTRACTOR in rendered
    assert "payload.unknown" in rendered


def test_nul_free_binary_is_caught_by_the_replacement_ratio(tmp_path):
    """The NUL check is not the whole probe, and this is the half it misses.

    High bytes with no NUL anywhere — a latin-1-ish blob, a stripped binary, a
    raw sample buffer. Every byte here starts an invalid UTF-8 sequence, so the
    prefix decodes to almost pure U+FFFD and only the ratio rejects it.
    """
    handler = _handler(tmp_path)
    rendered = _render(tmp_path, handler, "blob.unknown", bytes(range(0x80, 0x100)) * 32)
    assert NO_EXTRACTOR in rendered
    assert "blob.unknown" in rendered


def test_text_with_a_few_bad_bytes_is_still_text(tmp_path):
    """The ratio is a threshold, not a purity test — the other direction.

    A config saved in latin-1 with one accented character is text that someone
    wants read. It decodes to one U+FFFD in a page of ASCII, well under the
    bound, and rejecting it would be the probe failing at its own job.
    """
    handler = _handler(tmp_path)
    body = (SENTINEL * 40).encode() + "café naïve".encode("latin-1") + b"\ntail\n"
    rendered = _render(tmp_path, handler, "server.unknown", body)
    assert NO_EXTRACTOR not in rendered
    assert SENTINEL in rendered


def test_a_zip_of_ascii_is_not_mistaken_for_text(tmp_path):
    """The case the replacement-char ratio alone gets wrong."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("readme.txt", SENTINEL * 200)
    handler = _handler(tmp_path)
    rendered = _render(tmp_path, handler, "bundle.unknownzip", buf.getvalue())
    assert NO_EXTRACTOR in rendered
    assert SENTINEL not in rendered


def test_the_probe_is_bounded_and_is_not_paid_by_files_that_already_work(tmp_path):
    """The cost the row asked to have bounded, measured rather than asserted.

    Two claims: a file an extractor already covers triggers **no** probe read at
    all, and a file that needs the probe is read once, at most
    `TEXT_SNIFF_BYTES`. A probe that slurped the whole file would show up here
    as a multi-megabyte read on a file that then gets truncated anyway.
    """
    import src.document_processor as dp

    handler = _handler(tmp_path)
    reads: list[int] = []
    real = dp.looks_like_text

    def counting(path, probe_bytes=dp.TEXT_SNIFF_BYTES):
        reads.append(min(os.path.getsize(path), probe_bytes))
        return real(path, probe_bytes)

    dp.looks_like_text = counting
    try:
        big = (SENTINEL * 200_000).encode()
        assert len(big) > 4_000_000
        _render(tmp_path, handler, "covered.md", big)
        assert reads == [], "a registered extension paid for a probe it never needed"
        _render(tmp_path, handler, "uncovered.toml", big)
        assert reads == [dp.TEXT_SNIFF_BYTES], reads
    finally:
        dp.looks_like_text = real


def test_an_unreadable_encoding_keeps_the_banner_it_has_today(tmp_path):
    """`Law 1` again, stated as a limit rather than a gap.

    UTF-16 is text and this probe rejects it, because its NUL padding is
    indistinguishable from a binary container without sniffing the encoding.
    That is the behaviour these files already have, so nothing is taken away —
    but the limit is real and belongs in a test rather than only in a comment.
    """
    handler = _handler(tmp_path)
    rendered = _render(tmp_path, handler, "wide.unknown", SENTINEL.encode("utf-16"))
    assert NO_EXTRACTOR in rendered


def test_an_empty_prefix_is_not_binary(tmp_path):
    handler = _handler(tmp_path)
    rendered = _render(tmp_path, handler, "blank.unknown", b"")
    assert NO_EXTRACTOR not in rendered
    assert "blank.unknown" in rendered


def test_chat_ingest_calls_the_shared_probe_rather_than_a_copy(tmp_path):
    """`Law 13`, proved by moving the probe and watching chat ingest move.

    The probe shipped as a closure inside `attachment_as_doc`, where chat could
    not reach it — so the product had already decided a `.toml` attachment is
    text, for the mailbox and not for the composer. A re-inlined copy in
    `document_processor` would keep every other test in this file green; it
    cannot pass this one.
    """
    import src.document_processor as dp

    handler = _handler(tmp_path)
    real = dp.looks_like_text
    dp.looks_like_text = lambda path, probe_bytes=dp.TEXT_SNIFF_BYTES: False
    try:
        rendered = _render(tmp_path, handler, "config.toml", SENTINEL.encode())
        assert NO_EXTRACTOR in rendered, (
            "build_user_content is not calling the shared probe"
        )
    finally:
        dp.looks_like_text = real


def _drive_attachment_as_doc(tmp_path, monkeypatch, name, body: bytes):
    """Call the real `POST /api/email/attachment-as-doc` over one real file.

    Only the mailbox is faked — IMAP and the attachment extractor. Everything
    from the containment check through the decode decision is the shipped code.
    """
    import contextlib
    import email as email_mod
    import routes.email_routes as email_routes

    raw = b"Subject: t\r\nMessage-ID: <m@x>\r\n\r\nbody\r\n"
    target = tmp_path / "extract"
    target.mkdir(parents=True, exist_ok=True)
    (target / name).write_bytes(body)

    @contextlib.contextmanager
    def fake_imap(account_id=None, owner=""):
        yield type("C", (), {"select": lambda self, *a, **k: None})()

    monkeypatch.setattr(email_routes, "_imap", fake_imap)
    monkeypatch.setattr(
        email_routes, "_imap_uid_fetch", lambda *a, **k: ("OK", [(None, raw)])
    )
    monkeypatch.setattr(
        email_routes, "attachment_extract_dir", lambda folder, uid: target
    )
    monkeypatch.setattr(
        email_routes,
        "_extract_attachment_to_disk",
        lambda msg, index, d: target / name,
    )
    monkeypatch.setattr(
        "src.auth_helpers.get_current_user", lambda request: "tester"
    )
    assert email_mod.message_from_bytes(raw)["Message-ID"]

    router = email_routes.setup_email_routes()
    endpoint = next(
        r.endpoint for r in router.routes
        if r.path == "/api/email/attachment-as-doc/{uid}/{index}"
        and "POST" in getattr(r, "methods", set())
    )
    return endpoint("42", 0, request=None, folder="INBOX",
                    account_id=None, owner="tester")


def test_the_mailbox_asks_the_same_question_chat_ingest_does(tmp_path, monkeypatch):
    """`Law 13`, driven rather than grepped.

    The probe used to be a closure here, so the mailbox and the composer could
    give different answers about the same bytes and nothing would notice. Both
    callers are driven over the same two files and must agree — and the
    monkeypatch below proves the route is *calling* the shared function rather
    than merely importing it.
    """
    import src.document_processor as dp

    handler = _handler(tmp_path)
    png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"

    text_result = _drive_attachment_as_doc(
        tmp_path / "t", monkeypatch, "config.toml", SENTINEL.encode())
    binary_result = _drive_attachment_as_doc(
        tmp_path / "b", monkeypatch, "photo.png", png)

    # The refusal is only reachable when the probe says binary, so it is the
    # discriminator in both directions.
    assert binary_result.get("error") == "Unsupported attachment type: .png"
    assert text_result.get("doc_id"), text_result
    assert text_result.get("filename") == "config.toml"

    # And chat ingest answers the same two files the same way.
    assert NO_EXTRACTOR not in _render(tmp_path, handler, "config.toml", SENTINEL.encode())
    assert NO_EXTRACTOR in _render(tmp_path, handler, "photo.unknown", png)

    # One function: break it, and the mailbox breaks with it.
    monkeypatch.setattr(dp, "looks_like_text", lambda p, probe_bytes=0: False)
    flipped = _drive_attachment_as_doc(
        tmp_path / "f", monkeypatch, "config.toml", SENTINEL.encode())
    assert flipped.get("error") == "Unsupported attachment type: .toml", (
        "the mailbox is not calling the shared probe"
    )
