# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P23-04` (PERF-M-7, alias CHAT-M-15) — the two probes a chat switch makes
answer 200.

**What was wrong.** Every chat open asks two questions: is a reply still
streaming here (`GET /api/chat/stream_status/{id}`), and is research running
here (`GET /api/research/status/{id}`). For an ordinary chat the answer to both
is "no", and both routes said so with a 404 — so the browser printed two
"Failed to load resource … 404" console errors on every switch, every reload,
every chat (measured on `9560d50`: `sessions.js:2653,2776`, server log
1802-1803).

**What is pinned.** Driven over HTTP (the chat route, real owner check) and by
calling the research route's handler:

  * an owned chat with nothing streaming → 200 ``{"active": false}``;
  * a detached run or a live stream record → 200, ``active: true``, with the
    status the client reads (`streaming`);
  * another person's chat is still refused — the owner check runs first;
  * no research, and another person's research, give the *same* 200 answer, so
    the reply says nothing about a chat the asker does not own;
  * the browser reads ``active: false`` as the old 404: `checkPendingResearch`
    clears the research mark and draws nothing (it used to draw
    "[Research none]" for a status it did not know).
"""

import asyncio
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.database import Base, Session as DbSession
from routes import chat_routes, session_routes
from src import agent_runs
from tests.helpers.js_source import js_definition
from tests.helpers.source_text import blank_text

ROOT = Path(__file__).resolve().parents[1]
CHAT_JS = ROOT / "static" / "js" / "chat.js"

ALICE_SID = "sess-alice-probe"
BOB_SID = "sess-bob-probe"


@pytest.fixture
def client(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[DbSession.__table__])
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    db = factory()
    for sid, owner in ((ALICE_SID, "alice"), (BOB_SID, "bob")):
        db.add(DbSession(id=sid, name=f"{owner}'s chat", endpoint_url="http://m.test/v1",
                         model="m", owner=owner))
    db.commit()
    db.close()
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setattr(session_routes, "SessionLocal", factory)
    app = FastAPI()

    @app.middleware("http")
    async def _auth(request, call_next):
        request.state.current_user = "alice"
        return await call_next(request)

    app.include_router(chat_routes.setup_chat_routes(*(SimpleNamespace() for _ in range(6))))
    try:
        yield TestClient(app)
    finally:
        chat_routes._active_streams.pop(ALICE_SID, None)
        agent_runs._RUNS.pop(ALICE_SID, None)
        engine.dispose()


def test_an_idle_chat_answers_200_not_404(client):
    res = client.get(f"/api/chat/stream_status/{ALICE_SID}")
    assert res.status_code == 200
    assert res.json()["active"] is False
    assert res.json()["status"] != "streaming"


def test_a_detached_run_is_still_reported_streaming(client):
    run = agent_runs._Run()
    agent_runs._RUNS[ALICE_SID] = run
    res = client.get(f"/api/chat/stream_status/{ALICE_SID}")
    assert res.status_code == 200
    assert res.json()["status"] == "streaming" and res.json()["active"] is True


def test_a_live_stream_record_is_returned_and_marked_active(client):
    chat_routes._active_streams[ALICE_SID] = {"status": "streaming", "partial": "hi", "mode": "agent"}
    res = client.get(f"/api/chat/stream_status/{ALICE_SID}")
    body = res.json()
    assert res.status_code == 200
    assert body["status"] == "streaming" and body["active"] is True and body["mode"] == "agent"
    # The record itself is not changed by being reported.
    assert "active" not in chat_routes._active_streams[ALICE_SID]


def test_another_persons_chat_is_still_refused(client):
    res = client.get(f"/api/chat/stream_status/{BOB_SID}")
    assert res.status_code in (403, 404)
    assert "active" not in (res.json() or {})


# ── research ────────────────────────────────────────────────────────────────

def _research_status(handler, user):
    from routes.research_routes import setup_research_routes
    router = setup_research_routes(handler)
    target = next(r.endpoint for r in router.routes
                  if getattr(r, "path", "") == "/api/research/status/{session_id}")
    req = SimpleNamespace(state=SimpleNamespace(current_user=user),
                          client=SimpleNamespace(host="127.0.0.1"))
    return asyncio.run(target(session_id="x", request=req))


def test_no_research_answers_200_inactive():
    rh = MagicMock()
    rh._active_tasks = {}
    rh.get_status.return_value = None
    out = _research_status(rh, "alice")
    assert out == {"status": "none", "active": False}


def test_another_persons_research_reads_exactly_like_none():
    rh = MagicMock()
    rh._active_tasks = {"x": {"owner": "alice", "status": "running"}}
    rh.get_status.return_value = {"status": "running", "progress": {"phase": "secret"}}
    nobody = MagicMock()
    nobody._active_tasks = {}
    nobody.get_status.return_value = None
    assert _research_status(rh, "bob") == _research_status(nobody, "bob")
    assert "progress" not in _research_status(rh, "bob")


def test_owned_running_research_still_answers_its_status():
    rh = MagicMock()
    rh._active_tasks = {"x": {"owner": "alice", "status": "running"}}
    rh.get_status.return_value = {"status": "running", "progress": {}}
    assert _research_status(rh, "alice") == {"status": "running", "progress": {}}


# ── the browser reads it ────────────────────────────────────────────────────

def _check_pending_research() -> str:
    src = CHAT_JS.read_text(encoding="utf-8")
    code = blank_text(src, "js")
    at = code.index("export async function checkPendingResearch(")
    return js_definition(src, at).replace("export async function", "async function", 1)


@pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")
@pytest.mark.parametrize("reply", [
    {"status": 200, "body": {"status": "none", "active": False}},
    {"status": 404, "body": {"detail": "No research found for this session"}},
])
def test_the_browser_reads_inactive_as_no_research(tmp_path, reply):
    case = (
        "const calls = { cleared: [], fetched: [] };\n"
        "const API_BASE = '';\n"
        f"const REPLY = {json.dumps(reply)};\n"
        "globalThis.fetch = async (url) => { calls.fetched.push(url);"
        " return { ok: REPLY.status < 400, status: REPLY.status, json: async () => REPLY.body }; };\n"
        "const sessionModule = { clearResearching: (id) => calls.cleared.push(id),"
        " getSessions: () => [], getCurrentSessionId: () => 'x' };\n"
        "const document = { querySelector: () => null, getElementById: () => { calls.drew = true; return null; } };\n"
        "const _notifyResearchComplete = () => { calls.notified = true; };\n"
        + _check_pending_research() + "\n"
        "await checkPendingResearch('x');\n"
        "console.log(JSON.stringify(calls));\n"
    )
    (tmp_path / "case.mjs").write_text(case, encoding="utf-8")
    out = subprocess.run(["node", "case.mjs"], cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    calls = json.loads(out.stdout.strip().splitlines()[-1])
    assert calls["cleared"] == ["x"]
    assert calls["fetched"] == ["/api/research/status/x"]
    assert not calls.get("drew") and not calls.get("notified")
