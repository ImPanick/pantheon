# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1933`. The fallback memory extractor stored the rest of the sentence as the name.

`_fallback_memory_candidates` runs on every extraction pass, beside the model,
and caught "my name is X" and "call me X" with a greedy pattern that allowed
spaces and periods, so the name ran on to the last word boundary within 51
characters. "Hi, my name is Felix and I work at Acme. Can you help me plan a
trip?" was stored as "User's name is Felix and I work at Acme. Can you help me
plan a". A fallback fact skips quote verification and is committed by default;
an identity fact is pinned and core, so the run-on went into every later
prompt, and deduplication kept it beside the model's clean fact.

Now the name ends where the name does: where the clause goes on (*and*, *but*,
*please*), at punctuation or a symbol, or at the end of the line. More than
four words with nothing to stop them is a sentence, not a name, and is dropped
rather than stored. A period after a title or an initial stays part of the
name, so "Dr. Smith" and "J. R. Smith" come out whole. Upstream Odysseus made the capture lazy in a646b591, which ends
"Dr. Smith" at "Dr"; this keeps that fix's clause stop and not its cut.
"""
import pytest

from services.memory.memory_extractor import _fallback_memory_candidates


def _identity(content):
    cands = _fallback_memory_candidates([{"role": "user", "content": content}])
    return [c["text"] for c in cands if c["category"] == "identity"]


@pytest.mark.parametrize("content, fact", [
    ("Hi, my name is Felix and I work at Acme. Can you help me plan a trip?",
     "User's name is Felix"),
    ("my name is Sam. I need a recipe for dinner tonight please", "User's name is Sam"),
    ("call me Bob and help me write a cover letter", "User wants to be called Bob"),
    ("My name is Felix - I work at Acme", "User's name is Felix"),
])
def test_the_name_ends_where_the_sentence_goes_on(content, fact):
    assert _identity(content) == [fact]


def test_a_title_or_an_initial_stays_part_of_the_name():
    assert _identity("my name is J. R. Smith and I am a pilot") == ["User's name is J. R. Smith"]
    assert _identity("My name is Dr. Smith") == ["User's name is Dr. Smith"]
    assert _identity("my name is A.J. Smith") == ["User's name is A.J. Smith"]
    assert _identity("call me Dr. Ruiz, please") == ["User wants to be called Dr. Ruiz"]


def test_a_name_ended_by_punctuation_or_a_symbol_is_kept():
    """The names that already came out right still do, whatever ends them."""
    assert _identity("my name is Felix... anyway") == ["User's name is Felix"]
    assert _identity("My name is Ana Lucia, what is the capital of Peru?") == [
        "User's name is Ana Lucia"]
    assert _identity("My name is Felix: I need help with a letter") == ["User's name is Felix"]
    assert _identity("My name is Felix — I work at Acme") == ["User's name is Felix"]
    assert _identity("my name is Felix (he/him)") == ["User's name is Felix"]
    assert _identity("My name is Felix 😊") == ["User's name is Felix"]
    assert _identity("Just call me Alex.") == ["User wants to be called Alex"]


def test_a_run_on_with_nothing_to_stop_it_is_dropped_not_stored():
    assert _identity("hi my name is felix i need help with my code") == []
