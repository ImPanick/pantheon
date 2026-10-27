# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1593` — an email account the server will not save is answered with a 4xx
and the sentence, not HTTP 200 with `ok: false`.

`POST /api/email/accounts` with `{}` answered 200 `{"ok": false, "error":
"name required"}`: a refusal reported as a success status, so anything that
trusts the status — `fetch().ok`, a script, the access log — read it as a
save. A port that is not a number was answered the same way, on create and on
edit. Driven through the app's own router in a FastAPI app over a real temp
SQLite (`account_db`), with the person the routes depend on stood in for.
The refusal keeps the `{"ok", "error"}` shape, because that is what the
Settings form reads (`d.error`) to show the sentence.
"""
from __future__ import annotations

from unittest import mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.test_email_account_default_serialization import (  # noqa: F401
    _rows,
    _seed_account,
    account_db,
)


@pytest.fixture()
def client(account_db):
    import routes.email_routes as er
    from routes.email_helpers import require_owner, require_user

    app = FastAPI()
    with mock.patch.object(er, "_start_poller"):
        app.include_router(er.setup_email_routes())
    app.dependency_overrides[require_owner] = lambda: "alice"
    app.dependency_overrides[require_user] = lambda: "alice"
    with TestClient(app) as c:
        yield c, er, account_db


def test_an_account_with_no_name_is_refused_with_a_400_and_the_sentence(client):
    c, er, db = client
    r = c.post("/api/email/accounts", json={})
    assert r.status_code == 400, r.text
    assert r.json() == {"ok": False, "error": er.ACCOUNT_NEEDS_A_NAME}
    assert _rows(db) == [], "a refused account was written"


@pytest.mark.parametrize("field", ["imap_port", "smtp_port"])
def test_a_port_that_is_not_a_number_is_refused_with_a_400(client, field):
    c, _, db = client
    r = c.post("/api/email/accounts", json={"name": "Work", field: "993x"})
    assert r.status_code == 400, r.text
    assert r.json()["ok"] is False and "whole number" in r.json()["error"]
    assert _rows(db) == []


def test_an_edit_with_a_port_that_is_not_a_number_is_refused_with_a_400(client):
    c, _, db = client
    _seed_account(db, "acct1", "alice", is_default=True)
    r = c.put("/api/email/accounts/acct1", json={"name": "Renamed", "imap_port": "imap"})
    assert r.status_code == 400, r.text
    assert "whole number" in r.json()["error"]
    from core.database import EmailAccount
    s = db()
    try:
        assert s.get(EmailAccount, "acct1").name == "acct1", "the refused edit was half-saved"
    finally:
        s.close()


def test_an_account_that_can_be_saved_is_still_answered_200(client):
    c, _, db = client
    r = c.post("/api/email/accounts", json={"name": "Work", "imap_host": "mail.example.com"})
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    assert [owner for _, owner, _ in _rows(db)] == ["alice"]
