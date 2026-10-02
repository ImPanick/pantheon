# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P0-16` — the Apache-2.0 §4(b) change notices, and the nine files without one.

Upstream Odysseus credits Tongyi DeepResearch for four paths, `services/search/`
among them. Eight files under the other three carry a §4(b) change notice.
`services/search/` carries none, and on 2026-10-02 the owner ruled that it
stays that way: **credit only, no notice** (`D-2026-10-02-03`). The ruling's
reason that still holds is a fact about the files' contents — there is no
Tongyi DeepResearch expression in them — so that fact is what is asserted
here, against the files rather than against the sentence in `CREDITS.md` that
states it. If anyone ever ports DeepResearch code into `services/search/`,
the first test fails and the ruling's basis is gone; that is the moment to
re-ask the question, not to delete the test.

The ruling's other reason — the nine files are byte-identical to the fork
point — was true on 2026-08-27 and is not now: Pantheon has since edited them
(`P0-18`, `P15-04`, `P15-06`, `P16-*`, `B90`). `CREDITS.md` says so, and that
is not something a test can pin without a fork-point checkout.

Every check here reads the tracked tree through `git ls-files`, so a file
added to `services/search/` is covered the day it is added.
"""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# The names that would mark Tongyi's expression — the same four the 2026-08-27
# measurement searched for, so a later reading is comparable with it.
TONGYI = re.compile(r"Tongyi|DeepResearch|IterResearch|Alibaba", re.I)
NOTICE = "Apache-2.0 §4(b) change notice"
STAMPED = (
    "services/research/__init__.py",
    "services/research/research_handler.py",
    "services/research/service.py",
    "routes/research/__init__.py",
    "routes/research/research_routes.py",
    "src/research_handler.py",
    "src/deep_research.py",
    "src/goal_based_extractor.py",
)


def _search_files() -> list:
    out = subprocess.run(["git", "ls-files", "services/search/"], cwd=str(ROOT),
                         capture_output=True, text=True, check=True).stdout.split()
    assert out, "services/search/ has no tracked files — this test proves nothing"
    return out


def _head(rel: str, lines: int = 12) -> str:
    return "\n".join((ROOT / rel).read_text(encoding="utf-8").splitlines()[:lines])


def test_the_search_files_contain_nothing_of_tongyi_to_have_changed():
    """The ruling's basis, measured on the files themselves."""
    hits = []
    for rel in _search_files():
        for number, line in enumerate((ROOT / rel).read_text(encoding="utf-8").splitlines(), 1):
            if TONGYI.search(line):
                hits.append(f"{rel}:{number}: {line.strip()[:100]}")
    assert not hits, (
        "Tongyi DeepResearch names now appear in services/search/. The ruling "
        "that these files carry credit without a §4(b) notice (D-2026-10-02-03) "
        "rested on there being none — re-ask it:\n  " + "\n  ".join(hits))


def test_the_search_files_carry_credit_and_no_change_notice():
    """Credit only: no file under `services/search/` claims to be a changed copy
    of Tongyi's work, and `CREDITS.md` still credits the path to Tongyi and
    records the ruling beside it."""
    stamped = [rel for rel in _search_files() if NOTICE in _head(rel)]
    assert not stamped, stamped

    credits = (ROOT / "CREDITS.md").read_text(encoding="utf-8")
    # The list item alone: the paragraphs after it name `services/search/` too,
    # and a credit is the entry, not a sentence near it.
    entry = next((block.split("\n\n", 1)[0] for block in credits.split("\n- ")
                  if block.startswith("**[Tongyi DeepResearch]")), None)
    assert entry, "CREDITS.md no longer credits Tongyi DeepResearch"
    assert "`services/search/`" in entry, entry
    ruling = next((p for p in re.split(r"\n\s*\n", credits)
                   if p.startswith("**`services/search/` keeps its credit")), None)
    assert ruling and "D-2026-10-02-03" in ruling, ruling


def test_the_eight_derived_files_keep_their_notice():
    """The other half of the row, which the ruling leaves exactly as it was."""
    missing = [rel for rel in STAMPED if NOTICE not in _head(rel)]
    assert not missing, missing
    for rel in STAMPED:
        head = _head(rel)
        assert "licenses/DeepResearch-Apache-2.0.txt" in head, rel
        # The file's own licence is stated as ours, not as Apache-2.0 — the
        # defect the first attempt at these notices had.
        assert "AGPL-3.0-or-later" in head, rel
