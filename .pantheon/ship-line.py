#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B451` — which open rows are gates, and the arithmetic that says why it matters.

The tracker has one mark for *not done* and no mark for *not a gate*, so every
row a sweep files reads as blocking. That set does not converge: a codebase this
size always has more to find, and the number a person looks at — open rows — goes
up while the fraction done goes up too. Both are true at once and neither is a
measurement bug.

This script is the evidence behind `.pantheon/SHIP-LINE.md`. It does three things
and it is careful about which of them is judgement:

    .pantheon/ship-line.py            the register, adjudicated
    .pantheon/ship-line.py --trend    tracked / done / open, per Progress entry
    .pantheon/ship-line.py --check    the ratchet: no open row is unclassified

**The rule in `triage()` is recall-oriented triage, not a classifier.** It reads a
row's body for the signals that a gate leaves — an auth boundary, a licence
section number, a claim named false — and returns *candidate* or *clear*. A
candidate is a row somebody has to read. It is deliberately over-inclusive: a
false positive costs one reading and a false negative ships a gate as a nice-to-have.
The answers live in `SHIP-LINE.md`'s register, which is what `--check` reads.

**Why the register is a list and the rule is not.** Every hand-maintained list in
this repo has rotted — the status table (`B44`), the backlog's exclusion from it
(`B79`), a Progress entry claiming rows it left unticked (`B241`). This one is
guarded the same way those were fixed: `--check` fails when a row the rule calls a
candidate appears in neither list, and when a row named blocking is no longer open.
A row filed tomorrow is therefore *unclassified*, by name, until somebody says
which it is — which is the mechanism, and it is the only part of this that has to
survive the person who wrote it.

**This is a proposal and is deliberately not a gate.** `release-gate.py` runs
`.pantheon/check-*.py`; this file is not named that. Adopting the line is one
rename — `git mv .pantheon/ship-line.py .pantheon/check-ship-line.py` — after
which the gate picks it up with no other change, and a line in `ci.yml` puts it in
CI. Until the owner rules, a red answer here should not stop anybody's merge.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRACKER = ROOT / ".pantheon" / "ROADMAP.md"
PROPOSAL = ROOT / ".pantheon" / "SHIP-LINE.md"

# The tracker's own row grammar, spelled the way `check-tracker.py` spells it so
# the two agree about what a row is. `Law 13`: two parsers disagreeing about the
# row set is how a count becomes unfalsifiable.
TASK = re.compile(r"^- \[([ x~·])\] \*\*((?:P\d+-\d+[a-z]?)|(?:[BH]\d+))\*\*")
H1 = re.compile(r"^# (.+)$")
PROGRESS = re.compile(r"\*\*(\d+) tracked, (\d+) done\.")

# Register lines in SHIP-LINE.md. One id, one verdict, one line of reasoning:
#     | `B370` | blocking | security | two pages answer 200 with no cookie |
#     | `B421` | tracked  | written-down | the 27 advisories are recorded and unreachable |
REGISTER = re.compile(
    r"^\|\s*`((?:P\d+-\d+[a-z]?)|(?:[BH]\d+))`\s*\|\s*(blocking|tracked)\s*\|\s*([\w-]+)\s*\|"
)


class Row:
    __slots__ = ("id", "mark", "section", "line", "body")

    def __init__(self, id_, mark, section, line, body):
        self.id, self.mark, self.section, self.line, self.body = id_, mark, section, line, body

    @property
    def open(self) -> bool:
        return self.mark != "x"

    def __repr__(self) -> str:  # pragma: no cover - debugging only
        return f"<Row {self.id} [{self.mark}]>"


def parse_rows(text: str) -> list[Row]:
    """Every row in the tracker, with its continuation lines.

    A row is one `- [m] **ID**` line plus any indented lines under it, which is
    where the corrections live — and the corrections are usually the part that
    decides whether a row is a gate. Reading the first line only would classify
    `B421` as a shipped CRITICAL advisory; its continuation says `B336` measured
    all twenty-seven as unreachable.
    """
    lines = text.splitlines()
    out: list[Row] = []
    section = None
    i = 0
    while i < len(lines):
        ln = lines[i]
        h = H1.match(ln)
        if h:
            section = h.group(1)
        t = TASK.match(ln)
        if not t:
            i += 1
            continue
        body = [ln]
        j = i + 1
        while j < len(lines):
            nxt = lines[j]
            if TASK.match(nxt) or H1.match(nxt) or nxt.startswith("## "):
                break
            if not nxt.strip():
                k = j
                while k < len(lines) and not lines[k].strip():
                    k += 1
                if (k < len(lines) and lines[k].startswith((" ", "\t"))
                        and not TASK.match(lines[k])):
                    body.extend(lines[j:k + 1])
                    j = k + 1
                    continue
                break
            if nxt.startswith((" ", "\t")):
                body.append(nxt)
                j += 1
                continue
            break
        out.append(Row(t.group(2), t.group(1), section, i + 1, "\n".join(body)))
        i = j
    return out


# ---------------------------------------------------------------------------
# Triage
# ---------------------------------------------------------------------------

# Signals a gate leaves in the prose. Grouped by which of the ship line's four
# tests they point at, because the group is what tells a reader why they are
# being asked to look, and a reason is what stops a triage list being ignored.
SIGNALS: dict[str, tuple[str, ...]] = {
    "security": (
        r"unauthenticated", r"with no cookie", r"no auth call", r"fail[- ]open",
        r"without a session", r"auth boundary", r"require_admin", r"admin-gate",
        r"any logged-in non-admin", r"\bRCE\b", r"privilege", r"plain text",
        r"plaintext", r"not encrypted", r"secret grep", r"leak(?:s|ed|ing)? a token",
        # `P2-21` said *"both GETs are open"* and nothing above reads that. A
        # rule that misses the row naming two ungated endpoints is not a triage.
        r"\bungated\b", r"\bnot gated\b", r"only \w+ (?:are|is) gated",
        r"(?:GET|POST|PUT|DELETE|endpoint|route)s?\b[^.]{0,40}\b(?:are|is) open\b",
    ),
    # A shipped dependency is read every time, whatever the row says about it.
    # `B336` is the reason this group exists and the reason it is not a verdict:
    # twenty-seven open advisories are in bytes this project serves, all measured
    # unreachable and written down per id, which is a tracked row and not a gate.
    "supply": (
        r"advisor(?:y|ies)", r"\bCRITICAL\b", r"\bunpinned\b", r"hash-pinned",
    ),
    "licence": (
        r"AGPL", r"Apache-2\.0", r"§\s*13", r"§\s*4\(b\)", r"§\s*5\(a\)",
        r"licence obligation", r"attribution", r"change notice", r"(?-i:\bNOTICE\b)",
        r"copyright holder",
    ),
    "claim": (
        r"is false", r"was false", r"false (?:claim|statement|compliance)",
        r"claims? (?:a|an|the)\b[^.]{0,60}\bthat (?:is|are) not",
        r"misrepresent", r"never prints", r"does not reproduce",
        r"unreachable code", r"stated? both", r"nobody has confirmed",
        r"dead end", r"tick withdrawn",
    ),
    "first-ten": (
        r"first[- ]time user", r"silently (?:invisible|discarded|stor)",
        r"no refusal, no reason", r"stores its zip bytes", r"looks like a corrupt file",
        r"without a login", r"first ten minutes",
    ),
}

_COMPILED = {k: tuple(re.compile(p, re.I) for p in v) for k, v in SIGNALS.items()}


def triage(row: Row) -> tuple[bool, list[str]]:
    """Is this row worth a person reading it against the ship line?

    Returns `(candidate, reasons)`. Recall-oriented on purpose: a candidate costs
    one reading, and a row wrongly called clear ships a gate as a nice-to-have.
    It is **not** an answer — `SHIP-LINE.md`'s register is the answer, and every
    candidate has to appear there or `--check` fails.
    """
    hits: list[str] = []
    for group, pats in _COMPILED.items():
        if any(p.search(row.body) for p in pats):
            hits.append(group)
    return bool(hits), hits


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------

def parse_register(text: str) -> dict[str, tuple[str, str]]:
    """`{id: (verdict, class)}` from SHIP-LINE.md's register tables."""
    out: dict[str, tuple[str, str]] = {}
    for line in text.splitlines():
        m = REGISTER.match(line.strip())
        if m:
            out[m.group(1)] = (m.group(2), m.group(3))
    return out


# ---------------------------------------------------------------------------
# Trend
# ---------------------------------------------------------------------------

def trend(text: str) -> list[tuple[int, int]]:
    """`(tracked, done)` per § Progress entry, newest first.

    The headline is the status table's Total row restated in prose, and
    `check-tracker.py` validates the newest one against the table, so the series
    is the tracker's own arithmetic rather than a second count of it (`Law 14`).
    Repeats are kept: several entries can belong to one merge, and dropping them
    silently would be a third answer to "how many waves is this".
    """
    prog = text.split("## Progress", 1)[1].split("\n## ", 1)[0]
    return [(int(a), int(b)) for a, b in PROGRESS.findall(prog)]


def distinct_waves(series: list[tuple[int, int]], n: int) -> list[tuple[int, int]]:
    """The last `n` entries whose totals moved, oldest first.

    An entry that restates the totals unchanged is a turn, not a wave. Counting
    those as waves halves the apparent rate, which is how "fourteen closed a wave"
    and "twenty-two closed a wave" can both be derived from this file.
    """
    seen: list[tuple[int, int]] = []
    for item in series:  # newest first
        if not seen or item != seen[-1]:
            seen.append(item)
        if len(seen) >= n:
            break
    return list(reversed(seen))


def report_trend(rows: list[Row], text: str, n: int = 10) -> int:
    series = trend(text)
    waves = distinct_waves(series, n)
    print(f"§ Progress carries {len(series)} headline(s); "
          f"{len(waves)} of them moved the totals.\n")
    print("  tracked   done   open   done%   Δtracked  Δdone  Δopen")
    prev = None
    for tr, dn in waves:
        op = tr - dn
        delta = ""
        if prev:
            delta = (f"   {tr - prev[0]:+8d} {dn - prev[1]:+6d} "
                     f"{op - (prev[0] - prev[1]):+6d}")
        print(f"  {tr:>7}  {dn:>5}  {op:>5}  {100 * dn / tr:5.1f}%{delta}")
        prev = (tr, dn)

    first, last = waves[0], waves[-1]
    filed = last[0] - first[0]
    closed = last[1] - first[1]
    opened = (last[0] - last[1]) - (first[0] - first[1])
    steps = len(waves) - 1
    print()
    print(f"  over {steps} interval(s): filed {filed:+d}, closed {closed:+d}, "
          f"open {opened:+d}")
    print(f"  per interval: {filed / steps:.1f} filed, {closed / steps:.1f} closed")
    print(f"  file:close ratio {filed / closed:.3f}  "
          f"— the open count falls only below 1.000")
    print(f"  done {100 * first[1] / first[0]:.1f}% → {100 * last[1] / last[0]:.1f}%"
          f"  ·  open {first[0] - first[1]} → {last[0] - last[1]}")

    live = [r for r in rows if r.open]
    print()
    print(f"  tracker right now: {len(rows)} rows parsed, {len(live)} open")
    return 0


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _one_line(row: Row, width: int = 92) -> str:
    body = re.sub(r"\s+", " ", row.body).strip()
    body = re.sub(r"^- \[.\] \*\*[\w-]+\*\*\s*", "", body)
    body = body.replace("**", "").replace("`", "")
    return body[:width]


def report(rows: list[Row], register: dict[str, tuple[str, str]]) -> int:
    live = [r for r in rows if r.open]
    blocking = [r for r in live if register.get(r.id, ("", ""))[0] == "blocking"]
    reviewed = [r for r in live if register.get(r.id, ("", ""))[0] == "tracked"]
    unlisted = [r for r in live if r.id not in register]
    candidates = [r for r in unlisted if triage(r)[0]]

    print(f"open rows: {len(live)}")
    print(f"  blocking (adjudicated):     {len(blocking):>4}")
    print(f"  reviewed, not blocking:     {len(reviewed):>4}")
    print(f"  clear by rule, not read:    {len(unlisted) - len(candidates):>4}")
    print(f"  UNCLASSIFIED (rule says read me): {len(candidates):>4}")
    print()
    print("blocking:")
    for r in sorted(blocking, key=lambda r: (r.id[0], r.id)):
        cls = register[r.id][1]
        print(f"  {r.id:<8} {cls:<12} {_one_line(r)}")
    if candidates:
        print()
        print("unclassified — the rule flagged these and the register has no answer:")
        for r in candidates:
            print(f"  {r.id:<8} {'+'.join(triage(r)[1]):<28} {_one_line(r, 60)}")

    # Filing composition. The convergence argument is not "we will stop finding
    # things"; it is that almost nothing we find is a gate. Recent `B` rows are
    # the sweeps' output, and the id order is the filing order.
    recent = sorted((r for r in rows if r.id.startswith("B")),
                    key=lambda r: int(r.id[1:]))[-40:]
    rb = [r for r in recent if register.get(r.id, ("", ""))[0] == "blocking"]
    print()
    print(f"composition: of the last {len(recent)} `B` rows filed "
          f"({recent[0].id}–{recent[-1].id}), {len(rb)} are blocking"
          + (f" ({', '.join(r.id for r in rb)})" if rb else ""))
    return 0


def check(rows: list[Row], register: dict[str, tuple[str, str]]) -> int:
    """The ratchet. Exit 1 when the line has drifted from the tracker."""
    live = {r.id: r for r in rows if r.open}
    allr = {r.id: r for r in rows}
    problems: list[str] = []

    for rid, (verdict, _cls) in sorted(register.items()):
        if rid not in allr:
            problems.append(f"{rid}: in the register, not in the tracker")
        elif verdict == "blocking" and rid not in live:
            problems.append(
                f"{rid}: named blocking and is now ticked — move it to the "
                f"landed list and restate the count")

    for rid, row in sorted(live.items()):
        if rid in register:
            continue
        cand, why = triage(row)
        if cand:
            problems.append(
                f"{rid}: unclassified — the rule reads {'+'.join(why)} in it. "
                f"Say blocking or tracked in SHIP-LINE.md's register.")

    if problems:
        print(f"SHIP LINE DRIFTED — {len(problems)}:")
        for p in problems:
            print(f"  {p}")
        return 1
    print(f"ship line OK — {len(register)} adjudicated, "
          f"{sum(1 for r in rows if r.open)} open, nothing unclassified.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--trend", action="store_true", help="the tracked/done/open series")
    ap.add_argument("--check", action="store_true", help="fail on an unclassified open row")
    ap.add_argument("tracker", nargs="?", default=str(TRACKER),
                    help="a tracker to read instead of this tree's")
    ap.add_argument("--register", default=str(PROPOSAL),
                    help="the proposal holding the register")
    args = ap.parse_args(argv)

    text = Path(args.tracker).read_text(encoding="utf-8")
    rows = parse_rows(text)
    if args.trend:
        return report_trend(rows, text)

    reg_path = Path(args.register)
    register = parse_register(reg_path.read_text(encoding="utf-8")) if reg_path.exists() else {}
    if args.check:
        return check(rows, register)
    return report(rows, register)


if __name__ == "__main__":
    raise SystemExit(main())
