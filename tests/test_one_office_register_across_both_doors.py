# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B240` — the mailbox reads what the composer reads, driven over real files.

Measured on the tree as it stood, by driving `POST /api/email/attachment-as-doc`
over a LibreOffice-produced file of each type rather than by reading the route:

  * `.doc`, `.epub`, `.odt`, `.pptx`, `.xls` and `.xlsx` every one answered
    ``Unsupported attachment type``, while the same six are in
    ``INGESTIBLE_EXTS`` and are extracted for the model by
    ``src/markitdown_runtime`` when they arrive in the composer;
  * the one format the mailbox did read, `.docx`, was read by a **second**
    hand-rolled `python-docx` reader sitting inside the route, so one `.docx`
    had two renderings in one product (`Law 14`);
  * and the three text branches read with ``read_text(encoding="utf-8",
    errors="replace")`` whatever encoding the probe had just identified, so a
    cp1251 `.txt` attachment opened as 52 characters of U+FFFD.

Every fixture here is a real file produced by LibreOffice — see
``tests/helpers/office_fixtures.py`` for why that matters and how they are
stored. Only IMAP and the MIME extractor are faked; everything from the
containment check through the extractor dispatch and the Document write is the
shipped code.
"""
import builtins
import contextlib
import importlib.util
import socket

import pytest

import routes.email_routes as email_routes
from src.database import Document, SessionLocal
from src.document_processor import INGESTIBLE_EXTS, build_user_content
from src.markitdown_runtime import (
    MARKITDOWN_EXTS,
    NATIVE_OFFICE_EXTS,
    OFFICE_EXTS,
)
from src.upload_handler import UploadHandler
from tests.helpers.office_fixtures import (
    OFFICE_FIXTURE_EXTS,
    OFFICE_SENTINEL,
    office_fixture,
)

# `B858`. markitdown and `python-docx` live in `requirements-optional.txt`,
# which nothing installs by default — and every assertion below about what they
# RENDER was written on a machine that happened to have them. Twelve of them
# went red in the first CI run that ever completed, where only
# `requirements.txt` is installed, and the message they printed was the
# product's own correct banner: *"Office/EPUB document extraction requires
# markitdown."* The suite was failing a machine for the configuration the suite
# itself documents as supported.
#
# Asked of the interpreter, not of a list of environments: `find_spec` is the
# same question the product asks. The absent-dependency branch keeps running
# either way — it is the half that needs no dependency to prove, and it is the
# half this file exists for.
HAVE_MARKITDOWN = importlib.util.find_spec("markitdown") is not None
HAVE_DOCX = importlib.util.find_spec("docx") is not None

MARKITDOWN_REASON = (
    "markitdown is in requirements-optional.txt and is not installed here; "
    "this assertion is about what markitdown renders. The refusal branch is "
    "covered by test_a_format_whose_extractor_is_not_installed_is_refused_"
    "with_the_reason, which runs in every environment."
)
DOCX_REASON = (
    "python-docx is in requirements-optional.txt and is not installed here; "
    "this assertion is about the rendering it produces."
)

needs_markitdown = pytest.mark.skipif(not HAVE_MARKITDOWN, reason=MARKITDOWN_REASON)
needs_docx = pytest.mark.skipif(not HAVE_DOCX, reason=DOCX_REASON)


def _skip_if_that_format_needs_an_absent_extractor(ext: str) -> None:
    """Skip one parameter, not the sweep: `.doc` and `.odt` read without it."""
    if ext in MARKITDOWN_EXTS and not HAVE_MARKITDOWN:
        pytest.skip(f"{ext}: {MARKITDOWN_REASON}")


RAW_EMAIL = b"Subject: t\r\nMessage-ID: <m@x>\r\n\r\nbody\r\n"

# The six the row measured, spelled out rather than imported. A test that takes
# its expectations from the register it is testing proves only that the code
# agrees with itself — dropping `.xls` from `MARKITDOWN_EXTS` would also drop it
# from the sweep and nothing would fail. These six are the measurement.
REFUSED_BEFORE = (".doc", ".epub", ".odt", ".pptx", ".xls", ".xlsx")


# ── driving the two doors ───────────────────────────────────────────────────

def _drive_mailbox(tmp_path, monkeypatch, name, body: bytes):
    """Call the real `POST /api/email/attachment-as-doc` over one real file."""
    target = tmp_path / "extract"
    target.mkdir(parents=True, exist_ok=True)
    (target / name).write_bytes(body)

    @contextlib.contextmanager
    def fake_imap(account_id=None, owner=""):
        yield type("C", (), {"select": lambda self, *a, **k: None})()

    monkeypatch.setattr(email_routes, "_imap", fake_imap)
    monkeypatch.setattr(email_routes, "_imap_uid_fetch",
                        lambda *a, **k: ("OK", [(None, RAW_EMAIL)]))
    monkeypatch.setattr(email_routes, "attachment_extract_dir",
                        lambda folder, uid: target)
    monkeypatch.setattr(email_routes, "_extract_attachment_to_disk",
                        lambda msg, index, d: target / name)
    monkeypatch.setattr("src.auth_helpers.get_current_user", lambda request: "tester")

    router = email_routes.setup_email_routes()
    endpoint = next(
        r.endpoint for r in router.routes
        if r.path == "/api/email/attachment-as-doc/{uid}/{index}"
        and "POST" in getattr(r, "methods", set())
    )
    return endpoint("42", 0, request=None, folder="INBOX",
                    account_id=None, owner="tester")


def _document_body(result) -> str:
    """The text the route actually stored. A `doc_id` is not evidence."""
    assert result.get("doc_id"), result
    db = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == result["doc_id"]).first()
        assert doc is not None, result
        return doc.current_content or ""
    finally:
        db.close()


def _drive_composer(tmp_path, name, body: bytes) -> str:
    """Drive the real ``build_user_content`` over the same bytes."""
    handler = UploadHandler(str(tmp_path), str(tmp_path / "uploads"))
    path = tmp_path / "uploads" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    out = build_user_content(
        "please read this", ["fid"], str(tmp_path / "uploads"), handler,
        owner="tester",
        resolved_uploads={"fid": {"path": str(path), "name": name, "mime": None}},
    )
    if isinstance(out, str):
        return out
    return "".join(b.get("text", "") for b in out if isinstance(b, dict))


def _without_markitdown(monkeypatch):
    """Make the optional dependency absent, the way the product sees it."""
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "markitdown" or name.startswith("markitdown."):
            raise ImportError("No module named markitdown")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)


# ── the row's first Verify clause ───────────────────────────────────────────

@pytest.mark.parametrize("ext", REFUSED_BEFORE)
def test_the_six_formats_the_composer_reads_now_open_in_the_mailbox(
        tmp_path, monkeypatch, ext):
    """*"a `.xlsx` attachment opens in the editor"*, over a real file of each.

    Every one of these answered ``Unsupported attachment type: <ext>`` before
    this row, which is what makes this the `Law 9` test: it fails on the tree as
    it stood, six times, for six different reasons that are all the same reason.
    """
    _skip_if_that_format_needs_an_absent_extractor(ext)
    result = _drive_mailbox(tmp_path, monkeypatch, "report" + ext,
                            office_fixture(ext))
    assert "error" not in result, result
    assert result.get("filename") == "report" + ext
    assert OFFICE_SENTINEL in _document_body(result), ext


@pytest.mark.parametrize("ext", sorted(OFFICE_FIXTURE_EXTS))
def test_both_doors_put_the_same_document_s_prose_in_front_of_the_user(
        tmp_path, monkeypatch, ext):
    """The union, asserted on both sides rather than on the register.

    `Law 13`'s through-line for this wave: a file the composer can read and the
    mailbox cannot must be a deliberate, written difference or must not exist.
    Driven over one real file of every office format there is.
    """
    _skip_if_that_format_needs_an_absent_extractor(ext)
    body = office_fixture(ext)
    mailbox = _document_body(
        _drive_mailbox(tmp_path / "m", monkeypatch, "report" + ext, body))
    composer = _drive_composer(tmp_path / "c", "report" + ext, body)
    assert OFFICE_SENTINEL in mailbox, ext
    assert OFFICE_SENTINEL in composer, ext


@needs_markitdown
def test_one_docx_renders_identically_whichever_door_it_came_through(
        tmp_path, monkeypatch):
    """The row's second `Verify` clause.

    The mailbox walked `python-docx` paragraphs and built its own markdown while
    chat ingest sent the same file through markitdown. Measured on the fixture
    below, the two disagreed on both of the things it carries: the list arrived
    as two unmarked lines from the mailbox and as ``*`` bullets from the
    composer, and the table's header row was in different places. Now the
    mailbox's markdown is *contained in* what the composer puts in the message,
    which is the strongest form of "identically" that can be asserted — the
    composer wraps it in its ``[Document content — …]`` header.
    """
    body = office_fixture(".docx")
    mailbox = _document_body(
        _drive_mailbox(tmp_path / "m", monkeypatch, "report.docx", body))
    composer = _drive_composer(tmp_path / "c", "report.docx", body)

    assert mailbox.strip(), "the mailbox stored nothing"
    assert mailbox.strip() in composer, (
        "the two doors render one .docx differently:\n"
        f"--- mailbox ---\n{mailbox}\n--- composer ---\n{composer}"
    )
    # And the rendering is markitdown's, on both sides — the structure the
    # hand-rolled reader dropped.
    assert "# Quarterly Report" in mailbox
    assert "* Revenue rose in the third quarter." in mailbox


# ── the refusal names why, derived rather than transcribed ──────────────────

@pytest.mark.parametrize("ext", sorted(MARKITDOWN_EXTS))
def test_a_format_whose_extractor_is_not_installed_is_refused_with_the_reason(
        tmp_path, monkeypatch, ext):
    """The other half of the row's `Verify`: *refused with a reason that names why*.

    ``Unsupported attachment type: .xlsx`` is not a reason — it is a statement
    about the file type, and the file type is supported. What the caller gets
    now is the one sentence the composer's banner prints for the same file, so
    the person is told the same thing by both doors and it happens to be the
    thing they can act on.
    """
    from src.markitdown_runtime import MARKITDOWN_MISSING

    _without_markitdown(monkeypatch)
    result = _drive_mailbox(tmp_path, monkeypatch, "report" + ext,
                            office_fixture(ext))
    if ext == ".docx":
        # `.docx` has bundled readers, so it does not reach a refusal at all.
        assert result.get("doc_id"), result
        return
    assert "doc_id" not in result, result
    assert MARKITDOWN_MISSING in result["error"], result
    assert "Unsupported attachment type" not in result["error"]
    assert "report" + ext in result["error"]


@pytest.mark.parametrize("ext", sorted(NATIVE_OFFICE_EXTS | {".docx"}))
def test_the_bundled_formats_open_with_markitdown_absent(
        tmp_path, monkeypatch, ext):
    """`B102`'s readers are bundled, so "install the optional dep" would be a lie.

    `.docx` is in this list because `B240` moved the mailbox's `python-docx`
    reader into the extractor chain instead of deleting it (`Law 1`) — so the
    format markitdown normally handles still has an answer without it.
    """
    _without_markitdown(monkeypatch)
    result = _drive_mailbox(tmp_path, monkeypatch, "report" + ext,
                            office_fixture(ext))
    assert OFFICE_SENTINEL in _document_body(result), ext


@needs_docx
def test_the_docx_reader_the_mailbox_owned_now_answers_for_every_consumer(
        tmp_path, monkeypatch):
    """`Law 1`: the hand-rolled reader was moved, not deleted — and it moved *up*.

    Before this row the `python-docx` rendering existed only inside
    ``attachment_as_doc``; the composer's fallback when markitdown is missing was
    the bare ``<w:t>`` walk, which drops tables. With markitdown absent the
    composer now gets the table rows, because the reader is a rung of the shared
    `.docx` chain rather than a branch of one route.
    """
    _without_markitdown(monkeypatch)
    rendered = _drive_composer(tmp_path, "report.docx", office_fixture(".docx"))
    assert OFFICE_SENTINEL in rendered
    assert "| region | total |" in rendered, (
        "the composer lost the python-docx rendering the mailbox used to have"
    )


def test_the_mailbox_reads_the_register_rather_than_a_copy_of_it(
        tmp_path, monkeypatch):
    """`Law 13`, proved by moving the register and watching the route move.

    A branch that spelled its own seven extensions would pass every test above
    and fail this one. Empty the register and the `.xlsx` has to stop being an
    office file at that door.
    """
    monkeypatch.setattr("src.markitdown_runtime.OFFICE_EXTS", frozenset())
    result = _drive_mailbox(tmp_path, monkeypatch, "report.xlsx",
                            office_fixture(".xlsx"))
    assert result.get("error", "").startswith("Unsupported attachment type"), (
        "the mailbox is not asking OFFICE_EXTS"
    )


def test_the_refusal_reason_is_the_extractors_answer_and_not_this_routes(
        tmp_path, monkeypatch):
    """The reason is derived, so breaking the derivation breaks the refusal."""
    monkeypatch.setattr("src.markitdown_runtime.office_extraction_gap",
                        lambda path: "SENTINELgapANSWER")
    monkeypatch.setattr("src.markitdown_runtime.convert_to_markdown",
                        lambda path: None)
    result = _drive_mailbox(tmp_path, monkeypatch, "report.xlsx",
                            office_fixture(".xlsx"))
    assert result.get("error") == "report.xlsx: SENTINELgapANSWER", result


def test_every_office_extension_in_the_ingest_register_has_a_fixture_here():
    """The sweep cannot silently stop covering a format.

    ``OFFICE_EXTS`` is what the mailbox now asks; if a format is added to it and
    no real file of it is added here, the parametrised tests above quietly stop
    testing it. This is the assertion that makes that loud.
    """
    assert OFFICE_FIXTURE_EXTS == OFFICE_EXTS
    assert OFFICE_EXTS <= INGESTIBLE_EXTS
    assert set(REFUSED_BEFORE) <= OFFICE_EXTS


def test_the_gap_function_does_not_blame_the_missing_dependency_for_everything():
    """The three answers, asked directly, because two of them are unreachable
    from the route and would otherwise be untested.

    The route only calls this for a format in ``OFFICE_EXTS``, so the
    no-extractor answer has no caller today — and an answer that is wrong but
    unreachable becomes wrong and reachable the first time someone adds a
    caller. The `.odt`/`.doc` answer is `B102`'s distinction: their readers are
    bundled, so telling a person to install markitdown would be a lie about a
    format that is already supported.
    """
    from src.markitdown_runtime import (
        MARKITDOWN_MISSING,
        NO_EXTRACTABLE_TEXT,
        NO_OFFICE_EXTRACTOR,
        office_extraction_gap,
    )

    assert office_extraction_gap("/tmp/old.wpd") == NO_OFFICE_EXTRACTOR
    assert office_extraction_gap("/tmp/notes.txt") == NO_OFFICE_EXTRACTOR
    for ext in sorted(NATIVE_OFFICE_EXTS):
        assert office_extraction_gap("/tmp/report" + ext) == NO_EXTRACTABLE_TEXT
        assert MARKITDOWN_MISSING not in office_extraction_gap("/tmp/report" + ext)


def test_the_gap_function_names_the_dependency_only_when_it_is_missing(monkeypatch):
    """The same call, both sides of the one condition that makes it vary."""
    from src.markitdown_runtime import (
        MARKITDOWN_MISSING,
        NO_EXTRACTABLE_TEXT,
        office_extraction_gap,
    )

    if HAVE_MARKITDOWN:
        # `B858`. The "installed" half of "both sides of the one condition" can
        # only be asserted where it is installed. The half below cannot be
        # faked away and runs everywhere.
        assert office_extraction_gap("/tmp/sheet.xlsx") == NO_EXTRACTABLE_TEXT
    _without_markitdown(monkeypatch)
    assert office_extraction_gap("/tmp/sheet.xlsx") == MARKITDOWN_MISSING
    # And `B102`'s distinction, which only shows with the dependency gone: the
    # bundled readers are always present, so a `.doc` or an `.odt` that came out
    # empty is empty — telling the person to install markitdown would point them
    # at a dependency that would not have read it either.
    for ext in sorted(NATIVE_OFFICE_EXTS):
        assert office_extraction_gap("/tmp/report" + ext) == NO_EXTRACTABLE_TEXT


# ── `Law 16` ────────────────────────────────────────────────────────────────

def test_no_extractor_opens_a_socket_to_read_a_local_file(tmp_path, monkeypatch):
    """`Law 16`, driven rather than assumed.

    markitdown ships converters that fetch URLs — YouTube pages, search results
    — and an extractor that quietly reached one of them to render an attachment
    would be a document leaving the machine. Every socket constructor is made to
    raise, and all seven formats are driven through the real route underneath.
    """
    def refuse(*args, **kwargs):
        raise AssertionError("an extractor opened a socket to read a local file")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)

    driven = []
    for ext in sorted(OFFICE_FIXTURE_EXTS):
        if ext in MARKITDOWN_EXTS and not HAVE_MARKITDOWN:
            continue  # `B858`: the format is skipped, the law is not
        result = _drive_mailbox(tmp_path / ext.lstrip("."), monkeypatch,
                                "report" + ext, office_fixture(ext))
        assert OFFICE_SENTINEL in _document_body(result), ext
        driven.append(ext)
    assert driven, "no office format was driven — the law was not tested at all"


# ── the fourth reader the office branch was hiding ──────────────────────────

RUSSIAN = "Привет, мир! Конфигурация сервера для отдела продаж.\n"
POLISH = "Zażółć gęślą jaźń — plik konfiguracyjny serwera.\n"


@pytest.mark.parametrize("name,body,expected", [
    ("notes.txt", (RUSSIAN * 8).encode("cp1251"), RUSSIAN),
    ("rows.csv", (POLISH * 8).encode("cp1250"), POLISH),
    ("wide.txt", (RUSSIAN * 4).encode("utf-16"), RUSSIAN),
])
def test_the_mailbox_reads_an_attachment_in_the_encoding_it_identified(
        tmp_path, monkeypatch, name, body, expected):
    """The `.docx` branch was not the only thing this route answered on its own.

    Both text branches read with ``read_text(encoding="utf-8",
    errors="replace")`` — a fourth reader, which threw away the encoding the
    probe had just identified. Measured on the tree before this row, driven
    through the route: the cp1251 file opened as U+FFFD end to end, the cp1250
    one as ``Za??? g?l? ja??``, and the BOM'd UTF-16 one as NUL-separated
    letters. `B101` gave the composer ``decode_text_file`` for exactly this;
    the mailbox calls it now (`Law 13`).
    """
    result = _drive_mailbox(tmp_path, monkeypatch, name, body)
    stored = _document_body(result)
    assert expected.strip() in stored, repr(stored[:80])
    assert "�" not in stored
    assert "\x00" not in stored


# ── `Law 1`: what must still be refused ─────────────────────────────────────

@pytest.mark.parametrize("name,body", [
    ("photo.png", b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + bytes(64)),
    ("old.wpd", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + bytes(512)),
    ("deck.pages", b"PK\x03\x04" + bytes(64)),
])
def test_a_format_with_no_extractor_is_still_refused_by_type(
        tmp_path, monkeypatch, name, body):
    """Widening the door must not open it to everything.

    `emailLibrary.js` falls back to the download route on any ``{error}``, and
    that contract is this shape: an ``{error}`` with no ``doc_id``, naming the
    extension.
    """
    result = _drive_mailbox(tmp_path, monkeypatch, name, body)
    assert "doc_id" not in result, result
    assert result["error"].startswith("Unsupported attachment type:")
