# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1500` — the package importer does not make a nested SKILL.md its own skill.

The row (the remainder of `B591`): `_choose_folders`' last fallback — *any
folder at all*, for repositories of loose skills — took every folder holding a
SKILL.md, so `x/references/SKILL.md` shipped as an example became a separate
package skill. Measured on `ffaf6671` with a repository of loose skills one
level down (`tools/<name>/`, nothing at the top level and no `skills/` folder,
which is the shape that reaches the fallback): `tools/sweep` and
`tools/sweep/references` both installed, and the example took a card, an index
line and a name in the store.

Driven through the real importer against the fake GitHub the package tests use,
and through the real `SkillsManager.install_package`.

`Verify:` a loose-skills repository whose skill carries `references/SKILL.md`
installs one skill.
"""
from __future__ import annotations

import services.memory.skill_importer as si
from services.memory.skills import SkillsManager
from tests.test_a_skill_package_arrives_as_a_package import _md, _tarball, github  # noqa: F401

LOOSE = {
    "tools/sweep/SKILL.md": _md("sweep"),
    "tools/sweep/references/SKILL.md": _md("example-of-a-skill"),
    "tools/sweep/references/notes.md": "how the example works",
}


def test_a_loose_skill_carrying_references_skill_md_is_one_skill(github):
    github({"a/loose-nested/main": _tarball(LOOSE)})
    pkg = si.fetch_skill_package("https://github.com/a/loose-nested")
    assert [(s.folder, s.name) for s in pkg.skills] == [("tools/sweep", "sweep")]
    sweep = pkg.skills[0]
    # The example is one of its files, where its own SKILL.md can point at it.
    assert sorted(sweep.files) == ["SKILL.md", "references/SKILL.md", "references/notes.md"]


def test_it_installs_one_skill(github, tmp_path):
    github({"a/loose-nested/main": _tarball(LOOSE)})
    pkg = si.fetch_skill_package("https://github.com/a/loose-nested")
    sm = SkillsManager(str(tmp_path), library_root="")
    sm.install_package(pkg, owner="alice")
    assert [s["name"] for s in sm.load(owner="alice")] == ["sweep"]


def test_two_loose_skills_side_by_side_are_still_two(github):
    """The fallback exists for repositories of loose skills; siblings stay."""
    github({"a/loose-pair/main": _tarball({
        "tools/sweep/SKILL.md": _md("sweep"),
        "tools/sweep/references/SKILL.md": _md("example-of-a-skill"),
        "tools/tidy/SKILL.md": _md("tidy"),
    })})
    pkg = si.fetch_skill_package("https://github.com/a/loose-pair")
    assert sorted(s.name for s in pkg.skills) == ["sweep", "tidy"]
