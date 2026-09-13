# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P19` — the proof ledger, and the rules that keep it from becoming marketing.

The ledger's whole value is that a stranger can check it. That makes every way it
can quietly stop being true a defect, and these are the ways:

  * a claim outliving the file it cites
  * a claim citing a roadmap row nobody wrote
  * an `after` with no `before` — an assertion wearing a measurement's clothes
  * a fixture-measured number losing the word `fixture`
  * `LEDGER.md` hand-edited away from what the claims say
  * the README restating a figure that has since moved

**The tests here are about the checker, not about the prose.** `Law 20`: a test
that greps `LEDGER.md` for a nice sentence is testing the sentence. Each test
below breaks something and asserts the checker notices — because a checker that
passes on a broken tree is worse than no checker, and the only way to know is to
hand it a broken tree.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CHECKER = ROOT / ".pantheon" / "check-ledger.py"
LEDGER = ROOT / "LEDGER.md"
README = ROOT / "README.md"


def _load():
    """Import the checker fresh, with `.pantheon` on the path for `ledger`."""
    if str(ROOT / ".pantheon") not in sys.path:
        sys.path.insert(0, str(ROOT / ".pantheon"))
    spec = importlib.util.spec_from_file_location("_check_ledger", CHECKER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def checker():
    return _load()


@pytest.fixture()
def claims():
    if str(ROOT / ".pantheon") not in sys.path:
        sys.path.insert(0, str(ROOT / ".pantheon"))
    from ledger import claims as C

    return C


# --------------------------------------------------------------------------
# The tree as it stands
# --------------------------------------------------------------------------


def test_the_ledger_in_the_tree_is_what_the_claims_produce(checker):
    """Hand-editing LEDGER.md has to break something, or nothing stops it."""
    assert checker.verify() == []
    assert LEDGER.exists()
    assert LEDGER.read_text(encoding="utf-8") == checker.render()


def test_every_claim_carries_a_provenance_and_a_reproduction(claims):
    for claim in claims.CLAIMS:
        assert claim.provenance in claims.PROVENANCE, claim.id
        assert claim.repro.strip(), f"{claim.id} has no command a stranger can run"
        assert claim.how.strip(), f"{claim.id} does not say how we got there"


def test_every_cited_path_exists(claims):
    for claim in claims.CLAIMS:
        for path in claim.evidence:
            assert (ROOT / path).exists(), f"{claim.id} cites missing {path}"


def test_claim_ids_are_unique(claims):
    ids = [c.id for c in claims.CLAIMS]
    assert len(ids) == len(set(ids))


def test_no_area_renders_empty(claims):
    """An area header with nothing under it reads as a section somebody deleted."""
    used = {c.area for c in claims.CLAIMS}
    declared = {name for name, _ in claims.AREAS}
    assert used == declared, f"unused: {declared - used}, undeclared: {used - declared}"


# --------------------------------------------------------------------------
# The honesty rules, which are the reason this file exists
# --------------------------------------------------------------------------


def test_the_retrieval_numbers_are_labelled_fixture(claims):
    """The corpus says of itself that it tests the imagination. So must the ledger.

    These two rows carry the numbers a reader is most likely to quote and the
    ones least able to carry that weight. Losing the tag would not break a build
    or fail a test anywhere else in this repository — which is exactly why it is
    pinned here.
    """
    by_id = {c.id: c for c in claims.CLAIMS}
    for cid in ("retrieval-recall", "retrieval-mrr"):
        assert by_id[cid].provenance == "fixture"


def test_dropping_the_fixture_tag_is_caught(checker, claims, monkeypatch):
    swapped = tuple(
        c._replace(provenance="measured") if c.id == "retrieval-recall" else c
        for c in claims.CLAIMS
    )
    monkeypatch.setattr(claims, "CLAIMS", swapped)
    problems = checker.verify()
    assert any("retrieval-recall" in p and "fixture" in p for p in problems)


def test_a_claim_citing_a_missing_file_is_caught(checker, claims, monkeypatch):
    bad = claims.CLAIMS[0]._replace(id="probe", evidence=("no/such/file.py",))
    monkeypatch.setattr(claims, "CLAIMS", claims.CLAIMS + (bad,))
    assert any("no/such/file.py" in p for p in checker.verify())


def test_a_claim_citing_a_row_nobody_wrote_is_caught(checker, claims, monkeypatch):
    bad = claims.CLAIMS[0]._replace(id="probe", rows=("P99-99",))
    monkeypatch.setattr(claims, "CLAIMS", claims.CLAIMS + (bad,))
    assert any("P99-99" in p for p in checker.verify())


def test_an_after_with_no_before_is_caught(checker, claims, monkeypatch):
    """The shape this rule exists for: a number with nothing to compare it to."""
    bad = claims.CLAIMS[0]._replace(id="probe", before="", after="5")
    monkeypatch.setattr(claims, "CLAIMS", claims.CLAIMS + (bad,))
    assert any("probe" in p and "one-sided" in p for p in checker.verify())


def test_a_claim_with_no_reproduction_is_caught(checker, claims, monkeypatch):
    bad = claims.CLAIMS[0]._replace(id="probe", repro="   ")
    monkeypatch.setattr(claims, "CLAIMS", claims.CLAIMS + (bad,))
    assert any("probe" in p and "trust us" in p for p in checker.verify())


def test_an_unknown_provenance_tag_is_caught(checker, claims, monkeypatch):
    bad = claims.CLAIMS[0]._replace(id="probe", provenance="obviously")
    monkeypatch.setattr(claims, "CLAIMS", claims.CLAIMS + (bad,))
    assert any("probe" in p and "provenance" in p for p in checker.verify())


def test_losing_every_diffed_claim_is_caught(checker, claims, monkeypatch):
    """Without one, nothing in the ledger is measured against upstream's own tree."""
    flattened = tuple(
        c._replace(provenance="counted") if c.provenance == "diffed" else c
        for c in claims.CLAIMS
    )
    monkeypatch.setattr(claims, "CLAIMS", flattened)
    assert any("diffed" in p for p in checker.verify())


# --------------------------------------------------------------------------
# The README, which is the front door and had already rotted twice
# --------------------------------------------------------------------------


def test_the_readme_links_the_ledger():
    """A ledger nobody can find proves nothing — `Law 15`."""
    readme = README.read_text(encoding="utf-8")
    assert "LEDGER.md" in readme


def test_the_readme_test_badge_matches_the_ledger(checker, claims):
    by_id = {c.id: c for c in claims.CLAIMS}
    passing = by_id["tests"].after.split("·")[-1].strip().split()[0]
    readme = README.read_text(encoding="utf-8")
    assert f"tests-{passing.replace(',', '%2C')}%20passing" in readme
    assert f"**{passing} passing**" in readme


def test_readme_drift_is_caught(checker, claims, tmp_path, monkeypatch):
    """Move the badge, and the checker has to notice.

    The badge read `6,301 passing` against a suite of 8,642 before this rule
    existed. A stale number on the front page of a repository whose pitch is
    *our numbers are checkable* is the worst place to keep one.

    Derived, not typed — for the reason spelled out in the sibling below. This
    test was written with `tests-8%2C642%20passing` hard-coded and went stale
    the next time the suite grew: the `.replace` matched nothing, the README
    stayed valid, the checker reported no problem, and the assertion failed for
    the opposite of the reason it was written. Twice now, in two adjacent tests.
    """
    by_id = {c.id: c for c in claims.CLAIMS}
    passing = by_id["tests"].after.split("\u00b7")[-1].strip().split()[0]
    badge = f"tests-{passing.replace(',', '%2C')}%20passing"
    readme = README.read_text(encoding="utf-8")
    assert badge in readme, "the README badge is already out of step with the ledger"
    fake = tmp_path / "README.md"
    fake.write_text(readme.replace(badge, "tests-9%2C999%20passing"), encoding="utf-8")
    monkeypatch.setattr(checker, "README", fake)
    assert any("badge" in p for p in checker.verify())


def test_tracker_total_drift_is_caught(checker, tmp_path, monkeypatch):
    """Derive the current figures rather than typing them.

    Written first with `376 tracked tasks, 170 done` hard-coded, which stopped
    being true six rows later in the same sitting: the `.replace` silently
    matched nothing, the README stayed correct, the checker reported no problem
    and **the test failed for the opposite of the reason it was written**. A
    pinned figure inside the test that pins figures. The suite found it.
    """
    total = next(
        line for line in
        (ROOT / ".pantheon" / "ROADMAP.md").read_text(encoding="utf-8").splitlines()
        if line.startswith("| **Total**")
    )
    cells = [c.strip().strip("*") for c in total.split("|")]
    current = f"**{cells[3]} tracked tasks, {cells[6]} done"
    readme = README.read_text(encoding="utf-8")
    assert current in readme, "the README is already out of step with the tracker"
    fake = tmp_path / "README.md"
    fake.write_text(readme.replace(current, "**1 tracked tasks, 1 done"), encoding="utf-8")
    monkeypatch.setattr(checker, "README", fake)
    assert any("tracked tasks" in p for p in checker.verify())


# --------------------------------------------------------------------------
# The footgun the naming created
# --------------------------------------------------------------------------


def test_running_the_checker_bare_writes_nothing():
    """`release-gate.py` runs undeclared `.pantheon/check-*.py` with NO arguments.

    A script in that directory that regenerates a tracked file when called bare
    would rewrite the tree mid-gate, and the gate would pass because it did.
    Verifying is the default; writing takes `--write`.
    """
    before = LEDGER.read_text(encoding="utf-8")
    mtime = LEDGER.stat().st_mtime
    proc = subprocess.run(
        [sys.executable, str(CHECKER)], cwd=str(ROOT), capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert LEDGER.read_text(encoding="utf-8") == before
    assert LEDGER.stat().st_mtime == mtime


def test_a_stale_ledger_fails_the_default_invocation(tmp_path, monkeypatch):
    """The staleness rule is the one that stops a hand-edit surviving."""
    module = _load()
    fake = tmp_path / "LEDGER.md"
    fake.write_text("# not what the claims say\n", encoding="utf-8")
    monkeypatch.setattr(module, "OUTPUT", fake)
    monkeypatch.setattr(sys, "argv", ["check-ledger.py"])
    assert module.main() == 1


# --------------------------------------------------------------------------
# What the rendered file must contain, because leaving it out is the failure mode
# --------------------------------------------------------------------------


def test_the_ledger_states_what_it_does_not_prove(checker):
    """A ledger with no limitations section reads as marketing, and is treated so."""
    rendered = checker.render()
    assert "## What this ledger does not prove" in rendered
    assert "unmerged" in rendered or "behind" in rendered


def test_the_ledger_names_every_deleted_file(claims):
    """*We add, never subtract* is a claim with counter-examples, so name them.

    537 added against 5 removed is only evidence if the five are named. A row
    that states the ratio and not the exceptions has not earned the first
    number. The fifth arrived on 2026-09-12 and the claim's headline, its
    figure and its prose all had to move together — the headline said five
    while the sentence under it still said four, which no checker catches
    because both are prose.
    """
    by_id = {c.id: c for c in claims.CLAIMS}
    text = by_id["add-never-subtract"].pantheon
    assert "minus five files" in text, "the prose must agree with the headline"
    for deleted in (
        "ACKNOWLEDGMENTS.md",
        "odysseus.zsh",
        "GohuFont.ttf",
        "reminders.js",
        "pantheon-wordmark.png",
    ):
        assert deleted in text, f"{deleted} is deleted in the tree and unnamed in the ledger"


def test_the_ledger_prints_how_to_read_a_provenance_tag(checker, claims):
    rendered = checker.render()
    for tag in claims.PROVENANCE:
        assert f"**`{tag}`**" in rendered, f"{tag} is used but never explained"


# --------------------------------------------------------------------------
# Three rules a mutation run found untested — each one asserted against the
# DATA above and never against the CHECKER, so switching the rule off changed
# nothing and every test still passed. That is the same defect as a scan
# satisfied by a name inside `if False:`: the assertion was real and it was
# pointed at the wrong object.
# --------------------------------------------------------------------------


def test_a_claim_with_no_method_is_caught(checker, claims, monkeypatch):
    """`how` is the part worth reading. A row without it is a bullet point."""
    bad = claims.CLAIMS[0]._replace(id="probe", how="  ")
    monkeypatch.setattr(claims, "CLAIMS", claims.CLAIMS + (bad,))
    assert any("probe" in p and "how" in p for p in checker.verify())


def test_two_claims_sharing_an_id_is_caught(checker, claims, monkeypatch):
    """Ids address rows from elsewhere; two rows answering to one is a silent swap."""
    twin = claims.CLAIMS[0]._replace(headline="a different headline entirely")
    monkeypatch.setattr(claims, "CLAIMS", claims.CLAIMS + (twin,))
    problems = checker.verify()
    assert any(claims.CLAIMS[0].id in p and "share this id" in p for p in problems)


def test_a_claim_in_an_undeclared_area_is_caught(checker, claims, monkeypatch):
    """An area not in AREAS renders nowhere — the claim vanishes from the output."""
    bad = claims.CLAIMS[0]._replace(id="probe", area="Somewhere Else")
    monkeypatch.setattr(claims, "CLAIMS", claims.CLAIMS + (bad,))
    assert any("probe" in p and "AREAS" in p for p in checker.verify())


def test_an_undeclared_area_renders_a_summary_row_with_no_section(checker, claims, monkeypatch):
    """Why the rule above matters, and it is worse than "the claim disappears".

    Written expecting the claim to vanish entirely. It does not: the at-a-glance
    table iterates `CLAIMS` while the body iterates `AREAS`, so a claim in an
    undeclared area **appears in the summary table and has no section below it**
    — a headline promising detail that is not there, which is a worse failure
    than an absence because a reader cannot tell it happened.
    """
    bad = claims.CLAIMS[0]._replace(
        id="probe", area="Somewhere Else", headline="a headline with no section",
    )
    monkeypatch.setattr(claims, "CLAIMS", claims.CLAIMS + (bad,))
    rendered = checker.render()
    assert "| a headline with no section |" in rendered, "expected it in the summary table"
    assert "### a headline with no section" not in rendered, "expected no detail section"


# --------------------------------------------------------------------------
# The one rule that depends on something not every checkout has
# --------------------------------------------------------------------------


def test_the_upstream_gap_is_checked_live_where_the_remote_exists(checker, claims, monkeypatch):
    """`P19-05` asked for the behind-by-N to be measured, not typed.

    It cannot always be — the `upstream` remote lives on the deployment box and
    the mirror's history starts at an import commit. So the rule runs where it
    can and is silent where it cannot, and both halves need proving: a rule that
    only ever takes the silent branch is not a rule.
    """

    class _Result:
        def __init__(self, code, out):
            self.returncode, self.stdout = code, out

    # `git cherry` output: `+` is a commit we have no patch-equivalent for,
    # `-` is one we do. Counting lines rather than reading a number is the
    # whole correction — see the checker's own comment for why `rev-list` was
    # wrong, which this ledger's check is what discovered.
    def _cherry(plus, minus=0):
        return _Result(0, "\n".join(["+ " + "a" * 40] * plus + ["- " + "b" * 40] * minus))

    monkeypatch.setattr(checker.subprocess, "run", lambda *a, **k: _cherry(40))
    problems = checker._upstream_gap_problems()
    assert any("upstream moved" in p for p in problems), "drift not caught"

    stated = int({c.id: c for c in claims.CLAIMS}["behind-upstream"].after.split()[0])
    monkeypatch.setattr(checker.subprocess, "run", lambda *a, **k: _cherry(stated, minus=5))
    assert checker._upstream_gap_problems() == [], "agreement reported as a problem"


def test_a_cherry_picked_fix_stops_counting_as_behind(checker, claims, monkeypatch):
    """The bug this check had, caught by the check itself.

    `git rev-list FORK..upstream` does not fall when a fix is cherry-picked,
    because a cherry-pick is a new commit with a new sha — so after landing
    five upstream fixes the count still said twelve and the ledger would have
    been forced to keep claiming a gap it had just closed. `git cherry`
    compares patch ids, so an equivalent patch registers as `-`.
    """

    class _Result:
        def __init__(self, code, out):
            self.returncode, self.stdout = code, out

    # N absent, five equivalent: only the N may count. **N is read from the
    # claim, not typed here.** Written first with a literal seven, which went
    # stale the next time upstream moved and failed on a checker that was
    # working — the third time this file has been bitten by a pinned figure
    # inside a test whose job is to check figures.
    import re

    stated = int(re.match(r"(\d+)", {c.id: c for c in claims.CLAIMS}["behind-upstream"].after).group(1))
    out = "\n".join(["+ " + "a" * 40] * stated + ["- " + "b" * 40] * 5)
    monkeypatch.setattr(checker.subprocess, "run", lambda *a, **k: _Result(0, out))
    assert checker._upstream_gap_problems() == []

    # And one more absent commit than the claim admits to is the failure this
    # check exists for.
    out = "\n".join(["+ " + "a" * 40] * (stated + 1) + ["- " + "b" * 40] * 5)
    monkeypatch.setattr(checker.subprocess, "run", lambda *a, **k: _Result(0, out))
    problems = checker._upstream_gap_problems()
    assert len(problems) == 1 and "upstream moved" in problems[0]
    assert "git cherry" in problems[0], (
        "the message named `git rev-list`, which is the command this check was "
        "corrected away from — it would send a reader to reproduce the wrong number"
    )


def test_a_checkout_without_the_upstream_remote_is_not_a_failure(checker, monkeypatch):
    """Most checkouts have no `upstream` remote. That is normal, not broken."""

    class _Result:
        returncode, stdout = 128, ""

    monkeypatch.setattr(checker.subprocess, "run", lambda *a, **k: _Result())
    assert checker._upstream_gap_problems() == []


def test_losing_the_upstream_gap_claim_is_caught(checker, claims, monkeypatch):
    """Deleting the row that admits the weakness must not be a silent pass."""
    without = tuple(c for c in claims.CLAIMS if c.id != "behind-upstream")
    monkeypatch.setattr(claims, "CLAIMS", without)
    assert any("no longer states the gap" in p for p in checker._upstream_gap_problems())


def test_the_gap_is_measured_with_git_cherry_not_rev_list(checker, monkeypatch):
    """The command IS the correction, so the command is what gets asserted.

    Every other test here mocks `subprocess.run` wholesale and never looks at
    the argv — so swapping `git cherry` back to `git rev-list` survived them
    all, which is the one mutation that undoes this fix entirely.
    """
    seen = {}

    class _Result:
        returncode = 0
        stdout = ""

    def _capture(argv, *a, **k):
        seen["argv"] = list(argv)
        return _Result()

    monkeypatch.setattr(checker.subprocess, "run", _capture)
    checker._upstream_gap_problems()
    assert seen["argv"][:2] == ["git", "cherry"], (
        f"the gap is measured with {seen['argv'][:2]}; `rev-list` cannot see a "
        f"cherry-picked fix and would report a gap that is already closed"
    )
    assert "rev-list" not in seen["argv"]
