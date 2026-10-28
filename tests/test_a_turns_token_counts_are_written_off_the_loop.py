# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1618` — a streamed chat turn writes its token usage off the event loop,
and the counts are there when the chat is read right after the turn.

Measured before the fix: `run_post_response_tasks` was a plain function the
stream called inside `chat_stream`'s generator for every turn with metrics, and
it called `accumulate_token_usage`, which opens a database session and writes
the chat's counters and the round's `llm_round` event — on the event loop, so
every other request waited on that write. It was the off-the-loop helper
ratchet's last residual (`MAX_THROUGH_A_HELPER`, now 0), and the stream's two
terminal paths made the same call where the scan does not look.

Now `run_post_response_tasks` is awaited and hands the write to a worker
thread, as the terminal paths do: off the loop, and finished before the turn's
last frame — not fired and forgotten — so a read of the chat right after the
turn finds its counts.

Driven: the real `run_post_response_tasks` and `accumulate_token_usage` over a
real SQLite file on a running loop; and the real `/api/chat_stream` route's
terminal path (the foreground-routing harness, sockets stood in for).
"""
from __future__ import annotations

import asyncio
import json
import threading
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

import core.database as cdb
from core.database import Event
from core.database import Session as DbSession


@pytest.fixture()
def chat(monkeypatch, tmp_path):
    import routes.chat_helpers as chat_helpers
    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}", connect_args={"check_same_thread": False},
                           poolclass=NullPool)
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    opened = []

    def spy(*a, **kw):
        opened.append(threading.get_ident())
        return factory(*a, **kw)

    monkeypatch.setattr(cdb, "SessionLocal", spy)
    monkeypatch.setattr(chat_helpers, "SessionLocal", spy)
    db = factory()
    db.add(DbSession(id="c1", owner="ann", name="Planning the trip", endpoint_url="x", model="m",
                     total_input_tokens=0, total_output_tokens=0))
    db.commit()
    db.close()

    def read():
        d = factory()
        try:
            row = d.query(DbSession).filter(DbSession.id == "c1").first()
            rounds = d.query(Event).filter(Event.kind == "llm_round").count()
            return (row.total_input_tokens, row.total_output_tokens), rounds
        finally:
            d.close()

    return chat_helpers, opened, read


def test_the_turns_counts_are_written_off_the_loop_and_there_when_it_returns(chat):
    chat_helpers, opened, read = chat
    sess = SimpleNamespace(endpoint_url="x", model="m", headers={}, history=[], name="Planning the trip")

    async def turn():
        loop_thread = threading.get_ident()
        await chat_helpers.run_post_response_tasks(
            sess, SimpleNamespace(save_sessions=lambda: None), "c1", "hello", "hi there",
            {"model": "m", "input_tokens": 120, "output_tokens": 30},
            {"auto_memory": False, "auto_skills": False}, None, None, None, owner="ann")
        # Read as the chat's own read would be, the moment the turn is over.
        return loop_thread, read()

    loop_thread, (totals, rounds) = asyncio.run(turn())
    assert totals == (120, 30), "the counts are in the row when the turn is over"
    assert rounds == 1
    assert opened, "nothing opened a session — the drive is not measuring the row"
    assert loop_thread not in opened, "a session was opened on the event loop"


@pytest.mark.asyncio
async def test_a_failed_turns_counts_are_written_off_the_loop_too(monkeypatch):
    """The stream's terminal path — an agent turn that stopped on a provider
    error — counts its round inside the generator; it is handed to a thread
    there too, tagged an error as before."""
    import routes.chat_routes as chat_routes
    from test_foreground_model_routing import _RouteRequest, _chat_stream_endpoint

    captured = {}
    terminal = {"model": "m", "input_tokens": 75, "output_tokens": 15, "usage_source": "real",
                "tool_events": [{"tool": "bash", "output": "created", "exit_code": 0}]}
    chunks = ['data: {"delta": "partial answer"}\n\n',
              f'data: {json.dumps({"type": "agent_terminal", "data": terminal})}\n\n',
              f'event: error\ndata: {json.dumps({"status": 401, "error": "invalid key"})}\n\n']
    endpoint = _chat_stream_endpoint(monkeypatch, "agent", captured, agent_chunks=chunks,
                                     capture_completion=True)
    counted = []
    monkeypatch.setattr(chat_routes, "accumulate_token_usage",
                        lambda session, metrics, **kw: counted.append((threading.get_ident(), kw)))
    loop_thread = threading.get_ident()
    response = await endpoint(_RouteRequest("agent"))
    [chunk async for chunk in response.body_iterator]
    assert len(counted) == 1, captured
    thread, kw = counted[0]
    assert thread != loop_thread, "the terminal path counted on the event loop"
    assert kw == {"outcome": "error"}
