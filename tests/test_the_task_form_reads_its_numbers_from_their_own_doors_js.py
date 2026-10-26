# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B614` and `B1039` — the task form reads each number it states from the door
that is about it, and states the retry gaps it was never told.

**`B614`, measured before this file:** `default_trigger_count` — how many
events an event trigger waits for when nobody says — shipped on
`/meta/actions` only, so the form's event branch called `_fetchActions()` for
that one number: a Prompt task with an event trigger fetched the whole action
palette, though it has no action. Now `/meta/events` — which that branch
already fetches — carries it, the form reads it there, and `/meta/actions`
keeps the key for anything that read it from it (`Law 1`).

**`B1039`, measured before this file:** the form wrote the time limit's 30 s /
24 h and the retries' 10 as copies of the server's numbers, and the retry hint
said only "about twice as long as the one before", because the backoff's first
gap (`FAILURE_BACKOFF_BASE_SECONDS`, held to the interval floor) and its cap
(`FAILURE_BACKOFF_CAP_SECONDS`) were on no wire. Now `GET /api/tasks/meta/limits`
serves all of them from the scheduler's constants (`task_limits`), and the form
says "the first retry waits about 5 minutes … up to 6 hours" and refuses in the
served numbers' words.

Driven (`Law 20`): the real handlers, and the real form under node — the
harness `tests/test_one_task_form_in_two_places_js.py` built for it.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_one_task_form_in_two_places_js import (  # noqa: E402,F401
    _REQUEST, _case, _endpoint, _served_row, sandbox, task_db,
)


def _served(path):
    return json.loads(json.dumps(asyncio.run(_endpoint(path)(_REQUEST))))


# ── the doors ───────────────────────────────────────────────────────────────

def test_the_events_door_carries_the_trigger_default():
    from src.event_bus import DEFAULT_TRIGGER_COUNT
    out = _served("/api/tasks/meta/events")
    assert out["default_trigger_count"] == DEFAULT_TRIGGER_COUNT
    assert out["events"], "the events themselves are still served"


def test_the_limits_door_serves_the_schedulers_own_numbers(monkeypatch):
    import src.task_scheduler as ts
    out = _served("/api/tasks/meta/limits")
    assert out == {
        "timeout": {"min_seconds": ts.MIN_TASK_TIMEOUT_SECONDS,
                    "max_seconds": ts.MAX_TASK_TIMEOUT_SECONDS},
        "retries": {"max": ts.MAX_TASK_RETRIES,
                    "first_gap_seconds": max(ts.FAILURE_BACKOFF_BASE_SECONDS,
                                             ts.min_task_interval_seconds()),
                    "cap_seconds": ts.FAILURE_BACKOFF_CAP_SECONDS},
    }
    # The first gap is the one a retry really waits: the ladder's first rung
    # held to the interval floor, which an operator can raise.
    monkeypatch.setattr(ts, "min_task_interval_seconds", lambda: 30 * 60)
    assert _served("/api/tasks/meta/limits")["retries"]["first_gap_seconds"] == 30 * 60


def test_the_retry_count_the_route_refuses_is_the_one_it_serves(task_db, monkeypatch):
    """One number, read by the validator and served (`Law 7`)."""
    import pytest
    from fastapi import HTTPException

    import routes.task.task_routes as task_routes
    import src.task_scheduler as ts
    monkeypatch.setattr(task_routes, "SessionLocal", task_db)
    create = _endpoint("/api/tasks", "POST")
    body = {"name": "x", "prompt": "y", "schedule": "daily", "max_retries": ts.MAX_TASK_RETRIES + 1}
    with pytest.raises(HTTPException) as refused:
        asyncio.run(create(_REQUEST, task_routes.TaskCreate(**body)))
    assert refused.value.status_code == 400
    assert str(ts.MAX_TASK_RETRIES) in refused.value.detail


# ── B614 · the form ─────────────────────────────────────────────────────────

def test_a_prompt_task_on_an_event_asks_only_the_events_door(sandbox):
    out = _case(sandbox, {"events": {"events": [{"name": "document_created",
                                                 "description": "A document was made."}],
                                     "default_trigger_count": 4}}, """
        const host = hostIn();
        mountTaskFields(host, { task: null, tasks: [] });
        await tick();
        click(q(host, 'task-form-trigger-toggle').querySelector('[data-val="event"]'));
        await tick();
        console.log(JSON.stringify({
          count: q(host, 'task-form-trigger-count').value,
          urls: calls.fetch.map((c) => c.url.replace(/^https?:\\/\\/[^/]+/, '')),
        }));
    """)
    assert out["count"] == "4", "the served default is not what the box offers"
    assert "/api/tasks/meta/events" in out["urls"]
    assert not [u for u in out["urls"] if "/meta/actions" in u], (
        f"a Prompt task's event trigger fetched the action palette: {out['urls']}")


# ── B1039 · the form ────────────────────────────────────────────────────────

_WITH_LIMITS = """
const LIMITS = %s;
const inner = globalThis.fetch;
globalThis.fetch = async (url, opts) => {
  if (String(url).includes('/api/tasks/meta/limits')) {
    calls.fetch.push({ url: String(url), method: 'GET' });
    if (LIMITS === null) throw new Error('unreachable');
    return res(200, LIMITS);
  }
  return inner(url, opts);
};
"""


def _form_with_limits(sandbox, row, limits, edits=""):
    return _case(sandbox, {"saved": row}, (_WITH_LIMITS % json.dumps(limits)) + """
        const host = hostIn();
        mountTaskFields(host, { task: %s, tasks: [] });
        await tick();
        const said = {
          most: q(host, 'task-form-retries-most').textContent,
          max: q(host, 'task-form-retries').getAttribute('max'),
          hint: q(host, 'task-form-retries-hint').textContent,
        };
        %s
        click(q(host, 'task-form-save'));
        await tick();
        console.log(JSON.stringify({ said, writes: writes(), errors: ui.errors }));
    """ % (json.dumps(row), edits))


def test_the_retry_hint_says_the_served_gaps(sandbox, task_db):
    """The Verify: the gaps a person is told are the ones served — with the
    real door's answer, "the first retry waits about 5 minutes"."""
    row = _served_row(task_db)
    out = _form_with_limits(sandbox, row, _served("/api/tasks/meta/limits"))
    assert "The first retry waits about 5 minutes" in out["said"]["hint"], out["said"]
    assert "up to 6 hours" in out["said"]["hint"], out["said"]
    assert out["said"]["most"] == "(optional — up to 10 times)" and out["said"]["max"] == "10"

    # And numbers the server changes are the numbers the form says.
    other = {"timeout": {"min_seconds": 60, "max_seconds": 7200},
             "retries": {"max": 4, "first_gap_seconds": 600, "cap_seconds": 3600}}
    out = _form_with_limits(sandbox, row, other)
    assert "The first retry waits about 10 minutes" in out["said"]["hint"], out["said"]
    assert "up to 1 hour." in out["said"]["hint"], out["said"]
    assert out["said"]["most"] == "(optional — up to 4 times)" and out["said"]["max"] == "4"


def test_the_form_refuses_in_the_served_numbers_words(sandbox, task_db):
    row = _served_row(task_db)
    other = {"timeout": {"min_seconds": 60, "max_seconds": 7200},
             "retries": {"max": 4, "first_gap_seconds": 600, "cap_seconds": 3600}}
    out = _form_with_limits(sandbox, row, other, "q(host, 'task-form-retries').value = '5';")
    assert out["writes"] == [] and out["errors"] == ["Retries must be a whole number from 0 to 4"]
    out = _form_with_limits(sandbox, row, other, """
        q(host, 'task-form-timeout').value = '30';
        q(host, 'task-form-timeout-unit').value = '1';
    """)
    assert out["writes"] == []
    assert out["errors"] == ["The time limit must be between 1 minute and 2 hours"], out["errors"]


def test_before_the_door_answers_the_form_says_what_it_always_could(sandbox, task_db):
    """A door that cannot be reached leaves the server's own numbers, as the
    form held them, and a save the server still judges."""
    row = _served_row(task_db)
    out = _form_with_limits(sandbox, row, None, "q(host, 'task-form-retries').value = '3';")
    assert "about 5 minutes" in out["said"]["hint"] and out["said"]["max"] == "10"
    assert out["errors"] == [] and out["writes"][0]["body"]["max_retries"] == 3
