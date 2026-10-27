# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P27-10` — logins come into a person's own vault, and go out sealed.

Driven, not read (`Law 20`): a real SQLite database and the vault's real key
wrapping; the real routes over HTTP; the real scrypt and AES-GCM; a real
Bitwarden JSON and CSV export (the shapes Bitwarden and Vaultwarden write);
and for the server's Bitwarden link a `bw` on the PATH answering as the CLI
does.

The row's two promises are the adversaries (`Law 17`): a file — or a body —
trying to put items into somebody else's vault, and someone holding an export
without its passphrase.

**Measured before this file, on `2760dbe1`:** `routes/vault_mine_routes.py`
had no import and no export; a person moving to Pantheon typed every login in
by hand, and had no way to take theirs out.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import textwrap

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from src import vault as V
from src import vault_transfer as T

PASSWORD = "Pw-correct-horse-77"
PASSPHRASE = "a long walk to the lake"

BITWARDEN_JSON = {
    "encrypted": False,
    "folders": [{"id": "f1", "name": "Home"}],
    "items": [
        {"id": "1", "type": 1, "name": "Grafana", "notes": "the lab one", "favorite": False,
         "fields": [{"name": "org", "value": "lab", "type": 0}],
         "login": {"uris": [{"match": None, "uri": "http://grafana.lan:3000/login"},
                            {"match": None, "uri": "androidapp://com.grafana"}],
                   "username": "admin", "password": PASSWORD, "totp": "JBSWY3DPEHPK3PXP"}},
        {"id": "2", "type": 1, "name": "Home Wi-Fi", "login": {"uris": [], "username": "", "password": "wifi-pass-9"}},
        {"id": "3", "type": 2, "name": "Recovery codes", "notes": "11-22-33", "secureNote": {"type": 0}},
        {"id": "4", "type": 3, "name": "Visa", "card": {"number": "4111111111111111"}},
        {"id": "5", "type": 5, "name": "Deploy key",
         "sshKey": {"privateKey": "-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n-----END OPENSSH PRIVATE KEY-----",
                    "publicKey": "ssh-ed25519 AAAA deploy"}},
        {"id": "6", "type": 1, "name": "Passkey only", "login": {"uris": [{"uri": "https://example.org"}],
                                                               "username": "me"}},
    ],
}

BITWARDEN_CSV = textwrap.dedent("""\
    folder,favorite,type,name,notes,fields,reprompt,login_uri,login_username,login_password,login_totp
    ,,login,Gitea,,"token: abc",0,"https://git.example.org,http://gitea.lan:3000",dev,csv-pass-1,
    Home,1,note,Alarm code,4321,,0,,,,
    ,,login,Grafana,,,0,https://grafana.example.org,viewer,csv-pass-2,
    """)


@pytest.fixture()
def db(tmp_path, monkeypatch):
    import core.database as cdb
    import src.secret_storage as ss
    engine = create_engine(f"sqlite:///{tmp_path / 'vault.db'}", connect_args={"check_same_thread": False},
                           poolclass=NullPool)
    cdb.Base.metadata.create_all(engine, tables=[cdb.VaultKey.__table__, cdb.VaultItem.__table__])
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(cdb, "SessionLocal", factory)
    monkeypatch.setattr(ss, "_KEY_PATH", tmp_path / ".app_key")
    monkeypatch.setattr(ss, "_fernet", None)
    V._unlocked_until.clear()
    factory.engine_path = tmp_path / "vault.db"
    return factory


class _Auth:
    is_configured = True

    @staticmethod
    def verify_password(user, password):
        return password == f"{user}-pw"


@pytest.fixture()
def client(db, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import routes.vault_mine_routes as R
    monkeypatch.setattr(R, "SessionLocal", db)
    monkeypatch.setattr(R, "get_current_user", lambda request: request.headers.get("x-user"))
    monkeypatch.setattr(R, "request_is_a_person", lambda request: request.headers.get("x-token") is None)
    app = FastAPI()
    app.state.auth_manager = _Auth()
    app.include_router(R.setup_vault_mine_routes())
    return TestClient(app)


def _items(client, user):
    return {i["label"]: i for i in client.get("/api/vault/mine", headers={"x-user": user}).json()["items"]}


# ── bringing in ─────────────────────────────────────────────────────────────

def test_a_bitwarden_json_export_comes_into_the_callers_vault_and_nobody_elses(client, db):
    # The body names another account three ways; none of them is read.
    body = {"text": json.dumps(BITWARDEN_JSON), "account": "bob", "owner": "bob"}
    r = client.post("/api/vault/mine/import", headers={"x-user": "alice"}, json=body)
    assert r.status_code == 200, r.text
    got = r.json()
    assert sorted(got["imported"]) == ["Deploy key", "Grafana", "Home Wi-Fi", "Recovery codes"]
    assert {x["name"]: x["why"] for x in got["left_out"]} == {
        "Visa": "a card is not something an agent signs in with",
        "Passkey only": "it has no password to keep"}
    assert PASSWORD not in r.text and "4111" not in r.text, "the answer names items, never values"

    mine = _items(client, "alice")
    assert mine["Grafana"]["kind"] == "login" and mine["Grafana"]["addresses"] == ["http://grafana.lan:3000"]
    assert mine["Grafana"]["has_totp"] and mine["Grafana"]["username"] == "admin"
    assert mine["Grafana"]["use"] == "ask", "an imported login asks before an agent uses it"
    assert mine["Home Wi-Fi"]["kind"] == "key", "no web address: a command may use it, the browser cannot"
    assert mine["Recovery codes"]["kind"] == "note" and mine["Deploy key"]["kind"] == "key"
    assert client.get("/api/vault/mine", headers={"x-user": "bob"}).json()["items"] == [], \
        "an import never reaches another account"

    s = db()
    used = V.for_use(s, "alice", "Grafana")
    assert used["secret"] == PASSWORD and len(used["otp"]) == 6
    shown = V.reveal(s, "alice", mine["Grafana"]["id"])
    assert "Fields:\norg: lab" in shown["notes"] and shown["notes"].startswith("the lab one"), \
        "custom fields are kept, sealed, in the notes"
    assert V.reveal(s, "alice", mine["Deploy key"]["id"])["secret"].startswith("-----BEGIN OPENSSH")
    with pytest.raises(V.VaultRefused) as nope:
        V.for_use(s, "bob", "Grafana")
    assert nope.value.status == 404
    raw = db.engine_path.read_bytes()
    assert PASSWORD.encode() not in raw and b"wifi-pass-9" not in raw, "sealed at rest like any other item"


def test_the_same_file_twice_brings_nothing_in_the_second_time(client):
    a = {"x-user": "alice"}
    client.post("/api/vault/mine/items", headers=a,
                json={"label": "Grafana", "addresses": "grafana.example.org", "secret": "different"})
    first = client.post("/api/vault/mine/import", headers=a, json={"text": json.dumps(BITWARDEN_JSON)}).json()
    assert "Grafana (2)" in first["imported"], "a name taken by a different login is brought in beside it"
    assert any(x["name"] == "Grafana (2)" and "already have one" in x["said"] for x in first["said"])
    again = client.post("/api/vault/mine/import", headers=a, json={"text": json.dumps(BITWARDEN_JSON)}).json()
    assert again["imported"] == [] and sorted(again["already"]) == [
        "Deploy key", "Grafana", "Home Wi-Fi", "Recovery codes"]
    assert len(_items(client, "alice")) == 5


def test_a_bitwarden_csv_export_comes_in(client, db):
    r = client.post("/api/vault/mine/import", headers={"x-user": "alice"}, json={"text": BITWARDEN_CSV})
    assert r.status_code == 200, r.text
    mine = _items(client, "alice")
    assert mine["Gitea"]["addresses"] == ["https://git.example.org", "http://gitea.lan:3000"]
    assert mine["Alarm code"]["kind"] == "note"
    assert V.for_use(db(), "alice", "Gitea")["secret"] == "csv-pass-1"
    assert "token: abc" in V.reveal(db(), "alice", mine["Gitea"]["id"])["notes"]


@pytest.mark.parametrize("text,words", [
    ("", "Pick a file"),
    ("not,a,vault\n1,2,3\n", "needs the columns"),
    ('{"encrypted": true, "passwordProtected": true, "data": "2.x"}', "password-protected export"),
    ('{"encrypted": true, "data": "2.x"}', "encrypted to the Bitwarden account"),
    ('{"folders": []}', "no “items”"),
    ("{nope", "not JSON"),
])
def test_a_file_that_is_not_an_export_is_refused_in_a_sentence(client, text, words):
    r = client.post("/api/vault/mine/import", headers={"x-user": "alice"}, json={"text": text})
    assert r.status_code == 400 and words in r.json()["detail"]
    assert _items(client, "alice") == {}


def test_only_a_person_brings_logins_in_and_a_locked_vault_takes_none(client):
    token = client.post("/api/vault/mine/import", headers={"x-user": "alice", "x-token": "1"},
                        json={"text": json.dumps(BITWARDEN_JSON)})
    assert token.status_code == 403 and "Only a person" in token.json()["detail"]
    a = {"x-user": "alice"}
    client.put("/api/vault/mine/lock", headers=a, json={"idle_minutes": 5})
    client.put("/api/vault/mine/lock", headers=a, json={"locked": True})
    locked = client.post("/api/vault/mine/import", headers=a, json={"text": json.dumps(BITWARDEN_JSON)})
    assert locked.status_code == 423 and "Nothing was brought in" in locked.json()["detail"]
    client.put("/api/vault/mine/lock", headers=a, json={"locked": False, "password": "alice-pw"})
    assert _items(client, "alice") == {}


# ── taking out ──────────────────────────────────────────────────────────────

def _export(client, user="alice", passphrase=PASSPHRASE, password=None):
    return client.post("/api/vault/mine/export", headers={"x-user": user},
                       json={"passphrase": passphrase, "password": password or f"{user}-pw"})


def test_an_export_is_unreadable_without_its_passphrase(client):
    client.post("/api/vault/mine/import", headers={"x-user": "alice"}, json={"text": json.dumps(BITWARDEN_JSON)})
    r = _export(client)
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    env = r.json()
    for plain in (PASSWORD, "admin", "Grafana", "grafana.lan", "wifi-pass-9", "11-22-33", "Recovery"):
        assert plain not in r.text, f"{plain!r} is in the export in the clear"
    assert env["items"] == 4 and env["kdf"]["name"] == "scrypt" and env["cipher"] == "AES-256-GCM"

    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    wrong_key = T._key(b"not the passphrase at all", base64.b64decode(env["kdf"]["salt"]),
                       env["kdf"]["n"], env["kdf"]["r"], env["kdf"]["p"])
    with pytest.raises(InvalidTag):
        AESGCM(wrong_key).decrypt(base64.b64decode(env["nonce"]), base64.b64decode(env["data"]), T._header_aad(env))

    bob = {"x-user": "bob"}
    refused = client.post("/api/vault/mine/import", headers=bob,
                          json={"text": r.text, "passphrase": "not the passphrase at all"})
    assert refused.status_code == 403 and "does not open this export" in refused.json()["detail"]
    asked = client.post("/api/vault/mine/import", headers=bob, json={"text": r.text})
    assert asked.status_code == 401 and "type the passphrase" in asked.json()["detail"]
    assert _items(client, "bob") == {}


def test_a_changed_envelope_does_not_open_even_with_the_passphrase(client):
    client.post("/api/vault/mine/items", headers={"x-user": "alice"},
                json={"label": "NAS", "addresses": "nas.lan", "secret": PASSWORD})
    env = _export(client).json()
    for change in ({"items": 99}, {"made": "1999-01-01"}):
        forged = {**env, **change}
        r = client.post("/api/vault/mine/import", headers={"x-user": "bob"},
                        json={"text": json.dumps(forged), "passphrase": PASSPHRASE})
        assert r.status_code == 403, change
    weak = {**env, "kdf": {**env["kdf"], "n": 2}}
    r = client.post("/api/vault/mine/import", headers={"x-user": "bob"},
                    json={"text": json.dumps(weak), "passphrase": PASSPHRASE})
    assert r.status_code == 400 and "not one Pantheon makes" in r.json()["detail"]


def test_an_export_comes_back_in_whole_with_its_passphrase(client, db):
    a = {"x-user": "alice"}
    client.post("/api/vault/mine/import", headers=a, json={"text": json.dumps(BITWARDEN_JSON)})
    iid = _items(client, "alice")["Grafana"]["id"]
    client.put(f"/api/vault/mine/items/{iid}", headers=a, json={"use": "allowed", "agent_account": True})
    text = _export(client).text
    back = client.post("/api/vault/mine/import", headers={"x-user": "carol"},
                       json={"text": text, "passphrase": PASSPHRASE})
    assert back.status_code == 200 and sorted(back.json()["imported"]) == [
        "Deploy key", "Grafana", "Home Wi-Fi", "Recovery codes"]
    assert not back.json()["said"], "its own export comes back as it went out, with nothing to say"
    carol = _items(client, "carol")
    assert carol["Grafana"]["use"] == "allowed" and carol["Grafana"]["agent_account"]
    assert carol["Home Wi-Fi"]["kind"] == "key" and carol["Recovery codes"]["kind"] == "note"
    got = V.for_use(db(), "carol", "Grafana")
    assert got["secret"] == PASSWORD and got["origins"] == ["http://grafana.lan:3000"] and got["otp"]
    assert len(_items(client, "alice")) == 4, "the person who exported keeps everything"


@pytest.mark.parametrize("over,status,words", [
    ({"password": "wrong"}, 403, "Nothing was exported"),
    ({"passphrase": "short"}, 400, "at least 12 characters"),
])
def test_an_export_asks_for_the_password_and_a_real_passphrase(client, over, status, words):
    client.post("/api/vault/mine/items", headers={"x-user": "alice"},
                json={"label": "NAS", "addresses": "nas.lan", "secret": PASSWORD})
    r = _export(client, **over)
    assert r.status_code == status and words in r.json()["detail"] and PASSWORD not in r.text
    token = client.post("/api/vault/mine/export", headers={"x-user": "alice", "x-token": "1"},
                        json={"passphrase": PASSPHRASE, "password": "alice-pw"})
    assert token.status_code == 403


# ── the server's Bitwarden link ─────────────────────────────────────────────

@pytest.fixture()
def fake_bw(tmp_path, monkeypatch):
    """A `bw` on the PATH answering `list items` as the CLI does, and
    recording that it was asked with the session."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    asked = tmp_path / "asked"
    script = bin_dir / "bw"
    script.write_text("#!/bin/sh\n"
                      f"echo \"$@ $BW_SESSION\" >> {asked}\n"
                      f"cat {tmp_path / 'items.json'}\n")
    script.chmod(0o755)
    (tmp_path / "items.json").write_text(json.dumps(BITWARDEN_JSON["items"][:2]))
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    import src.tools.vault as tv
    monkeypatch.setattr(tv, "_load_vault_config", lambda: {"session": "sess-1"})
    import src.tool_security as ts
    monkeypatch.setattr(ts, "owner_is_admin", lambda owner: owner == "root")
    return asked


def test_an_admin_brings_in_from_the_servers_bitwarden_and_a_member_cannot(client, fake_bw):
    assert client.get("/api/vault/mine", headers={"x-user": "root"}).json()["server_bitwarden"] is True
    assert client.get("/api/vault/mine", headers={"x-user": "alice"}).json()["server_bitwarden"] is False
    member = client.post("/api/vault/mine/import", headers={"x-user": "alice"}, json={"source": "server-bitwarden"})
    assert member.status_code == 403 and "an admin's" in member.json()["detail"]
    assert not fake_bw.exists(), "a member's request never ran bw"
    r = client.post("/api/vault/mine/import", headers={"x-user": "root"}, json={"source": "server-bitwarden"})
    assert r.status_code == 200 and sorted(r.json()["imported"]) == ["Grafana", "Home Wi-Fi"]
    assert fake_bw.read_text().strip() == "list items sess-1"
    assert set(_items(client, "root")) == {"Grafana", "Home Wi-Fi"} and _items(client, "alice") == {}


# ── the page's sentence ─────────────────────────────────────────────────────

@pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")
def test_the_page_says_what_came_in_and_what_was_left_out(tmp_path):
    from pathlib import Path
    mod = (Path(__file__).resolve().parents[1] / "static/js/vaultSettings.js").as_uri()
    script = tmp_path / "t.mjs"
    script.write_text(
        f"import {{ transferReport }} from '{mod}';\n"
        "console.log(transferReport({imported: ['A', 'B'], already: ['C'], "
        "left_out: [{name: 'Visa', why: 'a card is not something an agent signs in with'}], "
        "said: [{name: 'B', said: 'kept as a key'}]}));\n"
        "console.log(transferReport({imported: [], already: [], left_out: [], said: []}));\n")
    out = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    first, second = out.stdout.strip().splitlines()
    assert first == ("Brought in 2 items. 1 was already in your vault. Left out: “Visa” (a card is not "
                     "something an agent signs in with). “B”: kept as a key. Each asks you before an agent "
                     "signs in with it; change that on its row.")
    assert second == "Nothing new was brought in."
