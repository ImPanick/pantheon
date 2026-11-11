# SPDX-License-Identifier: AGPL-3.0-or-later
"""Marking one message "not spam" clears that message's verdict and no other.

`POST /api/email/{uid}/unflag-spam` updates `email_tags` keyed on `uid` and the
owner alone. An IMAP UID is unique only inside one folder of one account, so a
person with two mailboxes, or a message in Junk and another in INBOX that happen
to share a UID number, had every one of those rows cleared by one click: a real
spam verdict on an unrelated message silently undone.
"""
from __future__ import annotations

import sqlite3
from unittest import mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


DDL = """CREATE TABLE email_tags (
    message_id TEXT, owner TEXT DEFAULT '', account_id TEXT DEFAULT '',
    uid TEXT, folder TEXT, subject TEXT, sender TEXT, tags TEXT,
    spam_verdict INTEGER DEFAULT 0, spam_reason TEXT, moved_to TEXT,
    model_used TEXT, created_at TEXT NOT NULL,
    PRIMARY KEY (message_id, owner, account_id))"""


@pytest.fixture()
def client(tmp_path):
    import routes.email_routes as er
    from routes.email_helpers import require_owner, require_user

    db = tmp_path / "scheduled.db"
    c = sqlite3.connect(db)
    c.execute(DDL)
    rows = [
        ("<clicked@a>", "alice", "acctA", "42", "INBOX"),
        ("<other@b>", "alice", "acctB", "42", "Junk"),
        ("<other@a>", "alice", "acctA", "42", "Archive"),
    ]
    for mid, owner, acct, uid, folder in rows:
        c.execute(
            "INSERT INTO email_tags (message_id, owner, account_id, uid, folder,"
            " spam_verdict, spam_reason, created_at) VALUES (?,?,?,?,?,1,'phish','now')",
            (mid, owner, acct, uid, folder),
        )
    c.commit(); c.close()

    app = FastAPI()
    with mock.patch.object(er, "_start_poller"), mock.patch.object(er, "SCHEDULED_DB", db):
        app.include_router(er.setup_email_routes())
        app.dependency_overrides[require_owner] = lambda: "alice"
        app.dependency_overrides[require_user] = lambda: "alice"
        with TestClient(app) as tc:
            yield tc, db


def _verdicts(db):
    c = sqlite3.connect(db)
    try:
        return dict(c.execute("SELECT message_id, spam_verdict FROM email_tags").fetchall())
    finally:
        c.close()


def test_not_spam_on_one_message_leaves_same_uid_elsewhere_alone(client):
    tc, db = client
    r = tc.post("/api/email/42/unflag-spam",
                params={"folder": "INBOX", "account_id": "acctA"})
    assert r.status_code == 200, r.text
    assert _verdicts(db) == {"<clicked@a>": 0, "<other@b>": 1, "<other@a>": 1}
