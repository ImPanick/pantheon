# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B241` — a § Progress entry that says a row closed, against the row's tick.

**What happened.** `1a70478` implemented `B02` and `B03` in full — code, tests,
mutations — and its own § Progress entry reads *"`B02`, `B03`, `B05`, `B07`,
`B21` and `B79` closed"*. Four of those six were `- [x]`. `B02` and `B03` were
`- [ ]` for two days, so the tracker's narrative and the tracker's count
disagreed about the same six rows in the same sentence, with `481 tracked, 268
done` computed from the ticks and the list beside it not. `B44` was prose
drifting from a table and `B79` was a table counting the wrong set of rows; this
is prose drifting from the **ticks**, and nothing compared those.

**Why the row was filed rather than built.** A scan for row ids in a sentence
containing *closed* over-fires at once. In the very entries this file scans it
would flag `B15`, `B16`, `B22` and `B23` (*ruled by the owner*), `B75`–`B78`
(*filed*), `B73` and `B74` (*filed to the backlog*) and `B121` (*left open on
purpose*). Nine false positives is a checker nobody can leave green.

**`Law 20`.** This checker reads Markdown, so it is a text scan and that is
legitimate: the roadmap is the artefact under test, not a stand-in for code. Its
own tests are not allowed the same licence, so nothing below asserts on
`check-tracker.py`'s source. Every test drives the real functions or the real
CLI over real, historical and synthetic trackers.
"""
from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CHECKER = ROOT / ".pantheon" / "check-tracker.py"
ROADMAP = ROOT / ".pantheon" / "ROADMAP.md"

# The commit whose Progress entry named two rows closed and left them unticked.
HISTORICAL = "1a70478"


def _module():
    spec = importlib.util.spec_from_file_location("check_tracker", CHECKER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(path: Path):
    proc = subprocess.run([sys.executable, str(CHECKER), str(path)],
                          capture_output=True, text=True, timeout=120)
    return proc.returncode, proc.stdout + proc.stderr


def _untick(text: str, *row_ids: str) -> str:
    """Put a row back the way `1a70478` left it."""
    for row_id in row_ids:
        before = text
        text = text.replace(f"- [x] **{row_id}**", f"- [ ] **{row_id}**", 1)
        assert text != before, f"{row_id} was not ticked to begin with"
    return text


# ---------------------------------------------------------------------------
# the state the row was filed from
# ---------------------------------------------------------------------------

def test_the_checker_fails_on_the_tree_as_it_stood_at_1a70478(tmp_path):
    """`Law 9`. The evidence is not "a test passes"; it is that the checker
    fails on the exact state the row describes and says which entry and which
    row. Reconstructed from the tracker in this tree by putting `B02` and `B03`
    back to `- [ ]` — the entry naming them closed is unchanged and still four
    entries down, because Progress entries are never rewritten."""
    broken = tmp_path / "ROADMAP.md"
    broken.write_text(_untick(ROADMAP.read_text(encoding="utf-8"), "B02", "B03"),
                      encoding="utf-8")
    code, out = _run(broken)
    assert code == 1, out
    assert "says B02 closed, and B02 is [ ]" in out, out
    assert "says B03 closed, and B03 is [ ]" in out, out
    # The ENTRY is named, because "something is wrong in Progress" is not a
    # fault anybody can act on — there are 171 of them. Both rows are named as
    # closed by two entries apiece (the wave that shipped them and the wave that
    # ticked them), and the report says so rather than picking one.
    assert out.count("The tally was answering a narrower question") == 2, out
    assert out.count("The wave with no collisions") == 2, out
    assert out.count("Progress:") == 4, out


@pytest.mark.skipif(
    subprocess.run(["git", "cat-file", "-e", f"{HISTORICAL}:.pantheon/ROADMAP.md"],
                   cwd=ROOT, capture_output=True).returncode != 0,
    reason="the historical commit is not reachable from this worktree")
def test_the_checker_fails_on_the_real_1a70478_blob(tmp_path):
    """The same claim against the actual bytes rather than a reconstruction."""
    blob = subprocess.run(
        ["git", "show", f"{HISTORICAL}:.pantheon/ROADMAP.md"],
        cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert blob.returncode == 0, blob.stderr
    old = tmp_path / "ROADMAP.md"
    old.write_text(blob.stdout, encoding="utf-8")
    code, out = _run(old)
    assert code == 1, out
    assert "says B02 closed, and B02 is [ ]" in out, out
    assert "says B03 closed, and B03 is [ ]" in out, out
    # That tracker was otherwise clean: these two rows are the whole fault, which
    # is the row's own claim about what nothing was comparing.
    assert "tracker DRIFTED — 2 row(s) wrong" in out, out


def test_no_progress_entry_in_this_tree_names_an_unticked_row():
    """The row's `Verify` against the tracker as it stands.

    This asserts the absence of a `Progress:` fault rather than a green exit,
    and the difference is deliberate: in a parallel wave the status table drifts
    the moment any agent ticks a row, and the integrator recounts it once on the
    merge. A test that demanded exit 0 would be red in every worktree for a
    reason that has nothing to do with this row."""
    code, out = _run(ROADMAP)
    assert "Progress:" not in out, out
    if code == 0:
        assert "rows named as closed in Progress are ticked" in out
    else:
        # Whatever else is drifting is a table recount, which is the
        # integrator's line to write and not a claim anybody made.
        faults = [ln.strip() for ln in out.splitlines() if ln.startswith("  ")]
        assert all(f.startswith(("Backlog:", "Total:")) for f in faults), out


# ---------------------------------------------------------------------------
# the grammar, over the entries this file really has
# ---------------------------------------------------------------------------

def test_closed_is_told_from_filed_ruled_and_left_open():
    """The sentence the row is, checked per entry over all 171 real headlines.

    The nine ids the row names as the naive version's false positives are not a
    list of rows that are never closed — every one of them was closed later, by
    a later entry, and a checker that refused to claim them at all would be
    useless. They are ids that ONE entry names with a verb that is not `closed`.
    So the claim tested here is per entry: the wave that *filed* `B75` does not
    claim it, and the wave that *closed* it does."""
    mod = _module()
    lines = ROADMAP.read_text(encoding="utf-8").splitlines()
    heads = mod.progress_headlines(lines)
    # `B310`. A floor, not a pin. This assertion exists to prove the scan found
    # the real corpus rather than three entries, and `171` was the count on the
    # day it was written — so the next Progress entry reddened it, which is a
    # test that fails on correct work. The property below is what the row is;
    # the number only has to be large enough that a broken parser cannot pass.
    assert len(heads) >= 171, len(heads)
    by_entry = {title: mod.closed_claims(headline) for title, headline in heads}

    filed = "The tally was answering a narrower question than its heading, and four rows landed in parallel"
    ruled = "An argument that ended the run, a gate that asked the wrong question, and a plan that lasted one turn"
    backlog = "A server that was started every morning and could not be called"
    # The exact nine. Each is named in the headline of the entry beside it, with
    # a verb that is not `closed`, and none of them is claimed there.
    for row_id, title in (("B15", ruled), ("B16", ruled), ("B22", ruled),
                          ("B23", ruled), ("B75", filed), ("B76", filed),
                          ("B77", filed), ("B78", filed), ("B74", backlog)):
        headline = dict(heads)[title]
        assert f"`{row_id}`" in headline, (row_id, title)
        assert row_id not in by_entry[title], \
            f"{row_id} is named in {title!r} with a verb that is not `closed`"
    # ...and each of them IS claimed by the entry that really closed it, so the
    # narrowness has not simply turned the check off.
    assert by_entry[ruled] == ["B06", "B17", "B19"], by_entry[ruled]
    assert by_entry[filed] == ["B02", "B03", "B05", "B07", "B21", "B79"], by_entry[filed]
    closed_somewhere = {r for claims in by_entry.values() for r in claims}
    for row_id in ("B75", "B76", "B77", "B78", "B121", "B73", "B74"):
        assert row_id in closed_somewhere, row_id
    # The four the owner RULED on are a different case and stay out entirely:
    # no entry has ever said they closed, so a checker that read `ruled` as a
    # closure would be inventing a claim nobody made.
    for row_id in ("B15", "B16", "B22", "B23"):
        assert row_id not in closed_somewhere, row_id
    # The range, and the bracketed same-turn form, both from real entries.
    # `B310`. Named, not `heads[0]`. This asked the *newest* entry for rows that
    # a *particular* entry closed, which is true only until the next entry lands
    # — and the next entry landed the same day. Every other lookup in this test
    # already names its entry; this one was the odd out and it was the one that
    # broke. A test that fails on correct work is not evidence of anything.
    ranges = ("The wave with no collisions, a 500 nobody was serving, and the "
              "nonce that was costing 283 KB a navigation")
    assert ranges in by_entry, sorted(by_entry)[:3]
    for row_id in ("B151", "B152", "B153", "B161", "B162", "B163"):
        assert row_id in by_entry[ranges], row_id
    assert "P18-09" in closed_somewhere
    # A floor for the same reason as the headline count above: this grows every
    # wave, and what it proves is that the grammar reads the whole file.
    assert len(closed_somewhere) >= 80, len(closed_somewhere)


@pytest.mark.parametrize("headline,want", [
    # the plain list, and the semicolon that ends the claim
    ("`B06`, `B17` and `B19` closed; `B15`, `B16`, `B22` and `B23` ruled by "
     "the owner (`D-2026-09-14-03`); the backlog sits outside this tally.",
     ["B06", "B17", "B19"]),
    # a range expands, and `filed` after the semicolon does not join it
    ("537 tracked, 326 done. `B02`, `B151`–`B153` and `B250` closed; fifteen "
     "rows filed.", ["B02", "B151", "B152", "B153", "B250"]),
    # a dash between two ids that cannot make a range is read as two ids, not
    # as two hundred invented ones
    ("`B12`–`P3-04` closed.", ["B12", "P3-04"]),
    # `filed` naming ids explicitly, still not a closure
    ("`B02`, `B03` closed; `B75`, `B76`, `B77` and `B78` filed.", ["B02", "B03"]),
    # ...and the same two clauses the other way round, which is what makes the
    # SEMICOLON the boundary rather than the order. A grammar that let `;` join
    # the run would read this as six closures and cry wolf on four of them.
    ("`B75`, `B76`, `B77` and `B78` filed; `B02` and `B03` closed.",
     ["B02", "B03"]),
    # The FULL STOP is the other boundary, and a bracketed id before it is what
    # tests it: `1 new phase row (`P18-09`).` ends where the sentence ends.
    ("381 tracked, 189 done. 1 new phase row (`P18-09`). `P18-08` closed.",
     ["P18-08"]),
    # A semicolon between an id and the closure clause. The verb is what stops
    # the run in every entry this file has today, so without this case the
    # semicolon bound is redundant and untested — and a terse
    # *"these two ruled; these two closed"* would walk straight through it.
    ("`B15`, `B16`; `B06` and `B17` closed.", ["B06", "B17"]),
    # And the verb itself, with a comma on either side of it: a word between two
    # ids ends the run. This is the row's own false positive in miniature —
    # `filed` and `closed` in one sentence, one claim.
    ("`B75` filed, `B02` closed.", ["B02"]),
    # a regression is not a row
    ("508 tracked, 286 done. 0 new phase rows, 1 regression closed. `B131` "
     "closed; 1 row filed.", ["B131"]),
    # the bracketed same-turn form
    ("381 tracked, 189 done. 1 new phase row (`P18-09`), closed the same turn. "
     "`B73` filed to the backlog. 0 regressions.", ["P18-09"]),
    # a full stop ends the run just as a semicolon does
    ("3 new rows (`P17-12`, `P17-13`, `P17-14`), 0 regressions. `P17-08` "
     "closed.", ["P17-08"]),
    # two claims in one headline
    ("`P18-06` closed, `P18-07` closed as well.", ["P18-06", "P18-07"]),
    # the words that are not closure
    ("`B22` ruled by the owner; `B44` renumbered on merge; `B12` folded into "
     "`B11`; `B121` is left open on purpose.", []),
    # no bold claim at all
    ("Suite 6,975 → 6,991 passing.", []),
    ("376 tracked, 182 done. 0 new rows, 0 regressions.", []),
])
def test_the_forms_a_progress_entry_uses(headline, want):
    """Synthetic headlines in the shapes this tracker really writes, driven
    through the shipped grammar. A form the file does not use yet is still a
    form somebody will write, which is why `renumbered`, `folded` and `left
    open` are in here beside the ones that already appear."""
    assert _module().closed_claims(headline) == want


def test_a_claim_naming_a_row_that_does_not_exist_is_reported(tmp_path):
    """The other half of a citation: a row id in a closure claim that resolves
    to nothing. `B48` is why an unresolvable id matters — two rows shared one id
    for a day, and a citation that cannot be resolved is a tick that lands on
    whichever row the reader found first."""
    text = ROADMAP.read_text(encoding="utf-8")
    entry = "### The tally was answering a narrower question"
    at = text.index(entry)
    text = text[:at] + text[at:].replace("`B79` closed;", "`B79` and `B999` closed;", 1)
    broken = tmp_path / "ROADMAP.md"
    broken.write_text(text, encoding="utf-8")
    code, out = _run(broken)
    assert code == 1, out
    assert "says B999 closed, and there is no row with that id" in out, out


def test_a_blocked_or_claimed_row_is_not_a_closed_one(tmp_path):
    """`- [~]` is blocked and `- [·]` is claimed. Neither is done, and a
    checker that accepted any non-empty mark would pass a row that is parked."""
    text = ROADMAP.read_text(encoding="utf-8")
    for mark in ("~", "·"):
        broken = tmp_path / f"ROADMAP-{ord(mark)}.md"
        broken.write_text(text.replace("- [x] **B05**", f"- [{mark}] **B05**", 1),
                          encoding="utf-8")
        code, out = _run(broken)
        assert code == 1, out
        assert f"says B05 closed, and B05 is [{mark}]" in out, out


def test_the_claim_is_read_from_the_headline_and_not_the_narrative(tmp_path):
    """The bound that makes this leave-green-able. A later paragraph of the
    newest entry says *"Three rows were closed by re-measuring and finding the
    filed number wrong"* and names `B83`, `B161` and `B162` in the sentences
    after it; another says `B121` is left open. None of that is the claim, and a
    checker that read the whole entry would fail on prose that is simply true."""
    mod = _module()
    lines = ROADMAP.read_text(encoding="utf-8").splitlines()
    title, headline = mod.progress_headlines(lines)[0]
    assert "tracked," in headline and "closed;" in headline
    body = ROADMAP.read_text(encoding="utf-8")
    assert "**Three rows were closed by re-measuring" in body
    assert "Three rows were closed by re-measuring" not in headline
    # A narrative sentence of exactly that shape claims nothing on its own.
    assert mod.closed_claims(
        "Three rows were closed by re-measuring and finding the filed number "
        "wrong, every time in the direction of more work. `B83` said five "
        "hand-written play triangles in two geometries; there were 19 in five."
    ) == []
