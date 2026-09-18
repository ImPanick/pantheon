# SPDX-License-Identifier: AGPL-3.0-or-later
"""The document index is bounded and it lets go of the machine (`P14-07`).

The row cites PandaOS: an out-of-memory crash that closed the app with no
warning while it built a search index. Measured on this tree before the row,
with `resource.getrusage`:

    a 105 MB notes vault -> 131,200 chunks retained, RSS 48 -> 185 MB, held for
                            the life of the process (built in __init__)
    ONE 419 MB file      -> RSS 185 -> 1,384 MB

3.3x the file: the decoded string, then a chunk list that overlaps and is
therefore larger than the file it came from. Nothing capped the size of a file
the walk would read, nothing capped what the index kept, and nothing yielded.
After this row the same 419 MB file costs 185 -> 185 MB and is reported.

These drive the real walk over real files in a temp directory.
"""
import os

import pytest

from src import index_walk
from src import personal_docs as pd


@pytest.fixture
def docs(tmp_path):
    d = tmp_path / "docs"
    d.mkdir()
    return d


def _write(d, name, kb):
    p = d / name
    p.write_text("lorem ipsum dolor sit amet " * (kb * 39), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# The per-file ceiling
# ---------------------------------------------------------------------------

def test_a_file_over_the_ceiling_is_not_read(docs, monkeypatch):
    """Not read — the decision has to be made BEFORE the extractor runs.

    Skipping after extraction would cap the index and not the memory, which is
    the only thing that was ever wrong here.
    """
    _write(docs, "huge.md", 64)
    # Patched on `personal_docs`, which is where the walk resolves it — the
    # shared walk reads the ceiling ONCE per walk and hands it down, so this is
    # the single seam both indexers come through.
    monkeypatch.setattr(pd, "max_file_bytes", lambda: 16 * 1024)

    read = []
    real = pd.extract_index_text
    monkeypatch.setattr(pd, "extract_index_text",
                        lambda p, n=None: (read.append(p), real(p, n))[1])

    out = list(pd.walk_index_candidates(str(docs)))
    assert read == []                       # never opened
    assert len(out) == 1
    path, _ext, text, reason = out[0]
    assert text == ""
    assert "index_max_file_mb" in reason and "ceiling" in reason


def test_the_ceiling_is_a_setting_and_zero_means_no_ceiling(docs, monkeypatch):
    """`Law 1`. The capability stays; only the default becomes finite."""
    _write(docs, "huge.md", 64)
    monkeypatch.setattr(pd, "max_file_bytes", lambda: 0)
    text = list(pd.walk_index_candidates(str(docs)))[0][2]
    assert len(text) > 60_000


def test_a_file_over_the_ceiling_is_still_listed(docs, monkeypatch):
    """`B75`'s rule. A file the user can see in their file manager must not
    vanish from the listing — *"where is my 400 MB export"* answered with
    silence is the failure that row was filed for."""
    _write(docs, "huge.md", 64)
    _write(docs, "small.md", 1)
    monkeypatch.setattr(pd, "max_file_bytes", lambda: 16 * 1024)

    skipped = []
    index = pd.load_personal_index(str(docs), skipped=skipped)
    names = {f["name"] for f in index}
    assert names == {"huge.md", "small.md"}
    assert [s for s in skipped if s["path"].endswith("huge.md")]
    assert next(f for f in index if f["name"] == "huge.md")["chunks"] == []


def test_a_file_exactly_at_the_ceiling_is_read(docs, monkeypatch):
    """"Larger than the 32 MB ceiling" has to mean larger than it.

    A survived mutation found this: `>` and `>=` were indistinguishable to
    every other test here, and the one that is wrong contradicts the sentence
    the user is shown.
    """
    p = docs / "exact.md"
    p.write_bytes(b"x" * 4096)
    monkeypatch.setattr(pd, "max_file_bytes", lambda: 4096)
    text = list(pd.walk_index_candidates(str(docs)))[0][2]
    assert len(text) == 4096

    monkeypatch.setattr(pd, "max_file_bytes", lambda: 4095)
    assert list(pd.walk_index_candidates(str(docs)))[0][2] == ""


def test_an_unreadable_file_is_not_filed_as_too_large(docs, monkeypatch):
    """Two different failures with two different remedies."""
    monkeypatch.setattr(index_walk, "max_file_bytes", lambda: 1)
    assert index_walk.file_is_too_large(str(docs / "does-not-exist.md")) is False


# ---------------------------------------------------------------------------
# The memory ceiling on what the index keeps
# ---------------------------------------------------------------------------

def test_the_index_stops_holding_text_at_its_budget(docs):
    for i in range(6):
        _write(docs, f"n{i}.md", 4)
    budget = index_walk.IndexBudget(limit_bytes=8 * 1024)

    skipped = []
    index = pd.load_personal_index(str(docs), skipped=skipped, budget=budget)

    assert len(index) == 6                       # all six listed
    held = [f for f in index if f["chunks"]]
    assert 0 < len(held) < 6                     # some held, some not
    assert budget.used <= budget.limit
    assert budget.dropped == 6 - len(held)
    assert any("index_budget_mb" in s["reason"] for s in skipped)


def test_a_budget_of_zero_holds_everything(docs):
    for i in range(3):
        _write(docs, f"n{i}.md", 4)
    budget = index_walk.IndexBudget(limit_bytes=0)
    index = pd.load_personal_index(str(docs), budget=budget)
    assert all(f["chunks"] for f in index)
    assert budget.dropped == 0


def test_a_budget_never_admits_half_a_document():
    """Half a document in a keyword index is a document that matches queries it
    cannot answer."""
    b = index_walk.IndexBudget(limit_bytes=100)
    assert b.take(60) is True
    assert b.take(60) is False
    assert b.used == 60                        # not 100, and not 120


def test_one_budget_covers_the_whole_refresh_not_each_directory(tmp_path, monkeypatch):
    """Thirteen folders each stopping at their own ceiling is thirteen ceilings.

    The same mistake `P15-05` found in the HuggingFace refresh, where per-source
    caps summed to a burst.
    """
    base = tmp_path / "base"
    extra = tmp_path / "extra"
    for d in (base, extra):
        d.mkdir()
        for i in range(4):
            _write(d, f"n{i}.md", 4)

    monkeypatch.setattr(index_walk, "retained_budget_bytes", lambda: 10 * 1024)
    mgr = object.__new__(pd.PersonalDocsManager)
    mgr.personal_dir = str(base)
    mgr.indexed_directories = [str(extra)]
    mgr.excluded_files = set()
    mgr.rag_manager = None
    mgr.refresh_index()

    held = sum(len("".join(f["chunks"])) for f in mgr.index)
    assert held <= 10 * 1024
    assert len(mgr.index) == 8              # every file still listed
    assert mgr.index_budget.dropped        # and the drop was recorded


def test_get_stats_says_what_is_held_and_what_is_not(tmp_path, monkeypatch):
    """`Law 15`. A ceiling nobody can see gets diagnosed as "search is broken"."""
    base = tmp_path / "base"
    base.mkdir()
    for i in range(4):
        _write(base, f"n{i}.md", 4)
    monkeypatch.setattr(index_walk, "retained_budget_bytes", lambda: 6 * 1024)
    mgr = object.__new__(pd.PersonalDocsManager)
    mgr.personal_dir = str(base)
    mgr.indexed_directories = []
    mgr.excluded_files = set()
    mgr.rag_manager = None
    mgr.refresh_index()

    stats = mgr.get_stats()
    assert stats["held_limit_bytes"] == 6 * 1024
    assert 0 < stats["held_bytes"] <= stats["held_limit_bytes"]
    assert stats["files_over_budget"] > 0


# ---------------------------------------------------------------------------
# The duty cycle
# ---------------------------------------------------------------------------

class _Clock:
    def __init__(self):
        self.now = 0.0
        self.slept = []

    def __call__(self):
        return self.now

    def sleep(self, n):
        self.slept.append(n)
        self.now += n


def test_a_short_index_never_rests():
    """Pacing must cost nothing on the walk that does not need it."""
    clock = _Clock()
    pacer = index_walk.IndexPacer(work_seconds=0.2, rest_seconds=0.02,
                                  sleep=clock.sleep, clock=clock)
    for _ in range(50):
        clock.now += 0.001
        pacer.tick()
    assert clock.slept == []
    assert pacer.rests == 0


def test_a_long_index_gives_the_machine_back():
    clock = _Clock()
    pacer = index_walk.IndexPacer(work_seconds=0.2, rest_seconds=0.02,
                                  sleep=clock.sleep, clock=clock)
    for _ in range(100):
        clock.now += 0.05           # 5 seconds of work, one file at a time
        pacer.tick()
    assert 18 <= pacer.rests <= 26      # ~one rest per 0.2s of work
    assert pacer.slept > 0
    # ~10% duty cycle: the work is what the operator asked for, the rest is what
    # keeps the box usable while it happens.
    assert 0.05 < pacer.slept / clock.now < 0.15


def test_pacing_can_be_switched_off_by_configuration_not_by_editing_code():
    clock = _Clock()
    pacer = index_walk.IndexPacer(work_seconds=0, rest_seconds=0,
                                  sleep=clock.sleep, clock=clock)
    clock.now += 100
    assert pacer.tick() == 0.0
    assert clock.slept == []


def test_the_walk_paces_itself_without_being_asked(docs, monkeypatch):
    """The default matters more than the parameter: the two indexers call this
    generator with no pacer at all.

    And it asserts the pacer is DRIVEN, not merely built — a constructed pacer
    whose `tick` is never called is the survived mutation this project keeps
    finding on wiring like this.
    """
    made, ticks = [], []
    real = index_walk.IndexPacer

    class _Spy(real):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            made.append(self)

        def tick(self):
            ticks.append(1)
            return super().tick()

    monkeypatch.setattr(pd, "IndexPacer", _Spy)
    for i in range(3):
        _write(docs, f"a{i}.md", 1)
    list(pd.walk_index_candidates(str(docs)))
    assert made, "the shared walk built no pacer, so nothing paces either index"
    assert len(ticks) == 3, "the pacer was built and then never asked"


# ---------------------------------------------------------------------------
# Both indexers, from one place
# ---------------------------------------------------------------------------

def test_the_vector_indexer_gets_the_same_ceiling(docs, monkeypatch):
    """`Law 13`. The bound is in the shared walk, so the vector index cannot
    have a different one — which is exactly how these two drifted before
    (#5559, `B75`)."""
    from src import rag_vector

    _write(docs, "huge.md", 64)
    _write(docs, "small.md", 1)
    monkeypatch.setattr(pd, "max_file_bytes", lambda: 16 * 1024)

    rag = object.__new__(rag_vector.VectorRAG)
    added = []
    monkeypatch.setattr(rag_vector.VectorRAG, "add_document",
                        lambda self, text, meta: (added.append(meta), True)[1])
    monkeypatch.setattr(rag_vector.VectorRAG, "_split_into_chunks",
                        lambda self, text: [text])

    result = rag.index_personal_documents(str(docs), file_extensions={".md"})
    assert result["success"]
    sources = {os.path.basename(m["source"]) for m in added}
    assert sources == {"small.md"}
    assert any("huge.md" in s["path"] and "index_max_file_mb" in s["reason"]
               for s in result["skipped"])
