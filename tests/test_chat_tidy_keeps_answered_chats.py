# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1781`. Tidy deleted chats the model had answered.

Tidy's Phase 1 (`POST /api/sessions/auto-sort` and `run_auto_sort`) deletes
empty chats and throwaways, and its dialog says what a throwaway is: *a test
name, or one message the model never answered*. The rules underneath went
further. A chat titled "New chat" (the title of every chat not yet named,
`P23-04`) or "Chat: …" was a throwaway by title alone, and so was any chat of
two messages whose first prompt was one to three words — "Explain quicksort"
and its answer. `run_auto_sort` added any chat of up to four messages whose
prompt was eight words or fewer, or whose text came to 250 characters.
Every one of those had an answer in it, and the deletion is permanent.

Now a chat the model answered is never a throwaway, and a title is no longer
evidence either way. The empty, Incognito, starred, recently-active and
archived rules are unchanged, and so is the throwaway rule for chats nobody
answered. Upstream Odysseus fixed the same defect in #6611 (1aff7183) by
deleting only empty and Incognito chats; that removes the throwaway half the
dialog promises, so it is not what this does.

Driven (`Law 20`): the real route and the real `run_auto_sort` over a real
SQLite file.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

import core.database as cdb
from core.database import ChatMessage as DbMessage
from core.database import Session as DbSession

LONG = ("Please compare these two approaches to caching the search results and tell me "
        "which one keeps memory use lower under load")

# name -> (messages as (role, text), extra columns). All are two hours old.
ANSWERED = {
    "kept-newchat": ("New chat", [("user", LONG), ("assistant", "The second one, because ...")]),
    "kept-quicksort": ("Quicksort", [("user", "Explain quicksort"),
                                     ("assistant", "Quicksort picks a pivot and ...")]),
    "kept-chatprefix": ("Chat: analysis", [("user", "Explain these results and retain the full answer"),
                                           ("assistant", "The results show ...")]),
    "kept-testname": ("Test", [("user", LONG), ("assistant", "Here is the comparison ...")]),
    "kept-opens-hi": ("Greeting then a question", [("user", "hi"), ("assistant", "Hello!"),
                                                   ("user", "What is a monad?"),
                                                   ("assistant", "A monad is ...")]),
}
UNANSWERED_LONG = {
    "kept-newchat-unanswered": ("New chat", [
        ("user", LONG),
        ("user", LONG + " and also whether the second approach needs a separate process"),
    ]),
}
THROWAWAYS = {
    "gone-empty": ("Old empty chat", []),
    "gone-incognito": ("Incognito", [("user", "secret question"), ("assistant", "answer")]),
    "gone-one-unanswered": ("Something", [("user", "a question nobody answered")]),
    "gone-hi-unanswered": ("Hi", [("user", "hi")]),
}


@pytest.fixture()
def db_factory(monkeypatch, tmp_path):
    import core.session_manager as smod
    import routes.session_routes as session_routes

    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}",
                           connect_args={"check_same_thread": False}, poolclass=NullPool)
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    for mod in (smod, session_routes, cdb):
        monkeypatch.setattr(mod, "SessionLocal", factory)
    monkeypatch.setattr(session_routes, "effective_user", lambda request: "alice")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    old = now - timedelta(hours=2)
    db = factory()

    def add(sid, name, messages, owner="alice", when=old, **extra):
        db.add(DbSession(id=sid, owner=owner, name=name, endpoint_url="x", model="m",
                         created_at=when, updated_at=when, last_accessed=when,
                         last_message_at=when, **extra))
        for i, (role, text) in enumerate(messages):
            db.add(DbMessage(id=f"{sid}-{i}", session_id=sid, role=role, content=text,
                             timestamp=when + timedelta(seconds=i)))

    for table in (ANSWERED, UNANSWERED_LONG, THROWAWAYS):
        for sid, (name, messages) in table.items():
            add(sid, name, messages)
    add("kept-fresh-empty", "Just opened", [], when=now)
    add("kept-starred-empty", "Starred", [], is_important=True)
    add("kept-archived", "Hi", [("user", "hi")], archived=True)
    add("kept-other-owner", "Hi", [("user", "hi")], owner="bob")
    db.commit()
    db.close()
    return factory


def _remaining(factory):
    db = factory()
    try:
        return {row.id for row in db.query(DbSession).all()}
    finally:
        db.close()


def _tidy_through_the_route(factory):
    import core.session_manager as smod
    import routes.session_routes as session_routes
    app = FastAPI()
    app.include_router(session_routes.setup_session_routes(smod.SessionManager(), {}))
    res = TestClient(app).post("/api/sessions/auto-sort?skip_llm=true")
    assert res.status_code == 200, res.text
    return res.json()


def _tidy_through_the_action(factory):
    from src.session_actions import run_auto_sort
    return asyncio.run(run_auto_sort("alice", skip_llm=True))


ENTRY_POINTS = [_tidy_through_the_route, _tidy_through_the_action]


@pytest.mark.parametrize("tidy", ENTRY_POINTS, ids=["route", "run_auto_sort"])
def test_a_chat_the_model_answered_is_never_a_throwaway(db_factory, tidy):
    tidy(db_factory)
    left = _remaining(db_factory)
    for sid in ANSWERED:
        assert sid in left, f"{sid} ({ANSWERED[sid][0]!r}) had an answer and was deleted"


@pytest.mark.parametrize("tidy", ENTRY_POINTS, ids=["route", "run_auto_sort"])
def test_a_title_alone_does_not_make_a_throwaway(db_factory, tidy):
    """'New chat' is the title of every chat not yet named."""
    tidy(db_factory)
    assert "kept-newchat-unanswered" in _remaining(db_factory)


@pytest.mark.parametrize("tidy", ENTRY_POINTS, ids=["route", "run_auto_sort"])
def test_what_the_dialog_names_is_still_deleted_and_nothing_else(db_factory, tidy):
    tidy(db_factory)
    left = _remaining(db_factory)
    for sid in THROWAWAYS:
        assert sid not in left, f"{sid} ({THROWAWAYS[sid][0]!r}) is what Tidy is for"
    for sid in ("kept-fresh-empty", "kept-starred-empty", "kept-archived", "kept-other-owner"):
        assert sid in left, sid


def test_the_route_counts_what_it_deleted(db_factory):
    body = _tidy_through_the_route(db_factory)
    assert body["deleted_empty"] == 1
    assert body["deleted_throwaway"] == 3
