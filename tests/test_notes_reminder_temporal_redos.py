# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B1919`. A reminder note of a digit and a long whitespace run held the server.

When the agent adds a note that reads like a reminder and gives it no due
date, `do_manage_notes` looks in the note's text for a time phrase. One of the
phrases it looks for, `\d{1,2}(?::\d{2})?\s*(?:am|pm)?\s+today`, let `\s*` and
`\s+` split one whitespace run every possible way, so a digit followed by a
long run of whitespace took the square of the run: 40,000 tabs took about 13
seconds on the loaded test machine, with the GIL held. The meridiem now takes
its own whitespace, `(?:\s*(?:am|pm))?\s+`: the same phrases, one way to read
each. Ported from upstream Odysseus 3d91ad82; the cases are upstream's.
"""

import json
import sys
import time
import uuid

import pytest

from tests.helpers.import_state import clear_fake_database_modules
from tests.helpers.sqlite_db import make_temp_sqlite

clear_fake_database_modules()

import core.database as cdb

_TS, _ENGINE, _TMPDB = make_temp_sqlite(cdb.Base.metadata)


@pytest.fixture(autouse=True)
def _bind_temp_db(monkeypatch):
    monkeypatch.setitem(sys.modules, "core.database", cdb)
    parent = sys.modules.get("core")
    if parent is not None:
        monkeypatch.setattr(parent, "database", cdb, raising=False)
    monkeypatch.setattr(cdb, "SessionLocal", _TS)
    yield


async def _add(content):
    from src.tool_implementations import do_manage_notes

    return await do_manage_notes(
        json.dumps({"action": "add", "title": "remind me", "content": content}),
        owner="tester-" + uuid.uuid4().hex[:6],
    )


async def test_a_reminder_of_a_digit_and_a_long_whitespace_run_is_read_in_one_pass():
    started = time.perf_counter()
    res = await _add("remind 1" + "\t" * 40_000 + "x")
    assert time.perf_counter() - started < 2.0
    assert res.get("exit_code", 0) == 0, res


@pytest.mark.parametrize("content, due", [
    ("remind me to call mom, 9 pm tomorrow", "T21:00:00"),
    ("remind me to water the plants 7am today", "T07:00:00"),
    ("remind me: 10:30 tonight", "T10:30:00"),
])
async def test_a_reminder_still_finds_its_time_first_phrase(content, due):
    res = await _add(content)
    assert res.get("exit_code", 0) == 0, res
    db = _TS()
    try:
        note = db.query(cdb.Note).filter(cdb.Note.id == res["note_id"]).first()
        assert note is not None and due in (note.due_date or ""), note and note.due_date
    finally:
        db.close()
