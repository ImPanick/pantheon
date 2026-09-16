#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Verify ROADMAP.md's status table against its actual ticks.

The table is the thing every agent reads first, and a table that disagrees with the
list is worse than no table — it sends agents to redo finished work or skip open work.
This recounts from the ticks and fails loudly on any drift.

    python3 .pantheon/check-tracker.py

It checks four things: every phase row against its ticks, the Total against the rows
above it, that no line naming a phase is skipped, and — `B241` — that a row a § Progress
entry says it CLOSED is actually ticked. On
2026-08-31 the row regex allowed bold only in the Done column, so all seven phases with a
bolded Blocked count silently failed to match and were never checked; six of the seven
were wrong, and this printed `tracker OK` over them. A checker that skips quietly is worse
than no checker, for the same reason the file it guards is.

Exits 0 when the table is right, 1 when it is not. It does not repair the table on its
own — drift means someone ticked without counting, and that is worth looking at rather
than silently overwriting.

Takes an optional path, so a test can drive it over a historical or synthetic tracker
rather than over the one in the tree:

    python3 .pantheon/check-tracker.py /tmp/some-ROADMAP.md
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
# `B79`. The backlog — `B` and `H` rows — was outside this table entirely, and
# so outside the Total, and so outside the `N tracked, M done` headline that
# restates it. Ninety-eight rows, seventy-seven of them done, invisible to the
# one line whose whole job is to say how much of this tracker is finished.
#
# **This is `B44` one level up, and it is worse.** `B44` was a prose headline
# that had drifted from a table; the table was right. Here the table itself was
# answering a narrower question than its own heading asks, and `check-tracker.py`
# validated it perfectly against the rows it had decided to count — internally
# consistent and externally wrong, which is the kind that survives a checker.
# It surfaced when eleven backlog rows closed in one day and the headline did
# not move, and the owner asked why.
#
# Counted here rather than left in prose for the same reason every other number
# in this file is: a figure nothing recomputes is a figure that rots.
BACKLOG = re.compile(rf"^\| Backlog \| (.+?) \| {NUM} \| {NUM} \| {NUM} \| {NUM} \|$")
BACKLOG_TASK = re.compile(r"^- \[([ x~·])\] \*\*([BH]\d+)\*\*")
TOTAL = re.compile(rf"^\| \*\*Total\*\* \| \| {NUM} \| {NUM} \| {NUM} \| {NUM} \|$")
# The headline on each § Progress entry: `**338 tracked, 123 done. …**`. It is the
# Total row restated in prose, and nothing checked it until 2026-09-07, by which
# point it read 135 against a table saying 116 — the one line in this file whose
# whole job is to summarise the rest, wrong by fifteen and carried forward
# unread from entry to entry, because every author copied the line above (`B44`).
# Only the newest entry is checked: the ones beneath it are a record of what was
# claimed at the time, and rewriting those is a different kind of dishonesty.
PROGRESS = re.compile(r"\*\*(\d+) tracked, (\d+) done\.")

# `B241`. The third disagreement, after `B44` (prose vs table) and `B79` (a table
# counting the wrong set): prose vs the TICKS. `1a70478` implemented `B02` and
# `B03` in full and its own § Progress entry says *"`B02`, `B03`, `B05`, `B07`,
# `B21` and `B79` closed"* — and both checkboxes stayed `- [ ]` for two days,
# with `481 tracked, 268 done` computed from the ticks and the list beside it
# not. The cost lands on the next agent, who reads an open row, re-derives work
# that already shipped, and finds the fix already in the tree.
#
# **The naive version is why this row was filed and not built.** Scan a § Progress
# entry for row ids inside a sentence containing *closed* and you flag `B15`,
# `B16`, `B22` and `B23`, which the same entry calls *ruled by the owner*;
# `B75`–`B78`, which it calls *filed*; `B73` and `B74`, *filed to the backlog*;
# and `B121`, which a later paragraph says is *left open on purpose*. A checker
# that cries wolf on nine rows is a checker nobody can leave green, which is
# worse than none.
#
# So this is deliberately NARROW, and the narrowness is the design rather than a
# shortcut. Two bounds, both of which every entry in this file already obeys:
#
#   1. Only the entry's FIRST BOLD SPAN is read — the `**N tracked, M done. …**`
#      headline, which is the one line every entry writes in the same form and
#      is the same span `PROGRESS` above already parses. Narrative paragraphs
#      further down say *closed* about all sorts of things ("three rows were
#      closed by re-measuring", "`B121` is left open") and none of them is the
#      claim.
#   2. Inside it, only the run of row ids IMMEDIATELY BEFORE the word `closed`
#      counts, and that run may contain nothing but ids, commas, brackets, `and`
#      and en-dashes. A `.` or a `;` ends it. That is what separates
#      *"`B06`, `B17` and `B19` closed; `B15`, `B16`, `B22` and `B23` ruled by
#      the owner"* — three claims, not seven — and it is what makes
#      *"1 regression closed"* claim nothing at all, because the token before
#      `closed` is a word.
#
# Measured over all 171 § Progress entries in this file: 19 carry a claim, 84
# row ids in total, and not one of the nine false positives above is among them.
# Run against `.pantheon/ROADMAP.md` as it stood at `1a70478`, it fails on
# exactly `B02` and `B03`.
CLAIM_ID = r"`(?:[BH]\d+|P\d+-\d+[a-z]?)`"
CLAIM_GLUE = r"(?:[ \t\n]|,|\(|\)|\band\b|–|—)"
CLAIM_TAIL = re.compile(rf"((?:{CLAIM_ID}|{CLAIM_GLUE})+)closed\b")
CLAIM_RANGE = re.compile(rf"({CLAIM_ID})\s*[–—]\s*({CLAIM_ID})")
CLAIM_ONE = re.compile(CLAIM_ID)
CLAIM_TOKEN = re.compile(
    rf"(?P<low>{CLAIM_ID})\s*[–—]\s*(?P<high>{CLAIM_ID})|(?P<one>{CLAIM_ID})")
# Both kinds of row, so a claim about a `B` row and a claim about a `P` row are
# resolved against the same ticks the table is recounted from.
ANY_TASK = re.compile(r"^- \[([ x~·])\] \*\*((?:P\d+-\d+\w*|[BH]\d+))\*\*")


def count(lines):
    """Count ticks per phase, ignoring fenced code blocks so examples never count.

    Returns (per, order, problems). `problems` is the third thing this file learned on
    2026-08-31: a misfiled task used to be *printed* and then exit 0 anyway, so CI went
    green over it. Reporting a fault you do not fail on is the same silence as not
    looking. Now it is returned, and the caller fails on it.
    """
    phase, fenced, per, order, problems = None, False, {}, [], []
    # B48: `P3-17` was the id of two different rows for a day — the newer filed
    # by a run that picked the next number it could see, in a file where the
    # numbers are not contiguous. Everything else here counted marks and got the
    # right totals over the wrong rows.
    seen_ids = {}
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
        seen_ids.setdefault(t.group(2), []).append(phase)
        per[phase][MARKS[t.group(1)]] += 1
    for task_id, phases in seen_ids.items():
        if len(phases) > 1:
            problems.append(
                f"{task_id} is the id of {len(phases)} different rows. An id is how a row is "
                f"cited — in a commit message, in a `Depends:`, in another row's prose — and two "
                f"rows sharing one means a citation cannot be resolved and a tick lands on "
                f"whichever the reader found first."
            )
    return per, order, problems


def progress_headlines(lines):
    """`(title, headline)` for every `### ` entry under `## Progress`.

    The headline is the entry's first bold span. Entries are NOT separated by
    blank lines in this file — the newest one runs to eight paragraphs with no
    blank line between them — so "the first paragraph" cannot be found by
    splitting on blank lines, and the bold span is what actually delimits the
    claim.
    """
    out, i, in_progress = [], 0, False
    while i < len(lines):
        line = lines[i]
        if line.startswith("## Progress"):
            in_progress = True
            i += 1
            continue
        if in_progress and line.startswith("## "):
            break
        if in_progress and line.startswith("### "):
            title = line[4:].strip()
            body, i = [], i + 1
            while i < len(lines) and not lines[i].startswith(("### ", "## ")):
                body.append(lines[i])
                i += 1
            m = re.search(r"\*\*(.+?)\*\*", " ".join(body), re.S)
            out.append((title, m.group(1) if m else ""))
            continue
        i += 1
    return out


def closed_claims(headline):
    """The row ids a § Progress headline says it CLOSED, in order, deduplicated.

    `B151`–`B153` is a range and expands; everything else is a plain id. A
    headline with no `closed` in it, or with no ids in front of the word, claims
    nothing — which is the answer for *"1 regression closed"* and for the 152
    entries of the 171 that make no closure claim at all.
    """
    ids = []
    for m in CLAIM_TAIL.finditer(headline):
        # Left to right, so the ids come back in the order the sentence names
        # them; a range is expanded where it stands rather than appended.
        for tok in CLAIM_TOKEN.finditer(m.group(1)):
            low, high = tok.group("low"), tok.group("high")
            if low is None:
                ids.append(tok.group("one").strip("`"))
                continue
            prefix = re.match(r"`([BH]|P\d+-)", low)
            a = int(re.search(r"(\d+)`$", low).group(1))
            b = int(re.search(r"(\d+)`$", high).group(1))
            if not prefix or re.match(r"`([BH]|P\d+-)", high).group(1) != prefix.group(1) or a >= b:
                # Not a range anybody can expand — a `B12`–`P3-04` is a typo,
                # and inventing 200 ids from it would be worse than reading the
                # two that are actually written.
                ids += [low.strip("`"), high.strip("`")]
                continue
            ids += [f"{prefix.group(1)}{n}" for n in range(a, b + 1)]
    return list(dict.fromkeys(ids))


def main(path=None) -> int:
    root = pathlib.Path(__file__).resolve().parent
    path = pathlib.Path(path) if path else root / "ROADMAP.md"
    lines = path.read_text(encoding="utf-8").splitlines()
    per, order, problems = count(lines)

    bad = list(problems)
    rows = []
    for line in lines:
        st = SETUP.match(line)
        if st:
            rows.append(tuple(map(int, st.groups()[1:])))
            continue
        # `B79`. The Backlog row counts toward the Total for the same reason
        # Setup does: a Total that omits a row printed above it is a different
        # number from the table it sits under. Its own figures are recounted
        # from the `B`/`H` ticks below.
        bl = BACKLOG.match(line)
        if bl:
            rows.append(tuple(map(int, bl.groups()[1:])))
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

    # `B79`. The Backlog row, recounted from the `B`/`H` ticks the same way every
    # phase row is recounted from its own. Adding an unchecked number to this
    # table would have been the defect it is meant to close.
    backlog_marks = {v: 0 for v in MARKS.values()}
    fenced = False
    for line in lines:
        if line.startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        m = BACKLOG_TASK.match(line)
        if m:
            backlog_marks[MARKS[m.group(1)]] += 1
    backlog_real = (
        sum(backlog_marks.values()), backlog_marks["ready"],
        backlog_marks["blocked"], backlog_marks["done"],
    )
    backlog_seen = [ln for ln in lines if BACKLOG.match(ln)]
    if len(backlog_seen) != 1:
        bad.append(
            f"Backlog: expected exactly one Backlog row, found {len(backlog_seen)} "
            f"— the B and H rows are {backlog_real[0]} tasks and they belong in the table"
        )
    else:
        claimed = tuple(map(int, BACKLOG.match(backlog_seen[0]).groups()[1:]))
        if claimed != backlog_real:
            bad.append(
                f"Backlog: row says {'/'.join(map(str, claimed))}, the B and H ticks "
                f"count {'/'.join(map(str, backlog_real))}  (total/ready/blocked/done)"
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

    # `B241`. A row a § Progress entry says it closed, against the tick that
    # row actually carries. The entry and the row are both named, because
    # "something is wrong in Progress" is not a fault anyone can act on.
    marks_by_id, fenced = {}, False
    for line in lines:
        if line.startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        m = ANY_TASK.match(line)
        if m:
            marks_by_id.setdefault(m.group(2), []).append(m.group(1))
    for title, headline in progress_headlines(lines):
        for row_id in closed_claims(headline):
            marks = marks_by_id.get(row_id)
            if marks is None:
                bad.append(
                    f"Progress: \"{title}\" says {row_id} closed, and there is no "
                    f"row with that id — a citation that cannot be resolved"
                )
            elif any(mark != "x" for mark in marks):
                shown = "/".join(f"[{mark}]" for mark in marks)
                bad.append(
                    f"Progress: \"{title}\" says {row_id} closed, and {row_id} is "
                    f"{shown} — tick it, or say in the entry what is still open"
                )

    total = sum(sum(v[k] for k in MARKS.values()) for v in per.values())
    if bad:
        print(f"tracker DRIFTED — {len(bad)} row(s) wrong, {total} tasks counted\n")
        for b in bad:
            print("  " + b)
        print("\nRecount and fix the table by hand.")
        return 1

    claims = sum(len(closed_claims(h)) for _, h in progress_headlines(lines))
    print(f"tracker OK — {total} phase tasks, every row matches its ticks, "
          f"{claims} rows named as closed in Progress are ticked")
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
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else None))
