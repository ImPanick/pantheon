"""The tracker checker has to fail on the drift it exists to catch.

On 2026-08-31 it did not. Its row regex accepted `**bold**` in the Done column and a
bare `(\\d+)` in Blocked, so every phase row that bolded its blocked count failed to
match and was **silently skipped** — seven of fifteen phases, which happened to be
exactly the seven that had blocked rows. Six of the seven were wrong, and the checker
printed `tracker OK` over them for days.

A checker that skips quietly is worse than no checker, for the same reason a tracker
updated *sometimes* is worse than no tracker: it is trusted. So this file does not test
that the checker passes on a good file — that proves nothing. It bends the tracker in
each of the ways it has actually drifted and asserts the checker notices. If a future
change to the regex reintroduces a silent skip, one of these goes red.
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PANTHEON = Path(__file__).resolve().parent.parent / ".pantheon"
CHECKER = PANTHEON / "check-tracker.py"
ROADMAP = PANTHEON / "ROADMAP.md"


def _run(tmp_path: Path, roadmap_text: str):
    """Run the real checker against a bent copy of the tracker."""
    shutil.copy(CHECKER, tmp_path / "check-tracker.py")
    (tmp_path / "ROADMAP.md").write_text(roadmap_text, encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(tmp_path / "check-tracker.py")],
        capture_output=True, text=True, cwd=tmp_path,
    )
    return proc.returncode, proc.stdout


@pytest.fixture(scope="module")
def roadmap() -> str:
    return ROADMAP.read_text(encoding="utf-8")


def _first_phase_row(text: str) -> str:
    m = re.search(r"^\| P\d+ \| .+ \|$", text, re.M)
    assert m, "no phase row found in ROADMAP.md"
    return m.group(0)


def test_the_real_tracker_is_green(tmp_path, roadmap):
    """Law 4's gate. If this is red the tracker is wrong, not this test."""
    code, out = _run(tmp_path, roadmap)
    assert code == 0, f"the committed tracker does not pass its own checker:\n{out}"
    assert "tracker OK" in out


def test_a_wrong_count_is_caught_even_when_the_column_is_bold(tmp_path, roadmap):
    """The exact defect. Bold must not buy a row an exemption from being checked."""
    row = _first_phase_row(roadmap)
    cells = row.split(" | ")
    cells[4] = "**99**"  # Blocked, bolded and wrong
    code, out = _run(tmp_path, roadmap.replace(row, " | ".join(cells)))
    assert code == 1, f"a bolded wrong count was accepted:\n{out}"
    assert "DRIFTED" in out


@pytest.mark.parametrize("column", [2, 3, 4, 5], ids=["tasks", "ready", "blocked", "done"])
def test_every_numeric_column_is_checked_bold_or_plain(tmp_path, roadmap, column):
    """Not just Blocked — any column that can be bolded can hide a wrong number."""
    row = _first_phase_row(roadmap)
    for value in ("77", "**77**"):
        cells = row.split(" | ")
        cells[column] = value
        bent = roadmap.replace(row, " | ".join(cells))
        if bent == roadmap:          # 77 was already the right answer here
            continue
        code, out = _run(tmp_path, bent)
        assert code == 1, f"column {column} as {value!r} went unchecked:\n{out}"


def test_an_unparseable_phase_row_is_reported_not_skipped(tmp_path, roadmap):
    """The class of bug, not just the instance: silence is the failure mode."""
    row = _first_phase_row(roadmap)
    code, out = _run(tmp_path, roadmap.replace(row, row.rsplit("|", 2)[0] + "|"))
    assert code == 1, f"a malformed phase row was skipped in silence:\n{out}"
    assert "malformed" in out


def test_the_total_row_has_to_add_up(tmp_path, roadmap):
    bent = re.sub(r"\| \*\*Total\*\* \| \| \*\*\d+\*\*", "| **Total** | | **999**", roadmap)
    assert bent != roadmap, "no Total row to bend"
    code, out = _run(tmp_path, bent)
    assert code == 1, f"a Total that does not add up was accepted:\n{out}"
    assert "Total" in out


def test_a_duplicated_total_row_is_caught(tmp_path, roadmap):
    """This one is not hypothetical — the Total row had accumulated 27 copies of
    itself on a single line before anything noticed, because nothing checked it."""
    m = re.search(r"^\| \*\*Total\*\* \| \|.*\|$", roadmap, re.M)
    assert m, "no Total row found"
    code, out = _run(tmp_path, roadmap.replace(m.group(0), m.group(0) + "\n" + m.group(0)))
    assert code == 1, f"a duplicate Total row was accepted:\n{out}"
    assert "Total" in out


def test_a_task_filed_under_the_wrong_phase_is_named(tmp_path, roadmap):
    """P3-16/P5-16 collided once already; the checker is what catches the next one."""
    m = re.search(r"^- \[[ x~·]\] \*\*(P\d+)-(\d+\w*)\*\*", roadmap, re.M)
    assert m
    wrong = m.group(0).replace(f"**{m.group(1)}-", "**P99-")
    code, out = _run(tmp_path, roadmap.replace(m.group(0), wrong, 1))
    assert code == 1, f"a task filed under a phase that does not exist was accepted:\n{out}"
