# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every task Apollo answers with names the agent that leads it.

Apollo's deck shows who leads each goal on its card and on its board (the
owner's verdict on the first cut: "no tells that it spawned another agent").
The task routes add `lead_name` so the deck needs no lookup per card: the
agent's own name, "Apollo" for a task Apollo leads itself, and the id for a
lead the catalogue no longer has.
"""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.helpers.apollo_db import apollo_db  # noqa: F401  (fixture)
from tests.helpers.signed_in import ADMIN, as_person, signed_in

ROSTER = {"agent-mail": "Inbox Keeper"}


@pytest.fixture
def ada(apollo_db, tmp_path, monkeypatch):
    def write(owner, task_id, *, title, **k):
        return SimpleNamespace(id="agent-mail") if "mail" in title.lower() else None
    monkeypatch.setattr("src.apollo.goal_lead.write", write)
    monkeypatch.setattr("src.agents.catalogue.get_agent",
                        lambda owner, aid: SimpleNamespace(name=ROSTER[aid]) if aid in ROSTER else None)
    manager = signed_in(monkeypatch, tmp_path / "auth")
    import routes.apollo_routes as apollo_routes
    app = as_person(FastAPI(), ADMIN, auth_manager=manager)
    app.include_router(apollo_routes.setup_apollo_routes())
    return TestClient(app)


def test_a_goal_answers_with_its_leads_name_everywhere_it_is_read(ada):
    made = ada.post("/api/apollo/tasks", json={"title": "Sort my mail", "start": False}).json()
    assert made["lead_agent"] == "agent-mail" and made["lead_name"] == "Inbox Keeper"
    assert ada.get(f"/api/apollo/tasks/{made['id']}").json()["lead_name"] == "Inbox Keeper"
    listed = ada.get("/api/apollo/tasks").json()["tasks"]
    assert [(t["title"], t["lead_name"]) for t in listed] == [("Sort my mail", "Inbox Keeper")]


def test_a_goal_with_no_fit_is_led_by_apollo(ada):
    made = ada.post("/api/apollo/tasks", json={"title": "Plan the garden", "start": False}).json()
    assert made["lead_agent"] is None and made["lead_name"] == "Apollo"


def test_a_lead_the_catalogue_lost_keeps_its_id(ada, monkeypatch):
    made = ada.post("/api/apollo/tasks", json={"title": "Sort my mail", "start": False}).json()
    monkeypatch.setattr("src.agents.catalogue.get_agent", lambda owner, aid: None)
    assert ada.get(f"/api/apollo/tasks/{made['id']}").json()["lead_name"] == "agent-mail"
