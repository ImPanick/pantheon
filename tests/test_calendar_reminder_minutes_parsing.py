# SPDX-License-Identifier: AGPL-3.0-or-later
"""do_manage_calendar must honour abbreviated reminder phrasings like "mins"/"hrs".

`_reminder_minutes` parsed the reminder offset with regexes anchored on
`(?:m|min|minute|minutes)\b` / `(?:h|hr|hour|hours)\b`. The trailing `\b`
made the very common plural abbreviations "mins" and "hrs" fail to match
(after "min" the next char "s" is a word char, so no boundary), so a request
like ``reminder_minutes: "5 mins"`` silently produced no reminder at all —
even though the sibling duration parser (no `\b`) already accepted them.
"""

import json
import sys
import uuid

import pytest

from tests.helpers.import_state import clear_fake_database_modules
from tests.helpers.sqlite_db import make_temp_sqlite

clear_fake_database_modules()

import core.database as cdb
from core.database import Note

_TS, _ENGINE, _TMPDB = make_temp_sqlite(cdb.Base.metadata)


@pytest.fixture(autouse=True)
def _bind_temp_db(monkeypatch):
    monkeypatch.setitem(sys.modules, "core.database", cdb)
    parent = sys.modules.get("core")
    if parent is not None:
        monkeypatch.setattr(parent, "database", cdb, raising=False)
    monkeypatch.setattr(cdb, "SessionLocal", _TS)
    yield


async def _create_with_reminder(reminder, owner):
    from src.tool_implementations import do_manage_calendar

    payload = {
        "action": "create_event",
        "summary": "Dentist",
        # Far-future so the reminder is never "already passed".
        "dtstart": "2030-01-01T10:00:00",
        "reminder_minutes": reminder,
    }
    return await do_manage_calendar(json.dumps(payload), owner=owner)


@pytest.mark.parametrize("reminder,expected", [
    ("5 mins", 5),
    ("10 mins", 10),
    ("2 hrs", 120),
    ("1 hr", 60),
    ("15 minutes", 15),   # regression: long form still works
    ("30m", 30),          # regression: bare unit still works
])
async def test_reminder_minutes_accepts_abbreviations(reminder, expected):
    owner = "tester-" + uuid.uuid4().hex[:6]
    res = await _create_with_reminder(reminder, owner)
    assert res.get("exit_code") == 0, res
    assert f"reminder {expected} min before" in res.get("response", ""), res

    db = _TS()
    try:
        note = (
            db.query(Note)
            .filter(Note.owner == owner, Note.title == "Reminder: Dentist")
            .first()
        )
        assert note is not None, "reminder note should have been created"
    finally:
        db.close()


async def test_no_reminder_when_offset_absent():
    owner = "tester-" + uuid.uuid4().hex[:6]
    from src.tool_implementations import do_manage_calendar

    payload = {
        "action": "create_event",
        "summary": "No Reminder Event",
        "dtstart": "2030-02-01T10:00:00",
    }
    res = await do_manage_calendar(json.dumps(payload), owner=owner)
    assert res.get("exit_code") == 0, res
    assert "reminder set" not in res.get("response", ""), res


# `B1909` (upstream Odysseus 84aa9a91, corrected). A reminder of 0 minutes ("at
# the event's start", which the Calendar offers beside "No reminder") was
# dropped: the alias chain `a or b or ...` skipped 0 as falsy, and the guard
# `raw in (None, "", False)` is True for 0 in Python, so upstream's alias fix
# alone still dropped it. And deleting an event left its reminder note behind,
# to fire for an event that no longer exists.


def _reminders(owner):
    db = _TS()
    try:
        return sorted((n.title, n.due_date) for n in db.query(Note).filter(Note.owner == owner).all())
    finally:
        db.close()


async def test_a_reminder_at_the_event_start_is_set():
    for zero in (0, 0.0):
        owner = "tester-" + uuid.uuid4().hex[:6]
        res = await _create_with_reminder(zero, owner)
        assert res.get("exit_code") == 0, res
        assert "with reminder 0 min before" in res["response"], res
        assert _reminders(owner) == [("Reminder: Dentist", "2030-01-01T10:00:00")]

    # "No reminder" still means none.
    for none in (False, "", "none"):
        owner = "tester-" + uuid.uuid4().hex[:6]
        res = await _create_with_reminder(none, owner)
        assert res.get("exit_code") == 0, res
        assert "reminder" not in res["response"], res
        assert _reminders(owner) == []


async def test_deleting_an_event_deletes_its_reminder_and_no_other():
    from src.tool_implementations import do_manage_calendar

    owner = "tester-" + uuid.uuid4().hex[:6]
    first = await _create_with_reminder(15, owner)
    # A second event of the same name a week later, with its own reminder.
    second = await do_manage_calendar(json.dumps({
        "action": "create_event", "summary": "Dentist",
        "dtstart": "2030-01-08T10:00:00", "reminder_minutes": 15,
    }), owner=owner)
    assert first.get("exit_code") == 0 and second.get("exit_code") == 0, (first, second)
    assert _reminders(owner) == [("Reminder: Dentist", "2030-01-01T09:45:00"),
                                 ("Reminder: Dentist", "2030-01-08T09:45:00")]

    deleted = await do_manage_calendar(json.dumps({"action": "delete_event", "uid": first["uid"]}),
                                       owner=owner)
    assert deleted.get("exit_code") == 0, deleted
    assert _reminders(owner) == [("Reminder: Dentist", "2030-01-08T09:45:00")]
