# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P8-23` — a trigger says which thing happened, not just that something did.

`fire_event(name, owner)` was the entire payload of the event bus, and the
webhook route had **no request parameter at all** — body, query and headers
were read by nobody. So "when a document is updated, summarise it" ran a task
that could not be told which document, and a POST carrying a GitHub issue rang
a doorbell. `B602` is the measurement: four of the eight catalogued events could
not name what fired them, including the `document_updated` that `P8-30` had just
added to the picker.

Everything here drives the real path (`Law 20`): the bus's own `_handle_event`,
the route handler with a real `starlette` request, and `_execute_llm_task` down
to the message list `stream_agent_loop` is handed.
"""

import asyncio
import json
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from starlette.requests import Request

from tests.helpers.import_state import clear_fake_database_modules

clear_fake_database_modules()

import core.database as cdb  # noqa: E402
import src.event_bus as eb  # noqa: E402
from core.database import ScheduledTask, TaskRun  # noqa: E402
from src.task_scheduler import TaskScheduler  # noqa: E402

_REAL_DATABASE_ATTRS = {
    "Base": cdb.Base,
    "SessionLocal": cdb.SessionLocal,
    "ScheduledTask": ScheduledTask,
    "TaskRun": TaskRun,
}


@pytest.fixture()
def task_db(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "core.database", cdb)
    for attr, value in _REAL_DATABASE_ATTRS.items():
        monkeypatch.setattr(cdb, attr, value, raising=False)
    engine = create_engine(
        f"sqlite:///{tmp_path / 'triggers.db'}",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(cdb, "SessionLocal", factory)
    return factory


def _seed(factory, **over):
    fields = dict(
        id="t1", owner=None, name="Summarise it", prompt="Summarise the document",
        task_type="action", action="tidy_sessions", trigger_type="event",
        trigger_event=eb.EVENT_DOCUMENT_UPDATED, trigger_count=1,
        status="active", output_target="session", webhook_token="tok",
    )
    fields.update(over)
    db = factory()
    try:
        db.add(ScheduledTask(**fields))
        db.commit()
    finally:
        db.close()


def _scheduler():
    s = TaskScheduler.__new__(TaskScheduler)
    s._task_handles = {}
    s._task_defer_counts = {}
    s._session_manager = None
    s._notify_run_outcome = MagicMock(return_value=True)
    s.add_notification = MagicMock()
    s._log_to_assistant = MagicMock()
    return s


# ── the bus ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_document_updated_trigger_names_the_document(task_db, monkeypatch):
    """`B602`'s own Verify line, driven through the bus rather than asserted
    about: fire the event the email server fires, with the document it fired
    for, and read what the scheduler was handed."""
    _seed(task_db)
    got = {}

    class _Sched:
        async def run_task_now(self, task_id, *, trigger=None):
            got["task_id"] = task_id
            got["trigger"] = trigger
            return True

    monkeypatch.setattr(eb, "_task_scheduler", _Sched(), raising=False)
    monkeypatch.setattr(eb, "_resolve_event_owner", lambda owner: None)

    await eb._handle_event(
        eb.EVENT_DOCUMENT_UPDATED, None,
        {"document_id": "doc-42", "title": "Q3 plan"},
    )

    assert got["task_id"] == "t1"
    trigger = got["trigger"]
    assert trigger["event"] == eb.EVENT_DOCUMENT_UPDATED
    assert trigger["source"] == eb.TRIGGER_SOURCE_EVENT
    assert trigger["data"] == {"document_id": "doc-42", "title": "Q3 plan"}


def test_the_catalogue_is_the_schema_for_a_payload():
    """A producer that invents a field does not get to start a second shape.
    The dropped key is the test: without the filter the envelope is whatever
    the last caller felt like sending."""
    built = eb.build_trigger(
        eb.TRIGGER_SOURCE_EVENT, eb.EVENT_DOCUMENT_UPDATED,
        {"document_id": "d1", "title": "T", "author_api_key": "sk-live-x"},
    )
    assert built["data"] == {"document_id": "d1", "title": "T"}
    assert "author_api_key" not in built["data"]


def test_every_catalogued_event_declares_what_it_hands_over():
    """`Law 15`. The picker can only say what a trigger gives you if every
    entry says so — including the one added last."""
    for entry in eb.EVENT_CATALOGUE:
        assert entry.get("payload"), entry["name"]
        assert entry.get("payload_summary"), entry["name"]
        assert set(entry["payload"]) == set(eb.EVENT_PAYLOAD_FIELDS[entry["name"]])


def test_a_trigger_with_no_payload_says_so_rather_than_nothing():
    """`Law 10`. "No payload" and "the payload was lost" are different facts
    and an empty string cannot tell them apart."""
    bare = eb.build_trigger(eb.TRIGGER_SOURCE_EVENT, eb.EVENT_SKILL_ADDED, None)
    assert bare["data"] == {}
    assert "no payload" in eb.trigger_summary(bare)


# ── the webhook ────────────────────────────────────────────────────────────

def _request(body: bytes, query: bytes = b"", headers=()):
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/tasks/t1/webhook/tok",
        "query_string": query,
        "headers": list(headers),
    }
    return Request(scope, receive)


def _webhook_endpoint(scheduler):
    import routes.task_routes as task_routes

    router = task_routes.setup_task_routes(scheduler)
    for route in router.routes:
        if getattr(route, "path", None) == "/api/tasks/{task_id}/webhook/{token}":
            return route.endpoint
    raise RuntimeError("webhook route not found")


@pytest.mark.asyncio
async def test_the_webhook_carries_the_request_it_was_sent(task_db, monkeypatch):
    """The route is a doorbell no longer: body, query and an allowlisted header
    all reach the run."""
    import routes.task_routes as task_routes
    monkeypatch.setattr(task_routes, "SessionLocal", task_db)
    _seed(task_db, trigger_type="webhook", trigger_event=None)

    got = {}

    class _Sched:
        async def run_task_now(self, task_id, *, trigger=None):
            got["trigger"] = trigger
            return True

    endpoint = _webhook_endpoint(_Sched())
    out = await endpoint(
        "t1", "tok",
        _request(
            b'{"issue": {"title": "Ship it"}}',
            query=b"ref=main",
            headers=[(b"content-type", b"application/json"),
                     (b"user-agent", b"GitHub-Hookshot/1")],
        ),
    )

    assert out["ok"] is True
    data = got["trigger"]["data"]
    assert got["trigger"]["source"] == eb.TRIGGER_SOURCE_WEBHOOK
    assert data["json"] == {"issue": {"title": "Ship it"}}
    assert data["query"] == {"ref": "main"}
    assert data["headers"]["user-agent"] == "GitHub-Hookshot/1"


@pytest.mark.asyncio
async def test_the_webhook_does_not_carry_a_signature_header(task_db, monkeypatch):
    """A signature is a secret, and this payload ends up in a model prompt and
    in a row a person reads. The header allowlist is what keeps it out."""
    import routes.task_routes as task_routes
    monkeypatch.setattr(task_routes, "SessionLocal", task_db)
    _seed(task_db, trigger_type="webhook", trigger_event=None)

    got = {}

    class _Sched:
        async def run_task_now(self, task_id, *, trigger=None):
            got["trigger"] = trigger
            return True

    endpoint = _webhook_endpoint(_Sched())
    await endpoint(
        "t1", "tok",
        _request(b"{}", headers=[(b"x-hub-signature-256", b"sha256=deadbeef"),
                                 (b"authorization", b"Bearer hunter2"),
                                 (b"user-agent", b"curl/8")]),
    )
    headers = got["trigger"]["data"].get("headers", {})
    assert set(headers) == {"user-agent"}


@pytest.mark.asyncio
async def test_an_empty_webhook_still_rings_the_doorbell(task_db, monkeypatch):
    """`Law 1`. Every caller that worked before this row works unchanged: no
    body, no query, no headers, and the task still runs."""
    import routes.task_routes as task_routes
    monkeypatch.setattr(task_routes, "SessionLocal", task_db)
    _seed(task_db, trigger_type="webhook", trigger_event=None)

    got = {}

    class _Sched:
        async def run_task_now(self, task_id, *, trigger=None):
            got["trigger"] = trigger
            return True

    endpoint = _webhook_endpoint(_Sched())
    out = await endpoint("t1", "tok", _request(b""))
    assert out["ok"] is True
    assert got["trigger"]["data"] == {}


# ── what the task is given ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_payload_reaches_the_model_as_untrusted_data(task_db, monkeypatch):
    """The whole point of the row, and the security shape of it.

    Three of the eight producers carry text somebody else chose, and the
    webhook's route is unauthenticated, so the payload is wrapped by
    `src.prompt_security` rather than pasted into the prompt — which also arms
    the post-external blocked-effect gate (`FORBIDDEN.md` Part 2) for the run.
    """
    captured = {}

    async def fake_stream(**kwargs):
        captured["messages"] = kwargs.get("messages")
        yield 'data: {"delta": "ok"}\n\n'
        yield "data: [DONE]\n\n"

    import src.agent_loop as agent_loop
    monkeypatch.setattr(agent_loop, "stream_agent_loop", fake_stream, raising=False)
    monkeypatch.setattr("src.tool_index.get_tool_index", lambda: None)

    sched = _scheduler()
    sched._state_for("r9")["trigger"] = eb.build_trigger(
        eb.TRIGGER_SOURCE_EVENT, eb.EVENT_DOCUMENT_UPDATED,
        {"document_id": "doc-42", "title": "Q3 plan"},
    )
    task = SimpleNamespace(
        id="t1", name="Summarise it", prompt="Summarise the document that changed",
        owner=None, max_steps=3, crew_member_id=None, character_id=None,
        endpoint_url="http://endpoint", model="m", session_id="sess-1",
    )
    await sched._execute_llm_task(task, db=None, run_id="r9")

    messages = captured["messages"]
    wrapped = [m for m in messages
               if isinstance(m.get("metadata"), dict)
               and m["metadata"].get("trusted") is False]
    assert wrapped, "the trigger payload never reached the model"
    body = wrapped[0]["content"]
    assert "doc-42" in body and "Q3 plan" in body
    from src.prompt_security import GUARD_OPEN, GUARD_CLOSE
    assert GUARD_OPEN in body and GUARD_CLOSE in body

    # The gate this arms is the one that must never lift. Asked of the function
    # that actually decides, not of the marker it reads.
    from src.tool_capabilities import messages_contain_external_untrusted_context
    assert messages_contain_external_untrusted_context(messages)

    # And the prompt itself is untouched — the payload is an extra message, not
    # a rewrite of what the person typed.
    assert messages[-1]["content"] == "Summarise the document that changed"


@pytest.mark.asyncio
async def test_a_run_with_no_trigger_is_unchanged(task_db, monkeypatch):
    """`Law 1`. Every scheduled run in the product has no trigger payload, and
    those build exactly the message list they built before this row."""
    captured = {}

    async def fake_stream(**kwargs):
        captured["messages"] = kwargs.get("messages")
        yield 'data: {"delta": "ok"}\n\n'
        yield "data: [DONE]\n\n"

    import src.agent_loop as agent_loop
    monkeypatch.setattr(agent_loop, "stream_agent_loop", fake_stream, raising=False)
    monkeypatch.setattr("src.tool_index.get_tool_index", lambda: None)

    sched = _scheduler()
    task = SimpleNamespace(
        id="t1", name="Nightly", prompt="do the thing", owner=None, max_steps=3,
        crew_member_id=None, character_id=None,
        endpoint_url="http://endpoint", model="m", session_id="sess-1",
    )
    await sched._execute_llm_task(task, db=None, run_id="r10")

    assert not [m for m in captured["messages"]
                if isinstance(m.get("metadata"), dict)]


@pytest.mark.asyncio
async def test_the_step_log_names_what_fired_the_run(task_db, monkeypatch):
    """Whoever opens a run wants to know what set it off. It is step one."""
    _seed(task_db)
    db = task_db()
    try:
        db.add(TaskRun(id="r1", task_id="t1", status="queued"))
        db.commit()
    finally:
        db.close()

    import src.builtin_actions as ba

    async def fake_action(owner=None, task_name="", progress_cb=None, **kwargs):
        progress_cb("Read the document")
        return "Summarised", True

    monkeypatch.setitem(ba.BUILTIN_ACTIONS, "tidy_sessions", fake_action)

    sched = _scheduler()
    await sched._execute_task_locked(
        "t1", "r1", gate_foreground=False, release_executing=False,
        trigger=eb.build_trigger(
            eb.TRIGGER_SOURCE_EVENT, eb.EVENT_DOCUMENT_UPDATED,
            {"document_id": "doc-42", "title": "Q3 plan"}),
    )

    db = task_db()
    try:
        steps = json.loads(db.query(TaskRun).filter(TaskRun.id == "r1").first().steps)
    finally:
        db.close()

    assert steps[0]["kind"] == "trigger"
    assert "doc-42" in steps[0]["detail"]
    assert [s["kind"] for s in steps] == ["trigger", "progress"]
