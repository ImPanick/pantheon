# SPDX-License-Identifier: AGPL-3.0-or-later
"""An Apollo task is Working, Needs you, Waiting or Done (settled call 3).

A task waits on the person only with the one question it needs answered; the
answer sends it back to work, kept as its next step for the lead. The pane's
header reads what Apollo is doing from these states. When no lead can be
written for a goal the task is still made, and says Apollo leads it.
"""
import pytest

from src.apollo import tasks as T
from src.apollo.errors import ApolloRefused
from tests.helpers.apollo_db import apollo_db  # noqa: F401  (fixture)

NO_FIT = lambda owner, text: None  # noqa: E731
FITS = lambda owner, text: {"id": "trip-planner"}  # noqa: E731


def test_a_new_task_is_working_and_led_by_the_roster_pick(apollo_db):
    db = apollo_db()
    t = T.create(db, "ada", title="Plan the Juneau trip", pick=FITS)
    assert t.state == "working" and t.lead_agent == "trip-planner"
    assert t.started_by == "person"


def test_with_no_lead_the_task_is_made_and_apollo_leads_it(apollo_db):
    db = apollo_db()
    t = T.create(db, "ada", title="Something nobody does", pick=NO_FIT)
    assert t.lead_agent is None
    assert "Apollo leads it" in t.next_step


def test_needs_you_needs_its_one_question(apollo_db):
    db = apollo_db()
    t = T.create(db, "ada", title="Book the dentist", pick=NO_FIT)
    with pytest.raises(ApolloRefused):
        T.set_state(t, "needs_you")
    T.set_state(t, "needs_you", question="Tuesday or Thursday?")
    assert t.question == "Tuesday or Thursday?"


def test_an_answer_sends_the_task_back_to_work_with_the_answer_kept(apollo_db):
    db = apollo_db()
    t = T.create(db, "ada", title="Book the dentist", pick=NO_FIT)
    T.set_state(t, "needs_you", question="Tuesday or Thursday?")
    T.answer(db, "ada", t.id, "Thursday")
    assert t.state == "working" and t.question is None
    assert "Thursday" in t.next_step and "Tuesday or Thursday?" in t.next_step


def test_a_task_not_waiting_on_you_takes_no_answer(apollo_db):
    db = apollo_db()
    t = T.create(db, "ada", title="Book the dentist", pick=NO_FIT)
    with pytest.raises(ApolloRefused) as refused:
        T.answer(db, "ada", t.id, "Thursday")
    assert refused.value.status == 409


def test_done_keeps_its_outcome_and_when(apollo_db):
    db = apollo_db()
    t = T.create(db, "ada", title="Book the dentist", pick=NO_FIT)
    T.set_state(t, "done", outcome="Booked Thursday 9 AM.")
    assert t.done_at is not None and t.outcome == "Booked Thursday 9 AM."


def test_the_header_says_needs_you_before_it_says_working(apollo_db):
    db = apollo_db()
    assert T.status(db, "ada")["words"].lower().startswith("idle")
    a = T.create(db, "ada", title="One", pick=NO_FIT)
    T.create(db, "ada", title="Two", pick=NO_FIT)
    db.flush()
    assert "working" in T.status(db, "ada")["words"].lower()
    T.set_state(a, "needs_you", question="Which one?")
    db.flush()
    assert T.status(db, "ada")["words"].lower().startswith("needs you")


def test_another_persons_task_is_not_found(apollo_db):
    db = apollo_db()
    t = T.create(db, "ada", title="Mine", pick=NO_FIT)
    db.commit()
    with pytest.raises(ApolloRefused) as refused:
        T.get(db, "bob", t.id)
    assert refused.value.status == 404
    assert T.list_for(db, "bob") == []
