# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1937`. An event link from the chat opened the calendar on today, not on the event's day.

`openCalendarTo` is what a chat link to an event (`[Dentist](#event-<uid>)`,
written by the agent's calendar tool) and a mail's calendar button open. It
stored the day to select as a `Date`, where every other writer of
`_selectedDay` stores a `'YYYY-MM-DD'` string and every reader compares one.
So no day was marked selected, the day panel found no events, and the empty
day's slot (`B730`) passed the `Date` through the HTML escaper, which threw:
the month never drew, the calendar stayed on today, and every later redraw
threw again until the person clicked a day. A `search:` target drew, with a
header reading "Invalid Date".

Now the day is stored as its string. It is built from the event's own day
(`_localDateOf`: a date as it is, a Z or offset timestamp as the local day, a
naive one cut), and a date-only target is read as that local day, as the year
view's day click does. Upstream Odysseus fixed the type in 84aa9a91 with
`_ds(new Date(ev.dtstart))`; that is not what this does, because
`new Date('2026-12-01')` is midnight UTC, the evening before west of UTC, so
an all-day event on the 1st opened on the last day of the month before.

Driven (`Law 20`): `openCalendarTo` and the day panel are cut out of
`static/js/calendar.js` with `tests/helpers/js_source` and run under node
beside the real `calendar/utils.js` and the real escaper, in three time zones;
the redraw is a stand-in that draws the day panel as `_renderMonth` does.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.helpers.js_source import js_binding, js_code, js_definition

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"
CAL = (JS / "calendar.js").read_text(encoding="utf-8")
CALCODE = js_code(CAL)

ZONES = ["America/New_York", "UTC", "Asia/Tokyo"]


def _cal(*signatures: str) -> str:
    return "\n".join(js_definition(CAL, CALCODE.index(sig)) + ";" for sig in signatures)


_HARNESS = f"""
import {{ _ds, _localDateOf }} from {json.dumps((JS / "calendar" / "utils.js").as_uri())};
import {{ esc }} from {json.dumps((JS / "util" / "escapeHtml.js").as_uri())};
""" + r"""
const uiModule = { esc };
let _selectedDay = null, _currentDate = new Date(), _view = 'month', _searchQuery = '';
let _allEvents = {}, _events = [];
const _moreIcon = '...';
const _eventVisible = () => true, _calItemBgStyle = () => '', _calColor = () => '#888', _locHTML = (s) => s;
const _fmtTime = (s) => String(s).slice(11, 16);
function openCalendar() {}
async function _fetchCalendars() {}
async function _fetchEvents() {}
// The redraw, as `_renderMonth` treats the selected day: the grid marks the
// cell whose date string is `_selectedDay`, and the day panel is drawn for it.
let drawn = null;
function _render() {
  const panel = _selectedDay ? _dayDetailHTML(_selectedDay) : '';
  drawn = { panel, month: _currentDate.getFullYear() + '-' + String(_currentDate.getMonth() + 1).padStart(2, '0') };
}
const EVENTS = [
  { uid: 'ev-dentist', summary: 'Dentist', dtstart: '2026-11-12T09:00:00', dtend: '2026-11-12T10:00:00', all_day: false },
  { uid: 'ev-holiday', summary: 'Holiday', dtstart: '2026-12-01', dtend: '2026-12-02', all_day: true },
];
async function open(target) {
  _selectedDay = 'as before'; drawn = null; _searchQuery = '';
  _allEvents = Object.fromEntries(EVENTS.map((e) => [e.uid, e])); _events = EVENTS;
  await openCalendarTo(target);
  const header = drawn && (drawn.panel.match(/<div class="cal-detail-header">\s*<span>([^<]*)/) || [])[1];
  return {
    selected: _selectedDay instanceof Date ? 'a Date' : _selectedDay,
    drawn: !!drawn, header: header || null, month: drawn && drawn.month,
    lists: drawn ? EVENTS.filter((e) => drawn.panel.includes(e.summary)).map((e) => e.summary) : [],
    today: _today(),
  };
}
"""

_FUNCTIONS = _cal("function _today(", "function _e(", "function _fmtDate(", "function _eventsForDay(",
                  "function _dayDetailHTML(", "async function openCalendarTo(") + "\n" + js_binding(
                      CAL, "_highlightEventUid") + ";"


def run(tmp_path, tz: str, target: str) -> dict:
    case = tmp_path / "case.mjs"
    case.write_text(_HARNESS + _FUNCTIONS + "\n"
                    f"console.log(JSON.stringify(await open({json.dumps(target)})));\n",
                    encoding="utf-8")
    proc = subprocess.run(["node", str(case)], cwd=tmp_path, capture_output=True, text=True,
                          timeout=30, env={**os.environ, "TZ": tz})
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("tz", ZONES)
def test_a_timed_events_link_opens_on_its_day_and_lists_it(tmp_path, tz):
    out = run(tmp_path, tz, "ev-dentist")
    assert out["selected"] == "2026-11-12"
    assert out["drawn"], "the day panel threw and the calendar stayed where it was"
    assert out["month"] == "2026-11" and out["lists"] == ["Dentist"]


@pytest.mark.parametrize("tz", ZONES)
def test_an_all_day_event_on_the_first_opens_on_the_first(tmp_path, tz):
    """West of UTC, `new Date('2026-12-01')` is the evening of 30 November."""
    out = run(tmp_path, tz, "ev-holiday")
    assert out["selected"] == "2026-12-01"
    assert out["drawn"] and out["month"] == "2026-12" and out["lists"] == ["Holiday"]


@pytest.mark.parametrize("tz", ZONES)
def test_a_date_opens_on_that_date(tmp_path, tz):
    out = run(tmp_path, tz, "2026-11-07")
    assert out["selected"] == "2026-11-07"
    assert out["drawn"] and out["month"] == "2026-11" and out["lists"] == []


@pytest.mark.parametrize("tz", ZONES)
def test_a_search_opens_on_today_under_a_real_date(tmp_path, tz):
    out = run(tmp_path, tz, "search:dentist")
    assert out["selected"] == out["today"]
    assert out["drawn"] and out["header"] and "Invalid Date" not in out["header"]
    assert out["lists"] == ["Dentist"]


def test_an_unknown_event_leaves_the_calendar_where_it_was(tmp_path):
    out = run(tmp_path, "America/New_York", "ev-nope")
    assert out["selected"] == "as before" and out["drawn"] is False
