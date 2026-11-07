# SPDX-License-Identifier: AGPL-3.0-or-later
import json
import sys

import pytest


def _import_consolidate_action():
    mod = sys.modules.get("src.builtin_actions")
    if mod is not None and not hasattr(mod, "action_consolidate_memory"):
        sys.modules.pop("src.builtin_actions", None)
        if "src" in sys.modules and hasattr(sys.modules["src"], "builtin_actions"):
            delattr(sys.modules["src"], "builtin_actions")
    from src.builtin_actions import action_consolidate_memory

    return action_consolidate_memory


def _write_memories(tmp_path, memories):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "memory.json").write_text(json.dumps(memories), encoding="utf-8")
    return data_dir


def _read_memories(data_dir):
    return json.loads((data_dir / "memory.json").read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_consolidate_memory_empty_owner_treats_each_owner_separately(monkeypatch, tmp_path):
    from src import constants
    from src import llm_core
    from src import task_endpoint
    action_consolidate_memory = _import_consolidate_action()

    long_alice_text = "Alice private project context. " + ("A" * 2200)
    data_dir = _write_memories(
        tmp_path,
        [
            {"id": "alice-long", "owner": "alice", "text": long_alice_text, "category": "project"},
            {"id": "alice-short", "owner": "alice", "text": "Alice likes quiet summaries.", "category": "preference"},
            {"id": "bob-keep", "owner": "bob", "text": "Bob secret deployment note.", "category": "project"},
            {"id": "bob-drop", "owner": "bob", "text": "Bob secret deployment note duplicate.", "category": "project"},
        ],
    )
    monkeypatch.setattr(constants, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(
        task_endpoint,
        "resolve_task_candidates",
        lambda *args, **kwargs: [("http://llm", "model", {})],
    )

    prompts = []

    async def fake_llm_call_async(_candidates, **kwargs):
        prompt = kwargs["messages"][0]["content"]
        prompts.append(prompt)
        if "alice-long" in prompt:
            assert "bob-keep" not in prompt
            return json.dumps(
                {
                    "keep": [
                        {"id": "alice-long", "text": "TRUNCATED REWRITE", "category": "project"},
                        {"id": "alice-short", "text": "Alice likes concise summaries.", "category": "preference"},
                    ],
                    "drop": [],
                }
            )
        assert "bob-keep" in prompt
        assert "alice-long" not in prompt
        return json.dumps(
            {
                "keep": [{"id": "bob-keep", "text": "Bob secret deployment note.", "category": "project"}],
                "drop": [{"id": "bob-drop", "reason": "duplicate"}],
            }
        )

    monkeypatch.setattr(llm_core, "llm_call_async_with_fallback", fake_llm_call_async)

    message, ok = await action_consolidate_memory("")

    assert ok is True
    assert "removed 1" in message.lower()
    assert len(prompts) == 2
    saved = {m["id"]: m for m in _read_memories(data_dir)}
    assert set(saved) == {"alice-long", "alice-short", "bob-keep"}
    assert saved["alice-long"]["text"] == long_alice_text
    assert saved["alice-short"]["text"] == "Alice likes concise summaries."


@pytest.mark.asyncio
async def test_consolidate_memory_specific_owner_does_not_absorb_ownerless_rows(monkeypatch, tmp_path):
    from src import constants
    from src import endpoint_resolver
    action_consolidate_memory = _import_consolidate_action()

    data_dir = _write_memories(
        tmp_path,
        [
            {"id": "alice-1", "owner": "alice", "text": "Alice likes local models.", "category": "preference"},
            {"id": "alice-2", "owner": "alice", "text": "Alice likes local models.", "category": "preference"},
            {"id": "legacy", "text": "Alice likes local models.", "category": "preference"},
            {"id": "bob-1", "owner": "bob", "text": "Bob likes hosted models.", "category": "preference"},
        ],
    )
    monkeypatch.setattr(constants, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(endpoint_resolver, "resolve_endpoint", lambda *args, **kwargs: ("", "", {}))

    message, ok = await action_consolidate_memory("alice")

    assert ok is True
    assert "Removed 1 duplicate" in message
    saved = {m["id"]: m for m in _read_memories(data_dir)}
    assert set(saved) == {"alice-1", "legacy", "bob-1"}
    assert "owner" not in saved["legacy"]
    assert saved["bob-1"]["owner"] == "bob"


@pytest.mark.asyncio
async def test_consolidate_memory_leaves_near_duplicates_for_ai(monkeypatch, tmp_path):
    """`B1947`. A near-duplicate is the model's call, not the text match's.

    "bullet points" and "bulletpoints" used to be merged before the model
    was asked, by the same fuzzy rule that merged "allergic" with "not
    allergic". Now all three memories reach the model, and the one it
    drops is the one that goes. Upstream Odysseus 2b2c3ae2 (#6955)."""
    from src import constants
    from src import llm_core
    from src import task_endpoint
    action_consolidate_memory = _import_consolidate_action()

    data_dir = _write_memories(
        tmp_path,
        [
            {"id": "a", "owner": "alice", "text": "User prefers bullet points when explaining.", "category": "preference"},
            {"id": "b", "owner": "alice", "text": "User prefers bulletpoints when explaining", "category": "preference", "pinned": True},
            {"id": "c", "owner": "alice", "text": "User likes local models.", "category": "preference"},
        ],
    )
    monkeypatch.setattr(constants, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(
        task_endpoint,
        "resolve_task_candidates",
        lambda *args, **kwargs: [("http://llm", "model", {})],
    )

    received_ids = []

    async def fake_llm_call_async(_candidates, **kwargs):
        items = json.loads(kwargs["messages"][0]["content"].split("MEMORIES:\n", 1)[1])
        received_ids.append({item["id"] for item in items})
        return json.dumps({
            "keep": [
                {"id": item["id"], "text": item["text"], "category": item["category"]}
                for item in items
                if item["id"] != "a"
            ],
            "drop": [{"id": "a", "reason": "Same preference as pinned b"}],
        })

    monkeypatch.setattr(llm_core, "llm_call_async_with_fallback", fake_llm_call_async)

    message, ok = await action_consolidate_memory("alice")

    assert ok is True
    assert "removed 1" in message.lower()
    saved = {m["id"]: m for m in _read_memories(data_dir)}
    assert set(saved) == {"b", "c"}
    assert saved["b"]["pinned"] is True
    assert received_ids == [{"a", "b", "c"}]


@pytest.mark.asyncio
async def test_a_style_profile_still_forming_survives_the_tidy(monkeypatch, tmp_path):
    """`B1952`. The style profile (`P13-17`) is not a memory. It has no text
    until twenty messages give it some, only the counters folded in so far,
    and the duplicate pass deleted every row with empty text, so each tidy
    before then threw the counts away and the profile started over."""
    from src import constants
    from src import memory_style
    from src import task_endpoint
    action_consolidate_memory = _import_consolidate_action()

    style = {"id": "style", "owner": "alice", "text": "", "category": "style",
             "kind": memory_style.KIND_STYLE, "source": "auto",
             "style": {"messages": 12, "words": 180}}
    data_dir = _write_memories(
        tmp_path,
        [
            style,
            {"id": "a", "owner": "alice", "text": "Alice likes local models.", "category": "preference"},
            {"id": "b", "owner": "alice", "text": "Alice likes local models.", "category": "preference"},
        ],
    )
    monkeypatch.setattr(constants, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(task_endpoint, "resolve_task_candidates", lambda *args, **kwargs: [])

    message, ok = await action_consolidate_memory("alice")

    assert ok is True
    assert "Removed 1 duplicate" in message
    saved = {m["id"]: m for m in _read_memories(data_dir)}
    assert set(saved) == {"style", "a"}
    assert saved["style"]["style"] == {"messages": 12, "words": 180}


@pytest.mark.asyncio
async def test_a_formed_style_profile_is_never_handed_to_the_model(monkeypatch, tmp_path):
    """`B1952`. Once formed, the profile went to the model as a memory to
    tidy, which may drop it or "clean" its text. A text the person corrected
    (`style_edited`) is never re-rendered, so the model's version replaced
    their correction for good."""
    from src import constants
    from src import llm_core
    from src import memory_style
    from src import task_endpoint
    action_consolidate_memory = _import_consolidate_action()

    data_dir = _write_memories(
        tmp_path,
        [
            {"id": "style", "owner": "alice", "text": "Writes in short lines, no greeting.",
             "category": "style", "kind": memory_style.KIND_STYLE, "source": "auto",
             "style": {"messages": 40}, "style_edited": 1},
            {"id": "a", "owner": "alice", "text": "Alice likes local models.", "category": "preference"},
            {"id": "b", "owner": "alice", "text": "Alice prefers local models.", "category": "preference"},
        ],
    )
    monkeypatch.setattr(constants, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(
        task_endpoint,
        "resolve_task_candidates",
        lambda *args, **kwargs: [("http://llm", "model", {})],
    )
    received_ids = []

    async def fake_llm_call_async(_candidates, **kwargs):
        items = json.loads(kwargs["messages"][0]["content"].split("MEMORIES:\n", 1)[1])
        received_ids.append({item["id"] for item in items})
        keep = [{"id": "a", "text": "Alice likes local models.", "category": "preference"}]
        if "style" in received_ids[-1]:
            keep.append({"id": "style", "text": "The user writes tersely.", "category": "preference"})
        return json.dumps({"keep": keep, "drop": [{"id": "b", "reason": "Same as a"}]})

    monkeypatch.setattr(llm_core, "llm_call_async_with_fallback", fake_llm_call_async)

    message, ok = await action_consolidate_memory("alice")

    assert ok is True
    assert received_ids == [{"a", "b"}]
    saved = {m["id"]: m for m in _read_memories(data_dir)}
    assert set(saved) == {"style", "a"}
    assert saved["style"]["text"] == "Writes in short lines, no greeting."
    assert saved["style"]["category"] == "style"


@pytest.mark.asyncio
async def test_what_is_written_while_the_model_thinks_is_kept(monkeypatch, tmp_path):
    """`B1953`. The tidy read the store, waited for the chat to go quiet,
    asked the model (up to two minutes a group) and saved the copy it had
    read. It runs on `memory_added`, so memories were being written in that
    window and the save overwrote them. Now it applies its own changes to the
    store as it is when it saves, and only to rows that still say what it read."""
    from src import constants
    from src import llm_core
    from src import task_endpoint
    from src.memory import MemoryManager
    action_consolidate_memory = _import_consolidate_action()

    data_dir = _write_memories(
        tmp_path,
        [
            {"id": "a", "owner": "alice", "text": "Alice likes local models.", "category": "preference"},
            {"id": "b", "owner": "alice", "text": "Alice prefers local models.", "category": "preference"},
            {"id": "c", "owner": "alice", "text": "Alice lives in Oslo.", "category": "fact"},
            {"id": "d", "owner": "alice", "text": "Alice has a cat.", "category": "fact"},
            {"id": "e", "owner": "alice", "text": "Alice drinks tea.", "category": "preference"},
        ],
    )
    monkeypatch.setattr(constants, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(
        task_endpoint,
        "resolve_task_candidates",
        lambda *args, **kwargs: [("http://llm", "model", {})],
    )

    async def fake_llm_call_async(_candidates, **kwargs):
        # While the model thinks: extraction adds a memory, the person deletes
        # one and corrects another, and a chat recalls a third.
        store = MemoryManager(str(data_dir))
        rows = [r for r in store.load_all_for_update() if r["id"] != "d"]
        for row in rows:
            if row["id"] == "e":
                row["text"] = "Alice drinks green tea."
        new = store.add_entry("Alice is learning Norwegian.", owner="alice")
        store.save(rows + [new])
        store.increment_uses(["c"])
        return json.dumps({
            "keep": [
                {"id": "a", "text": "Alice likes local models.", "category": "preference"},
                {"id": "c", "text": "Alice lives in Oslo, Norway.", "category": "fact"},
            ],
            "drop": [{"id": "b", "reason": "Same as a"}, {"id": "e", "reason": "Trivial"}],
        })

    monkeypatch.setattr(llm_core, "llm_call_async_with_fallback", fake_llm_call_async)

    message, ok = await action_consolidate_memory("alice")

    assert ok is True, message
    saved = {m["text"]: m for m in _read_memories(data_dir)}
    # The model's own verdicts still land: b goes, c is rewritten.
    assert "Alice prefers local models." not in saved
    assert saved["Alice lives in Oslo, Norway."]["id"] == "c"
    # What was written meanwhile stays: the new memory, the recall, the
    # deletion, and the correction the model never saw.
    assert "Alice is learning Norwegian." in saved
    assert saved["Alice lives in Oslo, Norway."]["uses"] == 1
    assert "Alice has a cat." not in saved
    assert saved["Alice drinks green tea."]["id"] == "e"
    assert set(saved) == {"Alice likes local models.", "Alice lives in Oslo, Norway.",
                          "Alice is learning Norwegian.", "Alice drinks green tea."}
