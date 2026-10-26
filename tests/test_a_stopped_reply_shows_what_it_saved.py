# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1205` (fx-chat) — a reply stopped live says the words it was saved with.

Escape at *Here is a*: the browser's reader is cut at once, and the detached
run, cancelled a moment later, saves what it had streamed — *Here is a long*,
the delta in flight when the Stop landed. The bubble said a word less than
the record, and a reload said the other thing.

Now `POST /api/chat/stop` waits for the cancelled run's save and answers with
it (`saved: {id, content}`), and the stopped bubble is redrawn from it when the
saved reply carries on what the bubble drew (`stoppedReplyRaw`) — with the
row's id, so it can be edited or deleted before a reload too.

Driven: a detached run (`src/agent_runs.py`) that saves on cancellation as the
chat route's own arm does, stopped through the real route; the real
`stoppedReplyRaw` and `_showWhatTheStopSaved`, cut out of `chat.js`, over the
DOM shim.
"""
from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

import routes.chat_routes as chat_routes
from core.models import ChatMessage
from src import agent_runs
from test_chat_actions_say_what_they_do import _cut  # noqa: E402
from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"


def _stop_endpoint(monkeypatch, sess):
    monkeypatch.setattr(chat_routes, "_verify_session_owner", lambda *a, **k: None)
    manager = SimpleNamespace(get_session=lambda sid: sess, save_sessions=lambda: None)
    router = chat_routes.setup_chat_routes(manager, *(SimpleNamespace() for _ in range(5)))
    return next(r.endpoint for r in router.routes if r.path == "/api/chat/stop/{session_id}")


@pytest.mark.asyncio
async def test_the_stop_answers_with_what_the_run_saved(monkeypatch):
    sess = SimpleNamespace(history=[ChatMessage("user", "tell me")])
    streamed = asyncio.Event()

    async def run():
        said = ""
        try:
            for word in ("Here is a", " long"):
                said += word
                yield f'data: {json.dumps({"delta": word})}\n\n'
            streamed.set()
            await asyncio.sleep(3600)
        except (asyncio.CancelledError, GeneratorExit):
            # What the chat route's own cancel arm does: the partial, stopped.
            sess.history.append(ChatMessage("assistant", said, {"stopped": True, "_db_id": "row-9"}))
            raise

    started = agent_runs.start("c-stop", run())
    await asyncio.wait_for(streamed.wait(), 5)
    stop = _stop_endpoint(monkeypatch, sess)
    request = SimpleNamespace(headers={"X-Pantheon-Run-Id": started.run_id})
    out = await stop(request, "c-stop")
    assert out == {"stopped": True, "saved": {"id": "row-9", "content": "Here is a long"}}


@pytest.mark.asyncio
async def test_a_stop_of_a_run_that_saved_nothing_answers_as_it_did(monkeypatch):
    sess = SimpleNamespace(history=[ChatMessage("user", "tell me")])
    waiting = asyncio.Event()

    async def run():
        waiting.set()
        await asyncio.sleep(3600)
        yield ""

    started = agent_runs.start("c-quiet", run())
    await asyncio.wait_for(waiting.wait(), 5)
    stop = _stop_endpoint(monkeypatch, sess)
    out = await stop(SimpleNamespace(headers={"X-Pantheon-Run-Id": started.run_id}), "c-quiet")
    assert out == {"stopped": True}
    assert await stop(SimpleNamespace(headers={"X-Pantheon-Run-Id": "another"}), "c-quiet") == {"stopped": False}


_SHIM = r"""
import { installDom, Node } from './dom.js';
export const document = installDom();
export { Node };
globalThis.window = globalThis;
"""


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    if not shutil.which("node"):
        pytest.skip("node binary not on PATH")
    d = tmp_path_factory.mktemp("stoppedreply")
    (d / "noop.js").write_text("export default {};\n")
    return _make_sandbox(d, JS / "agentStops.js", _SHIM, {})


_PAGE = r"""
import { document } from './shim.js';
globalThis.drawn = [];
const markdownModule = { squashOutsideCode: (t) => t,
  processWithThinking: (t) => { globalThis.drawn.push(t); return '<p>' + t + '</p>'; } };
%s
%s
"""


def _page(script):
    chat = JS / "chat.js"
    return _PAGE % (_cut(chat, "export function stoppedReplyRaw("), _cut(chat, "function _showWhatTheStopSaved(")) + script


@pytest.mark.parametrize("drawn, saved, expect", [
    ("Here is a", "Here is a long", "Here is a long"),                 # the delta in flight
    ("Here is a", "Here is a", None),                                    # nothing more was saved
    ("Here is a", "Something else entirely", None),                      # not this bubble's words
    ("Step two says", "Step one said this. Step two says more", None),   # a reply of several steps
    ("<think>hm</think>\n\nHere is a", "Here is a long", "<think>hm</think>\n\nHere is a long"),
    ("", "Here is a long", None),
    ("Here is a", "", None),
])
def test_the_bubble_takes_the_saved_words_only_when_they_carry_its_own_on(sandbox, drawn, saved, expect):
    out = _run(sandbox, "", _page("console.log(JSON.stringify(stoppedReplyRaw(%s, %s)));"
                                  % (json.dumps(drawn), json.dumps(saved))))
    assert out == expect


def test_the_stopped_bubble_is_redrawn_from_the_answer(sandbox):
    out = _run(sandbox, "", _page("""
        const holder = document.createElement('div'); holder.className = 'msg msg-ai';
        const body = document.createElement('div'); body.className = 'body'; holder.appendChild(body);
        body.innerHTML = '<p>Here is a</p>';
        const indicator = document.createElement('div'); indicator.className = 'stopped-indicator';
        indicator.textContent = 'Stopped · Continue'; body.appendChild(indicator);
        holder.dataset.raw = 'Here is a';
        _showWhatTheStopSaved(holder, 'Here is a', { stopped: true, saved: { id: 'row-9', content: 'Here is a long' } }, indicator);
        console.log(JSON.stringify({ raw: holder.dataset.raw, id: holder.dataset.dbId, drawn: globalThis.drawn,
                                     kept: body.querySelector('.stopped-indicator') === indicator }));
    """))
    assert out == {"raw": "Here is a long", "id": "row-9", "drawn": ["Here is a long"], "kept": True}


def test_an_answer_with_nothing_saved_leaves_the_bubble(sandbox):
    out = _run(sandbox, "", _page("""
        const holder = document.createElement('div');
        const body = document.createElement('div'); body.className = 'body'; holder.appendChild(body);
        body.innerHTML = '<p>Here is a</p>'; holder.dataset.raw = 'Here is a';
        _showWhatTheStopSaved(holder, 'Here is a', { stopped: true }, null);
        _showWhatTheStopSaved(holder, 'Here is a', null, null);
        console.log(JSON.stringify({ raw: holder.dataset.raw, drawn: globalThis.drawn, id: holder.dataset.dbId || '' }));
    """))
    assert out == {"raw": "Here is a", "drawn": [], "id": ""}
