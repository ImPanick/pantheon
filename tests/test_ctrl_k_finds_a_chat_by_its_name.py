# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1249` — Ctrl+K finds a chat by its name.

Measured on `299bd50`: Ctrl+K → *What the survey says* (the chat's title) → no
rows; *loose* (from *File the loose documents*) → no rows. The palette's chat
lane was `/api/search` alone, and `src/session_search.py` matches what was said
in a chat (`chat_messages`), never `sessions.name` — so a chat named by hand or
by the auto-namer was found only through a word that happened to be in one of
its messages.

Now `/api/search?chats=1` answers the chats whose name holds every word typed
as well (`search_session_titles`, under the message search's own owner rule),
and the palette draws them first, as **Chats**, ahead of the message hits — a
chat found by name is not offered again under its messages. `/find` asks
without `chats=1` and gets the list it always got.

Driven (`Law 20`): the real chat router over a real SQLite database, signed in
as one person beside another person's chat with the same words in its name;
and the real palette (`P9-01`'s sandbox) answered the way that route answers.
"""

import shutil
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.database import Base, ChatMessage as DbMessage, Session as DbSession
from routes import chat_routes

from test_the_search_box_is_the_command_palette_js import _chats, _palette, box  # noqa: E402,F401


@pytest.fixture
def client(monkeypatch):
    import src.session_search as session_search

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    db = factory()
    for sid, name, owner, archived in (
        ("s-survey", "What the survey says", "alice", False),
        ("s-loose", "File the loose documents", "alice", False),
        ("s-old", "What the survey said in March", "alice", True),
        ("s-bob", "What the survey says about Bob", "bob", False),
        ("s-ghost", "Nobody", "alice", False),
    ):
        db.add(DbSession(id=sid, name=name, owner=owner, archived=archived,
                         endpoint_url="http://m.test/v1", model="m"))
        db.add(DbMessage(id=sid + "-m", session_id=sid, role="user", content="hello there"))
    db.commit()
    db.close()
    monkeypatch.setattr(session_search, "SessionLocal", factory)
    app = FastAPI()

    @app.middleware("http")
    async def _person(request, call_next):
        request.state.current_user = "alice"
        return await call_next(request)

    app.include_router(chat_routes.setup_chat_routes(*(SimpleNamespace() for _ in range(6))))
    return TestClient(app)


def test_a_chat_is_found_by_the_words_of_its_name(client):
    whole = client.get("/api/search", params={"q": "What the survey", "chats": 1}).json()
    assert [c["session_name"] for c in whole["chats"]] == ["What the survey says"]
    assert whole["results"] == [], "no message says it — the name is the only way in"
    loose = client.get("/api/search", params={"q": "loose", "chats": 1}).json()
    assert [c["session_id"] for c in loose["chats"]] == ["s-loose"]
    # Every word, in any order, case aside.
    assert [c["session_id"] for c in client.get(
        "/api/search", params={"q": "SURVEY what", "chats": 1}).json()["chats"]] == ["s-survey"]


def test_another_persons_archived_or_hidden_chat_is_not_found(client):
    names = [c["session_name"] for c in client.get(
        "/api/search", params={"q": "survey", "chats": 1}).json()["chats"]]
    assert names == ["What the survey says"], "Bob's chat, an archived one, or a hidden one leaked"
    assert client.get("/api/search", params={"q": "Nobody", "chats": 1}).json()["chats"] == []


def test_find_still_gets_the_list_it_always_got(client):
    assert isinstance(client.get("/api/search", params={"q": "hello"}).json(), list)


@pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")
def test_the_palette_offers_the_chat_by_its_name_first(box):  # noqa: F811
    out = _palette(box, """
        answer('What the survey', { status: 200,
          chats: [{ session_id: 's-survey', session_name: 'What the survey says', last_active: null }],
          body: [row('s-survey', 'What the survey says', 'what the survey asked'),
                 row('s-notes', 'Notes', 'what the survey covers')] });
        open(); type('What the survey');
        await chatsArrive();
        const found = read();
        enter();
        console.log(JSON.stringify({ found, after: read() }));
    """)
    chats = _chats(out["found"]["groups"])
    assert chats[0]["label"] == "Chats"
    assert [o["label"] for o in chats[0]["options"]] == ["What the survey says"]
    assert chats[0]["options"][0]["marks"] == ["What the survey"]
    # Its message hit is not offered a second time; another chat's still is.
    assert [g["label"] for g in chats[1:]] == ["Notes"]
    assert out["found"]["active"].startswith("What the survey says")
    assert out["after"]["selected"] == ["s-survey"] and out["after"]["open"] is False
