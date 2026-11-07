# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B1917`. A model's answer of an unclosed code fence held the server for seconds.

When the memory tidy (`audit_memories`) and the chat tidy (`POST
/api/sessions/auto-sort`, and `run_auto_sort`, the same tidy run by the agent
and on a schedule) cannot read their model's answer as JSON, they look for a
fenced block with ``re.search(r'```(?:json)?\s*\n?([\s\S]*?)```', text)``. On
an opening fence, a run of spaces and no closing fence, `\s*` gave the spaces
back one at a time and the lazy body read the rest of the answer again for
each one: an opening fence and 40,000 spaces took 14 seconds in each place on
the loaded test machine, about 7 on an idle one, and the regex holds the GIL.

Now the fence's whitespace is taken possessively, `\s*+` (Python 3.11,
Pantheon's floor). The match is the one it was: whitespace holds no backtick,
so giving it back could never reach a closing fence. Upstream Odysseus
3d91ad82 changed the memory tidy's copy; the chat tidy's two are Pantheon's.
Each place is driven with a stand-in model that answers the flood, and fails
on the old code; a fenced answer still reads in each.
"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

import core.database as cdb
import services.memory.memory_extractor as memory_extractor
from core.database import ChatMessage as DbMessage
from core.database import Session as DbSession
from src.memory import MemoryManager

_FLOOD = "```json" + " " * 40_000 + "x"
_BUDGET_S = 2.0  # the old fence took 14 s on _FLOOD here; the new one, milliseconds


class _Model:
    """A stand-in model that gives one answer and notes when it gave it."""

    def __init__(self, answer):
        self.answer = answer
        self.answered = None

    async def call_async(self, *_a, **_k):
        self.answered = time.perf_counter()
        return self.answer

    def call(self, *_a, **_k):
        self.answered = time.perf_counter()
        return self.answer

    def seconds_since_it_answered(self):
        return time.perf_counter() - self.answered


# ── the memory tidy ─────────────────────────────────────────────────────────

@pytest.fixture()
def store(tmp_path):
    manager = MemoryManager(str(tmp_path))
    manager.save([manager.add_entry("The user keeps sourdough starter in the fridge",
                                    source="auto", confidence=0.8)])
    return manager


def _tidy_memories(monkeypatch, store, answer):
    model = _Model(answer)
    monkeypatch.setattr("src.llm_core.llm_call_async", model.call_async)
    return asyncio.run(memory_extractor.audit_memories(store, None, "http://x", "m")), model


def test_the_memory_tidy_reads_an_unclosed_fence_in_one_pass(monkeypatch, store):
    out, model = _tidy_memories(monkeypatch, store, _FLOOD)
    assert model.seconds_since_it_answered() < _BUDGET_S
    assert out["error"] == "bad_json"


@pytest.mark.parametrize("fence", [
    "```json\n{rows}\n```",
    "```\n{rows}\n```",
    "Here is the list:\n```json {rows}```\nDone.",
    "```json\n\n   {rows}   \n```",
])
def test_the_memory_tidy_still_reads_a_fenced_answer(monkeypatch, store, fence):
    entry = store.load_all()[0]
    rows = json.dumps([{"id": entry["id"], "text": "Keeps sourdough starter in the fridge",
                        "category": "fact"}])
    out, _model = _tidy_memories(monkeypatch, store, fence.replace("{rows}", rows))
    assert "error" not in out, out
    assert [row["text"] for row in store.load_all()] == ["Keeps sourdough starter in the fridge"]


# ── the chat tidy, through its route and as the agent runs it ───────────────

_CHATS = {"ann-0001-aaaa": "Sourdough starter", "ann-0002-bbbb": "Rye loaf",
          "ann-0003-cccc": "Bike gears"}
_FOLDERS = {"folders": {"Baking": ["ann-0001", "ann-0002"], "Bikes": ["ann-0003"]}}


@pytest.fixture()
def chats(monkeypatch, tmp_path):
    """Three answered chats in a real SQLite file, and the tidy's endpoint."""
    import core.session_manager as smod
    import routes.session_routes as session_routes
    import src.task_endpoint as task_endpoint

    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}",
                           connect_args={"check_same_thread": False}, poolclass=NullPool)
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    for mod in (smod, session_routes, cdb):
        monkeypatch.setattr(mod, "SessionLocal", factory)
    db = factory()
    t = datetime(2026, 1, 1)
    for sid, name in _CHATS.items():
        db.add(DbSession(id=sid, owner="ann", name=name, endpoint_url="x", model="m",
                         created_at=t, updated_at=t, last_accessed=t, last_message_at=t))
        for i in range(4):
            db.add(DbMessage(id=f"{sid}-{i}", session_id=sid,
                             role="user" if i % 2 == 0 else "assistant",
                             content=f"{name} {i}", timestamp=t))
    db.commit()
    db.close()
    monkeypatch.setattr(session_routes, "effective_user", lambda request: "ann")
    monkeypatch.setattr(task_endpoint, "resolve_task_endpoint",
                        lambda *a, **k: ("http://u/v1", "utility", {}))
    return factory


def _tidy_through_the_route(monkeypatch, answer):
    import core.session_manager as smod
    import routes.session_routes as session_routes

    model = _Model(answer)
    monkeypatch.setattr("src.llm_core.llm_call", model.call)
    app = FastAPI()
    app.include_router(session_routes.setup_session_routes(smod.SessionManager(), {}))
    return TestClient(app).post("/api/sessions/auto-sort"), model


def _tidy_as_the_agent_does(monkeypatch, answer):
    from src.session_actions import run_auto_sort

    model = _Model(answer)
    monkeypatch.setattr("src.llm_core.llm_call_async", model.call_async)
    return asyncio.run(run_auto_sort("ann")), model


def test_the_chat_tidy_reads_an_unclosed_fence_in_one_pass(monkeypatch, chats):
    res, model = _tidy_through_the_route(monkeypatch, _FLOOD)
    assert model.seconds_since_it_answered() < _BUDGET_S
    assert res.status_code == 502, res.text


def test_the_agents_chat_tidy_reads_an_unclosed_fence_in_one_pass(monkeypatch, chats):
    summary, model = _tidy_as_the_agent_does(monkeypatch, _FLOOD)
    assert model.seconds_since_it_answered() < _BUDGET_S
    assert summary.endswith("Folders not sorted: the model's answer could not be read."), summary


def test_both_chat_tidies_still_read_a_fenced_answer(monkeypatch, chats):
    fenced = "Sorted:\n```json\n" + json.dumps(_FOLDERS) + "\n```"
    res, _model = _tidy_through_the_route(monkeypatch, fenced)
    assert res.status_code == 200, res.text
    assert sorted(res.json()["folders"]) == ["Baking", "Bikes"]

    summary, _model = _tidy_as_the_agent_does(monkeypatch, fenced)
    assert "Sorted 3 chats into: Baking (2), Bikes (1)" in summary, summary
