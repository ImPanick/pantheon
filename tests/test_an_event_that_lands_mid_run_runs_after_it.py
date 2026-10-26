# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1512` — an event fired while its task is running runs after it, with its own payload.

The remainder of `B1075`, inferred from the code there and driven here. The
email server's process (no scheduler) writes `next_run = now` and
`pending_trigger` on the row while a run of the same task is in flight; at its
end `_execute_task_locked` set `task.next_run = None` from the row it had
loaded when it started — overwriting the event's `next_run`, so the loop never
ran it — and the envelope was then taken by whatever run started next, a
person's *Run now*, say. Now the finishing run reads the row again and keeps a
queued event due (`_queued_event_due`, through `_next_run_after`), and a run a
person started with no trigger of its own leaves the envelope to the event's
run.

Driven (`Law 20`): the real bus with no scheduler (the subprocess) and the real
`TaskScheduler`'s loop on one SQLite file; only the model is a recorder
(`walker_harness.recording_scheduler`), and the second event is fired from
inside the first run.
"""
from __future__ import annotations

import asyncio

from src.interactive_gate import STARTED_BY_PERSON
from tests.helpers.walker_harness import OWNER, recording_scheduler
from tests.test_an_event_from_another_process_reaches_its_task_with_its_payload import (  # noqa: F401
    _loop_once, _row, world,
)

import src.event_bus as bus  # noqa: E402

ONE = {"document_id": "doc-1", "title": "One"}
TWO = {"document_id": "doc-2", "title": "Two"}


def _fire_elsewhere(payload):
    """`document_updated` where no scheduler runs: the email server's process."""
    return bus._handle_event("document_updated", OWNER, payload)


def _handed(scheduler):
    return [c["trigger"]["data"] if c["trigger"] else None for c in scheduler.calls]


def test_an_event_landing_mid_run_runs_once_after_it_with_its_own_payload(world, monkeypatch):
    monkeypatch.setattr(bus, "_task_scheduler", None)
    asyncio.run(_fire_elsewhere(ONE))

    fired = []

    async def second_event_arrives(task, run_id):
        if not fired:                      # during the first run only
            fired.append(True)
            await _fire_elsewhere(TWO)
        return "read it"

    s = recording_scheduler({"Read the edited draft": second_event_arrives})
    asyncio.run(_loop_once(s))
    assert _handed(s) == [ONE]
    assert _row(world).next_run is not None, "the second event was overwritten by the first run"
    assert _row(world).pending_trigger is not None

    asyncio.run(_loop_once(s))
    assert _handed(s)[1] == TWO
    assert _row(world).pending_trigger is None and _row(world).next_run is None

    # A later Run now is handed nothing.
    asyncio.run(s._execute_task("t1", started_by=STARTED_BY_PERSON))
    assert _handed(s)[2:] == [None]


def test_a_person_s_run_now_leaves_a_queued_event_to_its_own_run(world, monkeypatch):
    monkeypatch.setattr(bus, "_task_scheduler", None)
    asyncio.run(_fire_elsewhere(ONE))
    s = recording_scheduler()

    asyncio.run(s._execute_task("t1", started_by=STARTED_BY_PERSON))
    assert _handed(s) == [None], "the person's run was handed the event's document"
    assert _row(world).pending_trigger is not None and _row(world).next_run is not None

    asyncio.run(_loop_once(s))
    assert _handed(s) == [None, ONE]
    assert _row(world).pending_trigger is None


def test_a_run_with_its_own_trigger_does_not_take_another_event_s(world, monkeypatch):
    """A webhook's run (its own envelope) used to clear whatever event was
    queued on the row — taken by a run that was never handed it."""
    from src.event_bus import TRIGGER_SOURCE_WEBHOOK, build_trigger

    monkeypatch.setattr(bus, "_task_scheduler", None)
    asyncio.run(_fire_elsewhere(ONE))
    s = recording_scheduler()

    hook = build_trigger(TRIGGER_SOURCE_WEBHOOK, "hook", {"n": 1})
    asyncio.run(s._execute_task("t1", trigger=hook))
    assert _row(world).pending_trigger is not None

    asyncio.run(_loop_once(s))
    assert [c["trigger"]["source"] for c in s.calls] == ["webhook", "event"]
    assert _handed(s)[1] == ONE
