# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P24-03` / `P24-04` — a hire is one row, owner-scoped, and it compiles to
the task engine's own tasks.

Driven through the real `routes/agent_routes.py` and the real task routes,
through `TestClient`, on a real SQLite file with its foreign keys on, against
the real shipped manifests. The scheduler is the Workbench tests' recorder
(imported, `Law 14`): nothing here runs a model; `P24-05`'s file does that.

**Measured before this file, on `a28041c`:** every path below answered 404 —
there was no `/api/agents`.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.test_a_workflow_is_kept_as_one_document import (  # noqa: F401  (fixtures)
    admins, sched, wf_db,
)
from core.database import AgentHire, AgentHireTask, ScheduledTask


@pytest.fixture()
def client(wf_db, sched, admins, monkeypatch, tmp_path):
    import routes.agent_routes as agent_routes
    import routes.task.task_routes as task_routes
    import routes.prefs_routes as prefs
    import src.constants as constants
    import src.task_action_policy as tap
    import src.tool_security as ts
    monkeypatch.setattr(task_routes, "SessionLocal", wf_db)
    monkeypatch.setattr(agent_routes, "SessionLocal", wf_db)
    monkeypatch.setattr(task_routes, "record_admin_refusal", tap.record_admin_refusal)
    monkeypatch.setattr(prefs, "_load_for_user", lambda user=None: {})
    monkeypatch.setattr(constants, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(ts, "owner_is_admin", lambda owner: owner in admins)
    import src.workstation_access as wa
    monkeypatch.setattr(wa, "may_use", lambda owner, **kw: owner in admins)
    app = FastAPI()

    @app.middleware("http")
    async def _who(request, call_next):
        request.state.current_user = request.headers.get("x-test-user")
        return await call_next(request)

    app.include_router(agent_routes.setup_agent_routes())
    app.include_router(task_routes.setup_task_routes(sched))
    return TestClient(app)


def call(client, method, url, user="alice", **kw):
    return client.request(method, url, headers={"x-test-user": user, **kw.pop("headers", {})}, **kw)


def hire(client, agent="morning-brief", user="alice", **body):
    res = call(client, "POST", f"/api/agents/{agent}/hire", user=user, json=body)
    assert res.status_code == 200, res.text
    return res.json()


def tasks_of(wf_db, hire_id):
    db = wf_db()
    try:
        links = db.query(AgentHireTask).filter(AgentHireTask.hire_id == hire_id).order_by(
            AgentHireTask.trigger).all()
        return [db.query(ScheduledTask).get(l.task_id) for l in links]
    finally:
        db.close()


# ── the catalogue ───────────────────────────────────────────────────────────

def test_everyone_sees_the_whole_catalogue_in_sections(client):
    alice = call(client, "GET", "/api/agents").json()
    bob = call(client, "GET", "/api/agents", user="bob").json()
    assert [a["id"] for a in alice["agents"]] == [a["id"] for a in bob["agents"]]
    assert len(alice["agents"]) == 173 and alice["broken"] == []    # 18 starters + wave 2 (`P24-23`)
    sections = {s["id"]: s for s in alice["sections"]}
    assert len(sections) == 26
    assert sections["email"]["count"] == 9 and sections["email"]["label"] == "Email & Inbox"
    assert sum(s["count"] for s in alice["sections"]) == 173
    assert [f["label"] for f in alice["families"]] == ["Everyday", "Knowledge", "Engineering", "Business"]
    brief = next(a for a in alice["agents"] if a["id"] == "morning-brief")
    # `P24-27`: a runbook opens with the job in a sentence, then its sections.
    assert brief["starts_on"] == "daily at 07:30" and "## Steps" in brief["runbook"]


def test_one_agent_says_what_a_non_admin_will_lack(client, admins):
    admins.add("alice")
    mine = call(client, "GET", "/api/agents/site-builder").json()
    theirs = call(client, "GET", "/api/agents/site-builder", user="bob").json()
    assert mine["lacking"] == []
    assert {"bash", "computer"} <= {x["tool"] for x in theirs["lacking"]}
    assert all(x["reason"] for x in theirs["lacking"])
    assert mine["effects"]["execute_code"] == "allow" and mine["effects"]["network_egress"] == "ask"
    assert call(client, "GET", "/api/agents/no-such-agent").json() == {
        "detail": "There is no agent called that in the hall."}


# ── a hire compiles to tasks ────────────────────────────────────────────────

def test_a_hire_is_one_task_per_trigger_in_the_persons_zone(client, wf_db):
    h = hire(client, inputs={"at": "06:45"}, tz_name="Australia/Sydney")
    # `P24-27` moved the file's version; the hire is at whatever the file says.
    from src.agents.catalogue import get_agent
    assert (h["status"], h["agent_id"], h["version"], h["starts_on"]) == (
        "on", "morning-brief", get_agent(None, "morning-brief").version, "daily at 06:45")
    [task] = tasks_of(wf_db, h["id"])
    assert (task.task_type, task.trigger_type, task.schedule, task.cron_expression) == (
        "llm", "schedule", "cron", "45 6 * * *")
    assert (task.tz_name, task.status, task.owner, task.name) == (
        "Australia/Sydney", "active", "alice", "Morning Brief")
    assert task.next_run is not None
    assert (task.max_steps, task.timeout_seconds) == (15, 8 * 60)


def test_each_kind_of_trigger_compiles_to_its_task(client, wf_db):
    inbox = hire(client, "inbox-triage")
    event, weekday = tasks_of(wf_db, inbox["id"])
    assert (event.trigger_type, event.trigger_event, event.trigger_count) == ("event", "email_received", 5)
    assert weekday.cron_expression == "0 8 * * 1-5"
    assert event.name == "Inbox Triage · new mail" and weekday.name == "Inbox Triage · weekdays at 08:00"
    review = tasks_of(wf_db, hire(client, "weekly-review")["id"])[0]
    assert review.cron_expression == "0 16 * * 5"
    by_hand = tasks_of(wf_db, hire(client, "proofreader", inputs={"document": "Plan"})["id"])[0]
    assert by_hand.trigger_type == "webhook" and by_hand.webhook_token and by_hand.next_run is None
    hourly = tasks_of(wf_db, hire(client, "server-health", inputs={"hosts": "nas, pi"})["id"])[0]
    assert hourly.cron_expression == "7 * * * *"


def test_a_hire_checks_what_it_is_given_before_writing_anything(client, wf_db):
    cases = [
        ("topic-watcher", {}, "“Topics to watch” needs an answer."),
        ("morning-brief", {"inputs": {"at": "7.30"}}, "“When it arrives” is not a time like 07:30."),
        ("morning-brief", {"inputs": {"mood": "sunny"}}, "Morning Brief does not ask for “mood”."),
        ("morning-brief", {"tz_name": "Mars/Olympus"}, "Not a timezone this machine knows"),
        ("morning-brief", {"grants": {"execute_code": "allow"}},
         "Morning Brief's tools never have the effect “execute_code”."),
        ("notes-gardener", {"grants": {"read_private": "maybe"}}, "can only be allow, ask or never"),
        ("site-builder", {"inputs": {"brief": "x", "folder": "../etc"}},
         "is a folder inside your projects folder"),
        ("site-builder", {"inputs": {"brief": "x"}, "project": "nope"},
         "There is no project called “nope” in your projects folder."),
    ]
    for agent, body, sentence in cases:
        res = call(client, "POST", f"/api/agents/{agent}/hire", json=body)
        assert res.status_code == 400 and sentence in res.json()["detail"], (agent, res.text)
    db = wf_db()
    try:
        assert db.query(AgentHire).count() == 0 and db.query(ScheduledTask).count() == 0
    finally:
        db.close()


def test_a_hire_may_only_tighten_except_ask_to_allow(client):
    gardener = call(client, "GET", "/api/agents/notes-gardener").json()
    assert gardener["effects"]["destructive"] == "ask" and gardener["effects"]["write_private"] == "allow"
    h = hire(client, "notes-gardener", grants={"destructive": "allow", "write_private": "ask"})
    assert h["effects"]["destructive"] == "allow" and h["effects"]["write_private"] == "ask"
    h2 = hire(client, "notes-gardener", grants={"read_private": "never"})
    assert h2["effects"]["read_private"] == "never"
    res = call(client, "PUT", f"/api/agents/hires/{h2['id']}", json={"grants": {"read_private": "allow",
                                                                               "write_private": "never"}})
    assert res.status_code == 200          # read_private back to the file's allow is not loosening
    hold = call(client, "POST", "/api/agents/model-steward/hire", json={})
    assert hold.status_code == 200
    res = call(client, "POST", "/api/agents/inbox-triage/hire",
               json={"grants": {"external_side_effect": "allow"}})
    assert res.status_code == 400 and "never have the effect" in res.json()["detail"]


def test_pause_resume_change_and_fire(client, wf_db):
    h = hire(client)
    [task] = tasks_of(wf_db, h["id"])
    paused = call(client, "POST", f"/api/agents/hires/{h['id']}/status", json={"status": "paused"}).json()
    assert paused["status"] == "paused" and paused["next_run"] is None
    assert tasks_of(wf_db, h["id"])[0].status == "paused"
    on = call(client, "POST", f"/api/agents/hires/{h['id']}/status", json={"status": "on"}).json()
    assert on["status"] == "on" and on["next_run"]
    changed = call(client, "PUT", f"/api/agents/hires/{h['id']}",
                   json={"inputs": {"at": "05:10"}, "name": "Early brief"}).json()
    [same] = tasks_of(wf_db, h["id"])
    assert same.id == task.id, "a change recompiles in place, keeping the task's runs"
    assert same.cron_expression == "10 5 * * *" and same.name == "Early brief"
    assert changed["starts_on"] == "daily at 05:10"
    fired = call(client, "DELETE", f"/api/agents/hires/{h['id']}").json()
    assert fired == {"ok": True, "fired": "Early brief", "tasks_removed": 1}
    db = wf_db()
    try:
        assert db.query(ScheduledTask).filter(ScheduledTask.id == task.id).first() is None
        assert db.query(AgentHireTask).count() == 0
    finally:
        db.close()


# ── whose a hire is ─────────────────────────────────────────────────────────

def test_a_hire_is_its_persons_and_an_admin_watches_everyones(client, admins):
    mine = hire(client)
    assert call(client, "GET", "/api/agents", user="bob").json()["hires"] == []
    for method, url, body in [("GET", f"/api/agents/hires/{mine['id']}", None),
                              ("PUT", f"/api/agents/hires/{mine['id']}", {"name": "x"}),
                              ("POST", f"/api/agents/hires/{mine['id']}/status", {"status": "paused"}),
                              ("DELETE", f"/api/agents/hires/{mine['id']}", None)]:
        res = call(client, method, url, user="bob", json=body)
        assert res.status_code == 404 and res.json() == {"detail": "There is no such hire."}, (method, url)
    admins.add("root")
    everyone = call(client, "GET", "/api/agents?everyone=1", user="root").json()
    assert everyone["everyone"] is True and [h["owner"] for h in everyone["hires"]] == ["alice"]
    assert call(client, "GET", "/api/agents?everyone=1", user="bob").json()["everyone"] is False
    assert call(client, "GET", f"/api/agents/hires/{mine['id']}", user="root").status_code == 200
    res = call(client, "PUT", f"/api/agents/hires/{mine['id']}", user="root", json={"name": "x"})
    assert res.status_code == 403 and "summoned by someone else" in res.json()["detail"]
    paused = call(client, "POST", f"/api/agents/hires/{mine['id']}/status", user="root",
                  json={"status": "paused"})
    assert paused.status_code == 200
    res = call(client, "POST", f"/api/agents/hires/{mine['id']}/status", user="root", json={"status": "on"})
    assert res.status_code == 403
    assert call(client, "DELETE", f"/api/agents/hires/{mine['id']}", user="root").json()["ok"] is True


def test_only_a_person_hires_changes_or_fires(client):
    from core.middleware import INTERNAL_TOOL_HEADER
    h = hire(client)
    loop = {INTERNAL_TOOL_HEADER: "x"}
    for method, url in [("POST", "/api/agents/morning-brief/hire"),
                        ("PUT", f"/api/agents/hires/{h['id']}"),
                        ("POST", f"/api/agents/hires/{h['id']}/status"),
                        ("DELETE", f"/api/agents/hires/{h['id']}")]:
        res = call(client, method, url, json={}, headers=loop)
        assert res.status_code == 403 and "Only a person" in res.json()["detail"], (method, url)


# ── the Tasks window ────────────────────────────────────────────────────────

def test_the_tasks_window_labels_an_agents_task_and_sends_its_changes_to_agents(client, wf_db):
    h = hire(client)
    [task] = tasks_of(wf_db, h["id"])
    listed = call(client, "GET", "/api/tasks").json()["tasks"]
    row = next(t for t in listed if t["id"] == task.id)
    assert row["agent"] == {"hire_id": h["id"], "name": "Morning Brief", "agent_id": "morning-brief"}
    for method, url, body in [("PUT", f"/api/tasks/{task.id}", {"name": "mine now"}),
                              ("DELETE", f"/api/tasks/{task.id}", None),
                              ("POST", f"/api/tasks/{task.id}/pause", None),
                              ("POST", f"/api/tasks/{task.id}/resume", None)]:
        res = call(client, method, url, json=body)
        assert res.status_code == 409, (method, url, res.text)
        assert res.json()["detail"] == ("“Morning Brief” is how the agent Morning Brief runs. Change, "
                                        "pause or dismiss it in Agents; Run now works here too.")
    res = call(client, "POST", f"/api/tasks/{task.id}/run", json={})
    assert res.status_code == 200, res.text


def test_an_update_to_the_file_waits_for_the_person(client, wf_db, monkeypatch):
    import src.agents.catalogue as C
    from dataclasses import replace
    h = hire(client)
    real = C.get_agent

    def newer(owner, agent_id, **kw):
        m = real(owner, agent_id, **kw)
        # `P24-27`: a version the shipped file has not reached (it is 1.1.0 now).
        return replace(m, version="9.9.9") if m is not None else None

    import routes.agent_routes as agent_routes
    monkeypatch.setattr(agent_routes, "get_agent", newer)
    res = call(client, "PUT", f"/api/agents/hires/{h['id']}", json={"name": "x"})
    assert res.status_code == 409 and "Update it first" in res.json()["detail"]
    shown = call(client, "GET", f"/api/agents/hires/{h['id']}").json()
    assert shown["update_to"] == "9.9.9"
    updated = call(client, "PUT", f"/api/agents/hires/{h['id']}", json={"update": True}).json()
    assert updated["version"] == "9.9.9" and updated["update_to"] is None


def test_a_file_that_says_never_cannot_be_loosened_by_a_hire(client, tmp_path):
    """Only `ask` → `allow` loosens (`D-2026-10-22-01` §3); `never` stays the
    file's, whatever the hire form sends."""
    import os
    from src.agents.catalogue import own_root
    root = os.path.join(own_root("alice", str(tmp_path)), "careful-reader")
    os.makedirs(root)
    with open(os.path.join(root, "AGENT.md"), "w", encoding="utf-8") as fh:
        fh.write("---\nid: careful-reader\nname: Careful Reader\ntagline: Reads, never fetches.\n"
                 "section: research\nversion: 1.0.0\ntriggers:\n  - {on: hand}\n"
                 "tools: [web_search, web_fetch]\neffects: {network_egress: never}\nmemory: none\n---\n"
                 "1. Search for the topic and say what you found, with the source.\n")
    for loosened in ("ask", "allow"):
        res = call(client, "POST", "/api/agents/careful-reader/hire",
                   json={"grants": {"network_egress": loosened}})
        assert res.status_code == 400, res.text
        assert res.json()["detail"] == ("Careful Reader says “network_egress” is never; you can "
                                        "make that stricter, not looser.")
    assert call(client, "POST", "/api/agents/careful-reader/hire", json={}).status_code == 200
