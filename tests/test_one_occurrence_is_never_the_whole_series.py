# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1906`. Deleting one occurrence of a repeating event could delete the whole series.

`DELETE /api/calendar/events/{uid}?scope=occurrence` hides one occurrence by
adding it to the series' `recurrence_exdates`, but only when the uid carried
an occurrence suffix (`{series}::{start}`) and the series still repeated.
Otherwise the scope was ignored and the request fell through to the series
delete: the row went, every occurrence with it, and on a CalDAV calendar the
delete was pushed to the server. The Calendar sent exactly that for a series
it held under its own uid (the row a create leaves), and the agent's
`app_api` can send it as the person. Nothing undoes a delete.

Now a request for one occurrence that names no occurrence of a repeating
series is refused with 400 and changes nothing. A real occurrence is hidden
as before, and a delete with no scope still deletes the series. The other
half of the defect, the Calendar's, is
`tests/test_one_occurrence_is_never_the_whole_series_js.py`.

Ported from upstream Odysseus 84aa9a91 (its 400 in `delete_event`).
Driven: the real route over a real SQLite file.
"""
from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import core.database as cdb
import routes.calendar_routes as croutes
from core.database import CalendarCal, CalendarDeletedEvent, CalendarEvent
from tests.helpers.sqlite_db import make_temp_sqlite


@pytest.fixture
def calendar_db(monkeypatch):
    factory, engine, tmpfile = make_temp_sqlite(cdb.Base.metadata)
    monkeypatch.setattr(croutes, "SessionLocal", factory)
    pushed = []

    async def _record_push(owner, uid, action):
        pushed.append((uid, action))

    monkeypatch.setattr(croutes, "_push_caldav_event_after_commit", _record_push)
    with factory() as db:
        for cal_id, source in (("local", "local"), ("remote", "caldav")):
            db.add(CalendarCal(id=cal_id, owner="alice", name=cal_id, source=source))
        for uid, cal_id, rrule in (("S1", "local", "FREQ=WEEKLY"), ("S2", "remote", "FREQ=WEEKLY"),
                                   ("ONCE", "local", "")):
            db.add(CalendarEvent(uid=uid, calendar_id=cal_id, summary=f"Standup {uid}",
                                 dtstart=datetime(2026, 6, 10, 5, 0), dtend=datetime(2026, 6, 10, 6, 0),
                                 is_utc=True, rrule=rrule, recurrence_exdates=""))
        db.commit()
    yield factory, pushed
    engine.dispose()
    tmpfile.close()


def _delete():
    for route in croutes.setup_calendar_routes().routes:
        if route.path == "/api/calendar/events/{uid}" and "DELETE" in route.methods:
            return route.endpoint
    raise AssertionError("DELETE /api/calendar/events/{uid} not found")


def _request():
    return SimpleNamespace(state=SimpleNamespace(current_user="alice"))


def _row(factory, uid):
    with factory() as db:
        return db.query(CalendarEvent).filter(CalendarEvent.uid == uid).first()


async def test_one_occurrence_is_hidden_and_the_series_is_kept(calendar_db):
    factory, pushed = calendar_db
    delete_event = _delete()

    # The series' own uid, asked for one occurrence: refused, nothing changed.
    for uid, scope in (("S1", "occurrence"), ("S1", "instance"), ("S2", "occurrence"),
                       ("ONCE::2026-06-10T05:00", "occurrence")):
        with pytest.raises(HTTPException) as refused:
            await delete_event(_request(), uid, scope=scope)
        assert refused.value.status_code == 400, uid
        assert "occurrence" in refused.value.detail
    for uid in ("S1", "S2", "ONCE"):
        assert _row(factory, uid) is not None, uid
    with factory() as db:
        assert db.query(CalendarDeletedEvent).count() == 0
    assert pushed == []

    # A real occurrence is hidden, and only it.
    answer = await delete_event(_request(), "S1::2026-06-10T05:00", scope="occurrence")
    assert answer == {"ok": True, "scope": "occurrence", "exdate": "2026-06-10T05:00"}
    assert json.loads(_row(factory, "S1").recurrence_exdates) == ["2026-06-10T05:00"]

    # Asked for the series, the series goes, as before.
    assert await delete_event(_request(), "S1") == {"ok": True}
    assert _row(factory, "S1") is None
    assert await delete_event(_request(), "S2", scope="series") == {"ok": True}
    assert pushed == [("S2", "delete")]
