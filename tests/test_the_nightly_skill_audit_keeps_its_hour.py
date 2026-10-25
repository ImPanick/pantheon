# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1462` — the nightly skill audit runs at the hour the panel says, midnight included.

The 2026-10-25 settings audit: `app.py` read `int(get_setting("skill_audit_hour",
2) or 2)`, so a stored `0` — which Settings offers and confirms as "from 00:00"
— ran at 02:00; and it read the hour once before a sleep of up to a day, so a
change waited a whole extra night. `routes/skills_routes.scheduled_audit_hour`
is the one reading now, and the loop re-reads it while it waits.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import src.settings as settings
from routes.skills_routes import scheduled_audit_hour


@pytest.mark.parametrize("stored, hour", [
    (0, 0), (2, 2), (23, 23), ("5", 5),     # midnight is an hour
    (None, 2), ("nope", 2), (24, 2), (-1, 2), (True, 2),
])
def test_the_hour_is_read_as_stored(monkeypatch, stored, hour):
    monkeypatch.setattr(settings, "get_setting", lambda k, d=None: stored)
    assert scheduled_audit_hour() == hour


def test_the_loop_uses_it_and_rereads_it_while_waiting():
    app = (Path(__file__).resolve().parent.parent / "app.py").read_text(encoding="utf-8")
    body = app[app.index("async def _skill_audit_nightly_loop"):]
    body = body[:body.index("_startup_tasks.append(asyncio.create_task(_skill_audit_nightly_loop()))")]
    assert 'get_setting("skill_audit_hour", 2) or 2' not in body
    assert body.count("scheduled_audit_hour()") >= 2, "read before the wait and again during it"
