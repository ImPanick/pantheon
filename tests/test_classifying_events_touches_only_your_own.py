# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2030`. Calendar Classify Events read and changed everybody's events.

`classify_events` (the "Calendar Classify Events" task every person has, and
a workflow step) chose the upcoming events by date and status alone, with no
owner. So one person's run sent every account's event titles and places for
the next 30 days to that person's model (which may be a cloud provider the
others never chose, or an endpoint the runner can read), and wrote a type,
a colour and an importance onto other people's events. Its own test checked
only whose model was used.

Now a run reads the events of its owner's calendars, joined the way the
check-in digest joins them. An unowned calendar counts where the daily brief
counts it (before the first account exists, v2 review HIGH-12), and a run
for nobody reads nothing once there are accounts (`B1271`).

Pantheon's own finding; upstream Odysseus has the same query.
"""
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import core.database as cdb
from src import builtin_actions

UNTOUCHED = (None, "normal", None)   # event_type, importance, color as stored


@pytest.fixture
def calendars(monkeypatch):
    """Alice's, Bob's and an unowned calendar, each with an event the keyword
    rules leave to the model; returns (session factory, prompts sent)."""
    engine = create_engine("sqlite://", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    for model in (cdb.CalendarCal, cdb.CalendarEvent):
        model.__table__.create(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(cdb, "SessionLocal", factory)

    soon = datetime.utcnow() + timedelta(days=2)
    rows = [
        ("alice", "Catch up with Sam", "Alice's kitchen", soon, "confirmed"),
        ("alice", "Called off coffee", "", soon, "cancelled"),
        ("alice", "Catch up with Jo", "", soon + timedelta(days=40), "confirmed"),
        ("bob", "Planning with Priya", "Bob's office, 4th floor", soon, "confirmed"),
        (None, "Board game night", "Community hall", soon, "confirmed"),
    ]
    with factory() as db:
        for owner in ("alice", "bob", None):
            db.add(cdb.CalendarCal(id=owner or "unowned", owner=owner, name=owner or "unowned"))
        for n, (owner, title, place, start, status) in enumerate(rows):
            db.add(cdb.CalendarEvent(uid=f"ev{n}", calendar_id=owner or "unowned", summary=title,
                                     location=place, dtstart=start,
                                     dtend=start + timedelta(hours=1), status=status))
        db.commit()

    from src import llm_core, task_endpoint

    prompts = []

    async def model(_candidates, **kwargs):
        prompt = kwargs["messages"][0]["content"]
        prompts.append(prompt)
        items = json.loads(prompt.rsplit("EVENTS: ", 1)[1])
        return json.dumps([{"i": it["i"], "type": "social", "importance": "high"} for it in items])

    async def quiet(_label):
        return False

    monkeypatch.setattr(task_endpoint, "resolve_task_candidates",
                        lambda **_kwargs: [("http://llm.test/v1", "model", {})])
    monkeypatch.setattr(llm_core, "llm_call_async_with_fallback", model)
    monkeypatch.setattr(builtin_actions, "wait_for_interactive_quiet", quiet)
    monkeypatch.setattr("src.ai_interaction._memory_manager", None)
    yield factory, prompts
    engine.dispose()


def _accounts(monkeypatch, exist: bool):
    monkeypatch.setattr("src.auth_manager_access.shared_auth_manager",
                        lambda: SimpleNamespace(is_configured=exist))


def _marks(factory):
    with factory() as db:
        return {ev.summary: (ev.event_type, ev.importance, ev.color)
                for ev in db.query(cdb.CalendarEvent).all()}


CLASSIFIED = ("social", "high", builtin_actions._TYPE_COLORS["social"])


async def test_a_run_reads_and_changes_only_its_owners_events(calendars, monkeypatch):
    factory, prompts = calendars
    _accounts(monkeypatch, exist=True)

    message, ok = await builtin_actions.action_classify_events("alice")

    assert ok is True, message
    assert "Scanned 1 upcoming event" in message, message
    sent = "\n".join(prompts)
    assert "Catch up with Sam" in sent and "Alice's kitchen" in sent
    for theirs in ("Planning with Priya", "Bob's office", "Board game night", "Community hall"):
        assert theirs not in sent
    assert _marks(factory) == {
        "Catch up with Sam": CLASSIFIED,
        "Called off coffee": UNTOUCHED,   # cancelled
        "Catch up with Jo": UNTOUCHED,    # beyond the 30 days
        "Planning with Priya": UNTOUCHED,
        "Board game night": UNTOUCHED,
    }


async def test_a_run_for_nobody_classifies_nothing_once_there_are_accounts(calendars, monkeypatch):
    factory, prompts = calendars
    _accounts(monkeypatch, exist=True)

    message, ok = await builtin_actions.action_classify_events("")

    assert (message, ok) == ("No upcoming events to classify", True)
    assert prompts == []
    assert set(_marks(factory).values()) == {UNTOUCHED}


async def test_before_the_first_account_an_unowned_calendar_is_everyones(calendars, monkeypatch):
    factory, prompts = calendars
    _accounts(monkeypatch, exist=False)

    message, ok = await builtin_actions.action_classify_events("alice")

    assert ok is True, message
    assert "Planning with Priya" not in "\n".join(prompts)
    marks = _marks(factory)
    assert marks["Catch up with Sam"] == marks["Board game night"] == CLASSIFIED
    assert marks["Planning with Priya"] == UNTOUCHED
