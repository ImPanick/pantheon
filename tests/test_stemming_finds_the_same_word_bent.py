# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B62` — a question asked in the tense people use must find the memory.

Found by `P13-13`'s golden set on its first run, which is that row justifying
its own existence. Neither engine reduced a word to its stem, so **`what do I
drive` returned nothing for "User drives a diesel van"** — a probe written as an
*easy control* both engines should pass — and **`any allergies` returned nothing
for "User is allergic to shellfish"**, the highest-stakes memory in the corpus.

`Law 16` decided the implementation: no model, no network, no downloaded corpus.
Porter's algorithm is suffix rules with no data behind it, so it is written out
in `src/text_stemmer.py` rather than depended on.

The measured result on the shipped fixture: **recall@5 0.63 → 0.77, MRR 0.633 →
0.767.** Four more probes answered out of thirty.
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest

from src import memory_retrieval, text_stemmer
from src.memory import MemoryManager

_REPO = Path(__file__).resolve().parents[1]
_EVAL = _REPO / ".pantheon" / "retrieval_eval.py"

sys.path.insert(0, str(_REPO / ".pantheon"))
import retrieval_eval  # noqa: E402


def _manager():
    return MemoryManager.__new__(MemoryManager)


# ── the two misses that filed the row ─────────────────────────────────────────


def test_a_question_in_the_wrong_tense_finds_the_memory():
    """`what do I drive` against "User **drives** a diesel van". One character.
    The probe was written as an easy control and it failed, which is how the row
    got filed."""
    rows = [{"id": "van", "text": "User drives a diesel van for site visits.",
             "timestamp": 1735689600},
            {"id": "cat", "text": "User's cat is called Bramble and is fifteen.",
             "timestamp": 1735689600}]
    found = [m["id"] for m in _manager().get_relevant_memories("what do I drive", rows, max_items=5)]
    assert found[:1] == ["van"]


def test_the_allergy_miss_is_honestly_still_a_miss():
    """And the one stemming does **not** fix, stated as a test rather than left
    as a hope.

    `drive`/`drives` differ by *inflection* — the same word bent for grammar.
    `allergies`/`allergic` differ by *derivation* — a noun and an adjective built
    from a shared root — and Porter is an inflectional stemmer by design.
    Collapsing derivations means over-stemming, which trades false negatives for
    false positives.

    So this is a **semantic** miss wearing a lexical costume, and `P13-16` is
    what answers it. Pinning it here stops the next person assuming the stemmer
    covers it, and turns green the day two-stage retrieval lands."""
    assert text_stemmer.stem("allergies") == "allergi"
    assert text_stemmer.stem("allergic") == "allerg"
    assert text_stemmer.stem("allergies") != text_stemmer.stem("allergic")


# ── the algorithm, against its own published vocabulary ───────────────────────


@pytest.mark.parametrize("word, expected", [
    # Porter's own test vocabulary, one case per rule that matters here.
    ("caresses", "caress"), ("ponies", "poni"), ("cats", "cat"),
    ("feed", "feed"), ("agreed", "agre"), ("plastered", "plaster"),
    ("motoring", "motor"), ("sing", "sing"), ("conflated", "conflat"),
    ("troubled", "troubl"), ("hopping", "hop"), ("tanned", "tan"),
    ("falling", "fall"), ("hissing", "hiss"), ("failing", "fail"),
    ("filing", "file"), ("happy", "happi"), ("sky", "sky"),
    ("relational", "relat"), ("conditional", "condit"), ("rational", "ration"),
    ("digitizer", "digit"), ("vietnamization", "vietnam"), ("operator", "oper"),
    ("feudalism", "feudal"), ("decisiveness", "decis"), ("hopefulness", "hope"),
    ("callousness", "callous"), ("formaliti", "formal"), ("sensibiliti", "sensibl"),
    ("triplicate", "triplic"), ("formative", "form"), ("formalize", "formal"),
    ("electricit i".replace(" ", ""), "electr"), ("electrical", "electr"),
    ("hopeful", "hope"), ("goodness", "good"), ("revival", "reviv"),
    ("allowance", "allow"), ("inference", "infer"), ("gyroscopic", "gyroscop"),
    ("adjustable", "adjust"), ("defensible", "defens"), ("irritant", "irrit"),
    ("replacement", "replac"), ("adjustment", "adjust"), ("dependent", "depend"),
    ("adoption", "adopt"), ("communism", "commun"), ("activate", "activ"),
    ("effective", "effect"), ("bowdlerize", "bowdler"),
])
def test_the_algorithm_matches_its_published_vocabulary(word, expected):
    # A hand-written stemmer is easy to get subtly wrong, and wrong here is
    # invisible: it does not crash, it just quietly stops matching. Porter
    # published a test vocabulary precisely so nobody has to trust a
    # reimplementation, and this is it.
    assert text_stemmer.stem(word) == expected


@pytest.mark.parametrize("word, expected, rule", [
    # One case per rule that Porter's published vocabulary does not separate.
    # Every one of these was found by mutation testing: the rule was deleted,
    # the suite stayed green, and a discriminating word had to be searched for
    # rather than guessed. A rule no input can distinguish is a rule that can be
    # deleted for free, which is the same argument as `P13-14`'s `cutoff`.
    ("witnesses", "wit", "step 1a -sses; without it `witnesses` stops at `witness`"),
    ("businesses", "busi", "the same rule on a word people actually type"),
    ("flies", "fli", "step 1a -ies; without it `flies` keeps a trailing e"),
    ("tries", "tri", "and `tries` never meets `try`"),
    ("stabilized", "stabil", "step 1b restores the e after -iz, or `stabiliz` never meets `stabilize`"),
    ("controlled", "control", "step 5b un-doubles a final l; `controlling` and `controlled` must agree"),
    ("travelled", "travel", "the British spelling is the one that proves 5b earns its place"),
    ("gypsy", "gypsi", "y after a consonant is a vowel, so step 1c does not fire"),
    ("dryly", "dryli", "and the same word with a suffix still resolves the y correctly"),
    ("employer", "employ", "y after a vowel is a consonant, which is what makes `employ` a stem"),
    ("fixing", "fix", "the cvc test excludes w, x and y — otherwise `fix` becomes `fixe`"),
    ("saying", "sai", "and `saying` becomes `saye`, which matches nothing"),
])
def test_the_rules_the_published_vocabulary_does_not_separate(word, expected, rule):
    assert text_stemmer.stem(word) == expected, rule


@pytest.mark.parametrize("word", ["toy", "boy", "day", "say", "sky"])
def test_a_three_letter_word_is_left_alone(word):
    # `_MIN_LENGTH`. Below four characters the rules start destroying rather
    # than reducing: `toy` becomes `toi` and `day` becomes `dai`, neither of
    # which matches anything a person would write. Porter has no such guard
    # because it was built for document indexing where that is harmless; here it
    # is a token that matches nothing.
    assert text_stemmer.stem(word) == word


@pytest.mark.parametrize("word", ["rate", "cease", "roll", "sky", "news"])
def test_short_and_awkward_words_are_not_destroyed(word):
    # The rules start destroying rather than reducing below four characters, and
    # `m` is what keeps `-ate` off `rate` while allowing it off `derivate`.
    out = text_stemmer.stem(word)
    assert len(out) >= 3, f"{word} was reduced to a fragment: {out!r}"


def test_a_stem_is_never_handed_back_as_a_fragment():
    # A two-letter stem matches half a corpus. Whatever the rules produce, a
    # result shorter than three characters is discarded in favour of the word.
    for word in ["ties", "ties", "ails", "eyes", "ages", "axes", "ices"]:
        assert len(text_stemmer.stem(word)) >= 3


def test_the_stemmer_reaches_no_network_and_loads_no_data():
    """`Law 16`. The reason this is written out rather than depended on: `nltk`
    downloads corpora on first use and every lemmatiser worth the name carries a
    model. Porter is rules with nothing behind them, so the module imports
    nothing at all."""
    source = (_REPO / "src" / "text_stemmer.py").read_text(encoding="utf-8")
    code = "\n".join(ln for ln in source.splitlines()
                     if not ln.lstrip().startswith("#") and '"""' not in ln)
    imports = re.findall(r"^\s*(?:import|from)\s+(\S+)", code, re.M)
    assert imports == ["__future__"], f"the stemmer grew a dependency: {imports}"


# ── it is applied to both sides, or it makes things worse ─────────────────────


def test_the_query_and_the_corpus_are_reduced_by_the_same_rules():
    # A stemmed query against unstemmed memories matches *less* than either
    # alone, so this is the one property that must never drift.
    assert memory_retrieval.content_tokens("drives") == memory_retrieval.content_tokens("driving")
    assert text_stemmer.stem("drives") in memory_retrieval.content_tokens("User drives a van")
    assert set(memory_retrieval.content_tokens("what do I drive")) <= set(
        memory_retrieval.content_tokens("User drives a diesel van")), \
        "the query's words must land in the memory's own token set after stemming"


def test_stopwords_are_filtered_on_both_sides_of_the_stemmer():
    """Both passes earn their place. Filtering *before* stops `does` being bent
    into `doe` and escaping the list; filtering *after* catches inflected forms
    the list does not carry — `having` is not in it, `have` is, and stemming is
    what connects them."""
    assert "doe" not in memory_retrieval.content_tokens("does it work")
    assert "have" not in memory_retrieval.content_tokens("having a look")
    assert memory_retrieval.content_tokens("having") == []


def test_a_real_word_still_survives_the_double_filter():
    # The negative control: if the second pass were too eager it would strip
    # content words whose stems happen to look common.
    assert memory_retrieval.content_tokens("deploying the certificate") == [
        text_stemmer.stem("deploying"), text_stemmer.stem("certificate")]


# ── the number, which is the row's whole justification ────────────────────────


def test_stemming_measurably_improved_retrieval():
    """`Law 9`. The row is ticked on a measurement, not on the observation that
    stemming is obviously good. Before: recall@5 0.63, MRR 0.633. After: 0.77
    and 0.767 — four more probes out of thirty."""
    corpus = retrieval_eval._load(_EVAL.parent / "fixtures" / "retrieval_probe.json")
    out = retrieval_eval.score(corpus, retrieval_eval.ENGINES["manager"](corpus, 5), 5)
    assert out["recall@5"] >= 0.76, f"stemming's gain has been lost: {out['recall@5']:.2f}"
    assert out["mrr"] >= 0.75, f"stemming's ranking gain has been lost: {out['mrr']:.3f}"


def test_what_is_left_is_semantic_and_nothing_lexical_will_fix_it():
    """The honest end of the lexical road, and the reason `P13-16` is the next
    row rather than a better tokenizer.

    Every surviving miss needs meaning, not spelling: `who am i` has no content
    words at all; `can I eat prawns`, `any allergies` and `what should I know
    about food` are three different routes to "allergic to shellfish" sharing no
    token with it; `meeting at half eight` needs to know that is before ten; and
    `what motorbike` needs to know a Moto Guzzi is one."""
    corpus = retrieval_eval._load(_EVAL.parent / "fixtures" / "retrieval_probe.json")
    out = retrieval_eval.score(corpus, retrieval_eval.ENGINES["manager"](corpus, 5), 5)
    missed = {m["query"] for m in out["misses"]}
    for query in ["who am i", "can I eat prawns", "any allergies"]:
        assert query in missed, (
            f"{query!r} now passes — if that is real, this test and `P13-16`'s "
            "premise both need re-deriving rather than deleting")
    for miss in out["misses"]:
        shared = set(memory_retrieval.content_tokens(miss["query"])) & set(
            memory_retrieval.content_tokens(
                next(m["text"] for m in corpus["memories"] if m["id"] in miss["expect"])))
        assert not shared, (
            f"{miss['query']!r} shares {shared} with its answer — that is a lexical "
            "miss and stemming was supposed to have taken it")


def test_the_eval_runs_clean_end_to_end():
    proc = subprocess.run([sys.executable, str(_EVAL)], capture_output=True,
                          text=True, cwd=str(_REPO), timeout=180)
    assert proc.returncode == 0, proc.stderr
    assert "recall@5" in proc.stdout
