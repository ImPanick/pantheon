# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B953` — a chat turn's compaction is said after a reload, as it was live.

`P4-13` puts a chat turn's compaction on the record it is saved with —
`context_compacted` and the messages and tokens before and after
(`_apply_shaping_metrics`, `routes/chat_routes.py`) — and the stream says it as
a toast: *Context compacted — older messages summarized (12/40 messages kept,
31,000 → 6,400 tokens)*. Nothing under `static/` read the record, so after a
reload the conversation never said its earlier half had been summarised away:
the live-vs-reload split `P4-13` was about, in chat mode. `B921` fixed it for
agent turns, which keep the compaction as a turn note; a chat reply is one
bubble and keeps none.

Now `addMessage`'s one-bubble path reads it off the record
(`compactionFromRecord`, `static/js/agentStops.js`) and draws the line above the
reply, through `renderAgentNote` — in the words the toast says it in, from the
one sentence builder (`compactionNoticeText`).

Driven (`Law 20`): a chat turn through `/api/chat_stream` with the real
`save_assistant_response`; the toast's words from the real builder over the
frame the route sent; the saved record drawn by the real `addMessage`.
"""

import asyncio
import json
import shutil
from pathlib import Path

import pytest

import routes.chat_routes as chat_routes
from tests.helpers.esc_stub import ui_default_stub  # B874
from test_foreground_model_routing import _COMPACTED_CONTEXT, _RouteRequest, _chat_stream_endpoint  # noqa: E402
from test_tool_effect_surfaces_js import _CARD_SHIM, _CARD_STUBS, _make_sandbox, _run  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CHAT_RENDERER = ROOT / "static" / "js" / "chatRenderer.js"

node_only = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _chat_turn(monkeypatch, overrides):
    """One chat turn through the route and the real save. Returns the frames
    it sent and the metadata it saved."""
    import core.database as database
    from routes.chat_helpers import save_assistant_response

    captured = {}
    endpoint = _chat_stream_endpoint(monkeypatch, "chat", captured, context_overrides=dict(overrides))
    monkeypatch.setattr(chat_routes, "save_assistant_response", save_assistant_response)
    monkeypatch.setattr(database, "update_session_last_accessed", lambda sid: None, raising=False)

    async def go():
        response = await endpoint(_RouteRequest("chat"))
        return [c async for c in response.body_iterator]

    chunks = asyncio.run(go())
    frames = [json.loads(c[6:]) for c in chunks if c.startswith("data: {")]
    saved = [m.metadata for m in captured.get("added_messages", []) if m.role == "assistant"]
    return frames, saved


_STUBS = dict(_CARD_STUBS, **{
    "ui.js": ui_default_stub(
        "showToast: () => {}, copyToClipboard: () => {},\n"
        "showError: (m) => { (globalThis.errors = globalThis.errors || []).push(String(m)); },\n"
        "el: (id) => document.getElementById(id), debounce: (f) => f,\n"
        "autoResize: () => {}, scrollHistory: () => {}, formatBytes: (n) => String(n),"),
})


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    if not shutil.which("node"):
        pytest.skip("node binary not on PATH")
    return _make_sandbox(tmp_path_factory.mktemp("chatcompact"), CHAT_RENDERER, _CARD_SHIM, _STUBS)


_PAGE = r"""
import { document, history } from './shim.js';
const { addMessage } = await import('./chatRenderer.js');
const { compactionNoticeText } = await import('./agentStops.js');
globalThis.errors = [];
const text = (n) => n.textContent.replace(/\s+/g, ' ').trim();
function shape() {
  return history.children.map((n) => {
    const cls = String(n.className || '');
    if (cls.includes('context-compacted-note')) return 'line:' + text(n);
    if (cls.includes('msg')) return 'msg:' + text(n.querySelector('.body'));
    return cls;
  });
}
"""


@node_only
def test_a_chat_turn_that_compacted_says_so_after_a_reload(monkeypatch, sandbox):
    """The row's `Verify:`, end to end. The toast's words, live, from the
    frame the route sent; the line above the reloaded reply, from the record
    the route saved — the same words, with the counts."""
    frames, saved = _chat_turn(monkeypatch, _COMPACTED_CONTEXT)
    [compacted] = [f for f in frames if f.get("type") == "compacted"]
    assert len(saved) == 1 and saved[0]["context_compacted"] is True
    out = _run(sandbox, "", _PAGE + """
        const toast = compactionNoticeText(%s);
        addMessage('assistant', 'Here is the summary you asked for.', 'selected-model', %s);
        console.log(JSON.stringify({ toast, shape: shape(), errors: globalThis.errors }));
    """ % (json.dumps(compacted), json.dumps(saved[0])))
    assert out["errors"] == []
    assert out["toast"] == ("Context compacted — older messages summarized "
                            "(12/40 messages kept, 31,000 → 6,400 tokens)")
    assert out["shape"] == ["line:" + out["toast"], "msg:Here is the summary you asked for."], out["shape"]


@node_only
def test_a_chat_turn_that_did_not_compact_draws_no_line(monkeypatch, sandbox):
    _, saved = _chat_turn(monkeypatch, {})
    out = _run(sandbox, "", _PAGE + """
        addMessage('assistant', 'Hello.', 'selected-model', %s);
        console.log(JSON.stringify({ shape: shape() }));
    """ % json.dumps(saved[0]))
    assert out["shape"] == ["msg:Hello."]


@node_only
def test_a_compaction_nothing_measured_is_said_without_figures(sandbox):
    """The flag without the figures — an older context, or a step that ran and
    shrank nothing — is the bare sentence, never a `0/0` that reads as a count."""
    out = _run(sandbox, "", _PAGE + """
        addMessage('assistant', 'Hello.', 'm', { context_compacted: true });
        addMessage('assistant', 'Again.', 'm', { context_compacted: true, context_messages_before_compact: 0,
          context_messages_after_compact: 0, context_tokens_before_compact: 0, context_tokens_after_compact: 0 });
        console.log(JSON.stringify({ shape: shape() }));
    """)
    assert out["shape"] == ["line:Context compacted — older messages summarized", "msg:Hello.",
                            "line:Context compacted — older messages summarized", "msg:Again."]


@node_only
def test_an_agent_turns_compaction_is_still_drawn_once(sandbox):
    """An agent turn keeps its compaction as a note (`B921`) and carries the
    flag on its record too; it is drawn by its rounds, once."""
    out = _run(sandbox, "", _PAGE + """
        addMessage('assistant', 'Done.', 'm', {
          round_texts: ['Done.'], context_compacted: true, context_messages_before_compact: 40,
          context_messages_after_compact: 12, context_tokens_before_compact: 31000,
          context_tokens_after_compact: 6400,
          agent_notes: [{ type: 'compacted', round: 0, data: { messages_before: 40, messages_after: 12,
            tokens_before: 31000, tokens_after: 6400 } }] });
        console.log(JSON.stringify({ shape: shape() }));
    """)
    assert [s for s in out["shape"] if s.startswith("line:")] == [
        "line:Context compacted — older messages summarized (12/40 messages kept, 31,000 → 6,400 tokens)"]
