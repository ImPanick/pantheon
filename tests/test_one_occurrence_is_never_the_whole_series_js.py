# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1906`. "This event only" on a new repeating event deleted the whole series.

After the Calendar creates a series, or an edit gives a single event a repeat
rule, its pool holds the series under its own uid until the next full fetch.
Deleting that row offers the choice "This event only" (the focused default)
or "All recurring events". `_deleteEvent` in `static/js/calendar.js` sent the
occurrence scope only for a uid with an occurrence suffix (`{series}::{start}`),
so for the series row it sent a plain `DELETE` with no scope: the server
deleted the series and every occurrence, pushed that to CalDAV, and the page
stripped every row of it. Nothing undoes a delete.

Now "This event only" always sends the occurrence scope. For a series row it
sends the series' first occurrence, keyed the way the server keys it
(`_expand_rrule`): the date for an all-day series, and for a timed one the
start in UTC when it carries an offset (the server stored it as UTC), or the
wall time for a floating one. Only that occurrence's rows leave the page. A row
with no start to key is not deleted, and the person is told. "All recurring
events" is unchanged. The server half is
`tests/test_one_occurrence_is_never_the_whole_series.py`.

Ported from upstream Odysseus 84aa9a91, which always sends the scope. It also
keys the series row, which upstream leaves to the server's refusal.
Driven under node, in Tokyo: the shipped `_optimisticEvent`, `_findEventByUid`
and `_deleteEvent`, cut out of calendar.js with
`tests/helpers/js_source.js_function`, with `calendar/utils.js` imported.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.helpers.js_source import js_function

ROOT = Path(__file__).resolve().parents[1]
CALENDAR_JS = ROOT / "static" / "js" / "calendar.js"
UTILS_JS = (ROOT / "static" / "js" / "calendar" / "utils.js").as_posix()

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

# The rows the server sends for a weekly series: occurrence uids, UTC starts.
LATER = {"uid": "S1::2026-06-17T05:00", "summary": "Standup", "dtstart": "2026-06-17T05:00:00Z",
         "dtend": "2026-06-17T06:00:00Z", "all_day": False, "rrule": "FREQ=WEEKLY",
         "is_recurrence": True, "series_uid": "S1"}


def _delete(seed, uid, scope):
    """Seed the pool, delete `uid` with `scope`, and say what happened.

    `seed` is a list of `["create", data]` (the row `_createEvent` leaves, made
    by the shipped `_optimisticEvent`) or `["server", row]` entries.
    """
    src = CALENDAR_JS.read_text(encoding="utf-8")
    fns = "\n".join(
        "%s %s" % (head, js_function(src, sig))
        for head, sig in (
            ("function _optimisticEvent(data, uid)", "function _optimisticEvent("),
            ("function _findEventByUid(uid)", "function _findEventByUid("),
            ("async function _deleteEvent(uid, { scope = 'series' } = {})", "async function _deleteEvent("),
        )
    )
    script = """
import * as utils from '%(utils)s';
Object.assign(globalThis, utils);
const API_BASE = '';
const LS_KEY = 'cal-cache';
const _calendars = [{ href: 'local', name: 'Personal', color: '#5b8abf' }];
let _allEvents = {};
let _events = [];
let _fetchedRanges = [['2026-06-01', '2026-07-13']];
let _open = true;
const calls = [], errors = [];
const _render = () => {};
const _updateBadge = () => {};
const _saveCache = () => {};
globalThis.localStorage = { removeItem() {} };
globalThis.window = { uiModule: { showError: (m) => errors.push(m) } };
globalThis.fetch = async (url, opts) => {
  calls.push((opts && opts.method || 'GET') + ' ' + url);
  return { ok: true, status: 200, json: async () => ({ ok: true }) };
};
%(fns)s
for (const [kind, data] of %(seed)s) {
  const row = kind === 'create' ? _optimisticEvent(data, data.uid) : data;
  _allEvents[row.uid] = row;
  _events.push(row);
}
const result = await _deleteEvent(%(uid)s, { scope: %(scope)s });
await new Promise((r) => setTimeout(r, 20));
console.log(JSON.stringify({ result, calls, errors, left: Object.keys(_allEvents).sort(),
                             shown: _events.map((e) => e.uid).sort(), ranges: _fetchedRanges.length }));
""" % {"utils": UTILS_JS, "fns": fns, "seed": json.dumps(seed),
       "uid": json.dumps(uid), "scope": json.dumps(scope)}
    done = subprocess.run(["node", "--input-type=module", "-e", script], cwd=str(ROOT),
                          capture_output=True, text=True, timeout=30,
                          env={**os.environ, "TZ": "Asia/Tokyo"})
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


def _created(uid, dtstart, dtend, **extra):
    return ["create", {"uid": uid, "summary": "Standup", "dtstart": dtstart, "dtend": dtend,
                       "rrule": "FREQ=WEEKLY", "calendar_href": "local", **extra}]


def test_this_event_only_on_a_new_series_deletes_its_first_occurrence():
    seed = [_created("S1", "2026-06-10T14:00:00+09:00", "2026-06-10T15:00:00+09:00"), ["server", LATER]]
    out = _delete(seed, "S1", "occurrence")

    # 14:00 in Tokyo is stored as 05:00 UTC, and that is the server's key.
    assert out["calls"] == ["DELETE /api/calendar/events/S1%3A%3A2026-06-10T05%3A00?scope=occurrence"]
    assert out["left"] == ["S1::2026-06-17T05:00"]
    assert out["shown"] == ["S1::2026-06-17T05:00"]
    assert out["errors"] == []
    assert out["ranges"] == 0      # the page fetches the series again

    # The row of that same occurrence, if the page holds it, goes with it.
    twin = dict(LATER, uid="S1::2026-06-10T05:00", dtstart="2026-06-10T05:00:00Z",
                dtend="2026-06-10T06:00:00Z")
    out = _delete(seed + [["server", twin]], "S1", "occurrence")
    assert out["left"] == ["S1::2026-06-17T05:00"]


def test_this_event_only_keys_an_all_day_and_a_floating_series_as_the_server_does():
    all_day = _delete([_created("S2", "2026-06-12", "2026-06-13", all_day=True)], "S2", "occurrence")
    assert all_day["calls"] == ["DELETE /api/calendar/events/S2%3A%3A2026-06-12?scope=occurrence"]
    floating = _delete([["server", {"uid": "S3", "summary": "Gym", "dtstart": "2026-06-10T09:30:00",
                                    "dtend": "2026-06-10T10:30:00", "all_day": False,
                                    "rrule": "FREQ=DAILY"}]], "S3", "occurrence")
    assert floating["calls"] == ["DELETE /api/calendar/events/S3%3A%3A2026-06-10T09%3A30?scope=occurrence"]

    # An occurrence the server sent, and "All recurring events", go out as before.
    one = _delete([["server", LATER]], LATER["uid"], "occurrence")
    assert one["calls"] == ["DELETE /api/calendar/events/S1%3A%3A2026-06-17T05%3A00?scope=occurrence"]
    assert one["left"] == []
    seed = [_created("S1", "2026-06-10T14:00:00+09:00", "2026-06-10T15:00:00+09:00"), ["server", LATER]]
    series = _delete(seed, "S1", "series")
    assert series["calls"] == ["DELETE /api/calendar/events/S1"]
    assert series["left"] == [] and series["shown"] == []


def test_a_series_row_with_no_start_to_key_is_not_deleted():
    out = _delete([_created("S4", "", "")], "S4", "occurrence")
    assert out["calls"] == []
    assert out["left"] == ["S4"]
    assert out["errors"] and "occurrence" in out["errors"][0]
