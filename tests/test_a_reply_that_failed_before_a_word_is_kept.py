# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1200` (fx-chat, `CHAT-M-13`'s rest) — a reply that fails before any output
is saved, so a reload still says it failed and offers *Retry*.

Live, the failure is one sentence, *Retry* and *Details* (`P23-04`); but the
chat route saved a turn only when it had written something, so after a reload
nothing said the reply failed and there was no *Retry* — the person's message
stood alone. Now the terminal error saves `{role: assistant, content: '',
metadata: {failed: true, failure: {status, message}}}` (the status, never the
provider's own text); the model's replay, a compaction's summary and the
chat's counts leave it out (`is_unanswered_reply`); and the history renderer
draws it with `buildReplyError`, Retry included, withdrawn by a later message.

Driven (`Law 20`): a chat turn whose model answers 502 before a word, through
`/api/chat_stream` and the real `save_assistant_response`; the saved record in
a real `Session`, replayed as the next request would be; the record drawn by
the real `addMessage`.
"""

import asyncio
import json
import shutil
from pathlib import Path

import pytest

import routes.chat_routes as chat_routes
from core.models import ChatMessage, Session, is_unanswered_reply
from tests.helpers.esc_stub import ui_default_stub  # B874
from test_foreground_model_routing import _RouteRequest, _chat_stream_endpoint  # noqa: E402
from test_tool_effect_surfaces_js import _CARD_SHIM, _CARD_STUBS, _make_sandbox, _run  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CHAT_RENDERER = ROOT / "static" / "js" / "chatRenderer.js"
node_only = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

FAILS = ['event: error\ndata: {"status": 502, "text": "upstream said: secret-ish detail"}\n\n',
         "data: [DONE]\n\n"]


def _turn(monkeypatch, chunks, *, incognito=False):
    import core.database as database
    from routes.chat_helpers import save_assistant_response

    captured = {}
    endpoint = _chat_stream_endpoint(monkeypatch, "chat", captured, chat_chunks=chunks)
    monkeypatch.setattr(chat_routes, "save_assistant_response", save_assistant_response)
    monkeypatch.setattr(database, "update_session_last_accessed", lambda sid: None, raising=False)
    request = _RouteRequest("chat")
    if incognito:
        request._form["incognito"] = "true"

    async def go():
        response = await endpoint(request)
        return [c async for c in response.body_iterator]

    sent = asyncio.run(go())
    return [m for m in captured.get("added_messages", []) if m.role == "assistant"], sent


def test_a_reply_that_failed_before_a_word_is_saved_as_failed(monkeypatch):
    saved, sent = _turn(monkeypatch, FAILS)
    assert len(saved) == 1
    [reply] = saved
    assert reply.content == ""
    assert reply.metadata["failed"] is True
    assert reply.metadata["failure"] == {"status": 502, "message": "Model request failed (HTTP 502)"}
    assert "secret-ish" not in json.dumps(reply.metadata), "the provider's own words were kept"
    assert reply.metadata["model"] == "selected-model"
    # The live stream still ends as it did: the error goes out, no success.
    assert any(c.startswith("event: error") for c in sent)
    assert "data: [DONE]\n\n" not in sent


def test_a_reply_that_wrote_something_is_saved_as_it_was(monkeypatch):
    saved, _ = _turn(monkeypatch, ['data: {"delta": "Half an ans"}\n\n'] + FAILS)
    assert len(saved) == 1 and saved[0].content.startswith("Half an ans")
    assert not is_unanswered_reply(saved[0])


def test_the_next_request_does_not_replay_it(monkeypatch):
    saved, _ = _turn(monkeypatch, FAILS)
    sess = Session(id="c1", name="a chat", endpoint_url="x", model="m",
                   history=[ChatMessage("user", "hello"), saved[0], ChatMessage("user", "hello again")])
    assert [m["role"] for m in sess.get_context_messages()] == ["user", "user"]
    assert is_unanswered_reply(saved[0]) and is_unanswered_reply(saved[0].to_dict())


def test_it_is_not_summarised_by_a_compaction(monkeypatch):
    """The compaction's transcript of the older half (`/compact`) skips it."""
    from test_the_compact_marker_is_found_by_its_flag import _Db, _Manager, _Session
    import routes.history_routes as history_routes
    import src.agent_runs as agent_runs
    import src.endpoint_resolver as endpoint_resolver
    import src.llm_core as llm_core
    import src.model_context as model_context
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    saved, _ = _turn(monkeypatch, FAILS)
    seen = []

    async def summarise(url, model, messages, **_k):
        seen.append(messages[1]["content"])
        return "What was said."

    monkeypatch.setattr(history_routes, "_verify_session_owner", lambda request, sid: None)
    monkeypatch.setattr(history_routes, "SessionLocal", _Db)
    monkeypatch.setattr(agent_runs, "is_active", lambda sid: False)
    monkeypatch.setattr(endpoint_resolver, "resolve_endpoint", lambda kind, owner=None: (None, None, {}))
    monkeypatch.setattr(llm_core, "llm_call_async", summarise)
    monkeypatch.setattr(model_context, "estimate_tokens", lambda messages: 100)
    monkeypatch.setattr(model_context, "get_context_length", lambda url, model: 1000)
    # `B1731`: the cut is sized to the window the wheel draws, read with its proof.
    monkeypatch.setattr(model_context, "get_context_length_known", lambda url, model: (1000, True))
    history = [ChatMessage("user", "first"), saved[0]] + [
        ChatMessage("user" if i % 2 == 0 else "assistant", f"line {i}") for i in range(6)]
    app = FastAPI()
    app.include_router(history_routes.setup_history_routes(_Manager(_Session(history))))
    assert TestClient(app).post("/api/session/s-1/compact").status_code == 200
    # `B1731`: the transcript is headed and its messages set apart by a blank
    # line; the failed reply between "first" and "line 0" is still not in it.
    lines = [line for line in seen[0].splitlines() if line]
    assert lines[0] == "Transcript to compact:"
    assert lines[1:4] == ["USER: first", "USER: line 0", "ASSISTANT: line 1"]


def test_incognito_keeps_no_record_of_it(monkeypatch):
    saved, _ = _turn(monkeypatch, FAILS, incognito=True)
    assert saved == []


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
    return _make_sandbox(tmp_path_factory.mktemp("unanswered"), CHAT_RENDERER, _CARD_SHIM, _STUBS)


@node_only
def test_a_reload_says_it_failed_and_offers_retry(monkeypatch, sandbox):
    saved, _ = _turn(monkeypatch, FAILS)
    meta = dict(saved[0].metadata, _db_id="row-2")
    out = _run(sandbox, "import { history } from './shim.js';\n"
                        "const { addMessage } = await import('./chatRenderer.js');\n", """
        let retried = 0;
        globalThis.window.chatModule = { retryLastTurn: () => { retried += 1; } };
        addMessage('user', 'hello', 'm', {});
        const bubble = addMessage('assistant', '', 'selected-model', %s);
        const err = bubble.querySelector('.reply-error');
        const retry = bubble.querySelector('.reply-error-retry');
        retry.click();
        const before = history.querySelectorAll('.reply-error-retry').length;
        addMessage('user', 'something else', 'm', {});
        console.log(JSON.stringify({
          sentence: err.querySelector('.reply-error-text').textContent,
          details: !!err.querySelector('.reply-error-details'),
          id: bubble.dataset.dbId, retried, before,
          after: history.querySelectorAll('.reply-error-retry').length,
          kept: history.querySelectorAll('.reply-error').length,
        }));
    """ % json.dumps(meta))
    assert out == {"sentence": "The model didn't answer (HTTP 502).", "details": False, "id": "row-2",
                   "retried": 1, "before": 1, "after": 0, "kept": 1}
