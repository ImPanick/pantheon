# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P24-21` / `P24-13` — a team is hired in one go, and *Try it once* runs a
trial now.

Through `TestClient` on a real SQLite file against the real shipped manifests
and teams, the routes and fixtures `test_a_hire_compiles_to_tasks.py` uses
(`Law 14`), with the scheduler handed to the agent routes as `app.py` hands it.

**Measured before this file, on `6f51844`:** `/api/agents/teams/…` and
`/api/agents/{id}/try` answered 404, and there was no `TEAM.md` anywhere.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.test_a_workflow_is_kept_as_one_document import (  # noqa: F401  (fixtures)
    admins, sched, wf_db,
)
from tests.test_a_hire_compiles_to_tasks import call
from core.database import AgentHire, ScheduledTask
from src.agents import teams as T
from src.agents.catalogue import catalogue
from src.agents.manifest import ManifestRefused


@pytest.fixture()
def client(wf_db, sched, admins, monkeypatch, tmp_path):
    import routes.agent_routes as agent_routes
    import routes.task.task_routes as task_routes
    import routes.prefs_routes as prefs
    import src.constants as constants
    import src.task_action_policy as tap
    import src.tool_security as ts
    import src.workstation_access as wa
    monkeypatch.setattr(task_routes, "SessionLocal", wf_db)
    monkeypatch.setattr(agent_routes, "SessionLocal", wf_db)
    monkeypatch.setattr(task_routes, "record_admin_refusal", tap.record_admin_refusal)
    monkeypatch.setattr(prefs, "_load_for_user", lambda user=None: {})
    monkeypatch.setattr(constants, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(ts, "owner_is_admin_or_single_user", lambda owner: owner in admins)
    monkeypatch.setattr(wa, "may_use", lambda owner, **kw: owner in admins)
    app = FastAPI()

    @app.middleware("http")
    async def _who(request, call_next):
        request.state.current_user = request.headers.get("x-test-user")
        return await call_next(request)

    app.include_router(agent_routes.setup_agent_routes(task_scheduler=sched))
    app.include_router(task_routes.setup_task_routes(sched))
    return TestClient(app)


TEAM = """---
id: pair
name: Pair
tagline: Two of them.
members: [morning-brief, topic-watcher]
---
About.
"""


# ── the file ────────────────────────────────────────────────────────────────

def test_every_shipped_team_reads_and_names_only_agents_the_hall_has():
    agents, _ = catalogue(None)
    found, broken = T.teams(None, [m.id for m in agents])
    assert broken == []
    assert len(found) == 14
    for team in found:
        assert 2 <= len(team.members) <= T.TEAM_MAX_MEMBERS


@pytest.mark.parametrize("change,words", [
    (("members: [morning-brief, topic-watcher]", "members: [morning-brief]"), "2 to 12 members"),
    (("members: [morning-brief, topic-watcher]", "members: [morning-brief, morning-brief]"), "each once"),
    (("tagline: Two of them.", "tagline: Two of them.\nleader: morning-brief"), "nothing reads: leader"),
    (("id: pair", "id: Pair"), "lower-case words"),
])
def test_a_team_file_that_does_not_read_says_why(change, words):
    with pytest.raises(ManifestRefused, match=words):
        T.parse_team(TEAM.replace(*change))


def test_a_team_naming_an_agent_the_hall_lacks_is_listed_broken_not_offered(tmp_path):
    (tmp_path / "pair").mkdir()
    (tmp_path / "pair" / T.TEAM_FILE).write_text(TEAM)
    found, broken = T.teams(None, ["morning-brief"], shipped_root=str(tmp_path),
                            data_dir=str(tmp_path / "data"))
    assert found == []
    assert broken == [{"folder": "pair", "source": "shipped",
                       "sentence": "Pair names topic-watcher, which the hall does not have."}]


def test_the_teams_form_asks_a_shared_key_once():
    agents, _ = catalogue(None)
    by_id = {m.id: m for m in agents}
    team = next(t for t in T.teams(None, by_id)[0] if t.id == "code-health")
    keys = [i["key"] for i in T.team_inputs(team, by_id)]
    assert keys[:2] == ["folder", "test_command"] and keys.count("folder") == 1, \
        "five members ask for the repository; the form asks once"


def test_a_key_two_members_mean_differently_is_asked_of_each():
    """Morning Brief's `at` is when it arrives; Evening Wrap's is when it wraps
    up. One field would give both one time."""
    agents, _ = catalogue(None)
    by_id = {m.id: m for m in agents}
    team = next(t for t in T.teams(None, by_id)[0] if t.id == "chief-of-staff")
    fields = {i["key"]: i["label"] for i in T.team_inputs(team, by_id)}
    assert fields == {"at": "When it arrives", "evening-wrap.at": "Evening Wrap: When it wraps up",
                      "weekly-review.at": "Weekly Review: When it arrives on Fridays"}
    values = {"at": "06:30", "evening-wrap.at": "18:30"}
    assert T.member_values(team, by_id, "morning-brief", values) == {"at": "06:30"}
    assert T.member_values(team, by_id, "evening-wrap", values) == {"at": "18:30"}
    assert T.member_values(team, by_id, "weekly-review", values) == {}, "its own default stands"


# ── *Hire all* ──────────────────────────────────────────────────────────────

def test_hire_all_makes_one_hire_per_member_each_with_its_own_keys(client, wf_db):
    res = call(client, "POST", "/api/agents/teams/research-desk/hire",
               json={"inputs": {"topics": ["solar"], "at": "07:30", "companies": ["Acme, acme.example"],
                                "question": "What is new in perovskites?", "document": "Draft"}})
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["team"] == "Research Desk" and out["kept"] == []
    assert sorted(h["agent_id"] for h in out["hired"]) == [
        "competitor-tracker", "deep-researcher", "fact-checker", "paper-reader", "topic-watcher"]
    db = wf_db()
    import json
    inputs = {h.agent_id: json.loads(h.inputs) for h in db.query(AgentHire).all()}
    assert set(inputs["competitor-tracker"]) == {"companies"}, "a member is given only the keys it asks for"
    assert inputs["paper-reader"]["topics"] == ["solar"], "a shared key reaches every member that asks it"
    assert inputs["topic-watcher"]["topics"] == ["solar"]


def test_a_member_already_hired_is_kept_as_it_is(client, wf_db):
    call(client, "POST", "/api/agents/morning-brief/hire", json={"inputs": {"at": "05:00"}})
    res = call(client, "POST", "/api/agents/teams/chief-of-staff/hire", json={"inputs": {"at": "09:00"}})
    assert res.status_code == 200, res.text
    assert res.json()["kept"] == ["morning-brief"]
    db = wf_db()
    briefs = db.query(AgentHire).filter(AgentHire.agent_id == "morning-brief").all()
    assert len(briefs) == 1 and '"05:00"' in briefs[0].inputs
    wrap = db.query(AgentHire).filter(AgentHire.agent_id == "evening-wrap").one()
    assert '"09:00"' not in wrap.inputs, "the brief's time is not the wrap's"


def test_one_members_refusal_leaves_no_hire_behind(client, wf_db):
    res = call(client, "POST", "/api/agents/teams/research-desk/hire", json={"inputs": {"at": "07:30"}})
    assert res.status_code == 400
    assert res.json()["detail"].startswith("Topic Watcher: ")
    db = wf_db()
    assert db.query(AgentHire).count() == 0 and db.query(ScheduledTask).count() == 0


def test_the_hall_lists_teams_with_what_is_hired(client):
    call(client, "POST", "/api/agents/model-steward/hire", json={})
    data = call(client, "GET", "/api/agents").json()
    lab = next(t for t in data["teams"] if t["id"] == "model-lab")
    assert lab["hired"] == 1
    assert [m["hired"] for m in lab["members"]] == [True, False, False, False]
    assert data["broken_teams"] == []
    assert data["ceilings"] == {"paused": False, "max_concurrent": 2}


def test_only_a_person_hires_a_team(client, monkeypatch):
    import routes.agent_routes as agent_routes
    monkeypatch.setattr(agent_routes, "request_is_a_person", lambda request: False)
    res = call(client, "POST", "/api/agents/teams/home-lab/hire", json={})
    assert res.status_code == 403 and res.json()["detail"] == agent_routes.ONLY_A_PERSON


def test_an_unknown_team_is_a_sentence(client):
    res = call(client, "POST", "/api/agents/teams/no-such/hire", json={})
    assert res.status_code == 404 and res.json()["detail"] == "There is no team called that in the hall."


# ── *Try it once* ───────────────────────────────────────────────────────────

def test_try_makes_a_trial_and_starts_its_run_as_a_person(client, sched, wf_db):
    res = call(client, "POST", "/api/agents/morning-brief/try", json={"inputs": {"at": "06:00"}})
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["status"] == "trial" and out["started"] is True
    db = wf_db()
    task = db.query(ScheduledTask).one()
    assert sched.runs == [{"task_id": task.id, "dry": False, "started_by": "person", "trigger": None}]
    assert (task.status, task.trigger_type, task.webhook_token, task.next_run) == \
        ("active", "webhook", None, None)
    res = call(client, "POST", f"/api/agents/hires/{out['id']}/status", json={"status": "on"})
    assert res.status_code == 200 and res.json()["status"] == "on"
    db.expire_all()
    assert db.query(ScheduledTask).one().trigger_type == "schedule"


def test_a_refused_trial_starts_nothing(client, sched, wf_db):
    res = call(client, "POST", "/api/agents/topic-watcher/try", json={})
    assert res.status_code == 400
    assert sched.runs == [] and wf_db().query(AgentHire).count() == 0


def test_a_skipped_runs_reason_reaches_the_hires_page(client, wf_db):
    """The engine keeps a skipped run's sentence in `result`; the hire's page
    reads it as `said`, because such a run has no report and no error."""
    import uuid
    from core.database import TaskRun
    h = call(client, "POST", "/api/agents/model-steward/hire", json={}).json()
    db = wf_db()
    db.add(TaskRun(id=str(uuid.uuid4()), task_id=h["tasks"][0]["id"], status="skipped",
                   result="An admin has paused all agents."))
    db.add(TaskRun(id=str(uuid.uuid4()), task_id=h["tasks"][0]["id"], status="success", result="secret answer"))
    db.commit()
    runs = call(client, "GET", f"/api/agents/hires/{h['id']}").json()["runs"]
    assert sorted((r["status"], r["said"]) for r in runs) == [
        ("skipped", "An admin has paused all agents."), ("success", None)]
