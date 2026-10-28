# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1161` — three mail markers were renamed with nothing carried across.

The rename to Pantheon changed how a reminder is marked and read only the new
marks:

1. `scheduled_emails.odysseus_kind` became `pantheon_kind`, added beside the
   old column with nothing copied — so a reminder queued before the upgrade
   went out as `X-Pantheon-Kind: scheduled`.
2. The mailbox's *Reminders* filter looked only for `X-Pantheon-Kind
   "reminder"` or *"Reminder (Pantheon):"*, so a reminder Odysseus sent
   (`X-Odysseus-Kind`, *"Reminder (Odysseus):"*) was not found by it…
3. …nor by *Clear reminders* (`DELETE /api/email/pantheon/reminders`).

Driven, not read (`Law 20`): the real migration over a real SQLite file in the
old shape and the real scheduled-mail poller; the real list and delete routes
against the loopback IMAP server (`tests/helpers/imap_server.py`, whose SEARCH
now judges `OR`/`HEADER`/`SUBJECT` as a server does), dialled by the real
`_imap_connect`. Only the far end of SMTP is a recorder.
"""
from __future__ import annotations

import asyncio
import email
import re
import sqlite3

import pytest

from tests.helpers.imap_server import ImapServer, message
from tests.test_mail_arriving_runs_its_workflow_with_nobody_looking import (  # noqa: F401
    ACCOUNT, OWNER, world,
)

_OLD_SCHEMA = """
CREATE TABLE scheduled_emails (
    id TEXT PRIMARY KEY, to_addr TEXT NOT NULL, cc TEXT, bcc TEXT, subject TEXT,
    body TEXT NOT NULL, in_reply_to TEXT, references_hdr TEXT, attachments TEXT,
    send_at TEXT NOT NULL, created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending', error TEXT, owner TEXT DEFAULT '',
    account_id TEXT, odysseus_kind TEXT
)
"""


def _queue(db, sid, kind_column, kind):
    con = sqlite3.connect(db)
    con.execute(
        f"INSERT INTO scheduled_emails (id, to_addr, subject, body, attachments, send_at, "
        f"created_at, status, {kind_column}) VALUES (?, 'me@example.test', ?, 'Water the plants.', "
        f"'[]', '2000-01-01T00:00:00', '1999-12-31T00:00:00', 'pending', ?)",
        (sid, f"Reminder: {sid}", kind))
    con.commit()
    con.close()


@pytest.fixture()
def sent(monkeypatch, tmp_path):
    """The old database, migrated by the real `_init_scheduled_db`, and the
    real poller with SMTP's far end recording what it was handed."""
    import routes.email_helpers as eh
    import routes.email_pollers as pollers

    db = tmp_path / "scheduled_emails.db"
    con = sqlite3.connect(db)
    con.execute(_OLD_SCHEMA)
    con.commit()
    con.close()
    _queue(db, "queued-by-odysseus", "odysseus_kind", "reminder")
    monkeypatch.setattr(eh, "SCHEDULED_DB", db)
    monkeypatch.setattr(pollers, "SCHEDULED_DB", db)

    out = []

    class _Sent:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def append(self, *a, **k):
            pass

    monkeypatch.setattr(pollers, "_get_email_config",
                        lambda account_id=None, owner="": {"from_address": "me@example.test"})
    monkeypatch.setattr(pollers, "_owner_for_email_account", lambda account_id: "")
    monkeypatch.setattr(pollers, "_send_smtp_message",
                        lambda cfg, frm, to, raw, *a, **k: out.append(email.message_from_string(raw)))
    monkeypatch.setattr(pollers, "_imap", _Sent)
    monkeypatch.setattr(pollers, "_detect_sent_folder", lambda imap: "Sent")
    monkeypatch.setattr(pollers, "_cleanup_compose_uploads", lambda attachments: None)
    return {"db": db, "out": out, "eh": eh, "pollers": pollers}


def test_a_reminder_queued_before_the_upgrade_goes_out_as_a_reminder(sent):
    """(1) — the upgrade copies the kind across, and the poller sends it."""
    sent["eh"]._init_scheduled_db()                       # the upgrade
    _queue(sent["db"], "queued-by-pantheon", "pantheon_kind", "alert")

    result = sent["pollers"]._scheduled_poll_once()

    assert sorted(result["sent"]) == ["queued-by-odysseus", "queued-by-pantheon"], result
    kinds = {m["X-Pantheon-Ref"]: m["X-Pantheon-Kind"] for m in sent["out"]}
    assert kinds == {"queued-by-odysseus": "reminder", "queued-by-pantheon": "alert"}


def test_an_install_that_already_upgraded_is_carried_across_on_its_next_start(sent):
    """The column was added on an earlier start that copied nothing: the row
    sits with `pantheon_kind` empty, and the next start fills it."""
    con = sqlite3.connect(sent["db"])
    con.execute("ALTER TABLE scheduled_emails ADD COLUMN pantheon_kind TEXT")
    con.commit()
    con.close()

    sent["eh"]._init_scheduled_db()

    con = sqlite3.connect(sent["db"])
    row = con.execute("SELECT pantheon_kind FROM scheduled_emails WHERE id = 'queued-by-odysseus'"
                      ).fetchone()
    con.close()
    assert row == ("reminder",)


# ── (2) and (3): the mailbox ─────────────────────────────────────────────────

_MAILBOX = [
    # (subject, extra headers, is a reminder)
    ("Reminder (Pantheon): water the plants", {"X-Pantheon-Kind": "reminder"}, True),
    ("Reminder (Odysseus): call the dentist", {"X-Odysseus-Kind": "reminder"}, True),
    ("Call the dentist", {"X-Odysseus-Kind": "reminder"}, True),           # header only
    ("Reminder (Odysseus): renew the lease", {}, True),                    # subject only
    ("Your reminder from the library", {}, False),
    ("Lunch on Friday?", {}, False),
]


def _fill(srv):
    for i, (subject, headers, _) in enumerate(_MAILBOX, start=1):
        srv.box.deliver(message(frm=f"{OWNER}@example.test", subject=subject, mid=f"m{i}@x",
                                headers=headers))


def _routes(world):
    pollers = world["pollers"]
    router = world["email_routes"].setup_email_routes()
    for t in (pollers._inbox_task, pollers._poller_task):
        if t is not None:
            t.cancel()
    clear = next(r.endpoint for r in router.routes
                 if getattr(r, "path", "") == "/api/email/pantheon/reminders")
    return pollers._INBOX_HOOKS["list"], clear


@pytest.mark.asyncio
async def test_the_reminders_filter_finds_odysseus_reminders_too(world):
    """(2)."""
    with ImapServer() as srv:
        world["add_account"](srv.port)
        _fill(srv)
        listed, _ = _routes(world)
        out = await asyncio.to_thread(listed, "INBOX", 50, 0, "reminders", ACCOUNT, None, False,
                                      OWNER)
    shown = sorted(e["subject"] for e in out["emails"])
    assert shown == sorted(s for s, _, reminder in _MAILBOX if reminder), out


@pytest.mark.asyncio
async def test_clear_reminders_takes_odysseus_reminders_too(world):
    """(3) — and only reminders: the library's mail and the lunch stay."""
    with ImapServer() as srv:
        world["add_account"](srv.port)
        _fill(srv)
        _, clear = _routes(world)
        # `B1609`: a plain `def` now — its IMAP talk runs in a worker thread, as here.
        await asyncio.to_thread(clear, account_id=ACCOUNT, permanent=False, owner=OWNER)
        stored = {int(u) for line in srv.box.log
                  for u in re.findall(r"UID STORE (\d+) \+FLAGS", line, re.I)}
    assert stored == {i for i, (_, _, reminder) in enumerate(_MAILBOX, start=1) if reminder}


def test_the_urgent_scanner_knows_an_odysseus_reminder_is_its_own_mail():
    """The same pair read by the scanner's self-filter (`src/builtin_actions`),
    so its own old reminders are not classified as urgent mail."""
    from src.mail_headers import is_own_origin, is_reminder

    old = email.message_from_bytes(message(
        frm="me@example.test", subject="Reminder (Odysseus): call", mid="o@x",
        headers={"X-Odysseus-Kind": "reminder", "X-Odysseus-Origin": "odysseus-ui"}))
    stranger = email.message_from_bytes(message(
        frm="lib@example.test", subject="Your reminder from the library", mid="l@x"))
    assert is_reminder(old) and is_own_origin(old)
    assert not is_reminder(stranger) and not is_own_origin(stranger)
