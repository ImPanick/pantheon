# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B491` — the personal-documents index is built when it is first asked for.

`P14-07` bounded and paced the keyword index; `PersonalDocsManager.__init__`
still called `refresh_index()`, so every tracked directory was walked,
extracted and chunked synchronously at construction — at boot, before anybody
had asked a question (measured then: 105 MB of notes, 131,200 chunks, ~137 MB
of RSS held for the life of a process that may never run a search).

Driven against the real manager over a real directory, with the one extraction
seam (`extract_index_text`, which `walk_index_candidates` calls once per file)
counting calls:

  * construction extracts nothing, and neither does the app's own initialiser
    (`src/app_initializer.py` used to read `.index` into a dict nobody read);
  * the first listing, retrieval or `skipped` read builds it once, and a second
    builds nothing more;
  * two first readers at once build it once;
  * an exclusion before the build is honoured by it, without building.
"""
import ast
import threading
from pathlib import Path

import pytest

import src.personal_docs as pd

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def counted(monkeypatch):
    calls = []
    real = pd.extract_index_text

    def counting(path, name=None):
        calls.append(path)
        return real(path, name)

    monkeypatch.setattr(pd, "extract_index_text", counting)
    return calls


@pytest.fixture
def docs(tmp_path):
    base = tmp_path / "personal"
    base.mkdir()
    (base / "harbour.md").write_text("The harbour master logs every tide.\n" * 20)
    (base / "seabed.txt").write_text("Who owns the seabed is a question of law.\n" * 20)
    extra = tmp_path / "notes"
    extra.mkdir()
    (extra / "kelp.md").write_text("Kelp forests store carbon.\n" * 20)
    return base, extra


def _manager(base, extra=None):
    mgr = pd.PersonalDocsManager(str(base))
    if extra is not None:
        mgr.indexed_directories = [str(extra)]
    return mgr


def test_construction_extracts_nothing(docs, counted):
    base, _ = docs
    mgr = _manager(base)
    assert counted == []
    assert mgr.index_built is False


def test_the_first_listing_builds_it_once_and_the_second_builds_nothing(docs, counted):
    base, extra = docs
    mgr = _manager(base, extra)
    assert counted == []
    names = sorted(f["name"] for f in mgr.get_file_list())
    assert names == ["harbour.md", "notes/kelp.md", "seabed.txt"]
    first = len(counted)
    assert first == 3
    mgr.get_file_list()
    _ = mgr.index, mgr.skipped, mgr.get_stats()
    assert len(counted) == first


def test_the_first_retrieval_builds_it_and_finds_the_document(docs, counted):
    base, _ = docs
    mgr = _manager(base)
    hits = mgr.retrieve("who owns the seabed", k=1)
    assert hits and "seabed" in hits[0].lower()
    assert len(counted) == 2
    mgr.retrieve("kelp", k=1)
    assert len(counted) == 2


def test_reading_what_was_skipped_builds_it_too(docs, counted, tmp_path):
    base, _ = docs
    (base / "blob.bin").write_bytes(b"\x00\x01\x02\xff" * 64)
    mgr = _manager(base)
    assert counted == []
    reasons = {Path(s["path"]).name for s in mgr.skipped}
    assert "blob.bin" in reasons
    assert mgr.index_built is True


def test_two_first_readers_build_it_once(docs, counted, monkeypatch):
    base, extra = docs
    mgr = _manager(base, extra)
    gate = threading.Event()
    real = pd.load_personal_index

    def slow(*a, **kw):
        gate.wait(1.0)   # hold the first build open while the second arrives
        return real(*a, **kw)

    monkeypatch.setattr(pd, "load_personal_index", slow)
    out = []
    readers = [threading.Thread(target=lambda: out.append(len(mgr.index))) for _ in range(2)]
    for t in readers:
        t.start()
    gate.set()
    for t in readers:
        t.join(5)
    assert out == [3, 3]
    assert len(counted) == 3   # one build: each file extracted once


def test_an_exclusion_before_the_build_is_kept_without_building(docs, counted):
    base, _ = docs
    mgr = _manager(base)
    mgr.exclude_file(str(base / "seabed.txt"))
    assert counted == [] and mgr.index_built is False
    names = [f["name"] for f in mgr.get_file_list()]
    # (`excluded_files.json` is the manager's own state file in the same
    # folder, and is listed as a document — pre-existing, filed separately.)
    assert "harbour.md" in names and "seabed.txt" not in names


def test_an_explicit_reload_still_builds_now(docs, counted):
    """`POST /api/personal/reload` calls `refresh_index`; it is a person asking."""
    base, _ = docs
    mgr = _manager(base)
    mgr.refresh_index()
    assert len(counted) == 2 and mgr.index_built is True


def test_the_app_initialiser_does_not_read_the_index():
    """`initialize_app_components` built the manager and then put
    `personal_docs_manager.index` in its answer — a key no module read, and now
    the read that would rebuild everything at boot. Scoped to the function by
    AST (`Law 20`): no attribute read of `.index` on the manager there."""
    src = (ROOT / "src" / "app_initializer.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    reads = [n for n in ast.walk(tree)
             if isinstance(n, ast.Attribute) and n.attr == "index"
             and isinstance(n.value, ast.Name) and n.value.id == "personal_docs_manager"]
    assert reads == []
