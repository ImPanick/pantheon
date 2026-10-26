# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B831` — every backlog id the tracker cites resolves to a row somebody can read.

**What happened.** `P12-04`'s prose says *"Filed as `B750` with the one edit it
needs"*, `P12-09` cites `B750` and `B751` again, and neither was ever a row. The
content survived only because the next agent to work `P2-09` was handed it in a
brief. Nothing recomputed the set of referenced-but-absent ids, so a citation
read as authoritative and pointed at nothing — `Law 8`'s failure with no checker
behind it.

**The other way a row goes missing.** `B01` *is* in the tracker: its marker was
glued onto the end of `B54`'s line by a later rewrite, so every rule in
`check-tracker.py` — which reads a row only where its marker starts a line —
counted around it. A row no rule counts is a row nobody can resolve either.

Like `tests/test_a_progress_entry_that_named_a_row_closed.py`, this drives the
real CLI over the real tracker with one fault injected, and asserts on what the
checker says rather than on its source (`Law 20`).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHECKER = ROOT / ".pantheon" / "check-tracker.py"
ROADMAP = ROOT / ".pantheon" / "ROADMAP.md"


def _run(path: Path):
    proc = subprocess.run([sys.executable, str(CHECKER), str(path)],
                          capture_output=True, text=True, timeout=120)
    return proc.returncode, proc.stdout + proc.stderr


def _faults(out: str):
    return [ln.strip() for ln in out.splitlines() if ln.startswith("  ")]


def _with(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "ROADMAP.md"
    path.write_text(text, encoding="utf-8")
    # The `B1406` rule reads DECISIONS.md beside the tracker; give it the real
    # one so a decision citation is not reported as a fault of this test's.
    decisions = ROOT / ".pantheon" / "DECISIONS.md"
    (tmp_path / "DECISIONS.md").write_text(decisions.read_text(encoding="utf-8"),
                                           encoding="utf-8")
    return path


def test_a_cited_id_with_no_row_is_reported_with_its_line(tmp_path):
    """The row's own defect: a citation in backticks naming a row that does
    not exist fails the checker, and the fault names the id and the line."""
    text = ROADMAP.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    at = next(i for i, ln in enumerate(lines) if ln.startswith("- [x] **B580**"))
    lines[at] = lines[at].rstrip("\n") + " Filed as `B99998` with the one edit it needs.\n"
    code, out = _run(_with(tmp_path, "".join(lines)))
    assert code == 1, out
    want = (f"B99998 is cited at line {at + 1} and there is no row with that id "
            f"— file the row, or correct the citation")
    assert want in _faults(out), out


def test_filing_the_row_resolves_the_citation(tmp_path):
    """...and the same citation is silent once the row exists, which is what
    makes the fault actionable rather than a permanent complaint."""
    text = ROADMAP.read_text(encoding="utf-8")
    cited = text.replace("- [x] **B580**",
                         "- [ ] **B99998** **A row.** — agent:`test`\n\n"
                         "- [x] **B580** See `B99998`.", 1)
    code, out = _run(_with(tmp_path, cited))
    assert not any(f.startswith("B99998") for f in _faults(out)), out


def test_a_bare_word_and_a_fenced_example_are_not_citations(tmp_path):
    """Scope (`Law 5`): a citation is an id in backticks. *"batch B1"* in
    prose is a word, and an id inside a fenced example is an example."""
    text = ROADMAP.read_text(encoding="utf-8")
    text = text.replace("- [x] **B580**",
                        "Batch B99997 ran first.\n\n```\nsee `B99996`\n```\n\n"
                        "- [x] **B580**", 1)
    code, out = _run(_with(tmp_path, text))
    faults = _faults(out)
    assert not any("B99997" in f for f in faults), out
    assert not any("B99996" in f for f in faults), out


def test_a_row_marker_glued_mid_line_is_reported(tmp_path):
    """`B01`'s shape: a row whose marker follows other text on a line is in
    the file and in nobody's count. The checker names the row and the line."""
    text = ROADMAP.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    at = next(i for i, ln in enumerate(lines) if ln.startswith("- [x] **B580**"))
    lines[at] = lines[at].rstrip("\n") + "- [ ] **B99995** **A glued row.**\n"
    code, out = _run(_with(tmp_path, "".join(lines)))
    assert code == 1, out
    assert (f"line {at + 1}: the row marker for B99995 sits mid-line, after other "
            f"text, so no rule here counts it — start it on its own line") in _faults(out), out
    # Split onto its own line, the same row is counted and the fault is gone.
    lines[at] = lines[at].replace("- [ ] **B99995**", "\n- [ ] **B99995**")
    code, out = _run(_with(tmp_path, "".join(lines)))
    assert not any("B99995" in f for f in _faults(out)), out
