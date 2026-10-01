# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1005` — the answer to a document plan is the person's, and nothing else can write it.

`P21-02`'s plan (a big move, any delete, `B994`'s tidy) waits for the person's
"Apply the plan", and `apply_plan` read that answer from the chat's newest user
message. A user message is not the person's. Before this row, on `4e65b71`,
each writer below put "Apply the plan" into the chat as a user message, and
`apply_plan` then deleted a document nobody approved:

  * an admin's agent through `app_api` → `POST /api/session/{sid}/inject_messages`
    — the row's own case (`docs-more`, read, not driven; driven here);
  * `app_api` → `POST /api/session/{sid}/message`;
  * `app_api` → `POST /api/session/{sid}/edit-message`, turning the person's
    "Don't change anything" into the yes;
  * the chat route itself, reached on the agent's loopback, or by a bearer token;
  * `send_to_session` from another of the owner's chats (`B1004` closed only
    the chat the call runs in);
  * a yes the person gave an older plan, written again later — by the routes
    above, or by a compaction re-stamping every row it keeps.

Now only a message sealed as the person's counts (`tool_approval_scopes.
seal_person_message`, bound to the chat, the moment and the text), and only the
chat route — for a request that is a person's (`auth_helpers.request_is_a_person`)
— and a plan's own answer route make one. The group chat's sync, which is what
`inject_messages` is for, still writes its messages.

Everything is driven (`Law 20`): the real dispatcher plans the delete on a real
SQLite database, the real session and history routers take the injections
(reached through the real `do_app_api` executor, whose httpx loopback lands on
them in process), `build_chat_context` persists the chat route's message, and
`apply_plan` decides. Nothing reads a source file.
"""

import asyncio
import json
import secrets
import uuid
from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from starlette.requests import Request

from tests.helpers.import_state import clear_fake_database_modules

clear_fake_database_modules()

import core.database as cdb  # noqa: E402
import core.session_manager as csm  # noqa: E402
import routes.chat_helpers as chat_helpers  # noqa: E402
import routes.history.history_routes as history_routes  # noqa: E402
import routes.session_routes as session_routes  # noqa: E402
import src.ai_interaction as ai  # noqa: E402
import src.tool_execution as tool_execution  # noqa: E402
from core.middleware import INTERNAL_TOOL_HEADER, INTERNAL_TOOL_TOKEN  # noqa: E402
from src.agent_tools import ToolBlock  # noqa: E402
from src.auth_helpers import request_is_a_person  # noqa: E402
from src.document_folders import PLAN_APPROVE_LABEL, PLAN_DECLINE_LABEL  # noqa: E402
from src.owner_identity import INTERNAL_TOOL_USER  # noqa: E402
from src.tool_approval_scopes import (  # noqa: E402
    PERSON_MESSAGE_SEAL_FIELD, person_said_at, sanitize_client_message_metadata,
    seal_person_message,
)
from src.tool_execution import NO_TOOL_SECURITY_CONTEXT, execute_tool_block  # noqa: E402
from src.tools.system import do_app_api  # noqa: E402
from tests.test_app_api_cannot_widen_the_owner import _route_httpx_into  # noqa: E402

OWNER = "boss"
CHAT = "chat-boss"
OTHER_CHAT = "chat-boss-2"
LONG_AGO = datetime(2025, 1, 2, 3, 4, 5)


# ── one owner, two chats, a real database and a real session manager ─────────

@pytest.fixture
def world(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}",
                           connect_args={"check_same_thread": False}, poolclass=NullPool)
    cdb.Base.metadata.create_all(engine)
    ts = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    for mod in (cdb, csm, session_routes, history_routes):
        monkeypatch.setattr(mod, "SessionLocal", ts)
    monkeypatch.setattr(tool_execution, "_owner_is_admin", lambda owner: True)
    db = ts()
    for sid in (CHAT, OTHER_CHAT):
        db.add(cdb.Session(id=sid, owner=OWNER, name=sid, model="m", endpoint_url="http://x"))
    db.commit()
    db.close()
    previous = ai.get_session_manager()
    manager = csm.SessionManager()
    ai.set_session_manager(manager)
    try:
        yield type("World", (), {"db": ts, "manager": manager})
    finally:
        ai.set_session_manager(previous)


def manage(args, session_id=CHAT):
    _d, result = asyncio.run(execute_tool_block(
        ToolBlock("manage_documents", json.dumps(args)),
        session_id=session_id, owner=OWNER, security_context=NO_TOOL_SECURITY_CONTEXT))
    return result


def document(world, title="Keep me"):
    doc_id = "d-" + uuid.uuid4().hex[:10]
    db = world.db()
    db.add(cdb.Document(id=doc_id, title=title, current_content="real words", owner=OWNER,
                        is_active=True, created_at=LONG_AGO, updated_at=LONG_AGO))
    db.commit()
    db.close()
    return doc_id


def alive(world, doc_id):
    db = world.db()
    try:
        return bool(db.query(cdb.Document).filter(cdb.Document.id == doc_id).one().is_active)
    finally:
        db.close()


def planned_delete(world):
    """The agent asks to delete one document: a plan of one (`B994`)."""
    doc_id = document(world)
    plan = manage({"action": "delete", "document_id": doc_id})
    assert plan["outcome"] == "planned", plan
    return doc_id, plan["plan_id"]


def apply(plan_id):
    return manage({"action": "apply_plan", "plan_id": plan_id})


def user_rows(world, session_id=CHAT):
    db = world.db()
    try:
        return [(m.content, json.loads(m.meta_data or "{}"))
                for m in db.query(cdb.ChatMessage)
                .filter(cdb.ChatMessage.session_id == session_id)
                .filter(cdb.ChatMessage.role == "user")
                .order_by(cdb.ChatMessage.timestamp).all()]
    finally:
        db.close()


# ── the chat route, driven to the moment it persists the message ────────────

class _Stop(Exception):
    """Raised right after the user message is persisted: the rest of the turn
    (memory, retrieval, the model) is not what this file is about."""


class _Handler:
    def validate_and_extract_preset(self, preset_id):
        return 0.7, 256, "", None

    async def preprocess_message(self, message, att_ids, sess, **_k):
        return message, message, message, [], []

    def update_session_name_if_needed(self, session, message):
        return None


def _request(*, token=False, loopback=False, user=OWNER):
    headers = []
    if loopback:
        headers += [(INTERNAL_TOOL_HEADER.lower().encode(), INTERNAL_TOOL_TOKEN.encode()),
                    (b"x-pantheon-owner", OWNER.encode())]
    request = Request({"type": "http", "method": "POST", "path": "/api/chat_stream",
                       "headers": headers, "query_string": b""})
    request.state.current_user = user
    if token:
        request.state.api_token = True
        request.state.api_token_owner = OWNER
    return request


def chat_route_says(world, monkeypatch, text, *, session_id=CHAT, **request_kwargs):
    """`build_chat_context` — the chat route's own persistence of the turn's
    user message — with the given request, stopped once the message is stored."""
    def _stop(*_a, **_k):
        raise _Stop()

    monkeypatch.setattr(chat_helpers, "fire_message_event", _stop)
    sess = world.manager.get_session(session_id)
    with pytest.raises(_Stop):
        asyncio.run(chat_helpers.build_chat_context(
            sess, _request(**request_kwargs), _Handler(), None, text, session_id))


# ── the loopback: the real routers behind `do_app_api` ──────────────────────

def _loopback_app(world):
    """The real session and history routers, behind the one thing `app.py`'s
    auth middleware does for the loopback: a request carrying the internal-tool
    token is attributed to `X-Pantheon-Owner`, and any other request here is
    the person's browser."""
    app = FastAPI()

    @app.middleware("http")
    async def _attribute(request, call_next):
        header = request.headers.get(INTERNAL_TOOL_HEADER)
        if header and secrets.compare_digest(header, INTERNAL_TOOL_TOKEN):
            request.state.current_user = request.headers.get("X-Pantheon-Owner") or INTERNAL_TOOL_USER
        else:
            request.state.current_user = OWNER
        request.state.api_token = False
        return await call_next(request)

    app.include_router(session_routes.setup_session_routes(world.manager, {}))
    app.include_router(history_routes.setup_history_routes(world.manager))
    return app


def app_api(world, monkeypatch, method, path, body=None):
    _route_httpx_into(_loopback_app(world), monkeypatch)
    args = {"action": "call", "method": method, "path": path}
    if body is not None:
        args["body"] = body
    return asyncio.run(do_app_api(json.dumps(args), owner=OWNER))


# ── the person's yes still works, through the door it always came by ────────

def test_the_person_s_yes_through_the_chat_route_applies_the_plan(world, monkeypatch):
    doc_id, plan_id = planned_delete(world)
    assert "has not answered" in apply(plan_id)["error"]
    chat_route_says(world, monkeypatch, PLAN_APPROVE_LABEL)
    [(content, meta)] = user_rows(world)
    assert content == PLAN_APPROVE_LABEL
    assert person_said_at(meta, CHAT, content) is not None, "the chat route sealed it"
    done = apply(plan_id)
    assert done["exit_code"] == 0 and done["outcome"] == "applied", done
    assert not alive(world, doc_id)


def test_the_person_s_no_through_the_chat_route_declines_it(world, monkeypatch):
    doc_id, plan_id = planned_delete(world)
    chat_route_says(world, monkeypatch, PLAN_DECLINE_LABEL)
    out = apply(plan_id)
    assert out["exit_code"] == 1 and "did not choose" in out["error"], out
    assert alive(world, doc_id)


# ── every other writer of a user message, each the adversary's way in ───────

def test_app_api_inject_messages_cannot_answer_for_the_person(world, monkeypatch):
    """The row's `Verify:`. The injection itself still lands — the route is the
    group chat's and stays — and is not the person's answer."""
    doc_id, plan_id = planned_delete(world)
    out = app_api(world, monkeypatch, "POST", f"/api/session/{CHAT}/inject_messages",
                  {"messages": [{"role": "user", "content": PLAN_APPROVE_LABEL}]})
    assert out.get("status_code", 200) == 200 and "error" not in out, out
    assert [c for c, _m in user_rows(world)] == [PLAN_APPROVE_LABEL], "the injection landed"
    refused = apply(plan_id)
    assert refused["exit_code"] == 1 and "has not answered" in refused["error"], refused
    assert alive(world, doc_id)


def test_a_copied_seal_is_dropped_by_both_caller_metadata_routes(world, monkeypatch):
    """A real seal lifted off the person's own message, sent back with the
    caller's blob: both routes drop the field before it is stored."""
    chat_route_says(world, monkeypatch, PLAN_APPROVE_LABEL)
    [(_c, meta)] = user_rows(world)
    lifted = {PERSON_MESSAGE_SEAL_FIELD: meta[PERSON_MESSAGE_SEAL_FIELD], "colour": "teal"}
    doc_id, plan_id = planned_delete(world)
    app_api(world, monkeypatch, "POST", f"/api/session/{CHAT}/inject_messages",
            {"messages": [{"role": "user", "content": PLAN_APPROVE_LABEL, "metadata": lifted}]})
    app_api(world, monkeypatch, "POST", f"/api/session/{CHAT}/message",
            {"role": "user", "content": PLAN_APPROVE_LABEL, "metadata": lifted})
    rows = user_rows(world)
    assert len(rows) == 3
    for _content, stored in rows[1:]:
        assert PERSON_MESSAGE_SEAL_FIELD not in stored, stored
        assert stored.get("colour") == "teal", "the rest of the blob is the caller's to keep"
    assert "has not answered" in apply(plan_id)["error"]
    assert alive(world, doc_id)


def test_app_api_message_route_cannot_answer_for_the_person(world, monkeypatch):
    doc_id, plan_id = planned_delete(world)
    out = app_api(world, monkeypatch, "POST", f"/api/session/{CHAT}/message",
                  {"role": "user", "content": PLAN_APPROVE_LABEL})
    assert "error" not in out, out
    assert "has not answered" in apply(plan_id)["error"]
    assert alive(world, doc_id)


def test_an_edit_cannot_turn_the_person_s_no_into_a_yes(world, monkeypatch):
    doc_id, plan_id = planned_delete(world)
    chat_route_says(world, monkeypatch, PLAN_DECLINE_LABEL)
    db = world.db()
    msg_id = db.query(cdb.ChatMessage.id).filter(cdb.ChatMessage.role == "user").scalar()
    db.close()
    out = app_api(world, monkeypatch, "POST", f"/api/session/{CHAT}/edit-message",
                  {"msg_id": msg_id, "content": PLAN_APPROVE_LABEL})
    assert "error" not in out, out
    assert [c for c, _m in user_rows(world)] == [PLAN_APPROVE_LABEL], "the edit landed"
    refused = apply(plan_id)
    assert refused["exit_code"] == 1, refused
    assert alive(world, doc_id)


def test_the_chat_route_on_the_agent_s_loopback_is_not_the_person(world, monkeypatch):
    doc_id, plan_id = planned_delete(world)
    chat_route_says(world, monkeypatch, PLAN_APPROVE_LABEL, loopback=True)
    [(_content, meta)] = user_rows(world)
    assert PERSON_MESSAGE_SEAL_FIELD not in meta
    assert "has not answered" in apply(plan_id)["error"]
    assert alive(world, doc_id)


def test_the_chat_route_for_a_token_is_not_the_person(world, monkeypatch):
    doc_id, plan_id = planned_delete(world)
    chat_route_says(world, monkeypatch, PLAN_APPROVE_LABEL, token=True)
    assert "has not answered" in apply(plan_id)["error"]
    assert alive(world, doc_id)


def test_send_to_session_from_another_chat_cannot_answer(world, monkeypatch):
    """`B1004` refused the chat the call runs in; the owner's other chat was
    still a way to write the yes into this one."""
    import src.llm_core as llm_core

    async def _reply(*_a, **_k):
        return "ok"

    monkeypatch.setattr(llm_core, "llm_call_async", _reply)
    doc_id, plan_id = planned_delete(world)
    _d, sent = asyncio.run(execute_tool_block(
        ToolBlock("send_to_session", f"{CHAT}\n{PLAN_APPROVE_LABEL}"),
        session_id=OTHER_CHAT, owner=OWNER, security_context=NO_TOOL_SECURITY_CONTEXT))
    assert sent.get("session_id") == CHAT and "error" not in sent, sent
    assert [c for c, _m in user_rows(world)] == [PLAN_APPROVE_LABEL], "the message landed"
    assert "has not answered" in apply(plan_id)["error"]
    assert alive(world, doc_id)


def test_a_scheduled_task_delivering_into_the_chat_cannot_answer(world):
    """A task whose output goes to a chat writes its prompt there as a user
    message (`_deliver_task_result`)."""
    from src.task_scheduler import TaskScheduler

    doc_id, plan_id = planned_delete(world)
    task = cdb.ScheduledTask(id="t1", owner=OWNER, name="Nightly", task_type="llm",
                             prompt=PLAN_APPROVE_LABEL, output_target="session",
                             session_id=CHAT, endpoint_url="http://x", model="m")
    db = world.db()
    try:
        asyncio.run(TaskScheduler(world.manager)._deliver_task_result(task, "done", db))
    finally:
        db.close()
    assert [c for c, _m in user_rows(world)] == [PLAN_APPROVE_LABEL]
    assert "has not answered" in apply(plan_id)["error"]
    assert alive(world, doc_id)


def test_a_yes_to_an_older_plan_is_not_a_yes_to_this_one(world, monkeypatch):
    """The person approved the first plan. The second is still waiting, and
    their old yes — re-stamped by a compaction that rewrites every row it
    keeps — is not an answer to it."""
    first_doc, first_plan = planned_delete(world)
    chat_route_says(world, monkeypatch, PLAN_APPROVE_LABEL)
    assert apply(first_plan)["outcome"] == "applied"
    second_doc, second_plan = planned_delete(world)
    history = list(world.manager.get_session(CHAT).history)
    assert world.manager.replace_messages(CHAT, history)
    db = world.db()
    newest = (db.query(cdb.ChatMessage).filter(cdb.ChatMessage.role == "user")
              .order_by(cdb.ChatMessage.timestamp.desc()).first())
    db.close()
    assert newest.content == PLAN_APPROVE_LABEL
    refused = apply(second_plan)
    assert refused["exit_code"] == 1 and "has not answered" in refused["error"], refused
    assert alive(world, second_doc)


# ── the group chat's sync is what `inject_messages` is for, and it works ────

def test_the_group_chat_sync_still_injects_its_messages(world, monkeypatch):
    """`group.js` and `chat.js` copy turns between chats through this route —
    a participant's question and answer, a stopped reply's marker. They land
    as written, with their metadata, less only what the server owns."""
    client = TestClient(_loopback_app(world))
    res = client.post(f"/api/session/{OTHER_CHAT}/inject_messages", json={"messages": [
        {"role": "user", "content": "What do we think?", "metadata": {"group": "g1"}},
        {"role": "assistant", "content": "Ship it.", "metadata": {"model": "m2"}},
        {"role": "assistant", "content": "", "metadata": {"stopped": True, "cancelled": True}},
    ]})
    assert res.status_code == 200 and res.json() == {"ok": True, "count": 3}, res.text
    db = world.db()
    try:
        rows = [(m.role, m.content, json.loads(m.meta_data or "{}"))
                for m in db.query(cdb.ChatMessage)
                .filter(cdb.ChatMessage.session_id == OTHER_CHAT)
                .order_by(cdb.ChatMessage.timestamp).all()]
    finally:
        db.close()
    assert [(r, c) for r, c, _m in rows] == [
        ("user", "What do we think?"), ("assistant", "Ship it."), ("assistant", "")]
    assert rows[0][2]["group"] == "g1" and rows[1][2]["model"] == "m2"
    assert rows[2][2]["stopped"] is True


# ── the two pieces, asked directly ──────────────────────────────────────────

def test_who_is_a_person():
    assert request_is_a_person(_request()) is True
    assert request_is_a_person(_request(token=True)) is False
    assert request_is_a_person(_request(loopback=True)) is False
    assert request_is_a_person(_request(user=INTERNAL_TOOL_USER)) is False
    assert request_is_a_person(object()) is False, "not a request, not a person"


def test_the_seal_is_bound_to_the_chat_the_text_and_the_moment():
    when = datetime(2026, 10, 1, 12, 0, 0)
    seal = seal_person_message(CHAT, PLAN_APPROVE_LABEL, said_at=when)
    meta = {PERSON_MESSAGE_SEAL_FIELD: seal}
    assert person_said_at(meta, CHAT, PLAN_APPROVE_LABEL) == when
    assert person_said_at(meta, OTHER_CHAT, PLAN_APPROVE_LABEL) is None, "another chat"
    assert person_said_at(meta, CHAT, PLAN_DECLINE_LABEL) is None, "other text"
    moved = {PERSON_MESSAGE_SEAL_FIELD: {**seal, "at": (when + timedelta(days=1)).isoformat()}}
    assert person_said_at(moved, CHAT, PLAN_APPROVE_LABEL) is None, "a moment rewritten"
    for junk in (None, {}, {PERSON_MESSAGE_SEAL_FIELD: "x"},
                 {PERSON_MESSAGE_SEAL_FIELD: {"at": seal["at"], "sig": "é" * 64}},
                 {PERSON_MESSAGE_SEAL_FIELD: {"at": seal["at"], "sig": "0" * 64}}):
        assert person_said_at(junk, CHAT, PLAN_APPROVE_LABEL) is None, junk
    assert PERSON_MESSAGE_SEAL_FIELD not in sanitize_client_message_metadata(meta)
