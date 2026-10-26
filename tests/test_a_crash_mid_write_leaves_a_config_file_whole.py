# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1017` — the last two plain writes onto guarded config stores are atomic.

`check-config-writes.py` listed them in `KNOWN_PLAIN_WRITES` rather than
failing on them: the boot migration of a flat `user_prefs.json` to the per-user
form (`core/database._migrate_assign_legacy_owner`), and the installer's first
admin (`setup.create_default_admin`). Both wrote with `open(…, "w")` +
`json.dump`, so a process dying mid-dump left the file truncated — every user's
preferences, or an auth.json the installer then skipped forever as "already
exists". Both go through `atomic_write_json(…, preserve_unreadable=True)` now.

Driven, not read (`Law 20`): each real function, against files of our own, with
`json.dump` made to die halfway through the bytes it was writing.
"""
import json
import sqlite3

import pytest

import core.database as database


class _Died(Exception):
    pass


@pytest.fixture
def dies_mid_dump(monkeypatch):
    """`json.dump` writes half of what it would have, then the process 'dies'."""
    real_dumps = json.dumps

    def dump(obj, fp, **kwargs):
        text = real_dumps(obj, **kwargs)
        fp.write(text[: len(text) // 2])
        fp.flush()
        raise _Died("killed mid-write")

    monkeypatch.setattr(json, "dump", dump)


def _legacy_install(tmp_path, monkeypatch, prefs):
    (tmp_path / "auth.json").write_text(json.dumps(
        {"users": {"joseph": {"password_hash": "x", "is_admin": True}}}), encoding="utf-8")
    sqlite3.connect(tmp_path / "pantheon.db").close()
    prefs_file = tmp_path / "user_prefs.json"
    prefs_file.write_text(json.dumps(prefs), encoding="utf-8")
    monkeypatch.setattr(database, "DATABASE_URL", f"sqlite:///{tmp_path / 'pantheon.db'}")
    monkeypatch.setattr(database, "AUTH_FILE", str(tmp_path / "auth.json"))
    monkeypatch.setattr(database, "USER_PREFS_FILE", str(prefs_file))
    return prefs_file


FLAT = {"theme": "dark", "font_family": "Inter", "foreground_fallback_enabled": True}


def test_the_prefs_migration_still_nests_flat_prefs_under_the_admin(tmp_path, monkeypatch):
    prefs_file = _legacy_install(tmp_path, monkeypatch, FLAT)

    database._migrate_assign_legacy_owner()

    assert json.loads(prefs_file.read_text(encoding="utf-8")) == {
        "foreground_fallback_enabled": True,
        "_users": {"joseph": {"theme": "dark", "font_family": "Inter"}},
    }


def test_a_crash_mid_migration_leaves_every_users_prefs_as_they_were(
        tmp_path, monkeypatch, dies_mid_dump):
    prefs_file = _legacy_install(tmp_path, monkeypatch, FLAT)

    database._migrate_assign_legacy_owner()   # logs the failure and carries on

    assert json.loads(prefs_file.read_text(encoding="utf-8")) == FLAT
    assert [p.name for p in tmp_path.iterdir() if ".tmp." in p.name] == []


def _installer(tmp_path, monkeypatch):
    import setup

    auth = tmp_path / "auth.json"
    monkeypatch.setattr(setup, "AUTH_FILE", str(auth))
    monkeypatch.setenv("PANTHEON_ADMIN_USER", "joseph")
    monkeypatch.setenv("PANTHEON_ADMIN_PASSWORD", "a long enough password")
    monkeypatch.setenv("PANTHEON_SKIP_ADMIN_PROMPT", "1")
    return setup, auth


def test_a_crash_while_creating_the_first_admin_leaves_no_half_written_file(
        tmp_path, monkeypatch, dies_mid_dump):
    setup, auth = _installer(tmp_path, monkeypatch)

    with pytest.raises(_Died):
        setup.create_default_admin()

    assert not auth.exists(), "a half-written auth.json would be skipped forever"


def test_so_the_next_run_creates_it(tmp_path, monkeypatch):
    setup, auth = _installer(tmp_path, monkeypatch)

    assert setup.create_default_admin() == "created"
    users = json.loads(auth.read_text(encoding="utf-8"))["users"]
    assert users["joseph"]["is_admin"] is True
    assert setup.create_default_admin() == "exists"
