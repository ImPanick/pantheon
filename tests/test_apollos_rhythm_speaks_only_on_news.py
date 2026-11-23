# SPDX-License-Identifier: AGPL-3.0-or-later
"""Apollo's rhythm (phase 4): briefings at the person's times, check-ins that
speak only on news, quiet hours that hold.

The outline (*Core behaviours* 1, settled call 4): "Briefings at the times
each person sets, plus check-ins between them that speak only when something
changed ... Quiet hours hold." Every case drives the real code over a temp
database: `src/apollo/rhythm.py`, the scheduler's own dispatch, and the
`/api/apollo/rhythm` routes behind the real sign-in.
"""
import asyncio
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.apollo import notebook, rhythm as R, spaces as S, tasks as T
from src.apollo.errors import ApolloRefused
from tests.helpers.apollo_db import apollo_db  # noqa: F401  (fixture)
from tests.helpers.signed_in import ADMIN, MEMBER, as_person, signed_in

ADA, BOB = "ada", "bob"
NO_FIT = lambda owner, text: None  # noqa: E731


def _apollo_chat(SessionLocal, owner, sid=None, tz="America/Anchorage"):
    from core.database import CrewMember, Session as DbSession
    sid = sid or f"s-apollo-{owner}"
    db = SessionLocal()
    db.add(DbSession(id=sid, name="Apollo", endpoint_url="http://localhost:11434", model="m", owner=owner))
    db.add(CrewMember(id=f"crew-{owner}", owner=owner, name="Apollo", session_id=sid,
                      is_default_assistant=True, timezone=tz))
    db.commit()
    db.close()
    return sid


@pytest.fixture
def db(apollo_db):
    _apollo_chat(apollo_db, ADA)
    d = apollo_db()
    yield d
    d.close()


def _task(db, title, **k):
    return T.create(db, ADA, title=title, pick=NO_FIT, **k)


# -- check-ins speak only on news -------------------------------------------

def test_a_check_in_with_nothing_new_stays_quiet_and_says_so(db):
    msg, line = R.checkin(db, ADA, "UTC")
    assert msg is None
    assert line == "Nothing changed since Apollo last spoke, so it stayed quiet."
    _task(db, "Draft the grant")              # working is not news
    assert R.checkin(db, ADA, "UTC")[0] is None


def test_a_task_that_needs_the_person_is_news_once_until_it_changes(db):
    t = _task(db, "Renew the domain")
    T.set_state(t, "needs_you", question="Two years or five?")
    msg, line = R.checkin(db, ADA, "UTC")
    assert msg == "“Renew the domain” needs you: Two years or five?"
    assert line == "Spoke: 1 new."
    # Said once; the same question again is not news.
    assert R.checkin(db, ADA, "UTC")[0] is None
    # A new question is.
    T.set_state(t, "needs_you", question="Which card?")
    assert R.checkin(db, ADA, "UTC")[0] == "“Renew the domain” needs you: Which card?"
    # Finishing it is news too, with its outcome.
    T.set_state(t, "done", outcome="Renewed for five years.")
    assert R.checkin(db, ADA, "UTC")[0] == "“Renew the domain” is done: Renewed for five years."
    assert R.checkin(db, ADA, "UTC")[0] is None


def test_several_things_come_as_one_message_with_the_count_first(db):
    a, b = _task(db, "Book the venue"), _task(db, "Pick a caterer")
    T.set_state(a, "needs_you", question="Saturday or Sunday?")
    T.set_state(b, "done", outcome="Booked Ortiz.")
    msg, _ = R.checkin(db, ADA, "UTC")
    first, *rest = msg.split("\n")
    assert first == "2 things since I last spoke:"
    assert sorted(rest) == ["- “Book the venue” needs you: Saturday or Sunday?",
                            "- “Pick a caterer” is done: Booked Ortiz."]


def test_a_task_in_a_space_names_its_space(db):
    home = S.create(db, ADA, "Home")
    t = _task(db, "Fix the gutter", space_id=home.id)
    T.set_state(t, "needs_you", question="This weekend?")
    assert R.checkin(db, ADA, "UTC")[0] == "“Fix the gutter” (in Home) needs you: This weekend?"


def test_a_locked_space_says_only_that_something_there_needs_them(db):
    vault = S.create(db, ADA, "Medical", airgapped=True)
    inner = S.create(db, ADA, "Claims", parent_id=vault.id)
    t = _task(db, "Appeal the denial", space_id=inner.id)
    T.set_state(t, "needs_you", question="Sign the appeal letter?")
    msg, _ = R.checkin(db, ADA, "UTC")
    assert msg == "Something in “Medical” needs you."
    assert "Appeal" not in msg and "Claims" not in msg
    assert R.checkin(db, ADA, "UTC")[0] is None


def test_quiet_hours_hold_in_the_persons_own_zone_across_midnight(db):
    R.save(db, ADA, quiet={"start": "22:00", "end": "07:00"})
    t = _task(db, "Answer the landlord")
    T.set_state(t, "needs_you", question="Accept Tuesday?")
    # 08:00 UTC is 23:00 the night before in Anchorage (UTC-9 in November).
    late = datetime(2026, 11, 23, 8, 0)
    msg, line = R.checkin(db, ADA, "America/Anchorage", now=late)
    assert msg is None and line == "Quiet hours: Apollo stayed quiet."
    # 17:00 UTC is 08:00 in Anchorage: quiet hours are over, and the news waited.
    morning = datetime(2026, 11, 23, 17, 0)
    assert R.checkin(db, ADA, "America/Anchorage", now=morning)[0] == "“Answer the landlord” needs you: Accept Tuesday?"


def test_an_open_loop_reaches_the_briefing_not_the_check_in(db):
    notebook.add(db, ADA, "Promised Dev the budget numbers", kind="open_loop")
    d = R.digest(db, ADA)
    assert d["loops"] == ["Promised Dev the budget numbers"]
    assert d["news"] == []
    assert "Open loops they owe or were promised:\n- Promised Dev the budget numbers" in R.section(d)


# -- settings ---------------------------------------------------------------

def _scheduled(db):
    from core.database import ScheduledTask
    return {t.id: t for t in db.query(ScheduledTask).filter(ScheduledTask.owner == ADA).all()}


def test_briefings_are_daily_tasks_on_the_engine_and_the_earliest_is_first_light(db):
    out = R.save(db, ADA, briefings=[{"time": "17:30"}, {"time": "07:00"}])
    assert [(b["name"], b["time"], b["enabled"]) for b in out["briefings"]] == [
        ("First light", "07:00", True), ("Briefing", "17:30", True)]
    rows = _scheduled(db)
    assert {(t.name, t.schedule, t.scheduled_time, t.crew_member_id, t.session_id, t.notifications_enabled)
            for t in rows.values()} == {
        ("First light", "daily", "07:00", "crew-ada", "s-apollo-ada", False),
        ("Briefing", "daily", "17:30", "crew-ada", "s-apollo-ada", False)}
    assert all(t.next_run is not None for t in rows.values())
    assert {R.kind_of(db, t) for t in rows.values()} == {"briefing"}
    # Keep the evening one, paused; drop the morning one: its task goes.
    evening = out["briefings"][1]["id"]
    out = R.save(db, ADA, briefings=[{"id": evening, "time": "18:00", "enabled": False}])
    assert [(b["id"], b["name"], b["time"], b["enabled"]) for b in out["briefings"]] == [
        (evening, "First light", "18:00", False)]
    assert list(_scheduled(db)) == [evening]
    assert _scheduled(db)[evening].status == "paused"


def test_a_briefing_list_is_checked_before_anything_changes(db):
    for bad, why in (([{"time": "7am"}], "HH:MM"),
                     ([{"time": "07:00"}, {"time": "07:00"}], "same time"),
                     ([{"time": f"0{i}:00"} for i in range(7)], "Up to 6")):
        with pytest.raises(ApolloRefused) as err:
            R.save(db, ADA, briefings=bad)
        assert why in err.value.sentence
    assert _scheduled(db) == {}


def test_check_ins_look_on_a_cron_and_off_removes_the_task(db):
    assert R.to_dict(db, ADA)["checkin_hours"] == 0       # none until the person sets it
    out = R.save(db, ADA, checkin_hours=3)
    assert out["checkin_hours"] == 3
    (task,) = _scheduled(db).values()
    assert (task.name, task.schedule, task.cron_expression) == ("Apollo check-in", "cron", "0 */3 * * *")
    assert R.kind_of(db, task) == "checkin"
    R.save(db, ADA, checkin_hours=6)
    (again,) = _scheduled(db).values()
    assert again.id == task.id and again.cron_expression == "0 */6 * * *"
    with pytest.raises(ApolloRefused):
        R.save(db, ADA, checkin_hours=5)
    assert R.save(db, ADA, checkin_hours=0)["checkin_hours"] == 0
    assert _scheduled(db) == {}


def test_a_task_named_like_a_briefing_is_not_one(db):
    """Which tasks are Apollo's is Apollo's record, never a name."""
    from core.database import ScheduledTask
    fake = ScheduledTask(id="t-fake", owner=ADA, name="First light", prompt="x", task_type="llm",
                         schedule="daily", scheduled_time="07:00", crew_member_id="crew-ada")
    db.add(fake)
    db.flush()
    assert R.kind_of(db, fake) is None


def test_no_apollo_chat_yet_is_refused_in_a_sentence(apollo_db):
    d = apollo_db()
    with pytest.raises(ApolloRefused) as err:
        R.save(d, BOB, briefings=[{"time": "07:00"}])
    assert err.value.status == 409
    assert "Apollo chat" in err.value.sentence
    d.close()


# -- the scheduler runs them --------------------------------------------------

class _Chats:
    def __init__(self):
        self.lines = []

    def add_message(self, session_id, message):
        self.lines.append((session_id, message.content, dict(message.metadata or {})))


def _run(sched, task_id, SessionLocal):
    from core.database import ScheduledTask
    db = SessionLocal()
    try:
        task = db.query(ScheduledTask).filter(ScheduledTask.id == task_id).first()
        return asyncio.run(sched._execute_llm_task(task, db, run_id="r1"))
    finally:
        db.close()


def test_the_scheduler_runs_a_check_in_with_no_model_and_posts_only_news(apollo_db, monkeypatch):
    from src.task_scheduler import TaskScheduler
    _apollo_chat(apollo_db, ADA, tz="UTC")
    d = apollo_db()
    task_id = R.save(d, ADA, checkin_hours=1) and R.row(d, ADA).checkin_task_id
    d.commit()
    chats = _Chats()
    sched = TaskScheduler(chats)
    monkeypatch.setattr(sched, "_usable_route",
                        lambda *a, **k: pytest.fail("a check-in never asks for a model"))
    assert _run(sched, task_id, apollo_db) == "Nothing changed since Apollo last spoke, so it stayed quiet."
    assert chats.lines == []
    t = _task(d, "Renew the domain")
    T.set_state(t, "needs_you", question="Two years or five?")
    d.commit()
    assert _run(sched, task_id, apollo_db) == "Spoke: 1 new."
    assert chats.lines == [("s-apollo-ada", "“Renew the domain” needs you: Two years or five?",
                            {"apollo": "checkin"})]
    assert [s["detail"] for s in sched.run_steps("r1")][-1] == "Spoke: 1 new."
    assert _run(sched, task_id, apollo_db).startswith("Nothing changed")
    assert len(chats.lines) == 1
    d.close()


def test_a_briefing_hands_the_model_apollos_section_and_the_next_check_in_doesnt_repeat_it(apollo_db, monkeypatch):
    from src.task_scheduler import TaskScheduler
    _apollo_chat(apollo_db, ADA, tz="UTC")
    d = apollo_db()
    R.save(d, ADA, briefings=[{"time": "07:00"}], checkin_hours=2)
    first_light = R.to_dict(d, ADA)["briefings"][0]["id"]
    checkin_id = R.row(d, ADA).checkin_task_id
    t = _task(d, "Pick a caterer")
    T.set_state(t, "needs_you", question="Ortiz or Lane?")
    d.commit()
    seen = {}

    async def fake_checkin(self, task, crew, db, session_id, endpoint_url, model, run_id=None,
                           apollo_section=None):
        seen.update(name=task.name, section=apollo_section)
        return "Good morning."
    monkeypatch.setattr(TaskScheduler, "_execute_checkin", fake_checkin)
    sched = TaskScheduler(_Chats())
    monkeypatch.setattr(sched, "_usable_route", lambda db, task, e, m: (e or "http://localhost:11434", m or "m"))
    assert _run(sched, first_light, apollo_db) == "Good morning."
    assert seen["name"] == "First light"
    assert "Needs them:\n- “Pick a caterer” needs you: Ortiz or Lane?" in seen["section"]
    assert _run(sched, checkin_id, apollo_db).startswith("Nothing changed")
    d.close()


# -- the routes -------------------------------------------------------------

@pytest.fixture
def rhythm_as(apollo_db, tmp_path, monkeypatch):
    manager = signed_in(monkeypatch, tmp_path / "auth")
    import routes.apollo_routes as apollo_routes

    def client(who):
        app = as_person(FastAPI(), who, auth_manager=manager)
        app.include_router(apollo_routes.setup_apollo_routes())
        return TestClient(app)
    return client


def test_the_rhythm_routes_are_each_persons_own(apollo_db, rhythm_as):
    _apollo_chat(apollo_db, ADMIN)
    ada, bob = rhythm_as(ADMIN), rhythm_as(MEMBER)
    r = ada.put("/api/apollo/rhythm", json={"briefings": [{"time": "07:00"}], "checkin_hours": 3,
                                            "quiet": {"start": "22:00", "end": "07:00"}})
    assert r.status_code == 200, r.text
    got = ada.get("/api/apollo/rhythm").json()
    assert [b["name"] for b in got["briefings"]] == ["First light"]
    assert got["checkin_hours"] == 3
    assert got["quiet"] == {"start": "22:00", "end": "07:00"}
    assert got["timezone"] == "America/Anchorage" and got["has_chat"] is True
    # Bob has no Apollo chat, sees nothing of Ada's, and can't set a rhythm yet.
    mine = bob.get("/api/apollo/rhythm").json()
    assert mine["briefings"] == [] and mine["checkin_hours"] == 0 and mine["has_chat"] is False
    r = bob.put("/api/apollo/rhythm", json={"checkin_hours": 3})
    assert r.status_code == 409
    # A bad time is a sentence, and changes nothing.
    r = ada.put("/api/apollo/rhythm", json={"briefings": [{"time": "25:00"}]})
    assert r.status_code == 400 and "HH:MM" in r.text
    assert [b["time"] for b in ada.get("/api/apollo/rhythm").json()["briefings"]] == ["07:00"]
    # Quiet hours come off with an empty pair.
    ada.put("/api/apollo/rhythm", json={"quiet": {"start": None, "end": None}})
    assert ada.get("/api/apollo/rhythm").json()["quiet"] == {"start": None, "end": None}
