# SPDX-License-Identifier: AGPL-3.0-or-later
"""Apollo is each person's own (his rule: instances and users fully separate).

Driven through the real `/api/apollo` router behind the real sign-in stamp, as
two people. What one keeps (a task, a note, a line of what Apollo knows) the
other can neither list nor open nor change, and a thing that isn't yours
answers the same 404 as one that doesn't exist.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.apollo import knows
from tests.helpers.apollo_db import apollo_db  # noqa: F401  (fixture)
from tests.helpers.signed_in import ADMIN, MEMBER, as_person, signed_in


@pytest.fixture
def apollo_as(apollo_db, tmp_path, monkeypatch):
    from src.memory import MemoryManager
    (tmp_path / "brain").mkdir()
    monkeypatch.setattr(knows, "_manager", MemoryManager(str(tmp_path / "brain")))
    # No roster in a test: every goal is led by Apollo itself.
    monkeypatch.setattr("src.apollo.lead.pick_lead", lambda owner, text, **k: None)
    manager = signed_in(monkeypatch, tmp_path / "auth")
    import routes.apollo_routes as apollo_routes

    def client(who):
        app = as_person(FastAPI(), who, auth_manager=manager)
        app.include_router(apollo_routes.setup_apollo_routes())
        return TestClient(app)
    return client


def test_a_task_is_its_makers_alone(apollo_as):
    ada, bob = apollo_as(ADMIN), apollo_as(MEMBER)
    r = ada.post("/api/apollo/tasks", json={"title": "Plan the Juneau trip"})
    assert r.status_code == 200, r.text
    tid = r.json()["id"]
    assert [t["id"] for t in ada.get("/api/apollo/tasks").json()["tasks"]] == [tid]
    assert bob.get("/api/apollo/tasks").json()["tasks"] == []
    for call in (lambda: bob.get(f"/api/apollo/tasks/{tid}"),
                 lambda: bob.patch(f"/api/apollo/tasks/{tid}", json={"title": "mine now"}),
                 lambda: bob.post(f"/api/apollo/tasks/{tid}/answer", json={"answer": "yes"}),
                 lambda: bob.post(f"/api/apollo/tasks/{tid}/start")):
        r = call()
        assert r.status_code == 404, r.text
        assert r.json()["detail"] == "That task isn't one of yours."
    assert ada.get(f"/api/apollo/tasks/{tid}").json()["title"] == "Plan the Juneau trip"


def test_a_note_is_its_keepers_alone(apollo_as, apollo_db):
    from contextlib import contextmanager

    @contextmanager
    def _db():
        db = apollo_db()
        try:
            yield db
        finally:
            db.close()

    ada, bob = apollo_as(ADMIN), apollo_as(MEMBER)
    from src.apollo import notebook
    with _db() as db:
        nid = notebook.add(db, ADMIN, "Owe Sam the slides", kind="open_loop").id
        db.commit()
    assert bob.get("/api/apollo/notebook").json()["notes"] == []
    assert bob.patch(f"/api/apollo/notebook/{nid}", json={"state": "dropped"}).status_code == 404
    loops = ada.get("/api/apollo/state").json()["open_loops"]
    assert [n["id"] for n in loops] == [nid]


def test_what_apollo_knows_about_one_person_is_not_shown_to_another(apollo_as):
    ada, bob = apollo_as(ADMIN), apollo_as(MEMBER)
    r = ada.post("/api/apollo/knows", json={"text": "Never book me before 10"})
    assert r.status_code == 200, r.text
    line = r.json()
    assert line["basis"] == "stated"
    assert bob.get("/api/apollo/knows").json()["lines"] == []
    assert bob.delete(f"/api/apollo/knows/{line['id']}").status_code == 404
    assert bob.patch(f"/api/apollo/knows/{line['id']}", json={"text": "x"}).status_code == 404
    assert [x["id"] for x in ada.get("/api/apollo/knows").json()["lines"]] == [line["id"]]


def test_what_a_person_types_on_the_page_is_stated_never_inferred(apollo_as):
    ada = apollo_as(ADMIN)
    r = ada.post("/api/apollo/knows", json={"text": "Prefers aisle seats", "basis": "inferred"})
    assert r.json()["basis"] == "stated"


def test_forget_means_gone(apollo_as):
    ada = apollo_as(ADMIN)
    lid = ada.post("/api/apollo/knows", json={"text": "Has a dog named Pip"}).json()["id"]
    assert ada.delete(f"/api/apollo/knows/{lid}").json() == {"forgotten": True}
    assert ada.get("/api/apollo/knows").json()["lines"] == []


def test_a_budget_over_the_admins_cap_is_refused_in_a_sentence(apollo_as, monkeypatch):
    from src.apollo import budget as B
    monkeypatch.setattr(B, "admin_cap", lambda settings=None: 1_000)
    r = apollo_as(MEMBER).post("/api/apollo/tasks", json={"title": "Big job", "budget_tokens": 5_000})
    assert r.status_code == 400
    assert r.json()["detail"].endswith(".")


def test_nobody_signed_in_gets_nothing(apollo_as):
    r = apollo_as(None).get("/api/apollo/tasks")
    assert r.status_code in (401, 403)
