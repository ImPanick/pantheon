# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1951`. A backup restore dropped the notes of every skill with steps.

`POST /api/import` recreates each skill through `add_skill`, which had no
`body_extra` argument and filled it from the legacy `solution` field only when
the skill had no procedure. So a skill with both steps and notes came back
without its notes, although the export carries them in `body_extra`.

Now the route passes `body_extra` when it is text, and an older backup without
it (or with something that is not text) still restores `solution` as before.

Ported from upstream Odysseus de438bfc (PR #6939); the three skills are
upstream's three cases, restored from one backup.
"""
import asyncio
from unittest.mock import MagicMock

import routes.backup_routes as br
from services.memory.skills import SkillsManager


class _Req:
    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


def _endpoint(monkeypatch, skills_manager):
    monkeypatch.setattr(br, "require_admin", lambda request: None)
    monkeypatch.setattr(br, "get_current_user", lambda request: "alice")
    router = br.setup_backup_routes(MagicMock(), MagicMock(), skills_manager)
    for r in router.routes:
        if r.path == "/api/import" and "POST" in getattr(r, "methods", set()):
            return r.endpoint
    raise AssertionError("import route not found")


def test_a_restore_brings_back_the_notes_of_a_skill_with_steps(monkeypatch, tmp_path):
    source = SkillsManager(str(tmp_path / "source"))
    source.add_skill(name="release", description="Cut a release", source="user",
                     procedure=["bump version", "tag"], pitfalls=["forgetting changelog"],
                     owner="alice")
    source.update_skill("release", {"body_extra": "## Notes\n\nRun the smoke suite on staging first."},
                        owner="alice")
    exported = source.load(owner="alice")
    # An older backup has no body_extra, and one hand-edited may hold a list:
    # both still restore their `solution` as before.
    legacy = {"title": "Water plants", "problem": "Plants look dry", "solution": "Water them twice a week."}
    odd = {"name": "odd", "description": "Odd skill", "body_extra": ["not", "text"],
           "solution": "Plain notes."}

    target = SkillsManager(str(tmp_path / "target"))
    result = asyncio.run(_endpoint(monkeypatch, target)(_Req({"skills": exported + [legacy, odd]})))

    assert "3 skills" in result["imported"]
    restored = {s["name"]: s for s in target.load(owner="alice")}
    assert restored["release"]["procedure"] == ["bump version", "tag"]
    assert restored["release"]["pitfalls"] == ["forgetting changelog"]
    assert restored["release"]["body_extra"] == "## Notes\n\nRun the smoke suite on staging first."
    assert restored["water-plants"]["when_to_use"] == "Plants look dry"
    assert restored["water-plants"]["body_extra"] == "Water them twice a week."
    assert restored["odd"]["body_extra"] == "Plain notes."
