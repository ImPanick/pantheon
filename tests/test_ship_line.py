# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B451` — the ship line's arithmetic, and the ratchet that stops it rotting.

`.pantheon/SHIP-LINE.md` proposes that fifteen of 234 open rows block making
this repository public, and that the other 219 stay tracked and stop being gates.
A proposal is a claim (`Law 9`), so every number in it is computed by
`.pantheon/ship-line.py` and every number here is computed the same way, from the
tracker, rather than restated.

The important test is `test_an_unclassified_candidate_fails_the_check`. Every
hand-maintained list in this repository has rotted — the status table drifted by
nineteen (`B44`), the backlog sat outside the table whose heading covered it
(`B79`), a Progress entry claimed rows it left unticked (`B241`) — and each was
fixed by a script that recounts and fails. If the ship line is adopted and its
`--check` cannot fail, it is the fourth.

`Law 20`: the parser and the rule are driven as code against synthetic trackers,
not asserted against the source text of the real one.
"""
import importlib.util
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TRACKER = ROOT / ".pantheon" / "ROADMAP.md"
PROPOSAL = ROOT / ".pantheon" / "SHIP-LINE.md"


def _load():
    spec = importlib.util.spec_from_file_location(
        "_ship_line", ROOT / ".pantheon" / "ship-line.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sl = _load()
TRACKER_TEXT = TRACKER.read_text(encoding="utf-8")
ROWS = sl.parse_rows(TRACKER_TEXT)
REGISTER = sl.parse_register(PROPOSAL.read_text(encoding="utf-8"))


# --- the parser agrees with the tracker's own arithmetic -------------------

def _check_tracker():
    spec = importlib.util.spec_from_file_location(
        "_check_tracker", ROOT / ".pantheon" / "check-tracker.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_row_parser_agrees_with_check_trackers_own_recount():
    """Two parsers disagreeing about the row set makes every count here
    unfalsifiable, so they are compared to each other directly.

    **Against `check-tracker.py`'s recount, not against the status table.** The
    table is written once by the integrator on merge, so inside a worktree that
    has filed rows it is correctly stale — a test pinned to it would be red for
    the whole of every wave and would therefore be ignored, which is worse than
    not having it. `check-tracker.py` owns the table; this owns the parse.
    """
    ct = _check_tracker()
    lines = TRACKER_TEXT.splitlines()
    per, _order, problems = ct.count(lines)
    assert not problems, problems

    phase_rows = [r for r in ROWS if re.match(r"P\d+-", r.id)]
    theirs = sum(sum(v[k] for k in ("ready", "claimed", "blocked", "done"))
                 for v in per.values())
    assert len(phase_rows) == theirs, (len(phase_rows), theirs)
    theirs_done = sum(v["done"] for v in per.values())
    assert sum(1 for r in phase_rows if not r.open) == theirs_done

    backlog = [r for r in ROWS if re.match(r"[BH]\d+", r.id)]
    fenced, mine = False, 0
    for line in lines:
        if line.startswith("```"):
            fenced = not fenced
            continue
        if not fenced and ct.BACKLOG_TASK.match(line):
            mine += 1
    assert len(backlog) == mine, (len(backlog), mine)


# There is deliberately no test here that the newest `§ Progress` headline
# matches the open count. `check-tracker.py` already enforces exactly that
# (`B44`), and a second copy of a ceiling is a ceiling that will disagree with
# itself — `Law 13`, and the same reason `release-gate.py` reads its checker
# list out of `ci.yml` instead of carrying one.


def test_the_trend_is_the_series_the_proposal_states():
    """`§ 1`'s table, computed. If the tracker moves, this fails and the
    proposal's own numbers have to be recomputed rather than carried — which is
    the failure mode `B44` is named after."""
    waves = sl.distinct_waves(sl.trend(TRACKER_TEXT), 10)
    assert len(waves) == 10
    first, last = waves[0], waves[-1]
    filed, closed = last[0] - first[0], last[1] - first[1]
    assert filed > closed > 0, (filed, closed)
    assert filed / closed > 1.0, (
        "the file-to-close ratio dropped below 1.0 — the open count is now "
        "falling, and § 1 of SHIP-LINE.md needs rewriting rather than patching")
    assert (last[1] / last[0]) > (first[1] / first[0])          # done % converges
    assert (last[0] - last[1]) > (first[0] - first[1])          # open count diverges


def test_repeated_progress_headlines_are_not_counted_as_waves():
    """Five consecutive entries read `382 tracked, 190 done`. Counting those as
    waves halves the apparent rate, which is how two different 'rows closed per
    wave' figures can both be derived from this file.

    Driven on a synthetic series, because the ten newest real entries happen to
    be distinct — so a `distinct_waves` that collapsed nothing would look right
    on today's tracker and be wrong the moment a wave restates the totals.
    """
    series = [(9, 9), (9, 9), (9, 9), (8, 7), (8, 7), (7, 5), (4, 1)]  # newest first
    assert sl.distinct_waves(series, 4) == [(4, 1), (7, 5), (8, 7), (9, 9)]
    assert sl.distinct_waves(series, 2) == [(8, 7), (9, 9)]
    # …and it is what § 1's "110 headlines, 10 moved the totals" is computed from.
    real = sl.trend(TRACKER_TEXT)
    waves = sl.distinct_waves(real, 10)
    assert len(real) > len(waves)
    assert all(a != b for a, b in zip(waves, waves[1:]))


# --- the register says what the proposal says ------------------------------

def test_every_registered_row_exists_and_every_blocking_row_is_open():
    ids = {r.id: r for r in ROWS}
    for rid, (verdict, _cls) in REGISTER.items():
        assert rid in ids, f"{rid} is registered and is not a row"
        if verdict == "blocking":
            assert ids[rid].open, f"{rid} is named blocking and is ticked"


def test_the_blocking_set_is_the_size_the_proposal_states():
    blocking = [r for r in ROWS
                if r.open and REGISTER.get(r.id, ("", ""))[0] == "blocking"]
    landed = [rid for rid, (v, _c) in REGISTER.items() if v == "landed"]
    body = PROPOSAL.read_text(encoding="utf-8")
    # `B522`. This pinned `15` and went red the day `P0-17` and `P6-08` closed —
    # two of the gates being *met*, which is the only direction this number is
    # supposed to move. Sixth instance of the shape `B520` names. The durable
    # claim is that the document and the register agree, whatever the number is:
    # a line whose prose and whose machine-readable half disagree is worse than
    # no line. `landed` rows stay in the register on purpose so a met gate can be
    # audited rather than quietly vanishing.
    stated = re.search(r"§?\s*3\.? The blocking set — (\w+) rows", body)
    assert stated, "§ 3's heading no longer states a count"
    words = {"ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
             "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18}
    assert words[stated.group(1)] == len(blocking) + len(landed), (
        f"§ 3 says {stated.group(1)} and the register holds {len(blocking)} blocking "
        f"+ {len(landed)} landed")
    body = PROPOSAL.read_text(encoding="utf-8").lower()
    assert "fourteen" not in body.split("## 3.")[1].split("## 4.")[0], (
        "§ 3 still says fourteen somewhere — a count carried forward rather than "
        "recomputed is the defect `B44` is named after")


def test_the_blocking_set_is_mostly_security_licence_and_claim():
    """The shape of the answer, not just its size. If a later wave makes this
    mostly feature rows, the line has been stretched and § 2 needs rewriting."""
    classes = [REGISTER[r.id][1] for r in ROWS
               if r.open and REGISTER.get(r.id, ("", ""))[0] == "blocking"]
    hard = sum(1 for c in classes if c in {"security", "licence", "claim"})
    assert hard >= len(classes) * 0.6, classes


def test_almost_nothing_recently_filed_is_a_gate():
    """The convergence argument, computed. Not *we will stop finding things* —
    that is false and the trend says so — but *almost nothing we find is a
    gate*, which is what makes a growing open count survivable."""
    recent = sorted((r for r in ROWS if r.id.startswith("B")),
                    key=lambda r: int(r.id[1:]))[-40:]
    gates = [r.id for r in recent if REGISTER.get(r.id, ("", ""))[0] == "blocking"]
    assert len(gates) <= len(recent) * 0.25, gates
    assert gates, "no recently filed row is a gate — check the register parsed"


# --- the rule ---------------------------------------------------------------

def _row(body: str) -> "sl.Row":
    return sl.parse_rows(body)[0]


# One example per signal, and the example is written so **only that signal**
# can match it. Anything less and a rule of ten overlapping patterns is held up
# by two of them: drop the other eight and every test still passes, because the
# rows they were written for happen to trip something else. Measured — that is
# exactly what the first draft of this file did.
EXAMPLES: dict[str, tuple[str, str]] = {
    # security
    r"unauthenticated": ("security", "served to an unauthenticated port"),
    r"with no cookie": ("security", "answers 200 to a client with no cookie"),
    r"no auth call": ("security", "the handler makes no auth call"),
    r"fail[- ]open": ("security", "the default is fail-open"),
    r"without a session": ("security", "reachable without a session"),
    r"auth boundary": ("security", "an auth boundary with a hole in it"),
    r"require_admin": ("security", "beside a require_admin handler"),
    r"admin-gate": ("security", "admin-gate the read path"),
    r"any logged-in non-admin": ("security", "any logged-in non-admin reads it"),
    r"\bRCE\b": ("security", "it closes a reported RCE"),
    r"privilege": ("security", "the privilege defaults to granted"),
    r"plain text": ("security", "the tokens are plain text at rest"),
    r"plaintext": ("security", "stored plaintext at rest"),
    r"not encrypted": ("security", "the column is not encrypted"),
    r"secret grep": ("security", "run the secret grep first"),
    r"leak(?:s|ed|ing)? a token": ("security", "the handler leaks a token"),
    r"\bungated\b": ("security", "the route is ungated"),
    r"\bnot gated\b": ("security", "the read path is not gated"),
    r"only \w+ (?:are|is) gated": ("security", "four handlers and only two are gated"),
    r"(?:GET|POST|PUT|DELETE|endpoint|route)s?\b[^.]{0,40}\b(?:are|is) open\b":
        ("security", "both GETs are open"),
    # licence
    r"AGPL": ("licence", "the AGPL obliges it"),
    r"Apache-2\.0": ("licence", "the file is Apache-2.0"),
    r"§\s*13": ("licence", "the §13 link is missing"),
    r"§\s*4\(b\)": ("licence", "the §4(b) stamp is missing"),
    r"§\s*5\(a\)": ("licence", "the §5(a) surface"),
    r"licence obligation": ("licence", "a licence obligation nobody met"),
    r"attribution": ("licence", "the attribution is wrong"),
    r"change notice": ("licence", "eight files carry a change notice"),
    r"(?-i:\bNOTICE\b)": ("licence", "NOTICE gives a different date"),
    r"copyright holder": ("licence", "the copyright holder's own words"),
    # claim
    r"is false": ("claim", "the sentence is false"),
    r"was false": ("claim", "the tick was false"),
    r"false (?:claim|statement|compliance)": ("claim", "a false claim in a document"),
    r"claims? (?:a|an|the)\b[^.]{0,60}\bthat (?:is|are) not":
        ("claim", "it claims a link that is not there"),
    r"misrepresent": ("claim", "shipping it would misrepresent the product"),
    r"never prints": ("claim", "a number its repro never prints"),
    r"does not reproduce": ("claim", "the figure does not reproduce"),
    r"unreachable code": ("claim", "the env leg is unreachable code"),
    r"stated? both": ("claim", "the page stated both dates"),
    r"nobody has confirmed": ("claim", "a setting nobody has confirmed"),
    r"dead end": ("claim", "the reporter is at a dead end"),
    r"tick withdrawn": ("claim", "tick withdrawn on measurement"),
    # first-ten
    r"first[- ]time user": ("first-ten", "a first-time user hits it"),
    r"silently (?:invisible|discarded|stor)": ("first-ten", "silently discarded"),
    r"no refusal, no reason": ("first-ten", "no refusal, no reason"),
    r"stores its zip bytes": ("first-ten", "it stores its zip bytes"),
    r"looks like a corrupt file": ("first-ten", "it looks like a corrupt file"),
    r"without a login": ("first-ten", "it answers without a login"),
    r"first ten minutes": ("first-ten", "inside the first ten minutes"),
    # supply
    r"advisor(?:y|ies)": ("supply", "nine open advisories"),
    r"\bCRITICAL\b": ("supply", "one of them CRITICAL"),
    r"\bunpinned\b": ("supply", "an unpinned resolve at runtime"),
    r"hash-pinned": ("supply", "no hash-pinned lock exists"),
}


def test_every_signal_in_the_rule_has_an_example():
    declared = {p for pats in sl.SIGNALS.values() for p in pats}
    assert declared == set(EXAMPLES), {
        "signals with no example": sorted(declared - set(EXAMPLES)),
        "examples for signals that are gone": sorted(set(EXAMPLES) - declared),
    }


@pytest.mark.parametrize("pattern", sorted(EXAMPLES))
def test_each_signal_flags_its_own_example_and_nothing_else_does(pattern):
    group, text = EXAMPLES[pattern]
    row = _row(f"- [ ] **B900** {text}.")
    cand, why = sl.triage(row)
    assert cand and why == [group], (cand, why)
    others = [p for p in sl.SIGNALS[group] if p != pattern]
    assert not any(re.search(p, row.body, re.I) for p in others), (
        f"{text!r} is matched by more than one signal in {group!r}, so dropping "
        f"{pattern!r} would not fail this test")


# `P10-12` is the known miss and § 6 of the proposal says so: it is the absence
# of an artefact — "write the release notes" — and no prose signal can find an
# absence. It is registered by hand. Every other gate has to be reachable by the
# rule, or a row filed tomorrow with the same shape is never offered for review.
RULE_CANNOT_SEE = {"P10-12"}


def test_the_rule_reaches_every_blocking_row_it_claims_to():
    """The recall claim in § 6, measured rather than asserted.

    Without this, the register carries the whole ship line and the rule carries
    none of it — and the mechanism is only worth what the rule's recall is worth,
    because `--check` never asks about a row the rule calls clear.
    """
    blocking = [r for r in ROWS
                if r.open and REGISTER.get(r.id, ("", ""))[0] == "blocking"]
    missed = sorted(r.id for r in blocking if not sl.triage(r)[0])
    assert set(missed) <= RULE_CANNOT_SEE, (
        f"the rule no longer reaches {sorted(set(missed) - RULE_CANNOT_SEE)}. "
        f"A gate the rule cannot see is a gate nobody is asked about."
    )
    # `B522`. Was `== 14`, i.e. "all but one of fifteen". The claim is the recall
    # of the rule, not an absolute: at most one blocking row may be invisible to
    # it, and the one that is must be named in the document.
    assert len(missed) <= 1, (len(blocking), missed)


def test_the_rule_clears_an_ordinary_tidiness_row():
    cand, why = sl.triage(_row(
        "- [ ] **B905** Collapse the seven hand-styled chips into one component "
        "so the strip is themeable. `Law 13`."))
    assert not cand, why


def test_the_rule_reads_the_indented_correction_not_just_the_first_line():
    """`B421` reads as a shipped CRITICAL advisory on its first line and is not.
    A rule that stops at the row line classifies it wrongly and, worse, does so
    confidently."""
    body = ("- [ ] **B906** Split the bundle into three published files.\n"
            "  The twenty-seven advisories are measured unreachable.\n")
    row = _row(body)
    assert "unreachable" in row.body
    assert sl.triage(row)[0]


# --- the ratchet ------------------------------------------------------------

SYNTHETIC = (
    "# Bugs found during implementation\n\n"
    "- [ ] **B907** A route answers 200 to a client with no cookie.\n"
    "- [ ] **B908** Rename a constant for tidiness.\n"
)


def test_an_unclassified_candidate_fails_the_check(capsys):
    """The mechanism. A row filed tomorrow with a gate's signal and no verdict
    is named, by id, and the check exits non-zero."""
    rows = sl.parse_rows(SYNTHETIC)
    assert sl.check(rows, {}) == 1
    assert "B907: unclassified" in capsys.readouterr().out


def test_a_classified_candidate_passes_and_a_clear_row_needs_no_entry(capsys):
    rows = sl.parse_rows(SYNTHETIC)
    assert sl.check(rows, {"B907": ("blocking", "security")}) == 0
    assert "ship line OK" in capsys.readouterr().out


def test_a_blocking_row_that_got_ticked_fails_the_check(capsys):
    rows = sl.parse_rows("# X\n\n- [x] **B909** Done now.\n")
    assert sl.check(rows, {"B909": ("blocking", "security")}) == 1
    assert "named blocking and is now ticked" in capsys.readouterr().out


def test_a_registered_row_that_left_the_tracker_fails_the_check(capsys):
    assert sl.check([], {"B910": ("tracked", "tidy")}) == 1
    assert "not in the tracker" in capsys.readouterr().out


def test_the_real_tree_is_green():
    assert sl.check(ROWS, REGISTER) == 0


def test_the_proposal_is_not_wired_as_a_gate_yet():
    """It is a proposal. `release-gate.py` globs `.pantheon/check-*.py`; this
    file is not named that, and adopting the line is the rename. A red answer
    must not block anybody's merge before the owner has ruled."""
    assert not (ROOT / ".pantheon" / "check-ship-line.py").exists()
    assert (ROOT / ".pantheon" / "ship-line.py").exists()
