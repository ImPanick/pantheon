# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B642`: `POST /api/compare/record` stores a verdict or refuses.

`RecordVoteRequest.winner` was a bare `str`, so `winner: ""` validated and the
route wrote a row with `voted_at` set and no winner — a comparison that reads as
never voted on while carrying a vote's timestamp. This drives the real route
over a real temp SQLite and reads `/history` back.
"""
import os

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.database import Base
from tests.helpers.sqlite_db import make_temp_sqlite


def _client(monkeypatch):
    import routes.compare.compare_routes as cr
    SessionLocal, engine, tmp = make_temp_sqlite(Base.metadata)
    monkeypatch.setattr(cr, "SessionLocal", SessionLocal)
    monkeypatch.setattr(cr, "get_current_user", lambda request: "alice")
    app = FastAPI()
    app.include_router(cr.setup_compare_routes(session_manager=None))
    return TestClient(app), (engine, tmp)


def _vote(client, **over):
    body = {"prompt": "which is better?", "models": ["llama", "qwen"], "winner": "llama"}
    body.update(over)
    return client.post("/api/compare/record", json=body)


def test_an_empty_winner_is_refused_and_nothing_is_stored(monkeypatch):
    client, keep = _client(monkeypatch)
    try:
        r = _vote(client, winner="")
        assert r.status_code == 422, r.text
        assert "winner is one of the models it compared" in r.text
        assert client.get("/api/compare/history").json() == [], \
            "a refused vote must leave no row behind"
    finally:
        os.unlink(keep[1].name)


def test_a_winner_the_comparison_did_not_include_is_refused(monkeypatch):
    client, keep = _client(monkeypatch)
    try:
        assert _vote(client, winner="mistral").status_code == 422
        assert _vote(client, models=[], winner="tie").status_code == 422, \
            "a vote naming no models has nothing a winner could be"
        assert client.get("/api/compare/history").json() == []
    finally:
        os.unlink(keep[1].name)


def test_a_named_winner_and_a_tie_are_stored_and_every_voted_row_has_a_verdict(monkeypatch):
    client, keep = _client(monkeypatch)
    try:
        assert _vote(client, winner="qwen").status_code == 200
        assert _vote(client, models=["a", "b", "c"], winner="c").status_code == 200
        assert _vote(client, winner="tie").status_code == 200
        _vote(client, winner="")
        rows = client.get("/api/compare/history").json()
        assert sorted(r["winner"] for r in rows) == ["c", "qwen", "tie"]
        assert all(r["winner"] for r in rows if r["voted_at"]), \
            "no row may carry voted_at without a verdict"
    finally:
        os.unlink(keep[1].name)
