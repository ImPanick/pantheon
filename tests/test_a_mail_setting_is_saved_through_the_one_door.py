# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B988`. `routes/contacts/contacts_routes.py` and `routes/email_helpers.py`
each read `settings.json` with a raw `json.loads` and wrote it back with their
own `atomic_write_json` — a second door beside `src.settings`. Their save never
invalidated `src.settings`' cache, so for up to `_CACHE_TTL` every
`get_setting` reader answered the value from before the save, and any
`src.settings` writer in that window saved its cached copy over the change.

Measured on `0317787`: `PUT /api/email/config` with `email_auto_tag: true`
wrote `true` to disk, `get_setting("email_auto_tag")` still answered `False`,
and one unrelated `save_settings(load_settings())` put `false` back.

Every case drives a real writer — the routes through their real routers, the
scan through `_run_auto_summarize_once` — against `src.settings` on a temp file
with the cache window widened so a slow request cannot close it and turn a lost
update into a pass. Nothing reads a source file (`Law 20`).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def store(tmp_path, monkeypatch):
    """`src.settings` on a temp file, warm, with a window no test can outlast."""
    import src.settings as S

    sp = tmp_path / "settings.json"
    sp.write_text(json.dumps({
        "email_auto_tag": False,
        "email_auto_summarize": False,
        "carddav_username": "before",
        "email_writing_style": "before",
    }), encoding="utf-8")
    monkeypatch.setattr(S, "SETTINGS_FILE", str(sp))
    monkeypatch.setattr(S, "_CACHE_TTL", 3600.0)
    # On the tree before `B988` each door had its own `SETTINGS_FILE`; point
    # them at the same file, as production does, so a run against that tree
    # fails for the lost update and not for reading a different file. On this
    # tree the attribute is gone and this sets a name nothing reads.
    import routes.contacts.contacts_routes as C
    import routes.email_helpers as EH
    monkeypatch.setattr(C, "SETTINGS_FILE", sp, raising=False)
    monkeypatch.setattr(EH, "SETTINGS_FILE", sp, raising=False)
    S._invalidate_caches()
    yield S
    S._invalidate_caches()


@pytest.fixture
def db(monkeypatch):
    """A throwaway SQLite with the real tables — `PUT /api/email/config` also
    writes the default account row, and the session conftest's in-memory URL
    is one database per connection."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    import core.database as D

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    D.Base.metadata.create_all(engine)
    monkeypatch.setattr(D, "SessionLocal", sessionmaker(bind=engine))
    yield
    engine.dispose()


def _on_disk(S, key):
    return json.loads(Path(S.SETTINGS_FILE).read_text(encoding="utf-8")).get(key)


def _an_unrelated_save(S):
    """What any other writer in the product does: read, change something
    else, save."""
    other = S.load_settings()
    other["b988_unrelated"] = 1
    S.save_settings(other)


def _email_client():
    import routes.email_routes as E
    from routes.email_helpers import require_owner, require_user
    app = FastAPI()
    app.include_router(E.setup_email_routes())
    app.dependency_overrides[require_owner] = lambda: ""
    app.dependency_overrides[require_user] = lambda: ""
    return TestClient(app, raise_server_exceptions=False)


def _contacts_client():
    from core.middleware import INTERNAL_TOOL_HEADER, INTERNAL_TOOL_TOKEN
    import routes.contacts.contacts_routes as C
    app = FastAPI()
    app.include_router(C.setup_contacts_routes())
    client = TestClient(app, raise_server_exceptions=False)
    client.headers.update({INTERNAL_TOOL_HEADER: INTERNAL_TOOL_TOKEN})
    return client


# ── the row's `Verify:` ──────────────────────────────────────────────────────

def test_an_email_config_save_is_answered_at_once_and_survives_the_next_save(store, db):
    S = store
    assert S.get_setting("email_auto_tag") is False            # the cache is warm
    r = _email_client().put("/api/email/config", json={"email_auto_tag": True})
    assert r.status_code == 200, r.text
    assert S.get_setting("email_auto_tag") is True, "a reader answered from before the save"
    _an_unrelated_save(S)
    assert _on_disk(S, "email_auto_tag") is True, "the next unrelated save wrote it away"
    assert _on_disk(S, "b988_unrelated") == 1


def test_a_contacts_config_save_is_answered_at_once_and_survives_the_next_save(store):
    S = store
    assert S.get_setting("carddav_username") == "before"
    r = _contacts_client().put("/api/contacts/config", json={"carddav_username": "alice"})
    assert r.status_code == 200, r.text
    assert S.get_setting("carddav_username") == "alice"
    _an_unrelated_save(S)
    assert _on_disk(S, "carddav_username") == "alice"


def test_a_contacts_password_is_still_stored_encrypted(store, tmp_path, monkeypatch):
    """The door moved; what goes through it did not. The password is encrypted
    before it is saved, and `GET /api/contacts/config` still masks it."""
    import src.secret_storage as SS
    monkeypatch.setattr(SS, "_KEY_PATH", tmp_path / ".app_key")
    monkeypatch.setattr(SS, "_fernet", None)
    S = store
    client = _contacts_client()
    r = client.put("/api/contacts/config", json={"carddav_password": "s3cret"})
    assert r.status_code == 200, r.text
    raw = Path(S.SETTINGS_FILE).read_text(encoding="utf-8")
    assert "s3cret" not in raw
    assert _on_disk(S, "carddav_password").startswith("enc:")
    assert client.get("/api/contacts/config").json()["password"] == "***"


def test_a_writing_style_save_is_answered_at_once_and_survives_the_next_save(store):
    S = store
    assert S.get_setting("email_writing_style") == "before"
    r = _email_client().put("/api/email/style", json={"style": "short and warm"})
    assert r.status_code == 200, r.text
    assert S.get_setting("email_writing_style") == "short and warm"
    _an_unrelated_save(S)
    assert _on_disk(S, "email_writing_style") == "short and warm"


def test_the_scan_flips_its_flags_where_every_reader_sees_them(store, monkeypatch):
    """`_run_auto_summarize_once` turns the flags it was asked for on, runs one
    pass, and puts them back. The pass and everything it calls read through
    `src.settings`; before, they were flipped behind the cache, so a reader in
    the pass answered the old flags and a save in it wrote them back off."""
    import routes.email_pollers as P
    S = store
    assert S.get_setting("email_auto_summarize") is False
    seen = {}

    async def one_pass(**_kw):
        seen["during"] = S.get_setting("email_auto_summarize")
        _an_unrelated_save(S)                      # any writer, mid-scan
        seen["after_a_save"] = _on_disk(S, "email_auto_summarize")
        return "ok"

    monkeypatch.setattr(P, "_auto_summarize_pass", one_pass)
    assert asyncio.run(P._run_auto_summarize_once(do_summary=True)) == "ok"
    assert seen == {"during": True, "after_a_save": True}
    assert S.get_setting("email_auto_summarize") is False, "the flag was not put back"
    assert _on_disk(S, "email_auto_summarize") is False
    assert _on_disk(S, "b988_unrelated") == 1


# ── what comes with the one door ─────────────────────────────────────────────

def test_an_unreadable_settings_file_is_not_replaced_by_a_mail_save(store, db):
    """`P3-16`. The email door used to raise on the read, which kept the file;
    through `src.settings` the read answers defaults and the save refuses, which
    keeps it the same way. Passes before and after: it pins that moving the door
    did not open the one failure `P3-16` exists for."""
    S = store
    Path(S.SETTINGS_FILE).write_text("{ not json", encoding="utf-8")
    S._invalidate_caches()
    r = _email_client().put("/api/email/config", json={"email_auto_tag": True})
    assert r.status_code == 500
    assert Path(S.SETTINGS_FILE).read_text(encoding="utf-8") == "{ not json"


def test_an_unreadable_settings_file_does_not_take_the_mail_settings_down(store, db):
    """`P3-16`'s other half, which the old door did not have: a file that
    cannot be read is answered with defaults so the app stays up. Through the
    email door's own `json.loads` it was a 500 for every reader of it."""
    S = store
    Path(S.SETTINGS_FILE).write_text("{ not json", encoding="utf-8")
    S._invalidate_caches()
    email_cfg = _email_client().get("/api/email/config")
    assert email_cfg.status_code == 200, email_cfg.text
    assert email_cfg.json()["email_auto_tag"] is False
    contacts_cfg = _contacts_client().get("/api/contacts/config")
    assert contacts_cfg.status_code == 200, contacts_cfg.text
    assert Path(S.SETTINGS_FILE).read_text(encoding="utf-8") == "{ not json"


def test_a_redirected_store_redirects_both_doors(store, tmp_path, monkeypatch):
    """The two modules look `src.settings` up when they are called, so a
    process that points `src.settings` somewhere else — another file, or a
    replaced loader and saver, which is how thirteen test files steer it
    (`B957`) — has not left a door pointing at the old one."""
    import routes.contacts.contacts_routes as C
    import routes.email_helpers as EH
    S = store
    elsewhere = tmp_path / "elsewhere.json"
    elsewhere.write_text(json.dumps({"carddav_username": "moved"}), encoding="utf-8")
    monkeypatch.setattr(S, "SETTINGS_FILE", str(elsewhere))
    S._invalidate_caches()
    assert C._load_settings()["carddav_username"] == "moved"
    assert EH._load_settings()["carddav_username"] == "moved"
    EH._save_settings({**EH._load_settings(), "email_auto_tag": True})
    assert json.loads(elsewhere.read_text(encoding="utf-8"))["email_auto_tag"] is True

    saved = []
    monkeypatch.setattr(S, "load_settings", lambda: {"carddav_username": "replaced"})
    monkeypatch.setattr(S, "save_settings", saved.append)
    for door in (C, EH):
        assert door._load_settings() == {"carddav_username": "replaced"}
        door._save_settings({"from": door.__name__})
    assert saved == [{"from": C.__name__}, {"from": EH.__name__}]
