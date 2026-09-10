# SPDX-License-Identifier: AGPL-3.0-or-later
"""
text_stemmer.py

The Porter stemming algorithm, vendored.

`B62`. Found by `P13-13`'s golden set on its first run: neither retrieval engine
reduced a word to its stem, so **`what do I drive` returned nothing for "User
drives a diesel van"** — a probe written as an *easy control* both engines should
pass — and **`any allergies` returned nothing for "User is allergic to
shellfish"**, the highest-stakes memory in the corpus. One character and one
syllable respectively.

`Law 16` decides the implementation. A stemmer must not pull a model or reach a
network, which rules out `nltk` (it downloads corpora on first use) and every
embedding-based lemmatiser. Porter's algorithm is a fixed set of suffix rules
with no data behind it, it was published without restriction and has been
reimplemented thousands of times, and it fits in one file with no imports. So it
is written out here rather than depended on.

**What this fixes and what it does not**, measured rather than assumed:

- `drives` → `drive`, `allergies` → `allergi`, `allergic` → `allerg`.
- So the first miss is fixed and **the second is not**, and the reason is worth
  keeping: `drive`/`drives` differ by *inflection* — the same word, bent for
  grammar — while `allergies`/`allergic` differ by *derivation*, a noun and an
  adjective built from a shared root. Porter is an inflectional stemmer by
  design; making it collapse derivations means over-stemming, which trades false
  negatives for false positives, and the golden set is how that trade gets
  judged rather than argued about.
- The honest conclusion is that `any allergies` is a **semantic** miss wearing a
  lexical costume, and `P13-16` is what answers it.

Reference: M.F. Porter, "An algorithm for suffix stripping", Program 14(3),
1980, pp. 130-137.
"""

from __future__ import annotations

_VOWELS = frozenset("aeiou")

# Below this length Porter does nothing useful and starts destroying words —
# "ties" would become "ti". The original algorithm has no such guard because it
# was written for document indexing where that collision is harmless; here a
# two-letter stem would match half the corpus.
_MIN_LENGTH = 4


def _is_consonant(word: str, i: int) -> bool:
    """`y` is the awkward one: a consonant after a vowel, a vowel after a
    consonant. In "toy" the consonants are t and y; in "syzygy", s, z and g."""
    ch = word[i]
    if ch in _VOWELS:
        return False
    if ch != "y":
        return True
    return i == 0 or not _is_consonant(word, i - 1)


def _measure(stem: str) -> int:
    """Porter's `m`: how many vowel-consonant pairs the stem contains.

    The whole algorithm is gated on this. `m` is a crude proxy for "is this a
    real word or a fragment", and it is what stops `-ate` being stripped from
    `rate` while allowing it off `derivate`.
    """
    m, i, n = 0, 0, len(stem)
    while i < n and _is_consonant(stem, i):
        i += 1
    while i < n:
        while i < n and not _is_consonant(stem, i):
            i += 1
        if i >= n:
            break
        m += 1
        while i < n and _is_consonant(stem, i):
            i += 1
    return m


def _has_vowel(stem: str) -> bool:
    return any(not _is_consonant(stem, i) for i in range(len(stem)))


def _double_consonant_end(stem: str) -> bool:
    return (len(stem) >= 2 and stem[-1] == stem[-2]
            and _is_consonant(stem, len(stem) - 1))


def _cvc_end(stem: str) -> bool:
    """Ends consonant-vowel-consonant where the last is not w, x or y.

    This is the test that keeps `hop` from becoming `hopE` while letting `fil`
    become `file`.
    """
    n = len(stem)
    if n < 3:
        return False
    if not (_is_consonant(stem, n - 3) and not _is_consonant(stem, n - 2)
            and _is_consonant(stem, n - 1)):
        return False
    return stem[-1] not in "wxy"


def _replace(word: str, suffix: str, replacement: str, min_measure: int | None) -> str | None:
    """Swap `suffix` for `replacement` when the *remaining stem* clears `m`."""
    if not word.endswith(suffix):
        return None
    stem = word[: len(word) - len(suffix)]
    if min_measure is not None and _measure(stem) <= min_measure:
        return None
    return stem + replacement


_STEP2 = (
    ("ational", "ate"), ("tional", "tion"), ("enci", "ence"), ("anci", "ance"),
    ("izer", "ize"), ("abli", "able"), ("alli", "al"), ("entli", "ent"),
    ("eli", "e"), ("ousli", "ous"), ("ization", "ize"), ("ation", "ate"),
    ("ator", "ate"), ("alism", "al"), ("iveness", "ive"), ("fulness", "ful"),
    ("ousness", "ous"), ("aliti", "al"), ("iviti", "ive"), ("biliti", "ble"),
)

_STEP3 = (
    ("icate", "ic"), ("ative", ""), ("alize", "al"), ("iciti", "ic"),
    ("ical", "ic"), ("ful", ""), ("ness", ""),
)

_STEP4 = (
    "al", "ance", "ence", "er", "ic", "able", "ible", "ant", "ement",
    "ment", "ent", "ou", "ism", "ate", "iti", "ous", "ive", "ize",
)


def _step1a(word: str) -> str:
    if word.endswith("sses"):
        return word[:-2]
    if word.endswith("ies"):
        return word[:-2]
    if word.endswith("ss"):
        return word
    if word.endswith("s"):
        return word[:-1]
    return word


def _step1b(word: str) -> str:
    if word.endswith("eed"):
        return word[:-1] if _measure(word[:-3]) > 0 else word
    for suffix in ("ed", "ing"):
        if word.endswith(suffix):
            stem = word[: -len(suffix)]
            if not _has_vowel(stem):
                continue
            if stem.endswith(("at", "bl", "iz")):
                return stem + "e"
            if _double_consonant_end(stem) and not stem.endswith(("l", "s", "z")):
                return stem[:-1]
            if _measure(stem) == 1 and _cvc_end(stem):
                return stem + "e"
            return stem
    return word


def _step1c(word: str) -> str:
    if word.endswith("y") and _has_vowel(word[:-1]):
        return word[:-1] + "i"
    return word


def _step_table(word: str, table, min_measure: int) -> str:
    for suffix, replacement in table:
        out = _replace(word, suffix, replacement, min_measure)
        if out is not None:
            return out
    return word


def _step4(word: str) -> str:
    for suffix in _STEP4:
        out = _replace(word, suffix, "", 1)
        if out is not None:
            return out
    if word.endswith("ion"):
        stem = word[:-3]
        if _measure(stem) > 1 and stem.endswith(("s", "t")):
            return stem
    return word


def _step5(word: str) -> str:
    if word.endswith("e"):
        stem = word[:-1]
        m = _measure(stem)
        if m > 1 or (m == 1 and not _cvc_end(stem)):
            word = stem
    if _measure(word) > 1 and _double_consonant_end(word) and word.endswith("l"):
        word = word[:-1]
    return word


def stem(word: str) -> str:
    """The Porter stem of one lowercase word.

    Short words are returned untouched: below four characters the rules start
    destroying rather than reducing, and a two-letter stem matches half a corpus.
    """
    word = (word or "").lower()
    if len(word) < _MIN_LENGTH:
        return word
    out = _step5(_step4(_step_table(
        _step_table(_step1c(_step1b(_step1a(word))), _STEP2, 0), _STEP3, 0)))
    # Never hand back a fragment. A stem shorter than three characters is a
    # collision waiting to happen and the original word is the safer answer.
    return out if len(out) >= 3 else word
