# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1139` — one mail fires `email_received` once, whether the inbox was listed
naming its account or not.

Measured by `integrate-e` (P22-00): `<stmt-dark-1400-…>` had two
`email_event_seen` rows, under `default` and under the account's id, and
`Fired email_received` was logged at both listings — the drive's own API call
named no account, the Email window named it. A listing with no account reads
the owner's default mailbox, so both are one mailbox and one key.

Driven through the real `GET /api/email/list` handler and the real IMAP code
(`_imap_connect` → `imaplib`) against a loopback IMAP server
(`tests/helpers/imap_server.py`), the account row in a real SQLite file.
"""

import sqlite3

import pytest

from tests.helpers.imap_server import ImapServer, message
from tests.helpers.walker_harness import make_db

pytestmark = pytest.mark.asyncio

OWNER = "rowan"
ACCOUNT = "8d92c7a0-acct"


@pytest.fixture()
def world(monkeypatch, tmp_path):
    from core.database import EmailAccount
    import routes.email_helpers as email_helpers
    import routes.email_routes as email_routes
    import src.event_bus as bus

    factory = make_db(monkeypatch, tmp_path / "pantheon.db")
    seen_db = tmp_path / "scheduled_emails.db"
    monkeypatch.setattr(email_helpers, "SCHEDULED_DB", seen_db)
    monkeypatch.setattr(email_routes, "SCHEDULED_DB", seen_db)
    email_helpers._init_scheduled_db()
    monkeypatch.setattr(email_routes, "_start_poller", lambda: None)
    fired = []
    monkeypatch.setattr(bus, "fire_event",
                        lambda name, owner=None, payload=None: fired.append((name, owner, payload)))
    with ImapServer() as srv:
        db = factory()
        db.add(EmailAccount(id=ACCOUNT, owner=OWNER, name="Home", is_default=True, enabled=True,
                            imap_host="127.0.0.1", imap_port=srv.port, imap_starttls=False,
                            imap_user="rowan@example.test", imap_password="pw",
                            from_address="rowan@example.test"))
        db.commit()
        db.close()
        router = email_routes.setup_email_routes()
        endpoint = next(r.endpoint for r in router.routes
                        if r.path == "/api/email/list" and "GET" in r.methods)

        async def listing(account_id=None, bust="1"):
            res = await endpoint(folder="INBOX", limit=50, offset=0, filter="all", from_addr=None,
                                 account_id=account_id, has_attachments=0, cached_only=0,
                                 cache_bust=bust, owner=OWNER)
            assert not res.get("error"), res
            return res

        yield {"srv": srv, "list": listing, "fired": fired, "seen_db": seen_db}


def _seen_rows(seen_db, message_key):
    con = sqlite3.connect(seen_db)
    try:
        return con.execute("SELECT account_key FROM email_event_seen WHERE message_key=?",
                           (message_key,)).fetchall()
    finally:
        con.close()


async def test_one_mail_listed_with_and_without_its_account_fires_once(world):
    srv, listing, fired = world["srv"], world["list"], world["fired"]
    srv.box.deliver(message(frm="Old <old@example.test>", subject="Old", mid="old@x"))
    # Both ways of listing have looked at this inbox before the mail lands —
    # the measured order: the drive's call named no account, the window did.
    await listing(account_id=None, bust="1")
    await listing(account_id=ACCOUNT, bust="2")
    assert fired == [], "the first look is a baseline"

    srv.box.deliver(message(frm="Northwind Bank <statements@northwindbank.example.com>",
                            subject="Your September statement", mid="stmt-1@northwind"))
    await listing(account_id=None, bust="3")
    await listing(account_id=ACCOUNT, bust="4")

    assert [(n, o, p["message_key"]) for n, o, p in fired] == [
        ("email_received", OWNER, "<stmt-1@northwind>")], fired
    # The event names the mailbox it read, by its id — what the email tools
    # take to fetch the message — and not the word "default".
    assert fired[0][2]["account"] == ACCOUNT
    assert fired[0][2]["from_address"] == "statements@northwindbank.example.com"
    assert _seen_rows(world["seen_db"], "<stmt-1@northwind>") == [(ACCOUNT,)]


async def test_a_mailbox_recorded_under_default_before_the_fix_is_not_fired_again(world):
    """An install that ran before this kept the account-less listing's
    messages under `default`. The first listing after the upgrade reads them
    as seen: the mail it already fired is not fired a second time, and what
    really is new still is."""
    srv, listing, fired, seen_db = world["srv"], world["list"], world["fired"], world["seen_db"]
    srv.box.deliver(message(frm="a@example.test", subject="Before", mid="before@x"))
    srv.box.deliver(message(frm="statements@northwindbank.example.com", subject="Fired already",
                            mid="fired-already@x"))
    con = sqlite3.connect(seen_db)
    con.execute("CREATE TABLE IF NOT EXISTS email_event_seen (owner TEXT NOT NULL, account_key TEXT NOT NULL, "
                "folder TEXT NOT NULL, message_key TEXT NOT NULL, first_seen_at TEXT NOT NULL, "
                "PRIMARY KEY (owner, account_key, folder, message_key))")
    con.executemany("INSERT INTO email_event_seen VALUES (?, 'default', 'INBOX', ?, '2026-10-02T10:56:21Z')",
                    [(OWNER, "<before@x>"), (OWNER, "<fired-already@x>")])
    con.commit()
    con.close()
    srv.box.deliver(message(frm="b@example.test", subject="Really new", mid="new@x"))

    await listing(account_id=ACCOUNT, bust="1")

    assert [p["message_key"] for _n, _o, p in fired] == ["<new@x>"], fired


async def test_another_owners_default_is_not_this_mailbox(world, monkeypatch):
    """The older key is read only for the mailbox an account-less listing of
    THIS owner reads: a second account of the same owner keeps its own."""
    from core.database import EmailAccount
    import core.database as cdb

    srv, listing, fired, seen_db = world["srv"], world["list"], world["fired"], world["seen_db"]
    db = cdb.SessionLocal()
    db.add(EmailAccount(id="work-acct", owner=OWNER, name="Work", is_default=False, enabled=True,
                        imap_host="127.0.0.1", imap_port=srv.port, imap_starttls=False,
                        imap_user="rowan@work.example", imap_password="pw"))
    db.commit()
    db.close()
    srv.box.deliver(message(frm="a@example.test", subject="Seen", mid="seen@x"))
    con = sqlite3.connect(seen_db)
    con.execute("CREATE TABLE IF NOT EXISTS email_event_seen (owner TEXT NOT NULL, account_key TEXT NOT NULL, "
                "folder TEXT NOT NULL, message_key TEXT NOT NULL, first_seen_at TEXT NOT NULL, "
                "PRIMARY KEY (owner, account_key, folder, message_key))")
    con.execute("INSERT INTO email_event_seen VALUES (?, 'default', 'INBOX', '<seen@x>', 'then')", (OWNER,))
    con.commit()
    con.close()

    await listing(account_id="work-acct", bust="1")
    assert fired == [], "the work account has no baseline of its own yet: this look is its baseline"
    assert _seen_rows(seen_db, "<seen@x>") == [("default",), ("work-acct",)]
