# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1867` — a new workflow's start takes the person's time zone.

A start's `tz_name` is the clock "daily at 09:00" and a Wait "until 08:00"
are read on. A draft from the person's words already took the browser's zone
(`describe`, `tz`); an empty workflow did not, so its start had no zone and
ran on UTC — hours from the person's 09:00, with nothing saying so.

`POST /api/workflows` now takes an optional `tz`: an empty workflow's start
takes it, and so does a file's start that names no zone of its own. A zone
this machine does not know is left out, never refused. Driven through the
real route, the real store and a real SQLite file (`Law 20`).
"""

import pytest

from tests.helpers.walker_harness import app_for, client_for, make_db, recording_scheduler

pytestmark = pytest.mark.asyncio

FILE = {"pantheon_workflow": 1, "name": "Morning note",
        "trigger": {"trigger_type": "schedule", "schedule": "daily", "scheduled_time": "08:00"},
        "graph": {"v": 1, "nodes": [{"id": "n1", "kind": "llm", "label": "Say hello",
                                     "config": {"prompt": "Say hello."}}], "edges": []},
        "requires": {}}


@pytest.fixture()
def app(monkeypatch, tmp_path):
    factory = make_db(monkeypatch, tmp_path / "tz.db")
    return app_for(factory, recording_scheduler(), monkeypatch)


async def _create(app, body):
    async with client_for(app) as client:
        res = await client.post("/api/workflows", headers={"x-test-user": "alice"}, json=body)
    assert res.status_code == 200, res.text
    return res.json()["workflow"]["trigger_task"]


async def test_an_empty_workflow_starts_in_the_zone_the_browser_named(app):
    start = await _create(app, {"tz": "Europe/Paris"})
    assert start["tz_name"] == "Europe/Paris"
    assert (start["schedule"], start["scheduled_time"]) == ("daily", "09:00")


@pytest.mark.parametrize("tz", ["Mars/Olympus_Mons", "", "   ", 42, None, "x" * 200])
async def test_a_zone_this_machine_does_not_know_is_left_out_not_refused(app, tz):
    start = await _create(app, {"name": "Unknown zone", "tz": tz})
    assert start["tz_name"] is None


async def test_with_no_zone_sent_the_start_is_as_it_always_was(app):
    assert (await _create(app, {}))["tz_name"] is None


async def test_a_file_that_names_no_zone_takes_the_persons(app):
    start = await _create(app, {"file": FILE, "tz": "Asia/Tokyo"})
    assert start["tz_name"] == "Asia/Tokyo"
    assert start["scheduled_time"] == "08:00"


async def test_a_file_that_names_its_zone_keeps_it(app):
    own = dict(FILE, trigger=dict(FILE["trigger"], tz_name="Europe/London"))
    start = await _create(app, {"file": own, "tz": "Asia/Tokyo"})
    assert start["tz_name"] == "Europe/London"
