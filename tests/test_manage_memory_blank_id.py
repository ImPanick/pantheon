# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1801`. A blank memory id edited or deleted the person's oldest memory.

The agent's `manage_memory` tool edits and deletes by id prefix: the first
stored memory whose id starts with the id it was given is the one changed. An
empty id is a prefix of every id, and nothing refused one, so an `edit` whose
line 2 was blank overwrote the first memory in the store (the oldest) and a
`delete` removed it, and both answered with success. The native function call
builds that shape whenever the model leaves `memory_id` out, which the schema
allows because add, list and search share it: `{"action": "edit", "text": t}`
becomes "edit\\n\\n" + t.

Now a blank or whitespace-only id is refused before the store is touched, and
an id or id prefix works as before. Ported from upstream Odysseus 6749d6cd
(#6342); its two cases are here, with the native call and the whitespace id
added.
"""
import asyncio

import pytest

from src import ai_interaction
from src.memory import MemoryManager
from src.tool_schemas import function_call_to_tool_block

FIRST = {"id": "aaaa1111-0000-4000-8000-000000000001", "text": "User prefers dark mode",
         "category": "preference", "owner": "alice", "timestamp": 1000}
SECOND = {"id": "bbbb2222-0000-4000-8000-000000000002", "text": "User lives in Lisbon",
          "category": "fact", "owner": "alice", "timestamp": 2000}


@pytest.fixture
def store(tmp_path, monkeypatch):
    manager = MemoryManager(str(tmp_path))
    manager.save([dict(FIRST), dict(SECOND)])
    monkeypatch.setattr(ai_interaction, "_memory_manager", manager)
    monkeypatch.setattr(ai_interaction, "_memory_vector", None)
    return manager


def _run(content):
    return asyncio.run(ai_interaction.do_manage_memory(content, owner="alice"))


def _texts(manager):
    return {m["id"]: m["text"] for m in manager.load_all()}


def test_a_delete_with_a_blank_id_deletes_nothing(store):
    result = _run(f"delete\n\n{SECOND['id']}")

    assert "error" in result and "memory_id" in result["error"]
    assert [m["id"] for m in store.load_all()] == [FIRST["id"], SECOND["id"]]


def test_an_edit_with_a_blank_id_overwrites_nothing(store):
    result = _run("edit\n\nUser lives in Berlin")

    assert "error" in result and "memory_id" in result["error"]
    assert _texts(store) == {FIRST["id"]: FIRST["text"], SECOND["id"]: SECOND["text"]}


def test_a_native_edit_that_leaves_out_the_memory_id_is_refused(store):
    block = function_call_to_tool_block(
        "manage_memory", '{"action": "edit", "text": "User lives in Berlin"}')
    assert block.content == "edit\n\nUser lives in Berlin"

    result = _run(block.content)

    assert "error" in result and "memory_id" in result["error"]
    assert "results" not in result, "the refusal must not also report an update"
    assert _texts(store)[FIRST["id"]] == FIRST["text"]


@pytest.mark.parametrize("content", [
    "edit\n   \nUser lives in Berlin",
    "edit\n\t\nUser lives in Berlin",
    f"delete\n  \n{SECOND['id']}",
])
def test_an_id_of_only_spaces_is_as_blank_as_an_empty_one(store, content):
    result = _run(content)

    assert "error" in result and "memory_id" in result["error"]
    assert _texts(store) == {FIRST["id"]: FIRST["text"], SECOND["id"]: SECOND["text"]}


def test_a_real_id_prefix_still_edits_and_deletes_only_its_own_memory(store):
    prefix = SECOND["id"][:8]

    edited = _run(f"edit\n{prefix}\nUser lives in Berlin")
    assert edited.get("action") == "edit", edited
    assert _texts(store) == {FIRST["id"]: FIRST["text"], SECOND["id"]: "User lives in Berlin"}

    deleted = _run(f"delete\n{prefix}")
    assert deleted.get("action") == "delete", deleted
    assert [m["id"] for m in store.load_all()] == [FIRST["id"]]


def test_a_native_delete_without_an_id_still_asks_for_one(store):
    block = function_call_to_tool_block("manage_memory", '{"action": "delete"}')

    result = _run(block.content)

    assert result == {"error": "Delete needs line 2: memory_id"}
    assert len(store.load_all()) == 2
