# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pantheon ships 286 skills and reaches nothing to do it.

The library is ECC (https://github.com/affaan-m/ECC, MIT), vendored under
`library/ecc/` and pinned to a named upstream commit. It exists because the
formats already matched: ECC writes `name:`/`description:` YAML frontmatter in
SKILL.md, which is exactly what `skill_format.parse_frontmatter` reads. Nothing
needed converting.

Two properties matter more than the count:

  * **Offline.** `Law 16` -- a fresh install has all 286 with no network.
  * **Read-only, and off every write path.** `_iter_skill_files` has three
    callers and one of them (`backfill_owner`) *rewrites* every file it is
    handed. Folding the library into that iterator would not merely surface it;
    it would rewrite vendored files in place on the next owner backfill.
"""
import json
import pathlib
import tempfile

import pytest

from services.memory.skills import SkillsManager

REPO = pathlib.Path(__file__).resolve().parent.parent
LIB = REPO / "library" / "ecc"


@pytest.fixture
def mgr():
    with tempfile.TemporaryDirectory() as d:
        yield SkillsManager(d)


def test_the_library_ships_in_the_repo_not_the_data_dir():
    """`data/` is disposable here. The library must survive wiping it."""
    assert (LIB / "skills").is_dir()
    assert (LIB / "MANIFEST.json").is_file()
    assert (LIB / "LICENSE").is_file()


def test_a_fresh_install_has_the_whole_library_with_no_network(mgr):
    skills = mgr.load_all()
    bundled = [s for s in skills if s.get("bundled")]
    assert len(bundled) >= 250, f"only {len(bundled)} bundled skills loaded"


def test_every_bundled_skill_parses(mgr):
    """The compatibility claim, checked rather than asserted."""
    dirs = [d for d in (LIB / "skills").iterdir() if d.is_dir()]
    loaded = {s["name"] for s in mgr.load_all() if s.get("bundled")}
    assert len(loaded) == len(dirs), (
        f"{len(dirs)} skill directories but {len(loaded)} loaded -- "
        f"{len(dirs) - len(loaded)} failed to parse"
    )


def test_bundled_skills_are_marked_read_only(mgr):
    for s in mgr.load_all():
        if s.get("bundled"):
            assert s["editable"] is False
            assert s["source"] == "bundled"


def test_the_library_is_not_on_the_write_path(mgr):
    """The bug this separation exists to prevent.

    `backfill_owner` rewrites every file `_iter_skill_files` yields. If the
    library were in that iterator, an owner backfill would rewrite 286 vendored
    files in place -- silently, and only visible as a dirty git tree.
    """
    writable = list(mgr._iter_skill_files())
    lib = str(LIB.resolve())
    intruders = [p for p in writable if str(pathlib.Path(p).resolve()).startswith(lib)]
    assert not intruders, f"library files are reachable from the write path: {intruders[:3]}"


def test_a_user_skill_shadows_a_bundled_one_of_the_same_name(mgr):
    """The fork mechanism: save over a bundled name and yours wins, no merge."""
    bundled = [s for s in mgr.load_all() if s.get("bundled")]
    victim = bundled[0]["name"]

    d = pathlib.Path(mgr.skills_root) / "general" / victim
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {victim}\ndescription: mine, not theirs\n---\n\n# Mine\n",
        encoding="utf-8",
    )

    after = {s["name"]: s for s in mgr.load_all()}
    assert after[victim].get("bundled") is not True, "the bundled copy won over the user's"
    assert "mine, not theirs" in after[victim]["description"]
    assert sum(1 for s in mgr.load_all() if s["name"] == victim) == 1, "the skill is duplicated"


def test_the_manifest_pins_a_named_upstream_commit():
    """"Ship the latest" is not a version. A pin is what makes an update reviewable."""
    m = json.loads((LIB / "MANIFEST.json").read_text(encoding="utf-8"))
    assert m["source"] == "https://github.com/affaan-m/ECC"
    assert m["licence"] == "MIT"
    assert len(m["commit"]) == 40, "the manifest does not pin a full commit sha"
    assert m["skills"] == len(m["files"])
    assert m["version"]


def test_the_manifest_checksums_match_what_is_on_disk():
    """An update that changed a file without changing the manifest would be invisible."""
    import hashlib

    m = json.loads((LIB / "MANIFEST.json").read_text(encoding="utf-8"))
    drifted = []
    for name, expected in m["files"].items():
        f = LIB / "skills" / name / "SKILL.md"
        if not f.exists():
            drifted.append((name, "missing")); continue
        got = hashlib.sha256(f.read_text(encoding="utf-8").encode()).hexdigest()[:16]
        if got != expected:
            drifted.append((name, "changed"))
    assert not drifted, f"library drifted from its manifest: {drifted[:5]}"


def test_the_licence_travels_with_the_code():
    """MIT's one obligation. P0 is meticulous about this and so is this row."""
    text = (LIB / "LICENSE").read_text(encoding="utf-8")
    assert "MIT License" in text
    assert "Affaan Mustafa" in text
    assert (REPO / "licenses" / "ECC-MIT.txt").is_file()
    credits = (REPO / "CREDITS.md").read_text(encoding="utf-8")
    assert "affaan-m/ECC" in credits, "the library is not attributed in CREDITS.md"


def test_no_third_party_executables_were_vendored():
    """We ship prose an agent reads, not code we have not read that runs."""
    offenders = [
        p.name for p in (LIB / "skills").rglob("*")
        if p.is_file() and p.suffix in {".sh", ".py", ".js", ".mjs", ".ts", ".tsx", ".swift"}
    ]
    assert not offenders, f"executable files vendored from upstream: {offenders[:5]}"


def test_a_missing_library_is_not_an_error():
    """An install that deleted it simply has no bundled skills."""
    with tempfile.TemporaryDirectory() as d:
        m = SkillsManager(d, library_root=str(pathlib.Path(d) / "nope"))
        assert m.load_all() == []
        assert m.library_manifest() == {}
