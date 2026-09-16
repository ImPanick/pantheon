# SPDX-License-Identifier: AGPL-3.0-or-later
"""B75 — two indexes over the same directory, built by the same click, from
different extension lists.

One ``POST /api/personal/add_directory`` calls ``rag.index_personal_documents``
**and** ``personal_docs_manager.add_directory(index=False)``, whose
``refresh_index()`` calls ``load_personal_index``. The vector index read
``rag_vector.DEFAULT_FILE_EXTENSIONS`` (11 entries); the keyword index read
``personal_docs.config.DEFAULT_EXTENSIONS`` (9). They agreed on four —
``.json .md .pdf .txt``. Keyword-only: ``.docx .epub .pptx .xls .xlsx``.
Vector-only: ``.css .csv .html .js .py .yaml .yml``. So **12 of the 16
extensions named between them were indexed by exactly one of the two**: a
``.docx`` in a vault was findable by keyword and invisible to semantic search, a
``.py`` was the reverse, and nothing on screen said which search the user was
getting.

The asymmetry was not arbitrary in one direction — ``index_personal_documents``
opened everything but ``.pdf`` with a plain UTF-8 ``open()``, so it *could not*
read the Office formats. The fix is therefore a register keyed by EXTRACTOR
(``personal_docs.TEXT_EXTENSIONS`` / ``PDF_EXTENSIONS`` / ``OFFICE_EXTENSIONS``,
each of which is a register that already existed), one shared walk
(``walk_index_candidates``), and both indexers deriving their defaults from it.

`B162` finished the derivation: those three names were still *new* registers
here, holding 16 extensions where chat ingest's held 36, so this file's
assertions moved from the count to the identity. What each test pins is
unchanged; the file it is pinned against is now the one chat ingest reads.

These drive the real indexers over a real directory (`Law 20`) — a fixture
holding one file of every indexable extension plus three nothing here reads.
Measured before the fix, over that directory: the vector index held 11 of the 16
and the keyword index held 9, sharing 4, and neither said a word about the rest.

What is pinned, and why each is a defect if it breaks:

  * the two defaults are the same set, and that set is the register's;
  * every file under an indexed directory is in BOTH indexes or reported as
    skipped with a reason — the row's ``Verify`` clause, asserted per file;
  * the two skip reports agree, because they come from one walk;
  * the reason survives to the HTTP response and into its message, since a count
    in a field nothing renders is the same silence the row is about;
  * hidden and junk directories are still pruned (#5559), and a caller that
    deliberately narrows the extension set still gets the narrow walk.
"""

import os
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

# Imported as modules, not as names: on the tree as it stood the register did
# not exist, and a collection-time ImportError would report "the fix is missing"
# where `Law 9` wants "the defect is present". This way the file loads there and
# the assertions below fail on the measurement instead.
from src import personal_docs, rag_vector
from src.personal_docs import load_personal_index
from src.rag_vector import VectorRAG

from src.markitdown_runtime import MARKITDOWN_EXTS

INDEXABLE_EXTENSIONS = getattr(personal_docs, "INDEXABLE_EXTENSIONS", ())
OFFICE_EXTS = getattr(personal_docs, "OFFICE_EXTENSIONS", None) or frozenset(MARKITDOWN_EXTS)
SKIP_UNSUPPORTED = getattr(personal_docs, "SKIP_UNSUPPORTED", "unsupported extension")
SKIP_NO_TEXT = getattr(personal_docs, "SKIP_NO_TEXT", "no extractable text")
SKIP_UNREADABLE = getattr(personal_docs, "SKIP_UNREADABLE", "could not be read")

# The 16 extensions the two lists named between them, and three nothing reads.
UNREADABLE_EXTS = (".exe", ".png", ".parquet")


@pytest.fixture
def vault(tmp_path, monkeypatch):
    """One file of every indexable extension, plus three unsupported ones.

    The PDF and Office extractors are the real registered ones; only the
    byte-level readers behind them are replaced, because pypdf and markitdown
    are not what this row is about and markitdown is an optional dependency
    that may not be installed on the box running the suite.
    """
    # The 16 the two lists named between them, whichever tree this runs on.
    named = set(rag_vector.DEFAULT_FILE_EXTENSIONS) | set(personal_docs.config.DEFAULT_EXTENSIONS)
    for ext in sorted(named):
        (tmp_path / f"doc{ext}").write_text(f"findable content for {ext}", encoding="utf-8")
    for ext in UNREADABLE_EXTS:
        (tmp_path / f"blob{ext}").write_bytes(b"\x00\x01binary")
    monkeypatch.setattr(personal_docs, "extract_pdf_text",
                        lambda p: f"pdf text of {os.path.basename(p)}")
    monkeypatch.setattr(personal_docs, "extract_office_text",
                        lambda p: f"office text of {os.path.basename(p)}")
    return tmp_path


def _vector_index(directory, file_extensions=None):
    """Drive the REAL index_personal_documents; collect what it stored."""
    stored = []
    store = VectorRAG.__new__(VectorRAG)
    store.add_document = lambda text, meta: (stored.append((text, meta)) or True)
    result = store.index_personal_documents(directory, file_extensions=file_extensions)
    return result, stored


def _sources(stored):
    return {meta["source"] for _text, meta in stored}


# ── one list ────────────────────────────────────────────────────────────────

def test_the_two_indexers_read_one_list():
    """Measured before `B75`: 11 vs 9, agreeing on 4."""
    vector = set(rag_vector.DEFAULT_FILE_EXTENSIONS)
    keyword = set(personal_docs.config.DEFAULT_EXTENSIONS)
    assert vector == keyword, (
        f"{len(vector ^ keyword)} of the {len(vector | keyword)} extensions named "
        f"between the two lists are indexed by exactly one of the two indexes: "
        f"{sorted(vector ^ keyword)}"
    )
    assert vector == set(INDEXABLE_EXTENSIONS)
    # And the union is exactly the three extractor registers, nothing hand-added.
    assert set(INDEXABLE_EXTENSIONS) == (
        personal_docs.TEXT_EXTENSIONS | personal_docs.PDF_EXTENSIONS
        | personal_docs.OFFICE_EXTENSIONS
    )
    # `B162`: and those three are chat ingest's, so the cardinality this test
    # pinned at 16 is now 36. The number is asserted as an identity rather than
    # a literal, because a literal is the thing that goes stale.
    from src.document_processor import INGESTIBLE_EXTS
    assert set(INDEXABLE_EXTENSIONS) == set(INGESTIBLE_EXTS)


def test_the_office_register_is_the_one_the_extractors_already_had():
    """`Law 14` — the Office list is not restated here.

    `B75` derived this from ``MARKITDOWN_EXTS``, which was the whole office
    register at the time. `B102` then wrote bundled `.odt` and `.doc` readers
    and made ``OFFICE_EXTS`` the union, so deriving from the narrower name had
    become a way of not seeing two extractors (`B162`).
    """
    from src.markitdown_runtime import MARKITDOWN_EXTS, NATIVE_OFFICE_EXTS, OFFICE_EXTS
    assert personal_docs.OFFICE_EXTENSIONS == frozenset(OFFICE_EXTS)
    assert personal_docs.OFFICE_EXTENSIONS >= frozenset(MARKITDOWN_EXTS)
    assert personal_docs.OFFICE_EXTENSIONS >= frozenset(NATIVE_OFFICE_EXTS)


# ── the row's Verify clause ─────────────────────────────────────────────────

def test_every_file_is_in_both_indexes_or_reported_skipped(vault):
    """Index one directory; account for every file in it."""
    result, stored = _vector_index(str(vault))
    keyword_skips = []
    keyword = load_personal_index(str(vault), skipped=keyword_skips)

    in_vector = _sources(stored)
    in_keyword = {f["path"] for f in keyword if f["chunks"]}
    vector_skipped = {e["path"]: e["reason"] for e in result["skipped"]}
    keyword_skipped = {e["path"]: e["reason"] for e in keyword_skips}

    on_disk = sorted(str(p) for p in vault.iterdir())
    assert len(on_disk) == len(INDEXABLE_EXTENSIONS) + len(UNREADABLE_EXTS)
    for path in on_disk:
        both = path in in_vector and path in in_keyword
        reported = bool(vector_skipped.get(path)) and bool(keyword_skipped.get(path))
        assert both or reported, (
            f"{path} is in neither both indexes nor both skip reports "
            f"(vector={path in in_vector}, keyword={path in in_keyword}, "
            f"skip={vector_skipped.get(path)!r}/{keyword_skipped.get(path)!r})"
        )
        assert not (both and reported), f"{path} is both indexed and reported skipped"


def test_the_two_skip_reports_agree(vault):
    result, _stored = _vector_index(str(vault))
    keyword_skips = []
    load_personal_index(str(vault), skipped=keyword_skips)
    assert {(e["path"], e["reason"]) for e in result["skipped"]} == \
           {(e["path"], e["reason"]) for e in keyword_skips}
    assert result["skipped_count"] == len(result["skipped"]) == len(UNREADABLE_EXTS)


@pytest.mark.parametrize("ext", sorted(OFFICE_EXTS))
def test_office_formats_now_reach_the_vector_index(vault, ext):
    """Keyword-only before the fix — invisible to semantic search."""
    _result, stored = _vector_index(str(vault))
    assert str(vault / f"doc{ext}") in _sources(stored)


@pytest.mark.parametrize("ext", [".css", ".csv", ".html", ".js", ".py", ".yaml", ".yml"])
def test_code_and_data_formats_now_reach_the_keyword_index(vault, ext):
    """Vector-only before the fix — invisible to keyword search."""
    keyword = load_personal_index(str(vault))
    assert str(vault / f"doc{ext}") in {f["path"] for f in keyword if f["chunks"]}


def test_an_unsupported_extension_is_reported_with_a_reason(vault):
    result, _stored = _vector_index(str(vault))
    reasons = {e["path"]: e["reason"] for e in result["skipped"]}
    for ext in UNREADABLE_EXTS:
        assert reasons[str(vault / f"blob{ext}")] == SKIP_UNSUPPORTED


def test_an_office_file_that_reads_as_nothing_is_reported_not_dropped(tmp_path, monkeypatch):
    """markitdown missing, an encrypted PDF, a scan with no text layer: the file
    is real and the format is supported, so "unsupported" would be a lie."""
    (tmp_path / "scan.pdf").write_bytes(b"%PDF-1.4 no text layer")
    (tmp_path / "deck.pptx").write_bytes(b"PK")
    monkeypatch.setattr(personal_docs, "extract_pdf_text", lambda p: "")
    monkeypatch.setattr(personal_docs, "extract_office_text", lambda p: "")

    result, stored = _vector_index(str(tmp_path))
    assert stored == []
    assert {e["reason"] for e in result["skipped"]} == {SKIP_NO_TEXT}

    keyword_skips = []
    keyword = load_personal_index(str(tmp_path), skipped=keyword_skips)
    assert {e["reason"] for e in keyword_skips} == {SKIP_NO_TEXT}
    # `Law 1`: the docs listing still shows the file it found, with no chunks.
    assert sorted(f["name"] for f in keyword) == ["deck.pptx", "scan.pdf"]
    assert all(f["chunks"] == [] for f in keyword)


def test_an_extractor_that_raises_is_reported_unreadable(tmp_path, monkeypatch):
    (tmp_path / "broken.pdf").write_bytes(b"%PDF")

    def _boom(_p):
        raise OSError("permission denied")

    monkeypatch.setattr(personal_docs, "extract_pdf_text", _boom)
    result, stored = _vector_index(str(tmp_path))
    assert stored == []
    assert [e["reason"] for e in result["skipped"]] == [SKIP_UNREADABLE]


# ── things that must not have changed ───────────────────────────────────────

def test_hidden_and_junk_directories_are_still_pruned(tmp_path):
    """#5559 — the shared walk still applies the shared prune."""
    (tmp_path / "keep.md").write_text("visible", encoding="utf-8")
    (tmp_path / ".hidden.md").write_text("hidden file", encoding="utf-8")
    for junk in (".git", "node_modules", "__pycache__", "venv"):
        d = tmp_path / junk
        d.mkdir()
        (d / "junk.md").write_text("junk", encoding="utf-8")

    _result, stored = _vector_index(str(tmp_path))
    keyword = load_personal_index(str(tmp_path))
    assert _sources(stored) == {str(tmp_path / "keep.md")}
    assert [f["name"] for f in keyword] == ["keep.md"]


def test_a_narrowed_extension_set_is_still_honoured(vault):
    """`Law 1` — the `file_extensions` argument still narrows the walk. A
    register format the caller narrowed away is not reported (they asked not to
    see it); a format nothing here reads still is, because "you narrowed to .md"
    is not why a `.png` is missing from the index."""
    result, stored = _vector_index(str(vault), file_extensions={".md"})
    assert _sources(stored) == {str(vault / "doc.md")}
    assert {Path(e["path"]).suffix for e in result["skipped"]} == set(UNREADABLE_EXTS)


def test_the_walk_is_deterministic(vault):
    keyword_a = [f["name"] for f in load_personal_index(str(vault))]
    keyword_b = [f["name"] for f in load_personal_index(str(vault))]
    assert keyword_a == keyword_b == sorted(keyword_a)


# ── the reason has to reach the user ────────────────────────────────────────

_PEER = ("203.0.113.7", 54321)


@pytest.fixture
def personal_api(tmp_path, monkeypatch):
    """The real add_directory route over a real directory.

    The docs manager's own report covers EVERY tracked directory, not just the
    one being added — ``refresh_index`` re-walks all of them — so the fixture
    seeds it with a third entry under a sibling whose name shares a prefix
    (``personal-other`` vs ``personal``). Only the two under the added directory
    may reach the response, and the two the vector side already reported must
    not be reported twice.
    """
    from fastapi import FastAPI
    import routes.personal_routes as pr
    from src.auth_helpers import require_user
    from core.middleware import require_admin

    vault_dir = tmp_path / "personal"
    vault_dir.mkdir()
    (vault_dir / "notes.md").write_text("indexable", encoding="utf-8")
    (vault_dir / "sheet.xlsx").write_bytes(b"PK")
    (vault_dir / "blob.exe").write_bytes(b"\x00")
    sibling = tmp_path / "personal-other"
    sibling.mkdir()
    (sibling / "elsewhere.exe").write_bytes(b"\x00")
    monkeypatch.setattr(personal_docs, "extract_office_text", lambda p: "")
    monkeypatch.setattr(pr, "PERSONAL_DIR", str(tmp_path))

    stored = []
    rag = VectorRAG.__new__(VectorRAG)
    rag.add_document = lambda text, meta: (stored.append((text, meta)) or True)
    monkeypatch.setattr(pr, "get_rag_manager", lambda: rag)

    manager = SimpleNamespace(index=[], skipped=[], indexed_directories=[], raced=True)

    def _add_directory(directory, index=True, owner=None):
        # What PersonalDocsManager.refresh_index leaves behind: this
        # directory's skips plus every other tracked directory's.
        manager.skipped = [
            entry for entry in (
                {"path": str(vault_dir / "blob.exe"), "reason": SKIP_UNSUPPORTED},
                {"path": str(vault_dir / "sheet.xlsx"), "reason": SKIP_NO_TEXT},
                {"path": str(sibling / "elsewhere.exe"), "reason": SKIP_UNSUPPORTED},
            ) if os.path.exists(entry["path"])
        ]
        if manager.raced:
            # A file that appeared between the vector walk and this one. The two
            # walks are not simultaneous, so their reports can genuinely differ
            # — which is why the route reports the union rather than trusting
            # whichever indexer it happens to read.
            manager.skipped.append({"path": str(vault_dir / "raced.psd"),
                                    "reason": SKIP_UNSUPPORTED})

    manager.add_directory = _add_directory
    app = FastAPI()
    app.include_router(pr.setup_personal_routes(manager, rag, True))
    app.dependency_overrides[require_user] = lambda: "alice"
    app.dependency_overrides[require_admin] = lambda: None
    transport = httpx.ASGITransport(app=app, client=_PEER)
    client = httpx.AsyncClient(transport=transport, base_url="http://docs.test")
    return client, vault_dir, manager


async def test_the_route_reports_which_files_it_could_not_index(personal_api):
    client, vault_dir, _manager = personal_api
    async with client as c:
        res = await c.post("/api/personal/add_directory", json={"directory": str(vault_dir)})
    assert res.status_code == 200, res.text
    body = res.json()
    assert {Path(e["path"]).name: e["reason"] for e in body["skipped"]} == {
        "blob.exe": SKIP_UNSUPPORTED,
        "sheet.xlsx": SKIP_NO_TEXT,
        # Only the keyword indexer saw this one; the union is what the user gets.
        "raced.psd": SKIP_UNSUPPORTED,
    }
    assert body["skipped_count"] == 3
    assert body["skipped_reasons"] == {SKIP_UNSUPPORTED: 2, SKIP_NO_TEXT: 1}
    # And it is said out loud, not only carried in a field.
    assert "skipped" in body["message"]
    assert SKIP_UNSUPPORTED in body["message"] and SKIP_NO_TEXT in body["message"]
    # The docs manager reported the same two files the vector side did, and one
    # under a sibling directory that merely shares a name prefix. Deduped, and
    # confined to the directory that was actually added.
    assert [Path(e["path"]).name for e in body["skipped"]].count("blob.exe") == 1
    assert not any("elsewhere.exe" in e["path"] for e in body["skipped"])


async def test_a_directory_with_nothing_to_report_says_nothing(personal_api):
    client, vault_dir, manager = personal_api
    manager.raced = False
    (vault_dir / "blob.exe").unlink()
    (vault_dir / "sheet.xlsx").unlink()
    # ...and the manager finds nothing to report under it either.
    vault_dir.parent.joinpath("personal-other", "elsewhere.exe").unlink()
    async with client as c:
        body = (await c.post("/api/personal/add_directory",
                             json={"directory": str(vault_dir)})).json()
    assert body["skipped_count"] == 0
    assert body["skipped"] == []
    assert "skipped" not in body["message"]
