# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1895` — a time in a run's sentence says which clock it is on.

The audit (`clock-words-no-zone`): "Waiting until 08:00", "Did not start: the
07:00 run is still …", "Nobody answered by 09:30 — …", "Kept from the run at
10:42" named no clock. With no zone on the start the time was UTC, and a
person in Sydney read it as their own; with a zone it was that zone's, and a
person anywhere else read it as theirs.

The rule (`workflow_runs._clock`): such a time always says its clock — "UTC"
when the start has no zone (or one this machine does not know), otherwise the
zone's place as the trigger form says it ("Sydney time",
`taskFields.js:_zonePlace`). Always, because the sentence is written once,
mostly by a run nobody watches, and read later by whoever opens it: the
server cannot know when it writes whose zone the reader's will be.

Driven (`Law 20`): the real scheduler running a real Wait over a real SQLite
file (`walker_harness`) and its real restart-free resume; the trigger form's
own `_zonePlace`, cut out of `taskFields.js` and run under node.
"""

import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from src import workflow_runs as wr
from tests.helpers.js_source import js_function
from tests.helpers.walker_harness import (
    arrow, make_db, node, records_of, recording_scheduler, runs_of, seed_workflow, settle,
    skip_ahead,
)

ROOT = Path(__file__).resolve().parent.parent
TASK_FIELDS = ROOT / "static" / "js" / "tasks" / "taskFields.js"
SEVEN = datetime(2026, 11, 7, 7, 0)          # naive UTC, as a row stores it


# ── The rule ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("zone", [None, "", "UTC", "Etc/UTC", "GMT", "Mars/Olympus_Mons"])
def test_with_no_zone_or_one_that_is_utc_the_time_says_utc(zone):
    assert wr._clock(SEVEN, zone) == "07:00 UTC"


@pytest.mark.parametrize("zone,said", [
    ("Australia/Sydney", "18:00 Sydney time"),                       # AEDT, +11
    ("America/Argentina/Buenos_Aires", "04:00 Buenos Aires time"),   # -3
    ("Europe/London", "07:00 London time"),                          # GMT in November
])
def test_with_a_zone_the_time_says_its_place(zone, said):
    assert wr._clock(SEVEN, zone) == said


def test_no_time_is_still_a_question_mark():
    assert wr._clock(None, "Australia/Sydney") == "?"


@pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")
def test_the_place_is_the_one_the_trigger_form_says():
    zones = ["Australia/Sydney", "America/Argentina/Buenos_Aires", "UTC", "Etc/GMT+4",
             "America/New_York", "  Europe/Paris  ", ""]
    body = js_function(TASK_FIELDS.read_text(encoding="utf-8"), "export function _zonePlace")
    script = (f"function _zonePlace(zone) {body}\n"
              f"console.log(JSON.stringify({json.dumps(zones)}.map(_zonePlace)));")
    done = subprocess.run(["node", "--input-type=module", "-e", script],
                          capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == [wr.zone_place(z) for z in zones]


# ── In a run ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def factory(monkeypatch, tmp_path):
    return make_db(monkeypatch, tmp_path / "clock.db")


WAIT_THEN_ACT = (
    [node("w", "Until later", "wait", mode="for", minutes=1),
     node("act", "Tidy", "action", action="tidy_sessions")],
    [arrow("start", "w"), arrow("w", "act")],
)


def _until(factory, run_id):
    rec = {r["node_id"]: r for r in records_of(factory, run_id)}["w"]
    return datetime.fromisoformat(rec["waiting"]["until"].rstrip("Z")).replace(tzinfo=timezone.utc)


def _hhmm(until, zone=None):
    return (until.astimezone(ZoneInfo(zone)) if zone else until).strftime("%H:%M")


@pytest.mark.asyncio
async def test_a_wait_on_a_start_with_no_zone_says_utc_waiting_and_done(factory, monkeypatch):
    seed_workflow(factory, *WAIT_THEN_ACT)
    s = recording_scheduler()
    await s._execute_task("wf")
    [run] = runs_of(factory, "wf")
    assert run["status"] == "waiting", run
    at = f"{_hhmm(_until(factory, run['id']))} UTC"
    assert run["result"] == f"Waiting until {at}", run["result"]
    assert f"Waiting until {at}, or as soon after as Pantheon is idle" in \
        [st.get("detail") for st in run["steps"]], run["steps"]

    skip_ahead(monkeypatch, 61)
    assert await s._resume_due_waits() == 1
    await settle(s)
    [run] = runs_of(factory, "wf")
    assert run["status"] == "success", run
    done = {r["node_id"]: r for r in records_of(factory, run["id"])}["w"]
    assert done["output"]["text"] == f"Waited until {at}."


@pytest.mark.asyncio
async def test_a_wait_on_a_start_in_a_zone_says_the_zones_place(factory):
    seed_workflow(factory, *WAIT_THEN_ACT, tz_name="Australia/Sydney")
    s = recording_scheduler()
    await s._execute_task("wf")
    [run] = runs_of(factory, "wf")
    at = f"{_hhmm(_until(factory, run['id']), 'Australia/Sydney')} Sydney time"
    assert run["result"] == f"Waiting until {at}", run["result"]

    # A second start while it waits is told in the same words (`B674`).
    await s._execute_task("wf")
    first, second = runs_of(factory, "wf")
    assert second["status"] == "skipped", second
    assert re.fullmatch(rf"Did not start: the \d\d:\d\d Sydney time run is still "
                        rf"waiting until {at}\.", second["result"]), second["result"]
