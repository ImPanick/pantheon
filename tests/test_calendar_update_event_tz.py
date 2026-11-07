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
from datetime import datetime, timedelta

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
