# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1804`. The daily brief listed calendar events at the wrong hour, or not at all.

Pantheon's calendar stores an event that carries a zone (one made in the
calendar, by the agent's calendar tool, or pulled by CalDAV) as a UTC instant,
with `is_utc` on the row. The daily brief bounded "today" by the server's local
midnight, compared those bounds with every row as stored, and printed the
stored hour. On a server whose zone is not UTC, a UTC row was listed at its UTC
hour and a late event that falls on the next UTC day was dropped. On the
default container, whose zone is UTC, every brief was in UTC, wherever the
person lives.

Now a UTC row is bounded by the day's start and end, each converted to UTC on
its own (which keeps a 23- or 25-hour daylight-saving day right), and printed
in local time; floating and all-day rows keep the local-day comparison. The
day is the zone the task fires in when it has one (its own, then its crew
member's: `P8-32`'s one resolver), and the server's clock otherwise, which the
brief now names.

Ported from upstream Odysseus ef3467e8 (#6926), with its cases. The task's
zone, the named clock and the scheduler half are Pantheon's.
"""
import asyncio
import os
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import core.database as cdb
from src import builtin_actions

needs_tzset = pytest.mark.skipif(not hasattr(time, "tzset"),
                                 reason="changes the process's local time zone")


@contextmanager
def server_zone(name):
    previous = os.environ.get("TZ")
    os.environ["TZ"] = name
    time.tzset()
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = previous
        time.tzset()


def _memory_db():
    return create_engine("sqlite://", poolclass=StaticPool,
                         connect_args={"check_same_thread": False})


@pytest.fixture
def calendar(monkeypatch):
    """Alice's, Bob's and an unowned calendar; returns `add(uid, start, end, ...)`."""
    engine = _memory_db()
    for model in (cdb.CalendarCal, cdb.CalendarEvent, cdb.Note):
        model.__table__.create(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(cdb, "SessionLocal", factory)
    # An install with accounts, so an unowned row is nobody's (`HIGH-12`).
    monkeypatch.setattr("src.auth_manager_access.shared_auth_manager",
                        lambda: SimpleNamespace(is_configured=True))

    def no_mailbox(*args, **kwargs):
        raise RuntimeError("no mailbox in a calendar-only brief")

    monkeypatch.setattr("routes.email_helpers._imap_connect", no_mailbox)
    with factory() as db:
        for owner in ("alice", "bob", None):
            db.add(cdb.CalendarCal(id=owner or "shared", owner=owner, name=owner or "shared"))
        db.commit()

    def add(uid, start, end, *, stored_utc=False, all_day=False, owner="alice",
            status="confirmed"):
        """`start` and `end` are wall-clock times (naive means the server's
        zone); a UTC row stores them as the UTC instant, the others as typed."""
        def stored(value):
            if stored_utc and not all_day:
                return value.astimezone(timezone.utc).replace(tzinfo=None)
            return value.replace(tzinfo=None)

        with factory() as db:
            db.add(cdb.CalendarEvent(uid=uid, calendar_id=owner or "shared", summary=uid,
                                     dtstart=stored(start), dtend=stored(end),
                                     is_utc=stored_utc, all_day=all_day, status=status))
            db.commit()

    yield add
    engine.dispose()


def _brief(**kwargs):
    text, ok = asyncio.run(builtin_actions.action_daily_brief("alice", **kwargs))
    assert ok, text
    return text


def _midnight(now):
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


@needs_tzset
@pytest.mark.parametrize("zone", ["Europe/Berlin", "America/Los_Angeles"])
def test_the_brief_lists_the_local_day_in_local_hours_whatever_the_storage(calendar, zone):
    add = calendar
    with server_zone(zone):
        today = _midnight(datetime.now())
        add("early", today + timedelta(minutes=30), today + timedelta(hours=1), stored_utc=True)
        add("utc-ten", today + timedelta(hours=10), today + timedelta(hours=11), stored_utc=True)
        add("local-nine", today + timedelta(hours=9), today + timedelta(hours=10))
        add("all-day", today, today + timedelta(days=1), stored_utc=True, all_day=True)
        add("next-day", today + timedelta(days=1, minutes=30), today + timedelta(days=1, hours=1),
            stored_utc=True)
        add("ended", today - timedelta(hours=1), today, stored_utc=True)
        add("cancelled", today + timedelta(hours=12), today + timedelta(hours=13), stored_utc=True,
            status="cancelled")
        add("foreign", today + timedelta(hours=12), today + timedelta(hours=13), stored_utc=True,
            owner="bob")
        add("unowned", today + timedelta(hours=12), today + timedelta(hours=13), owner=None)
        text = _brief()

    lines = ["all day  all-day", "00:30  early", "09:00  local-nine", "10:00  utc-ten"]
    for line in lines:
        assert line in text, text
    assert [text.index(line) for line in lines] == sorted(text.index(line) for line in lines), text
    for excluded in ("next-day", "ended", "cancelled", "foreign", "unowned"):
        assert excluded not in text, text


@needs_tzset
def test_a_task_s_own_zone_is_the_day_and_the_clock_of_its_brief(calendar):
    """The default container runs in UTC; the person lives in New York."""
    new_york = ZoneInfo("America/New_York")
    with server_zone("UTC"):
        today = _midnight(datetime.now(new_york))
        calendar("standup", today + timedelta(hours=10), today + timedelta(hours=10, minutes=15),
                 stored_utc=True)
        calendar("dinner", today + timedelta(hours=20, minutes=30), today + timedelta(hours=22),
                 stored_utc=True)
        calendar("tomorrow", today + timedelta(days=1, hours=1), today + timedelta(days=1, hours=2),
                 stored_utc=True)
        text = _brief(tz_name="America/New_York")

    assert "10:00  standup" in text, text
    assert "20:30  dinner" in text, "an evening on the next UTC day was dropped"
    assert "tomorrow" not in text, text
    assert f"{today:%A, %B} {today.day}, {today:%Y}" in text, "the date is the person's"


@needs_tzset
def test_floating_and_all_day_rows_keep_the_local_day(calendar):
    with server_zone("Europe/Berlin"):
        today = _midnight(datetime.now())
        calendar("dentist", today + timedelta(hours=23), today + timedelta(hours=23, minutes=30))
        calendar("holiday", today, today + timedelta(days=1), all_day=True)
        calendar("yesterday", today - timedelta(hours=2), today - timedelta(hours=1))
        text = _brief()

    assert "23:00  dentist" in text and "all day  holiday" in text, text
    assert "yesterday" not in text, text


@needs_tzset
def test_without_a_zone_the_brief_says_whose_clock_its_times_are(calendar):
    with server_zone("UTC"):
        today = _midnight(datetime.now())
        calendar("standup", today + timedelta(hours=10), today + timedelta(hours=11), stored_utc=True)
        server = _brief()
        own = _brief(tz_name="UTC")

    assert "Calendar (server time, UTC):" in server, server
    assert "Calendar:" in own and "server time" not in own, own


@pytest.mark.parametrize("day, hours", [("2026-03-29", 23), ("2026-10-25", 25)])
def test_a_daylight_saving_day_is_bounded_by_the_offset_at_each_end(day, hours):
    start = datetime.fromisoformat(day)
    berlin = ZoneInfo("Europe/Berlin")
    begin = builtin_actions._daily_brief_utc_boundary(start, berlin)
    end = builtin_actions._daily_brief_utc_boundary(start + timedelta(days=1), berlin)
    assert end - begin == timedelta(hours=hours)
    if hasattr(time, "tzset"):
        with server_zone("Europe/Berlin"):
            assert builtin_actions._daily_brief_utc_boundary(start) == begin
            assert builtin_actions._daily_brief_utc_boundary(start + timedelta(days=1)) == end


@pytest.mark.parametrize("stored_utc, all_day, expected", [
    (True, False, datetime(2026, 6, 1, 10)),
    (False, False, datetime(2026, 6, 1, 8)),
    (True, True, datetime(2026, 6, 1, 8)),
])
def test_only_a_stored_utc_instant_is_converted_to_local_time(stored_utc, all_day, expected):
    event = SimpleNamespace(dtstart=datetime(2026, 6, 1, 8), is_utc=stored_utc, all_day=all_day)
    assert builtin_actions._daily_brief_local_start(event, ZoneInfo("Europe/Berlin")) == expected


# ── the scheduler hands the brief the zone the task fires in ────────────────

@pytest.fixture
def brief_kwargs(monkeypatch):
    """What `daily_brief` is called with, through the scheduler's real
    `_execute_action`; the brief itself is a recorder."""
    seen = []

    async def brief(**kwargs):
        seen.append(kwargs)
        return "brief", True

    monkeypatch.setitem(builtin_actions.BUILTIN_ACTIONS, "daily_brief", brief)
    return seen


def _execute(**task):
    from src.task_scheduler import TaskScheduler
    row = SimpleNamespace(**{"action": "daily_brief", "owner": "alice", "name": "Morning brief",
                             "prompt": None, "tz_name": None, "crew_member_id": None, **task})
    return asyncio.run(TaskScheduler.__new__(TaskScheduler)._execute_action(row))


def test_the_scheduler_hands_the_brief_the_task_s_own_zone(brief_kwargs):
    _execute(tz_name="Europe/Berlin")
    assert brief_kwargs[-1].get("tz_name") == "Europe/Berlin"


def test_a_task_that_follows_its_crew_member_hands_the_brief_that_zone(brief_kwargs, monkeypatch):
    engine = _memory_db()
    cdb.Base.metadata.create_all(engine, tables=[cdb.Session.__table__, cdb.CrewMember.__table__])
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(cdb, "SessionLocal", factory)
    with factory() as db:
        db.add(cdb.CrewMember(id="cm1", owner="alice", name="Sydney desk",
                              timezone="Australia/Sydney"))
        db.commit()

    _execute(crew_member_id="cm1")

    assert brief_kwargs[-1].get("tz_name") == "Australia/Sydney"
    engine.dispose()


def test_a_task_with_no_zone_leaves_the_brief_on_the_server_s_clock(brief_kwargs):
    _execute()
    assert "tz_name" not in brief_kwargs[-1]
