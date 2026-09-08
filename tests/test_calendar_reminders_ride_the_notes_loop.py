# SPDX-License-Identifier: AGPL-3.0-or-later
r"""The calendar has no notification poller of its own — and must not need one.

`static/js/calendar/reminders.js` polled `/api/notes?label=calendar` on a 60s
timer and fired its own `Notification`. Nothing imported it, and the reason is
recorded in the module it was meant to serve::

    // Calendar reminders are stored as Notes. The Notes reminder loop owns
    // notification dispatch so calendar reminders do not fire twice.
    -- static/js/calendar.js

`P3-10` deleted it. That deletion is only safe while two separate facts hold,
in two separate files, neither of which mentions the other:

  1. `notes.js` boots its reminder loop against **every** note — an unfiltered
     `GET /api/notes`. Narrow that to a label slice and calendar reminders stop
     being seen at all.
  2. The note `calendar.js` writes for a reminder clears every gate
     `_checkReminders` applies: unarchived, a `due_date` carrying a time
     component, not already fired.

So this file does not read either function and assert on its text — that would
test the file, not the code. It lifts the production function bodies out
verbatim, runs them under `node` against stubs, and feeds the note the calendar
*actually builds* into the loop that *actually dispatches*. Break either half
and a reminder set on a calendar event silently never arrives.
"""

import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_CALENDAR = _REPO / "static" / "js" / "calendar.js"
_NOTES = _REPO / "static" / "js" / "notes.js"
_SW = _REPO / "static" / "sw.js"
_HAS_NODE = shutil.which("node") is not None


def _constant(src: Path, name: str) -> str:
    """The whole `const NAME = ...;` line, ready to paste into a module.

    Lifted rather than re-declared: a harness that writes its own twelve hours
    would keep passing on the day the real one changes, which is the whole
    failure mode `P3-26` was filed about.
    """
    text = src.read_text(encoding="utf-8")
    match = re.search(rf"\nconst\s+{re.escape(name)}\s*=.*?;", text, re.S)
    assert match, f"{name} not found in {src.name}"
    return match.group(0).strip()


def _function(src: Path, name: str) -> str:
    """The whole declaration of `name`, ready to paste into a module."""
    text = src.read_text(encoding="utf-8")
    match = re.search(
        rf"\n((?:export\s+)?(?:async\s+)?function\s+{re.escape(name)}\s*\([^)]*\)\s*\{{)",
        text,
    )
    assert match, f"{name} not found in {src.name}"
    start = match.start(1)
    i = match.end(1)
    depth = 1
    while i < len(text) and depth:
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
        i += 1
    assert depth == 0, f"{name} body did not close"
    # `export` is meaningless once pasted into a harness that calls it directly.
    return re.sub(r"^export\s+", "", text[start:i])


def _run(script: str) -> dict:
    proc = subprocess.run(
        ["node", "--input-type=module"],
        input=textwrap.dedent(script),
        capture_output=True,
        text=True,
        cwd=str(_REPO),
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert lines, f"node produced no stdout\n{proc.stderr}"
    return json.loads(lines[-1])


# ── half one: what the calendar writes ────────────────────────────────────────

_CALENDAR_HARNESS = """
    let posted = null;
    const fetch = async (url, opts) => {
      if (String(url).includes('/api/notes') && opts && opts.method === 'POST') {
        posted = { url: String(url), body: JSON.parse(opts.body) };
      }
      return { ok: true, json: async () => ({ id: 'n1' }) };
    };
    const uiModule = { showToast() {}, showError() {} };
    const window = { notesModule: { refreshDueBadge() {} } };

    __CREATE__

    const ev = {
      summary: 'Standup',
      location: 'Room 3',
      all_day: false,
      dtstart: new Date(Date.now() + 5 * 60000).toISOString(),
    };
    await _createEventReminder(ev, new Date(Date.now() - 10000));
    console.log(JSON.stringify(posted));
"""


def _calendar_reminder_note() -> dict:
    """The note body `_createEventReminder` puts on the wire, verbatim."""
    posted = _run(_CALENDAR_HARNESS.replace("__CREATE__", _function(_CALENDAR, "_createEventReminder")))
    assert posted, "the calendar did not POST a note"
    note = posted["body"]
    note["id"] = "cal-1"
    return note


# ── half two: what the notes loop dispatches ──────────────────────────────────

_NOTES_HARNESS = """
    // A pinned clock, when the test asks for one. `Date.now()` is what
    // `_checkReminders` reads, so the boundary cases have to reach it through
    // `Date` itself rather than through a note whose offset is already stale by
    // the time node starts. `globalThis.Date` and not `Date`: the class below
    // shadows the binding for the whole module, so naming it bare here is a TDZ
    // error rather than the global.
    const _RealDate = globalThis.Date;
    const _PINNED = __NOW__;
    class Date extends _RealDate {
      static now() { return _PINNED === null ? _RealDate.now() : _PINNED; }
    }

    const fired = [];
    const late = [];
    const patched = [];
    let badges = 0;
    let saved = null;
    const _notes = __NOTES__;
    const alreadyFired = new Set(__FIRED__);

    const _loadFiredReminders = () => new Set(alreadyFired);
    const _saveFiredReminders = (s) => { saved = [...s]; };
    const _fireReminder = (note, lateness) => { fired.push(note.id); late.push(lateness || ''); };
    const _patchNote = async (id, patch) => { patched.push([id, patch]); };
    const _updateRailBadge = () => { badges += 1; };
    const _advanceRecurring = () => null;

    __HAS_TIME__

    __LOOKBACK__

    __LATENESS__

    __CHECK__

    _checkReminders();
    console.log(JSON.stringify({ fired, late, patched, badges, saved }));
"""


_LATENESS_HARNESS = """
    __LATENESS__
    const ms = __MS__;
    const now = 1_700_000_000_000;
    console.log(JSON.stringify(_reminderLateness(now - ms, now)));
"""


def _lateness(ms_late) -> str:
    """`_reminderLateness` itself, with the clock held still."""
    script = (
        _LATENESS_HARNESS
        .replace("__LATENESS__", _function(_NOTES, "_reminderLateness"))
        # `json.dumps` would write bare NaN, which JSON.parse rejects but JS reads fine.
        .replace("__MS__", "NaN" if ms_late != ms_late else repr(ms_late))
    )
    return _run(script)


def _check_reminders(notes: list, fired: tuple = (), now: int | None = None) -> dict:
    script = (
        _NOTES_HARNESS
        .replace("__NOW__", "null" if now is None else repr(now))
        .replace("__NOTES__", json.dumps(notes))
        .replace("__FIRED__", json.dumps(list(fired)))
        .replace("__HAS_TIME__", _function(_NOTES, "_hasTimeComponent"))
        .replace("__LOOKBACK__", _constant(_NOTES, "REMINDER_LOOKBACK_MS"))
        .replace("__LATENESS__", _function(_NOTES, "_reminderLateness"))
        .replace("__CHECK__", _function(_NOTES, "_checkReminders"))
    )
    return _run(script)


pytestmark = pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")


def test_a_calendar_reminder_is_dispatched_by_the_notes_loop():
    # The whole justification for deleting calendar/reminders.js, executed:
    # the calendar builds a note, the notes loop fires it. Neither file names
    # the other, so nothing but this test holds the two ends together.
    note = _calendar_reminder_note()
    assert note["label"] == "calendar", "the reminder note stopped being a calendar note"
    assert _check_reminders([note])["fired"] == ["cal-1"]


def test_the_loop_does_not_care_which_label_a_note_carries():
    # If dispatch were ever gated on a label, the calendar would need its own
    # poller back. Same note, no label at all — still fires.
    note = _calendar_reminder_note()
    note.pop("label", None)
    note["id"] = "unlabelled"
    assert _check_reminders([note])["fired"] == ["unlabelled"]


@pytest.mark.parametrize(
    "mutate, why",
    [
        (lambda n: n.update(archived=True), "archived notes must stay quiet"),
        (lambda n: n.update(due_date=n["due_date"][:10]), "a date with no time is not a reminder"),
        (lambda n: n.update(due_date=None), "a note with no due date is not a reminder"),
    ],
)
def test_notes_that_should_stay_quiet_do(mutate, why):
    # Negative controls: without these, the positive test above would pass on a
    # `_checkReminders` that fired for literally everything.
    note = _calendar_reminder_note()
    mutate(note)
    out = _check_reminders([note])
    assert out["fired"] == [], why
    # And it must not be *consumed* either. A note the loop skips is a note it
    # never had a reminder for; if skipping still added it to the fired set, a
    # user who later put a time on that same note would find it pre-retired and
    # would never be told. So the fired set is left untouched, not just quiet.
    assert out["saved"] is None, f"{why} — and must not be retired on the way past"


def test_a_reminder_already_fired_does_not_fire_twice():
    note = _calendar_reminder_note()
    assert _check_reminders([note], fired=("cal-1",))["fired"] == []


def test_a_reminder_missed_while_you_were_away_is_still_delivered():
    # `P3-26`, decided 2026-09-08. This used to assert the opposite — a
    # reminder five minutes late was retired without a notification, and the
    # sixty-second window that did it was never chosen: `calendar/reminders.js`
    # allowed five minutes and said why, `P3-10` deleted that module, and the
    # narrower number survived by accident.
    note = _calendar_reminder_note()
    note["due_date"] = _shift_iso(note["due_date"], -5 * 60)
    out = _check_reminders([note])
    assert out["fired"] == ["cal-1"]
    assert out["late"] == ["was due 5 minutes ago"], (
        "a late reminder that does not say it is late is the reason the window "
        "had to stay narrow"
    )


def test_a_reminder_hours_late_still_arrives_and_says_how_late():
    # The case the row was really about: due at 3pm, laptop shut at 2:55,
    # opened at 8pm. Twelve hours is only a safe window because the
    # notification states its own age.
    note = _calendar_reminder_note()
    note["due_date"] = _shift_iso(note["due_date"], -5 * 60 * 60)
    out = _check_reminders([note])
    assert out["fired"] == ["cal-1"]
    assert out["late"] == ["was due 5 hours ago"]


def test_a_reminder_on_time_says_nothing_about_lateness():
    # The overwhelming majority. A reminder that fires within the minute is not
    # late and must not be dressed as though it were.
    out = _check_reminders([_calendar_reminder_note()])
    assert out["fired"] == ["cal-1"]
    assert out["late"] == [""]


def test_a_reminder_older_than_the_window_is_still_retired_silently():
    # The one thing both positions always agreed on: a browser opened after a
    # fortnight must not deliver a fortnight of reminders at once.
    note = _calendar_reminder_note()
    note["due_date"] = _shift_iso(note["due_date"], -13 * 60 * 60)
    out = _check_reminders([note])
    assert out["fired"] == []
    assert out["saved"] == ["cal-1"], "a missed reminder must still be retired, not re-checked forever"


_EPOCH = 1_700_000_000_000  # a fixed Tuesday; only its stillness matters
_TWELVE_HOURS = 12 * 60 * 60 * 1000


def _note_due_at(ms: int) -> dict:
    """A minimal reminder note due at an exact millisecond."""
    from datetime import datetime, timezone

    when = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    return {"id": "pinned", "title": "Pinned", "due_date": when.isoformat().replace("+00:00", "Z")}


def test_the_far_edge_of_the_window_belongs_to_silence():
    # Exactly twelve hours old, to the millisecond. `due > cutoff` fires and
    # `due <= cutoff` retires, so the boundary itself has to fall on one side
    # by decision rather than by whichever comparison was typed first: at the
    # stated width the answer is "older than the window", and older is silent.
    note = _note_due_at(_EPOCH - _TWELVE_HOURS)
    out = _check_reminders([note], now=_EPOCH)
    assert out["fired"] == []
    assert out["saved"] == ["pinned"]


def test_one_millisecond_inside_the_window_still_arrives():
    # The other side of the same millisecond. Without this the test above
    # passes on a loop that retires everything.
    note = _note_due_at(_EPOCH - _TWELVE_HOURS + 1)
    out = _check_reminders([note], now=_EPOCH)
    assert out["fired"] == ["pinned"]
    assert out["late"] == ["was due 11h 59m ago"]


def test_no_past_due_note_is_left_in_the_gap_between_the_two_branches():
    # The reason `cutoff` is computed once. Two subtractions can disagree, and
    # if the retire branch is the wider of the two there is a band of notes
    # that neither fires nor retires — re-read every thirty seconds, forever,
    # never shown and never consumed. Sampled across three decades of lateness.
    for hours in (0, 1, 11, 12, 13, 100, 24 * 365):
        note = _note_due_at(_EPOCH - hours * 60 * 60 * 1000)
        out = _check_reminders([note], now=_EPOCH)
        handled = bool(out["fired"]) or bool(out["saved"])
        assert handled, f"a note {hours}h past due was neither delivered nor retired"


def test_the_window_is_twelve_hours_and_says_so():
    # The row's `Verify:` — a named constant with a sentence saying which way
    # it was chosen, so the next reader finds a decision and not a magic number.
    text = _NOTES.read_text(encoding="utf-8")
    assert "const REMINDER_LOOKBACK_MS = 12 * 60 * 60 * 1000;" in text
    assert "decided by the owner" in text


@pytest.mark.parametrize("ms_late, expected", [
    (0, ""),
    (59_000, ""),
    (60_000, "was due 1 minute ago"),
    # 90s is 1.5 minutes: floor says one, round says two. A reminder must never
    # claim to be later than it is.
    (90_000, "was due 1 minute ago"),
    (120_000, "was due 2 minutes ago"),
    (119_000, "was due 1 minute ago"),
    (59 * 60_000, "was due 59 minutes ago"),
    (60 * 60_000, "was due 1 hour ago"),
    (2 * 60 * 60_000, "was due 2 hours ago"),
    (90 * 60_000, "was due 1h 30m ago"),
    (float("nan"), ""),
])
def test_how_late_is_said_in_words_a_person_reads(ms_late, expected):
    # Exact milliseconds, straight into the function. Driving the boundaries
    # through a note instead means the note's own ten-second offset and the
    # test's own runtime both land on the answer — the 59-second case failed
    # that way first, and a boundary test that drifts is not testing a boundary.
    assert _lateness(ms_late) == expected


# ── half three: what the notification actually says ───────────────────────────

_FIRE_HARNESS = """
    let posted = null;
    const toasts = [];
    const notified = [];
    const glowed = [];

    // The 1500ms fallback timer exists so a slow server still produces a
    // notification. Stubbed to a no-op: this harness is about what the title
    // says, and a live timer would only make node sit for a second and a half.
    const setTimeout = () => 0;
    const clearTimeout = () => {};

    const fetch = async (url, opts) => {
      posted = { url: String(url), body: JSON.parse(opts.body) };
      return { ok: true, json: async () => ({}) };
    };
    const uiModule = { showToast: (msg) => toasts.push(msg) };
    class Notification {
      static permission = 'granted';
      constructor(title, opts) { notified.push({ title, body: opts.body }); }
      close() {}
    }
    const window = { Notification, focus() {} };
    const document = { querySelector: () => null };
    const openPanel = () => {};
    const _setReminderCardGlow = (id, on) => { glowed.push([id, on]); };
    const _queuePendingHighlight = () => {};
    const _hasItems = (note) => Array.isArray(note.items) && note.items.length > 0;

    __FIRE__

    _fireReminder(__NOTE__, __LATENESS__);
    // Let the resolved fetch drain so the local notification is observed too;
    // the toast and the browser notification are the two things a person sees.
    await new Promise(r => setImmediate(r));
    console.log(JSON.stringify({ posted, toasts, notified, glowed }));
"""


def _fire(note: dict, lateness: str) -> dict:
    """`_fireReminder` itself — what reaches the wire and the screen."""
    script = (
        _FIRE_HARNESS
        .replace("__FIRE__", _function(_NOTES, "_fireReminder"))
        .replace("__NOTE__", json.dumps(note))
        .replace("__LATENESS__", json.dumps(lateness))
    )
    return _run(script)


def test_the_age_is_on_the_title_where_it_gets_read():
    # `P3-26`'s visible half, and the only part of it a person ever sees. The
    # loop can compute the age perfectly and hand it over correctly and the row
    # is still not done if the notification does not say it.
    out = _fire({"id": "n1", "title": "Take the pasta off", "content": "now"}, "was due 8 minutes ago")
    assert out["posted"]["body"]["title"] == "Take the pasta off — was due 8 minutes ago"
    assert out["notified"][0]["title"] == "Take the pasta off — was due 8 minutes ago"
    assert out["toasts"] == ["Take the pasta off — was due 8 minutes ago"]


def test_an_on_time_reminder_keeps_its_own_title_exactly():
    # No separator, no trailing punctuation, nothing appended. The overwhelming
    # majority of reminders are on time and must look untouched.
    out = _fire({"id": "n1", "title": "Standup", "content": "room 3"}, "")
    assert out["posted"]["body"]["title"] == "Standup"
    assert out["notified"][0]["title"] == "Standup"


def test_the_age_does_not_leak_into_the_body():
    # The body is the note's own content. If the age were appended there too it
    # would be said twice, and the body is what a browser notification truncates
    # first — which is the whole reason the age rides the title.
    out = _fire({"id": "n1", "title": "Standup", "content": "room 3"}, "was due 2 hours ago")
    assert out["posted"]["body"]["body"] == "room 3"
    assert "was due" not in out["notified"][0]["body"]


def test_an_untitled_note_still_says_how_late_it_is():
    # `note.title || 'Note reminder'` is the fallback, and the age has to attach
    # to the fallback too — a note with no title is exactly the one whose
    # timing a reader cannot infer from anything else.
    out = _fire({"id": "n1", "title": "", "content": "milk"}, "was due 3h 5m ago")
    assert out["posted"]["body"]["title"] == "Note reminder — was due 3h 5m ago"


def _shift_iso(iso: str, seconds: int) -> str:
    from datetime import datetime, timedelta, timezone

    when = datetime.fromisoformat(iso.replace("Z", "+00:00")) + timedelta(seconds=seconds)
    return when.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


# ── the offline manifest, after a module leaves the tree ──────────────────────


def _precache_entries() -> list:
    text = _SW.read_text(encoding="utf-8")
    entries = []
    for block in ("PRECACHE", "PANEL_PRECACHE"):
        match = re.search(rf"\nconst {block} = \[", text)
        assert match, f"{block} not found in sw.js"
        i = match.end()
        depth = 1
        while i < len(text) and depth:
            if text[i] == "[":
                depth += 1
            elif text[i] == "]":
                depth -= 1
            i += 1
        entries += re.findall(r"'(/static/[^']+)'", text[match.end() : i - 1])
    return entries


def test_the_offline_manifest_only_names_files_that_exist():
    # A precached URL that 404s makes `cache.addAll` reject, and the whole
    # install fails — every entry, not just the missing one. Deleting a module
    # without editing this list is therefore not a tidiness problem; it takes
    # the app offline-capability down entirely.
    entries = _precache_entries()
    assert len(entries) > 50, "the precache list came back suspiciously short — parser drift?"
    # Entries carry cache-busting query strings; the file on disk does not.
    missing = [e for e in entries if not (_REPO / e.split("?")[0].lstrip("/")).is_file()]
    assert missing == [], f"precached but not in the tree: {missing}"


_IMPORT = re.compile(r"""(?:import|export)[^'"]*?from\s*['"](\.[^'"]+)['"]|import\(\s*['"](\.[^'"]+)['"]""")


def test_no_module_imports_a_file_that_is_not_there():
    # The other half of a deletion going wrong: a live importer left pointing
    # at a module that no longer exists. The browser fails the whole graph.
    dangling = []
    for js in sorted((_REPO / "static").rglob("*.js")):
        if "/lib/" in js.as_posix():
            continue
        for static_spec, dynamic_spec in _IMPORT.findall(js.read_text(encoding="utf-8")):
            spec = static_spec or dynamic_spec
            target = (js.parent / spec.split("?")[0]).resolve()
            if not target.is_file():
                dangling.append(f"{js.relative_to(_REPO)} -> {spec}")
    assert dangling == [], f"imports with no file behind them: {dangling}"
