# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1093` — *Test this step* that the person was told did not run does not run
afterwards, and a test leaves no chat behind.

**Measured on the merged tree** (drive runs 1 and 2, the server log): a test of
a Prompt step on a local model answered "Not tested: Request exceeded 45s
timeout" — `app.py`'s request ceiling, a 504 — and the test kept running on
the server: its model round completed 91 s after the press, 46 s after the
504. `_RequestTimeoutMiddleware`'s `wait_for` stops waiting for the handler,
not the handler (`BaseHTTPMiddleware` lets the endpoint finish). And the press
made a chat, "[Task] Morning inbox brief", in the Tasks folder — empty, before
the workflow had ever run, and kept on its trigger.

Now the route awaits the test only while the request is waiting for it, and a
test removes the chat it made. Driven (`Law 20`): the real app out of process
(its real request ceiling, set to one second, its real middleware stack, the
real route and scheduler — the model scripted and slower than the ceiling),
and in process the real `test_workflow_node`, the real Prompt executor and
agent loop, and a real `SessionManager` on one SQLite file.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from tests.helpers.walker_harness import make_db, node, seed_workflow

_REPO = Path(__file__).resolve().parents[1]
ENDPOINT = dict(model="scripted", endpoint_url="http://127.0.0.1:9/v1")


# ── the chat ────────────────────────────────────────────────────────────────

@pytest.fixture()
def world(monkeypatch, tmp_path):
    import core.session_manager as sm_mod
    import src.agent_loop as agent_loop
    import src.task_endpoint as task_endpoint
    from src.task_scheduler import TaskScheduler

    factory = make_db(monkeypatch, tmp_path / "chat.db")
    monkeypatch.setattr(sm_mod, "SessionLocal", factory)

    async def model(candidates, messages, **kwargs):
        yield f"data: {json.dumps({'delta': 'The summary.'})}\n\n"
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", model)
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: None, raising=False)
    monkeypatch.setattr(agent_loop, "estimate_tokens", lambda *a, **k: 10)
    monkeypatch.setattr(agent_loop, "blocked_tools_for_owner", lambda owner: set(), raising=False)
    monkeypatch.setattr(task_endpoint, "resolve_task_candidates", lambda **kw: [])
    manager = sm_mod.SessionManager()
    s = TaskScheduler(manager)
    s._log_to_assistant = lambda *a, **k: None
    return factory, s, manager


def _chats(factory):
    from core.database import Session as DbSession
    db = factory()
    try:
        return [(r.id, r.name, r.folder) for r in db.query(DbSession).all()]
    finally:
        db.close()


def _trigger(factory):
    from core.database import ScheduledTask
    db = factory()
    try:
        return db.query(ScheduledTask).filter(ScheduledTask.id == "wf").first()
    finally:
        db.close()


STEP = node("n1", "Send me the summary", prompt="Summarise my inbox.", **ENDPOINT)


@pytest.mark.asyncio
async def test_a_tested_prompt_step_leaves_no_chat(world):
    factory, s, manager = world
    seed_workflow(factory, [STEP], [], name="Morning inbox brief")
    out = await s.test_workflow_node(_trigger(factory), "Morning inbox brief", STEP)
    assert (out["status"], out["text"]) == ("success", "The summary."), out
    assert _chats(factory) == [], "the test left a chat in the sidebar"
    assert _trigger(factory).session_id is None, "…or one kept on the trigger"
    assert manager.sessions == {}


@pytest.mark.asyncio
async def test_a_workflow_that_has_a_chat_keeps_it_through_a_test(world):
    """`Law 1`: a chat a real run made is the workflow's; a test runs in it and
    leaves it exactly where it was."""
    factory, s, manager = world
    seed_workflow(factory, [STEP], [], name="Morning inbox brief")
    await s._execute_task("wf")
    [(chat, name, folder)] = _chats(factory)
    assert (name, folder) == ("[Task] Morning inbox brief", "Tasks")
    assert _trigger(factory).session_id == chat
    out = await s.test_workflow_node(_trigger(factory), "Morning inbox brief", STEP)
    assert out["status"] == "success"
    assert [c[0] for c in _chats(factory)] == [chat]
    assert _trigger(factory).session_id == chat


# ── the request ceiling ─────────────────────────────────────────────────────

_PROBE = textwrap.dedent(
    """
    import asyncio, json, time
    import app as app_module
    import src.agent_loop as agent_loop
    import src.task_endpoint as task_endpoint
    from tests.helpers.signed_in import sign_in
    from fastapi.testclient import TestClient

    app_module.REQUEST_HARD_TIMEOUT = 1.0          # the ceiling, at one second
    rounds = {"started": 0, "completed": 0}

    async def model(candidates, messages, **kwargs):
        rounds["started"] += 1
        await asyncio.sleep(3)                     # a local model, slower than the ceiling
        rounds["completed"] += 1
        yield "data: " + json.dumps({"delta": "The summary."}) + "\\n\\n"
        yield "data: [DONE]\\n\\n"

    agent_loop.stream_llm_with_fallback = model
    agent_loop.get_mcp_manager = lambda: None
    agent_loop.estimate_tokens = lambda *a, **k: 10
    task_endpoint.resolve_task_candidates = lambda **kw: []
    STEP = __STEP__
    out = {}
    with TestClient(app_module.app) as client:
        sign_in(app_module, client)
        from core.database import SessionLocal, ModelEndpoint, ScheduledTask, Workflow, Session
        db = SessionLocal()
        db.add(ModelEndpoint(id="local", name="Local", is_enabled=True, endpoint_kind="local",
                             base_url="http://127.0.0.1:9/v1", cached_models='["scripted"]'))
        db.add(ScheduledTask(id="wf", owner="ada", name="Morning inbox brief",
                             task_type="workflow", trigger_type="webhook", status="active"))
        db.add(Workflow(id="w1", owner="ada", name="Morning inbox brief", task_id="wf", version=1,
                        graph=json.dumps({"v": 1, "nodes": [STEP], "edges": []})))
        db.commit()
        db.close()
        t0 = time.monotonic()
        r = client.post("/api/workflows/w1/nodes/n1/test", json={"node": STEP, "source": "none"})
        out["answer"] = [r.status_code, r.json(), round(time.monotonic() - t0, 2)]
        time.sleep(3.5)                            # past when the round would have finished
        out["rounds"] = dict(rounds)
        db = SessionLocal()
        out["chats"] = [s.name for s in db.query(Session).all()]
        db.close()
    print("RESULT " + json.dumps(out))
    """
)


def test_a_test_the_ceiling_cut_off_does_not_run_on_afterwards(tmp_path):
    env = os.environ.copy()
    env.update({
        "CHROMADB_CONNECT_TIMEOUT": "0.01", "CHROMADB_HOST": "127.0.0.1", "CHROMADB_PORT": "9",
        "DATABASE_URL": f"sqlite:///{tmp_path / 'app.db'}", "PANTHEON_DATA_DIR": str(tmp_path),
        "PANTHEON_DISABLE_MCP": "1", "PYTHONPATH": str(_REPO), "PYTHON_DOTENV_DISABLED": "1",
        "BACKGROUND_TASK_FOREGROUND_GATE": "0",
    })
    probe = _PROBE.replace("__STEP__", repr(STEP))
    done = subprocess.run([sys.executable, "-c", probe], cwd=_REPO, env=env,
                          capture_output=True, text=True, timeout=240)
    line = next((ln for ln in done.stdout.splitlines() if ln.startswith("RESULT ")), None)
    assert line, done.stderr[-4000:]
    out = json.loads(line[len("RESULT "):])
    status, body, took = out["answer"]
    assert status == 504, out                      # what the person is told
    assert out["rounds"] == {"started": 1, "completed": 0}, \
        f"the test they were told did not run, ran: {out}"
    assert took < 2.9, f"the request was held until the round ended: {out}"
    assert out["chats"] == [], out
