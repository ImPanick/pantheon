# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B591` — a `SKILL.md` inside a skill's own folder is one of its files.

`_iter_skill_files` yielded every directory under `data/skills/` holding a
`SKILL.md`, at any depth, so an example file shipped as `references/SKILL.md`
became a second skill with a card, an index entry, a line in the model's prompt
and a slot in the namespace `add_skill` uniquifies against — a later real skill
of that name was silently saved as `name-2`. The read-only library layers walked
the same way. And `pick_skill_md` took the first `SKILL.md` in a bundle in dict
order, so a bundle listing the example first installed the example.

Driven through the real `SkillsManager` on a temp store and a temp library.
"""
from __future__ import annotations

import textwrap

from services.memory.skills import SkillsManager


def _md(name: str, description: str) -> str:
    return textwrap.dedent(f"""\
        ---
        name: {name}
        description: {description}
        category: general
        status: published
        confidence: 0.9
        ---

        ## When to Use
        when {name} applies

        ## Procedure
        1. do {name}
        """)


OUTER = _md("outer", "the real skill")
INNER = _md("inner", "an example file shipped with the real skill")


def test_a_nested_skill_md_is_not_a_second_skill(tmp_path):
    root = tmp_path / "skills" / "general" / "outer"
    (root / "references").mkdir(parents=True)
    (root / "SKILL.md").write_text(OUTER, encoding="utf-8")
    (root / "references" / "SKILL.md").write_text(INNER, encoding="utf-8")
    sm = SkillsManager(str(tmp_path), library_root="")

    assert [s["name"] for s in sm.load_all()] == ["outer"]
    assert [s["name"] for s in sm.index_for()] == ["outer"]
    # Readable as what it is: one of the skill's references.
    assert sm.read_skill_reference("outer", "references/SKILL.md") == INNER
    # And it holds no name: a real skill called `inner` keeps its name.
    made = sm.add_skill(name="inner", description="a real one", procedure=["x"],
                        source="user")
    assert made["name"] == "inner"


def test_the_shipped_library_walks_the_same_way(tmp_path):
    lib = tmp_path / "library"
    (lib / "outer" / "references").mkdir(parents=True)
    (lib / "outer" / "SKILL.md").write_text(OUTER, encoding="utf-8")
    (lib / "outer" / "references" / "SKILL.md").write_text(INNER, encoding="utf-8")
    sm = SkillsManager(str(tmp_path / "data"), library_root=str(lib))

    assert [s["name"] for s in sm.load_all()] == ["outer"]
    assert sm.read_skill_reference("outer", "references/SKILL.md",
                                   include_library=True) == INNER


def test_a_bundle_listing_its_example_first_installs_the_skill(tmp_path):
    """The bundle shape `import_bundle_from_files` reads — a download handed
    back, or a fetched folder — with the example ahead of the skill."""
    sm = SkillsManager(str(tmp_path), library_root="")
    entry = sm.import_bundle_from_files(
        {"references/SKILL.md": INNER, "SKILL.md": OUTER, "references/notes.md": "notes"},
        owner=None)
    assert entry["name"] == "outer"
    assert [s["name"] for s in sm.load_all()] == ["outer"]
    assert sm.read_skill_reference("outer", "references/SKILL.md") == INNER
