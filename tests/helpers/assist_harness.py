# SPDX-License-Identifier: AGPL-3.0-or-later
"""`wb-assist`'s shared world for `P22-19`, `P22-20` and `P22-24`.

Built on `walker_harness` (`Law 14`): the real `TaskScheduler`, the real task
and workflow routers, a real SQLite FILE, the real rule, the real slots and the
real dispatcher. What stands in is what would reach outside, and only that:

  * **a model** — `workflow_assist._complete`, the one seam every model call of
    this package goes through, answered by a script that records every message
    list it was handed (`ScriptedModel`);
  * **a chat server's far end** — an MCP manager whose one tool records each
    post (`Chat`), which is also what `workflow_resources` reads, so the palette,
    the rule at save and at run, and the dispatcher all see the same tool;
  * **the Integration store** — `integrations.load_integrations`, which reads an
    encrypted file in the data directory.

Who is asking is a request header the test app reads, so the person-only doors
(`request_is_a_person`, `B1005`) are asked about exactly what they look at:
`x-test-user` names the caller (a browser session), `x-test-token` makes the
request a bearer token's (`request.state.api_token`, `B70`), and the real
`X-Pantheon-Internal-Token` header is what the assistant's loopback carries.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from core.middleware import INTERNAL_TOOL_HEADER
from tests.helpers.walker_harness import make_db, recording_scheduler

POST = "mcp__chat__send_message"
CHAT_SCHEMA = {"type": "object", "properties": {
    "channel": {"type": "string"}, "text": {"type": "string"}}}
KEY = "sekret-api-key-123"
BASE_URL = "http://miniflux.lan:8090"

PERSON = {"x-test-user": "alice"}
TOKEN = {"x-test-user": "alice", "x-test-token": "1"}
ASSISTANT = {"x-test-user": "alice", INTERNAL_TOOL_HEADER: "whatever-it-carries"}


class Chat:
    """The chat server's far end: one tool, every post recorded."""

    def __init__(self, description="Post a message to a channel."):
        self.description = description
        self.posted = []

    def get_all_tools(self, disabled_map=None, overrides=None):
        return [{"qualified_name": POST, "server_id": "chat", "server_name": "Chat",
                 "name": "send_message", "description": self.description,
                 "input_schema": CHAT_SCHEMA, "is_disabled": False, "is_readonly": False}]

    async def call_tool(self, name, args):
        self.posted.append((name, dict(args)))
        return {"stdout": "posted", "stderr": "", "exit_code": 0}


def miniflux(base_url=BASE_URL, *, description="My feeds", preset="miniflux", key=KEY):
    return {"id": "intg-miniflux", "name": "Miniflux", "enabled": True, "base_url": base_url,
            "auth_type": "header", "api_key": key, "auth_header": "X-Auth-Token",
            "auth_param": "", "description": description, "preset": preset}


def make_app(factory, scheduler, monkeypatch, *, backup=False):
    """The task and workflow routers (and, with `backup`, the backup router) as
    `app.py` includes them, over the real scheduler."""
    from fastapi import FastAPI
    import routes.task.task_routes as task_routes
    import routes.workflow.workflow_routes as workflow_routes

    monkeypatch.setattr(task_routes, "SessionLocal", factory)
    monkeypatch.setattr(workflow_routes, "SessionLocal", factory)
    import routes.prefs_routes as prefs
    monkeypatch.setattr(prefs, "_load_for_user", lambda user=None: {})
    app = FastAPI()

    @app.middleware("http")
    async def _who(request, call_next):
        request.state.current_user = request.headers.get("x-test-user")
        if request.headers.get("x-test-token"):
            request.state.api_token = True
        return await call_next(request)

    app.include_router(task_routes.setup_task_routes(scheduler))
    app.include_router(workflow_routes.setup_workflow_routes(scheduler))
    return app


def build_world(monkeypatch, tmp_path, *, admin="alice", integrations=(), chat=None,
                name="assist.db"):
    """The real scheduler and routes over a real SQLite file, a chat server
    that records, the given Integrations, and `admin` the one admin — one
    answer from every place that asks (the dispatcher, the palette's reach, the
    task policy the store and the walker read)."""
    import src.agent_tools as agent_tools
    import src.integrations as integrations_mod
    import src.task_action_policy as tap
    import src.task_scheduler as ts
    import src.tool_execution as tool_execution
    import src.tool_security as tool_security
    from src.tool_approvals import tool_approval_store

    factory = make_db(monkeypatch, tmp_path / name)
    tool_approval_store._pending.clear()
    chat = chat or Chat()
    monkeypatch.setattr(agent_tools, "get_mcp_manager", lambda: chat, raising=False)
    is_admin = lambda owner: owner == admin  # noqa: E731
    monkeypatch.setattr(tool_execution, "_owner_is_admin", is_admin)
    monkeypatch.setattr(tool_security, "owner_is_admin_or_single_user", is_admin)
    monkeypatch.setattr(ts, "owner_has_admin_task_privileges", is_admin)
    monkeypatch.setattr(tap, "owner_has_admin_task_privileges", is_admin)
    listed = [dict(i) for i in integrations]
    monkeypatch.setattr(integrations_mod, "load_integrations", lambda: [dict(i) for i in listed])
    s = recording_scheduler()
    return SimpleNamespace(factory=factory, s=s, chat=chat, integrations=listed,
                           app=make_app(factory, s, monkeypatch))


class ScriptedModel:
    """`workflow_assist._complete`, scripted: each call takes the next answer
    (text, a dict sent as JSON, or an exception raised) and records the owner,
    the messages and the settings it was asked with."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    async def __call__(self, owner, messages, **kw):
        self.calls.append({"owner": owner, "messages": [dict(m) for m in messages], "kw": kw})
        if not self.answers:
            raise AssertionError("the model was asked more times than the test scripted")
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer if isinstance(answer, str) else json.dumps(answer)


def script_model(monkeypatch, *answers) -> ScriptedModel:
    from src import workflow_assist
    model = ScriptedModel(answers)
    monkeypatch.setattr(workflow_assist, "_complete", model)
    return model


def rows(factory, model, **where):
    db = factory()
    try:
        q = db.query(model)
        for key, value in where.items():
            q = q.filter(getattr(model, key) == value)
        return q.all()
    finally:
        db.close()


def stored(factory, workflow_id):
    """`(workflow row, its graph, its trigger row)`, read fresh."""
    from core.database import ScheduledTask, Workflow
    db = factory()
    try:
        wf = db.query(Workflow).filter(Workflow.id == workflow_id).first()
        trigger = db.query(ScheduledTask).filter(ScheduledTask.id == wf.task_id).first()
        return wf, json.loads(wf.graph), trigger
    finally:
        db.close()


def versions(factory, workflow_id):
    from core.database import WorkflowVersion
    db = factory()
    try:
        return [{"version": v.version, "source": v.source, "graph": json.loads(v.graph)}
                for v in db.query(WorkflowVersion).filter(WorkflowVersion.workflow_id == workflow_id)
                .order_by(WorkflowVersion.version).all()]
    finally:
        db.close()


def marks_of(graph) -> dict:
    return {n["id"]: n.get("unchecked") for n in graph.get("nodes") or ()}
