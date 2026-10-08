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
                name="assist.db", skills=(), workstation=False):
    """The real scheduler and routes over a real SQLite file, a chat server
    that records, the given Integrations, and `admin` the one admin — one
    answer from every place that asks (the dispatcher, the palette's reach, the
    task policy the store and the walker read).

    `skills` — `[(name, description)]` written for alice by the real
    `SkillsManager` over a temporary data directory (`test_a_skill_is_a_step`'s
    move). `workstation` — Code is available (the workstation's three
    conditions answer None), so a test can show Code is left out of a draft by
    the drafter's rule and not merely because the workstation is off."""
    from services.memory.skills import SkillsManager, invalidate_skill_cache
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    monkeypatch.setattr("src.constants.DATA_DIR", str(data))
    invalidate_skill_cache()
    sm = SkillsManager(str(data))
    for skill_name, description in skills:
        sm.add_skill(name=skill_name, description=description, owner="alice",
                     procedure=["Read it", "Do it"], status="published")
    if workstation:
        import src.workflow_effects as we
        monkeypatch.setattr(we, "workstation_why", lambda owner: None)
    import routes.task.task_routes as task_routes
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
    # `task_routes` imports `owner_has_admin_task_privileges` by name, so it holds
    # whatever `tap` held when the module was first imported. Patching only `tap`
    # left the routes' copy to import order (fx5-green, measured in the full run):
    # when this world was the first to import `task_routes`, the routes kept THIS
    # test's `is_admin` for the rest of the session, past its monkeypatch; when an
    # earlier file (`test_a_chain_becomes_a_workflow_and_the_chain_stays.py`)
    # imported it first, the routes kept the real check, which answers from the
    # shared auth manager — nobody here is in it — so the task routes' resume, dry
    # run and webhook refused alice (403 "requires admin privileges"). The module
    # is imported above, before `tap` is patched, so it binds the real function,
    # and its own name is patched here and restored with the rest.
    monkeypatch.setattr(task_routes, "owner_has_admin_task_privileges", is_admin)
    listed =[dict(i) for i in integrations]
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


class Feeds:
    """A loopback HTTP server standing in for an Integration's far end: it
    records every request, answers `/v1/entries` with two entries, and any
    other path with a 404 whose body is `self.not_found` — text the server's
    owner writes, which is exactly what `P22-20`'s adversary controls."""

    def __init__(self):
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        self.requests = []
        self.not_found = {"error": "not found", "hint": "Did you mean /v1/entries?"}
        server = self

        class Handler(BaseHTTPRequestHandler):
            def _answer(self):
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    self.rfile.read(length)
                server.requests.append({"method": self.command, "path": self.path,
                                        "headers": {k.lower(): v for k, v in self.headers.items()}})
                if self.path.split("?")[0] == "/v1/entries":
                    status, payload = 200, {"total": 2, "entries": [{"id": 1, "title": "One"},
                                                                     {"id": 2, "title": "Two"}]}
                else:
                    status, payload = 404, server.not_found
                data = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _answer

            def log_message(self, *a):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        self.base_url = f"http://miniflux.lan:{self.port}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def resolve_to_loopback(monkeypatch, host="miniflux.lan"):
    """The Integration's host name resolves, through the SSRF guard's own
    resolver, to the loopback — so the guard approves it and the transport is
    pinned to what it approved (`test_an_http_step_goes_through_an_integration`'s
    move). Nothing else is resolved."""
    import ipaddress

    def resolve(name):
        if name == host:
            return ["127.0.0.1"]
        try:
            return [str(ipaddress.ip_address(name))]
        except ValueError:
            return []
    monkeypatch.setattr("src.url_safety._default_resolver", resolve)
    monkeypatch.delenv("INTEGRATION_API_BLOCK_PRIVATE_IPS", raising=False)
