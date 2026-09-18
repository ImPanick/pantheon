# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P8-16` — getting one skill out, whole.

A skill is a directory: `SKILL.md` plus whatever `references/` and `templates/`
an import brought with it. There was a way to put one of those in (`import
bundle from URL`, and the backup importer) and no way at all to get one back
out. `/api/backup/export` dumps every skill as a flat JSON row — the parsed
fields, none of the sibling files — so it is a backup of the library and not a
copy of a skill you can hand to somebody.

The export is deliberately the **exact** shape `import_bundle_from_files`
accepts, `{relative path: text}`, so the round trip is a round trip rather than
two formats that nearly agree, and it borrows the importer's own caps so an
export can always be imported back (`Law 14`).

`versions/` is excluded, and that is a decision rather than an omission: it is
this install's edit history, and shipping it would put the drafts somebody
rejected into whatever they meant to share.
"""

import json

import pytest

from services.memory.skills import SkillsManager
from src.tools.system import do_manage_skills


@pytest.fixture
def store(tmp_path):
    sm = SkillsManager(str(tmp_path), library_root="")
    sm.add_skill(name="brief-the-board", description="Write the quarterly board brief",
                 category="writing", tags=["board", "writing"],
                 when_to_use="Before each board meeting",
                 procedure=["Pull the numbers", "Draft it", "Send for review"],
                 pitfalls=["Do not quote unaudited figures"],
                 verification=["The chair acknowledged receipt"],
                 source="user", status="published", owner="alice")
    skill_dir = tmp_path / "skills" / "writing" / "brief-the-board"
    (skill_dir / "references").mkdir(parents=True, exist_ok=True)
    (skill_dir / "references" / "last-quarter.md").write_text(
        "# Q3\n\nRevenue was up.\n", encoding="utf-8")
    (skill_dir / "templates").mkdir(parents=True, exist_ok=True)
    (skill_dir / "templates" / "brief.md").write_text(
        "# {{quarter}} board brief\n", encoding="utf-8")
    return sm


def test_the_export_is_the_whole_directory_not_just_the_procedure(store):
    files = store.export_skill("brief-the-board", owner="alice")
    assert set(files) == {"SKILL.md", "references/last-quarter.md", "templates/brief.md"}
    assert "Do not quote unaudited figures" in files["SKILL.md"]
    assert files["references/last-quarter.md"].startswith("# Q3")


def test_an_export_can_be_imported_back(store, tmp_path):
    files = store.export_skill("brief-the-board", owner="alice")

    elsewhere = SkillsManager(str(tmp_path / "other"), library_root="")
    entry = elsewhere.import_bundle_from_files(files, owner="bob", category="imported")

    assert entry["name"] == "brief-the-board"
    round_tripped = elsewhere.export_skill("brief-the-board", owner="bob")
    assert set(round_tripped) == set(files)
    assert round_tripped["templates/brief.md"] == files["templates/brief.md"]
    assert "Pull the numbers" in round_tripped["SKILL.md"]


def test_the_edit_history_is_not_part_of_what_you_share(store):
    # Every content edit leaves a copy in `versions/` (`P8-10`). Those are this
    # install's rejected drafts, and an export is a copy of the skill.
    store.update_skill("brief-the-board",
                       {"procedure": ["Pull the numbers", "Draft it", "Ship it"]},
                       owner="alice")
    assert store.list_versions("brief-the-board", owner="alice"), "no history to exclude"

    files = store.export_skill("brief-the-board", owner="alice")
    assert not any(k.startswith("versions/") for k in files), sorted(files)


def test_a_skill_that_is_not_yours_does_not_export(store):
    assert store.export_skill("brief-the-board", owner="bob") is None
    assert store.export_skill("no-such-skill", owner="alice") is None


def test_a_binary_extra_file_does_not_sink_the_export(store, tmp_path):
    (tmp_path / "skills" / "writing" / "brief-the-board" / "logo.png").write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\xff\xfe")
    files = store.export_skill("brief-the-board", owner="alice")
    assert "SKILL.md" in files, "one unreadable extra file lost the whole export"
    assert "logo.png" not in files


@pytest.mark.asyncio
async def test_a_person_can_ask_for_it_and_get_something_they_can_save(tmp_path, monkeypatch):
    # `P8-00`: reachable without reading this file. Asking the assistant to
    # export a skill returns a JSON document it can write out or paste.
    import src.constants as constants
    monkeypatch.setattr(constants, "DATA_DIR", str(tmp_path), raising=False)
    sm = SkillsManager(str(tmp_path), library_root="")
    sm.add_skill(name="brief-the-board", description="Write the quarterly board brief",
                 category="writing", procedure=["Pull the numbers"],
                 source="user", owner=None)

    out = await do_manage_skills(
        json.dumps({"action": "export", "name": "brief-the-board"}), owner=None)
    assert "error" not in out, out
    body = out["results"]
    payload = json.loads(body[body.index("{"):])
    assert payload["skill"] == "brief-the-board"
    assert "SKILL.md" in payload["files"]
    assert "Pull the numbers" in payload["files"]["SKILL.md"]

    missing = await do_manage_skills(
        json.dumps({"action": "export", "name": "nope"}), owner=None)
    assert missing.get("exit_code") == 1
