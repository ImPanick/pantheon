# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1214` — the compact marker says *Chat compacted*, and is found by its flag.

`POST /api/session/{id}/compact` saves a visible line in the chat it compacts,
and it said **Conversation compacted** (a chat is a chat, `D-2026-10-03-01`
§3). The context popover found that line again by its words —
`textContent.includes('Conversation compacted')` — and every chat compacted
so far keeps those words in its history, so the reader had to stop depending
on them before the writer could change.

Now the bubble says what it is (`data-compacted`, from the record's
`compacted` flag, which every stored marker carries) and `compactMarkerIn`
finds it by that; the writer says *Chat compacted*. Driven: the real route
writes the rows; the real `addMessage` draws a marker in the old words and one
in the new, and the real `compactMarkerIn` finds both.
"""

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.models import ChatMessage
from tests.helpers.esc_stub import ui_default_stub  # B874
from test_tool_effect_surfaces_js import _CARD_SHIM, _CARD_STUBS, _make_sandbox, _run  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CHAT_RENDERER = ROOT / "static" / "js" / "chatRenderer.js"


class _Query:
    def __init__(self, rows=(), first=None):
        self._rows, self._first = list(rows), first

    def filter(self, *a, **k):
        return self

    def order_by(self, *a, **k):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._first


class _Db:
    added = []

    def query(self, model):
        return _Query(first=SimpleNamespace(message_count=0, updated_at=None))

    def add(self, row):
        _Db.added.append(row)

    def delete(self, row):
        pass

    def commit(self):
        pass

    def close(self):
        pass


class _Session:
    id = "s-1"
    name = "a chat"
    endpoint_url = "http://example.test/v1"
    model = "m"
    headers = {}
    owner = "ann"

    def __init__(self, history):
        self.history = history
        self.message_count = len(history)

    def get_context_messages(self):
        return [m.to_dict() for m in self.history]


class _Manager:
    def __init__(self, session):
        self.session = session

    def get_session(self, session_id, **_kw):
        return self.session

    def save_sessions(self):
        pass

    def replace_messages(self, session_id, messages):
        # `B1506`: the route persists the compacted history through this seam
        # (one ordered write) instead of adding two rows by hand.
        _Db.added = [SimpleNamespace(role=m.role, content=m.content, meta_data=json.dumps(m.metadata))
                     for m in messages]
        self.session.history = list(messages)
        return True


def test_the_route_writes_chat_compacted(monkeypatch):
    import routes.history_routes as history_routes
    import src.agent_runs as agent_runs
    import src.endpoint_resolver as endpoint_resolver
    import src.llm_core as llm_core
    import src.model_context as model_context

    async def summarise(*_a, **_k):
        return "What was said."

    _Db.added = []
    monkeypatch.setattr(history_routes, "_verify_session_owner", lambda request, sid: None)
    monkeypatch.setattr(history_routes, "SessionLocal", _Db)
    monkeypatch.setattr(agent_runs, "is_active", lambda sid: False)
    monkeypatch.setattr(endpoint_resolver, "resolve_endpoint", lambda kind, owner=None: (None, None, {}))
    monkeypatch.setattr(llm_core, "llm_call_async", summarise)
    monkeypatch.setattr(model_context, "estimate_tokens", lambda messages: 100)
    monkeypatch.setattr(model_context, "get_context_length", lambda url, model: 1000)
    history = [ChatMessage("user" if i % 2 == 0 else "assistant", f"line {i}") for i in range(8)]
    app = FastAPI()
    app.include_router(history_routes.setup_history_routes(_Manager(_Session(history))))
    assert TestClient(app).post("/api/session/s-1/compact").status_code == 200
    # `B1506`: the whole history is written now, kept rows too; the marker is
    # the assistant row that carries the flag.
    [visible] = [r for r in _Db.added if r.role == "assistant" and "compacted" in (json.loads(r.meta_data or "null") or {})]
    assert visible.content == "**Chat compacted** — 4 messages summarized, 4 kept."
    assert json.loads(visible.meta_data)["compacted"] is True


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
    return _make_sandbox(tmp_path_factory.mktemp("compactmarker"), CHAT_RENDERER, _CARD_SHIM, _STUBS)


@pytest.mark.parametrize("words", [
    "**Conversation compacted** — 12 messages summarized, 4 kept.",   # every chat compacted before
    "**Chat compacted** — 12 messages summarized, 4 kept.",            # the writer now
])
def test_a_stored_marker_in_either_words_is_found(sandbox, words):
    out = _run(sandbox, "import { history } from './shim.js';\n"
                        "const { addMessage, compactMarkerIn } = await import('./chatRenderer.js');\n", """
        addMessage('user', 'hello', 'm', {});
        addMessage('assistant', 'Hi there.', 'm', {});
        const marker = addMessage('assistant', %s, 'm', { compacted: true, messages_removed: 12 });
        addMessage('assistant', 'And on we go.', 'm', {});
        const found = compactMarkerIn(history);
        console.log(JSON.stringify({ same: found === marker, flagged: history.querySelectorAll('.msg[data-compacted]').length,
                                     none: compactMarkerIn(null) }));
    """ % json.dumps(words))
    assert out == {"same": True, "flagged": 1, "none": None}


def test_the_popover_finds_the_marker_by_its_flag_not_its_words():
    """The scroll after a compaction reads `compactMarkerIn`; the words it
    matched are gone from the reader (`Law 20`: the whole file, for absence)."""
    src = CHAT_RENDERER.read_text(encoding="utf-8")
    assert "compactMarkerIn(document.getElementById('chat-history'))" in src
    assert "Conversation compacted'" not in src
