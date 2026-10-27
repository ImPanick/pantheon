# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P13-18`, `P13-19`, `P13-20` — the Brain's account of the reading, the register and humour.

The three rows were done on the server on 2026-09-19 *"except the Brain's
account of it"*, and folded into `B820`. `B820`'s *How you write* panel
(`static/js/memory.js` `renderStylePanel`) drew the profile — `P13-17` — and
nothing else. Measured on `2760dbe1`: the panel never said that a conversation
is compared with the profile (`P13-18`), what that comparison may change and
that a chosen persona beats it (`P13-19`), or what this person's jokes have been
learned to mean (`P13-20`) — and that association is **stored** on the style
record, so it was a part of the profile nobody could see, which is the one
thing `D-2026-09-09-01` forbids (*"a profile you cannot see is a profile you
cannot correct"*).

Now `GET /api/memory`'s `style.profile` carries `reading` (`memory_style.
reading_account`) and `humour.sentence` (`humour_account`), written beside the
rules they describe, and the panel prints both; *Forget how I write* says it
takes the jokes' meaning too. The reading itself is still never stored or
shown — there is nothing of it to correct, only to understand.

Driven (`Law 20`): the real `GET /api/memory` handler over a real
`MemoryManager` in a temp directory, taught the way the chat teaches it
(`record_style_observation`); the panel half is driven under node in
`tests/test_the_brain_shows_how_you_write_js.py`.
"""
from __future__ import annotations

import pytest

from src import memory_style as ms
from src.memory import MemoryManager
from test_the_assistant_learns_how_you_talk import FORMAL, TERSE_SWEARER, _routes


@pytest.fixture
def manager(tmp_path):
    return MemoryManager(str(tmp_path))


def _style(manager, monkeypatch):
    return _routes(manager, monkeypatch)[("GET", "/api/memory")](request=None)["style"]


def _formed(manager, text=FORMAL):
    for _ in range(ms.PROFILE_MIN_MESSAGES):
        manager.record_style_observation(text, owner="felix")


def test_the_reading_is_explained_beside_the_profile_and_is_not_itself_there(manager, monkeypatch):
    """`P13-18` / `P13-19`: what a conversation is compared with the profile
    for, which observables count, and what they may change — and the reading
    is not a field (it is never stored)."""
    _formed(manager)
    profile = _style(manager, monkeypatch)["profile"]
    said = profile["reading"]
    assert f"last {ms.READING_WINDOW} messages are compared with this" in said
    for signal in ms.SIGNALS:
        assert signal.replace("_", " ") in said, signal
    assert "replies get shorter" in said and "instead of asking" in said
    assert "never changes what is true" in said and "not saved" in said
    assert "persona you choose always wins" in said
    assert not {"signals", "confidence", "baseline"} & set(profile), \
        "a reading reached the payload; it is never stored"


def test_for_somebody_who_swears_as_punctuation_swearing_is_not_listed(manager, monkeypatch):
    _formed(manager, TERSE_SWEARER)
    profile = _style(manager, monkeypatch)["profile"]
    assert profile["traits"][ms.TRAIT_PROFANITY] == "punctuation", "the premise"
    assert "swearing" not in profile["reading"]


def test_before_the_jokes_are_learned_it_says_how_far_and_that_they_change_nothing(manager, monkeypatch):
    """`P13-20`'s `None`, said rather than left blank."""
    _formed(manager)
    unremarkable = {"signals": [], "confidence": 0.0, "baseline": True}
    manager.record_style_observation("haha nice one", reading=unremarkable, owner="felix")
    humour = _style(manager, monkeypatch)["profile"]["humour"]
    assert humour["means"] is None
    assert humour["sentence"] == (f"What your jokes mean is not learned yet — 1 of "
                                  f"{ms.HUMOUR_MIN_EVIDENCE} seen. Until it is, a joke "
                                  "changes nothing about the reply.")


def test_once_learned_it_says_what_the_jokes_mean_and_what_that_does(manager, monkeypatch):
    _formed(manager)
    unremarkable = {"signals": [], "confidence": 0.0, "baseline": True}
    for _ in range(ms.HUMOUR_MIN_EVIDENCE):
        manager.record_style_observation("haha nice one", reading=unremarkable, owner="felix")
    humour = _style(manager, monkeypatch)["profile"]["humour"]
    assert humour["means"] == ms.HUMOUR_RELAXED
    assert "writing as you always do" in humour["sentence"]
    assert "light touch is welcome" in humour["sentence"]


@pytest.mark.parametrize("meaning, words", [
    (ms.HUMOUR_DEFUSE, "play it straight and get shorter"),
    (ms.HUMOUR_WRAPPER, "the complaint is taken as the message"),
])
def test_each_learned_meaning_has_its_own_sentence(meaning, words):
    said = ms.humour_account({meaning: ms.HUMOUR_MIN_EVIDENCE})
    assert words in said, said


def test_evidence_that_points_no_way_says_so():
    said = ms.humour_account({"relaxed": 3, "defuse": 3})
    assert "6 seen, and they do not point one way" in said
