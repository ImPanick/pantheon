# SPDX-License-Identifier: AGPL-3.0-or-later
"""A lead's run reports back to Apollo (settled calls 3, 8 and 9).

When the lead agent's run for a goal finishes, its report moves the goal on:
Done with the report's first line as the outcome, or Needs you with one
question when the run didn't deliver. The run's tokens are charged to the goal
only on an API-billed model. Apollo's chat gets one line. A run that isn't an
Apollo goal's is left exactly as it was.
"""
from types import SimpleNamespace

import pytest

from core.database import Event
from src.apollo import runs
from src.apollo import tasks as T
from tests.helpers.apollo_db import apollo_db  # noqa: F401  (fixture)

PAID = "https://api.example-llm.com/v1/chat/completions"
LOCAL = "http://localhost:8080/v1/chat/completions"
REPORT = "Here is what I did.\n\n## Report\n- Booked Thursday 9 AM with Dr. Lee.\n- Calendar updated."


@pytest.fixture
def goal(apollo_db, monkeypatch):
    db = apollo_db()
    t = T.create(db, "ada", title="Book the dentist", pick=lambda o, x: {"id": "booker"})
    t.hire_id = "hire-1"
    db.add(Event(run_id="run-1", input_tokens=700, output_tokens=300))
    db.commit()
    monkeypatch.setattr("src.agents.hires.hire_for_task",
                        lambda db, task_id: SimpleNamespace(id="hire-1", owner="ada")
                        if task_id == "sched-1" else None)
    return db, t


def landed(db, answer, *, checks=None, endpoint=PAID):
    posted = []
    line = runs.report_landed(db, SimpleNamespace(id="sched-1", session_id="s-9"), "run-1",
                              answer, checks=checks, endpoint_url=endpoint,
                              post=lambda owner, text, meta: posted.append((owner, text, meta)))
    return line, posted


def test_a_good_report_marks_the_goal_done_with_its_outcome(goal):
    db, t = goal
    line, posted = landed(db, REPORT)
    db.refresh(t)
    assert t.state == "done"
    assert t.outcome == "Booked Thursday 9 AM with Dr. Lee."
    assert t.session_id == "s-9"
    assert posted == [("ada", line, {"source": "apollo", "apollo_task_id": t.id, "state": "done"})]
    assert line.startswith("Done: Book the dentist.")


def test_a_short_run_puts_the_goal_back_to_you_with_one_question(goal):
    db, t = goal
    landed(db, REPORT, checks=[{"ok": False, "detail": "no calendar event"}])
    db.refresh(t)
    assert t.state == "needs_you" and t.question.endswith("?")


def test_tokens_are_charged_on_a_paid_model_only(goal):
    db, t = goal
    landed(db, REPORT, endpoint=LOCAL)
    db.refresh(t)
    assert t.spent_tokens == 0
    t.state = "working"
    db.commit()
    landed(db, REPORT, endpoint=PAID)
    db.refresh(t)
    assert t.spent_tokens == 1_000


def test_a_run_that_is_not_an_apollo_goals_is_left_alone(goal):
    db, t = goal
    line = runs.report_landed(db, SimpleNamespace(id="other", session_id=None), "run-1", REPORT,
                              endpoint_url=PAID)
    db.refresh(t)
    assert line is None and t.state == "working" and t.spent_tokens == 0


def test_the_lead_is_told_its_goal_and_any_answer_you_gave(goal):
    db, t = goal
    T.set_state(t, "needs_you", question="Morning or afternoon?")
    T.answer(db, "ada", t.id, "Morning")
    manifest = SimpleNamespace(name="Booker", memory="none", runbook="Find a slot, then book it.")
    parts = runs.apollo_plan_parts(db, SimpleNamespace(id="hire-1", owner="ada"), manifest)
    assert "handed you: Book the dentist" in parts["system_prompt"]
    assert "Find a slot, then book it." in parts["system_prompt"]
    assert "## Report" in parts["system_prompt"]
    brief = parts["context_messages"][0]["content"]
    assert "Morning" in brief
    assert runs.apollo_plan_parts(db, SimpleNamespace(id="nobody", owner="ada"), manifest) is None


def test_every_other_hire_keeps_its_own_prompt(apollo_db):
    db = apollo_db()
    assert runs.apollo_plan_parts(db, SimpleNamespace(id="h-x", owner="bob"),
                                  SimpleNamespace(name="X", memory="none", runbook="r")) is None


def test_a_goal_over_budget_on_a_paid_model_asks_instead_of_starting(goal, monkeypatch):
    db, t = goal
    t.budget_tokens = 500
    t.spent_tokens = 500
    db.commit()
    run, why = runs.prepare(db, "ada", t, endpoint_url=PAID)
    assert run is None and why.endswith(".")
    assert t.state == "needs_you"

