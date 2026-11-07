# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1803`. A reminder whose email, ntfy or webhook send failed was never retried.

The background scanner (`action_ping_notes`, about once a minute from the
scheduler) sends each due note through `dispatch_reminder` and then stamped
the note as pinged, whatever the dispatch returned. The dispatcher reports a
failed SMTP send, a non-2xx from ntfy or the webhook, or a timeout as
`*_sent: False` rather than raising, so a reminder whose one send failed was
recorded as delivered and skipped for 25 minutes, by which time it had long
left its ±90 s due window. The channel the person chose never got it, and
nothing said so.

The stamp was also a plain timestamp written over the dispatcher's own
`{at, channel}` receipt, and the dispatcher reads a plain timestamp as
browser-only. So with the app open, an email the scanner had sent went out a
second time when the browser fired the same reminder at its due time.

Now the dispatcher owns the receipts and the scanner counts only what went
out through the configured channel. A failed external send is tried again on
the next scan inside the window, without a second in-app notice, and the
scanner's prune keeps the receipts the dispatch wrote.

Ported from upstream Odysseus a8c147b2 (#6566). Its cases are rebuilt on
Pantheon's helpers, and the app-open double email is added. Driven through
the real scanner, the real dispatcher and the real fire-reminder route over a
real SQLite file; only the far ends (the HTTP client, SMTP, the scheduler's
notice queue) are stand-ins.
"""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

import core.database as cdb
from routes.note import note_routes
from src import builtin_actions
from src.builtin_actions import TaskNoop
from tests.helpers.signed_in import as_person

# Self-hosted ends on the LAN, which the reminder SSRF guard allows by default.
INTEGRATIONS = [
    {"id": "hook", "name": "Home hook", "base_url": "http://192.168.1.50:8080/reminders", "enabled": True},
    {"id": "push", "name": "Home ntfy", "preset": "ntfy", "base_url": "http://192.168.1.51", "enabled": True},
]
MAILBOX = {"account_name": "Home", "smtp_host": "192.168.1.60", "smtp_port": 587,
           "smtp_security": "starttls", "smtp_user": "alice@home.test",
           "smtp_password": "app-password", "from_address": "alice@home.test"}


@pytest.fixture
def reminders(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'notes.db'}",
                           connect_args={"check_same_thread": False}, poolclass=NullPool)
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(cdb, "SessionLocal", factory)
    monkeypatch.setattr(note_routes, "SessionLocal", factory)
    for module in (builtin_actions, note_routes):
        monkeypatch.setattr(module, "DATA_DIR", str(tmp_path))

    settings = {
        "reminder_channel": "webhook",
        "reminder_llm_synthesis": False,
        "reminder_webhook_integration_id": "hook",
        "reminder_webhook_payload_template": '{"message": "{{message}}"}',
        "reminder_ntfy_topic": "reminders",
    }
    monkeypatch.setattr("src.settings.load_settings", lambda: settings)
    monkeypatch.setattr("src.tool_privileges.may_use_tool", lambda *a, **k: True)
    monkeypatch.setattr("src.integrations.load_integrations", lambda: [dict(i) for i in INTEGRATIONS])
    monkeypatch.delenv("REMINDER_WEBHOOK_BLOCK_PRIVATE_IPS", raising=False)

    posts, statuses, mail, notices = [], [], [], []

    class _FarEnd:
        """httpx.AsyncClient at the far end: records each request and answers
        with the next status in `statuses` (200 once they run out)."""

        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def request(self, method, url, **kwargs):
            posts.append(url)
            return httpx.Response(statuses.pop(0) if statuses else 200)

    def smtp(cfg, sender, recipients, message):
        """SMTP at the far end: fails while the next status is an error."""
        if statuses and statuses[0] >= 400:
            statuses.pop(0)
            raise OSError("SMTP server closed the connection")
        mail.append(recipients)

    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", _FarEnd)
    monkeypatch.setattr("routes.email_routes._get_email_config", lambda **kw: dict(MAILBOX))
    monkeypatch.setattr("routes.email_helpers._send_smtp_message", smtp)
    queue = SimpleNamespace(add_notification=lambda **kw: notices.append(kw))
    monkeypatch.setattr(note_routes, "_scheduler_ref", queue)

    now = datetime.now(timezone.utc)
    with factory() as db:
        db.add(cdb.Note(id="note-1", owner="alice", title="Call the plumber",
                        due_date=now.isoformat()))
        db.commit()

    path = tmp_path / "note_pings_alice.json"
    return SimpleNamespace(
        scan=lambda: builtin_actions.action_ping_notes("alice"),
        receipts=lambda: json.loads(path.read_text(encoding="utf-8")),
        path=path, settings=settings, posts=posts, statuses=statuses, mail=mail,
        notices=notices, queue=queue, factory=factory, now=now, real_client=real_client,
    )


@pytest.mark.parametrize("channel", ["webhook", "ntfy"])
async def test_a_failed_send_is_tried_again_on_the_next_scan(reminders, channel):
    r = reminders
    r.settings["reminder_channel"] = channel
    r.statuses[:] = [503, 200]

    with pytest.raises(TaskNoop):
        await r.scan()
    assert len(r.posts) == 1
    assert len(r.notices) == 1, "the in-app notice still goes out"
    assert r.receipts()["note-1"]["channel"] == "browser"

    message, ok = await r.scan()
    assert ok is True and message.startswith("Pinged 1")
    assert len(r.posts) == 2
    assert len(r.notices) == 1, "the retry queued a second in-app notice"
    assert r.receipts()["note-1"]["channel"] == channel

    with pytest.raises(TaskNoop):
        await r.scan()
    assert len(r.posts) == 2, "a delivered reminder was sent again"


async def test_a_failed_email_is_tried_again_on_the_next_scan(reminders):
    r = reminders
    r.settings["reminder_channel"] = "email"
    r.statuses[:] = [503]

    with pytest.raises(TaskNoop):
        await r.scan()
    assert r.mail == []

    _, ok = await r.scan()
    assert ok is True
    assert r.mail == [["alice@home.test"]]
    assert r.receipts()["note-1"]["channel"] == "email"


async def test_a_receipt_from_older_code_does_not_hold_back_the_external_send(reminders):
    """A plain timestamp is what the browser path wrote before receipts had a channel."""
    r = reminders
    r.path.write_text(json.dumps({"note-1": r.now.isoformat()}), encoding="utf-8")

    message, ok = await r.scan()

    assert ok is True and message.startswith("Pinged 1")
    assert len(r.posts) == 1
    assert r.notices == [], "the browser already had this one"
    assert r.receipts()["note-1"]["channel"] == "webhook"


async def test_the_browser_channel_still_sends_once_and_keeps_its_receipt(reminders):
    r = reminders
    r.settings["reminder_channel"] = "browser"

    _, ok = await r.scan()
    assert ok is True
    assert r.receipts()["note-1"]["channel"] == "browser"

    with pytest.raises(TaskNoop):
        await r.scan()
    assert len(r.notices) == 1 and r.posts == []


async def test_a_send_that_reached_no_one_is_not_recorded(reminders, monkeypatch):
    r = reminders
    monkeypatch.setattr(note_routes, "_scheduler_ref", None)
    r.statuses[:] = [503, 200]

    with pytest.raises(TaskNoop):
        await r.scan()
    assert "note-1" not in r.receipts()

    _, ok = await r.scan()
    assert ok is True and len(r.posts) == 2


async def test_the_prune_keeps_the_receipts_the_dispatch_wrote(reminders):
    r = reminders
    with r.factory() as db:
        db.add(cdb.Note(id="later", owner="alice", title="Later",
                        due_date=(r.now + timedelta(days=1)).isoformat()))
        db.commit()
    r.path.write_text(json.dumps({
        "gone": "2026-01-01T00:00:00+00:00",
        "later": {"at": r.now.isoformat(), "channel": "email"},
    }), encoding="utf-8")

    _, ok = await r.scan()

    assert ok is True
    receipts = r.receipts()
    assert set(receipts) == {"note-1", "later"}
    assert receipts["note-1"]["channel"] == "webhook"
    assert receipts["later"]["channel"] == "email"


async def test_an_email_the_scanner_sent_is_not_sent_again_when_the_browser_fires(reminders):
    """The app is open: the scanner sends within 90 s of due, the browser fires at due."""
    r = reminders
    r.settings["reminder_channel"] = "email"
    _, ok = await r.scan()
    assert ok is True and len(r.mail) == 1

    app = FastAPI()
    app.include_router(note_routes.setup_note_routes(task_scheduler=r.queue))
    as_person(app, "alice", auth_manager=SimpleNamespace(
        is_configured=True, get_privileges=lambda _name: {}))
    transport = httpx.ASGITransport(app=app, client=("203.0.113.7", 54321))
    async with r.real_client(transport=transport, base_url="http://notes.test") as c:
        fired = await c.post("/api/notes/fire-reminder", json={"note_id": "note-1"})

    assert fired.status_code == 200, fired.text
    assert len(r.mail) == 1, "the same reminder was emailed twice"
