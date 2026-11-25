# SPDX-License-Identifier: AGPL-3.0-or-later
"""A task's own chat is its owner's, and Apollo hears one line about it.

The outline's "Task chat": *Chat with this agent* opens the chat the task's
lead works in. Driven through the real `/api/apollo` router behind the real
sign-in stamp:

  * the chat opens only once the lead has started (409 in a sentence before),
    only for the task's owner (404 for anyone else's task), and never onto a
    chat someone else owns even if the task row points at it (403);
  * what the person tells the lead lands in their Apollo chat as one line, cut
    short, and nothing lands for a person with no Apollo chat yet;
  * the approvals a lead's scheduled run is parked on are listed for that
    task's owner alone, and only for Apollo's own tasks.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.apollo import chat as C
from src.apollo import tasks as T
from tests.helpers.apollo_db import apollo_db  # noqa: F401  (fixture)
from tests.helpers.signed_in import ADMIN, MEMBER, as_person, signed_in

NO_FIT = lambda owner, text: None  # noqa: E731


class _Sessions:
    """The one call `post_line` makes on the app's session manager."""

    def __init__(self):
        self.added = []

    def add_message(self, session_id, message):
        self.added.append((session_id, message.role, message.content, dict(message.metadata or {})))


@pytest.fixture
def world(apollo_db, tmp_path, monkeypatch):
    monkeypatch.setattr("src.apollo.goal_lead.write", lambda *a, **k: None)
    manager = signed_in(monkeypatch, tmp_path / "auth")
    sessions = _Sessions()
    import routes.apollo_routes as apollo_routes

    def client(who):
        app = as_person(FastAPI(), who, auth_manager=manager)
        app.state.session_manager = sessions
        app.include_router(apollo_routes.setup_apollo_routes())
        return TestClient(app)

    def chat_row(sid, owner):
        from core.database import Session as DbSession
        db = apollo_db()
        db.add(DbSession(id=sid, name=sid, endpoint_url="http://local", model="m", owner=owner))
        db.commit()
        db.close()

    def task(owner, title="Find a Saturday dentist", **cols):
        db = apollo_db()
        t = T.create(db, owner, title=title, pick=NO_FIT)
        for k, v in cols.items():
            setattr(t, k, v)
        db.commit()
        tid = t.id
        db.close()
        return tid

    def apollo_chat(owner, sid):
        from core.database import CrewMember
        chat_row(sid, owner)
        db = apollo_db()
        db.add(CrewMember(id=f"crew-{owner}", owner=owner, name="Apollo", session_id=sid,
                          is_default_assistant=True))
        db.commit()
        db.close()

    from types import SimpleNamespace
    return SimpleNamespace(client=client, chat_row=chat_row, task=task,
                           apollo_chat=apollo_chat, sessions=sessions, db=apollo_db)


def test_a_task_with_no_run_yet_says_its_chat_opens_once_the_lead_starts(world):
    tid = world.task(ADMIN)
    r = world.client(ADMIN).get(f"/api/apollo/tasks/{tid}/chat")
    assert r.status_code == 409
    assert r.json()["detail"] == C.NO_CHAT_YET


def test_the_owner_opens_the_chat_the_lead_works_in(world):
    world.chat_row("s-lead", ADMIN)
    tid = world.task(ADMIN, session_id="s-lead", lead_agent="researcher")
    r = world.client(ADMIN).get(f"/api/apollo/tasks/{tid}/chat")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["session_id"] == "s-lead" and body["lead_agent"] == "researcher"
    assert body["title"] == "Find a Saturday dentist"


def test_someone_elses_task_chat_is_not_found_and_a_chat_not_yours_stays_closed(world):
    world.chat_row("s-ada", ADMIN)
    tid = world.task(ADMIN, session_id="s-ada")
    r = world.client(MEMBER).get(f"/api/apollo/tasks/{tid}/chat")
    assert r.status_code == 404
    # Bob's own task row pointed at Ada's chat: refused, not opened.
    bobs = world.task(MEMBER, session_id="s-ada")
    r = world.client(MEMBER).get(f"/api/apollo/tasks/{bobs}/chat")
    assert r.status_code == 403
    assert r.json()["detail"] == "That task's chat isn't yours, so it stays closed."


def test_what_the_person_tells_the_lead_reaches_apollo_as_one_short_line(world):
    world.apollo_chat(ADMIN, "s-apollo")
    world.chat_row("s-lead", ADMIN)
    tid = world.task(ADMIN, session_id="s-lead")
    words = "Saturdays only, please. " * 20
    r = world.client(ADMIN).post(f"/api/apollo/tasks/{tid}/said", json={"words": words})
    assert r.status_code == 200, r.text
    assert r.json()["posted"] is True
    [(sid, role, line, meta)] = world.sessions.added
    assert sid == "s-apollo" and role == "assistant"
    assert line.startswith("You told the lead on “Find a Saturday dentist”: Saturdays only, please.")
    assert line.endswith("…") and len(line) < 220
    assert meta == {"source": "apollo", "apollo_task_id": str(tid), "kind": "task_chat"}


def test_nothing_lands_for_a_person_with_no_apollo_chat_and_empty_words_are_refused(world):
    world.chat_row("s-bob", MEMBER)
    tid = world.task(MEMBER, session_id="s-bob")
    bob = world.client(MEMBER)
    r = bob.post(f"/api/apollo/tasks/{tid}/said", json={"words": "Hello"})
    assert r.status_code == 200 and r.json()["posted"] is False
    assert world.sessions.added == []
    r = bob.post(f"/api/apollo/tasks/{tid}/said", json={"words": "   "})
    assert r.status_code == 400
    assert r.json()["detail"] == "Say something to the lead first."
    # A task whose lead hasn't started has no chat to have spoken in.
    quiet = world.task(MEMBER, title="Not started")
    assert bob.post(f"/api/apollo/tasks/{quiet}/said", json={"words": "Hi"}).status_code == 409
    # Another person's task takes no line either.
    ada_tid = world.task(ADMIN)
    assert bob.post(f"/api/apollo/tasks/{ada_tid}/said", json={"words": "Hi"}).status_code == 404


def test_a_leads_parked_approval_is_listed_for_its_owner_alone(world, monkeypatch):
    mine = world.task(ADMIN, hire_id="h-ada")
    world.task(MEMBER, hire_id="h-bob")
    done = world.task(ADMIN, title="Old one", hire_id="h-old", state="done")
    runs = {"h-ada": ["st-ada"], "h-bob": ["st-bob"], "h-old": ["st-old"]}
    monkeypatch.setattr("src.agents.hires.task_ids_of", lambda db, hire_id: runs.get(hire_id, []))
    parked = {
        ADMIN: [
            {"task_id": "st-ada", "run_id": "run-1", "tool_label": "send_email",
             "approval": {"approval_id": "ap-1", "description": "It writes outside Pantheon."}},
            {"task_id": "st-old", "run_id": "run-2", "tool_label": "x", "approval": {"approval_id": "ap-2"}},
            {"task_id": "st-elsewhere", "run_id": "run-3", "tool_label": "y", "approval": {"approval_id": "ap-3"}},
        ],
        MEMBER: [{"task_id": "st-bob", "run_id": "run-4", "tool_label": "z", "approval": {"approval_id": "ap-4"}}],
    }
    monkeypatch.setattr("src.task_scheduler.plain_waiting_list", lambda db, owner: parked.get(owner, []))
    got = world.client(ADMIN).get("/api/apollo/approvals").json()["approvals"]
    assert got == [{"task_id": mine, "title": "Find a Saturday dentist", "run_task_id": "st-ada",
                    "run_id": "run-1", "approval_id": "ap-1", "tool": "send_email",
                    "question": "Find a Saturday dentist: allow send_email?",
                    "why": "It writes outside Pantheon."}]
    assert done not in [a["task_id"] for a in got]
    bobs = world.client(MEMBER).get("/api/apollo/approvals").json()["approvals"]
    assert [a["approval_id"] for a in bobs] == ["ap-4"]
