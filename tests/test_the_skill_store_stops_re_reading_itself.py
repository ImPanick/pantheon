# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P8-19` — parsing the whole library on every request that mentions skills.

`load_all()` walked the store and ran `Skill.from_markdown` on every file it
found, and it is called at least three times per agent request: once by
`_build_base_prompt` for the index, once by `_build_system_prompt` for the
matched-skills block, and once more by the tool-RAG pass that widens the tool set
from a skill's `requires_toolsets`. Every route that lists, reads or saves a
skill calls it again. The bundled library is **286 `SKILL.md` files and 2.5 MB of
markdown** (`library/ecc/skills`, measured 2026-09-18) that never change between
releases, and all of it was re-parsed each time.

`SkillsManager` is constructed fresh at every one of those call sites —
`SkillsManager(DATA_DIR)` — so the cache has to be module-level or it is a cache
that is always cold. It is keyed on `(st_mtime_ns, st_size, st_ino)`: the walk
still happens, because that is how a new or deleted skill is noticed, and what
is skipped is re-parsing bytes that have already been parsed.

The correctness half is the half worth testing hardest. A stale skill index is
worse than a slow one — it is the model being told a procedure exists that was
deleted, or being handed the version before the fix.
"""

import textwrap
import time
from pathlib import Path

import pytest

import services.memory.skill_format as skill_format
from services.memory.skills import SkillsManager, invalidate_skill_cache


def _write(root: Path, name: str, *, description="a test procedure", category="ops"):
    d = root / category / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(textwrap.dedent(f"""\
        ---
        name: {name}
        description: {description}
        version: 1.0.0
        category: {category}
        tags: []
        status: published
        confidence: 0.9
        source: learned
        created: 2026-01-01T00:00:00Z
        ---

        ## When to Use

        when the test says so

        ## Procedure

        1. do the thing
        """), encoding="utf-8")
    return d / "SKILL.md"


@pytest.fixture
def counting(monkeypatch):
    """How many SKILL.md files were actually parsed."""
    calls = []
    real = skill_format.Skill.from_markdown

    def counted(text, *, path=None):
        calls.append(path)
        return real(text, path=path)

    monkeypatch.setattr(skill_format.Skill, "from_markdown", staticmethod(counted))
    invalidate_skill_cache()
    return calls


@pytest.fixture
def store(tmp_path):
    root = tmp_path / "skills"
    for i in range(12):
        _write(root, f"skill-{i:02d}")
    invalidate_skill_cache()
    return SkillsManager(str(tmp_path), library_root="")


def test_the_second_read_of_an_unchanged_store_parses_nothing(store, counting):
    first = store.load_all()
    parsed_first = len(counting)
    assert parsed_first == 12, parsed_first

    counting.clear()
    second = store.load_all()
    assert counting == [], (
        f"{len(counting)} files re-parsed for a store nothing had touched"
    )
    assert [s["name"] for s in first] == [s["name"] for s in second]


def test_one_agent_request_worth_of_reads_parses_the_library_once(store, counting):
    # The shape of a real turn: the index, the relevance pass and the tool-RAG
    # pass, each constructing its own manager because that is what the loop does.
    data_dir = store.data_dir
    SkillsManager(data_dir, library_root="").index_for(owner=None)
    SkillsManager(data_dir, library_root="").load(owner=None)
    SkillsManager(data_dir, library_root="").load_all()
    assert len(counting) == 12, (
        f"{len(counting)} parses for 12 skills across one turn's three reads"
    )


def test_an_edited_skill_is_seen_immediately(store, counting):
    store.load_all()
    path = Path(store.skills_root) / "ops" / "skill-00" / "SKILL.md"
    path.write_text(path.read_text(encoding="utf-8")
                    .replace("a test procedure", "the description after the edit"),
                    encoding="utf-8")

    after = {s["name"]: s["description"] for s in store.load_all()}
    assert after["skill-00"] == "the description after the edit"


def test_a_write_through_the_manager_is_seen_immediately(store):
    store.load_all()
    assert store.update_skill("skill-00", {"description": "edited via the manager"},
                              owner=None) is True
    after = {s["name"]: s["description"] for s in store.load_all()}
    assert after["skill-00"] == "edited via the manager"


def test_a_new_skill_appears_and_a_deleted_one_disappears(store):
    before = {s["name"] for s in store.load_all()}
    _write(Path(store.skills_root), "skill-99")
    assert "skill-99" in {s["name"] for s in store.load_all()}

    assert store.delete_skill("skill-99", owner=None) is True
    assert "skill-99" not in {s["name"] for s in store.load_all()}
    assert before == {s["name"] for s in store.load_all()}


def test_an_edit_within_the_same_clock_tick_is_not_missed(store):
    # The reason the key is not mtime alone. `atomic_write_text` replaces the
    # file, so the inode moves even where a filesystem's mtime granularity
    # would hide a fast rewrite.
    store.load_all()
    for i in range(6):
        store.update_skill("skill-01", {"description": f"rev {i}"}, owner=None)
        seen = {s["name"]: s["description"] for s in store.load_all()}
        assert seen["skill-01"] == f"rev {i}", (
            f"iteration {i}: the store returned {seen['skill-01']!r}"
        )


def test_what_a_caller_mutates_does_not_leak_into_the_next_read(store):
    # `load_all` writes the usage counters onto the dict it hands back, and
    # every route returns these straight to a caller. A cached dict handed out
    # by reference would accumulate whatever anybody did to it.
    first = store.load_all()
    first[0]["description"] = "scribbled on"
    first[0]["tags"].append("scribbled")
    first[0]["uses"] = 999

    second = store.load_all()
    assert second[0]["description"] != "scribbled on"
    assert "scribbled" not in second[0]["tags"]
    assert second[0]["uses"] == 0


def test_the_bundled_library_is_cached_the_same_way(tmp_path, counting):
    library = tmp_path / "library"
    for i in range(5):
        _write(library, f"bundled-{i}")
    sm = SkillsManager(str(tmp_path / "data"), library_root=str(library))

    assert len(sm.load_all()) == 5
    assert len(counting) == 5
    counting.clear()
    assert len(sm.load_all()) == 5
    assert counting == []


def test_reading_one_skill_no_longer_parses_the_whole_store(store, counting):
    store.load_all()
    counting.clear()
    md = store.read_skill_md("skill-07", owner=None)
    assert md and "skill-07" in md
    assert counting == [], f"{len(counting)} files parsed to read one skill"
