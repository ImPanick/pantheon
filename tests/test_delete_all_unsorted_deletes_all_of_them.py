# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1225` (fx-ops) — "Delete all N unsorted" deletes all of them, and says N truly.

The Unsorted group's × asked "Delete all N unsorted chats?" about the chats the
sidebar holds and deleted those, one `DELETE` each. The sidebar holds one page
of a person's chats (`list_page`, 100, since `P23-07`), so with more on the
server it said N, deleted N, and every older unsorted chat stayed. A starred
chat was counted in N and then silently refused by the one-chat delete.

Now `deleteAllUnsorted` asks the server for the whole list first when the page
is not all of it (`X-More-Chats`), so the question names the number that goes;
starred chats stay and the question says so; the delete is one request to
`/api/sessions/bulk-delete`, and a count short of the ask is said.

Driven (`Law 20`): the real `deleteAllUnsorted`, `_everyChatOnServer` and
`_normalizeSessionsList`, cut out of `sessions.js` and run under node against a
server holding 150 unsorted chats when the page shows 100; and the real
`bulk-delete` route over a real `SessionManager` and SQLite file.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

import core.database as cdb
from core.database import Session as DbSession
from tests.helpers.js_source import js_binding, js_definition
from tests.helpers.source_text import blank_text

ROOT = Path(__file__).resolve().parents[1]
SESSIONS_JS = (ROOT / "static" / "js" / "sessions.js").read_text(encoding="utf-8")


def _cut(signature: str) -> str:
    return js_definition(SESSIONS_JS, blank_text(SESSIONS_JS, "js").index(signature))


_WORLD = r"""
const API_BASE = '';
let currentSessionId = 'old-3';
let sessions = [];
const asked = [], said = [], posted = [], deselected = [];
const uiModule = {
  styledConfirm: async (q) => { asked.push(q); return true; },
  showToast: (m) => said.push(['toast', m]), showError: (m) => said.push(['error', m]),
};
// As the real one: it lets go of the open chat only.
const _deselectCurrentSession = (sid) => { if (currentSessionId !== sid) return; currentSessionId = null; deselected.push(sid); };
const chat = (id, extra) => Object.assign({ id, name: id, folder: '', archived: false, is_important: false }, extra || {});
// The server: 150 unsorted chats (two starred), ten in a folder.
const server = [];
for (let i = 0; i < 150; i++) server.push(chat(i < 100 ? 'new-' + i : 'old-' + (i - 100), i === 7 || i === 120 ? { is_important: true } : null));
for (let i = 0; i < 10; i++) server.push(chat('filed-' + i, { folder: 'Work' }));
let shortBy = 0;
globalThis.fetch = async (url, init) => {
  const u = String(url);
  if (u.startsWith('/api/sessions?')) {
    const q = new URLSearchParams(u.split('?')[1]);
    const limit = Number(q.get('limit')), offset = Number(q.get('offset'));
    const page = server.slice(offset, offset + limit);
    const more = offset + limit < server.length;
    return { ok: true, headers: { get: (h) => (h === 'X-More-Chats' && more ? '1' : null) }, json: async () => page };
  }
  if (u === '/api/sessions/bulk-delete') {
    const ids = JSON.parse(init.body).ids;
    posted.push(ids);
    return { ok: true, json: async () => ({ deleted: ids.length - shortBy }) };
  }
  throw new Error('unexpected ' + u);
};
const loadSessions = async () => { sessions = []; };
"""


def _run(script: str) -> dict:
    body = (_WORLD + "\nlet _moreChats = true;\n"
            + js_binding(SESSIONS_JS, "_EVERY_CHAT_PAGE") + "\n"
            + _cut("async function _everyChatOnServer(") + "\n"
            + _cut("function _normalizeSessionsList(") + "\n"
            + _cut("export async function deleteAllUnsorted(").replace("export ", "", 1) + "\n"
            + script)
    out = subprocess.run(["node", "--input-type=module"], input=body, capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


pytestmark_node = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


@pytestmark_node
def test_the_question_and_the_delete_cover_every_unsorted_chat():
    out = _run("""
        const shown = server.slice(0, 100);          // the page the sidebar drew
        await deleteAllUnsorted(shown);
        console.log(JSON.stringify({ asked, posted: posted.map((p) => p.length), first: posted[0],
                                     said, deselected }));
    """)
    assert out["asked"] == ["Delete all 148 unsorted chats? 2 starred chats will stay."]
    assert out["posted"] == [148], "one request, every unsorted chat but the starred"
    assert "old-49" in out["first"] and "new-7" not in out["first"] and "old-20" not in out["first"]
    assert not [i for i in out["first"] if i.startswith("filed-")]
    assert out["said"] == [["toast", "Deleted 148 unsorted chats"]]
    assert out["deselected"] == ["old-3"], "the open chat was one of them"


@pytestmark_node
def test_a_page_that_is_the_whole_list_is_not_asked_again_and_a_short_count_is_said():
    out = _run("""
        _moreChats = false;
        shortBy = 1;
        await deleteAllUnsorted([chat('a'), chat('b'), chat('c', { is_important: true })]);
        console.log(JSON.stringify({ asked, posted, said }));
    """)
    assert out["asked"] == ["Delete all 2 unsorted chats? 1 starred chat will stay."]
    assert out["posted"] == [["a", "b"]]
    assert out["said"] == [["error", "Deleted 1 of 2 unsorted chats. The rest are still in the list; try again."]]


@pytestmark_node
def test_a_list_that_could_not_be_read_deletes_nothing():
    out = _run("""
        globalThis.fetch = async () => ({ ok: false, status: 503, json: async () => ({}) });
        await deleteAllUnsorted(server.slice(0, 100));
        console.log(JSON.stringify({ asked, said }));
    """)
    assert out["asked"] == []
    assert out["said"] == [["error", "Could not list all your unsorted chats, so nothing was deleted. Try again."]]


def test_the_server_deletes_every_chat_it_is_given_and_keeps_the_starred(monkeypatch, tmp_path):
    import core.session_manager as smod
    import routes.session_routes as session_routes

    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}",
                           connect_args={"check_same_thread": False}, poolclass=NullPool)
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    for mod in (smod, session_routes):
        monkeypatch.setattr(mod, "SessionLocal", factory)
    monkeypatch.setattr(session_routes, "_verify_session_owner", lambda request, sid, *a: None)
    db = factory()
    for i in range(120):
        db.add(DbSession(id=f"c{i}", owner="ann", name=f"chat {i}", endpoint_url="x", model="m",
                         is_important=(i == 5)))
    db.commit()
    db.close()
    app = FastAPI()
    app.include_router(session_routes.setup_session_routes(smod.SessionManager(), {}))
    res = TestClient(app).post("/api/sessions/bulk-delete", json={"ids": [f"c{i}" for i in range(120)]})
    assert res.json() == {"deleted": 119}
    db = factory()
    try:
        assert [r.id for r in db.query(DbSession).all()] == ["c5"]
    finally:
        db.close()
