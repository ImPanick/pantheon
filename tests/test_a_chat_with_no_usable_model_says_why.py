# SPDX-License-Identifier: AGPL-3.0-or-later
"""`D-2026-10-07-02` §1 — a chat, a task, a workflow step, the agent or the API
with no model an endpoint lists fails at once and says why.

The owner, 2026-10-07: *"Started a chat with no model fails clearly, and
states why."* and *"never populate a fabricated model"*.

Measured on `fcd559e` (the base):

  * a chat with no model got "No model selected for this chat. Open the model
    picker and choose one before sending." — even on an install with no model
    at all, where there is nothing to pick;
  * a chat on an endpoint that had stopped answering, or on a model its server
    no longer listed, was sent: it failed later, in the provider's words;
  * a scheduled task that named no model ran on the model of its owner's
    newest chat (`_resolve_defaults`), whatever it was; one naming a model
    nothing listed ran anyway, and a failure was recorded as
    `RuntimeError: …`;
  * the agent's `list_models` answered Anthropic with ten built-in `claude-*`
    names and an endpoint that did not answer with a row `(endpoint offline)`;
    `chat_with_model` matched against the built-in names;
  * `POST /api/v1/chat` with an API key and no model used `deepseek-chat`;
    `POST /api/session/openai` with no model used `gpt-4o`.

Driven (`Law 20`): the real chat route over HTTP, the real scheduler running a
task to its run record, the agent's real tools, the real API routes — against
a real SQLite file and local list servers (`tests/helpers/model_lists.py`);
nothing leaves the machine (`Law 16`).
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.database import Base, ModelEndpoint, Session as DbSession
from tests.helpers.model_lists import ListServer, closed_port, no_proxy, point_hosts_at

NO_MODEL = "No model yet. Models are added in Settings → Added Models."


class _Manager:
    is_configured = True

    def is_admin(self, user):
        return user == "ada"


@pytest.fixture
def world(tmp_path, monkeypatch):
    import routes.chat_routes as chat_routes
    import routes.model_routes as model_routes
    import routes.session_routes as session_routes
    import src.database as src_database
    import src.endpoint_resolver as endpoint_resolver
    import src.settings

    no_proxy(monkeypatch)
    monkeypatch.setenv("AUTH_ENABLED", "true")
    engine = create_engine(f"sqlite:///{tmp_path / 'chat.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine, tables=[ModelEndpoint.__table__, DbSession.__table__])
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    for mod in (chat_routes, model_routes, session_routes, endpoint_resolver, src_database):
        monkeypatch.setattr(mod, "SessionLocal", factory)
    monkeypatch.setattr(src.settings, "SETTINGS_FILE", str(tmp_path / "settings.json"))
    src.settings._invalidate_caches()
    monkeypatch.setattr(model_routes, "_LISTING_STATE", {}, raising=False)
    servers = []
    sessions = {}

    class World:
        db = factory

        def serve(self, models, **kw):
            s = ListServer(models, **kw)
            servers.append(s)
            return s

        def add(self, ep_id, base_url, **cols):
            db = factory()
            db.add(ModelEndpoint(id=ep_id, name=cols.pop("name", ep_id), base_url=base_url,
                                 is_enabled=True, **cols))
            db.commit()
            db.close()

        def chat(self, sid, endpoint_url, model, owner="ada"):
            db = factory()
            db.add(DbSession(id=sid, name="A chat", endpoint_url=endpoint_url, model=model, owner=owner))
            db.commit()
            db.close()
            sessions[sid] = SimpleNamespace(id=sid, endpoint_url=endpoint_url, model=model,
                                            headers={}, owner=owner, history=[])

        def client(self, user="ada"):
            app = FastAPI()
            app.state.auth_manager = _Manager()

            @app.middleware("http")
            async def _who(request, call_next):
                request.state.current_user = user
                return await call_next(request)

            manager = SimpleNamespace(get_session=lambda sid: sessions[sid])
            app.include_router(chat_routes.setup_chat_routes(
                manager, *(SimpleNamespace() for _ in range(5))))
            return TestClient(app, raise_server_exceptions=False)

    yield World()
    for s in servers:
        s.stop()
    src.settings._invalidate_caches()


def _send(world, sid, user="ada"):
    return world.client(user).post("/api/chat", json={"message": "hello", "session": sid})


# ── the chat ────────────────────────────────────────────────────────────────

def test_a_chat_with_no_model_and_none_added_is_refused_with_where_to_add_one(world):
    world.chat("s1", "", "")
    res = _send(world, "s1")
    assert res.status_code == 400
    assert res.json()["detail"] == NO_MODEL


def test_a_chat_with_no_model_chosen_says_pick_one(world):
    srv = world.serve(["alpha-7b"])
    world.add("office", srv.base, name="Office LLM", endpoint_kind="local",
              cached_models=json.dumps(["alpha-7b"]))
    world.chat("s1", "", "")
    res = _send(world, "s1")
    assert res.status_code == 400
    assert res.json()["detail"] == "No model chosen for this chat. Pick one from the model menu."


def test_a_chat_on_an_endpoint_that_is_not_answering_is_refused_at_once(world):
    url = f"http://127.0.0.1:{closed_port()}/v1"
    world.add("office", url, name="Office LLM", endpoint_kind="local")
    world.chat("s1", url + "/chat/completions", "alpha-7b")
    res = _send(world, "s1")
    assert res.status_code == 503
    assert res.json()["detail"] == "Office LLM isn't answering. Pick another from the model menu."


def test_a_chat_on_a_model_its_endpoint_no_longer_lists_is_refused_unsent(world):
    srv = world.serve(["alpha-7b"])
    world.add("office", srv.base, name="Office LLM", endpoint_kind="local",
              cached_models=json.dumps(["alpha-7b"]))
    world.chat("s1", srv.base + "/chat/completions", "gone-70b")
    res = _send(world, "s1")
    assert res.status_code == 409
    assert res.json()["detail"] == "gone-70b isn't listed by Office LLM now. Pick another from the model menu."
    assert not [a for a in srv.asked if "chat/completions" in a["path"]], "it was sent anyway"


def test_a_listed_model_passes_and_a_server_that_came_back_is_asked_first(world):
    """Nothing listed since a restart, the server is up: the gate asks it,
    stores the answer, and lets the chat through — a stale failure is not a
    refusal."""
    import routes.chat_routes as chat_routes
    import routes.model_routes as model_routes

    srv = world.serve(["alpha-7b"])
    world.add("office", srv.base, name="Office LLM", endpoint_kind="local")
    sess = SimpleNamespace(endpoint_url=srv.base + "/chat/completions", model="alpha-7b")
    chat_routes._require_usable_model(SimpleNamespace(), sess, owner="ada")
    db = world.db()
    try:
        row = db.query(ModelEndpoint).filter(ModelEndpoint.id == "office").first()
        assert json.loads(row.cached_models) == ["alpha-7b"]
        assert model_routes.offered_models(row) == ["alpha-7b"]
    finally:
        db.close()


# ── a task and a workflow step ──────────────────────────────────────────────

@pytest.fixture
def scheduler_world(monkeypatch, tmp_path):
    """The walker world: the real scheduler and agent loop; only the model's
    words are scripted. Its endpoint `http://127.0.0.1:9/v1` lists `scripted`
    and `m` (`tests/helpers/walker_harness.make_db`)."""
    import src.agent_loop as agent_loop
    import src.task_endpoint as task_endpoint
    from src.task_scheduler import TaskScheduler
    from tests.helpers.walker_harness import make_db
    import src.settings

    factory = make_db(monkeypatch, tmp_path / "tasks.db")
    import routes.model_routes as model_routes
    import src.endpoint_resolver as endpoint_resolver
    monkeypatch.setattr(model_routes, "SessionLocal", factory)
    monkeypatch.setattr(endpoint_resolver, "SessionLocal", factory)
    monkeypatch.setattr(model_routes, "_LISTING_STATE", {}, raising=False)
    monkeypatch.setattr(src.settings, "SETTINGS_FILE", str(tmp_path / "settings.json"))
    src.settings._invalidate_caches()

    async def model(candidates, messages, **kwargs):
        yield "data: " + json.dumps({"delta": "Done."}) + "\n\n"
        yield "data: [DONE]\n\n"
    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", model)
    monkeypatch.setattr(agent_loop, "estimate_tokens", lambda *a, **k: 10)
    monkeypatch.setattr(task_endpoint, "task_llm_call_async",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("fallback call")))
    s = TaskScheduler(None)
    s._log_to_assistant = lambda *a, **k: None
    yield SimpleNamespace(factory=factory, s=s)
    src.settings._invalidate_caches()


def _run_task(w, **cols):
    from core.database import ScheduledTask, TaskRun
    db = w.factory()
    db.add(ScheduledTask(id="t1", owner="alice", name="Morning", task_type="llm",
                         prompt="Summarise.", status="active", trigger_type="manual", **cols))
    db.commit()
    db.close()
    asyncio.run(w.s._execute_task("t1"))
    db = w.factory()
    try:
        run = db.query(TaskRun).filter(TaskRun.task_id == "t1").first()
        return run.status, run.error
    finally:
        db.close()


def test_a_task_on_a_model_nothing_lists_records_why_it_did_not_run(scheduler_world):
    status, error = _run_task(scheduler_world, model="gone-70b", endpoint_url="http://127.0.0.1:9/v1")
    assert status == "error"
    assert error == "gone-70b isn't listed by Scripted world now. Pick another model for this task."


def test_a_task_on_a_listed_model_runs(scheduler_world):
    status, error = _run_task(scheduler_world, model="scripted", endpoint_url="http://127.0.0.1:9/v1")
    assert (status, error) == ("success", None)


def test_a_task_with_no_model_does_not_borrow_the_newest_chats(scheduler_world):
    """No task model and none configured: the run says so. The base ran it on
    the model of the owner's newest chat."""
    db = scheduler_world.factory()
    db.add(DbSession(id="c1", name="Old chat", owner="alice", model="scripted",
                     endpoint_url="http://127.0.0.1:9/v1/chat/completions"))
    db.commit()
    db.close()
    status, error = _run_task(scheduler_world)
    assert status == "error"
    assert error == "No model yet. An admin adds one in Settings → Added Models."


def test_a_workflow_step_naming_a_model_nothing_lists_says_so_for_the_step(scheduler_world):
    from src import workflow_document as wd
    from src.endpoint_resolver import NoUsableModel

    trigger = SimpleNamespace(id="wf", owner="alice", tz_name=None, session_id=None)
    step = wd.node_stand_in(trigger, "Morning", {"id": "n1", "kind": "llm", "label": "Draft",
                                                "config": {"prompt": "Draft.", "model": "gone-70b"}})
    db = scheduler_world.factory()
    try:
        with pytest.raises(NoUsableModel) as exc:
            scheduler_world.s._usable_route(db, step, step.endpoint_url, step.model)
    finally:
        db.close()
    assert str(exc.value) == "gone-70b isn't listed by any endpoint now. Pick another model for this step."


# ── the agent's model tools ─────────────────────────────────────────────────

def test_the_agents_list_models_names_only_what_was_listed(world, monkeypatch):
    from src.agent_tools.model_interaction_tools import list_models

    office = world.serve(["alpha-7b"])
    claude = world.serve(["claude-fixture-sonnet"], anthropic_key="good")
    point_hosts_at(monkeypatch, {"api.anthropic.com": claude.port})
    world.add("office", office.base, name="Office LLM", endpoint_kind="local")
    world.add("anthropic", f"http://api.anthropic.com:{claude.port}", name="Anthropic",
              endpoint_kind="api", api_key="good")
    world.add("dead", f"http://127.0.0.1:{closed_port()}/v1", name="Dead box", endpoint_kind="local")
    out = asyncio.run(list_models("", owner="ada"))["results"]
    assert "`alpha-7b`" in out and "`claude-fixture-sonnet`" in out
    assert "Dead box isn't answering." in out
    assert "(endpoint offline)" not in out
    assert "claude-sonnet-4" not in out and "claude-opus-4" not in out


def test_chat_with_model_resolves_only_a_listed_name(world, monkeypatch):
    from src.ai_interaction import _resolve_model

    claude = world.serve(["claude-fixture-sonnet"], anthropic_key="good")
    point_hosts_at(monkeypatch, {"api.anthropic.com": claude.port})
    world.add("anthropic", f"http://api.anthropic.com:{claude.port}", name="Anthropic",
              endpoint_kind="api", api_key="good")
    with pytest.raises(ValueError) as exc:
        _resolve_model("claude-sonnet-4", owner="ada")
    assert "not listed by any endpoint" in str(exc.value)
    url, model, _headers = _resolve_model("claude-fixture-sonnet", owner="ada")
    assert model == "claude-fixture-sonnet" and url.endswith("/v1/messages")


# ── the API ─────────────────────────────────────────────────────────────────

def _api_app(router):
    app = FastAPI()

    @app.middleware("http")
    async def _token(request, call_next):
        request.state.current_user = "api"
        request.state.api_token = True
        request.state.api_token_owner = "ada"
        request.state.api_token_scopes = ["chat"]
        return await call_next(request)

    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


def test_the_api_names_no_model_for_a_callers_key(world, monkeypatch):
    import src.llm_core as llm_core
    from routes.webhook.webhook_routes import setup_webhook_routes

    sent = []

    async def llm_call_async(url, model, messages, **kw):
        sent.append(model)
        return "reply"
    monkeypatch.setattr(llm_core, "llm_call_async", llm_call_async)
    created = []
    manager = SimpleNamespace(
        create_session=lambda **kw: created.append(kw) or SimpleNamespace(headers={}, history=[], **kw),
        save_sessions=lambda: None)
    router = setup_webhook_routes(SimpleNamespace(fire_and_forget=lambda *a, **k: None),
                                  None, session_manager=manager)
    res = _api_app(router).post("/api/v1/chat", json={"message": "hi", "api_key": "sk-caller",
                                                  "provider": "deepseek"})
    assert res.status_code == 400
    assert res.json()["detail"] == "Pass model with api_key: a name your provider lists for that key."
    assert sent == [] and created == []


def test_an_openai_session_names_no_model(world, monkeypatch):
    import routes.session_routes as session_routes

    router = session_routes.setup_session_routes(
        SimpleNamespace(create_session=lambda **kw: (_ for _ in ()).throw(AssertionError("made"))),
        {"OPENAI_API_KEY": "sk-server", "REQUEST_TIMEOUT": 5, "SESSIONS_FILE": "x"})
    app = FastAPI()

    @app.middleware("http")
    async def _who(request, call_next):
        request.state.current_user = "ada"
        return await call_next(request)

    app.include_router(router)
    res = TestClient(app, raise_server_exceptions=False).post("/api/session/openai", data={})
    assert res.status_code == 400
    assert res.json()["detail"] == "Name a model: one OpenAI lists for this server's key."
