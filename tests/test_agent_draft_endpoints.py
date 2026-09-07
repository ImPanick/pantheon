"""The three routes behind the approval card, and the one that was missing (`H01`).

The endpoints have existed since before the fork; nothing called them, so
nothing had ever exercised them either. Driving them here found the defect the
UI would otherwise have inherited: `list_pending` did not return `cc` or `bcc`,
although `_stash_agent_draft` has always stored both. An approval card built on
that endpoint would have shown a message without its recipients, and asked
someone to press Send on a blind copy they could not see.

Owner scoping is tested hardest, because these rows are outbound email. A leak
here is not a disclosure, it is somebody else's mail going out under your
account.
"""
import sqlite3

import pytest


@pytest.fixture
def db(tmp_path, monkeypatch):
    import routes.email_helpers as email_helpers
    import routes.email_routes as email_routes

    path = tmp_path / "scheduled_emails.db"
    monkeypatch.setattr(email_helpers, "SCHEDULED_DB", path)
    monkeypatch.setattr(email_routes, "SCHEDULED_DB", path)
    email_helpers._init_scheduled_db()
    return path


def _stage(db, sid, owner, *, created_at="2025-01-01T00:00:00", status="agent_draft",
           to="a@example.test", cc=None, bcc=None, subject="Subject", body="Body"):
    conn = sqlite3.connect(db)
    conn.execute(
        """INSERT INTO scheduled_emails
           (id, to_addr, cc, bcc, subject, body, attachments, send_at, created_at,
            status, account_id, owner)
           VALUES (?, ?, ?, ?, ?, ?, '[]', '2999-01-01T00:00:00', ?, ?, 'gmail', ?)""",
        (sid, to, cc, bcc, subject, body, created_at, status, owner),
    )
    conn.commit()
    conn.close()


def _status(db, sid):
    conn = sqlite3.connect(db)
    row = conn.execute("SELECT status, send_at FROM scheduled_emails WHERE id = ?",
                       (sid,)).fetchone()
    conn.close()
    return row


@pytest.fixture
def handlers(db, monkeypatch):
    """The four handlers, pulled off the real router by their real paths.

    Matched on the full mounted path rather than a suffix, so a change to the
    router prefix fails this rather than silently matching the wrong route.
    `require_owner` is a FastAPI dependency; the handlers are called with the
    owner passed directly, which is what it resolves to at runtime and keeps
    these tests about the SQL rather than about FastAPI.
    """
    import routes.email_routes as email_routes
    router = email_routes.setup_email_routes()
    wanted = {
        ("/api/email/pending", "GET"): "list",
        ("/api/email/pending/{sid}/approve", "POST"): "approve",
        ("/api/email/pending/{sid}", "DELETE"): "discard",
        ("/api/email/pending/discard-all", "POST"): "discard_all",
    }
    found = {}
    for route in router.routes:
        path = getattr(route, "path", "")
        for method in (getattr(route, "methods", set()) or set()):
            key = wanted.get((path, method))
            if key:
                found[key] = route.endpoint
    missing = set(wanted.values()) - set(found)
    assert not missing, f"routes missing: {missing}"
    return found


async def _call(fn, *args, **kwargs):
    return await fn(*args, **kwargs)


# ── the defect the card would have inherited ────────────────────────────────

@pytest.mark.asyncio
async def test_the_listing_returns_every_recipient_including_bcc(db, handlers):
    """`_stash_agent_draft` has always stored `cc` and `bcc`; this endpoint did
    not return them. A blind copy you cannot see before pressing Send is worse
    than the black hole this row replaces."""
    _stage(db, "d1", "alice", cc="cc@example.test", bcc="secret@example.test")
    out = await _call(handlers["list"], owner="alice")
    assert len(out["pending"]) == 1
    row = out["pending"][0]
    assert row["to_addr"] == "a@example.test"
    assert row["cc"] == "cc@example.test"
    assert row["bcc"] == "secret@example.test"
    assert row["body"] == "Body"


@pytest.mark.asyncio
async def test_the_oldest_age_is_reported_and_is_the_MAX(db, handlers):
    """The row's gating question was *a week or a year*. The panel headline
    needs the oldest, and a mean or a first-row age would understate exactly the
    backlog this exists to surface."""
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    _stage(db, "new", "alice", created_at=(now - timedelta(hours=2)).isoformat())
    _stage(db, "old", "alice", created_at=(now - timedelta(days=400)).isoformat())
    out = await _call(handlers["list"], owner="alice")
    assert out["count"] == 2
    assert out["oldest_age_seconds"] > 399 * 86400
    ages = {r["id"]: r["age_seconds"] for r in out["pending"]}
    assert 7000 < ages["new"] < 7400


@pytest.mark.asyncio
async def test_an_unreadable_timestamp_is_absent_not_zero(db, handlers):
    """`0` reads as *just now*, which is the opposite of what an unparseable
    row usually means — and on this panel it would say the backlog is fresh."""
    _stage(db, "bad", "alice", created_at="not a date")
    out = await _call(handlers["list"], owner="alice")
    assert out["pending"][0]["age_seconds"] is None
    assert out["oldest_age_seconds"] is None


@pytest.mark.asyncio
async def test_the_age_is_read_as_UTC_not_as_local_time(db, handlers, monkeypatch):
    """`created_at` is written as naive UTC. Parsing it as local time reports the
    backlog hours newer or older depending on the operator's offset, which is
    the one number this row exists to put in front of somebody."""
    import os
    import time as _time
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    _stage(db, "d1", "alice", created_at=(now - timedelta(hours=1)).isoformat())
    monkeypatch.setenv("TZ", "Pacific/Auckland")
    try:
        _time.tzset()
        out = await _call(handlers["list"], owner="alice")
    finally:
        os.environ.pop("TZ", None)
        _time.tzset()
    assert 3400 < out["pending"][0]["age_seconds"] < 3800, \
        "the age moved with the machine's timezone"


# ── owner scoping: this is outbound email ───────────────────────────────────

@pytest.mark.asyncio
async def test_one_owner_never_sees_anothers_drafts(db, handlers):
    _stage(db, "mine", "alice")
    _stage(db, "theirs", "bob")
    out = await _call(handlers["list"], owner="alice")
    assert [r["id"] for r in out["pending"]] == ["mine"]


@pytest.mark.asyncio
async def test_one_owner_cannot_approve_anothers_draft(db, handlers):
    """A leak here is not a disclosure — it is somebody else's mail going out."""
    _stage(db, "theirs", "bob")
    out = await _call(handlers["approve"], sid="theirs", owner="alice")
    assert out["success"] is False
    assert _status(db, "theirs")[0] == "agent_draft"


@pytest.mark.asyncio
async def test_one_owner_cannot_discard_anothers_draft(db, handlers):
    _stage(db, "theirs", "bob")
    out = await _call(handlers["discard"], sid="theirs", owner="alice")
    assert out["success"] is False
    assert _status(db, "theirs")[0] == "agent_draft"


@pytest.mark.asyncio
async def test_discard_all_stops_at_the_owner_boundary(db, handlers):
    _stage(db, "a1", "alice")
    _stage(db, "a2", "alice")
    _stage(db, "b1", "bob")
    out = await _call(handlers["discard_all"], owner="alice")
    assert out["success"] is True and out["discarded"] == 2
    assert _status(db, "a1")[0] == "cancelled"
    assert _status(db, "b1")[0] == "agent_draft"


# ── the two verbs ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_approve_makes_the_poller_pick_it_up(db, handlers):
    """The staged row has a far-future `send_at` the poller never reaches, so
    flipping the status alone would leave it exactly as stuck as before."""
    from datetime import datetime
    _stage(db, "d1", "alice")
    assert _status(db, "d1")[1].startswith("2999")
    out = await _call(handlers["approve"], sid="d1", owner="alice")
    assert out["success"] is True
    status, send_at = _status(db, "d1")
    assert status == "pending"
    assert not send_at.startswith("2999")
    assert send_at <= datetime.utcnow().isoformat()


@pytest.mark.asyncio
async def test_discard_cancels_rather_than_deletes(db, handlers):
    """Draining a year-old backlog should not be the destructive act. The row
    stays and can be read back by anyone who wants it."""
    _stage(db, "d1", "alice")
    out = await _call(handlers["discard"], sid="d1", owner="alice")
    assert out["success"] is True
    assert _status(db, "d1")[0] == "cancelled"


@pytest.mark.asyncio
async def test_discard_all_cancels_rather_than_deletes(db, handlers):
    _stage(db, "d1", "alice")
    await _call(handlers["discard_all"], owner="alice")
    assert _status(db, "d1") is not None
    assert _status(db, "d1")[0] == "cancelled"


@pytest.mark.asyncio
async def test_a_second_decision_on_the_same_draft_is_refused(db, handlers):
    """Two clicks, one send. The card disables its buttons while a request is in
    flight, but a second browser tab does not know that."""
    _stage(db, "d1", "alice")
    first = await _call(handlers["approve"], sid="d1", owner="alice")
    second = await _call(handlers["approve"], sid="d1", owner="alice")
    assert first["success"] is True
    assert second["success"] is False
    third = await _call(handlers["discard"], sid="d1", owner="alice")
    assert third["success"] is False, "an approved mail was cancelled after the fact"
    assert _status(db, "d1")[0] == "pending"


@pytest.mark.asyncio
async def test_only_agent_drafts_are_touched(db, handlers):
    """`scheduled_emails` also holds the user's own scheduled mail. A bulk
    discard that reached those would delete work nobody staged on their
    behalf."""
    _stage(db, "draft", "alice", status="agent_draft")
    _stage(db, "user-scheduled", "alice", status="pending")
    out = await _call(handlers["list"], owner="alice")
    assert [r["id"] for r in out["pending"]] == ["draft"]
    await _call(handlers["discard_all"], owner="alice")
    assert _status(db, "user-scheduled")[0] == "pending"
