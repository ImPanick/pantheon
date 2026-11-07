# SPDX-License-Identifier: AGPL-3.0-or-later
"""update_event must anchor datetimes to the user tz, like create_event.

create_event parses a naive/natural-language dtstart in the USER's
timezone (parse_due_for_user -> stored naive-UTC, is_utc=True), but
update_event parsed args["dtstart"] with the raw server-local _parse_dt
and never refreshed is_utc. So updating an event to the same naive value
it was created with silently shifted it by the user's UTC offset (9h for a
Tokyo user) and left is_utc inconsistent. The do_manage_notes update path
was already fixed for the analogous issue.
"""
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

import core.database as cdb
from core.database import CalendarCal, CalendarEvent
from tests.helpers.sqlite_db import make_temp_sqlite

_TS, _ENGINE, _TMPDB = make_temp_sqlite(cdb.Base.metadata)


@pytest.fixture(autouse=True)
def _bind_temp_db(monkeypatch):
    monkeypatch.setattr(cdb, "SessionLocal", _TS)
    import routes.calendar_routes as cr
    monkeypatch.setattr(cr, "SessionLocal", _TS, raising=False)
    yield


@pytest.fixture
def tokyo_offset():
    from routes.calendar_routes import set_user_tz_offset
    set_user_tz_offset(540)  # Tokyo, UTC+9
    try:
        yield
    finally:
        set_user_tz_offset(None)


async def test_update_event_dtstart_anchored_to_user_tz(tokyo_offset):
    from src.tool_implementations import do_manage_calendar

    owner = "tz-" + uuid.uuid4().hex[:6]
    naive = "2026-06-10T14:00:00"  # 14:00 Tokyo == 05:00 UTC

    created = await do_manage_calendar(json.dumps({
        "action": "create_event",
        "summary": "Standup",
        "dtstart": naive,
    }), owner=owner)
    assert created.get("exit_code", 0) == 0, created
    uid = created["uid"]

    db = _TS()
    try:
        ev = db.query(CalendarEvent).filter(CalendarEvent.uid == uid).first()
        created_dtstart, created_is_utc = ev.dtstart, ev.is_utc
    finally:
        db.close()

    # Update the same event to the SAME naive wall-clock value.
    updated = await do_manage_calendar(json.dumps({
        "action": "update_event",
        "uid": uid,
        "dtstart": naive,
    }), owner=owner)
    assert updated.get("exit_code", 0) == 0, updated

    db = _TS()
    try:
        ev = db.query(CalendarEvent).filter(CalendarEvent.uid == uid).first()
        # Same input -> same stored moment and same is_utc flag as create.
        assert ev.dtstart == created_dtstart
        assert bool(ev.is_utc) == bool(created_is_utc)
        # And concretely: 14:00 Tokyo is 05:00 UTC, stored naive-UTC.
        assert ev.dtstart.hour == 5
        assert bool(ev.is_utc) is True
    finally:
        db.close()


# `B1907` (upstream Odysseus 218d7624). update_event gave an event a new start
# and kept its old end when no end came with it, which Pantheon's own prompt
# allows and the email-to-calendar pass does whenever a mail gives no end: moved
# later, the event ended before it began and dropped out of its own day's list;
# moved earlier, it was stretched. And a uid copied out of a reply's
# `[Summary](#event-<uid>)` anchor was "not found".


def _stored(uid):
    db = _TS()
    try:
        ev = db.query(CalendarEvent).filter(CalendarEvent.uid == uid).first()
        return None if ev is None else (ev.summary, ev.dtstart, ev.dtend)
    finally:
        db.close()


async def _create(owner, summary, dtstart, dtend):
    from src.tool_implementations import do_manage_calendar

    created = await do_manage_calendar(json.dumps({
        "action": "create_event", "summary": summary, "dtstart": dtstart, "dtend": dtend,
    }), owner=owner)
    assert created.get("exit_code", 0) == 0, created
    return created["uid"]


async def _update(owner, **fields):
    from src.tool_implementations import do_manage_calendar

    updated = await do_manage_calendar(json.dumps({"action": "update_event", **fields}), owner=owner)
    assert updated.get("exit_code", 0) == 0, updated
    return updated


async def test_update_event_new_start_preserves_duration_when_end_is_omitted(tokyo_offset):
    owner = "move-duration-" + uuid.uuid4().hex[:6]
    uid = await _create(owner, "Dinner", "2026-10-11T09:30:00", "2026-10-11T11:00:00")

    await _update(owner, uid=uid, dtstart="2026-10-12T21:30:00")

    _, start, end = _stored(uid)
    assert start == datetime(2026, 10, 12, 12, 30)      # 21:30 Tokyo, stored as UTC
    assert end - start == timedelta(minutes=90)
    assert end > start

    # Upstream's tail: the moved event is on its new evening (`B1908`).
    from src.tool_implementations import do_manage_calendar
    listed = await do_manage_calendar(json.dumps({
        "action": "list_events",
        "start": "2026-10-12T18:00:00",
        "end": "2026-10-13T00:00:00",
    }), owner=owner)
    assert listed.get("exit_code", 0) == 0, listed
    assert [event["summary"] for event in listed["events"]] == ["Dinner"]


async def test_update_event_earlier_start_keeps_the_length_and_a_given_end_is_kept(tokyo_offset):
    owner = "move-earlier-" + uuid.uuid4().hex[:6]
    uid = await _create(owner, "Dentist", "2026-10-11T09:30:00", "2026-10-11T11:00:00")

    await _update(owner, uid=uid, dtstart="2026-10-11T07:00:00")
    _, start, end = _stored(uid)
    assert (start, end - start) == (datetime(2026, 10, 10, 22, 0), timedelta(minutes=90))

    # Both ends given: the given end, as before.
    await _update(owner, uid=uid, dtstart="2026-10-11T08:00:00", dtend="2026-10-11T12:00:00")
    _, start, end = _stored(uid)
    assert (start, end) == (datetime(2026, 10, 10, 23, 0), datetime(2026, 10, 11, 3, 0))


async def test_an_event_anchor_in_place_of_its_uid_finds_the_event(tokyo_offset):
    from src.tool_implementations import do_manage_calendar

    owner = "anchor-" + uuid.uuid4().hex[:6]
    uid = await _create(owner, "Review", "2026-10-11T09:30:00", "2026-10-11T11:00:00")

    await _update(owner, uid=f"#event-{uid}", summary="Review (moved)")
    assert _stored(uid)[0] == "Review (moved)"
    await _update(owner, uid=f"event-{uid}", summary="Review (again)")
    assert _stored(uid)[0] == "Review (again)"
    deleted = await do_manage_calendar(json.dumps({"action": "delete_event", "uid": f"#event-{uid}"}),
                                       owner=owner)
    assert deleted.get("exit_code", 0) == 0, deleted
    assert _stored(uid) is None

    # A real uid that begins with `event-` is tried first and finds itself.
    plain = "abc" + uuid.uuid4().hex[:6]
    db = _TS()
    try:
        cal = CalendarCal(id="cal-" + plain, owner=owner, name="Main")
        db.add(cal)
        for row_uid in (f"event-{plain}", plain):
            db.add(CalendarEvent(uid=row_uid, calendar_id=cal.id, summary=row_uid,
                                 dtstart=datetime(2026, 10, 11, 1, 0), dtend=datetime(2026, 10, 11, 2, 0),
                                 is_utc=True))
        db.commit()
    finally:
        db.close()
    deleted = await do_manage_calendar(json.dumps({"action": "delete_event", "uid": f"event-{plain}"}),
                                       owner=owner)
    assert deleted.get("exit_code", 0) == 0, deleted
    assert _stored(f"event-{plain}") is None
    assert _stored(plain) is not None

    missing = await do_manage_calendar(json.dumps({"action": "delete_event", "uid": "#event-nope"}),
                                       owner=owner)
    assert missing == {"error": "Event #event-nope not found", "exit_code": 1}


async def test_list_events_accepts_start_time_end_time_aliases():
    from src.tool_implementations import do_manage_calendar

    owner = "list-" + uuid.uuid4().hex[:6]
    created = await do_manage_calendar(json.dumps({
        "action": "create_event",
        "summary": "July planning",
        "dtstart": "2026-07-15T12:00:00Z",
        "dtend": "2026-07-15T13:00:00Z",
    }), owner=owner)
    assert created.get("exit_code", 0) == 0, created

    listed = await do_manage_calendar(json.dumps({
        "action": "list_events",
        "start_time": "2026-07-01T00:00:00Z",
        "end_time": "2026-08-01T00:00:00Z",
    }), owner=owner)
    assert listed.get("exit_code", 0) == 0, listed
    assert "between 2026-07-01 and 2026-08-01" in listed["response"]
    assert [event["summary"] for event in listed["events"]] == ["July planning"]


async def test_list_events_query_without_range_does_not_default_to_two_weeks():
    from src.tool_implementations import do_manage_calendar

    listed = await do_manage_calendar(json.dumps({
        "action": "list_events",
        "query": "July",
    }), owner="list-" + uuid.uuid4().hex[:6])
    assert listed.get("exit_code") == 1, listed
    assert "explicit start/end" in listed["error"]


# `B1908` (upstream Odysseus 218d7624, adapted). list_events read the bounds a
# chat sends, naive local times as its prompt asks, as if they were UTC, and
# compared them with timed rows stored in UTC: anyone away from UTC was shown
# the wrong day, off by their offset. All-day and floating rows are stored as
# wall time, so reading the bounds in UTC for every row (upstream's one-line
# swap) would pull in the neighbouring day's all-day event instead. Each row is
# now compared in the frame it is stored in.


@pytest.fixture
def anchorage_offset():
    from routes.calendar_routes import set_user_tz_offset
    set_user_tz_offset(-540)  # Anchorage in summer, UTC-9
    try:
        yield
    finally:
        set_user_tz_offset(None)


def _all_day_rows(owner, *days):
    """All-day rows as CalDAV, .ics import and the Calendar store them: naive dates."""
    db = _TS()
    try:
        cal = CalendarCal(id="cal-" + owner, owner=owner, name="Main")
        db.add(cal)
        for day in days:
            start = datetime.fromisoformat(day)
            db.add(CalendarEvent(uid=f"{owner}-{day}", calendar_id=cal.id, summary=f"All day {day}",
                                 dtstart=start, dtend=start + timedelta(days=1),
                                 all_day=True, is_utc=False))
        db.commit()
    finally:
        db.close()


async def _listed(owner, start, end):
    from src.tool_implementations import do_manage_calendar

    listed = await do_manage_calendar(json.dumps({"action": "list_events", "start": start, "end": end}),
                                      owner=owner)
    assert listed.get("exit_code", 0) == 0, listed
    return listed


async def test_a_days_list_in_tokyo_holds_that_days_events(tokyo_offset):
    owner = "list-tokyo-" + uuid.uuid4().hex[:6]
    await _create(owner, "Breakfast meeting", "2026-06-10T08:00:00", "2026-06-10T09:00:00")
    await _create(owner, "Next breakfast", "2026-06-11T08:00:00", "2026-06-11T09:00:00")
    _all_day_rows(owner, "2026-06-09", "2026-06-10")

    listed = await _listed(owner, "2026-06-10T00:00:00", "2026-06-11T00:00:00")

    assert sorted(event["summary"] for event in listed["events"]) == ["All day 2026-06-10", "Breakfast meeting"]
    assert "between 2026-06-10 and 2026-06-11" in listed["response"]


async def test_a_days_list_west_of_utc_holds_that_days_events(anchorage_offset):
    owner = "list-anchorage-" + uuid.uuid4().hex[:6]
    await _create(owner, "Dinner", "2026-06-10T20:00:00", "2026-06-10T21:00:00")
    await _create(owner, "Last night's dinner", "2026-06-09T20:00:00", "2026-06-09T21:00:00")
    _all_day_rows(owner, "2026-06-10", "2026-06-11")

    listed = await _listed(owner, "2026-06-10T00:00:00", "2026-06-11T00:00:00")

    assert sorted(event["summary"] for event in listed["events"]) == ["All day 2026-06-10", "Dinner"]
    assert "between 2026-06-10 and 2026-06-11" in listed["response"]


# `B1909` (upstream Odysseus 84aa9a91). An all-day date from the agent was read
# as the person's midnight and stored as its UTC instant: east of UTC that is
# the day before, so a birthday was shown, listed and synced a day early. It is
# now kept as the calendar day written, the way CalDAV, .ics and the Calendar
# store all-day rows, and its reminder is timed against the person's clock.


async def test_create_all_day_date_preserves_literal_calendar_day(tokyo_offset):
    from src.tool_implementations import do_manage_calendar

    owner = "all-day-date-" + uuid.uuid4().hex[:6]
    created = await do_manage_calendar(json.dumps({
        "action": "create_event",
        "summary": "My Birthday",
        "dtstart": "2026-10-24",
        "all_day": True,
        "rrule": "FREQ=YEARLY",
    }), owner=owner)
    assert created.get("exit_code", 0) == 0, created

    db = _TS()
    try:
        ev = db.query(CalendarEvent).filter(CalendarEvent.uid == created["uid"]).first()
        assert bool(ev.all_day) is True
        assert bool(ev.is_utc) is False
        assert ev.dtstart.isoformat() == "2026-10-24T00:00:00"
        assert ev.dtend.isoformat() == "2026-10-25T00:00:00"
    finally:
        db.close()

    listed = await _listed(owner, "2026-10-24T00:00:00", "2026-10-25T00:00:00")
    assert [event["dtstart"] for event in listed["events"]] == ["2026-10-24"]
    assert (await _listed(owner, "2026-10-23T00:00:00", "2026-10-24T00:00:00"))["events"] == []


async def test_an_all_day_event_keeps_its_days_when_written_with_times_or_moved(tokyo_offset):
    from src.tool_implementations import do_manage_calendar

    owner = "all-day-times-" + uuid.uuid4().hex[:6]
    # An end later on the start's own day is that one day; one later on a
    # following day keeps that day too (all-day ends are exclusive).
    one = await do_manage_calendar(json.dumps({
        "action": "create_event", "summary": "Holiday", "all_day": True,
        "dtstart": "2026-10-24T00:00:00", "dtend": "2026-10-24T23:59:59",
    }), owner=owner)
    trip = await do_manage_calendar(json.dumps({
        "action": "create_event", "summary": "Trip", "all_day": True,
        "dtstart": "2026-10-24", "dtend": "2026-10-26T18:00:00",
    }), owner=owner)
    assert _stored(one["uid"])[1:] == (datetime(2026, 10, 24), datetime(2026, 10, 25))
    assert _stored(trip["uid"])[1:] == (datetime(2026, 10, 24), datetime(2026, 10, 27))

    # Moved with update_event, it lands on the day written and keeps its length.
    await _update(owner, uid=trip["uid"], dtstart="2026-11-03")
    assert _stored(trip["uid"])[1:] == (datetime(2026, 11, 3), datetime(2026, 11, 6))
    await _update(owner, uid=one["uid"], dtstart="2026-11-01T00:00:00", dtend="2026-11-01")
    assert _stored(one["uid"])[1:] == (datetime(2026, 11, 1), datetime(2026, 11, 2))


async def test_an_all_day_reminder_is_timed_by_the_persons_clock(anchorage_offset, monkeypatch):
    import src.user_time as user_time
    from core.database import Note
    from src.tool_implementations import do_manage_calendar

    # 20:00 on 9 June in Anchorage is already 10 June in UTC.
    evening = datetime(2026, 6, 9, 20, 0, tzinfo=timezone(timedelta(hours=-9)))
    monkeypatch.setattr(user_time, "now_user_local", lambda now_utc=None: evening)
    owner = "all-day-remind-" + uuid.uuid4().hex[:6]
    created = await do_manage_calendar(json.dumps({
        "action": "create_event", "summary": "Moving day", "all_day": True,
        "dtstart": "2026-06-10", "reminder_minutes": 30,
    }), owner=owner)
    assert created.get("exit_code", 0) == 0, created
    assert "with reminder 30 min before" in created["response"], created

    db = _TS()
    try:
        note = db.query(Note).filter(Note.owner == owner).one()
        assert note.due_date == "2026-06-09T23:30:00"
    finally:
        db.close()
