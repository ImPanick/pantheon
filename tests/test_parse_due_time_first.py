# SPDX-License-Identifier: AGPL-3.0-or-later
"""Regression: parse_due_for_user must handle time-first phrasings.

The tool schema and tool_index both advertise '11pm today' as a valid
due_date example. The parser's natural-language branch only matched
day-first format ('today at 11pm'), so time-first strings like '3pm today'
raised ValueError, fell back to the raw string, and the ISO-only reminder
scanner never fired the note. Fixes #3302.

`B1919` is at the bottom: a time phrase that is a long run of whitespace.
"""
import time
from datetime import datetime, timezone

import pytest

import routes.calendar_routes as calendar_routes
from src.user_time import clear_user_time_context, set_user_tz_name, set_user_tz_offset


class _FixedNow(datetime):
    """Freeze server clock at 2026-06-07T10:00:00 UTC for deterministic tests."""
    @classmethod
    def now(cls, tz=None):
        value = datetime(2026, 6, 7, 10, 0, 0, tzinfo=timezone.utc)
        if tz is not None:
            return value.astimezone(tz)
        return value.replace(tzinfo=None)


def setup_function():
    clear_user_time_context()
    set_user_tz_offset(0)
    set_user_tz_name("UTC")


def teardown_function():
    clear_user_time_context()


def test_time_first_today(monkeypatch):
    monkeypatch.setattr(calendar_routes, "datetime", _FixedNow)
    result = calendar_routes.parse_due_for_user("3pm today")
    assert result.startswith("2026-06-07T15:00:00")


def test_time_first_today_11pm(monkeypatch):
    monkeypatch.setattr(calendar_routes, "datetime", _FixedNow)
    result = calendar_routes.parse_due_for_user("11pm today")
    assert result.startswith("2026-06-07T23:00:00")


def test_time_first_tomorrow(monkeypatch):
    monkeypatch.setattr(calendar_routes, "datetime", _FixedNow)
    result = calendar_routes.parse_due_for_user("9am tomorrow")
    assert result.startswith("2026-06-08T09:00:00")


def test_time_first_with_minutes(monkeypatch):
    monkeypatch.setattr(calendar_routes, "datetime", _FixedNow)
    result = calendar_routes.parse_due_for_user("2:30pm tomorrow")
    assert result.startswith("2026-06-08T14:30:00")


def test_day_first_still_works(monkeypatch):
    """Existing day-first format must not regress."""
    monkeypatch.setattr(calendar_routes, "datetime", _FixedNow)
    result = calendar_routes.parse_due_for_user("today at 3pm")
    assert result.startswith("2026-06-07T15:00:00")


# ── `B1919` · a time phrase that is a long run of whitespace ────────────────
#
# `parse_due_for_user` and `_parse_dt` read every event start and end the
# calendar is given (`EventCreate.dtstart` is any length), every agent event and
# every note's due date. Three of their patterns went back over one whitespace
# run from every place in it, so the time grew with the square of the run, and
# the regex holds the GIL: the time-first form `^(.+?)\s+(today|...)$`, the
# a.m./p.m. normaliser `\b([ap])\s*\.?\s*m\.?\b`, and the time of day's
# `\s*(am|pm)?\s*$`, two whitespace runs side by side. 30,000 tabs took 3 to 30
# seconds a call on the loaded test machine. Upstream Odysseus 3d91ad82
# rewrote the first two (`^(.*\S)`, `(?:\s*\.)?`); the third, which its flood
# never reached, is Pantheon's (`(?:\s*(am|pm))?`). Each reads the same phrases
# as before, and each of the first three floods is slow on one of them alone.

@pytest.mark.parametrize("phrase, expected", [
    ("3pm tomorrow", "2026-06-08T15:00:00"),
    ("9 a.m today", "2026-06-07T09:00:00"),
    ("11pm tonight", "2026-06-07T23:00:00"),
    ("9 p.m tomorrow", "2026-06-08T21:00:00"),
    ("tomorrow at 9 PM", "2026-06-08T21:00:00"),
    ("12:30pm  tomorrow", "2026-06-08T12:30:00"),
    ("12am today", "2026-06-07T00:00:00"),
    ("7 am", "2026-06-07T07:00:00"),
])
def test_a_time_phrase_still_reads_as_it_did(monkeypatch, phrase, expected):
    monkeypatch.setattr(calendar_routes, "datetime", _FixedNow)
    assert calendar_routes.parse_due_for_user(phrase).startswith(expected)
    assert calendar_routes._parse_dt(phrase).isoformat().startswith(expected)


_RUN = "\t" * 30_000
_FLOODS = {
    "ampm-normaliser": "a\n" + _RUN + "x",  # the newline keeps the time-first form linear
    "time-first": "a" + _RUN + "m",          # the normaliser matches at once
    "time-of-day": "1\n" + _RUN + "x",       # no a or p for the normaliser
    "upstream": "a" + _RUN + "x",            # upstream's: the first two at once
}


@pytest.mark.parametrize("parser", ["parse_due_for_user", "_parse_dt"])
@pytest.mark.parametrize("flood", list(_FLOODS.values()), ids=list(_FLOODS))
def test_a_time_phrase_of_whitespace_is_read_in_one_pass(monkeypatch, parser, flood):
    monkeypatch.setattr(calendar_routes, "datetime", _FixedNow)
    started = time.perf_counter()
    try:
        getattr(calendar_routes, parser)(flood)
    except ValueError:
        pass  # it is not a time; how long it took to say so is the point
    assert time.perf_counter() - started < 2.0
