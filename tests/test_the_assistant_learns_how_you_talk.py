# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P13-17` / `P13-18` / `P13-19` / `P13-20` — one design, ruled on by `D-2026-09-09-01`.

The owner's ask, in their words: *"the idea the llm can build a profile on the
user based around topics of conversation… recognizes tone by the way the user
types, shifts in emotion by the amount of swears or laughing, which ties into
humor etc."*

The decision turns that into four rows and two hard limits, and the limits are
what most of this file tests:

* **the baseline is personal and never population.** *"A swear count is not an
  emotion signal. A swear count against this person's own baseline is."* The
  owner writes *"PRESS!!"* and *"lol"* as ordinary register, and a
  population-trained scorer reads that as elevated every single time;
* **humour does nothing until it is learned.** Detecting that someone jokes is
  trivial. One observable carries opposite meanings across people — defuse,
  relaxed, wrapper — so a counter cannot separate them, and *"abstaining is not
  caution here, it is correctness"*.

And the line no row here may cross: the profile records **how to be useful to
this person**, never **how this person is doing**. `FORBIDDEN_WORDS` is that
sentence as a fixture, and the test that reads it walks the module's own emitted
output rather than its source, because a file-wide grep would match the
paragraph you are reading (`Law 20`; `H10` is the worked example).
"""

import json
import time

import pytest

from src import memory_edges, memory_style as ms
from src.memory import MemoryManager


@pytest.fixture
def manager(tmp_path):
    return MemoryManager(str(tmp_path))


def baseline(text, times=30):
    """A profile's running totals, built the only way they are ever built."""
    totals = {}
    for _ in range(times):
        totals = ms.fold(totals, ms.observe(text))
    return totals


# Two people who could not be more different, and both are ordinary.
TERSE_SWEARER = "fix the parser its broken again fuck"
FORMAL = "Could you please take a look at the parser when you have a moment? I would appreciate it."


# ── `P13-17` · the profile ────────────────────────────────────────────────────

def test_a_person_with_no_history_has_no_profile_rather_than_an_average_one():
    # The same call `P13-01` made for confidence and `P13-15` made for mentions:
    # a value invented for somebody nobody has observed looks exactly like a
    # value somebody measured.
    assert ms.traits({}) == {}
    assert ms.traits(baseline(FORMAL, times=ms.PROFILE_MIN_MESSAGES - 1)) == {}
    assert ms.traits(baseline(FORMAL, times=ms.PROFILE_MIN_MESSAGES)) != {}


def test_how_somebody_capitalises_is_observed_rather_than_assumed():
    # Caught by mutation: every other test in this file used a baseline whose
    # case bucket happened to match the hardcoded answer, so pinning the trait
    # to `sentence_case` passed all of them.
    assert ms.traits(baseline(TERSE_SWEARER))[ms.TRAIT_CASE] == "lowercase"
    assert ms.traits(baseline(FORMAL))[ms.TRAIT_CASE] == "sentence_case"


def test_the_profile_reads_like_sentences_and_not_like_a_record():
    lines = ms.sentences(ms.traits(baseline(TERSE_SWEARER)))
    assert lines, "a profile with history renders something"
    for line in lines:
        assert line[0].isupper() and line.endswith("."), line
        assert "=" not in line and ":" not in line, line


def test_no_trait_bucket_or_sentence_this_module_can_emit_is_about_mood():
    """The line the decision draws, executable.

    *"'Writes shorter under pressure; wants the fix before the explanation' is a
    working note. 'Seems anxious lately' is not something a text box should be
    keeping about anybody, and no row here may produce it."*

    Walked over the module's **output**, not its text: every trait id, every
    bucket id, every rendered sentence, every signal name, every register key
    and value, and the register instruction itself.
    """
    emitted = list(ms.TRAITS) + list(ms.SIGNALS) + list(ms.HUMOUR_MEANINGS)
    emitted += list(ms.REGISTER_NEUTRAL) + list(ms.REGISTER_NEUTRAL.values())
    for buckets in ms._BUCKETS.values():
        for bucket, sentence in buckets:
            emitted += [bucket, sentence]
    reading = {"signals": list(ms.SIGNALS), "confidence": 0.9, "baseline": True}
    for humour in ms.HUMOUR_MEANINGS:
        emitted.append(ms.register_text(ms.register(reading, humour=humour, joking=True)))
    haystack = " ".join(emitted).lower()
    for word in ms.FORBIDDEN_WORDS:
        assert word not in haystack, f"{word!r} reached something the person reads"


def test_the_sentences_do_not_move_when_the_numbers_do():
    """Bucketed, and two things depend on it.

    A person cannot correct a sentence that rewrites itself under them, and the
    profile rides in a **system** message where per-turn text invalidates the
    KV-cache prefix on every request for local backends
    (`src/user_time.py:216`, issue #2927).
    """
    totals = baseline(FORMAL)
    before = ms.sentences(ms.traits(totals))
    for _ in range(40):
        totals = ms.fold(totals, ms.observe(FORMAL))
    assert ms.sentences(ms.traits(totals)) == before


def test_swearing_as_punctuation_and_swearing_as_emphasis_are_different_traits():
    # The row's own worked example. Two people can swear at the same rate per
    # message and mean opposite things by it; what separates them is how spread
    # out it is, not how much there is.
    habitual = baseline("fuck this parser is broken")
    occasional = {}
    for i in range(30):
        occasional = ms.fold(occasional, ms.observe(
            "fuck this parser" if i % 10 == 0 else "please look at the parser"))
    assert ms.traits(habitual)[ms.TRAIT_PROFANITY] == "punctuation"
    assert ms.traits(occasional)[ms.TRAIT_PROFANITY] == "emphasis"


def test_the_profile_stores_counters_and_never_the_message(manager):
    secret = "my landlord is called Wendy and the rent is 1450 a month"
    for _ in range(ms.PROFILE_MIN_MESSAGES):
        manager.record_style_observation(secret)
    raw = json.dumps(manager.load_all())
    assert "Wendy" not in raw and "1450" not in raw
    assert manager.style_profile()["style"]["messages"] == ms.PROFILE_MIN_MESSAGES


def test_a_style_record_is_not_a_memory_and_never_reaches_a_prompt(manager):
    for _ in range(ms.PROFILE_MIN_MESSAGES):
        manager.record_style_observation(TERSE_SWEARER)
    manager.save(manager.load_all() + [manager.add_entry("User drives a van")])
    surfacing = memory_edges.live(manager.load_all())
    assert [row["text"] for row in surfacing] == ["User drives a van"]
    assert manager.style_profile() is not None, "it is still in the store"


def test_a_store_written_before_this_row_still_works(tmp_path):
    """The migration proof, against a store created without the field.

    The phase's store correction holds and was re-measured again for this wave:
    memory lives in `data/memory.json`, and the SQL `memories` table still has
    **three** non-test readers (`core/database.py` count,
    `src/builtin_actions.py`, `routes/admin_wipe` count + delete), not one of
    which reads a memory to answer anything. So there is no `ALTER TABLE` here,
    and the equivalent obligation is this: a record written by hand, before
    `kind` existed, loads and reads as a memory.
    """
    store = tmp_path / "memory.json"
    store.write_text(json.dumps([
        {"id": "old", "text": "User is allergic to shellfish",
         "timestamp": 1780000000, "source": "user", "category": "fact"},
    ]), encoding="utf-8")
    manager = MemoryManager(str(tmp_path))
    rows = manager.load_all()
    assert rows[0]["kind"] == ms.KIND_MEMORY
    assert ms.kind_of(rows[0]) == ms.KIND_MEMORY
    assert [r["id"] for r in memory_edges.live(rows)] == ["old"]
    assert manager.style_profile() is None


def test_an_unrecognised_kind_reads_as_a_memory_rather_than_vanishing():
    # Of the two ways to be wrong, "a style note got treated as a memory" is
    # visible in the Brain and "every memory stopped surfacing" is the least
    # visible failure this product can have.
    assert ms.kind_of({"kind": "styel"}) == ms.KIND_MEMORY
    assert ms.kind_of({"kind": None}) == ms.KIND_MEMORY
    assert ms.kind_of("not a dict") == ms.KIND_MEMORY
    assert ms.kind_of({"kind": ms.KIND_STYLE}) == ms.KIND_STYLE


# ── `P13-18` · the reading ────────────────────────────────────────────────────

def test_the_same_message_reads_differently_for_two_different_baselines():
    """`P13-18`'s `Verify:` line, and the whole argument of the row.

    One message, two people. For the person who swears as punctuation it is
    nothing; for the person who does not, it is the loudest thing in the
    message. A population-trained model cannot produce this answer because it
    has never met either of them.
    """
    message = ["what the fuck"]
    swearer = ms.read(baseline(TERSE_SWEARER), message)
    formal = ms.read(baseline(FORMAL), message)
    assert ms.SIGNAL_SWEARING not in swearer["signals"]
    assert ms.SIGNAL_SWEARING in formal["signals"]
    assert formal["confidence"] > swearer["confidence"]


def test_a_new_user_is_read_as_nothing_rather_than_as_neutral():
    reading = ms.read({}, ["WHY IS THIS STILL BROKEN"])
    assert reading["signals"] == []
    assert reading["confidence"] == 0.0
    # The third field, and it is why `P13-20` can tell "we could not look" from
    # "we looked and nothing was unusual" (`Law 10`).
    assert reading["baseline"] is False
    assert ms.read(baseline(FORMAL), [FORMAL])["baseline"] is True


def test_a_reading_is_never_written_to_the_record(manager):
    """*"An assistant that decided you were angry in March and has been careful
    with you ever since is what happens when 2 is stored like 1."*"""
    for _ in range(ms.PROFILE_MIN_MESSAGES):
        manager.record_style_observation(FORMAL)
    manager.record_style_observation("WHY IS THIS STILL BROKEN")
    record = manager.style_profile()
    for banned in ("reading", "signals", "confidence_reading", "state"):
        assert banned not in record, banned
    assert set(record["style"]) == set(ms.OBSERVATION_FIELDS)


def test_a_reading_does_not_survive_the_window_it_was_computed_from():
    """It decays because it is recomputed, and it is gone next session because
    a new session is a new window. There is no field to expire."""
    totals = baseline(FORMAL)
    under = ms.read(totals, ["BROKEN", "STILL BROKEN", "FIX IT"])
    assert under["signals"], "a strong deviation reads as one"
    # A new session: the window is whatever that session has, and it has this.
    assert ms.read(totals, [FORMAL])["signals"] == []


def test_the_newest_message_counts_for_more_than_the_oldest():
    """The decay, and the assertion is strict on purpose.

    The two windows below hold the *same three messages* in opposite orders, so
    an undecayed fold cannot tell them apart — `>=` was green with
    `READING_DECAY = 1.0` and a mutation said so.
    """
    totals = baseline(FORMAL)
    calming = ms.read(totals, ["FIX IT", "FIX IT", FORMAL])
    escalating = ms.read(totals, [FORMAL, "FIX IT", "FIX IT"])
    assert sorted(calming["signals"]) != sorted(escalating["signals"])
    assert escalating["confidence"] > calming["confidence"]


def test_confidence_never_claims_certainty_about_a_person():
    totals = baseline(FORMAL, times=10000)
    reading = ms.read(totals, ["FIX IT NOW"])
    assert 0.0 < reading["confidence"] <= 0.9


# ── `P13-19` · register, not mood ─────────────────────────────────────────────

def test_the_move_under_pressure_is_shorter_and_never_softer():
    """*"Answering impatience with sympathy is answering it with more words,
    which is exactly backwards."*"""
    reading = ms.read(baseline(FORMAL), ["BROKEN", "STILL BROKEN", "FIX IT"])
    reg = ms.register(reading)
    assert reg["length"] == "shorter"
    assert reg["hedging"] == "none"
    assert reg["clarify"] == "act"
    text = ms.register_text(reg).lower()
    assert "short" in text
    for soft in ("gentle", "kind", "sympath", "reassur", "apolog"):
        assert soft not in text, soft


def test_an_explicit_persona_is_never_softened_by_a_reading():
    """`setting_is_explicit` — a thing a person typed beats a thing we inferred.

    *"Someone running Razor asked for blunt and minimal; a reading that they
    seem playful today does not get to soften it."*
    """
    reading = ms.read(baseline(FORMAL), ["BROKEN", "STILL BROKEN", "FIX IT"])
    assert ms.register(reading)["length"] == "shorter"
    assert ms.register(reading, persona_is_explicit=True) == ms.REGISTER_NEUTRAL
    assert ms.register(reading, humour=ms.HUMOUR_RELAXED, joking=True,
                       persona_is_explicit=True) == ms.REGISTER_NEUTRAL


def test_a_low_confidence_reading_changes_nothing_at_all():
    """*"Low confidence means behave normally — not 'behave gently'.
    Softening everything for someone who is not upset is patronising."*"""
    weak = {"signals": [ms.SIGNAL_SHORTER], "baseline": True,
            "confidence": ms.REGISTER_MIN_CONFIDENCE - 0.01}
    strong = dict(weak, confidence=ms.REGISTER_MIN_CONFIDENCE)
    assert ms.register(weak) == ms.REGISTER_NEUTRAL
    assert ms.register(strong) != ms.REGISTER_NEUTRAL


def test_a_neutral_register_puts_nothing_on_the_wire():
    # Not an empty message — no message. A turn where the assistant should
    # behave normally is a turn where this feature is absent, not quiet.
    assert ms.register_text(ms.REGISTER_NEUTRAL) == ""
    assert ms.register_text(None) == ""
    assert ms.is_neutral(ms.register(None))


def test_the_register_may_not_change_what_is_true_and_says_so_on_the_wire():
    """*"A reading may change how much is said, how directly, and whether the
    assistant asks or acts. It may not change what is true, and it may not add
    feelings the assistant does not have."*"""
    reading = {"signals": list(ms.SIGNALS), "confidence": 0.9, "baseline": True}
    text = ms.register_text(ms.register(reading))
    assert ms.REGISTER_GUARD in text
    assert "does not change any fact" in text
    assert "not mention it" in text
    # Every dial is a property of delivery. None of them names content.
    assert set(ms.REGISTER_NEUTRAL) == {"length", "hedging", "clarify", "humour"}


# ── `P13-20` · humour, which does nothing until it is learned ─────────────────

def test_an_unlearned_association_produces_no_register_change():
    """The row's whole point, and the `None` branch is not a fallthrough.

    *"Mistaking a wrapped complaint for a good mood is the single most
    alienating error the feature could make."*
    """
    unremarkable = {"signals": [], "confidence": 0.0, "baseline": True}
    assert ms.register(unremarkable, humour=None, joking=True) == ms.REGISTER_NEUTRAL
    assert ms.humour_means({}) is None
    assert ms.humour_means({"relaxed": ms.HUMOUR_MIN_EVIDENCE - 1}) is None


def test_the_same_joke_frequency_with_opposite_learning_gives_opposite_registers():
    """`P13-20`'s `Verify:` line, exactly."""
    counts = ms.HUMOUR_MIN_EVIDENCE
    relaxed = ms.humour_means({"relaxed": counts, "defuse": 0, "wrapper": 0})
    defuse = ms.humour_means({"relaxed": 0, "defuse": counts, "wrapper": 0})
    assert (relaxed, defuse) == (ms.HUMOUR_RELAXED, ms.HUMOUR_DEFUSE)

    turn = {"signals": [], "confidence": 0.0, "baseline": True}
    a = ms.register(turn, humour=relaxed, joking=True)
    b = ms.register(turn, humour=defuse, joking=True)
    assert a["humour"] == "welcome"
    assert b["humour"] == "avoid"
    assert a["length"] == "normal" and b["length"] == "shorter"


def test_evidence_without_a_margin_is_not_evidence():
    # Six observations split three-two-one is not evidence of anything.
    split = {"relaxed": 3, "defuse": 2, "wrapper": 1}
    assert sum(split.values()) >= ms.HUMOUR_MIN_EVIDENCE
    assert ms.humour_means(split) is None
    assert ms.humour_means({"relaxed": 6, "defuse": 2, "wrapper": 1}) == ms.HUMOUR_RELAXED


def test_a_joke_around_a_complaint_is_read_as_the_wrapper_and_not_the_mood():
    joking_complaint = ms.observe("lol it's still broken, classic")
    under = {"signals": [ms.SIGNAL_SHORTER], "confidence": 0.8, "baseline": True}
    assert ms.classify_humour(joking_complaint, under) == ms.HUMOUR_WRAPPER
    # The same deviation without a complaint is the defuse case.
    plain_joke = ms.observe("lol ok")
    assert ms.classify_humour(plain_joke, under) == ms.HUMOUR_DEFUSE
    # And writing exactly as they always do is the green light.
    unremarkable = {"signals": [], "confidence": 0.0, "baseline": True}
    assert ms.classify_humour(plain_joke, unremarkable) == ms.HUMOUR_RELAXED


def test_a_joke_from_someone_with_no_baseline_teaches_nothing():
    # The branch that stops a brand-new user teaching the wrong association out
    # of their first six messages.
    joke = ms.observe("haha ok")
    assert ms.classify_humour(joke, {"signals": [], "confidence": 0.0,
                                     "baseline": False}) is None
    assert ms.classify_humour(joke, None) is None
    assert ms.classify_humour(ms.observe("no joke here"), None) is None


def test_the_association_is_learned_through_the_store(manager):
    for _ in range(ms.PROFILE_MIN_MESSAGES):
        manager.record_style_observation(FORMAL)
    unremarkable = {"signals": [], "confidence": 0.0, "baseline": True}
    for _ in range(ms.HUMOUR_MIN_EVIDENCE):
        manager.record_style_observation("haha nice one", reading=unremarkable)
    learned = manager.style_profile()["humour"]
    assert learned["means"] == ms.HUMOUR_RELAXED
    assert learned["observations"][ms.HUMOUR_RELAXED] == ms.HUMOUR_MIN_EVIDENCE


# ── the store and the wire ────────────────────────────────────────────────────

def test_an_edit_is_kept_and_not_overwritten_by_the_next_observation(manager):
    for _ in range(ms.PROFILE_MIN_MESSAGES):
        manager.record_style_observation(FORMAL)
    rows = manager.load_all()
    rows[0]["text"] = "Wants the answer first. Hates preamble."
    rows[0]["style_edited"] = int(time.time())
    manager.save(rows)
    for _ in range(ms.PROFILE_MIN_MESSAGES * 3):
        manager.record_style_observation(TERSE_SWEARER)
    record = manager.style_profile()
    assert record["text"] == "Wants the answer first. Hates preamble."
    # The counters keep going — the observation is still true, only the
    # description is theirs now.
    assert record["style"]["messages"] > ms.PROFILE_MIN_MESSAGES


def test_deleting_the_profile_takes_the_counters_with_it(manager):
    for _ in range(ms.PROFILE_MIN_MESSAGES):
        manager.record_style_observation(FORMAL)
    profile_id = manager.style_profile()["id"]
    manager.save([r for r in manager.load_all() if r["id"] != profile_id])
    assert manager.style_profile() is None
    manager.record_style_observation(FORMAL)
    assert manager.style_profile()["style"]["messages"] == 1
    assert ms.traits(manager.style_profile()["style"]) == {}


def test_an_empty_message_is_not_an_observation(manager):
    assert manager.record_style_observation("   ") is None
    assert manager.record_style_observation(None) is None
    assert manager.load_all() == []


# ── the seam: the chat preface ────────────────────────────────────────────────
#
# `Law 13`. Everything above is a vocabulary and a store. These are the tests
# that say it is *reached* — and the one that says where it is allowed to sit,
# which is a constraint rather than a detail.

class _Docs:
    rag_manager = None


class _Session:
    def __init__(self, user_messages=()):
        self._messages = [{"role": "user", "content": text} for text in user_messages]

    def get_context_messages(self):
        return list(self._messages)


def _processor(manager):
    from src.chat_processor import ChatProcessor
    return ChatProcessor(memory_manager=manager, personal_docs_manager=_Docs())


def test_the_preface_observes_the_turn_and_the_profile_grows(manager):
    processor = _processor(manager)
    for _ in range(ms.PROFILE_MIN_MESSAGES):
        processor.build_context_preface(
            message=FORMAL, session=_Session(), use_rag=False, use_memory=True)
    record = manager.style_profile()
    assert record["style"]["messages"] == ms.PROFILE_MIN_MESSAGES
    assert record["text"], "the sentences render once there is enough history"


def test_incognito_leaves_no_trace_in_the_profile(manager):
    processor = _processor(manager)
    for _ in range(ms.PROFILE_MIN_MESSAGES * 2):
        processor.build_context_preface(
            message=FORMAL, session=_Session(), use_rag=False,
            use_memory=True, incognito=True)
    assert manager.style_profile() is None


def test_turning_the_brain_off_turns_the_observation_off(manager):
    # Observing how somebody writes into a store they have just switched off is
    # the surveillance reading of this feature, which the decision draws a line
    # against by name.
    processor = _processor(manager)
    for _ in range(ms.PROFILE_MIN_MESSAGES * 2):
        processor.build_context_preface(
            message=FORMAL, session=_Session(), use_rag=False, use_memory=False)
    assert manager.style_profile() is None


def test_an_ordinary_turn_puts_nothing_extra_on_the_wire(manager):
    processor = _processor(manager)
    for _ in range(ms.PROFILE_MIN_MESSAGES):
        processor.build_context_preface(
            message=FORMAL, session=_Session(), use_rag=False, use_memory=True)
    preface, _, _ = processor.build_context_preface(
        message=FORMAL, session=_Session([FORMAL]), use_rag=False, use_memory=True)
    assert not any("How to pitch this reply" in (m.get("content") or "")
                   for m in preface)
    assert processor._last_register == ms.REGISTER_NEUTRAL


def test_a_reading_reaches_the_model_as_a_user_message_and_never_the_system_block(manager):
    """Where it sits is a constraint, not a detail.

    `src/user_time.py:216` documents it in full (issue #2927): local
    llama.cpp / LM Studio backends key their KV-cache prefix off the system
    block byte-for-byte, and `llm_core` consolidates every `system` message in
    this array to the front. A register that changes turn to turn would
    invalidate the cached prefix on every single request for exactly the
    self-hosted setups this project exists to serve.
    """
    processor = _processor(manager)
    for _ in range(ms.PROFILE_MIN_MESSAGES):
        processor.build_context_preface(
            message=FORMAL, session=_Session(), use_rag=False, use_memory=True)
    preface, _, _ = processor.build_context_preface(
        message="FIX IT", session=_Session(["BROKEN", "STILL BROKEN"]),
        use_rag=False, use_memory=True)
    hits = [m for m in preface if "How to pitch this reply" in (m.get("content") or "")]
    assert len(hits) == 1, "the register reaches the model exactly once"
    assert hits[0]["role"] == "user"
    assert preface[-1] is hits[0], "and it is last, after memory and RAG"
    assert not any(m.get("role") == "system" and "How to pitch" in m.get("content", "")
                   for m in preface)


def test_a_chosen_preset_beats_the_reading_at_the_seam_too(manager):
    processor = _processor(manager)
    for _ in range(ms.PROFILE_MIN_MESSAGES):
        processor.build_context_preface(
            message=FORMAL, session=_Session(), use_rag=False, use_memory=True)
    preface, _, _ = processor.build_context_preface(
        message="FIX IT", session=_Session(["BROKEN", "STILL BROKEN"]),
        use_rag=False, use_memory=True,
        preset_system_prompt="You are Razor. Be blunt and minimal.")
    assert not any("How to pitch this reply" in (m.get("content") or "")
                   for m in preface)
    assert processor._last_register == ms.REGISTER_NEUTRAL


def test_a_manager_that_predates_this_row_still_builds_a_preface():
    class _Old:
        def load(self, owner=None):
            return []

    processor = _processor(_Old())
    preface, _, _ = processor.build_context_preface(
        message="hello", session=_Session(), use_rag=False, use_memory=True)
    assert processor._last_register == ms.REGISTER_NEUTRAL
    assert isinstance(preface, list)


# ── the seam: the routes ──────────────────────────────────────────────────────

def _routes(manager, monkeypatch, caller="felix"):
    from unittest.mock import MagicMock

    import routes.memory_routes as mr

    monkeypatch.setattr(mr, "get_current_user", lambda request: caller, raising=False)
    monkeypatch.setattr("src.auth_helpers.require_privilege",
                        lambda request, privilege: caller)
    router = mr.setup_memory_routes(manager, MagicMock())
    # Keyed by method AND path: `GET`, `PUT` and `DELETE` all live at
    # `/api/memory/{memory_id}`, and a dict keyed on path alone silently hands
    # back whichever one was registered last. It handed back `delete_memory`,
    # which is the kind of green-looking wrong answer `Law 20` is about.
    return {(method, route.path): route.endpoint
            for route in router.routes
            for method in getattr(route, "methods", ())}


def test_the_page_can_say_how_far_off_a_profile_is(manager, monkeypatch):
    """`Law 15`, and it rides the payload the Brain already fetches.

    *"18 of 20 messages seen"* is a sentence a cold reader understands; a page
    that can only say nothing is one they file as broken. It is a key on
    `GET /api/memory` rather than a route of its own because
    `check-unreachable.py` counted the standalone endpoint as the 91st route
    with no frontend caller against a ceiling of 90 — `static/**` is another
    agent's this wave, so nothing would have called it, and raising a ratchet
    to admit an unwired endpoint is the drift `Law 13` is about.
    """
    endpoints = _routes(manager, monkeypatch)
    out = endpoints[("GET", "/api/memory")](request=None)["style"]
    assert out == {"profile": None, "observed": 0,
                   "needed": ms.PROFILE_MIN_MESSAGES}
    for _ in range(ms.PROFILE_MIN_MESSAGES - 1):
        manager.record_style_observation(FORMAL, owner="felix")
    partial = endpoints[("GET", "/api/memory")](request=None)["style"]
    assert partial["profile"] is None
    assert partial["observed"] == ms.PROFILE_MIN_MESSAGES - 1
    manager.record_style_observation(FORMAL, owner="felix")
    out = endpoints[("GET", "/api/memory")](request=None)["style"]
    assert out["profile"]["sentences"]
    assert out["profile"]["traits"][ms.TRAIT_CASE] == "sentence_case"
    assert out["profile"]["humour"]["means"] is None


def test_the_brain_payload_survives_a_manager_that_predates_this_row(monkeypatch):
    from unittest.mock import MagicMock

    import routes.memory_routes as mr

    class _Old:
        def load(self, owner=None):
            return [{"id": "a", "text": "User drives a van"}]

    monkeypatch.setattr(mr, "get_current_user", lambda request: "felix", raising=False)
    monkeypatch.setattr("src.auth_helpers.require_privilege",
                        lambda request, privilege: "felix")
    router = mr.setup_memory_routes(_Old(), MagicMock())
    endpoint = next(r.endpoint for r in router.routes
                    if r.path == "/api/memory" and "GET" in r.methods)
    out = endpoint(request=None)
    assert out["memory"][0]["text"] == "User drives a van"
    assert out["style"]["profile"] is None


def test_correcting_the_profile_is_recorded_as_the_error_signal(manager, monkeypatch):
    """*"Edits are the only error signal this feature can have."*"""
    recorded = []
    import src.events as events
    monkeypatch.setattr(events, "record_event",
                        lambda *a, **k: recorded.append((a, k)))
    for _ in range(ms.PROFILE_MIN_MESSAGES):
        manager.record_style_observation(FORMAL, owner="felix")
    profile_id = manager.style_profile(owner="felix")["id"]

    endpoints = _routes(manager, monkeypatch)
    endpoints[("PUT", "/api/memory/{memory_id}")](
        request=None, memory_id=profile_id,
        text="Wants the answer first.", category=None)
    assert manager.style_profile(owner="felix")["style_edited"]
    assert recorded and recorded[-1][1]["outcome"] == "edited"
    assert recorded[-1][1]["name"] == "style_profile"


def test_an_ordinary_memory_edit_is_not_a_style_edit(manager, monkeypatch):
    # The flag is set by kind, not by which route was called.
    row = manager.add_entry("User drives a van", owner="felix")
    manager.save([row])
    endpoints = _routes(manager, monkeypatch)
    endpoints[("PUT", "/api/memory/{memory_id}")](
        request=None, memory_id=row["id"], text="User drives a lorry", category=None)
    assert "style_edited" not in manager.load_all()[0]


def test_the_timeline_is_not_swamped_by_a_record_that_moves_every_turn(manager, monkeypatch):
    # The profile's timestamp bumps on every user message, so leaving it in
    # would pin one row to the top of every timeline for ever.
    manager.save([manager.add_entry("User drives a van", owner="felix")])
    for _ in range(ms.PROFILE_MIN_MESSAGES):
        manager.record_style_observation(FORMAL, owner="felix")
    endpoints = _routes(manager, monkeypatch)
    rows = endpoints[("GET", "/api/memory/timeline")](request=None)["timeline"]
    assert [r["text"] for r in rows] == ["User drives a van"]


def test_the_brain_list_still_shows_it_because_it_is_meant_to_be_read(manager, monkeypatch):
    for _ in range(ms.PROFILE_MIN_MESSAGES):
        manager.record_style_observation(FORMAL, owner="felix")
    endpoints = _routes(manager, monkeypatch)
    rows = endpoints[("GET", "/api/memory")](request=None)["memory"]
    assert [r["kind"] for r in rows] == [ms.KIND_STYLE]
