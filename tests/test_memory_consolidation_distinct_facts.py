# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1947`. Memory Tidy deleted different facts as if they were duplicates.

Memory Tidy (the built-in `consolidate_memory` task, on by default and run
after every fifth memory) removes duplicates before it asks a model, and that
pass deletes outright: nobody is asked and nothing is archived. It called two
memories one fact when their text was 88% alike, when the shorter one (24
characters or more) sat inside the longer, or when they matched after every
character outside a-z, 0-9 and a little punctuation had been turned into a
space. So "User is not allergic to peanuts." went as a copy of "User is
allergic to peanuts.", Bjorn as a copy of Bjarne, 16 servers as 64, and two
Cyrillic memories whose letters had all been erased. The shorter text ranked
higher, so a memory that added an exception was the one deleted. When no
model answered, a second pass deleted again by text alone, across categories.

Now only the same text, after case, spacing and Unicode form, in the same
category is a duplicate. Everything else is left for the AI step, which
deletes only what the model explicitly drops.

Ported from upstream Odysseus 2b2c3ae2 (PR #6955); the cases are upstream's,
plus one for a longer memory that adds an exception. Only the data directory
and endpoint discovery are replaced: no model is called and no real store is
read or changed.
"""

import json

import pytest

from tests.test_builtin_memory_consolidation import _import_consolidate_action


@pytest.fixture
def consolidate_without_model(monkeypatch, tmp_path):
    from src import constants, task_endpoint

    action = _import_consolidate_action()
    from src.builtin_actions import TaskNoop

    data_dir = tmp_path / "memory-data"
    data_dir.mkdir()
    memory_file = data_dir / "memory.json"
    monkeypatch.setattr(constants, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(task_endpoint, "resolve_task_candidates", lambda *args, **kwargs: [])

    async def run(memories):
        for memory in memories:
            memory.update(timestamp=1, source="user", uses=0)
        memory_file.write_text(json.dumps(memories, ensure_ascii=False), encoding="utf-8")
        try:
            message, ok = await action("test-owner")
            assert ok, message
        except TaskNoop:
            pass
        saved = json.loads(memory_file.read_text(encoding="utf-8"))
        # Pantheon's store fills in its own fields (kind, status, mentions,
        # edges, ...) when it loads a row, and a save writes them, so compare
        # each row on the fields this test wrote.
        written = {memory["id"]: set(memory) for memory in memories}
        return [
            {key: value for key, value in row.items() if key in written.get(row.get("id"), ())}
            for row in saved
        ]

    return run


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("left", "right"),
    [
        pytest.param("Dog is named Bjorn.", "Dog is named Bjarne.", id="different-names"),
        pytest.param("Møte med Åse torsdag", "Møte med Åge torsdag", id="norwegian-names"),
        pytest.param("User runs 16 local servers.", "User runs 64 local servers.", id="different-numbers"),
        pytest.param("User wants notifications enabled.", "User wants notifications disabled.", id="opposite-setting"),
        pytest.param("User is allergic to peanuts.", "User is not allergic to peanuts.", id="negated-fact"),
        pytest.param("User works with Müller.", "User works with Möller.", id="diacritic-collision"),
        pytest.param("User lives in Oslo.", "User lives in Otta.", id="different-places"),
        pytest.param("Кота зовут Барсик.", "Кота зовут Мурзик.", id="cyrillic"),
        pytest.param("猫の名前はミケです。", "猫の名前はタマです。", id="japanese"),
        pytest.param("The storage bucket is backup", "The storage bucket is backups", id="substring-value"),
        pytest.param("User is now here.", "User is nowhere.", id="word-boundaries"),
        pytest.param("User's account is user.name", "User's account is username", id="significant-punctuation"),
        pytest.param("User takes the 8:15 train to work",
                     "User takes the 8:15 train to work, except on Fridays when they cycle",
                     id="longer-adds-an-exception"),
    ],
)
async def test_consolidation_preserves_distinct_facts(consolidate_without_model, left, right):
    memories = [
        {"id": "left", "owner": "test-owner", "text": left, "category": "fact"},
        {"id": "right", "owner": "test-owner", "text": right, "category": "fact"},
    ]

    assert await consolidate_without_model(memories) == memories


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("left", "right"),
    [
        pytest.param("User likes local models.", "  USER likes   local models.  ", id="case-whitespace"),
        pytest.param("Møte med Åse torsdag.", "Møte med Åse torsdag.", id="canonical-unicode"),
        pytest.param("Кота зовут Барсик.", "Кота зовут Барсик.", id="cyrillic-exact"),
        pytest.param("猫の名前はミケです。", "猫の名前はミケです。", id="japanese-exact"),
        pytest.param("User lives on Straße.", "User lives on STRASSE.", id="unicode-casefold"),
    ],
)
async def test_consolidation_deduplicates_equivalent_text_and_keeps_pinned(
    consolidate_without_model, left, right
):
    memories = [
        {"id": "left", "owner": "test-owner", "text": left, "category": "fact"},
        {"id": "right", "owner": "test-owner", "text": right, "category": "fact", "pinned": True},
    ]

    assert await consolidate_without_model(memories) == [memories[1]]


@pytest.mark.asyncio
async def test_consolidation_preserves_same_text_in_different_categories(consolidate_without_model):
    memories = [
        {"id": "fact", "owner": "test-owner", "text": "Keep this record.", "category": "fact"},
        {"id": "instruction", "owner": "test-owner", "text": "Keep this record.", "category": "instruction"},
    ]

    assert await consolidate_without_model(memories) == memories
