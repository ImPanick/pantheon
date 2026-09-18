# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P13-09` — the consolidation pass exists and is blind.

`POST /memory/audit` has always merged near-duplicates and removed junk, and it
has always done both by returning a shorter list: whatever the model did not
send back was deleted, with no record of which entry replaced it and no use
made of the fact that two independent extractions had just agreed. The row asks
for the opposite of that — *"raise confidence where sources agree and record a
contradiction edge where they do not, rather than picking a winner quietly."*

Three things follow, and each is a test below:

* a merge is **corroboration**, so the survivor takes the higher confidence and
  keeps what both records knew about how often the person said it;
* the losing entry is **superseded, not deleted** — `P13-02`'s edge already
  stops it surfacing, so consolidation still consolidates while nothing is
  destroyed;
* a conflict the pass notices is **recorded, not resolved**.

Nothing here asserts on prompt text. The model is stubbed and the assertions
are on the store afterwards, because `Law 20`: a test that greps a file is
testing the file.
"""

import asyncio
import json

import pytest

from src import memory_edges, memory_retrieval
from src.memory import MemoryManager
import services.memory.memory_extractor as mx


@pytest.fixture
def store(tmp_path):
    return MemoryManager(str(tmp_path))


def _audit(monkeypatch, manager, reply, vector=None, owner=None):
    async def _fake_llm(*args, **kwargs):
        return reply

    import src.llm_core as llm_core
    monkeypatch.setattr(llm_core, "llm_call_async", _fake_llm)
    return asyncio.run(mx.audit_memories(manager, vector, "http://x", "m", owner=owner))


def _by_id(manager):
    return {row["id"]: row for row in manager.load_all()}


def _two_names(store):
    weak = store.add_entry("User's name is Sam", source="auto", confidence=0.55)
    strong = store.add_entry("The user is called Sam", source="auto", confidence=0.95)
    weak.update(mentions=3, mention_sessions=2, mention_session_ids=["s1", "s2"])
    strong.update(mentions=1, mention_sessions=1, mention_session_ids=["s2"])
    store.save([weak, strong])
    return weak, strong


def test_a_merged_entry_is_superseded_rather_than_deleted(monkeypatch, store):
    weak, strong = _two_names(store)
    result = _audit(monkeypatch, store, json.dumps([
        {"id": strong["id"], "text": "The user is called Sam", "category": "identity",
         "merged_from": [weak["id"]]},
    ]))

    rows = _by_id(store)
    assert weak["id"] in rows, "the merged-away entry was destroyed"
    assert rows[weak["id"]]["superseded_by"] == strong["id"]
    assert result["superseded"] == 1
    assert result["after"] == 1, "the live count is still the consolidated one"


def test_the_superseded_entry_stops_surfacing(monkeypatch, store):
    """Consolidation still consolidates. `P13-02`'s edge is what does it now,
    which is why keeping the record costs nothing at query time."""
    weak, strong = _two_names(store)
    _audit(monkeypatch, store, json.dumps([
        {"id": strong["id"], "text": "The user is called Sam", "category": "identity",
         "merged_from": [weak["id"]]},
    ]))

    returned = memory_retrieval.retrieve("what is my name sam", store.load_all(), k=5)
    assert [row["id"] for row in returned] == [strong["id"]]


def test_the_survivor_takes_the_higher_confidence_and_never_an_increment(monkeypatch, store):
    """`P13-01` fixes confidence as the extractor's self-report, and a merge is
    the one event that is genuinely evidence about it. `max` says "the
    best-evidenced of these"; an increment would invent a growth curve and
    everything would read 1.0 after enough tidies."""
    weak, strong = _two_names(store)
    _audit(monkeypatch, store, json.dumps([
        {"id": strong["id"], "text": "The user is called Sam", "category": "identity",
         "merged_from": [weak["id"]]},
    ]))
    assert _by_id(store)[strong["id"]]["confidence"] == 0.95

    # And the other direction: the survivor was the less sure of the two.
    weak2 = store.add_entry("User has a cat", source="auto", confidence=0.4)
    strong2 = store.add_entry("The user owns a cat", source="auto", confidence=0.9)
    store.save([weak2, strong2])
    _audit(monkeypatch, store, json.dumps([
        {"id": weak2["id"], "text": "User has a cat", "category": "fact",
         "merged_from": [strong2["id"]]},
    ]))
    assert _by_id(store)[weak2["id"]]["confidence"] == 0.9


def test_mentions_are_summed_and_sessions_are_not(monkeypatch, store):
    """`P13-15`. Every mention was a real statement, so the sum is exact.
    Sessions are not: both records can have been mentioned in the same
    conversation, and counts alone cannot tell. Under-counting durability is
    survivable; over-counting makes a guess look like a pattern."""
    weak, strong = _two_names(store)
    _audit(monkeypatch, store, json.dumps([
        {"id": strong["id"], "text": "The user is called Sam", "category": "identity",
         "merged_from": [weak["id"]]},
    ]))
    survivor = _by_id(store)[strong["id"]]
    assert survivor["mentions"] == 4
    assert survivor["mention_sessions"] == 2, "s2 was counted twice"
    assert sorted(survivor["mention_session_ids"]) == ["s1", "s2"]


def test_a_model_that_merges_without_saying_so_is_still_recorded(monkeypatch, store):
    """The case that decides whether this row ships anything on real hardware.

    A local utility model too small to follow the extended schema does what it
    always did: returns a shorter list and names nothing. The survivor is found
    the same way the extractor's own dedupe finds one — `_text_duplicate_of`,
    which already answers "which memory does this restate" (`Law 14`).
    """
    first = store.add_entry("User drives a diesel van", source="auto", confidence=0.6)
    second = store.add_entry("User drives a diesel van for work",
                             source="auto", confidence=0.9)
    first.update(mentions=3, mention_sessions=2, mention_session_ids=["s1", "s2"])
    second.update(mentions=1, mention_sessions=1, mention_session_ids=["s2"])
    store.save([first, second])

    _audit(monkeypatch, store, json.dumps([
        {"id": second["id"], "text": "User drives a diesel van for work",
         "category": "fact"},
    ]))
    rows = _by_id(store)
    assert rows[first["id"]]["superseded_by"] == second["id"]
    assert rows[second["id"]]["mentions"] == 4
    assert rows[second["id"]]["confidence"] == 0.9


def test_the_undeclared_fallback_reaches_only_as_far_as_the_dedupe_does(monkeypatch, store):
    """And the limit of it, stated rather than discovered later.

    `_text_duplicate_of` is Jaccard at 0.6, so it catches a restatement and not
    a rewording: *"User's name is Sam"* and *"The user is called Sam"* score
    0.29 against each other — they are the AUDIT prompt's own example of a
    merge, and no fuzzy matcher in this module can see it. That is precisely
    why the prompt asks the model for `merged_from` rather than relying on this
    path, and why lowering the threshold is not the answer: the same function
    decides what extraction treats as a duplicate, so a looser one would start
    swallowing distinct facts at write time.
    """
    weak, strong = _two_names(store)
    _audit(monkeypatch, store, json.dumps([
        {"id": strong["id"], "text": "The user is called Sam", "category": "identity"},
    ]))
    assert weak["id"] not in _by_id(store), (
        "if this now passes, the dedupe threshold moved and extraction moved with it")


def test_a_removal_with_no_surviving_near_duplicate_is_still_a_removal(monkeypatch, store):
    """`Law 1` is about capability, not about junk the audit was asked to
    remove. Nothing here turns "delete the meaningless entry" into "keep it
    forever" — that is `P13-04`'s row, and doing it here would quietly change
    what the Tidy button means."""
    keep = store.add_entry("User drives a diesel van", source="auto")
    junk = store.add_entry("The assistant apologised for the delay", source="auto")
    store.save([keep, junk])

    _audit(monkeypatch, store, json.dumps([
        {"id": keep["id"], "text": "User drives a diesel van", "category": "fact"},
    ]))
    assert junk["id"] not in _by_id(store)


def test_a_contradiction_is_recorded_rather_than_resolved(monkeypatch, store):
    berlin = store.add_entry("User lives in Berlin", source="auto", confidence=0.8)
    munich = store.add_entry("User lives in Munich", source="auto", confidence=0.7)
    store.save([berlin, munich])

    result = _audit(monkeypatch, store, json.dumps([
        {"id": berlin["id"], "text": "User lives in Berlin", "category": "fact",
         "contradicts": [munich["id"]]},
        {"id": munich["id"], "text": "User lives in Munich", "category": "fact",
         "contradicts": [berlin["id"]]},
    ]))

    assert result["contradictions"] == 1, "the mirror was stored as a second edge"
    rows = store.load_all()
    index = memory_edges.build_edge_index(rows)
    assert index["contradicts"][berlin["id"]] == {munich["id"]}
    # Both are still live, and both come back.
    returned = memory_retrieval.retrieve("where does the user live", rows, k=5)
    assert {row["id"] for row in returned} == {berlin["id"], munich["id"]}


def test_an_invented_id_is_ignored_rather_than_believed(monkeypatch, store):
    """Both new fields are claims about ids, and a model will answer with ids
    it made up. Nothing is written for one, and a self-claim is not a relation.

    Junk that is not even a string is in here on purpose: that is the one guard
    at the parse site that is load-bearing, because an unhashable id raises
    rather than being ignored, and a `TypeError` inside the audit is swallowed
    by its own `except` and reported as a failed tidy.
    """
    berlin = store.add_entry("User lives in Berlin", source="auto")
    store.save([berlin])

    result = _audit(monkeypatch, store, json.dumps([
        {"id": berlin["id"], "text": "User lives in Berlin", "category": "fact",
         "merged_from": ["nope", {"id": "a dict"}, ["a list"], 7],
         "contradicts": ["also-nope", berlin["id"], None, {"id": "a dict"}]},
    ]))
    assert "error" not in result, result
    assert result["contradictions"] == 0
    assert _by_id(store)[berlin["id"]]["edges"] == []


def test_a_second_audit_does_not_re_examine_what_the_first_archived(monkeypatch, store):
    """Two ways this bites, and the second is the expensive one.

    A superseded entry sent back to the model returns as a duplicate of the
    entry that replaced it. And the tidy fingerprint is computed over what was
    audited: if the archive were included on the next read but not on the last
    write, the fingerprints would never match and every call would spend a full
    LLM round discovering nothing had changed.
    """
    weak, strong = _two_names(store)
    _audit(monkeypatch, store, json.dumps([
        {"id": strong["id"], "text": "The user is called Sam", "category": "identity",
         "merged_from": [weak["id"]]},
    ]))

    calls = []

    async def _counted(*args, **kwargs):
        calls.append(1)
        return "[]"

    import src.llm_core as llm_core
    monkeypatch.setattr(llm_core, "llm_call_async", _counted)
    second = asyncio.run(mx.audit_memories(store, None, "http://x", "m"))

    assert calls == [], "the audit re-ran the model over an unchanged store"
    assert second.get("already_tidy") is True
    assert second["before"] == 1, "the archived entry was counted as live"


def test_the_vector_index_is_rebuilt_from_the_live_set_only(monkeypatch, store):
    """The one path that does not go through the scorer.

    `MemoryVectorStore.find_similar` is the extractor's first dedupe gate. A
    superseded memory left in the index would be matched there, so the next
    time the person stated the fact the restatement would be credited to the
    archived copy and the live one would never hear about it.
    """
    class _Vector:
        healthy = True

        def __init__(self):
            self.rebuilt = None

        def rebuild(self, entries):
            self.rebuilt = [e["id"] for e in entries]

    weak, strong = _two_names(store)
    vector = _Vector()
    _audit(monkeypatch, store, json.dumps([
        {"id": strong["id"], "text": "The user is called Sam", "category": "identity",
         "merged_from": [weak["id"]]},
    ]), vector=vector)

    assert vector.rebuilt == [strong["id"]]


def test_the_startup_rebuild_does_not_put_the_archive_back(monkeypatch, tmp_path):
    """The other rebuild, and the one that made this row half-wired.

    `src/app_initializer.py` rebuilds an empty vector index from the whole
    store at boot. Filtering the audit's own rebuild and not this one means the
    archive is out of the index until the next restart and back in afterwards —
    the worst version, because the bug only appears on a machine that has been
    restarted and is invisible on the one where the change was made.
    """
    from unittest.mock import MagicMock
    import src.app_initializer as app_init
    import src.memory_vector as memory_vector_mod

    manager = MemoryManager(str(tmp_path))
    live = manager.add_entry("User drives a diesel van", source="auto")
    live["edges"] = [{"type": "supersedes", "target": "archived"}]
    archived = manager.add_entry("User drives a van", source="auto")
    archived["id"] = "archived"
    manager.save([live, archived])

    class _Vector:
        healthy = True

        def __init__(self):
            self.rebuilt = None

        def count(self):
            return 0

        def rebuild(self, entries):
            self.rebuilt = [e["id"] for e in entries]

    vector = _Vector()
    for name in ["SkillsManager", "SessionManager", "UploadHandler",
                 "PersonalDocsManager", "APIKeyManager", "PresetManager",
                 "MemoryProviderRegistry", "NativeMemoryProvider", "ChatProcessor",
                 "ResearchHandler", "ChatHandler", "ModelDiscovery"]:
        monkeypatch.setattr(app_init, name, lambda *a, **k: MagicMock())
    monkeypatch.setattr(app_init, "MemoryManager", lambda *a, **k: manager)
    import src.tool_utils as tool_utils
    monkeypatch.setattr(tool_utils, "_upload_handler", tool_utils._upload_handler)
    monkeypatch.setattr(app_init, "set_session_manager", lambda *a, **k: None)
    monkeypatch.setattr(app_init, "update_search_config", lambda *a, **k: None)
    monkeypatch.setattr(app_init, "create_directories", lambda: None)
    monkeypatch.setattr(memory_vector_mod, "MemoryVectorStore", lambda *a, **k: vector)

    app_init.initialize_managers(str(tmp_path), rag_manager=None)

    assert vector.rebuilt == [live["id"]], (
        "the superseded memory went back into the index at startup")


def test_an_audit_that_would_empty_the_store_is_refused(monkeypatch, store):
    """`B640`, found while writing the tests above.

    The over-deletion guard only fired at eight entries or more, and "fewer
    than eight" is a person's first weeks with the product. A reply that parsed
    as a list but named no id the store recognises produced an empty result
    that sailed straight past it, and the write is atomic, so the loss was
    durable.
    """
    keep = store.add_entry("User drives a diesel van", source="auto")
    store.save([keep])

    result = _audit(monkeypatch, store, json.dumps([
        {"id": "an-id-from-another-store", "text": "whatever", "category": "fact"},
    ]))
    assert result["error"] == "unsafe_removal"
    assert [row["id"] for row in store.load_all()] == [keep["id"]]
