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
import base64
import io
import os
import zipfile

import pytest

from src.document_processor import (
    INGESTIBLE_EXTS,
    PROSE_LANGUAGES,
    TEXT_EXTS,
    _is_text_file,
    attachment_language,
    build_user_content,
    decode_text_file,
    looks_like_text,
)
from src.markitdown_runtime import (
    MARKITDOWN_EXTS,
    NATIVE_OFFICE_EXTS,
    OFFICE_EXTS,
    is_markitdown_format,
    is_office_format,
)
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
# Accepted, and never readable as text: the six `B05` wanted moved into the text
# arm, plus the two `B102` gave extractors to. `_process_text_file` would hand
# the model a binary stream for every one of them.
EXPECTED_BINARY_DOC = frozenset({
    ".doc", ".docx", ".epub", ".odt", ".pdf", ".pptx", ".xls", ".xlsx",
})
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

# The honest other half: binary containers with no extractor. These keep the
# banner, and the banner is true. `B76` left `.doc` and `.odt` here and `B102`
# took them out by writing the two extractors, so what remains is the formats
# nobody has claimed — WordPerfect (a binary record stream) and Pages (a zip).
BINARY_NO_EXTRACTOR = (".wpd", ".pages")

UNREGISTERED = DECODES_AS_TEXT + BINARY_NO_EXTRACTOR


def _ole2_doc(text: str) -> bytes:
    """An OLE2 header as Word writes it: the magic, then NUL padding.

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
    if ext == ".wpd":
        return _ole2_doc(text)      # WordPerfect 6+ ships as an OLE2 container
    if ext == ".pages":
        return _odt(text)           # Pages is a zip, like every modern office zip
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

def test_accepted_extensions_are_exactly_the_registers(tmp_path):
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
    assert set(OFFICE_EXTS | PDF_EXTS) == EXPECTED_BINARY_DOC
    # Four registers, one per extractor, no overlap and no slack: markitdown,
    # the bundled office readers `B102` added, pypdf, and the text arm.
    assert set(MARKITDOWN_EXTS) & set(NATIVE_OFFICE_EXTS) == set()
    assert len(INGESTIBLE_EXTS) == (
        len(TEXT_EXTS) + len(MARKITDOWN_EXTS) + len(NATIVE_OFFICE_EXTS) + len(PDF_EXTS)
    )


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


def test_the_remaining_encoding_limit_is_utf16_without_a_bom(tmp_path):
    """`Law 1` as a limit, moved by `B101` rather than removed.

    This was `test_an_unreadable_encoding_keeps_the_banner_it_has_today`, and it
    asserted that a UTF-16 attachment keeps the banner. `B101` made a BOM'd one
    readable (see below), so what is left is the file that declares nothing: NUL
    padding with no byte-order mark is not distinguishable from a container
    prefix without guessing, and the probe does not guess. The register arm is
    unaffected — a `.txt` in this encoding is read, because something already
    decided to read it.
    """
    handler = _handler(tmp_path)
    rendered = _render(tmp_path, handler, "wide.unknown", SENTINEL.encode("utf-16-le"))
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


# --------------------------------------------------------------------------
# `B100` — the label and the fence are one answer
# --------------------------------------------------------------------------

# What the composer must say about each of these. Spelled out rather than
# derived from `LANGUAGE_ALIASES`, for the same reason `EXPECTED_TEXT` is: a
# test that reads its expectations out of the map it is testing proves only that
# the code agrees with itself. The last four are the measured defect — before
# `B100` every one of them was `[Type: text]` with no fence at all.
LABELLED = [
    ("config.yaml", "yaml", True),
    ("config.toml", "toml", True),
    ("script.py", "python", True),
    ("notes.md", "markdown", True),
    ("readme.txt", "text", False),
    ("server.log", "log", False),
    ("notes.markdown", "markdown", True),
    ("header.h", "c", True),
    ("build.gradle", "gradle", True),
    ("Setup.ps1", "powershell", True),
]


@pytest.mark.parametrize("name,language,fenced", LABELLED)
def test_the_label_and_the_fence_agree_on_every_file(tmp_path, name, language, fenced):
    """The row's `Verify`, driven through the real composer.

    `.markdown` is the one it names: `routes/email_routes.py` loads it as a
    markdown Document and `static/js/emailLibrary.js` offers the document editor
    for it, while the composer called it `text`.
    """
    handler = _handler(tmp_path)
    rendered = _render(tmp_path, handler, name, SENTINEL.encode())
    assert f"[Type: {language}," in rendered, rendered[:200]
    assert (f"```{language}\n" in rendered) is fenced, rendered[:200]
    assert SENTINEL in rendered


def test_two_byte_identical_files_are_labelled_by_what_they_are(tmp_path):
    """The measurement `B100` was filed on: same bytes, two names, two answers.

    `config.yaml` arrived as ```yaml and `config.toml` arrived bare, which is a
    statement about the register rather than about the file.
    """
    handler = _handler(tmp_path)
    body = b"host = 'localhost'\nport = 8080\n"
    yaml_out = _render(tmp_path, handler, "config.yaml", body)
    toml_out = _render(tmp_path, handler, "config.toml", body)
    assert "```yaml" in yaml_out and "[Type: yaml," in yaml_out
    assert "```toml" in toml_out and "[Type: toml," in toml_out


def test_the_fence_is_derived_from_the_label_and_not_from_a_second_list(tmp_path, monkeypatch):
    """`Law 14`, proved by moving the one map and watching both outputs move.

    A re-introduced `code_extensions` set passes every other test in this
    section — the labels and the fences would still agree on today's
    extensions — and cannot pass this one, because there is nothing to add
    `.zzz` to but the map the label comes from.
    """
    import src.document_processor as dp

    handler = _handler(tmp_path)
    monkeypatch.setattr(
        dp, "LANGUAGE_ALIASES", {**dp.LANGUAGE_ALIASES, ".zzz": "python"}
    )
    rendered = _render(tmp_path, handler, "mystery.zzz", SENTINEL.encode())
    assert "[Type: python," in rendered
    assert "```python\n" in rendered


def test_prose_is_the_only_thing_printed_without_a_fence(tmp_path):
    """One invariant over every extension the text arm claims.

    Before `B100` this could not hold: `.csv` and `.h` carried a label from one
    list and their fence from another, so `.h` was `[Type: text]` and `.csv`
    was `[Type: csv]` with no fence — a label that says it is data and a body
    that runs into the prose around it.
    """
    handler = _handler(tmp_path)
    for ext in sorted(TEXT_EXTS):
        rendered = _render(tmp_path, handler, "sample" + ext, SENTINEL.encode())
        language = attachment_language("sample" + ext)
        assert f"[Type: {language}," in rendered, ext
        assert ("```" + language) in rendered or language in PROSE_LANGUAGES, ext
        if language in PROSE_LANGUAGES:
            assert "```" not in rendered, ext


def test_a_file_with_no_extension_is_still_prose(tmp_path):
    """`Law 1`: the old map answered `text` for an empty extension. So does this."""
    handler = _handler(tmp_path)
    rendered = _render(tmp_path, handler, "Dockerfile", SENTINEL.encode())
    assert "[Type: text," in rendered
    assert "```" not in rendered
    assert SENTINEL in rendered


def test_the_language_answer_is_one_function(tmp_path):
    assert attachment_language("a.markdown") == "markdown"
    assert attachment_language("a.MD") == "markdown"
    assert attachment_language(".md") == "markdown"      # bare dotfile
    assert attachment_language("a.toml") == "toml"
    assert attachment_language("a.kt") == "kotlin"
    assert attachment_language("Dockerfile") == "text"
    assert attachment_language("archive.tar.gz") == "gz"
    # Not a word, so not a language: the fence would be noise and the label a lie.
    assert attachment_language("weird.123") == "text"
    assert attachment_language("weird.") == "text"


# --------------------------------------------------------------------------
# `B101` — the encoding is sniffed, not assumed
# --------------------------------------------------------------------------

RUSSIAN = "Привет, мир! Конфигурация сервера для отдела продаж.\n"
POLISH = "Zażółć gęślą jaźń — plik konfiguracyjny serwera.\n"


def test_a_utf16_text_file_with_a_bom_reaches_the_model(tmp_path):
    """The row's first `Verify` clause.

    Measured before `B101`: zero bytes. The NUL padding that makes UTF-16 look
    like a container is preceded by two bytes that say exactly what it is.
    """
    handler = _handler(tmp_path)
    body = (SENTINEL + "\n" + RUSSIAN).encode("utf-16")
    rendered = _render(tmp_path, handler, "wide.unknown", body)
    assert NO_EXTRACTOR not in rendered
    assert SENTINEL in rendered
    assert RUSSIAN.strip() in rendered
    assert "\x00" not in rendered


@pytest.mark.parametrize("encoding", ["utf-16", "utf-32", "utf-8-sig"])
def test_every_bom_is_read_and_not_printed(tmp_path, encoding):
    handler = _handler(tmp_path)
    rendered = _render(tmp_path, handler, "wide.unknown", SENTINEL.encode(encoding))
    assert SENTINEL in rendered, encoding
    assert "﻿" not in rendered, encoding


def test_a_cp1251_conf_reaches_the_model(tmp_path):
    """The row's second `Verify` clause, and the reason the ratio was the wrong lever.

    This file has no NUL and no BOM. It fails the replacement-char ratio at
    0.793 — measured — which is what kept it out; widening the ratio to admit it
    would have admitted binary with it.
    """
    handler = _handler(tmp_path)
    rendered = _render(tmp_path, handler, "server.conf", (RUSSIAN * 20).encode("cp1251"))
    assert NO_EXTRACTOR not in rendered
    assert RUSSIAN.strip() in rendered


def test_legacy_prose_is_not_silently_thrown_away_by_the_reader(tmp_path):
    """The half of `B101` that a register could never have fixed.

    `.txt` is in `TEXT_EXTS`, so this file always reached `_process_text_file` —
    which read it through `personal_docs.read_text_file`, i.e. utf-8 with
    `errors="ignore"`. Every Cyrillic byte was dropped on the floor and the
    model was told the file was nearly empty, with nothing anywhere saying so.
    The `charset_normalizer` fallback written directly below that call never ran
    because `read_text_file` returns `""` instead of raising.
    """
    handler = _handler(tmp_path)
    rendered = _render(tmp_path, handler, "notes.txt", (RUSSIAN * 8).encode("cp1251"))
    assert RUSSIAN.strip() in rendered


def test_a_file_the_old_gate_already_accepted_is_no_longer_mangled(tmp_path):
    """The case between the two halves, and the one nothing was watching.

    Polish cp1250 scores 0.170 on the replacement ratio — under the 0.30 bound,
    so this file was called text and read. It was then decoded as UTF-8 and every
    accented character was dropped on the floor: the model received
    "Za g jazn plik konfiguracyjny serwera" and no marker saying anything had
    gone missing. A rule that only rescued files scoring *above* the bound would
    leave this exactly as it was.
    """
    handler = _handler(tmp_path)
    rendered = _render(tmp_path, handler, "server.conf", (POLISH * 20).encode("cp1250"))
    assert NO_EXTRACTOR not in rendered
    assert POLISH.strip() in rendered


def test_a_registered_extension_is_decoded_even_when_the_probe_says_binary(tmp_path):
    """The deliberate asymmetry: the probe decides *whether*, the reader decides *how*.

    BOM-less UTF-16 keeps the banner when nothing claims it (see the limit test
    above), but a `.txt` was claimed by the register, so refusing to decode it
    would only mean handing the model NUL-separated letters — which is what it
    got before.
    """
    handler = _handler(tmp_path)
    body = (SENTINEL + "\n").encode("utf-16-le")
    assert not looks_like_text(str(_write(tmp_path, "probe.bin", body)))
    rendered = _render(tmp_path, handler, "notes.txt", body)
    assert SENTINEL in rendered
    assert "\x00" not in rendered


def test_the_probe_and_the_reader_are_one_decision(tmp_path, monkeypatch):
    """`Law 13`: break the sniff, and both sides of it change together."""
    import src.document_processor as dp

    path = str(_write(tmp_path, "notes.conf", (POLISH * 20).encode("cp1250")))
    assert looks_like_text(path)
    assert POLISH.strip() in decode_text_file(path)

    monkeypatch.setattr(dp, "sniff_text_encoding", lambda head: None)
    assert not dp.looks_like_text(path)


def test_a_detector_guess_is_taken_only_when_it_decodes_better(monkeypatch):
    """The comparison is the safety rail, and the detector is stubbed to prove it.

    ``charset_normalizer`` answers with its best guess, not with a promise. Three
    measured examples of a guess that must lose: `ascii` for UTF-8 text with one
    stray byte (0.357 replacements against UTF-8's 0.083), and — with the real
    detector — `utf_16_be` for ``b"h\xc3\xa9llo w\xc3\xb6rld\xff"``, which
    decodes to CJK with a *perfect* score because every byte pair maps to
    something. A wide codec cannot win here at all: real UTF-16 arrives with a
    BOM or with NULs and is answered before this point.
    """
    import src.document_processor as dp

    body = "héllo wörld".encode("utf-8") + b"\xff"
    monkeypatch.setattr(dp, "_detect_encoding", lambda head: "ascii")
    assert dp.sniff_text_encoding(body) == "utf-8"

    monkeypatch.setattr(dp, "_detect_encoding", lambda head: "utf_16_be")
    assert dp.sniff_text_encoding(body) == "utf-8"


def test_a_spotless_decode_of_control_characters_is_not_text(monkeypatch):
    """The other guard: "it decoded" is not evidence.

    Every single-byte codec maps almost every byte to *something*, so a binary
    prefix can decode with zero replacement characters and still be binary. What
    real prose does not contain is C0/C1 controls — here 0.948 of the file.
    """
    import src.document_processor as dp

    body = b"report\n" + bytes(range(0x80, 0xA0)) * 4
    monkeypatch.setattr(dp, "_detect_encoding", lambda head: "latin-1")
    assert dp.sniff_text_encoding(body) is None


def test_binary_is_still_binary_after_the_encoding_sniff(tmp_path):
    """`Law 1`'s other direction, re-run against the widened gate.

    `charset_normalizer` answers `None` for all of these, and the control-char
    guard is the belt if a future version stops doing so.
    """
    handler = _handler(tmp_path)
    for name, body in [
        ("a.unknown", b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"),
        ("b.unknown", b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01"),
        ("c.unknown", b"\x1f\x8b\x08\x00\x00\x00\x00\x00"),
        ("d.unknown", b"MZ\x90\x00\x03\x00\x00\x00"),
        ("e.unknown", bytes(range(0x80, 0x100)) * 32),
        ("f.unknown", bytes(range(256)) * 4),
    ]:
        assert NO_EXTRACTOR in _render(tmp_path, handler, name, body), name


def _write(tmp_path, name, body: bytes):
    path = tmp_path / "raw" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return path


# --------------------------------------------------------------------------
# `B102` — the two formats that had no extractor
# --------------------------------------------------------------------------

# A real Word 97-2003 file, produced by LibreOffice ("doc:MS Word 97"), gzipped
# and base64'd so the patch stays text. It is a real one on purpose: a `.doc` is
# an OLE2 container holding a piece table, and a fixture written by the same
# person who wrote the reader would agree with the reader's assumptions rather
# than with Word's. It contains a heading, a Cyrillic paragraph, a hyperlink
# field, a two-row table and the sentinel.
#
# LibreOffice writes every piece as UTF-16 (measured on three of its outputs), so
# the CP1252-compressed piece — what Word writes for a document that fits in that
# codepage, and half of the piece-table format — is covered by
# `_word97_doc_compressed` below, which re-encodes this same real file's piece
# rather than inventing a container.
DOC_FIXTURE_GZ_B64 = (
    "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"
)

# An ODF text document, built here rather than vendored: `.odt` is a zip of XML,
# so the fixture is readable in the diff and says exactly what the extractor is
# expected to walk. The namespace declarations and element shapes are copied
# from what LibreOffice actually writes, and the extractor was driven against
# LibreOffice output as well while it was written.
ODT_CONTENT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<office:document-content
    xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
    xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
    xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0"
    xmlns:xlink="http://www.w3.org/1999/xlink" office:version="1.3">
  <office:body><office:text>
    <text:h text:outline-level="1">Quarterly Report</text:h>
    <text:p>%s</text:p>
    <text:p>Cyrillic: \u041f\u0440\u0438\u0432\u0435\u0442, \u043c\u0438\u0440!</text:p>
    <text:p>See <text:a xlink:href="https://example.com/x">the link</text:a> for details.</text:p>
    <text:p>Column<text:tab/>Total</text:p>
    <table:table><table:table-row>
      <table:table-cell><text:p>North</text:p></table:table-cell>
      <table:table-cell><text:p>42</text:p></table:table-cell>
    </table:table-row></table:table>
  </office:text></office:body>
</office:document-content>
"""


# A second real Word 97 file, this one carrying a footnote. Word keeps footnote
# text in the same stream, *after* the body, and `ccpText` in the FIB is where
# the body stops — 104 characters of the 152 stored here.
FOOT_DOC_GZ_B64 = (
    "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"
)

# Where the fixture above keeps its one piece. Both are read out of the file
# itself by the assertions in `_word97_doc_compressed`, so a regenerated fixture
# fails loudly rather than being silently re-encoded at the wrong offset.
_PIECE_STREAM_OFFSET = 2048     # `fc` in the piece-table entry
_PIECE_FILE_OFFSET = 7168       # where that stream offset lands in the file
_PIECE_CHARS = 177              # `ccpText`


def _word97_doc() -> bytes:
    import gzip as _gzip
    return _gzip.decompress(base64.b64decode(DOC_FIXTURE_GZ_B64))


def _word97_footnote_doc() -> bytes:
    import gzip as _gzip
    return _gzip.decompress(base64.b64decode(FOOT_DOC_GZ_B64))


def _word97_doc_compressed() -> bytes:
    """The same real file with its single piece stored the way Word stores one.

    A piece is either UTF-16 or "compressed" — one CP1252 byte per character,
    with the byte offset doubled and flagged in the top bits of `fc`. LibreOffice
    only ever writes the first kind, so this rewrites the second into a real
    container rather than hand-building a CFB that would agree with whatever the
    reader assumes. Two edits, both of them structures the file itself
    describes: the piece's UTF-16 bytes become CP1252 bytes in place, and its
    `fc` gains the flag and the doubled offset. Nothing moves, because a piece is
    addressed by `fc` and not by its size.

    The Cyrillic paragraph cannot survive CP1252 — which is precisely why Word
    has two piece kinds — so it is asserted on the UTF-16 original instead.
    """
    import struct

    data = bytearray(_word97_doc())
    pcd = struct.pack("<HIH", 0x0050, _PIECE_STREAM_OFFSET, 0)
    assert data.count(pcd) == 1, "fixture changed: the piece table entry moved"
    span = slice(_PIECE_FILE_OFFSET, _PIECE_FILE_OFFSET + 2 * _PIECE_CHARS)
    text = bytes(data[span]).decode("utf-16-le")
    assert text.startswith("Quarterly Report"), "fixture changed: the text moved"
    data[span] = text.encode("cp1252", "replace") + b"\x00" * _PIECE_CHARS
    at = data.index(pcd)
    data[at:at + 8] = struct.pack(
        "<HIH", 0x0050, (_PIECE_STREAM_OFFSET << 1) | 0x40000000, 0
    )
    return bytes(data)


def _odt_document(text: str = SENTINEL, content_xml: str | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mimetype", "application/vnd.oasis.opendocument.text")
        z.writestr("content.xml", (content_xml or ODT_CONTENT_XML) % text)
    return buf.getvalue()


def test_a_real_word_97_document_puts_its_prose_in_the_message(tmp_path):
    """The row's `Verify`, first clause, on a file Word itself would open.

    Measured before `B102`: the banner, zero bytes. markitdown 0.1.6 raises
    `UnsupportedFormatException` on this same file — *"no converter attempted a
    conversion"* — so adding `.doc` to `MARKITDOWN_EXTS` would have replaced a
    true banner with a misleading one.
    """
    handler = _handler(tmp_path)
    rendered = _render(tmp_path, handler, "quarterly.doc", _word97_doc())
    assert NO_EXTRACTOR not in rendered
    assert SENTINEL in rendered
    assert "Quarterly Report" in rendered
    # The Cyrillic paragraph is a UTF-16 piece in a file whose other pieces are
    # CP1252-compressed: reading it proves the piece table is being walked
    # rather than the stream being scanned for printable runs.
    assert "\u041f\u0440\u0438\u043c\u0435\u0440" in rendered
    # A field arrives as "\x13 HYPERLINK "https://…" \x14 the link \x15": the
    # reader keeps the result and drops the instruction.
    assert "the link" in rendered
    assert "HYPERLINK" not in rendered
    assert "https://example.com" not in rendered
    # Table cells are cell-separated, not run together.
    assert "North" in rendered and "42" in rendered


def test_a_doc_whose_pieces_are_cp1252_compressed_reads_the_same(tmp_path):
    """The other half of the piece table, which no LibreOffice output produces.

    Word writes this form for any document that fits in CP1252, which is most
    `.doc` files in the world. A reader that assumes UTF-16 returns the same
    bytes read two per character: unicode noise, with nothing on the outside to
    say it went wrong.
    """
    handler = _handler(tmp_path)
    rendered = _render(tmp_path, handler, "compressed.doc", _word97_doc_compressed())
    assert NO_EXTRACTOR not in rendered
    assert SENTINEL in rendered
    assert "Quarterly Report" in rendered
    assert "the link" in rendered
    assert "North" in rendered and "42" in rendered


def test_the_body_stops_where_the_document_says_it_does(tmp_path):
    """`ccpText`, on a real file that has something behind it.

    Footnote text sits in the same stream after the body. Without the bound it is
    concatenated onto the last paragraph with no anchor and no marker, so the
    model reads a sentence that is not in the document.
    """
    handler = _handler(tmp_path)
    rendered = _render(tmp_path, handler, "withnote.doc", _word97_footnote_doc())
    assert SENTINEL in rendered
    assert "FOOTNOTEONLYTEXT" not in rendered


def test_an_odt_puts_its_prose_in_the_message(tmp_path):
    """The row's `Verify`, second clause."""
    handler = _handler(tmp_path)
    rendered = _render(tmp_path, handler, "report.odt", _odt_document())
    assert NO_EXTRACTOR not in rendered
    assert SENTINEL in rendered
    assert "Quarterly Report" in rendered
    assert "the link" in rendered
    assert "North" in rendered and "42" in rendered
    assert "\u041f\u0440\u0438\u0432\u0435\u0442" in rendered


def test_neither_format_is_listed_in_a_register_whose_extractor_refuses_it(tmp_path):
    """The other half of the row's `Verify`, and why this is a second register.

    `.odt` and `.doc` are accepted uploads and reach an extractor, but that
    extractor is not markitdown — which refuses both — so they are not in
    `MARKITDOWN_EXTS`. A single office register would have to be either wrong
    about markitdown or wrong about these files.
    """
    handler = _handler(tmp_path)
    for ext in (".doc", ".odt"):
        assert handler.is_document_file("probe" + ext), ext
        assert is_office_format("probe" + ext), ext
        assert not is_markitdown_format("probe" + ext), ext
        assert ext in NATIVE_OFFICE_EXTS and ext not in MARKITDOWN_EXTS, ext


def test_the_bundled_readers_do_not_need_markitdown(tmp_path, monkeypatch):
    """The dependency claim, driven with the optional dependency taken away.

    `.docx` already had a bundled reader for this case; `.odt` and `.doc` now
    share the property, which is what makes them extractors rather than an entry
    in someone else's list.
    """
    import src.markitdown_runtime as mr

    def _absent():
        raise RuntimeError(mr.MARKITDOWN_MISSING)

    monkeypatch.setattr(mr, "load_markitdown", _absent)
    handler = _handler(tmp_path)
    assert SENTINEL in _render(tmp_path, handler, "a.doc", _word97_doc())
    assert SENTINEL in _render(tmp_path, handler, "b.odt", _odt_document())
    assert SENTINEL in _render(tmp_path, handler, "c.docx", _minimal_docx(SENTINEL))


def test_a_document_part_that_declares_entities_is_refused(tmp_path):
    """An attachment is untrusted input, and ElementTree expands internal entities.

    Ten nested definitions are the textbook way to turn 200 bytes into gigabytes.
    A document part has no reason to declare any, so one that does is not parsed
    — and the file still gets a banner naming it rather than a traceback.
    """
    bomb = (
        '<?xml version="1.0"?><!DOCTYPE d [<!ENTITY a "AAAAAAAAAA">'
        '<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]>'
        '<office:document-content '
        'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
        'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">'
        '<office:body><office:text><text:p>&b;%s</text:p>'
        '</office:text></office:body></office:document-content>'
    )
    handler = _handler(tmp_path)
    rendered = _render(tmp_path, handler, "bomb.odt", _odt_document(content_xml=bomb))
    assert SENTINEL not in rendered
    assert "bomb.odt" in rendered


def test_a_reader_that_falls_over_still_produces_a_message(tmp_path):
    """An extractor walks attacker-supplied structure, so it can fail unexpectedly.

    Four thousand nested `<text:span>` elements exhaust Python's recursion limit
    inside the paragraph walk. Every deliberate path through these readers
    answers "cannot read this" with `None`, and an unplanned exception means the
    same thing — so it becomes the same banner rather than a traceback out of
    `build_user_content`, which would take the whole message down with it.
    """
    ns = ('xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
          'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"')
    deep = "<text:span>" * 4000 + SENTINEL + "</text:span>" * 4000
    xml = (f'<?xml version="1.0"?><office:document-content {ns}><office:body>'
           f"<office:text><text:p>{deep}</text:p></office:text>"
           f"</office:body></office:document-content>")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("content.xml", xml)

    handler = _handler(tmp_path)
    rendered = _render(tmp_path, handler, "deep.odt", buf.getvalue())
    assert "deep.odt" in rendered
    assert "no extractable text found" in rendered
    assert SENTINEL not in rendered


def test_a_doc_that_is_not_a_doc_is_not_pretended_to_be_one(tmp_path):
    """`Law 1`: the banner must stay true for the files it is true about."""
    handler = _handler(tmp_path)
    for name, body in [
        ("fake.doc", b"just some text saved with the wrong suffix"),
        ("fake.odt", b"PK\x03\x04 but not an ODF package"),
        ("empty.doc", b""),
    ]:
        rendered = _render(tmp_path, handler, name, body)
        assert name in rendered, name
        assert "no extractable text found" in rendered, (name, rendered)
        assert "requires markitdown" not in rendered, name
