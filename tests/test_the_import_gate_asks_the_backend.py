# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B232`/`B233` — the composer stopped guessing, and a `.doc` stopped arriving as bytes.

Two rows, one file, because they are one defect seen from two ends.

**`B232`.** `static/js/chat.js` decided which files may be imported with a
hand-maintained **38-extension regex** at `:2485` and a *different*
36-extension one at `:7672`, in front of a backend that derives the answer.
Measured against the real registers before this row, the gate was wrong in both
directions at once:

* **10 ingestible extensions were never offered** — `.bash .doc .docx .epub
  .nix .odt .pdf .pptx .xls .xlsx` — five of them formats the server has had a
  bundled extractor for since `B102`.
* **9 offered extensions no register names** — `.conf .env .ini .less .sass
  .scss .svelte .toml .vue` — and those nine were the *right* answer, because
  `looks_like_text` rescues them on the server (`B76`). The composer was already
  offering files no register names, which is the evidence that the question was
  never "is the extension on a list".

**The naive fix was a trap and it is pinned here.** `INGESTIBLE_EXTS` is
`TEXT_EXTS | OFFICE_EXTS | PDF_EXTS`, so handing it to the banner verbatim
offers `.pdf`, `.docx`, `.xlsx`, `.pptx` and `.epub` to a code path that
pre-reads the raw `File` **as text** — "offer to import a `.zip`" in another
costume. `test_a_container_is_never_handed_to_the_text_reader` is that trap,
driven.

**`B233`.** `documentLibrary.js` `readFileContent` branched on
`.xlsx/.xls/.ods` and on `.docx` and **on nothing else**, so a `.doc` fell
through to `FileReader.readAsText` and the library stored the OLE2 bytes of a
legacy Word file under `language: 'markdown'`. Driven on the tree as it stood,
the harness records exactly that: the POST body's `content` begins
`\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1`.

`Law 20`: every JS assertion below runs the real block out of the real module
under node. `Law 9`: the harnesses run on the tree before this row too and
report what it answered — see each test's docstring for the measured before.
"""
import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import src.document_processor as dp
from src.document_processor import INGESTIBLE_EXTS, TEXT_EXTS
from src.markitdown_runtime import OFFICE_EXTS
from src.pdf_runtime import PDF_EXTS

# Resolved with `getattr`, the pattern
# `tests/test_short_sample_encoding_guess.py` already uses. `Law 9` wants each
# test below to fail **on the tree as it stood** for its own reason; a
# module-level ImportError collapses all of them into one collection error,
# which is weaker evidence and hides which ones were already true. The defaults
# describe the old tree — there was no third answer, so everything was a
# boolean and the composer decided with a regex.
EXTRACTED_EXTS = getattr(dp, "EXTRACTED_EXTS", OFFICE_EXTS | PDF_EXTS)
INGEST_KIND_TEXT = getattr(dp, "INGEST_KIND_TEXT", "text")
INGEST_KIND_DOCUMENT = getattr(dp, "INGEST_KIND_DOCUMENT", "document")
INGEST_KIND_BINARY = getattr(dp, "INGEST_KIND_BINARY", "binary")
ingest_kind = getattr(dp, "ingest_kind", lambda path, name=None: "binary")

ROOT = Path(__file__).resolve().parent.parent
H_GATE = ROOT / "tests" / "harness" / "composer_import_gate.js"
H_LIB = ROOT / "tests" / "harness" / "library_office_import.js"
JS_LANG = ROOT / "static" / "js" / "attachmentLanguage.js"

needs_node = pytest.mark.skipif(not shutil.which("node"),
                                reason="node binary not on PATH")

# A real OLE2/CFB header — what a legacy `.doc` actually starts with.
OLE2_HEADER = bytes.fromhex("d0cf11e0a1b11ae1") + b"\x00" * 32
ZIP_HEADER = b"PK\x03\x04" + b"\x00" * 32


def _run(harness: Path, *argv: str) -> dict:
    env = dict(os.environ)
    # The library harness lifts `SERVER_EXTRACTED_EXTS` out of the module and
    # needs the one input that module imports: the generated `OFFICE_EXTS`.
    # Passed from the Python register so a drift between the two is a failure
    # here as well as in the gate checker.
    env["OFFICE_EXTS_JSON"] = json.dumps(sorted(OFFICE_EXTS))
    proc = subprocess.run(["node", str(harness), *argv],
                          capture_output=True, text=True, env=env)
    assert proc.returncode == 0, f"{harness.name} {argv}: {proc.stderr}"
    return json.loads(proc.stdout)


def _write(tmp_path, name: str, body: bytes) -> str:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return str(path)


# ── the decision itself ─────────────────────────────────────────────────────


def test_the_verdict_is_three_answers_and_not_a_boolean(tmp_path):
    """The shape of the fix, which is the thing the row says the regex got wrong.

    `.kt` is text and no register names it. `.docx` is a zip and the product
    reads it anyway. `.png` is neither. A single yes/no cannot carry those three
    and the 38-extension regex was a single yes/no.
    """
    assert ingest_kind(_write(tmp_path, "Main.kt", b"fun main() {}")) == INGEST_KIND_TEXT
    assert ingest_kind(_write(tmp_path, "server.toml", b"[a]\nb = 1\n")) == INGEST_KIND_TEXT
    assert ingest_kind(_write(tmp_path, "README", b"no suffix at all\n")) == INGEST_KIND_TEXT
    assert ingest_kind(_write(tmp_path, "memo.doc", OLE2_HEADER)) == INGEST_KIND_DOCUMENT
    assert ingest_kind(_write(tmp_path, "letter.docx", ZIP_HEADER)) == INGEST_KIND_DOCUMENT
    assert ingest_kind(_write(tmp_path, "report.pdf", b"%PDF-1.4\n")) == INGEST_KIND_DOCUMENT
    assert ingest_kind(_write(tmp_path, "photo.png",
                              b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)) == INGEST_KIND_BINARY


def test_the_extractor_is_asked_before_the_byte_probe(tmp_path):
    """Order, and why it is that way rather than the other way.

    A `.docx` is a zip: `looks_like_text` says no, correctly. If the probe ran
    first the product would call a file it can read `binary`. The extension
    answers *which extractor*; the bytes answer *whether there is anything to
    read at all*, and only for the files no extractor claims.
    """
    docx = _write(tmp_path, "letter.docx", ZIP_HEADER)
    assert dp.looks_like_text(docx) is False
    assert ingest_kind(docx) == INGEST_KIND_DOCUMENT


def test_the_registers_are_the_union_and_not_a_copy():
    """`Law 13`. `EXTRACTED_EXTS` is stated as a union, so it cannot drift."""
    assert EXTRACTED_EXTS == OFFICE_EXTS | PDF_EXTS
    assert INGESTIBLE_EXTS == TEXT_EXTS | EXTRACTED_EXTS
    # The subtraction the row names: what an extractor reads and a text probe
    # cannot. This is the set the 38-extension regex never offered.
    assert sorted(EXTRACTED_EXTS) == [
        ".doc", ".docx", ".epub", ".odt", ".pdf", ".pptx", ".xls", ".xlsx"]


def test_the_measured_gap_is_gone_in_both_directions(tmp_path):
    """The row's two measurements, re-derived from the registers rather than
    quoted.

    The first list is what the old regex refused and the product can read; the
    second is what it offered and no register names. The new answer offers
    **both** — the first as containers to post, the second as text, because the
    bytes decode — and that is the whole of `B232` in one assertion.
    """
    old_regex_exts = {
        ".txt", ".py", ".js", ".ts", ".html", ".htm", ".css", ".md", ".json",
        ".csv", ".yml", ".yaml", ".sh", ".sql", ".rs", ".go", ".java", ".c",
        ".cpp", ".h", ".rb", ".php", ".xml", ".jsx", ".tsx", ".log", ".toml",
        ".ini", ".conf", ".env", ".vue", ".svelte", ".scss", ".sass", ".less",
    }
    missing = sorted(INGESTIBLE_EXTS - old_regex_exts)
    assert missing == [".bash", ".doc", ".docx", ".epub", ".nix", ".odt",
                       ".pdf", ".pptx", ".xls", ".xlsx"], missing
    unnamed = sorted(old_regex_exts - INGESTIBLE_EXTS)
    assert unnamed == [".conf", ".env", ".ini", ".less", ".sass", ".scss",
                       ".svelte", ".toml", ".vue"], unnamed

    for ext in missing:
        body = OLE2_HEADER if ext == ".doc" else (
            b"%PDF-1.4\n" if ext == ".pdf" else (
                ZIP_HEADER if ext in {".docx", ".epub", ".odt", ".pptx",
                                      ".xls", ".xlsx"} else b"plain text\n"))
        kind = ingest_kind(_write(tmp_path, "f" + ext, body))
        assert kind in (INGEST_KIND_TEXT, INGEST_KIND_DOCUMENT), (ext, kind)
    for ext in unnamed:
        kind = ingest_kind(_write(tmp_path, "f" + ext, b"key = value\n"))
        assert kind == INGEST_KIND_TEXT, (ext, kind)


# ── the upload response and the header that carry it ────────────────────────


class _Request:
    def __init__(self):
        self.state = SimpleNamespace(current_user=None)
        self.app = SimpleNamespace(state=SimpleNamespace(auth_manager=None))
        self.client = SimpleNamespace(host="127.0.0.1")


def _upload_router(tmp_path, monkeypatch, name: str, body: bytes):
    """Drive the real `GET /api/upload/{id}` over one real file on disk."""
    import fastapi.dependencies.utils as dependency_utils
    import routes.upload_routes as upload_routes
    from src.upload_handler import UploadHandler

    monkeypatch.setattr(dependency_utils, "ensure_multipart_is_installed",
                        lambda: None)
    upload_dir = tmp_path / "uploads" / "2026" / "09" / "16"
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_id = "e" * 32 + os.path.splitext(name)[1]
    path = upload_dir / file_id
    path.write_bytes(body)

    handler = UploadHandler(str(tmp_path), str(tmp_path / "uploads"))
    index = {"owner:hash": {
        "id": file_id, "path": str(path), "mime": "application/octet-stream",
        "size": len(body), "name": name, "original_name": name, "owner": "owner",
    }}
    monkeypatch.setattr(handler, "_load_upload_index", lambda: index)
    router, _cleanup = upload_routes.setup_upload_routes(handler)
    endpoint = {r.endpoint.__name__: r.endpoint
                for r in router.routes}["download_file"]
    return asyncio.run(endpoint(_Request(), file_id, thumb=0))


@pytest.mark.parametrize("name,body,want", [
    ("Main.kt", b"fun main() { println(1) }", INGEST_KIND_TEXT),
    ("server.toml", b"[server]\nport = 80\n", INGEST_KIND_TEXT),
    ("memo.doc", OLE2_HEADER, INGEST_KIND_DOCUMENT),
    ("report.pdf", b"%PDF-1.4\n%%EOF\n", INGEST_KIND_DOCUMENT),
    ("photo.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, INGEST_KIND_BINARY),
])
def test_the_download_route_publishes_the_verdict(tmp_path, monkeypatch,
                                                  name, body, want):
    """`B232`'s server half, at the door the browser already knocks on.

    An attachment the browser has an id for has no `File` to probe, so the
    answer has to travel on the response. `X-Preview-Refused` is the precedent:
    a decision this process has already made, published rather than re-derived
    in the browser.
    """
    response = _upload_router(tmp_path, monkeypatch, name, body)
    headers = {k.lower(): v for k, v in response.headers.items()}
    assert headers["x-upload-kind"] == want
    # `Law 1`: the header is additive and nothing else about the response moved.
    assert headers["x-content-type-options"] == "nosniff"


def test_a_probe_that_cannot_read_the_file_says_binary(tmp_path, monkeypatch):
    """The failure mode, fixed in the direction that refuses.

    `looks_like_text` answers "not text" for a path it cannot open, and the
    route's wrapper does the same for anything the probe raises. A route whose
    job is to serve bytes must not 500 because a classification failed.
    """
    import routes.upload_routes as upload_routes

    def boom(*_a, **_k):
        raise OSError("disk went away")

    monkeypatch.setattr(upload_routes, "ingest_kind", boom)
    assert upload_routes._upload_kind("/nope", "x.txt") == INGEST_KIND_BINARY


# ── the composer, driven ────────────────────────────────────────────────────


@needs_node
def test_the_composer_offers_what_the_server_says_it_can_read():
    """`B232`'s `Verify:` — *a `.kt` attachment is offered for import*.

    **On the tree as it stood** this harness answered
    `["notes.txt", "server.toml", ".env", "refused.txt"]`: no `Main.kt`, no
    `report.pdf`, no `memo.doc`, no `deck.pptx`.
    """
    out = _run(H_GATE, "verdicts")
    assert "Main.kt" in out["offered"], out["offered"]
    assert "server.toml" in out["offered"]
    assert ".env" in out["offered"]
    assert "report.pdf" in out["offered"]
    assert "memo.doc" in out["offered"]
    assert "deck.pptx" in out["offered"]
    assert "photo.png" not in out["offered"]
    assert "archive.zip" not in out["offered"]


@needs_node
def test_a_container_is_never_handed_to_the_text_reader():
    """The trap, driven: `INGESTIBLE_EXTS` swapped in verbatim lands here.

    The real import loop is run over the rows the real gate picked, and both
    `file.text()` and the POST helper record their calls — so this is a thing
    the harness watched happen, not a property inferred from a field. A `.pdf`
    or a `.doc` in `readAsText` is the "offer to import a `.zip`" failure
    wearing this row's clothes.
    """
    out = _run(H_GATE, "verdicts")
    assert out["error"] is None, out["error"]
    for name in out["readAsText"]:
        assert not any(name.lower().endswith(ext) for ext in EXTRACTED_EXTS), name
    assert out["readAsText"] == ["notes.txt", "Main.kt", "server.toml", ".env"]
    # Every container went to an import route with its bytes, not as a string.
    containers = [t for t, u in zip(out["posted"], out["postedTo"])
                  if u.startswith("/api/documents/import-")]
    assert containers == ["report.pdf", "memo.doc", "deck.pptx"], out
    assert out["imported"] == 7


@needs_node
def test_a_refused_upload_is_not_offered_for_import():
    """Found while closing this row, and it is `B03` in a fifth place.

    On the tree as it stood the banner read the *pending* files, so a file the
    server **rejected** — never stored, no id, still sitting in the composer —
    was offered for import anyway: the harness recorded `refused.txt` in the
    offered list. Reading the upload outcome instead is what makes it impossible.
    """
    out = _run(H_GATE, "verdicts")
    assert "refused.txt" not in out["offered"], out["offered"]
    assert "refused.txt" not in out["readAsText"]
    assert "refused.txt" not in out["posted"]


@needs_node
def test_no_verdict_is_not_the_same_as_text():
    """The fallback that must not exist.

    An older server, or a response shape that moves, leaves `kind` absent on a
    file that uploaded perfectly well. Defaulting that to `text` is how a `.zip`
    ends up being read with `file.text()` — the whole failure this row is
    about — so an absent verdict offers nothing at all. The composer has an
    upload id in hand and can ask again; guessing is what it stopped doing.
    """
    out = _run(H_GATE, "stale")
    assert out["offered"] == [], out["offered"]
    assert out["readAsText"] == []
    assert out["posted"] == []


@needs_node
@pytest.mark.parametrize("mode", ["drain", "mismatch"])
def test_nothing_is_offered_from_somebody_elses_upload(mode):
    """The `B03` discipline, applied to the second reader of the same list.

    A queue drain's rows travelled on the queued item and the module's last
    upload belongs to a different batch. Same length is not the same batch, so
    the per-row name is checked as well — which is exactly what the bubble
    pairing beside it does.
    """
    out = _run(H_GATE, mode)
    assert out["offered"] == [], out["offered"]


# ── the library, driven ─────────────────────────────────────────────────────


@needs_node
@pytest.mark.parametrize("name", ["memo.doc", "report.odt", "deck.pptx",
                                  "book.epub"])
def test_a_container_dropped_on_the_library_is_extracted_by_the_server(name):
    """`B233`'s `Verify:` — *importing a `.doc` produces its prose, or is
    refused with a reason; it does not produce a markdown document full of
    control characters.*

    **On the tree as it stood**, driven, `memo.doc` POSTed
    `{"content": "\\u00d0\\u00cf\\u0011\\u00e0\\u00a1\\u00b1\\u001a\\u00e1…",
    "language": "markdown"}` to `/api/document` — the OLE2 header of a legacy
    Word file, stored as the document's text. `.odt`, `.pptx` and `.epub` each
    stored `PK\\u0003\\u0004`.
    """
    out = _run(H_LIB, name)
    assert out["endpoints"] == ["/api/documents/import-office"], out
    assert out["postedAsFile"] == [True]
    # Nothing was read in the browser, so no bytes were sent as `content`.
    assert out["contents"] == [None]
    assert out["imported"] == 1


@needs_node
@pytest.mark.parametrize("name,expected", [
    ("notes.txt", "plain words\n"),
    ("letter.docx", "# mammoth markdown\n"),
])
def test_the_client_converters_this_module_has_are_untouched(name, expected):
    """`Law 1`. `.docx` through mammoth and a plain text file through the
    reader both still take the path they took before this row — the new branch
    is the *subtraction* of what the browser can convert from what the server
    extracts, not a replacement for it."""
    out = _run(H_LIB, name)
    assert out["endpoints"] == ["/api/document"], out
    assert out["contents"] == [expected]
    assert out["postedAsFile"] == [False]


@needs_node
def test_a_spreadsheet_still_becomes_csv_in_the_browser():
    """`Law 1` again, and the one the register subtraction has to get right:
    `.xls`/`.xlsx` are in `OFFICE_EXTS` **and** have a client converter, so
    they must not be routed to the server."""
    out = _run(H_LIB, "sheet.xlsx")
    assert out["endpoints"] == ["/api/document"]
    assert out["languages"] == ["csv"]
    assert out["contents"] == ["a,b\n1,2\n"]


# ── the generated registers ─────────────────────────────────────────────────


@needs_node
def test_the_browser_reads_the_servers_registers_and_not_a_copy():
    """`Law 14`. The browser cannot import a Python register, so the registers
    it needs are **generated** from the three modules that own them and
    `.pantheon/check-attachment-language.py` fails the gate when they drift.
    Driven here rather than diffed: both sides are asked about every extension.
    """
    script = (
        "import { TEXT_EXTS, OFFICE_EXTS, PDF_EXTS, INGESTIBLE_EXTS, "
        "ingestKindFromName, isExtractedExtension } from '%s';\n"
        "console.log(JSON.stringify({\n"
        "  text: [...TEXT_EXTS].sort(), office: [...OFFICE_EXTS].sort(),\n"
        "  pdf: [...PDF_EXTS].sort(), all: [...INGESTIBLE_EXTS].sort(),\n"
        "  kinds: Object.fromEntries([...INGESTIBLE_EXTS].map(e => "
        "[e, ingestKindFromName('x' + e, '')])),\n"
        "  extracted: Object.fromEntries([...INGESTIBLE_EXTS].map(e => "
        "[e, isExtractedExtension('x' + e)])),\n"
        "  unknown: ingestKindFromName('Main.kt', ''),\n"
        "}));" % JS_LANG
    )
    proc = subprocess.run(["node", "--input-type=module", "--eval", script],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    js = json.loads(proc.stdout)
    assert js["text"] == sorted(TEXT_EXTS)
    assert js["office"] == sorted(OFFICE_EXTS)
    assert js["pdf"] == sorted(PDF_EXTS)
    assert js["all"] == sorted(INGESTIBLE_EXTS)
    for ext, kind in js["kinds"].items():
        assert kind == (INGEST_KIND_DOCUMENT if ext in EXTRACTED_EXTS
                        else INGEST_KIND_TEXT), ext
    for ext, extracted in js["extracted"].items():
        assert extracted is (ext in EXTRACTED_EXTS), ext
    # And the honest half: a suffix no register names is `null` in the browser,
    # not `binary`. Only the bytes can answer, and only the server has them.
    assert js["unknown"] is None


# ── the route the library half needed (`B233`) ──────────────────────────────


def _office_route(tmp_path, monkeypatch, name: str, body: bytes):
    """Drive the real `POST /api/documents/import-office` over one real file.

    Called directly, the way `tests/test_auth_disabled_document_access.py`
    drives the document router, so the assertion lands on the real closure.
    """
    import io
    import uuid as _uuid

    import fastapi.dependencies.utils as dependency_utils
    import routes.document.document_routes as droutes
    from fastapi import UploadFile
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import NullPool
    import core.database as cdb
    from src.upload_handler import UploadHandler

    monkeypatch.setattr(dependency_utils, "ensure_multipart_is_installed",
                        lambda: None)
    engine = create_engine(f"sqlite:///{tmp_path / 'docs.db'}",
                           connect_args={"check_same_thread": False},
                           poolclass=NullPool)
    cdb.Base.metadata.create_all(engine)
    monkeypatch.setattr(droutes, "SessionLocal",
                        sessionmaker(bind=engine, autoflush=False,
                                     autocommit=False))
    monkeypatch.setattr("src.auth_helpers.require_privilege",
                        lambda request, priv: "tester")

    handler = UploadHandler(str(tmp_path), str(tmp_path / "uploads"))
    router = droutes.setup_document_routes(None, handler)
    endpoint = next(r.endpoint for r in router.routes
                    if getattr(r, "path", None) == "/api/documents/import-office")
    upload = UploadFile(filename=name, file=io.BytesIO(body))
    return asyncio.run(endpoint(_Request(), file=upload, session_id=None))


def test_a_real_word_97_document_becomes_a_document_with_its_prose(
        tmp_path, monkeypatch):
    """`B233`'s `Verify:`, first clause, at the route.

    The extractor is `B102`'s and is not touched here: this row is the wiring
    that lets the library reach it, so the evidence is that a real Word 97 file
    posted to this route comes back as a Document whose content is the prose the
    mailbox already produced for the same bytes.
    """
    from tests.test_attachment_extension_registers import _word97_doc

    doc = _office_route(tmp_path, monkeypatch, "quarterly.doc", _word97_doc())
    assert doc["language"] == "markdown"
    assert doc["title"] == "quarterly"
    assert "Quarterly Report" in doc["current_content"]
    # And the row's own sentence: not a document full of control characters.
    assert "\xd0\xcf\x11\xe0" not in doc["current_content"]
    assert sum(1 for ch in doc["current_content"] if ord(ch) < 9) == 0


def test_an_odt_takes_the_same_route(tmp_path, monkeypatch):
    """`B102` bundled the `.odt` reader too, and it was reaching the library
    through `FileReader.readAsText` — i.e. not at all."""
    from tests.test_attachment_extension_registers import _odt_document

    doc = _office_route(tmp_path, monkeypatch, "notes.odt", _odt_document())
    assert doc["language"] == "markdown"
    assert "PK\x03\x04" not in doc["current_content"]


def test_a_format_nothing_reads_is_refused_at_the_door(tmp_path, monkeypatch):
    """`Law 16`-adjacent housekeeping and a real one: the extension is checked
    **before** `save_upload`, so a `.zip` posted here is refused without
    charging the rate limiter or committing bytes to disk."""
    from fastapi import HTTPException
    from src.markitdown_runtime import NO_OFFICE_EXTRACTOR

    with pytest.raises(HTTPException) as exc:
        _office_route(tmp_path, monkeypatch, "archive.zip", ZIP_HEADER)
    assert exc.value.status_code == 415
    assert NO_OFFICE_EXTRACTOR in str(exc.value.detail)
    assert not list((tmp_path / "uploads").rglob("*.zip"))


def test_a_container_with_no_text_is_refused_with_the_reason(tmp_path,
                                                             monkeypatch):
    """`B162`'s contract, one route on. "Nothing reads this format" and "a
    reader ran and there is no text in here" are different things to tell
    someone, and an empty document says neither."""
    import io
    import zipfile

    from fastapi import HTTPException
    from src.markitdown_runtime import NO_EXTRACTABLE_TEXT

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mimetype", "application/vnd.oasis.opendocument.text")
        z.writestr("content.xml", "<office:body></office:body>")
    with pytest.raises(HTTPException) as exc:
        _office_route(tmp_path, monkeypatch, "empty.odt", buf.getvalue())
    assert exc.value.status_code == 422
    assert NO_EXTRACTABLE_TEXT in str(exc.value.detail)


def test_the_upload_response_carries_the_verdict_per_file(tmp_path, monkeypatch):
    """`B232`'s server half at the *other* door: `POST /api/upload`.

    The composer has the `File` in hand and no id yet, so it reads the verdict
    off the response rather than asking for it — one field per accepted file,
    from the same `ingest_kind` the header uses.
    """
    import io

    import fastapi.dependencies.utils as dependency_utils
    import routes.upload_routes as upload_routes
    from fastapi import UploadFile
    from src.upload_handler import UploadHandler

    monkeypatch.setattr(dependency_utils, "ensure_multipart_is_installed",
                        lambda: None)
    handler = UploadHandler(str(tmp_path), str(tmp_path / "uploads"))
    router, _cleanup = upload_routes.setup_upload_routes(handler)
    endpoint = {r.endpoint.__name__: r.endpoint
                for r in router.routes}["api_upload"]

    batch = [
        ("notes.txt", b"plain words\n", INGEST_KIND_TEXT),
        ("Main.kt", b"fun main() { println(1) }\n", INGEST_KIND_TEXT),
        ("memo.doc", OLE2_HEADER, INGEST_KIND_DOCUMENT),
        ("photo.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, INGEST_KIND_BINARY),
    ]
    uploads = [UploadFile(filename=n, file=io.BytesIO(b)) for n, b, _ in batch]
    result = asyncio.run(endpoint(_Request(), files=uploads, session_id=None))
    got = {item["name"]: item["kind"] for item in result["files"]}
    for name, _body, want in batch:
        assert got.get(name) == want, (name, got)
