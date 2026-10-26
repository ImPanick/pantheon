# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1507` — a live user bubble carries its row id.

Only replies were given their row id on the stream (`message_saved`). The
person's bubble — drawn by the composer before the request goes out — had none
until a reload, so deleting a just-sent turn named only the reply: the delete
removed both bubbles, the server removed one row, and the person's message came
back on the next reload and stayed in every prompt after it (`B1331`'s refusal
covers a pair with *no* id, not a pair with one).

Now the stream says the person's row first thing (`user_message_saved`), read
off the message the turn stored (`add_user_message` returns it), and the
browser puts it on the bubble the send drew — or on the one an edit or a
regenerate kept, whose old row their trim removed.

Driven (`Law 20`):

  * the real `add_user_message` over a real `SessionManager` and SQLite file
    returns the message with the id of the row it wrote; the real
    `delete-messages` route given both ids leaves a reload with neither;
  * `/api/chat_stream` (the route harness `test_foreground_model_routing.py`
    built) announces that id before the reply, and announces nothing for a turn
    that stored no message;
  * the two arms cut out of `chat.js`'s live stream put the ids on the bubbles,
    and the real `deleteMessage` then posts both.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import textwrap
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

import core.database as cdb
import routes.chat_routes as chat_routes
from core.database import Session as DbSession
from core.models import ChatMessage
from tests.helpers.js_source import js_definition
from tests.helpers.source_text import blank_text
import test_a_resumed_stream_draws_what_the_live_one_drew as streams  # noqa: E402
from test_foreground_model_routing import _RouteRequest, _chat_stream_endpoint  # noqa: E402


# ── the row, stored and deleted ─────────────────────────────────────────────

@pytest.fixture()
def store(monkeypatch, tmp_path):
    import core.models as models
    import core.session_manager as smod
    import routes.history_routes as history_routes
    import routes.session_routes as session_routes

    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}",
                           connect_args={"check_same_thread": False}, poolclass=NullPool)
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    for mod in (smod, session_routes, history_routes):
        monkeypatch.setattr(mod, "SessionLocal", factory)
    monkeypatch.setattr(history_routes, "_verify_session_owner", lambda request, sid: None)
    db = factory()
    db.add(DbSession(id="c1", owner="ann", name="a chat", endpoint_url="x", model="m"))
    db.commit()
    db.close()
    manager = smod.SessionManager()
    monkeypatch.setattr(models, "_SESSION_MANAGER_INSTANCE", manager)
    return smod, history_routes, manager


def test_the_stored_message_comes_back_with_its_row_id(store):
    from routes.chat_helpers import add_user_message

    smod, history_routes, manager = store
    sess = manager.get_session("c1")
    handler = SimpleNamespace(update_session_name_if_needed=lambda *a, **k: None)
    said = add_user_message(sess, handler, SimpleNamespace(
        user_content="hello", attachment_meta=None, text_for_context="hello"))
    assert said is not None and said.content == "hello"
    sess.add_message(ChatMessage("assistant", "Hi."))
    reply_id = sess.history[-1].metadata["_db_id"]

    stored = [m.metadata["_db_id"] for m in smod.SessionManager().get_session("c1").history]
    assert stored == [said.metadata["_db_id"], reply_id]

    # The pair deleted by both ids, as the page now can before a reload.
    app = FastAPI()
    app.include_router(history_routes.setup_history_routes(manager))
    res = TestClient(app).post("/api/session/c1/delete-messages",
                               json={"msg_ids": [said.metadata["_db_id"], reply_id]})
    assert res.status_code == 200, res.text
    fresh = smod.SessionManager()
    fresh.sessions.pop("c1", None)
    reload_app = FastAPI()
    reload_app.include_router(history_routes.setup_history_routes(fresh))
    assert TestClient(reload_app).get("/api/history/c1?limit=24").json()["history"] == []


def test_an_incognito_turn_stores_and_returns_nothing(store):
    from routes.chat_helpers import add_user_message

    _smod, _hr, manager = store
    sess = manager.get_session("c1")
    handler = SimpleNamespace(update_session_name_if_needed=lambda *a, **k: None)
    assert add_user_message(sess, handler, SimpleNamespace(
        user_content="psst", attachment_meta=None, text_for_context="psst"), incognito=True) is None
    assert sess.history == []


# ── the stream says it ──────────────────────────────────────────────────────

def _events(monkeypatch, **context):
    captured = {}
    endpoint = _chat_stream_endpoint(monkeypatch, "chat", captured, context_overrides=context)
    monkeypatch.setattr(chat_routes, "save_assistant_response", lambda *a, **k: None)

    async def go():
        response = await endpoint(_RouteRequest("chat"))
        return [c async for c in response.body_iterator]

    out = []
    for chunk in asyncio.run(go()):
        for line in chunk.splitlines():
            if line.startswith("data: ") and line[6:].strip().startswith("{"):
                out.append(json.loads(line[6:]))
    return out


def test_the_stream_names_the_persons_row_before_the_reply(monkeypatch):
    said = ChatMessage("user", "hello", metadata={"_db_id": "row-u1"})
    events = _events(monkeypatch, user_message=said)
    saved = [e for e in events if e.get("type") == "user_message_saved"]
    assert saved == [{"type": "user_message_saved", "id": "row-u1"}]
    first_delta = next(i for i, e in enumerate(events) if "delta" in e)
    assert events.index(saved[0]) < first_delta


def test_a_turn_that_stored_no_message_names_none(monkeypatch):
    assert not [e for e in _events(monkeypatch, user_message=None) if e.get("type") == "user_message_saved"]


# ── the page puts it on the bubble, and the delete names both ───────────────

_PAGE = r"""
class El {
  constructor(cls) { this.className = cls; this.dataset = {}; this.parentNode = null; this.children = []; this.isConnected = true; }
  get classList() { const s = this; return { contains: (c) => s.className.split(/\s+/).includes(c) }; }
  appendChild(n) { n.parentNode = this; this.children.push(n); return n; }
  get nextElementSibling() { const k = this.parentNode.children; return k[k.indexOf(this) + 1] || null; }
  remove() { const k = this.parentNode.children; k.splice(k.indexOf(this), 1); this.isConnected = false; }
  querySelectorAll(sel) { return this.children.filter((n) => n.classList.contains(sel.replace('.', ''))); }
  querySelector() { return null; }
}
const box = new El('chat-history');
globalThis.document = { getElementById: (id) => (id === 'chat-history' ? box : null) };
const posted = [];
globalThis.fetch = async (url, init) => { posted.push({ url, body: JSON.parse(init.body) }); return { ok: true }; };
const API_BASE = '';
const sessionModule = { getCurrentSessionId: () => 's1' };
const uiModule = { styledConfirm: async () => true, showToast() {}, showError(m) { posted.push({ error: m }); } };
const chatRenderer = { showWelcomeScreen() {} };
const readRefusal = async () => ({ sentence: 'refused' });
const refreshChatContextHeader = () => {};
"""


def _delete_message() -> str:
    src = streams._chat()
    at = blank_text(src, "js").index("export async function deleteMessage(")
    return js_definition(src, at + len("export "))


def _run_page(script: str) -> dict:
    user_arm = streams._arm("} else if (json.type === 'user_message_saved') {")
    reply_arm = streams._arm("} else if (json.type === 'message_saved') {")
    body = _PAGE + _delete_message() + textwrap.dedent("""
        function feed(events, { _userMsgEl, holder, _resendBubble = null, _isBg = false }) {
          for (const json of events) {
            if (json.type === 'user_message_saved') %s
            else if (json.type === 'message_saved') %s
          }
        }
    """) % (user_arm, reply_arm) + textwrap.dedent(script)
    out = subprocess.run(["node", "--input-type=module"], input=body, capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


@pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")
def test_a_turn_deleted_before_a_reload_names_both_rows():
    out = _run_page("""
        const mine = box.appendChild(new El('msg msg-user'));
        const reply = box.appendChild(new El('msg msg-ai'));
        feed([{ type: 'user_message_saved', id: 'row-u1' }, { type: 'message_saved', id: 'row-a1' }],
             { _userMsgEl: mine, holder: reply });
        await deleteMessage(mine);
        console.log(JSON.stringify({ posted, left: box.children.length }));
    """)
    assert out["posted"] == [{"url": "/api/session/s1/delete-messages", "body": {"msg_ids": ["row-u1", "row-a1"]}}]
    assert out["left"] == 0


@pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")
def test_a_regenerated_turn_gives_the_kept_bubble_its_new_row():
    """An edit or a regenerate trims from the person's message and sends it
    again, keeping the bubble: the stored row is new, and the bubble takes it."""
    out = _run_page("""
        const kept = box.appendChild(new El('msg msg-user'));
        kept.dataset.dbId = 'row-old';
        const reply = box.appendChild(new El('msg msg-ai'));
        feed([{ type: 'user_message_saved', id: 'row-new' }], { _userMsgEl: null, _resendBubble: kept, holder: reply });
        const background = box.appendChild(new El('msg msg-user'));
        feed([{ type: 'user_message_saved', id: 'row-elsewhere' }], { _userMsgEl: background, holder: reply, _isBg: true });
        console.log(JSON.stringify({ kept: kept.dataset.dbId, background: background.dataset.dbId || null }));
    """)
    assert out == {"kept": "row-new", "background": None}
