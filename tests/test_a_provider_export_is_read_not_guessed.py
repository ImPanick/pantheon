# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P13-06` — importing a ChatGPT, Claude or Gemini conversation export.

**The premise, measured first.** `POST /api/memory/import` already accepted
`.json`, and all three exports are `.json`, so every one of them already
*reached* the endpoint — and was handled as "a document": the first 15,000
characters of raw export JSON, braces and node ids and `create_time` floats,
handed to an extraction model. The memories-export fast path underneath looked
for a `text` key, found none on any of the three shapes, and passed it through.
The pipe was right and nothing read the file.

Three things this row has to be true about:

* **the file is read, not guessed** — sniffed by structure rather than by
  filename, `None` rather than a wrong provider, and only the person's own
  turns, because three years of another assistant's confident wrong answers is
  the worst corpus this product could be handed;
* **every imported memory carries its origin and enters lower** — written into
  the store by the server, never carried back through a browser that can drop
  it, at a confidence that sits strictly between the floor and the first-hand
  default;
* **`Law 16`** — an import reads a file the user hands over, and nothing here
  can reach anything.

`Law 20`: every test calls the thing. Nothing greps a file.
"""

import asyncio
import io
import json

import pytest

from src import memory_edges, memory_retrieval
from src.memory import MemoryManager
from services.memory import provider_import
from services.memory.memory_extractor import (
    DEFAULT_CONFIDENCE,
    IMPORT_CONFIDENCE_CEILING,
    MIN_CONFIDENCE,
    store_imported,
)


@pytest.fixture
def store(tmp_path):
    return MemoryManager(str(tmp_path))


# ── the three shapes, as they actually ship ───────────────────────────────────

def chatgpt_export():
    return [{
        "title": "Van maintenance",
        "conversation_id": "c1",
        # Deliberately stored out of order: a `mapping` is a dict of tree
        # nodes keyed by id, and a fixture whose storage order happens to
        # match its timestamps cannot tell whether anything sorted it.
        "mapping": {
            "n3": {"id": "n3", "message": {
                "author": {"role": "user"}, "create_time": 3.0,
                "content": {"content_type": "text", "parts": ["It is a 2016 plate"]}}},
            "n2": {"id": "n2", "message": {
                "author": {"role": "assistant"}, "create_time": 2.0,
                "content": {"content_type": "text", "parts": ["You should service it."]}}},
            "n1": {"id": "n1", "message": {
                "author": {"role": "user"}, "create_time": 1.0,
                "content": {"content_type": "text", "parts": ["I drive a Transit van"]}}},
            "n0": {"id": "n0", "message": {
                "author": {"role": "system"}, "create_time": 0.0,
                "content": {"content_type": "text", "parts": [""]}}},
        },
    }]


def claude_export():
    return [{
        "uuid": "u1",
        "name": "Shellfish",
        "chat_messages": [
            {"uuid": "m1", "sender": "human", "text": "I am allergic to shellfish"},
            {"uuid": "m2", "sender": "assistant", "text": "Noted."},
            {"uuid": "m3", "sender": "human", "text": "",
             "content": [{"type": "text", "text": "I also avoid peanuts"},
                         {"type": "image", "source": {}}]},
        ],
    }]


def gemini_export():
    return [
        {"header": "Gemini Apps", "products": ["Gemini Apps"],
         "title": "Prompted  My name is Sam", "time": "2026-01-01T00:00:00Z"},
        {"header": "Gemini Apps", "products": ["Gemini Apps"],
         "title": "Used Gemini Apps", "time": "2026-01-01T00:01:00Z"},
        {"header": "Search", "products": ["Search"],
         "title": "Searched for cheap flights", "time": "2026-01-01T00:02:00Z"},
    ]


# ── sniffing ──────────────────────────────────────────────────────────────────

def test_each_provider_is_recognised_by_its_own_structure():
    assert provider_import.sniff(chatgpt_export()) == provider_import.CHATGPT
    assert provider_import.sniff(claude_export()) == provider_import.CLAUDE
    assert provider_import.sniff(gemini_export()) == provider_import.GEMINI


def test_an_unrecognised_file_is_none_rather_than_a_guess():
    """A misread export yields nothing, and *"0 facts found"* is
    indistinguishable from a file with nothing in it."""
    assert provider_import.sniff([{"text": "User drives a van"}]) is None
    assert provider_import.sniff({"conversations": []}) is None
    assert provider_import.sniff([]) is None
    assert provider_import.sniff("conversations.json") is None


def test_a_json_file_that_is_not_a_list_at_all_is_declined_and_not_crashed_on():
    """Caught by mutation: the type guard in `sniff` was untested.

    `json.load` happily returns `None`, a number or a string — a `.json` file
    containing `null` is valid JSON — and every recogniser below the guard
    iterates what it is handed. Without it those inputs raise `TypeError` out
    of an upload handler rather than falling through to the generic import path
    the way every other unrecognised file does.
    """
    for not_an_export in (None, 42, 3.5, True):
        assert provider_import.sniff(not_an_export) is None


def test_a_takeout_export_that_is_not_gemini_is_not_read_as_gemini():
    # `title` alone matches Search, Maps and YouTube. Importing somebody's
    # search history as memories is only visible after it has happened.
    assert provider_import.sniff([
        {"header": "Search", "products": ["Search"], "title": "Searched for x"},
    ]) is None


# ── only the person's own words ───────────────────────────────────────────────

def test_chatgpt_reads_the_users_turns_in_order_and_drops_the_assistants():
    out = provider_import.read_export(chatgpt_export())
    assert out["provider"] == provider_import.CHATGPT
    assert out["conversations"] == 1
    assert out["messages"] == 2
    assert out["dropped_assistant"] == 1
    assert "I drive a Transit van" in out["text"]
    assert "It is a 2016 plate" in out["text"]
    assert "You should service it." not in out["text"]
    # A `mapping` is a dict of tree nodes; its iteration order is storage
    # order, not the order anybody said anything in.
    assert out["text"].index("I drive a Transit van") < out["text"].index("It is a 2016 plate")


def test_chatgpt_skips_what_the_product_injected_rather_than_what_you_typed():
    export = chatgpt_export()
    export[0]["mapping"]["nx"] = {"id": "nx", "message": {
        "author": {"role": "user"}, "create_time": 0.5,
        "metadata": {"is_visually_hidden_from_conversation": True},
        "content": {"content_type": "text", "parts": ["custom instructions blob"]}}}
    out = provider_import.read_export(export)
    assert "custom instructions blob" not in out["text"]
    assert out["messages"] == 2


def test_a_non_text_part_contributes_nothing_rather_than_its_repr():
    export = chatgpt_export()
    export[0]["mapping"]["n1"]["message"]["content"]["parts"] = [
        {"content_type": "image_asset_pointer", "asset_pointer": "file-abc"},
        "I drive a Transit van",
    ]
    out = provider_import.read_export(export)
    assert "asset_pointer" not in out["text"]
    assert "I drive a Transit van" in out["text"]


def test_claude_reads_both_spellings_of_a_message_body():
    """`text` and the typed-block `content` array both ship, sometimes in one
    file, so taking whichever is non-empty is how a message with an attachment
    beside its prose keeps its prose."""
    out = provider_import.read_export(claude_export())
    assert out["provider"] == provider_import.CLAUDE
    assert "I am allergic to shellfish" in out["text"]
    assert "I also avoid peanuts" in out["text"]
    assert "Noted." not in out["text"]
    assert out["messages"] == 2 and out["dropped_assistant"] == 1


def test_gemini_reads_prompts_and_ignores_every_other_activity():
    out = provider_import.read_export(gemini_export())
    assert out["provider"] == provider_import.GEMINI
    assert out["messages"] == 1
    assert "My name is Sam" in out["text"]
    assert "cheap flights" not in out["text"]
    assert "Used Gemini Apps" not in out["text"]


def test_gemini_survives_the_double_space_the_export_actually_ships():
    out = provider_import.read_export([
        {"header": "Gemini Apps", "products": ["Gemini Apps"],
         "title": "Prompted  I live in Leeds"},
    ])
    assert "I live in Leeds" in out["text"]
    assert not out["text"].startswith("Prompted")


def test_junk_inside_a_recognised_export_is_skipped_not_crashed_on():
    export = chatgpt_export()
    export.append("not a conversation")
    export.append({"mapping": {"bad": None, "worse": {"message": "string"}}})
    out = provider_import.read_export(export)
    assert out["messages"] == 2


# ── the budget, reported rather than hidden ───────────────────────────────────

def test_truncation_is_a_field_and_not_a_marker_buried_in_the_prompt():
    export = [{"uuid": "u", "name": "Long", "chat_messages": [
        {"sender": "human", "text": "x" * 500} for _ in range(20)]}]
    out = provider_import.read_export(export, char_budget=1200)
    assert out["truncated"] is True
    assert out["messages"] == 2, "the count is of what was read, not what was in the file"


def test_nothing_is_truncated_when_it_all_fits():
    out = provider_import.read_export(claude_export(), char_budget=10000)
    assert out["truncated"] is False


def test_one_pasted_document_cannot_eat_the_whole_budget():
    export = [{"uuid": "u", "name": "Paste", "chat_messages": [
        {"sender": "human", "text": "y" * 50000},
        {"sender": "human", "text": "I drive a Transit van"}]}]
    out = provider_import.read_export(export, char_budget=6000)
    assert out["messages"] == 2
    assert "I drive a Transit van" in out["text"]


# ── `Law 16` ──────────────────────────────────────────────────────────────────

def test_reading_an_export_reaches_nothing(monkeypatch):
    """The destination is the whole test, so the test is about destinations.

    Asserted by breaking every way out of the process rather than by grepping
    the module for `import requests`: `B723` closed a hole of exactly this
    shape two waves ago, and the temptation on an importer is always the same
    one — *just check the export format version*.
    """
    import socket

    def _no(*args, **kwargs):
        raise AssertionError("an import must not reach the network")

    monkeypatch.setattr(socket, "socket", _no)
    monkeypatch.setattr(socket, "create_connection", _no)
    monkeypatch.setattr(socket, "getaddrinfo", _no)
    for export in (chatgpt_export(), claude_export(), gemini_export()):
        assert provider_import.read_export(export)["messages"] >= 1


# ── the origin and the confidence ─────────────────────────────────────────────

def test_an_import_is_trusted_less_than_something_learned_first_hand():
    """The relation is the fact; the number is a copy of it (`Law 6`).

    Below the floor and every import is silently discarded. At or above the
    first-hand default and *"lower confidence than something learned
    first-hand"* is simply false.
    """
    assert MIN_CONFIDENCE < IMPORT_CONFIDENCE_CEILING < DEFAULT_CONFIDENCE


def test_every_imported_memory_carries_where_it_came_from(store):
    out = store_imported(store, [{"text": "User drives a Transit van",
                                  "category": "fact"}],
                         provider_import.CHATGPT, owner="felix",
                         filename="conversations.json")
    assert len(out["stored"]) == 1
    row = store.load_all()[0]
    assert row["source"] == "import"
    assert row["provenance"]["producer"] == "provider_import:chatgpt"
    assert row["import_file"] == "conversations.json"
    assert row["confidence"] == IMPORT_CONFIDENCE_CEILING


def test_an_unverifiable_citation_is_not_invented(store):
    # `P13-03`: `quote` is the one field somebody reads to decide whether to
    # believe a memory, and the import prompt does not ask for one.
    store_imported(store, [{"text": "User drives a van"}], provider_import.CLAUDE)
    assert store.load_all()[0]["provenance"]["quote"] is None


def test_a_model_that_volunteers_less_confidence_is_believed(store):
    store_imported(store, [{"text": "User might drive a van", "confidence": 0.61}],
                   provider_import.CLAUDE)
    assert store.load_all()[0]["confidence"] == 0.61


def test_a_model_that_volunteers_more_confidence_is_capped(store):
    store_imported(store, [{"text": "User drives a van", "confidence": 1.0}],
                   provider_import.CLAUDE)
    assert store.load_all()[0]["confidence"] == IMPORT_CONFIDENCE_CEILING


def test_an_empty_or_one_word_fact_is_not_stored(store):
    # A model that answers `{"text": ""}` has answered nothing, and a memory
    # of "ok" is a row in the Brain that can never be useful.
    out = store_imported(store, [{"text": ""}, {"text": "ok"},
                                 {"text": "User drives a Transit van"}],
                         provider_import.CLAUDE)
    assert [e["text"] for e in out["stored"]] == ["User drives a Transit van"]


def test_a_fact_under_the_floor_is_counted_rather_than_swallowed(store):
    out = store_imported(store, [{"text": "User maybe drives", "confidence": 0.2},
                                 {"text": "User drives a van"}],
                         provider_import.CLAUDE)
    assert out["below_floor"] == 1
    assert len(out["stored"]) == 1


# ── what an import is allowed to do on its own ────────────────────────────────

def test_an_import_proposes_and_does_not_bind(store):
    """Thousands of messages nobody has read is the clearest case the proposal
    state was ever built for."""
    store_imported(store, [{"text": "User drives a Transit van"}],
                   provider_import.CHATGPT)
    row = store.load_all()[0]
    assert row["status"] == memory_edges.STATUS_PROPOSED
    assert memory_edges.live(store.load_all()) == []
    assert memory_retrieval.retrieve("van", store.load_all()) == []


def test_a_fact_the_brain_already_knows_is_recorded_as_a_restatement(store):
    """`P13-15`: the moment a fact is confirmed must not be the moment the
    observation is discarded. Saying a thing in ChatGPT last year and here is
    evidence, not a collision."""
    existing = store.add_entry("User drives a Transit van")
    store.save([existing])
    out = store_imported(store, [{"text": "User drives a Transit van"}],
                         provider_import.CHATGPT)
    assert out["duplicates"] == 1 and out["stored"] == []
    assert len(store.load_all()) == 1
    assert store.load_all()[0]["mentions"] == 1


def test_an_import_never_writes_over_a_store_it_could_not_read(store, monkeypatch):
    from src.memory import MemoryStoreUnreadable

    store.save([{"id": "keep", "text": "User drives a van", "category": "fact"}])
    raw = open(store.memory_file, encoding="utf-8").read()
    monkeypatch.setattr(store, "load_all_for_update",
                        lambda: (_ for _ in ()).throw(MemoryStoreUnreadable("gone")))
    out = store_imported(store, [{"text": "Something new entirely"}],
                         provider_import.CLAUDE)
    assert out["stored"] == []
    assert open(store.memory_file, encoding="utf-8").read() == raw


# ── the route, end to end ─────────────────────────────────────────────────────

def _import_route(manager, monkeypatch, reply, caller="felix"):
    from unittest.mock import MagicMock
    import routes.memory_routes as mr

    async def _fake_llm(*args, **kwargs):
        return reply

    monkeypatch.setattr(mr, "get_current_user", lambda request: caller, raising=False)
    monkeypatch.setattr("src.auth_helpers.require_privilege",
                        lambda request, privilege: caller)
    monkeypatch.setattr(mr, "resolve_task_endpoint",
                        lambda *a, **k: ("http://x", "m", {}))
    monkeypatch.setattr(mr, "llm_call_async", _fake_llm)
    router = mr.setup_memory_routes(manager, MagicMock())
    for route in router.routes:
        if route.path == "/api/memory/import":
            return route.endpoint
    raise AssertionError("no import route")


def _upload(payload, name="conversations.json"):
    from starlette.datastructures import UploadFile

    return UploadFile(filename=name,
                      file=io.BytesIO(json.dumps(payload).encode("utf-8")))


def test_a_chatgpt_export_becomes_proposals_with_their_origin(store, monkeypatch):
    endpoint = _import_route(store, monkeypatch, json.dumps(
        [{"text": "User drives a Transit van", "category": "fact"}]))
    out = asyncio.run(endpoint(request=None, session=None,
                               file=_upload(chatgpt_export())))
    assert out["provider"] == "chatgpt"
    assert out["conversations"] == 1 and out["messages"] == 2
    assert out["dropped_assistant"] == 1
    assert [s["text"] for s in out["suggestions"]] == ["User drives a Transit van"]
    assert out["suggestions"][0]["id"], "the reviewer needs the id, not the text"

    row = store.load_all()[0]
    assert row["status"] == memory_edges.STATUS_PROPOSED
    assert row["provenance"]["producer"] == "provider_import:chatgpt"
    assert row["confidence"] == IMPORT_CONFIDENCE_CEILING


def test_the_model_is_given_the_transcript_rather_than_the_raw_json(store, monkeypatch):
    """The measured premise: before this row, the model was handed braces."""
    seen = {}

    from unittest.mock import MagicMock
    import routes.memory_routes as mr

    async def _capture(url, model, messages, **kwargs):
        seen["prompt"] = messages[-1]["content"]
        return "[]"

    monkeypatch.setattr(mr, "get_current_user", lambda request: None, raising=False)
    monkeypatch.setattr("src.auth_helpers.require_privilege", lambda r, p: None)
    monkeypatch.setattr(mr, "resolve_task_endpoint", lambda *a, **k: ("http://x", "m", {}))
    monkeypatch.setattr(mr, "llm_call_async", _capture)
    router = mr.setup_memory_routes(store, MagicMock())
    endpoint = next(r.endpoint for r in router.routes
                    if r.path == "/api/memory/import")
    asyncio.run(endpoint(request=None, session=None, file=_upload(chatgpt_export())))
    assert "I drive a Transit van" in seen["prompt"]
    assert "create_time" not in seen["prompt"]
    assert "mapping" not in seen["prompt"]


def test_a_recognised_export_with_nothing_of_yours_in_it_says_so(store, monkeypatch):
    endpoint = _import_route(store, monkeypatch, "[]")
    only_assistant = [{"uuid": "u", "name": "n", "chat_messages": [
        {"sender": "assistant", "text": "Hello"}]}]
    out = asyncio.run(endpoint(request=None, session=None,
                               file=_upload(only_assistant)))
    assert out["suggestions"] == []
    assert out["provider"] == "claude"
    assert "claude export" in out["message"]


def test_a_file_that_sniffs_as_an_export_is_read_as_one(store, monkeypatch):
    """The generic memories fast path must not get first refusal.

    A file can satisfy both shapes — a conversation export beside a row that
    happens to carry a `text` key — and the fast path returns early. Without
    the exclusion the person gets one stray suggestion and none of their
    conversations, which looks like a successful import of almost nothing.
    """
    endpoint = _import_route(store, monkeypatch, json.dumps(
        [{"text": "User is allergic to shellfish", "category": "fact"}]))
    mixed = claude_export() + [{"text": "a stray memories row"}]
    out = asyncio.run(endpoint(request=None, session=None, file=_upload(mixed)))
    assert out.get("provider") == "claude"
    assert [s["text"] for s in out["suggestions"]] == \
        ["User is allergic to shellfish"]


def test_a_memories_export_still_takes_the_path_it_always_did(store, monkeypatch):
    """`Law 1`. A generic `.json` of `{text, category}` rows round-trips
    without an LLM call and without being persisted, exactly as before."""
    endpoint = _import_route(store, monkeypatch, "SHOULD NOT BE CALLED")
    out = asyncio.run(endpoint(request=None, session=None, file=_upload(
        [{"text": "User drives a van", "category": "fact"}], name="memories.json")))
    assert out["suggestions"] == [{"text": "User drives a van", "category": "fact"}]
    assert "provider" not in out
    assert store.load_all() == []


# ── the seam between an import and the memories it produces ───────────────────

def _add_route(manager, monkeypatch, caller="felix"):
    from unittest.mock import MagicMock
    import routes.memory_routes as mr

    monkeypatch.setattr(mr, "get_current_user", lambda request: caller, raising=False)
    monkeypatch.setattr("src.auth_helpers.require_privilege",
                        lambda request, privilege: caller)
    router = mr.setup_memory_routes(manager, MagicMock())
    for route in router.routes:
        if route.path == "/api/memory/add":
            return route.endpoint
    raise AssertionError("no add route")


def test_saving_a_proposal_from_the_review_list_binds_it(store, monkeypatch):
    """The branch that could never be reached before anything wrote proposals
    through a surface a person reviews.

    Without it, clicking *save* on an imported fact answers "Memory already
    exists" and the proposal sits unbound forever — a button that does nothing,
    which is the least visible failure this product can have (`P0-05`).
    """
    from src.request_models import MemoryAddRequest

    store_imported(store, [{"text": "User drives a Transit van"}],
                   provider_import.CHATGPT, owner="felix")
    endpoint = _add_route(store, monkeypatch)
    out = asyncio.run(endpoint(request=None, memory_data=MemoryAddRequest(
        text="User drives a Transit van", category="fact")))
    assert out["verdict"] == "committed"
    row = store.load_all()[0]
    assert row["status"] == memory_edges.STATUS_COMMITTED
    assert row["committed_by"] == "felix"
    assert len(store.load_all()) == 1, "binding must not write a second copy"
    assert memory_retrieval.retrieve("van", store.load_all())


def test_saving_something_already_committed_is_unchanged(store, monkeypatch):
    from src.request_models import MemoryAddRequest

    entry = store.add_entry("User drives a van", owner="felix")
    store.save([entry])
    endpoint = _add_route(store, monkeypatch)
    out = asyncio.run(endpoint(request=None, memory_data=MemoryAddRequest(
        text="User drives a van", category="fact")))
    assert out["message"] == "Memory already exists"
    assert "verdict" not in out
    assert len(store.load_all()) == 1


def test_saving_the_text_of_an_archived_memory_restores_it(store, monkeypatch):
    """`P13-04` and `P13-06` meeting: an archived memory is not committed, so
    the same branch brings it back rather than writing a duplicate."""
    from src.request_models import MemoryAddRequest

    entry = store.add_entry("User drives a van", owner="felix")
    store.save([entry])
    store.archive([entry["id"]])
    endpoint = _add_route(store, monkeypatch)
    out = asyncio.run(endpoint(request=None, memory_data=MemoryAddRequest(
        text="User drives a van", category="fact")))
    assert out["verdict"] == "committed"
    assert len(store.load_all()) == 1
    assert store.load_all()[0]["status"] == memory_edges.STATUS_COMMITTED
