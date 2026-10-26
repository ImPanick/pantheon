# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1040` — a task linked to a crew member, with no zone of its own, is shown
and saved on the crew member's clock, which is the clock it fires on.

**Measured before this file:** `_resolve_task_timezone` is task → crew member →
none (`P8-32`), so a crew-linked 09:00 task with no zone fires at 09:00 on the
crew member's clock. `_task_to_dict` served `crew_member_id` and not that zone,
so the form said "Not set: … kept in UTC", drew the time converted from UTC to
the browser's clock and converted it back on save, and the card drew it on the
browser's clock too: for a person in New York and a crew member in Paris, the
09:00 task read "Daily at 05:00".

Now the row carries `crew_zone` (`followed_crew_zone`: the zone and whose it
is), the card draws the time on that clock, and the form says whose zone it
follows, shows the time as stored and sends it as typed — `tz_name` still as
the person chose it. Driven (`Law 20`): the real `_task_to_dict` and update
route on a real SQLite file, and the real card and form under node, in the
browser's own zone set to New York.
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_one_task_form_in_two_places_js import (  # noqa: E402,F401
    _REQUEST, _case, _endpoint, _served_row, sandbox, task_db,
)


def _crew(task_db, zone="Europe/Paris"):
    from core.database import CrewMember
    db = task_db()
    try:
        if not db.query(CrewMember).filter(CrewMember.id == "c1").first():
            db.add(CrewMember(id="c1", owner=None, name="Ada", timezone=zone))
            db.commit()
    finally:
        db.close()


def test_the_row_says_whose_zone_it_follows(task_db):
    _crew(task_db)
    row = _served_row(task_db, crew_member_id="c1")
    assert row["tz_name"] is None
    assert row["crew_zone"] == {"tz_name": "Europe/Paris", "crew_member": "Ada"}


def test_a_zone_of_its_own_wins_and_is_not_said_as_the_crews(task_db):
    _crew(task_db)
    row = _served_row(task_db, crew_member_id="c1", tz_name="Asia/Tokyo")
    assert row["crew_zone"] is None


def test_a_crew_zone_the_machine_does_not_know_is_not_claimed(task_db):
    """`compute_next_run` falls back to UTC on a zone `zoneinfo` refuses; the
    row does not say the task follows it."""
    _crew(task_db, zone="Mars/Olympus_Mons")
    assert _served_row(task_db, crew_member_id="c1")["crew_zone"] is None


def test_a_crew_linked_nine_oclock_task_reads_nine_on_its_card(sandbox, task_db):
    """The Verify: 09:00 on the card, on the crew member's clock."""
    _crew(task_db)
    row = _served_row(task_db, crew_member_id="c1")
    out = _case(sandbox, {}, """
        process.env.TZ = 'America/New_York';
        console.log(JSON.stringify({ label: __t._scheduleLabel(%s) }));
    """ % json.dumps(row))
    assert out["label"].startswith("Daily at 09:00"), out["label"]
    assert out["label"].endswith("Paris time"), out["label"]


def test_the_form_shows_and_saves_it_on_that_clock(sandbox, task_db, monkeypatch):
    _crew(task_db)
    row = _served_row(task_db, crew_member_id="c1")
    out = _case(sandbox, {"saved": row}, """
        process.env.TZ = 'America/New_York';
        const host = hostIn();
        mountTaskFields(host, { task: %s, tasks: [] });
        await tick();
        const shown = { hour: String(q(host, 'task-form-time-wrap-hour').value),
                        zone: q(host, 'task-form-tz').value,
                        note: q(host, 'task-form-tz-note').textContent };
        click(q(host, 'task-form-save'));
        await tick();
        console.log(JSON.stringify({ shown, writes: writes(), errors: ui.errors }));
    """ % json.dumps(row))
    assert out["errors"] == [], out["errors"]
    assert out["shown"]["hour"] == "9", f"drawn on the browser's clock: {out['shown']}"
    assert out["shown"]["zone"] == ""
    assert "follows Ada’s zone, Europe/Paris" in out["shown"]["note"], out["shown"]
    (write,) = out["writes"]
    body = write["body"]
    assert body["scheduled_time"] == "09:00", "sent converted to UTC from the browser's clock"
    assert body["tz_name"] == "", "the crew's zone was written onto the task"

    # Through the real update route: still 09:00 on Paris's clock.
    import routes.task.task_routes as task_routes
    monkeypatch.setattr(task_routes, "SessionLocal", task_db)
    update = _endpoint("/api/tasks/{task_id}", "PUT")
    saved = json.loads(json.dumps(asyncio.run(
        update(_REQUEST, "t1", task_routes.TaskUpdate(**body)))))
    when = datetime.fromisoformat(saved["next_run"].rstrip("Z")).replace(tzinfo=timezone.utc)
    paris = when.astimezone(ZoneInfo("Europe/Paris"))
    assert (paris.hour, paris.minute) == (9, 0), paris
