#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Verify ROADMAP.md's status table against its actual ticks.

The table is the thing every agent reads first, and a table that disagrees with the
list is worse than no table — it sends agents to redo finished work or skip open work.
This recounts from the ticks and fails loudly on any drift.

    python3 .pantheon/check-tracker.py

It checks three things: every phase row against its ticks, the Total against the rows
above it, and — the one that was missing — that no line naming a phase is skipped. On
2026-08-31 the row regex allowed bold only in the Done column, so all seven phases with a
bolded Blocked count silently failed to match and were never checked; six of the seven
were wrong, and this printed `tracker OK` over them. A checker that skips quietly is worse
than no checker, for the same reason the file it guards is.

Exits 0 when the table is right, 1 when it is not. It does not repair the table on its
own — drift means someone ticked without counting, and that is worth looking at rather
than silently overwriting.
"""
import re
import signal
import sys
import pathlib

MARKS = {" ": "ready", "·": "claimed", "~": "blocked", "x": "done"}
TASK = re.compile(r"^- \[([ x~·])\] \*\*(P\d+-\d+\w*)\*\*")
PHASE = re.compile(r"^# (P\d+) · (.+)$")
# A count may be bolded in any column — the table bolds whatever is worth the eye.
# Every column therefore has to accept it. Getting this wrong is not a cosmetic
# miss: a row the regex cannot parse is silently skipped, so the row that most
# wants checking (the one bold enough to be interesting) is the one that never is.
NUM = r"\*{0,2}(\d+)\*{0,2}"
ROW = re.compile(rf"^\| (P\d+) \| (.+?) \| {NUM} \| {NUM} \| {NUM} \| {NUM} \|$")
# ...and a line that names a phase but will not parse is reported, never skipped.
ROWISH = re.compile(r"^\| (P\d+) \|")
# The Setup row has no phase section to recount against, so it is not validated
# against ticks -- but it does have to be part of the Total, or the Total is a
# different number from the table it sits under.
SETUP = re.compile(rf"^\| Setup \| (.+?) \| {NUM} \| {NUM} \| {NUM} \| {NUM} \|$")
TOTAL = re.compile(rf"^\| \*\*Total\*\* \| \| {NUM} \| {NUM} \| {NUM} \| {NUM} \|$")
# The headline on each § Progress entry: `**338 tracked, 123 done. …**`. It is the
# Total row restated in prose, and nothing checked it until 2026-09-07, by which
# point it read 135 against a table saying 116 — the one line in this file whose
# whole job is to summarise the rest, wrong by fifteen and carried forward
# unread from entry to entry, because every author copied the line above (`B44`).
# Only the newest entry is checked: the ones beneath it are a record of what was
# claimed at the time, and rewriting those is a different kind of dishonesty.
PROGRESS = re.compile(r"\*\*(\d+) tracked, (\d+) done\.")


def count(lines):
    """Count ticks per phase, ignoring fenced code blocks so examples never count.

    Returns (per, order, problems). `problems` is the third thing this file learned on
    2026-08-31: a misfiled task used to be *printed* and then exit 0 anyway, so CI went
    green over it. Reporting a fault you do not fail on is the same silence as not
    looking. Now it is returned, and the caller fails on it.
    """
    phase, fenced, per, order, problems = None, False, {}, [], []
    for line in lines:
        if line.startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        m = PHASE.match(line)
        if m:
            phase = m.group(1)
            per[phase] = {"name": m.group(2), **{v: 0 for v in MARKS.values()}}
            order.append(phase)
            continue
        t = TASK.match(line)
        if not t:
            continue
        if phase is None:
            problems.append(f"{t.group(2)} sits above the first phase header")
            continue
        owner = t.group(2).split("-")[0]
        if owner != phase:
            problems.append(f"{t.group(2)} is filed under {phase} — one of the two ids is wrong")
        per[phase][MARKS[t.group(1)]] += 1
    return per, order, problems


def main() -> int:
    root = pathlib.Path(__file__).resolve().parent
    path = root / "ROADMAP.md"
    lines = path.read_text(encoding="utf-8").splitlines()
    per, order, problems = count(lines)

    bad = list(problems)
    rows = []
    for line in lines:
        st = SETUP.match(line)
        if st:
            rows.append(tuple(map(int, st.groups()[1:])))
            continue
        m = ROW.match(line)
        if not m:
            rough = ROWISH.match(line)
            if rough:
                bad.append(f"{rough.group(1)}: table row is malformed and was never checked -- {line.strip()}")
            continue
        ph, _, tasks, ready, blocked, done = m.group(1), m.group(2), *map(int, m.groups()[2:])
        if ph not in per:
            bad.append(f"{ph}: table has a row for a phase with no section")
            continue
        v = per[ph]
        real = (v["ready"] + v["claimed"] + v["blocked"] + v["done"], v["ready"] + v["claimed"], v["blocked"], v["done"])
        rows.append((tasks, ready, blocked, done))
        if (tasks, ready, blocked, done) != real:
            bad.append(
                f"{ph}: table says {tasks}/{ready}/{blocked}/{done}, ticks say "
                f"{real[0]}/{real[1]}/{real[2]}/{real[3]}  (total/ready/blocked/done)"
            )

    # The Total row is a sum nobody was checking. It had silently accumulated 27
    # appended copies of itself before anyone noticed, because no rule said it had
    # to add up. Now one does.
    seen = [ln for ln in lines if TOTAL.match(ln)]
    if len(seen) != 1:
        bad.append(f"Total: expected exactly one Total row, found {len(seen)}")
    elif rows:
        t = tuple(map(int, TOTAL.match(seen[0]).groups()))
        summed = tuple(sum(c[i] for c in rows) for i in range(4))
        if t != summed:
            bad.append(
                f"Total: row says {'/'.join(map(str, t))}, the rows above it sum to "
                f"{'/'.join(map(str, summed))}  (total/ready/blocked/done)"
            )

    # The newest § Progress headline, against the Total row it restates.
    if len(seen) == 1:
        t = tuple(map(int, TOTAL.match(seen[0]).groups()))
        newest = None
        in_progress = False
        for line in lines:
            if line.startswith("## Progress"):
                in_progress = True
                continue
            if in_progress:
                m = PROGRESS.search(line)
                if m:
                    newest = (line.strip(), int(m.group(1)), int(m.group(2)))
                    break
        if newest is None:
            bad.append("Progress: no entry carries a `N tracked, M done` headline")
        elif (newest[1], newest[2]) != (t[0], t[3]):
            bad.append(
                f"Progress: the newest entry says {newest[1]} tracked / {newest[2]} done, "
                f"the status table says {t[0]} / {t[3]}  -- {newest[0]}"
            )

    total = sum(sum(v[k] for k in MARKS.values()) for v in per.values())
    if bad:
        print(f"tracker DRIFTED — {len(bad)} row(s) wrong, {total} tasks counted\n")
        for b in bad:
            print("  " + b)
        print("\nRecount and fix the table by hand.")
        return 1

    print(f"tracker OK — {total} phase tasks, every row matches its ticks")
    for ph in order:
        v = per[ph]
        print(f"  {ph:<4} ready {v['ready']:>3}  claimed {v['claimed']:>2}  blocked {v['blocked']:>2}  done {v['done']:>3}")
    return 0


if __name__ == "__main__":
    # `| head` closes the pipe; not an error worth a traceback.
    try:
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    except (AttributeError, ValueError):
        pass
    sys.exit(main())
