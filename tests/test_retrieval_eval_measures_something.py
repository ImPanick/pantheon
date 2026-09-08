# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P13-13` — the golden set, and the harness that scores it.

`P14-02` records `asked` and `returned` per search. *Returned 5* is not
*returned the right 5*, so before this there was no number anywhere that could
tell one retrieval engine from another, and `P13-14` would have shipped on the
claim that BM25 is obviously better than Jaccard — an adjective, which `Law 9`
does not accept as evidence.

These tests are about the scorer, not about retrieval. A scorer that reports
a good number for a bad engine is worse than no scorer, so the harness is
checked against engines whose answers are known in advance.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_EVAL = _REPO / ".pantheon" / "retrieval_eval.py"
_FIXTURE = _REPO / ".pantheon" / "fixtures" / "retrieval_probe.json"

sys.path.insert(0, str(_REPO / ".pantheon"))
import retrieval_eval  # noqa: E402


def _corpus():
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


# ── the scorer, against answers known in advance ──────────────────────────────


def _tiny():
    return {
        "provenance": "fixture",
        "memories": [{"id": "a", "text": "one"}, {"id": "b", "text": "two"},
                     {"id": "c", "text": "three"}],
        "probes": [{"query": "q1", "expect": ["a"]}, {"query": "q2", "expect": ["b"]}],
    }


def test_a_perfect_engine_scores_one_on_both_metrics():
    ranked = {"q1": ["a", "b", "c"], "q2": ["b", "a", "c"]}
    out = retrieval_eval.score(_tiny(), ranked, k=5)
    assert out["recall@5"] == 1.0
    assert out["mrr"] == 1.0


def test_an_engine_that_returns_nothing_scores_zero():
    out = retrieval_eval.score(_tiny(), {"q1": [], "q2": []}, k=5)
    assert out["recall@5"] == 0.0
    assert out["mrr"] == 0.0
    assert len(out["misses"]) == 2


def test_recall_and_mrr_disagree_on_purpose():
    # The reason both are reported. An engine that is always right at rank 5
    # scores a perfect recall@5 and 0.2 on MRR, and memory is injected under a
    # slot limit — so rank is not cosmetic and a single number would hide it.
    ranked = {"q1": ["x", "y", "z", "w", "a"], "q2": ["x", "y", "z", "w", "b"]}
    out = retrieval_eval.score(_tiny(), ranked, k=5)
    assert out["recall@5"] == 1.0
    assert out["mrr"] == pytest.approx(0.2)


def test_k_actually_cuts_off():
    ranked = {"q1": ["x", "y", "a"], "q2": ["x", "y", "b"]}
    assert retrieval_eval.score(_tiny(), ranked, k=3)["recall@3"] == 1.0
    assert retrieval_eval.score(_tiny(), ranked, k=2)["recall@2"] == 0.0


def test_a_miss_records_where_it_did_land():
    # Rank 9 is a ranking problem; absent entirely is a recall problem. They
    # are fixed differently, so a miss that does not say which is a miss you
    # cannot act on.
    ranked = {"q1": ["x", "y", "z", "w", "v", "a"], "q2": ["b"]}
    misses = retrieval_eval.score(_tiny(), ranked, k=3)["misses"]
    assert [m["found_at"] for m in misses] == [6]


# ── the corpus itself ─────────────────────────────────────────────────────────


def test_every_probe_expects_a_memory_that_exists():
    # A probe expecting an id nothing carries is a probe that can never pass,
    # and it would drag the score down forever while looking like an engine
    # failure. `_load` refuses it; this proves the shipped file is clean.
    retrieval_eval._load(_FIXTURE)


def test_the_fixture_says_it_is_a_fixture():
    # The whole honesty argument. A number computed over hand-written probes is
    # a fact about whoever wrote them, and `P13-13` says so in as many words:
    # pairs written from imagination test the imagination. Only `curated`
    # supports a claim about how well this product remembers.
    corpus = _corpus()
    assert corpus["provenance"] == "fixture"
    assert "not a measurement" in corpus["note"].lower()


def test_every_probe_says_why_it_is_in_the_file():
    # Without this the corpus rots into a list of strings nobody dares change,
    # because no one can tell a deliberate hard case from a typo.
    for probe in _corpus()["probes"]:
        assert probe.get("why", "").strip(), f"{probe['query']!r} does not say why"


def test_the_corpus_is_big_enough_for_a_percentage_to_mean_anything():
    corpus = _corpus()
    assert len(corpus["probes"]) >= 30, "fewer than 30 probes and one miss moves the number 3%"
    assert len(corpus["memories"]) >= 20, "a corpus that small makes IDF meaningless"


def test_the_corpus_contains_the_collisions_the_row_was_filed_about():
    # `P13-11`'s named failures, present as probes rather than as prose. If
    # somebody rewrites this file, these have to survive the rewrite.
    queries = " | ".join(p["query"] for p in _corpus()["probes"])
    assert "do I prefer dark mode" in queries, "P13-11(b), the first-person preference phrasing"
    assert "dark roast" in queries, "the dark-mode/dark-roast collision word overlap cannot separate"


# ── both engines run, over one corpus, and the numbers are real ───────────────


def test_both_engines_can_be_scored_over_the_same_corpus():
    # The comparison `P13-14` rests on. Neither engine gets its own corpus and
    # neither gets a vector service, because the degraded path is the one a
    # person actually meets.
    corpus = _corpus()
    for name, engine in retrieval_eval.ENGINES.items():
        out = retrieval_eval.score(corpus, engine(corpus, 5), 5)
        assert out["n"] == len(corpus["probes"])
        assert 0.0 <= out[f"recall@5"] <= 1.0
        assert 0.0 <= out["mrr"] <= 1.0


def test_no_call_path_is_worse_than_the_scorer_that_was_deleted():
    # The one comparison a deletion owes. `P13-14` removed Jaccard-plus-keyword-
    # lists on the strength of a measurement — 0.40 recall@5 and 0.319 MRR on
    # this corpus — and that number is the floor from here on. It is not a
    # ratchet on an uncalibrated figure (`P3-20`); it is a historical fact about
    # what the product used to do, and "never worse than what we removed" is the
    # claim the deletion rests on.
    corpus = _corpus()
    floor = retrieval_eval.DELETED_SCORER_BASELINE
    for name, engine in retrieval_eval.ENGINES.items():
        out = retrieval_eval.score(corpus, engine(corpus, 5), 5)
        assert out["recall@5"] >= floor["recall"], f"{name} is worse than the deleted scorer"
        assert out["mrr"] >= floor["mrr"], f"{name} ranks worse than the deleted scorer"


def test_both_call_paths_return_the_same_ranking():
    # `P13-14`'s actual property, and the one that would regress. These are two
    # entry points into one scorer now — the Brain and the agent go through
    # `MemoryManager`, the chat preface through `_hybrid_retrieve` — and the day
    # they disagree a second scorer has grown back, which is the defect `Law 13`
    # names and the reason the row existed.
    corpus = _corpus()
    rankings = {name: engine(corpus, 5) for name, engine in retrieval_eval.ENGINES.items()}
    first, *rest = rankings.values()
    for other in rest:
        assert other == first, "the call paths have diverged; a second scorer is back"


def test_the_deletion_actually_improved_things():
    # The measurement that justified `P13-14`, kept as a live assertion rather
    # than as a sentence in a commit message. `Law 9`: the row cannot be ticked
    # on "BM25 is obviously better", which is an adjective.
    corpus = _corpus()
    out = retrieval_eval.score(corpus, retrieval_eval.ENGINES["manager"](corpus, 5), 5)
    floor = retrieval_eval.DELETED_SCORER_BASELINE
    assert out["recall@5"] > floor["recall"], "the replacement is not better, only different"
    assert out["mrr"] > floor["mrr"] * 1.5, "the ranking gain was the larger half of the case"


def test_neither_engine_is_perfect_and_that_is_the_point():
    # A corpus every engine passes measures nothing. These probes were chosen
    # to include cases no lexical scorer can answer — `can I eat prawns` shares
    # not one token with `allergic to shellfish` — so a perfect score here
    # would mean the corpus had been softened, not that retrieval improved.
    corpus = _corpus()
    for name, engine in retrieval_eval.ENGINES.items():
        out = retrieval_eval.score(corpus, engine(corpus, 5), 5)
        assert out["recall@5"] < 1.0, f"{name} scores perfectly — the corpus has gone soft"


# ── the command a person runs ─────────────────────────────────────────────────


def _run(*args):
    proc = subprocess.run([sys.executable, str(_EVAL), *args],
                          capture_output=True, text=True, cwd=str(_REPO), timeout=180)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def test_the_report_names_its_provenance_before_it_names_a_number():
    # A reader who sees `recall@5 0.63` and not the word `fixture` will quote
    # the number. The header exists so that cannot happen by accident.
    out = _run()
    assert "provenance: fixture" in out
    assert out.index("provenance") < out.index("recall@5")


def test_it_is_a_report_and_never_a_gate():
    # A ratchet on a number nobody has calibrated is `P3-20`'s mistake. The
    # first honest thing to know is what today's number even is.
    proc = subprocess.run([sys.executable, str(_EVAL)], capture_output=True,
                          text=True, cwd=str(_REPO), timeout=180)
    assert proc.returncode == 0


def test_json_output_is_machine_readable_and_carries_provenance():
    payload = json.loads(_run("--json"))
    assert payload["provenance"] == "fixture"
    assert set(payload["results"]) == set(retrieval_eval.ENGINES)


def test_generate_marks_its_output_as_unchecked():
    # The trap this closes: a generated corpus that looks curated. Every query
    # says REWRITE ME because a template cannot guess how a person asks, and
    # the provenance says `generated`, which the report renders as "not yet
    # checked by a person".
    memories = [{"id": "m1", "text": "User's name is Felix.", "category": "identity"}]
    drafted = retrieval_eval._generate.__wrapped__(memories) if hasattr(
        retrieval_eval._generate, "__wrapped__") else None
    if drafted is None:
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump(memories, fh)
            path = Path(fh.name)
        drafted = retrieval_eval._generate(path)
        path.unlink()
    assert drafted["provenance"] == "generated"
    assert all("REWRITE ME" in p["query"] for p in drafted["probes"])
    assert retrieval_eval.PROVENANCE_NOTE["generated"].startswith("machine-drafted")
