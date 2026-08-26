#!/usr/bin/env python3
"""Verify ROADMAP.md's status table against its actual ticks.

The table is the thing every agent reads first, and a table that disagrees with the
list is worse than no table — it sends agents to redo finished work or skip open work.
This recounts from the ticks and fails loudly on any drift.

    python3 .pantheon/check-tracker.py

Exits 0 when the table is right, 1 when it is not. It does not repair the table on its
own — drift means someone ticked without counting, and that is worth looking at rather
than silently overwriting.
"""
import re
import sys
import pathlib

MARKS = {" ": "ready", "·": "claimed", "~": "blocked", "x": "done"}
TASK = re.compile(r"^- \[([ x~·])\] \*\*(P\d+-\d+\w*)\*\*")
PHASE = re.compile(r"^# (P\d+) · (.+)$")
ROW = re.compile(r"^\| (P\d+) \| (.+?) \| (\d+) \| (\d+) \| (\d+) \| \*?\*?(\d+)\*?\*? \|$")


def count(lines):
    """Count ticks per phase, ignoring fenced code blocks so examples never count."""
    phase, fenced, per, order = None, False, {}, []
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
            print(f"  FAIL  {t.group(2)} sits above the first phase header")
            continue
        owner = t.group(2).split("-")[0]
        if owner != phase:
            print(f"  FAIL  {t.group(2)} is filed under {phase}")
        per[phase][MARKS[t.group(1)]] += 1
    return per, order


def main() -> int:
    root = pathlib.Path(__file__).resolve().parent
    path = root / "ROADMAP.md"
    lines = path.read_text(encoding="utf-8").splitlines()
    per, order = count(lines)

    bad = []
    for line in lines:
        m = ROW.match(line)
        if not m:
            continue
        ph, _, tasks, ready, blocked, done = m.group(1), m.group(2), *map(int, m.groups()[2:])
        if ph not in per:
            bad.append(f"{ph}: table has a row for a phase with no section")
            continue
        v = per[ph]
        real = (v["ready"] + v["claimed"] + v["blocked"] + v["done"], v["ready"] + v["claimed"], v["blocked"], v["done"])
        if (tasks, ready, blocked, done) != real:
            bad.append(
                f"{ph}: table says {tasks}/{ready}/{blocked}/{done}, ticks say "
                f"{real[0]}/{real[1]}/{real[2]}/{real[3]}  (total/ready/blocked/done)"
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
    sys.exit(main())
