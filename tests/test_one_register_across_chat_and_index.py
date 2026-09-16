# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B162` / `B180` — a document a chat can read is a document the search can find.

Two agents fixed one seam from two sides last wave and neither could reach the
other's files, so the seam stayed open with the two halves facing each other:

* chat ingest asks ``document_processor.INGESTIBLE_EXTS`` — ``TEXT_EXTS`` (28)
  union ``markitdown_runtime.OFFICE_EXTS`` (7, including the bundled `.odt` and
  `.doc` readers `B102` wrote) union ``pdf_runtime.PDF_EXTS`` (1) — and, for a
  suffix none of those names, asks the *bytes* (`B76`, ``looks_like_text``);
* the indexers asked ``personal_docs.INDEXABLE_EXTENSIONS``, which `B75` built
  as a **fourth** register: a hand-written ten-entry ``TEXT_EXTENSIONS``, a
  restated ``PDF_EXTENSIONS`` and ``OFFICE_EXTENSIONS = MARKITDOWN_EXTS``.

Measured on the tree before this row, by importing both and by walking one
directory holding one file of each: chat read **36** extensions, the index
**16**, and the 20 in between — ``.bash .c .cpp .doc .go .h .htm .java .jsx
.log .nix .odt .php .rb .rs .sh .sql .ts .tsx .xml`` — were reported by the
index as *"unsupported extension"* while the same files put their prose in a
chat message.

And the reader was the second half of the same seam. ``personal_docs.read_text_file``
was ``open(..., encoding="utf-8", errors="ignore")``, the call `B101` removed
from the chat path and could not remove from this one. ``errors="ignore"`` does
not mangle a legacy-encoded file, it empties it, and it cannot raise, so nothing
downstream ever knew. Measured, over files the index accepted and indexed:

  * cp1251 Russian ``.txt`` -> ``'  '``, **zero tokens**, matches nothing,
    reports nothing;
  * cp1250 Polish ``Zażółć gęślą jaźń`` -> ``'Za gl ja'``;
  * BOM'd UTF-16 ``.txt`` -> ``'a\\x00t\\x00t\\x00...'``.

These drive the real indexers, the real chat gate and the real routes over real
files (`Law 20`). Nothing here reads a register to build its own expectation
except where the expectation is the identity itself.
"""

import asyncio
import io
import os
import zipfile
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

# Modules, not names: on the pre-change tree several of these names do not
# exist, and a collection-time ImportError reports "the fix is missing" where
# `Law 9` wants "the defect is present".
from src import personal_docs, rag_vector
import routes.personal_routes as personal_routes
from src.personal_docs import load_personal_index, retrieve_personal_keyword
from src.rag_vector import VectorRAG
from src.upload_handler import UploadHandler

SENTINEL = "SENTINELzebraBODY7f3a"

SKIP_UNSUPPORTED = getattr(personal_docs, "SKIP_UNSUPPORTED", "unsupported extension")
SKIP_NO_TEXT = getattr(personal_docs, "SKIP_NO_TEXT", "no extractable text")

# Suffixes no register names, whose bytes are text. `B76` made these reach the
# model; `B162`'s `Verify` names `.conf` explicitly, which is why a register
# alone could never have closed this row.
BYTES_ONLY = (".conf", ".toml", ".rst")
# Bytes that are not text under any suffix. These must keep the banner and keep
# the skip reason — widening the index must not widen it to containers.
NOT_TEXT = {"blob.png": b"\x89PNG\r\n\x1a\n\x00\x00\x00rIHDR",
            "blob.exe": b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00binary\x00\x00"}


def _minimal_docx(text: str) -> bytes:
    """A real `.docx` — markitdown reads it, and so does the bundled `<w:t>`
    reader when markitdown is not installed."""
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    doc = (f'<?xml version="1.0"?><w:document xmlns:w="{ns}"><w:body>'
           f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", doc)
    return buf.getvalue()


def _minimal_odt(text: str) -> bytes:
    """A real ODF text document: a zip whose ``content.xml`` holds `<text:p>`.

    `B102` wrote this extractor and the index called the format unsupported,
    which is the row's headline in one file.
    """
    ns = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
    content = (f'<?xml version="1.0"?><office:document-content '
               f'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
               f'xmlns:text="{ns}"><office:body><office:text>'
               f"<text:p>{text}</text:p></office:text></office:body>"
               f"</office:document-content>")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("mimetype", "application/vnd.oasis.opendocument.text")
        z.writestr("content.xml", content)
    return buf.getvalue()


def _vector_index(directory, file_extensions=None):
    """Drive the REAL index_personal_documents; collect what it stored."""
    stored = []
    store = VectorRAG.__new__(VectorRAG)
    store.add_document = lambda text, meta: (stored.append((text, meta)) or True)
    result = store.index_personal_documents(directory, file_extensions=file_extensions)
    return result, stored


def _sources(stored):
    return {meta["source"] for _text, meta in stored}


def _chat_reads(tmp_path, name, path):
    """The gate `build_user_content` asks, driven rather than restated.

    ``is_document_file`` is the register arm and ``looks_like_text`` is the byte
    arm; a file that satisfies either one reaches the model as text.
    """
    from src.document_processor import looks_like_text
    handler = UploadHandler(str(tmp_path), str(tmp_path / "uploads"))
    return handler.is_document_file(name) or looks_like_text(str(path))


@pytest.fixture
def vault(tmp_path):
    """One file of every extension chat ingest accepts, plus the awkward ones.

    Bodies are real: a text body for the text formats, real containers for the
    two office formats whose extractors are bundled, and a text body for the
    formats whose extractor needs an optional dependency — those are expected to
    be *reported with a reason*, which is the other half of the `Verify` clause.
    """
    from src.document_processor import INGESTIBLE_EXTS
    root = tmp_path / "vault"
    root.mkdir()
    for ext in sorted(INGESTIBLE_EXTS):
        (root / f"doc{ext}").write_text(f"{SENTINEL} content for {ext}", encoding="utf-8")
    (root / "doc.docx").write_bytes(_minimal_docx(SENTINEL))
    (root / "doc.odt").write_bytes(_minimal_odt(SENTINEL))
    for ext in BYTES_ONLY:
        (root / f"plain{ext}").write_text(f"{SENTINEL} decodes fine", encoding="utf-8")
    (root / "polish.txt").write_bytes("Zażółć gęślą jaźń".encode("cp1250"))
    (root / "russian.txt").write_bytes("сервер порт настройка".encode("cp1251"))
    (root / "wide.txt").write_bytes("attention widened".encode("utf-16"))
    for name, body in NOT_TEXT.items():
        (root / name).write_bytes(body)
    return root


# ── one register ────────────────────────────────────────────────────────────

def test_one_register_answers_can_we_read_this_extension():
    """`Law 13`. Measured before: 36 for chat, 16 for the index."""
    from src.document_processor import INGESTIBLE_EXTS

    index = set(personal_docs.INDEXABLE_EXTENSIONS)
    chat = set(INGESTIBLE_EXTS)
    assert index == chat, (
        f"{len(chat - index)} extensions chat ingest reads are unsupported to "
        f"the index: {sorted(chat - index)}"
    )
    # And both indexers still read that one register, not a copy of it.
    assert set(rag_vector.DEFAULT_FILE_EXTENSIONS) == index
    assert set(personal_docs.config.DEFAULT_EXTENSIONS) == index


def test_each_register_is_the_extractors_own_register():
    """`Law 14` — three registers, one per extractor, none of them restated."""
    from src.markitdown_runtime import OFFICE_EXTS
    from src.pdf_runtime import PDF_EXTS
    from src.document_processor import TEXT_EXTS

    assert personal_docs.TEXT_EXTENSIONS == frozenset(TEXT_EXTS)
    assert personal_docs.PDF_EXTENSIONS == frozenset(PDF_EXTS)
    assert personal_docs.OFFICE_EXTENSIONS == frozenset(OFFICE_EXTS)


def test_the_upload_gate_and_the_index_accept_the_same_extensions(tmp_path):
    """The two ends of the seam, asked as the product asks them."""
    handler = UploadHandler(str(tmp_path), str(tmp_path / "uploads"))
    accepted = {ext for ext in personal_docs.INDEXABLE_EXTENSIONS
                if handler.is_document_file("probe" + ext)}
    assert accepted == set(personal_docs.INDEXABLE_EXTENSIONS)


# ── the row's Verify clause, per file ───────────────────────────────────────

def test_every_file_chat_can_read_is_in_both_indexes_or_reported(vault, tmp_path):
    """Index one directory; account for every file in it, on both sides.

    This is `B75`'s `Verify` asked across the seam rather than inside one half
    of it: a file either reaches BOTH indexes or is reported skipped with a
    reason by both, and no file chat ingest can read is written off as an
    unsupported extension.
    """
    result, stored = _vector_index(str(vault))
    keyword_skips = []
    keyword = load_personal_index(str(vault), skipped=keyword_skips)

    in_vector = _sources(stored)
    in_keyword = {f["path"] for f in keyword if f["chunks"]}
    vector_skipped = {e["path"]: e["reason"] for e in result["skipped"]}
    keyword_skipped = {e["path"]: e["reason"] for e in keyword_skips}

    unsupported_but_readable = []
    for path in sorted(str(p) for p in vault.iterdir()):
        name = os.path.basename(path)
        both = path in in_vector and path in in_keyword
        reported = bool(vector_skipped.get(path)) and bool(keyword_skipped.get(path))
        assert both or reported, (
            f"{name} is in neither both indexes nor both skip reports "
            f"(vector={path in in_vector}, keyword={path in in_keyword}, "
            f"skip={vector_skipped.get(path)!r}/{keyword_skipped.get(path)!r})"
        )
        assert not (both and reported), f"{name} is both indexed and reported skipped"
        if (vector_skipped.get(path) == SKIP_UNSUPPORTED
                and _chat_reads(tmp_path, name, path)):
            unsupported_but_readable.append(name)

    assert not unsupported_but_readable, (
        "the index calls these an unsupported extension and chat ingest reads "
        f"every one of them: {sorted(unsupported_but_readable)}"
    )


def test_the_two_indexes_still_agree_with_each_other(vault):
    """`B75`'s property, re-asserted over the wider register (`Law 1`)."""
    result, _stored = _vector_index(str(vault))
    keyword_skips = []
    load_personal_index(str(vault), skipped=keyword_skips)
    assert {(e["path"], e["reason"]) for e in result["skipped"]} == \
           {(e["path"], e["reason"]) for e in keyword_skips}


@pytest.mark.parametrize("ext", [".bash", ".c", ".go", ".h", ".htm", ".java",
                                 ".jsx", ".log", ".nix", ".php", ".rb", ".rs",
                                 ".sh", ".sql", ".ts", ".tsx", ".xml"])
def test_the_text_formats_chat_reads_now_reach_the_index(vault, ext):
    """Seventeen of the twenty. Reported "unsupported extension" before."""
    _result, stored = _vector_index(str(vault))
    assert str(vault / f"doc{ext}") in _sources(stored)


# ── the extractors B102 wrote, reaching the index ───────────────────────────

def test_an_odt_is_searchable_by_a_phrase_from_its_body(tmp_path):
    """`B162`'s `Verify`, first clause, end to end through the keyword index."""
    root = tmp_path / "vault"
    root.mkdir()
    (root / "minutes.odt").write_bytes(_minimal_odt("the harbour extension was approved"))
    index = load_personal_index(str(root))
    hits = retrieve_personal_keyword(index, "harbour extension approved")
    assert hits, "an .odt in the index matched nothing from its own body"
    assert "harbour" in hits[0]


def test_a_doc_is_routed_to_the_office_extractor(tmp_path, monkeypatch):
    """The `.doc` reader `B102` bundled is reachable from the index.

    The extractor is recorded rather than re-tested — `B102`'s own tests drive
    the real Word 97 container — because what this row changed is the routing:
    before it, ``extract_office_text`` was never called for a `.doc` at all and
    the file was reported as an unsupported extension.
    """
    root = tmp_path / "vault"
    root.mkdir()
    (root / "letter.doc").write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64)
    seen = []
    monkeypatch.setattr(personal_docs, "extract_office_text",
                        lambda p: seen.append(p) or "recovered prose")
    _result, stored = _vector_index(str(root))
    assert seen == [str(root / "letter.doc")]
    assert _sources(stored) == {str(root / "letter.doc")}


# ── the reader (B101's defect, still live in the index) ─────────────────────

def test_a_cp1251_file_indexes_its_words_rather_than_the_empty_string(tmp_path):
    """`B162`'s `Verify`, second clause. Measured before: ``'  '``, no tokens."""
    root = tmp_path / "vault"
    root.mkdir()
    (root / "server.conf").write_bytes("сервер порт настройка".encode("cp1251"))
    index = load_personal_index(str(root))
    assert [f["name"] for f in index] == ["server.conf"]
    assert "сервер" in "".join(index[0]["chunks"])
    assert retrieve_personal_keyword(index, "настройка")


def test_a_cp1250_file_keeps_the_characters_it_will_be_searched_for(tmp_path):
    """The invisible half: this file WAS indexed, with every accent deleted."""
    root = tmp_path / "vault"
    root.mkdir()
    (root / "polish.txt").write_bytes("Zażółć gęślą jaźń".encode("cp1250"))
    index = load_personal_index(str(root))
    body = "".join(index[0]["chunks"])
    assert "Zażółć" in body, f"accents dropped: {body!r}"
    assert retrieve_personal_keyword(index, "Zażółć")


def test_a_utf16_file_indexes_words_not_nul_padding(tmp_path):
    root = tmp_path / "vault"
    root.mkdir()
    (root / "wide.txt").write_bytes("attention widened".encode("utf-16"))
    index = load_personal_index(str(root))
    body = "".join(index[0]["chunks"])
    assert "\x00" not in body
    assert "attention" in body


def test_the_index_and_chat_read_one_file_the_same_way(tmp_path):
    """`Law 13` on the reader: one encoding decision, two consumers."""
    from src.document_processor import decode_text_file
    path = tmp_path / "notes.txt"
    path.write_bytes("Zażółć gęślą jaźń".encode("cp1250"))
    assert personal_docs.read_text_file(str(path)) == decode_text_file(str(path))


# ── the bytes decide for a suffix no register names ─────────────────────────

@pytest.mark.parametrize("ext", BYTES_ONLY)
def test_a_suffix_no_register_names_is_indexed_when_its_bytes_decode(vault, ext):
    """`B76`'s rule, now the index's. `.conf` is `B162`'s own `Verify` word."""
    _result, stored = _vector_index(str(vault))
    assert str(vault / f"plain{ext}") in _sources(stored)


@pytest.mark.parametrize("ext", BYTES_ONLY)
def test_the_registers_did_not_grow_to_swallow_them(ext):
    """The trap `B76` named, checked from the index side.

    Appending the suffix is what must NOT have happened: these files are indexed
    because their bytes decode, and the register still says no, so the 27th
    format is covered without anybody editing a list.
    """
    assert ext not in personal_docs.INDEXABLE_EXTENSIONS
    assert personal_docs.extractor_for("probe" + ext) is None


@pytest.mark.parametrize("name", sorted(NOT_TEXT))
def test_bytes_that_are_not_text_are_still_reported_unsupported(vault, name):
    """`Law 1` guard: widening the index must not widen it to containers."""
    result, stored = _vector_index(str(vault))
    path = str(vault / name)
    assert path not in _sources(stored)
    assert {e["path"]: e["reason"] for e in result["skipped"]}[path] == SKIP_UNSUPPORTED


def test_naming_the_whole_register_is_not_a_narrowing(vault):
    """Both indexers pass the register explicitly and mean "everything".

    If that set were treated as a filter, every byte-decoded format would be
    filtered out by the default argument of the only two callers there are.
    """
    _result, stored = _vector_index(
        str(vault), file_extensions=set(rag_vector.DEFAULT_FILE_EXTENSIONS))
    assert str(vault / "plain.conf") in _sources(stored)


def test_a_deliberate_narrowing_still_narrows(vault):
    """`Law 1` — `B75`'s `file_extensions` argument still means what it did."""
    result, stored = _vector_index(str(vault), file_extensions={".md"})
    assert _sources(stored) == {str(vault / "doc.md")}
    # A format nothing reads is still reported: "you narrowed to .md" is not
    # why a `.png` is missing. A `.conf` the caller narrowed away is not.
    reported = {os.path.basename(e["path"]) for e in result["skipped"]}
    assert reported == set(NOT_TEXT)


# ── the fourth site: POST /api/personal/upload ──────────────────────────────

# Loopback: `upload_files_to_rag` calls `require_privilege(request, ...)`
# directly rather than through `Depends`, so a dependency override cannot
# stand in for it and the request has to be one `require_user` admits.
_PEER = ("127.0.0.1", 54321)


@pytest.fixture
def personal_api(tmp_path, monkeypatch):
    """The real upload route, with a real RAG store recording what it indexed."""
    from fastapi import FastAPI
    from src.auth_helpers import require_user
    from core.middleware import require_admin

    monkeypatch.setattr(personal_routes, "UPLOADS_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr(personal_routes, "PERSONAL_DIR", str(tmp_path / "personal"))
    (tmp_path / "personal").mkdir()

    stored = []
    rag = VectorRAG.__new__(VectorRAG)
    rag.add_document = lambda text, meta: (stored.append((text, meta)) or True)
    monkeypatch.setattr(personal_routes, "get_rag_manager", lambda: rag)

    manager = SimpleNamespace(index=[], skipped=[], indexed_directories=[],
                              add_directory=lambda *a, **k: None)
    app = FastAPI()
    app.include_router(personal_routes.setup_personal_routes(manager, rag, True))
    app.dependency_overrides[require_user] = lambda: "alice"
    app.dependency_overrides[require_admin] = lambda: None
    transport = httpx.ASGITransport(app=app, client=_PEER)
    client = httpx.AsyncClient(transport=transport, base_url="http://docs.test")
    return client, stored


async def _upload(client, name, body: bytes):
    async with client as c:
        return await c.post("/api/personal/upload",
                            files={"files": (name, body, "application/octet-stream")})


async def test_an_uploaded_docx_is_indexed_as_its_prose_not_its_zip(personal_api):
    """The seam's fourth answer to "can we read this".

    This route asked no register at all: `.pdf` through pypdf and **everything
    else** through ``content_bytes.decode("utf-8", errors="replace")``. Measured
    on a 40-paragraph document, that produced 3 chunks which are 30 % U+FFFD and
    contain no word of the document, while the extractor finds its prose.
    """
    client, stored = personal_api
    body = _minimal_docx("Quarterly revenue rose in the Osaka region")
    res = await _upload(client, "brief.docx", body)
    assert res.status_code == 200, res.text
    text = " ".join(chunk for chunk, _meta in stored)
    assert "Osaka" in text, f"indexed the container, not the document: {text[:120]!r}"
    assert "�" not in text


async def test_an_uploaded_legacy_encoded_file_keeps_its_characters(personal_api):
    """`errors="replace"` was this route's version of the same defect.

    The body is a realistic config file rather than two words: measured, an
    11-byte cp1251 sample is guessed **Big5** by `charset_normalizer` and the
    shared sniff accepts it, which is a limit of the detector on tiny inputs and
    is filed as `B201` rather than papered over here.
    """
    client, stored = personal_api
    body = ("# сервер и порт\n"
            "сервер = настройка памяти\n"
            "порт = резервное копирование\n").encode("cp1251")
    res = await _upload(client, "server.conf", body)
    assert res.status_code == 200, res.text
    assert "сервер" in " ".join(chunk for chunk, _meta in stored)


async def test_an_uploaded_file_no_register_names_is_still_indexed(personal_api):
    """`Law 1`: this route accepted any suffix, and it still does — now because
    the bytes decode rather than because nothing was asked."""
    client, stored = personal_api
    res = await _upload(client, "pyproject.toml", b"[tool]\nzebra = 1\n")
    assert res.status_code == 200, res.text
    assert "zebra" in " ".join(chunk for chunk, _meta in stored)
