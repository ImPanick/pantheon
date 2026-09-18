# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P13-01` and `P13-03` — how sure the extractor was, and where the fact came from.

`P13-01` asks for the skill extractor's 0..1 score and floor on the other half
of the feature. Two things make that more than a field:

* **The floor is imported, not copied.** `services/memory/skill_extractor.py`
  has owned `MIN_CONFIDENCE` since long before memories had a confidence
  concept, and the row asks for "the same tuning surface, one fewer concept to
  learn". A second constant is a second knob that drifts (`Law 14`).
* **Confidence does not move on its own.** The `P13` preamble reads a
  competitor's shipped version of exactly this — `CONFIDENCE 66%` beside
  `1 mentions` — and names it: that is the extractor's self-report presented as
  corroboration. Corroboration is `mentions`/`mention_sessions` (`P13-15`), and
  the two stay apart.

`P13-03` asks which session, which message and which tool. The session is
already on the record and is deliberately not copied into `provenance`
(`Law 7`). What is new is the producer and the message — and the message can
only be known through a citation, so the citation is **checked against the
transcript** rather than believed.
"""

import asyncio
import json

import pytest

from src.memory import MemoryManager, new_provenance, normalise_confidence
import services.memory.memory_extractor as mx
from services.memory.skill_extractor import MIN_CONFIDENCE


# ── the number itself ──

@pytest.mark.parametrize("value,expected", [
    (0.83, 0.83),
    ("0.4", 0.4),
    (1.9, 1.0),          # clamped: a model asked for 0..1 sometimes says 1.5
    (-3, 0.0),
    (None, None),        # not recorded
    ("high", None),      # unparseable is not a number
    (float("nan"), None),
    (True, None),        # a bool is not a confidence, and float(True) is 1.0
])
def test_confidence_is_parsed_or_reported_as_not_recorded(value, expected):
    assert normalise_confidence(value) == expected


def test_a_memory_written_before_this_row_reads_as_not_recorded(tmp_path):
    """`P13-15` set the precedent: legacy memories read zero, not one.

    A number invented for a record that never had one makes an old memory look
    freshly assessed, which is the reading the phase preamble objects to.
    """
    store = tmp_path / "memory.json"
    store.write_text(json.dumps([
        {"id": "old", "text": "User drives a diesel van", "timestamp": 1},
    ]), encoding="utf-8")

    entry = MemoryManager(str(tmp_path)).load_all()[0]
    assert entry["confidence"] is None
    assert entry["provenance"] is None
    assert entry["edges"] == []


# ── the floor ──

def test_the_floor_is_the_skill_extractors_own_constant():
    """One tuning surface, which is what the row asks for in so many words.

    Identity, not equality: two constants that happen to hold 0.6 are two
    constants, and the day somebody moves one of them the other is wrong.
    """
    assert mx.MIN_CONFIDENCE is MIN_CONFIDENCE


@pytest.fixture(autouse=True)
def _no_incidental_audit(monkeypatch):
    """`extract_and_store` triggers an audit every `AUDIT_INTERVAL` facts, off a
    MODULE-LEVEL counter that survives between tests.

    Without this, the fifth extraction anywhere in the process runs the audit
    against whatever LLM stub happens to be installed, and a test about the
    confidence floor silently becomes a test about the audit. Reset rather than
    disabled, so the path itself is still the real one.
    """
    monkeypatch.setattr(mx, "_extractions_since_audit", 0)


class _Session:
    session_id = "sess-1"
    owner = None

    def __init__(self, messages):
        self._messages = messages

    def get_context_messages(self):
        return self._messages


def _run_extraction(monkeypatch, tmp_path, reply, messages=None):
    manager = MemoryManager(str(tmp_path))
    # Deliberately clear of every `_fallback_memory_candidates` pattern, so a
    # test about the LLM path measures the LLM path. "I live in Berlin" in here
    # would add a second, pattern-extracted memory to every assertion below.
    messages = messages or [
        {"role": "user", "content": "I drive a diesel van"},
        {"role": "assistant", "content": "Noted."},
    ]

    async def _fake_llm(*args, **kwargs):
        return reply

    import src.llm_core as llm_core
    monkeypatch.setattr(llm_core, "llm_call_async", _fake_llm)
    asyncio.run(mx.extract_and_store(
        _Session(messages), manager, None, "http://x", "m"))
    return manager


def test_a_fact_below_the_floor_is_dropped(monkeypatch, tmp_path):
    reply = json.dumps([
        {"text": "User might possibly enjoy sailing", "category": "preference",
         "confidence": 0.2},
    ])
    manager = _run_extraction(monkeypatch, tmp_path, reply)
    assert [m["text"] for m in manager.load_all()] == []


def test_a_fact_above_the_floor_is_kept_with_its_number(monkeypatch, tmp_path):
    reply = json.dumps([
        {"text": "User drives a diesel van", "category": "fact", "confidence": 0.82},
    ])
    manager = _run_extraction(monkeypatch, tmp_path, reply)
    stored = manager.load_all()
    assert [m["text"] for m in stored] == ["User drives a diesel van"]
    assert stored[0]["confidence"] == 0.82


def test_a_model_that_omits_confidence_is_not_punished_for_it(monkeypatch, tmp_path):
    """"Did not answer" and "is not sure" are different claims.

    A local model too small to follow the extended schema returns text and
    category only. Defaulting that below the floor would silently throw away
    every fact it ever extracted, and the log would read `0 candidates`.
    """
    reply = json.dumps([{"text": "User drives a diesel van", "category": "fact"}])
    manager = _run_extraction(monkeypatch, tmp_path, reply)
    stored = manager.load_all()
    assert [m["text"] for m in stored] == ["User drives a diesel van"]
    assert stored[0]["confidence"] == mx.DEFAULT_CONFIDENCE


def test_an_unparseable_confidence_falls_back_rather_than_to_zero(monkeypatch, tmp_path):
    reply = json.dumps([
        {"text": "User drives a diesel van", "category": "fact", "confidence": "very"},
    ])
    manager = _run_extraction(monkeypatch, tmp_path, reply)
    assert [m["text"] for m in manager.load_all()] == ["User drives a diesel van"]


# ── provenance ──

def test_provenance_does_not_carry_the_session_id(tmp_path):
    """`Law 7`. `session_id` is already on the record and two copies of one
    fact go stale separately."""
    row = new_provenance("memory_routes.add")
    assert "session_id" not in row
    assert set(row) == {"producer", "message_index", "quote"}


def test_a_verified_quote_records_which_message_it_came_from(monkeypatch, tmp_path):
    reply = json.dumps([
        {"text": "User drives a diesel van", "category": "fact",
         "confidence": 0.9, "quote": "I drive a diesel van"},
    ])
    manager = _run_extraction(monkeypatch, tmp_path, reply)
    provenance = manager.load_all()[0]["provenance"]
    assert provenance["producer"] == mx.PRODUCER_LLM
    assert provenance["message_index"] == 0
    assert provenance["quote"] == "I drive a diesel van"


def test_an_invented_quote_is_discarded_rather_than_stored(monkeypatch, tmp_path):
    """The one field a person would use to decide whether to believe a memory.

    A model asked to cite its source will produce a plausible sentence the user
    never typed. An unverifiable citation is worse than none, so the fact
    survives and the citation does not.
    """
    reply = json.dumps([
        {"text": "User drives a diesel van", "category": "fact",
         "confidence": 0.9, "quote": "I have owned three diesel vans since 2011"},
    ])
    manager = _run_extraction(monkeypatch, tmp_path, reply)
    stored = manager.load_all()
    assert [m["text"] for m in stored] == ["User drives a diesel van"]
    assert stored[0]["provenance"]["quote"] is None
    assert stored[0]["provenance"]["message_index"] is None


def test_a_quote_from_the_assistant_is_not_accepted_as_the_users_words():
    """`EXTRACT_SYSTEM_PROMPT` lists "things the assistant said" under bad
    examples, so a citation pointing at one is not provenance for a fact about
    the user."""
    messages = [
        {"role": "user", "content": "what do you make of it"},
        {"role": "assistant", "content": "You clearly drive a diesel van."},
    ]
    assert mx._verified_quote("You clearly drive a diesel van.", messages) == (None, None)


def test_a_citation_too_short_to_mean_anything_is_not_evidence():
    """"Sam" appears in any message containing the word."""
    messages = [{"role": "user", "content": "my name is Sam"}]
    assert mx._verified_quote("Sam", messages) == (None, None)
    index, quote = mx._verified_quote("my name is Sam", messages)
    assert (index, quote) == (0, "my name is Sam")


def test_the_pattern_extractor_names_itself_and_the_message_it_matched():
    """The one producer in the module that can know the message without asking
    a model to cite itself — it found the sentence."""
    messages = [
        {"role": "assistant", "content": "hello"},
        {"role": "user", "content": "my name is Ada and I live in Lisbon"},
    ]
    candidates = mx._fallback_memory_candidates(messages)
    assert candidates, "the pattern extractor matched nothing"
    for candidate in candidates:
        assert candidate["producer"] == mx.PRODUCER_FALLBACK
        assert candidate["message_index"] == 1
        assert candidate["confidence"] == mx.FALLBACK_CONFIDENCE


def test_a_pattern_match_is_stored_with_its_own_provenance(monkeypatch, tmp_path):
    """End to end: the fallback path's fact reaches the store carrying the
    producer that found it, not the one that did not."""
    manager = _run_extraction(
        monkeypatch, tmp_path, "[]",
        messages=[
            {"role": "user", "content": "my name is Ada"},
            {"role": "assistant", "content": "Hello Ada."},
        ])
    stored = manager.load_all()
    assert stored, "the pattern fallback fact was dropped"
    assert stored[0]["provenance"]["producer"] == mx.PRODUCER_FALLBACK
    assert stored[0]["provenance"]["message_index"] == 0
    assert stored[0]["confidence"] == mx.FALLBACK_CONFIDENCE


def test_the_retrieval_trace_carries_the_confidence_and_nothing_invented(tmp_path):
    """`P13-10` folds into `P13-01`: the trace already says WHICH memories
    changed the answer, and the only field it lacked is this one. `None` stays
    `None` — a pill reading 80% over a memory nobody assessed is the failure
    the preamble cites."""
    from src.chat_processor import ChatProcessor

    manager = MemoryManager(str(tmp_path))
    # One down each of the two paths that build the trace: a pinned identity
    # fact nothing ranked, and a fact the scorer retrieved.
    pinned = manager.add_entry("User's name is Ada", source="auto",
                               category="identity", confidence=0.82)
    pinned["pinned"] = True
    recalled = manager.add_entry("User drives a diesel van", source="user")
    manager.save([pinned, recalled])

    processor = ChatProcessor(manager, None, None)
    processor.build_context_preface("what do I drive", session=None, use_rag=False)
    by_text = {row["text"]: row for row in processor._last_used_memories}
    assert set(by_text) == {"User's name is Ada", "User drives a diesel van"}, \
        f"the trace did not carry both paths: {sorted(by_text)}"
    assert by_text["User's name is Ada"]["confidence"] == 0.82
    assert by_text["User drives a diesel van"]["confidence"] is None
