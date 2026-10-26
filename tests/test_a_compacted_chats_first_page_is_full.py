# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1332` (fx7-dup) — `/api/history?limit=N` pages over the messages a reader
can see.

`total` and the newest page's offset were counted over every row, and the page
then dropped the `hidden` ones (a compaction's summary, kept for the model). So
a compacted chat's first page came back a message short (23 for a `limit=24`
ask), `total` was one more than anything would ever be drawn, and the
older-page walk in `sessions.js` (`offset - limit`) counted in a space the
browser never saw. Now `offset`, `total` and `has_more_*` are all in the
displayed space.

Driven: the real route over a real SQLite file holding a compacted chat — the
four kept messages, the hidden summary and the visible marker as
`POST /api/session/{id}/compact` writes them, then the chat going on — and the
browser's own walk (`nextOffset = offset - limit`, `sessions.js`).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

import core.database as cdb
from core.database import ChatMessage as DbMessage
from core.database import Session as DbSession


@pytest.fixture()
def client(monkeypatch, tmp_path):
    import core.session_manager as smod
    import routes.history_routes as history_routes
    import routes.session_routes as session_routes

    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}", connect_args={"check_same_thread": False},
                           poolclass=NullPool)
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    for mod in (smod, session_routes, history_routes):
        monkeypatch.setattr(mod, "SessionLocal", factory)
    db = factory()
    db.add(DbSession(id="c1", owner="ann", name="a chat", endpoint_url="x", model="m"))
    t = datetime(2026, 1, 1)
    rows = [("user", "kept 1", None), ("assistant", "kept 2", None), ("user", "kept 3", None),
            ("assistant", "kept 4", None),
            ("system", "[Conversation summary — 20 earlier messages were compacted]\n\n…",
             {"compacted": True, "hidden": True}),
            ("assistant", "**Chat compacted** — 20 messages summarized, 4 kept.",
             {"compacted": True, "messages_removed": 20})]
    # A message that only mentions the word stays a message.
    rows += [("user" if i % 2 == 0 else "assistant", f"later {i}",
              {"note": "the \"hidden\" word, not the flag"} if i == 0 else None) for i in range(20)]
    for i, (role, content, meta) in enumerate(rows):
        db.add(DbMessage(id=f"r{i:02d}", session_id="c1", role=role, content=content,
                         meta_data=json.dumps(meta) if meta else None, timestamp=t + timedelta(seconds=i)))
    db.commit()
    db.close()
    monkeypatch.setattr(session_routes, "effective_user", lambda request: "ann")
    app = FastAPI()
    app.include_router(history_routes.setup_history_routes(smod.SessionManager()))
    return TestClient(app)


def test_the_first_page_is_full_and_counts_what_is_drawn(client):
    page = client.get("/api/history/c1?limit=24").json()
    assert len(page["history"]) == 24
    assert page["total"] == 25, "the hidden summary is counted"
    assert page["offset"] == 1 and page["has_more_before"] is True and page["has_more_after"] is False
    assert not [e for e in page["history"] if (e.get("metadata") or {}).get("hidden")]
    assert "later 0" in [e["content"] for e in page["history"]], "a mention of the word is not the flag"
    assert page["history"][-1]["content"] == "later 19"


def test_the_load_earlier_walk_reaches_the_first_message_once_each(client):
    """`sessions.js`'s own arithmetic: `nextOffset = max(0, offset - limit)`,
    `nextLimit = offset - nextOffset`, until `has_more_before` is false."""
    page = client.get("/api/history/c1?limit=24").json()
    drawn = [e["content"] for e in page["history"]]
    offset, limit = page["offset"], page["limit"]
    while page["has_more_before"]:
        next_offset = max(0, offset - limit)
        page = client.get(f"/api/history/c1?limit={offset - next_offset}&offset={next_offset}").json()
        drawn = [e["content"] for e in page["history"]] + drawn
        offset = page["offset"]
    assert drawn[0] == "kept 1"
    assert len(drawn) == len(set(drawn)) == 25
    assert not any(c.startswith("[Conversation summary") for c in drawn)
