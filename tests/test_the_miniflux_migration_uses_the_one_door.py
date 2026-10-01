# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1008` — the boot-time Miniflux migration writes settings.json through `src.settings`.

`src/integrations.py`'s `migrate_from_settings` (run by `setup_auth_routes` on
every boot) moved two legacy keys into an integration and wrote settings.json
back with its own `open(…, "w")` + `json.dump`: a fourth door onto the file
`B988` had just narrowed to one. On `4e65b71`, driven here: a crash in the
middle of the write left the file that holds every credential half-written;
and because the write went around `src.settings`' cache, the next unrelated
save put both keys back. `.pantheon/check-config-writes.py` could not see it —
it classified only `atomic_write_*` calls.

Every case drives the real function against `src.settings` on a temp file, or
the real checker on a mirror of the tree (`Law 20`; the mirror is
`test_a_failed_read_never_becomes_a_write.py`'s, so nothing here writes into
the repository it measures).
"""
import json

import pytest

import src.integrations as integrations
import src.settings as app_settings
from tests.test_a_failed_read_never_becomes_a_write import (  # noqa: F401
    _load_checker, _mirror_source, _run, _the_tree_under_test_is_never_written_to, mirror,
)

LEGACY = {"miniflux_url": "http://rss.lan:8080/", "miniflux_api_key": "mf-key-123",
          "theme": "paper", "email_auto_tag": True, "some_operator_choice": [1, 2]}


@pytest.fixture
def store(tmp_path, monkeypatch):
    settings_file = tmp_path / "settings.json"
    settings_file.write_text(json.dumps(LEGACY, indent=2), encoding="utf-8")
    monkeypatch.setattr(app_settings, "SETTINGS_FILE", str(settings_file))
    monkeypatch.setattr(integrations, "DATA_FILE", str(tmp_path / "integrations.json"))
    # The cache window as long as a test: a lost update has all of it to happen in.
    monkeypatch.setattr(app_settings, "_CACHE_TTL", 3600)
    app_settings._invalidate_caches()
    yield settings_file
    app_settings._invalidate_caches()


def _on_disk(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_it_moves_the_two_keys_and_keeps_every_other(store):
    integrations.migrate_from_settings()
    [made] = integrations.load_integrations()
    assert made["preset"] == "miniflux" and made["base_url"] == "http://rss.lan:8080"
    saved = _on_disk(store)
    assert "miniflux_url" not in saved and "miniflux_api_key" not in saved
    for key in ("theme", "email_auto_tag", "some_operator_choice"):
        assert saved[key] == LEGACY[key], key


def test_an_unrelated_save_does_not_bring_the_keys_back(store):
    """`B988`'s lost update, at boot: the settings were read (and cached)
    before the migration ran; the next save of that cached copy wrote both keys
    back. Every reader sees the migration at once now."""
    assert app_settings.get_setting("miniflux_url") == LEGACY["miniflux_url"]  # cached
    integrations.migrate_from_settings()
    assert app_settings.get_setting("miniflux_url") in (None, "")
    app_settings.save_settings(app_settings.load_settings())
    assert "miniflux_url" not in _on_disk(store)


def test_a_crash_in_the_write_leaves_settings_as_they_were(store, monkeypatch):
    """The write is cut off half-way through. The file the person's
    credentials live in must still read as it did."""
    real_dump = json.dump

    def _dies_half_way(obj, fp, *a, **k):
        if isinstance(obj, dict) and "some_operator_choice" in obj:
            fp.write('{"theme": "pap')
            raise OSError("disk went away")
        return real_dump(obj, fp, *a, **k)

    monkeypatch.setattr(json, "dump", _dies_half_way)
    before = store.read_bytes()
    with pytest.raises(OSError):
        integrations.migrate_from_settings()
    assert store.read_bytes() == before


def test_an_unreadable_settings_file_is_left_exactly_as_it_is(store):
    store.write_bytes(b'{"miniflux_url": "http://rss.lan", "miniflux_api_key": "k", ')
    before = store.read_bytes()
    integrations.migrate_from_settings()
    assert store.read_bytes() == before
    assert integrations.load_integrations() == []


def test_nothing_to_move_writes_nothing(store):
    store.write_text(json.dumps({"theme": "paper"}), encoding="utf-8")
    before = store.read_bytes()
    integrations.migrate_from_settings()
    assert store.read_bytes() == before and integrations.load_integrations() == []


# ── the checker sees a plain write onto a guarded store ─────────────────────

_OLD_WRITE = '''
    settings.pop("miniflux_url", None)
    settings.pop("miniflux_api_key", None)
    app_settings.save_settings(settings)
'''
_PLAIN_WRITE = '''
    settings.pop("miniflux_url", None)
    settings.pop("miniflux_api_key", None)
    settings_path = SETTINGS_FILE
    with open(settings_path, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)
'''


def test_the_checker_fails_on_the_old_door(mirror):
    """The migration as it was — an alias of `SETTINGS_FILE` opened for
    writing — is a problem the checker names, where before it passed."""
    target = mirror / "src" / "integrations.py"
    source = target.read_text(encoding="utf-8")
    assert source.count(_OLD_WRITE) == 1, "the migration no longer looks like this"
    target.write_text(source.replace(_OLD_WRITE, _PLAIN_WRITE), encoding="utf-8")
    code, out = _run(_load_checker(mirror))
    assert code == 1, out
    assert "src/integrations.py" in out and "writes `SETTINGS_FILE`" in out, out
    assert "plain open(…, 'w')" in out


@pytest.mark.parametrize("spelling", [
    'Path(SETTINGS_FILE).write_text("{}")',
    'open(os.path.join(DATA_DIR, "settings.json"), mode="w").write("{}")',
    'open(FEATURES_FILE, "a+").write("x")',
], ids=["write_text", "basename", "append"])
def test_the_checker_sees_the_other_spellings(mirror, spelling):
    target = mirror / "src" / "integrations.py"
    target.write_text(target.read_text(encoding="utf-8")
                      + f"\n\ndef _b1008_probe():\n    from pathlib import Path\n    {spelling}\n",
                      encoding="utf-8")
    code, out = _run(_load_checker(mirror))
    assert code == 1 and "src/integrations.py" in out, out


def test_a_read_is_not_a_write(mirror):
    target = mirror / "src" / "integrations.py"
    target.write_text(target.read_text(encoding="utf-8")
                      + '\n\ndef _b1008_probe():\n    return open(SETTINGS_FILE, "r").read()\n',
                      encoding="utf-8")
    code, out = _run(_load_checker(mirror))
    assert code == 0, out


def test_the_known_plain_writes_are_named_and_kept_honest(mirror):
    """The two found on the way are filed, not fixed — so the checker lists
    them, fails when another appears, and fails when one of them is gone."""
    module = _load_checker(mirror)
    module.KNOWN_PLAIN_WRITES.pop(("core/database.py", "USER_PREFS_FILE"))
    code, out = _run(module)
    assert code == 1 and "core/database.py" in out and "USER_PREFS_FILE" in out, out
    module = _load_checker(mirror)
    module.KNOWN_PLAIN_WRITES[("src/settings.py", "SETTINGS_FILE")] = "gone"
    code, out = _run(module)
    assert code == 1 and "no plain write there any more" in out, out


def test_both_halves_go_through_the_one_door(store, monkeypatch):
    """The read as well as the write: a `src.settings` pointed somewhere else —
    another loader and saver, as thirteen test files and any later store do —
    takes the migration with it, and the file it used to open is not read."""
    held = {"settings": {"miniflux_url": "http://elsewhere/", "miniflux_api_key": "k2",
                         "theme": "cute"}}
    monkeypatch.setattr(app_settings, "load_settings", lambda: dict(held["settings"]))
    monkeypatch.setattr(app_settings, "save_settings", lambda s: held.update(settings=dict(s)))
    before = store.read_bytes()
    integrations.migrate_from_settings()
    assert held["settings"] == {"theme": "cute"}
    [made] = integrations.load_integrations()
    assert made["base_url"] == "http://elsewhere"
    assert store.read_bytes() == before, "the file behind the door was not opened"
