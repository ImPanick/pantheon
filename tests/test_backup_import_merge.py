# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1950`. Restoring a backup deleted every template and group saved since.

Settings > Import Data (`POST /api/import`) says it merges a backup with what
is already there, and memories, skills, settings, features and preferences do.
The presets did not: `user_templates` and `group_presets` are lists, and the
backup's list was written over the current one. Every character template
saved after the backup, and every group preset (a group chat saves one on its
own), was gone, for every person on the instance, with nothing to undo it.

Now those lists are merged by `id`: an entry in the backup replaces the saved
one with its id, any other entry in the backup is added unless an equal one is
already there, and everything saved since stays. The built-in and custom
presets are still restored by key. Ported from upstream Odysseus #6940
(2f7302a3), whose cases these are. Its follow-up (e1d1b595) refuses the whole
restore over one entry whose id is missing or not text; here such an entry is
added once, as an entry without an id.
"""
import asyncio
import json
from unittest.mock import MagicMock

import routes.backup_routes as br
from src.preset_manager import PresetManager


class _Req:
    """A request with no ASGI stream, so `_load_import_body` reads `json()`."""

    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


def _restore(monkeypatch, presets, backup):
    monkeypatch.setattr(br, "require_admin", lambda request: None)
    monkeypatch.setattr(br, "get_current_user", lambda request: "alice")
    memories = MagicMock()
    memories.load_all_for_update.return_value = []
    router = br.setup_backup_routes(memories, presets, MagicMock())
    [endpoint] = [r.endpoint for r in router.routes
                  if r.path == "/api/import" and "POST" in getattr(r, "methods", set())]
    result = asyncio.run(endpoint(_Req(backup)))
    assert result["ok"] is True, result
    return result


def _template(tid, name):
    return {"id": tid, "name": name, "system_prompt": f"You are {name}."}


def _on_disk(tmp_path, key):
    return json.loads((tmp_path / "presets.json").read_text(encoding="utf-8"))[key]


def test_templates_saved_after_the_backup_survive_its_restore(monkeypatch, tmp_path):
    presets = PresetManager(str(tmp_path))
    presets.save_user_template(_template("user-ada", "Ada (edited since)"))
    presets.save_user_template(_template("user-grace", "Grace"))   # made after the backup
    custom = dict(presets.get("custom"), system_prompt="the backed-up prompt")
    _restore(monkeypatch, presets, {"presets": {
        "user_templates": [_template("user-ada", "Ada"), _template("user-bob", "Bob")],
        "custom": custom,
    }})
    # The backup's "user-ada" takes its place; "user-grace" stays.
    assert [(t["id"], t["name"]) for t in _on_disk(tmp_path, "user_templates")] == [
        ("user-ada", "Ada"), ("user-grace", "Grace"), ("user-bob", "Bob")]
    # The custom preset is restored by key, as it was.
    assert presets.get("custom")["system_prompt"] == "the backed-up prompt"


def test_group_presets_saved_after_the_backup_survive_its_restore(monkeypatch, tmp_path):
    presets = PresetManager(str(tmp_path))
    presets.save_group_presets([
        {"id": "grp-1", "name": "Ada & Bob", "participants": []},
        {"id": "grp-2", "name": "Ada & Grace", "participants": []},   # a group chat since
    ])
    _restore(monkeypatch, presets, {"presets": {
        "group_presets": [{"id": "grp-1", "name": "Ada & Bob", "participants": []}]}})
    assert [g["id"] for g in presets.get_group_presets()] == ["grp-1", "grp-2"]


def test_an_entry_without_an_id_is_added_once_however_often_the_file_is_restored(
        monkeypatch, tmp_path):
    presets = PresetManager(str(tmp_path))
    presets.save_user_template(_template("user-grace", "Grace"))
    backup = {"presets": {"user_templates": [{"name": "Nameless", "system_prompt": "Hi."}]}}
    _restore(monkeypatch, presets, backup)
    _restore(monkeypatch, presets, backup)
    assert [t["name"] for t in _on_disk(tmp_path, "user_templates")] == ["Grace", "Nameless"]


def test_an_id_that_is_not_text_is_an_entry_without_an_id(monkeypatch, tmp_path):
    """A hand-edited backup can say `"id": ["x"]`, which nothing can be looked
    up by. It is added as it is, and the restore does not stop half done."""
    presets = PresetManager(str(tmp_path))
    presets.save_user_template(_template("user-grace", "Grace"))
    odd = {"id": ["x"], "name": "Odd"}
    _restore(monkeypatch, presets, {"presets": {"user_templates": [odd]}})
    assert _on_disk(tmp_path, "user_templates") == [_template("user-grace", "Grace"), odd]
