# SPDX-License-Identifier: AGPL-3.0-or-later
""""Just do it", earned per kind of work and granted by the person (phase 4).

The outline (*Personality, adaptation and brand*; settled call 2, B): "After a
run of approvals with no edits, Apollo offers the step up and the person
confirms ... earned per kind, never globally ... The admin's autonomy ceiling
still caps it." Driven over a temp database: `src/apollo/trust.py`, the task
answer door that records the person's answers, the scheduler's park that
answers a granted card through that same door, the routes, and the check-in
that mentions an offer once.
"""
import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.apollo import rhythm as R, trust as Tr
from src.apollo.errors import ApolloRefused
from tests.helpers.apollo_db import apollo_db  # noqa: F401  (fixture)
from tests.helpers.signed_in import ADMIN, MEMBER, as_person, signed_in
from tests.test_a_plain_task_waits_for_your_yes import world  # noqa: F401  (fixture)

ADA = "ada"


def _lead(db, owner, *, kind="mail reply", n=1, space_id=None):
    """An Apollo task of `kind` whose lead runs as scheduled task `run-{n}`."""
    from core.database import AgentHire, AgentHireTask, ApolloTask, ScheduledTask
    db.add(AgentHire(id=f"hire-{n}", owner=owner, agent_id="mailer", version="1", name="Mailer"))
    db.add(ScheduledTask(id=f"run-{n}", owner=owner, name="Mailer run", prompt="x", task_type="llm",
                         schedule="once"))
    db.flush()
    db.add(AgentHireTask(task_id=f"run-{n}", hire_id=f"hire-{n}", trigger=0))
    db.add(ApolloTask(id=f"apt-{n}", owner=owner, title="Reply to the landlord", kind=kind,
                      hire_id=f"hire-{n}", state="working", space_id=space_id, started_by="person"))
    db.flush()
    return f"run-{n}"


@pytest.fixture
def db(apollo_db):
    d = apollo_db()
    yield d
    d.close()


def _allow(db, run, tool="send_email", times=1):
    out = None
    for _ in range(times):
        out = Tr.record(db, ADA, run, "approve_task", tool) or out
    return out


def test_five_clean_allows_for_a_kind_earn_an_offer_and_a_deny_starts_over(db):
    run = _lead(db, ADA)
    assert _allow(db, run, times=4) is None
    (row,) = Tr.list_for(db, ADA)
    assert row["state"] == "drafting" and row["streak"] == 4
    assert row["words"] == "Apollo asks before send_email for mail reply. 1 more clean yes and it'll offer to just do it."
    Tr.record(db, ADA, run, "deny", "send_email")
    assert Tr.list_for(db, ADA)[0]["streak"] == 0
    offer = _allow(db, run, times=5)
    assert offer["state"] == "offered"
    assert offer["words"] == ("You've allowed send_email for mail reply 5 times in a row without a change. "
                              "Should Apollo just do it for mail reply from now on?")


def test_trust_is_per_kind_and_per_action_never_global(db):
    mail = _lead(db, ADA, kind="Mail  Reply", n=1)
    certs = _lead(db, ADA, kind="cert renewal", n=2)
    _allow(db, mail, times=5)
    _allow(db, certs, times=2)
    _allow(db, mail, tool="delete_email", times=1)
    rows = {(r["kind"], r["tool"]): r["state"] for r in Tr.list_for(db, ADA)}
    assert rows == {("mail reply", "send_email"): "offered", ("mail reply", "delete_email"): "drafting",
                    ("cert renewal", "send_email"): "drafting"}


def test_a_card_that_isnt_an_apollo_leads_or_has_no_kind_builds_nothing(db):
    from core.database import ScheduledTask
    db.add(ScheduledTask(id="plain", owner=ADA, name="Mine", prompt="x", task_type="llm", schedule="once"))
    run = _lead(db, ADA, kind=None, n=3)
    assert Tr.record(db, ADA, "plain", "approve_task", "send_email") is None
    assert Tr.record(db, ADA, run, "approve_task", "send_email") is None
    assert Tr.record(db, "bob", _lead(db, ADA, n=4), "approve_task", "send_email") is None
    assert Tr.list_for(db, ADA) == []


def test_yes_needs_the_admins_ceiling_and_not_now_keeps_quiet_for_a_month(db):
    run = _lead(db, ADA)
    offer = _allow(db, run, times=5)
    with pytest.raises(ApolloRefused) as err:
        Tr.answer(db, ADA, offer["id"], True, may_auto=False)
    assert err.value.status == 403 and "autonomy ceiling" in err.value.sentence
    out = Tr.answer(db, ADA, offer["id"], False, may_auto=True)
    assert out["state"] == "drafting" and out["streak"] == 0
    assert _allow(db, run, times=6) is None                  # declined: no new offer this month
    assert Tr.list_for(db, ADA)[0]["state"] == "drafting"


def test_a_grant_covers_its_kind_and_action_and_taking_it_back_starts_over(db):
    run = _lead(db, ADA)
    offer = _allow(db, run, times=5)
    assert Tr.answer(db, ADA, offer["id"], True, may_auto=True)["words"] == "Apollo just does send_email for mail reply."
    assert Tr.granted_kind(db, ADA, run, "send_email") == "mail reply"
    assert Tr.granted_kind(db, ADA, run, "delete_email") is None
    assert Tr.granted_kind(db, "bob", run, "send_email") is None
    out = Tr.take_back(db, ADA, offer["id"])
    assert out["state"] == "drafting" and out["streak"] == 0
    assert Tr.granted_kind(db, ADA, run, "send_email") is None
    with pytest.raises(ApolloRefused):
        Tr.answer(db, ADA, offer["id"], True, may_auto=True)    # no open offer now


def test_an_offer_behind_an_airgap_shows_only_inside_it(db):
    from src.apollo import spaces as S
    vault = S.create(db, ADA, "Medical", airgapped=True)
    run = _lead(db, ADA, space_id=vault.id)
    _allow(db, run, times=5)
    assert Tr.list_for(db, ADA, space=S.ALL) == []
    assert [r["state"] for r in Tr.list_for(db, ADA, space=vault.id)] == ["offered"]


def test_the_next_check_in_mentions_an_offer_once(db):
    from core.database import CrewMember, Session as DbSession
    db.add(DbSession(id="s", name="Apollo", endpoint_url="http://localhost:11434", model="m", owner=ADA))
    db.flush()
    db.add(CrewMember(id="crew-ada", owner=ADA, name="Apollo", session_id="s", is_default_assistant=True))
    run = _lead(db, ADA)
    _allow(db, run, times=5)
    msg, _ = R.checkin(db, ADA, "UTC")
    assert msg.startswith("You've allowed send_email for mail reply 5 times")
    assert R.checkin(db, ADA, "UTC")[0] is None


# -- the scheduler just does it, through the run's own door --------------------

def test_a_granted_card_is_answered_allow_once_by_apollo_and_the_person_isnt_asked(apollo_db, monkeypatch):
    from core.database import ScheduledTask
    from src.task_scheduler import TaskScheduler
    db = apollo_db()
    run = _lead(db, ADA)
    offer = _allow(db, run, times=5)
    Tr.answer(db, ADA, offer["id"], True, may_auto=True)
    db.commit()
    task = db.query(ScheduledTask).filter(ScheduledTask.id == run).first()
    sched = TaskScheduler(None)
    answered, pinged = [], []
    monkeypatch.setattr(sched, "add_notification", lambda *a, **k: pinged.append(a))

    async def answer_question(**kw):
        answered.append(kw)
        return "resumed", None
    monkeypatch.setattr(sched, "answer_question", answer_question)
    ceiling = {"on": True}
    monkeypatch.setattr("src.approval_mode.may_use_auto", lambda owner, **k: ceiling["on"])
    waiting = {"approval_id": "ap-1", "session_id": "sess-1"}

    async def park():
        did = sched._apollo_just_does_it(db, task, "r1", waiting, "send_email")
        await asyncio.sleep(0.05)
        return did
    assert asyncio.run(park()) is True
    (kw,) = answered
    assert (kw["task_id"], kw["run_id"], kw["approval_id"], kw["decision"], kw["session"]) == (
        run, "r1", "ap-1", "approve_task", "sess-1")
    assert kw["who"] == "Apollo (you let it just do this for mail reply)"
    assert sched.run_steps("r1")[-1]["detail"] == "You let Apollo just do send_email for mail reply, so it's allowing it."
    # Another action of the same kind still asks; so does any card once the
    # admin takes the ceiling away.
    assert asyncio.run(_just(sched, db, task, "delete_email")) is False
    ceiling["on"] = False
    assert asyncio.run(_just(sched, db, task, "send_email")) is False
    assert len(answered) == 1
    db.close()


async def _just(sched, db, task, tool):
    return sched._apollo_just_does_it(db, task, "r2", {"approval_id": "ap-2", "session_id": "s"}, tool)


# -- the routes -------------------------------------------------------------

@pytest.fixture
def trust_as(apollo_db, tmp_path, monkeypatch):
    manager = signed_in(monkeypatch, tmp_path / "auth")
    import routes.apollo_routes as apollo_routes

    def client(who):
        app = as_person(FastAPI(), who, auth_manager=manager)
        app.include_router(apollo_routes.setup_apollo_routes())
        return TestClient(app)
    return client


def test_the_trust_routes_are_each_persons_own_and_yes_is_held_to_the_ceiling(apollo_db, trust_as, monkeypatch):
    d = apollo_db()
    run = _lead(d, ADMIN)
    for _ in range(5):
        Tr.record(d, ADMIN, run, "approve_task", "send_email")
    d.commit()
    d.close()
    ada, bob = trust_as(ADMIN), trust_as(MEMBER)
    (row,) = ada.get("/api/apollo/trust").json()["trust"]
    assert row["state"] == "offered"
    assert bob.get("/api/apollo/trust").json()["trust"] == []
    assert bob.post(f"/api/apollo/trust/{row['id']}", json={"answer": "yes"}).status_code == 404
    assert ada.post(f"/api/apollo/trust/{row['id']}", json={"answer": "maybe"}).status_code == 400
    monkeypatch.setattr("src.approval_mode.may_use_auto", lambda owner, **k: False)
    r = ada.post(f"/api/apollo/trust/{row['id']}", json={"answer": "yes"})
    assert r.status_code == 403 and "autonomy ceiling" in r.text
    monkeypatch.setattr("src.approval_mode.may_use_auto", lambda owner, **k: True)
    assert ada.post(f"/api/apollo/trust/{row['id']}", json={"answer": "yes"}).json()["state"] == "granted"
    assert ada.delete(f"/api/apollo/trust/{row['id']}").json()["state"] == "drafting"


# -- end to end: the real scheduler, loop, gate and answer route ---------------

def _lead_plain(w, monkeypatch, kind="mail reply"):
    """`plain` (tests.test_a_plain_task_waits_for_your_yes) as the lead of an
    Apollo task of `kind`. The agent's own run plan (manifest, budget, checks)
    is the agents' tests' to drive; here the lead runs as the plain task."""
    from core.database import AgentHire, AgentHireTask, ApolloTask
    monkeypatch.setattr("src.agents.runtime.plan_for_task", lambda db, task, run_id=None: None)
    db = w.factory()
    db.add(AgentHire(id="hire-p", owner="alice", agent_id="mailer", version="1", name="Mailer"))
    db.flush()
    db.add(AgentHireTask(task_id="plain", hire_id="hire-p", trigger=0))
    db.add(ApolloTask(id="apt-p", owner="alice", title="Morning replies", kind=kind, hire_id="hire-p",
                      state="working", started_by="person"))
    db.commit()
    db.close()


def _trust_rows(w):
    db = w.factory()
    try:
        return Tr.list_for(db, "alice")
    finally:
        db.close()


@pytest.mark.asyncio
async def test_the_persons_allow_on_a_leads_card_counts_and_a_grant_answers_the_next_one(world, monkeypatch):
    from tests.test_a_plain_task_waits_for_your_yes import ALICE, _answer_url, _park, _plain_task
    from tests.helpers.walker_harness import client_for, runs_of, settle
    w = world
    _plain_task(w)
    _lead_plain(w, monkeypatch)
    run, rec = await _park(w)
    card = rec["waiting"]["approval"]
    async with client_for(w.app) as client:
        res = await client.post(_answer_url(run), headers=ALICE,
                                json={"approval_id": card["approval_id"], "decision": "approve_task"})
    assert res.status_code == 200, res.text
    await settle(w.s)
    (row,) = _trust_rows(w)
    assert (row["kind"], row["tool"], row["streak"], row["state"]) == ("mail reply", "bash", 1, "drafting")

    # Granted (as five clean yeses and the person's yes would), the next card
    # is answered by Apollo through the same door: it runs once, nobody is asked.
    db = w.factory()
    from core.database import ApolloTrust
    t = db.query(ApolloTrust).one()
    t.state, t.streak = "granted", 5
    db.commit()
    db.close()
    monkeypatch.setattr("src.approval_mode.may_use_auto", lambda owner, **k: True)
    w.s.pop_notifications()
    w.executed.clear()
    w.script.append("```bash\nprintf second-reply\n```")
    from tests.test_a_plain_task_waits_for_your_yes import _webhook
    await w.s._execute_task("plain", trigger=_webhook())
    await settle(w.s)
    last = runs_of(w.factory, "plain")[-1]
    assert w.executed == [("bash", "printf second-reply")], last
    assert last["status"] == "success", last
    assert any(s.get("detail") == "You let Apollo just do bash for mail reply, so it's allowing it."
               for s in last["steps"])
    assert not [n for n in w.s.pop_notifications() if n["status"] == "waiting"], "nobody was asked"
    assert _trust_rows(w)[0]["streak"] == 5, "Apollo's own answer isn't the person's record"


@pytest.mark.asyncio
async def test_without_the_ceiling_a_grant_still_asks(world, monkeypatch):
    from tests.test_a_plain_task_waits_for_your_yes import _park, _plain_task
    w = world
    _plain_task(w)
    _lead_plain(w, monkeypatch)
    db = w.factory()
    from core.database import ApolloTrust
    db.add(ApolloTrust(id="t1", owner="alice", kind="mail reply", tool="bash", state="granted", streak=5,
                       allowed=5, denied=0))
    db.commit()
    db.close()
    monkeypatch.setattr("src.approval_mode.may_use_auto", lambda owner, **k: False)
    run, rec = await _park(w)
    assert run["status"] == "waiting" and w.executed == []
    assert [n for n in w.s.pop_notifications() if n["status"] == "waiting"]
