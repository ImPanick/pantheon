# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1496` — *Test this step* on a model slower than the request ceiling waits
for its answer, within the test's own budget.

**Measured before this file** (`B1093`'s drive, and here): a step test is one
request, and `app.py`'s request ceiling (`REQUEST_HARD_TIMEOUT`, 45 s) cut it
off — the panel said *"Not tested: Request exceeded 45s timeout"*, a sentence
nobody can act on (`Law 15`), and since `B1093` the test is cancelled with it.
So a step on a local model slower than 45 s could never be tested at all.

Now the step-test route is exempt from the ceiling (`_TIMEOUT_EXEMPT_PATTERNS`),
because it is bounded twice already: by the test's own budget
(`test_workflow_node`: the workflow's time limit, else five minutes, which it
says as "Timed out after …") and by the page waiting
(`_while_the_request_waits`, `B1093`). Driven (`Law 20`): the real app out of
process — its real request ceiling, set to one second, its real middleware
stack, the real route and scheduler — with the model scripted and three times
slower than the ceiling.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

from tests.helpers.walker_harness import node

_REPO = Path(__file__).resolve().parents[1]
STEP = node("n1", "Send me the summary", prompt="Summarise my inbox.",
            model="scripted", endpoint_url="http://127.0.0.1:9/v1")

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
    exempt = getattr(app_module, "_exempt_from_request_ceiling", lambda p: None)
    out = {"exempt": {p: exempt(p) for p in (
        "/api/workflows/w1/nodes/n1/test", "/api/workflows/w1/nodes/n1/fix",
        "/api/workflows/w1/nodes/n1/fields", "/api/workflows/w1", "/api/tasks/t1/run",
        "/api/chat/stream")}}
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
        out["rounds"] = dict(rounds)
        db = SessionLocal()
        out["chats"] = [s.name for s in db.query(Session).all()]
        db.close()
    print("RESULT " + json.dumps(out))
    """
)


def test_a_step_slower_than_the_ceiling_is_tested_and_answered(tmp_path):
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
    assert status == 200, (
        f"a step slower than the request ceiling was not tested: {out}")
    assert (body.get("outcome"), body.get("status"), body.get("text")) == (
        "ran", "success", "The summary."), body
    assert took >= 2.9, f"answered before the model did: {out}"
    assert out["rounds"] == {"started": 1, "completed": 1}, out
    assert out["chats"] == [], "the test left a chat"
    # Only the step test is let past the ceiling; its neighbours keep it.
    assert out["exempt"] == {
        "/api/workflows/w1/nodes/n1/test": True,
        "/api/workflows/w1/nodes/n1/fix": False,
        "/api/workflows/w1/nodes/n1/fields": False,
        "/api/workflows/w1": False,
        "/api/tasks/t1/run": False,
        "/api/chat/stream": True,
    }, out["exempt"]


def test_the_tests_own_budget_is_what_bounds_it():
    """The exemption leans on this: a test that runs past its budget ends,
    saying how long it was given (`test_workflow_node`)."""
    import asyncio

    from src.task_scheduler import TaskScheduler
    from types import SimpleNamespace

    s = TaskScheduler(None)

    async def forever(*a, **k):
        await asyncio.sleep(30)

    s._run_workflow_step = forever
    s._test_context = lambda *a, **k: {}
    task = SimpleNamespace(id="wf", owner="ada", timeout_seconds=None, session_id=None)
    out = asyncio.run(s.test_workflow_node(task, "Morning inbox brief", STEP, timeout=0.2))
    assert out["status"] == "error" and out["text"].startswith("Timed out after"), out
