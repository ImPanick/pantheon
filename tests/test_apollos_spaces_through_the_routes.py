# SPDX-License-Identifier: AGPL-3.0-or-later
"""Spaces through `/api/apollo`, as two people, and from Apollo's own tool.

Driven through the real router behind the real sign-in stamp. A space, its
context and its grants are its owner's alone (404 to anyone else, the same as
one that doesn't exist); a space's Activity reads that space; the All view
leaves out what's behind an airgap; a space's Apollo chat is made once; and
Apollo's tool, called from a space's chat, keeps what it makes in that space.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.apollo import knows, spaces as S
from tests.helpers.apollo_db import apollo_db  # noqa: F401  (fixture)
from tests.helpers.signed_in import ADMIN, MEMBER, as_person, signed_in


@pytest.fixture
def apollo_as(apollo_db, tmp_path, monkeypatch):
    from src.memory import MemoryManager
    (tmp_path / "brain").mkdir()
    monkeypatch.setattr(knows, "_manager", MemoryManager(str(tmp_path / "brain")))
    monkeypatch.setattr(knows, "_sealed", {})
    monkeypatch.setattr("src.apollo.goal_lead.write", lambda *a, **k: None)
    manager = signed_in(monkeypatch, tmp_path / "auth")
    import routes.apollo_routes as apollo_routes

    def client(who):
        app = as_person(FastAPI(), who, auth_manager=manager)
        app.include_router(apollo_routes.setup_apollo_routes())
        return TestClient(app)
    return client


def _apollo_chat(apollo_db, owner, sid="s-apollo"):
    from core.database import CrewMember, Session as DbSession
    db = apollo_db()
    db.add(DbSession(id=sid, name="Apollo", endpoint_url="http://localhost:11434", model="m", owner=owner))
    db.add(CrewMember(id=f"crew-{owner}", owner=owner, name="Apollo", session_id=sid,
                      is_default_assistant=True))
    db.commit()
    db.close()


def test_a_space_and_everything_on_it_is_its_makers_alone(apollo_as):
    ada, bob = apollo_as(ADMIN), apollo_as(MEMBER)
    r = ada.post("/api/apollo/spaces", json={"name": "CyberKnox"})
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    assert [s["name"] for s in ada.get("/api/apollo/spaces").json()["spaces"]] == ["CyberKnox"]
    assert bob.get("/api/apollo/spaces").json()["spaces"] == []
    for call in (lambda: bob.patch(f"/api/apollo/spaces/{sid}", json={"name": "mine"}),
                 lambda: bob.delete(f"/api/apollo/spaces/{sid}"),
                 lambda: bob.get(f"/api/apollo/spaces/{sid}/context"),
                 lambda: bob.post(f"/api/apollo/spaces/{sid}/grants", json={"source_id": sid, "scope": "memory"}),
                 lambda: bob.post(f"/api/apollo/spaces/{sid}/chat"),
                 lambda: bob.get(f"/api/apollo/tasks?space={sid}"),
                 lambda: bob.post("/api/apollo/tasks", json={"title": "x", "space_id": sid})):
        r = call()
        assert r.status_code == 404, r.text
        assert r.json()["detail"] == S.NOT_YOURS
    g = ada.post("/api/apollo/spaces", json={"name": "Home"}).json()["id"]
    gid = ada.post(f"/api/apollo/spaces/{sid}/grants", json={"source_id": g, "scope": "outcomes"}).json()["grant_id"]
    assert bob.delete(f"/api/apollo/grants/{gid}").status_code == 404
    assert ada.delete(f"/api/apollo/grants/{gid}").json() == {"revoked": True}


def test_activity_reads_one_space_and_all_leaves_the_airgapped_out(apollo_as):
    ada = apollo_as(ADMIN)
    work = ada.post("/api/apollo/spaces", json={"name": "CyberKnox"}).json()["id"]
    home = ada.post("/api/apollo/spaces", json={"name": "Home"}).json()["id"]
    ada.post("/api/apollo/tasks", json={"title": "Fix the gutter", "space_id": home, "start": False})
    ada.post("/api/apollo/tasks", json={"title": "SBIR budget", "space_id": work, "start": False})
    ada.post("/api/apollo/tasks", json={"title": "Call Mom", "start": False})
    titles = lambda q: sorted(t["title"] for t in ada.get(f"/api/apollo/tasks{q}").json()["tasks"])  # noqa: E731
    assert titles(f"?space={home}") == ["Fix the gutter"]
    assert titles("?space=top") == ["Call Mom"]
    assert titles("") == ["Call Mom", "Fix the gutter", "SBIR budget"]
    r = ada.patch(f"/api/apollo/spaces/{work}", json={"airgapped": True})
    assert r.json()["airgapped"] is True and r.json()["sealed"] is True
    assert titles("") == ["Call Mom", "Fix the gutter"]
    assert titles(f"?space={work}") == ["SBIR budget"]
    top = ada.get("/api/apollo/state?space=top").json()
    assert {k["name"]: k["sealed"] for k in top["children"]} == {"CyberKnox": True, "Home": False}


def test_what_apollo_knows_in_a_space_keeps_to_that_space(apollo_as):
    ada = apollo_as(ADMIN)
    home = ada.post("/api/apollo/spaces", json={"name": "Home"}).json()["id"]
    work = ada.post("/api/apollo/spaces", json={"name": "CyberKnox", "airgapped": True}).json()["id"]
    ada.post(f"/api/apollo/knows?space={home}", json={"text": "The boiler is in the garage"})
    line = ada.post(f"/api/apollo/knows?space={work}", json={"text": "The PI is Dr. Ito"}).json()
    assert [x["text"] for x in ada.get(f"/api/apollo/knows?space={home}").json()["lines"]] == [
        "The boiler is in the garage"]
    assert [x["text"] for x in ada.get("/api/apollo/knows").json()["lines"]] == ["The boiler is in the garage"]
    # A sealed line is reachable only from inside its edge.
    assert ada.delete(f"/api/apollo/knows/{line['id']}").status_code == 404
    assert ada.delete(f"/api/apollo/knows/{line['id']}?space={work}").json() == {"forgotten": True}


def test_a_spaces_apollo_chat_is_made_once_and_the_pin_needs_an_airgap(apollo_as, apollo_db):
    _apollo_chat(apollo_db, ADMIN)
    ada = apollo_as(ADMIN)
    work = ada.post("/api/apollo/spaces", json={"name": "CyberKnox"}).json()["id"]
    first = ada.post(f"/api/apollo/spaces/{work}/chat").json()["session_id"]
    assert ada.post(f"/api/apollo/spaces/{work}/chat").json()["session_id"] == first
    assert ada.post("/api/apollo/spaces/top/chat").json()["session_id"] == "s-apollo"
    r = ada.patch(f"/api/apollo/spaces/{work}", json={"local_only": True})
    assert r.status_code == 400
    r = ada.patch(f"/api/apollo/spaces/{work}", json={"airgapped": True, "local_only": True})
    assert r.json()["local_only"] is True
    ctx = ada.get(f"/api/apollo/spaces/{work}/context").json()
    assert ctx["reads_from"] == [] and ctx["read_by"] == []
    assert ada.delete(f"/api/apollo/spaces/{work}").json() == {"deleted": True}


def test_apollos_tool_keeps_what_it_makes_in_the_space_it_was_called_from(apollo_as, apollo_db):
    from src.apollo import tool
    _apollo_chat(apollo_db, ADMIN)
    ada = apollo_as(ADMIN)
    work = ada.post("/api/apollo/spaces", json={"name": "CyberKnox"}).json()["id"]
    home = ada.post("/api/apollo/spaces", json={"name": "Home"}).json()["id"]
    chat = ada.post(f"/api/apollo/spaces/{work}/chat").json()["session_id"]
    out, _run = tool.run_sync(ADMIN, {"action": "create_task", "title": "SBIR budget", "start": False}, chat)
    assert out["exit_code"] == 0 and out["task"]["space_id"] == work
    tool.run_sync(ADMIN, {"action": "note", "text": "Owe Sam the slides", "kind": "open_loop"}, chat)
    notes = ada.get(f"/api/apollo/notebook?space={work}").json()["notes"]
    assert [n["text"] for n in notes] == ["Owe Sam the slides"]
    # A task in a space beside it is out of this chat's reach.
    other = ada.post("/api/apollo/tasks", json={"title": "Fix the gutter", "space_id": home, "start": False}).json()
    out, _ = tool.run_sync(ADMIN, {"action": "update_task", "id": other["id"], "title": "x"}, chat)
    assert out["exit_code"] == 1 and "can't change" in out["error"]
    # Apollo's main chat is the top layer.
    out, _ = tool.run_sync(ADMIN, {"action": "create_task", "title": "Call Mom", "start": False}, "s-apollo")
    assert out["task"]["space_id"] is None
