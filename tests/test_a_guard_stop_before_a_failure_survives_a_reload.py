# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B942` — a guard stop before a model failure is still there after a reload.

`P4-10` puts the guard stops (`agent_stops`) on the loop's final `metrics`, the
record a finished turn is saved from. A turn whose model request fails is saved
from somewhere else: the `agent_terminal` frame's record (`src/agent_loop.py`,
the terminal branch), which carried the rounds and the tool events and no
stops. The loop-breaker does not end a turn — it refuses the round's calls and
forces one more round for an answer — so a loop-breaker stop followed by a
failed forced-answer round was drawn live and gone after a reload.

Driven (`Law 20`): the real `stream_agent_loop` with a scripted model that
repeats one call fifteen times and then gets a 502; its frames through
`/api/chat_stream` and the real `save_assistant_response`; the saved record
drawn by the real `addMessage`.
"""

import asyncio
import json
import shutil
from pathlib import Path

import pytest

import src.agent_loop as agent_loop
from tests.helpers.esc_stub import ui_default_stub  # B874
from test_a_reload_keeps_the_turns_notes import _saved_through_route  # noqa: E402
from test_tool_effect_surfaces_js import _CARD_SHIM, _CARD_STUBS, _make_sandbox, _run  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CHAT_RENDERER = ROOT / "static" / "js" / "chatRenderer.js"

_TAIL = "```bash\ntail -n 50 /var/log/app.log\n```"


def _frames(chunks):
    return [json.loads(c[6:]) for c in chunks if c.startswith("data: {")]


def _stop_then_502(monkeypatch):
    """Round 1 repeats one call fifteen times — the loop-breaker's runaway
    stop, nothing run — and the forced-answer round after it writes a few
    words and then the provider answers 502."""
    monkeypatch.setattr(agent_loop, "get_setting", lambda k, d=None: d, raising=False)
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: None, raising=False)
    monkeypatch.setattr(agent_loop, "estimate_tokens", lambda *a, **k: 10, raising=False)
    monkeypatch.setattr(agent_loop, "blocked_tools_for_owner", lambda o: set(), raising=False)
    calls = []

    async def fake_stream(*_a, **_k):
        calls.append(1)
        if len(calls) == 1:
            yield f"data: {json.dumps({'delta': chr(10).join([_TAIL] * 15)})}\n\n"
            yield "data: [DONE]\n\n"
            return
        yield f"data: {json.dumps({'delta': 'From the log so far'})}\n\n"
        yield f"event: error\ndata: {json.dumps({'status': 502})}\n\n"

    async def fake_execute(block, *_a, **_k):
        return (block.tool_type, {"output": "ok", "exit_code": 0})

    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", fake_stream, raising=False)
    monkeypatch.setattr(agent_loop, "execute_tool_block", fake_execute, raising=False)

    async def drain():
        return [c async for c in agent_loop.stream_agent_loop(
            "http://local.test/v1", "small-local-model",
            [{"role": "user", "content": "look into the failing service"}],
            max_rounds=4, relevant_tools={"bash"})]

    return asyncio.run(drain())


def test_the_failed_turns_record_carries_the_stop_the_stream_drew(monkeypatch):
    frames = _frames(_stop_then_502(monkeypatch))
    stops = [f for f in frames if f.get("type") == "loop_breaker_triggered"]
    terminals = [f for f in frames if f.get("type") == "agent_terminal"]
    assert len(stops) == 1 and stops[0]["round"] == 1, frames
    assert len(terminals) == 1, "the scripted run did not end in a model failure"
    assert not any(f.get("type") == "metrics" for f in frames), "a failed turn has no final metrics"
    # What the stream drew is what the record carries, byte for byte.
    assert terminals[0]["data"].get("agent_stops") == stops


def test_a_turn_no_guard_stopped_claims_no_stop_when_it_fails(monkeypatch):
    """The other side of it: a failure with no stop before it says none."""
    monkeypatch.setattr(agent_loop, "get_setting", lambda k, d=None: d, raising=False)
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: None, raising=False)
    monkeypatch.setattr(agent_loop, "estimate_tokens", lambda *a, **k: 10, raising=False)

    async def fake_stream(*_a, **_k):
        yield f"data: {json.dumps({'delta': 'Looking'})}\n\n"
        yield f"event: error\ndata: {json.dumps({'status': 502})}\n\n"

    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", fake_stream, raising=False)

    async def drain():
        return [c async for c in agent_loop.stream_agent_loop(
            "http://local.test/v1", "small-local-model",
            [{"role": "user", "content": "look into it"}], max_rounds=3, relevant_tools={"bash"})]

    [terminal] = [f for f in _frames(asyncio.run(drain())) if f.get("type") == "agent_terminal"]
    assert "agent_stops" not in terminal["data"]


# ── the reload ──────────────────────────────────────────────────────────────

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
    return _make_sandbox(tmp_path_factory.mktemp("stopfail"), CHAT_RENDERER, _CARD_SHIM, _STUBS)


def test_a_loop_breaker_stop_then_a_502_reloads_with_the_stop_line(monkeypatch, sandbox):
    """The row's `Verify:`, end to end: the real loop, the real route and save,
    the real history renderer. The stop line is drawn where the live stream
    drew it — after the round it stopped, before the failed answer."""
    chunks = _stop_then_502(monkeypatch)
    [saved] = _saved_through_route(monkeypatch, chunks)
    assert saved.get("failed") is True, "the turn was not saved from its terminal record"
    out = _run(sandbox, "", """
        import { document, history } from './shim.js';
        const { addMessage } = await import('./chatRenderer.js');
        globalThis.errors = [];
        addMessage('assistant', 'From the log so far', 'small-local-model', %s);
        const text = (n) => n.textContent.replace(/\\s+/g, ' ').trim();
        console.log(JSON.stringify({ errors: globalThis.errors, shape: history.children.map((n) => {
          const cls = String(n.className || '');
          if (cls.includes('agent-stop')) return 'stop:' + text(n.querySelector('.agent-stop-headline'));
          if (cls.includes('msg')) return 'msg:' + text(n.querySelector('.body'));
          return cls;
        }) }));
    """ % json.dumps(saved))
    assert out["errors"] == []
    assert out["shape"] == [
        "stop:Stopped: called bash with identical arguments 15 times.",
        "msg:From the log so far [Agent stopped: Model request failed (HTTP 502)]",
    ], out["shape"]
