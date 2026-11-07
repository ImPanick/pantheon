# SPDX-License-Identifier: AGPL-3.0-or-later
"""Forking a session must not mutate the source session's messages.

ChatMessage.metadata is a dict. add_message() -> _persist_message() stamps
_db_id (and timestamp) onto that dict in place. The fork handler used to pass
the source message's metadata dict by reference into the new session, so
persisting the fork rewrote the SOURCE messages' _db_id — breaking
edit/delete-by-id on the original conversation. The fork must copy the dict.

`B1986`. A message's Fork posted `keep_count`, the bubble's place among the
bubbles on the page, and the route copied that many rows. A chat opens on its
newest 24 rows, so a Fork in a longer chat copied the wrong span (on the newest
reply of a 42-message chat, the first 24 rows and none of the newest 18), and an
agent reply is drawn as two bubbles, so a Fork on it copied the message after
it as well. The browser now names the reply by its row's id (`through_msg_id`)
and the route copies through that row, or forks nothing when this chat no
longer holds it. `keep_count` alone (`/fork N`) is answered as before, which
the first case here still drives.
"""
import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from core.models import ChatMessage
import routes.history_routes as mod


class _FakeSession:
    def __init__(self, name="", owner=None):
        self.name = name
        self.owner = owner
        self.endpoint_url = ""
        self.model = ""
        self.history = []

    def add_message(self, message):
        # Mirror _persist_message: stamp the in-memory message's metadata.
        if message.metadata is None:
            message.metadata = {}
        message.metadata["_db_id"] = f"new-{len(self.history)}"
        self.history.append(message)


class _FakeSessionManager:
    def __init__(self, source):
        self.sessions = {"src-id": source}
        self.created = None

    def get_session(self, session_id):
        # Fork looks the source up through get_session — the hydration seam —
        # so a session only present in the DB still forks a real transcript.
        return self.sessions[session_id]

    def create_session(self, session_id=None, name=None, endpoint_url=None,
                       model=None, rag=False, owner=None):
        self.created = _FakeSession(name=name, owner=owner)
        return self.created

    def save_sessions(self):
        pass


def _fork_handler(router):
    for route in router.routes:
        if "/fork" in getattr(route, "path", "") and "POST" in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError("fork route not found")


def test_fork_does_not_corrupt_source_message_metadata(monkeypatch):
    monkeypatch.setattr(mod, "_verify_session_owner", lambda *a, **k: None)

    source = _FakeSession(name="Original", owner="alice")
    source.history = [
        ChatMessage("user", "hi", {"_db_id": "src-0"}),
        ChatMessage("assistant", "yo", {"_db_id": "src-1"}),
    ]
    sm = _FakeSessionManager(source)

    req = SimpleNamespace()

    async def _json():
        return {"keep_count": 2}

    req.json = _json

    router = mod.setup_history_routes(sm)
    fork = _fork_handler(router)
    result = asyncio.run(fork(request=req, session_id="src-id"))

    assert result["status"] == "ok"
    assert result["kept"] == 2

    # The forked session got its own metadata dicts...
    new_session = sm.created
    assert new_session.history[0].metadata is not source.history[0].metadata
    assert new_session.history[1].metadata is not source.history[1].metadata

    # ...and the source session's _db_id values are untouched.
    assert source.history[0].metadata["_db_id"] == "src-0"
    assert source.history[1].metadata["_db_id"] == "src-1"


# ── `B1986`: a fork through the message it was pressed on ──────────────────

def _forking(monkeypatch, rows=6):
    """A chat of `rows` messages whose rows carry the ids id-0, id-1, …, and a
    `fork(body)` that posts `body` to its fork route."""
    monkeypatch.setattr(mod, "_verify_session_owner", lambda *a, **k: None)
    source = _FakeSession(name="Long chat", owner="alice")
    source.history = [ChatMessage("user" if i % 2 == 0 else "assistant", f"m{i}", {"_db_id": f"id-{i}"})
                      for i in range(rows)]
    sm = _FakeSessionManager(source)
    handler = _fork_handler(mod.setup_history_routes(sm))

    def fork(body):
        async def _json():
            return body
        return asyncio.run(handler(request=SimpleNamespace(json=_json), session_id="src-id"))

    return sm, fork


def test_a_fork_through_a_message_copies_the_chat_through_that_message(monkeypatch):
    """The count beside it is a bubble's place on a page (2 here); the message
    it names is the fourth row, and the fork copies through it."""
    sm, fork = _forking(monkeypatch)
    result = fork({"through_msg_id": "id-3", "keep_count": 2})
    assert result["kept"] == 4
    assert [m.content for m in sm.created.history] == ["m0", "m1", "m2", "m3"]


def test_a_fork_through_a_message_this_chat_no_longer_holds_makes_no_chat(monkeypatch):
    sm, fork = _forking(monkeypatch)
    with pytest.raises(HTTPException) as refused:
        fork({"through_msg_id": "id-gone", "keep_count": 2})
    assert refused.value.status_code == 404
    assert refused.value.detail == "That message is no longer in this chat — reload and try again."
    assert sm.created is None, "a chat was made from a span nobody named"
