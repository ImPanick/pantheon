# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1331` (fx7-dup) — a reloaded chat's bubbles carry their row ids, and a
delete that removes nothing says so.

`/api/history?limit=24` — the only way `sessions.js` asks — built its entries
from the rows (`_db_history_entry`) without the row's id, so after a reload no
bubble had `data-db-id`: *Edit message* answered *"Cannot edit: message ID not
found"*, and *Delete message* removed the bubbles, found no ids, and said
*Message deleted* while the rows stayed in the chat and in the prompt. The
route, asked with no ids, answered `{"status": "ok", "deleted": 0}`.

Now each paged entry carries `_db_id` (the row's own id, set over any copied
one), the route refuses a delete that names nothing or removes nothing, and
`deleteMessage` refuses rather than pretends when a bubble has no id.

Driven (`Law 20`): the real routes over a real SQLite file; the real
`addMessage` draws a paged entry; the real `deleteMessage`, cut out of
`chat.js`, over the DOM shim.
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

import core.database as cdb
from core.database import ChatMessage as DbMessage
from core.database import Session as DbSession
from tests.helpers.esc_stub import ui_default_stub  # B874
from test_chat_actions_say_what_they_do import _cut  # noqa: E402
from test_tool_effect_surfaces_js import _CARD_SHIM, _CARD_STUBS, _make_sandbox, _run  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"
node_only = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


@pytest.fixture()
def chat(monkeypatch, tmp_path):
    import core.session_manager as smod
    import routes.history_routes as history_routes
    import routes.session_routes as session_routes

    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}", connect_args={"check_same_thread": False},
                           poolclass=NullPool)
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    for mod in (smod, session_routes, history_routes):
        monkeypatch.setattr(mod, "SessionLocal", factory)
    db = factory()
    db.add(DbSession(id="c1", owner="ann", name="a chat", endpoint_url="x", model="m"))
    for i in range(4):
        # A forked row carries its source's `_db_id` in its stored metadata.
        meta = json.dumps({"_db_id": "the-source-row"}) if i == 3 else None
        db.add(DbMessage(id=f"row-{i}", session_id="c1", role="user" if i % 2 == 0 else "assistant",
                         content=f"line {i}", meta_data=meta, timestamp=datetime(2026, 1, 1, 0, i)))
    db.commit()
    db.close()
    monkeypatch.setattr(session_routes, "effective_user", lambda request: "ann")
    app = FastAPI()
    app.include_router(history_routes.setup_history_routes(smod.SessionManager()))

    def rows():
        d = factory()
        try:
            return [r.id for r in d.query(DbMessage).order_by(DbMessage.timestamp).all()]
        finally:
            d.close()

    return TestClient(app), rows


def test_a_paged_entry_carries_its_rows_id(chat):
    client, _ = chat
    page = client.get("/api/history/c1?limit=24").json()
    assert [e["metadata"]["_db_id"] for e in page["history"]] == ["row-0", "row-1", "row-2", "row-3"]


def test_deleting_a_reloaded_bubble_removes_its_row(chat):
    client, rows = chat
    page = client.get("/api/history/c1?limit=24").json()
    ids = [e["metadata"]["_db_id"] for e in page["history"][2:]]
    res = client.post("/api/session/c1/delete-messages", json={"msg_ids": ids})
    assert res.status_code == 200 and res.json() == {"status": "ok", "deleted": 2}
    assert rows() == ["row-0", "row-1"]
    assert [e["content"] for e in client.get("/api/history/c1?limit=24").json()["history"]] == ["line 0", "line 1"]


@pytest.mark.parametrize("body, status, words", [
    ({"msg_ids": []}, 400, "no saved message was named"),
    ({}, 400, "no saved message was named"),
    ({"msg_ids": ["not-a-row"]}, 404, "no longer in this chat"),
])
def test_a_delete_that_removes_nothing_says_so(chat, body, status, words):
    client, rows = chat
    res = client.post("/api/session/c1/delete-messages", json=body)
    assert res.status_code == status, res.text
    assert words in res.json()["detail"]
    assert rows() == ["row-0", "row-1", "row-2", "row-3"]


_STUBS = dict(_CARD_STUBS, **{
    "ui.js": ui_default_stub(
        "showToast: () => {}, copyToClipboard: () => {}, showError: () => {},\n"
        "el: (id) => document.getElementById(id), debounce: (f) => f,\n"
        "autoResize: () => {}, scrollHistory: () => {}, formatBytes: (n) => String(n),"),
})


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    if not shutil.which("node"):
        pytest.skip("node binary not on PATH")
    return _make_sandbox(tmp_path_factory.mktemp("reloadedbubble"), JS / "chatRenderer.js", _CARD_SHIM, _STUBS)


@node_only
def test_a_reloaded_bubble_carries_data_db_id(chat, sandbox):
    client, _ = chat
    page = client.get("/api/history/c1?limit=24").json()
    out = _run(sandbox, "import { history } from './shim.js';\n"
                        "const { addMessage } = await import('./chatRenderer.js');\n", """
        for (const e of %s) addMessage(e.role, e.content, 'm', e.metadata);
        console.log(JSON.stringify(history.querySelectorAll('.msg').map((n) => n.dataset.dbId || '')));
    """ % json.dumps(page["history"]))
    assert out == ["row-0", "row-1", "row-2", "row-3"]


_DELETE = r"""
const calls = { fetched: [], errors: [], toasts: [] };
const box = history;   // the shim's `#chat-history`
const nodes = %s.map(([cls, id]) => {
  const n = document.createElement('div'); n.className = 'msg ' + cls;
  if (id) n.dataset.dbId = id; box.appendChild(n); return n;
});
const uiModule = { styledConfirm: async () => true, showError: (m) => calls.errors.push(m),
                   showToast: (m) => calls.toasts.push(m) };
const sessionModule = { getCurrentSessionId: () => %s };
const chatRenderer = { showWelcomeScreen: () => {} };
const API_BASE = '';
const readRefusal = async () => ({ sentence: 'refused' });
globalThis.fetch = async (url, init) => { calls.fetched.push([url, JSON.parse(init.body)]);
  return { ok: true, json: async () => ({ status: 'ok' }) }; };
%s
await deleteMessage(nodes[1]);
console.log(JSON.stringify({ ...calls, left: box.querySelectorAll('.msg').length }));
"""


def _delete(sandbox, shape, session):
    return _run(sandbox, "import { document, history } from './shim.js';\n", _DELETE % (
        json.dumps(shape), json.dumps(session), _cut(JS / "chat.js", "export async function deleteMessage(")))


@node_only
def test_a_bubble_with_no_row_id_is_refused_not_pretended(sandbox):
    out = _delete(sandbox, [["msg-user", ""], ["msg-ai", ""]], "c1")
    assert out["fetched"] == [] and out["toasts"] == []
    assert out["left"] == 2, "the bubbles went while their rows stayed"
    assert out["errors"] == ["That message has no saved copy on this page yet. Reload the chat, then delete it."]


@node_only
def test_a_bubble_with_its_row_id_is_deleted_by_it(sandbox):
    out = _delete(sandbox, [["msg-user", "row-0"], ["msg-ai", "row-1"]], "c1")
    assert out["fetched"] == [["/api/session/c1/delete-messages", {"msg_ids": ["row-0", "row-1"]}]]
    assert out["left"] == 0 and out["toasts"] == ["Deleted"]


@node_only
def test_with_no_chat_at_all_the_bubble_is_simply_removed(sandbox):
    """#1428, kept: nothing is stored, so removing the bubble is the delete."""
    out = _delete(sandbox, [["msg-user", ""], ["msg-ai", ""]], None)
    assert out["fetched"] == [] and out["left"] == 0 and out["toasts"] == ["Message deleted"]
