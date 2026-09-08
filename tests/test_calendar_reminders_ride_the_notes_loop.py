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
    const fired = [];
    const patched = [];
    let badges = 0;
    let saved = null;
    const _notes = __NOTES__;
    const alreadyFired = new Set(__FIRED__);

    const _loadFiredReminders = () => new Set(alreadyFired);
    const _saveFiredReminders = (s) => { saved = [...s]; };
    const _fireReminder = (note) => { fired.push(note.id); };
    const _patchNote = async (id, patch) => { patched.push([id, patch]); };
    const _updateRailBadge = () => { badges += 1; };
    const _advanceRecurring = () => null;

    __HAS_TIME__

    __CHECK__

    _checkReminders();
    console.log(JSON.stringify({ fired, patched, badges, saved }));
"""


def _check_reminders(notes: list, fired: tuple = ()) -> dict:
    script = (
        _NOTES_HARNESS
        .replace("__NOTES__", json.dumps(notes))
        .replace("__FIRED__", json.dumps(list(fired)))
        .replace("__HAS_TIME__", _function(_NOTES, "_hasTimeComponent"))
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


def test_a_reminder_missed_by_more_than_a_minute_is_retired_silently():
    # The delta the deleted module carried: it allowed a five-minute catch-up,
    # the live loop allows one minute and then marks the note fired without a
    # notification. Pinned here so the difference is a decision, not a drift —
    # see P3-26, which asks whether the window should widen.
    note = _calendar_reminder_note()
    note["due_date"] = _shift_iso(note["due_date"], -5 * 60)
    out = _check_reminders([note])
    assert out["fired"] == []
    assert out["saved"] == ["cal-1"], "a missed reminder must still be retired, not re-checked forever"


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
