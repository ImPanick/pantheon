# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B906` — a run stopped at its step limit announces no step past it.

Four places in the loop announce the next step with `agent_step` — the bottom
of an ordinary step, an intent nudge, the loop-breaker's forced answer and the
Pantheon-Qwen memory shortcut — and none of them knew the `for` was about to
end. Measured: `max_rounds=2` and a model that keeps calling tools sent
`agent_step` round 3, then `rounds_exhausted` with `rounds: 2`. The browser's
`agent_step` arm opened a bubble with a *Generating response* spinner for step
3, which sat empty above the Continue box. `P4-23`'s meter already reads its
frame where a step actually starts, for this reason.

Now every such announcement goes through one function that returns nothing on
the last step, and the browser, at the stop, calls off the *Thinking* spinner
the last tool result had scheduled for the step after it.

Driven, not read (`Law 20`): the loop with a scripted model, and the browser's
`rounds_exhausted` arm cut out of `chat.js` and executed.
"""

import asyncio
import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

import src.agent_loop as agent_loop
from tests.helpers.source_text import blank  # B290
from test_a_stopped_agent_says_what_it_was_doing import _TAIL, _drive, _events  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CHAT_JS = ROOT / "static" / "js" / "chat.js"

node_only = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _plan(i):
    # Distinct calls, so the loop-breaker's no-progress rule never fires and
    # the run goes on until the step limit stops it.
    return '```update_plan\n{"plan":"- [ ] step %d"}\n```' % i


def _steps(events):
    return [e["round"] for e in events if e.get("type") == "agent_step"]


def test_a_run_stopped_at_its_limit_announces_no_step_past_it(monkeypatch):
    """The row's `Verify:`: the stop is not preceded by a step event naming a
    step past the limit."""
    events, _ = _drive(monkeypatch, [_plan(i) for i in range(6)],
                       tools={"update_plan"}, max_rounds=2)
    stop = next(i for i, e in enumerate(events) if e.get("type") == "rounds_exhausted")
    assert events[stop]["rounds"] == 2
    assert _steps(events) == [2], f"steps announced: {_steps(events)}"


def test_every_step_announced_is_a_step_that_starts(monkeypatch):
    """Each `agent_step` is followed by that step's own `P4-23` frame — the one
    sent where a step actually begins — before anything else is announced."""
    events, _ = _drive(monkeypatch, [_plan(i) for i in range(6)],
                       tools={"update_plan"}, max_rounds=3)
    for i, e in enumerate(events):
        if e.get("type") != "agent_step":
            continue
        rest = events[i + 1:]
        starts = [f for f in rest if f.get("type") == "agent_budget" and f["round"] == e["round"]]
        assert starts, f"step {e['round']} was announced and never started"


def test_a_promise_on_the_last_step_announces_nothing_after_it(monkeypatch):
    """The intent nudge announced the step it would nudge in — on the last step
    too, where there is none."""
    events, _ = _drive(monkeypatch, ["Let me check the logs"], tools={"bash"}, max_rounds=1)
    assert any(e.get("type") == "rounds_exhausted" for e in events), events
    assert _steps(events) == [], f"steps announced past a one-step limit: {_steps(events)}"


def test_a_loop_breaker_on_the_last_step_announces_nothing_after_it(monkeypatch):
    """The loop-breaker forces one tool-free step to write the answer. On the
    last step there is no such step, and it said there was."""
    events, _ = _drive(monkeypatch, ["\n".join([_TAIL] * 15), "Here is what I found."],
                       tools={"bash"}, max_rounds=1)
    assert any(e.get("type") == "loop_breaker_triggered" for e in events), events
    assert _steps(events) == [], f"steps announced past a one-step limit: {_steps(events)}"


def test_the_qwen_memory_shortcut_on_the_last_step_announces_nothing_after_it(monkeypatch):
    """The fourth site. On a Pantheon-Qwen model a memory *lookup* is dropped
    and the model is told to answer from the facts it was already given — in
    the next step, which on the last step does not exist."""
    monkeypatch.setattr(agent_loop, "get_setting", lambda k, d=None: d, raising=False)
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: None, raising=False)
    monkeypatch.setattr(agent_loop, "estimate_tokens", lambda *a, **k: 10, raising=False)
    monkeypatch.setattr(agent_loop, "blocked_tools_for_owner", lambda o: set(), raising=False)
    lookup = ('<tool_call>\n{"name": "manage_memory", "arguments": '
              '{"action": "search", "query": "preferences"}}\n</tool_call>')

    async def fake_stream(*_a, **_k):
        yield f"data: {json.dumps({'delta': lookup})}\n\n"
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", fake_stream, raising=False)

    async def drain():
        return [c async for c in agent_loop.stream_agent_loop(
            "http://local.test/v1", "pantheon-qwen3-4b",
            [{"role": "user", "content": "what do you know about me? I prefer short answers"}],
            max_rounds=1, relevant_tools={"manage_memory"})]

    events = _events(asyncio.run(drain()))
    assert any(e.get("type") == "rounds_exhausted" for e in events), events
    assert _steps(events) == [], f"steps announced past a one-step limit: {_steps(events)}"


def test_a_step_before_the_limit_is_still_announced(monkeypatch):
    """Not a quieter loop: every step that does run is announced as before."""
    events, _ = _drive(monkeypatch, ["Let me check the logs"], tools={"bash"}, max_rounds=5)
    assert _steps(events) == [2, 3], _steps(events)


# ── the browser at the stop ─────────────────────────────────────────────────


def _rounds_exhausted_arm() -> str:
    """The `rounds_exhausted` arm of the live dispatcher, cut out of the real
    file by its own delimiters in comment-blanked text."""
    code = blank(CHAT_JS)
    opening = "} else if (json.type === 'rounds_exhausted') {"
    assert code.count(opening) == 1, "the rounds_exhausted arm is no longer a unique anchor"
    start = code.index(opening) + len(opening)
    return code[start:code.index("} else if (json.type === 'model_actual') {", start)]


@node_only
def test_at_the_stop_nothing_is_left_waiting_for_the_next_step():
    """The last tool result schedules a *Thinking* spinner for the step after
    it (`_scheduleThinkingSpinner`). At the limit there is no such step: the
    stop calls it off, and still draws the Continue box."""
    # `B915`: the arm draws its note through `renderAgentNote`, the builder the
    # reload and a resumed stream use, so the real `agentStops.js` is imported.
    script = textwrap.dedent("""
        import { renderAgentNote } from %s;
        const calls = [];
        const made = [];
        const node = (tag) => ({
          tag, className: '', textContent: '', children: [], title: '', style: {},
          appendChild(c) { this.children.push(c); return c; },
          addEventListener() {}, remove() {}, scrollIntoView() {}, setAttribute() {},
        });
        const box = {
          children: [], querySelector: () => null,
          appendChild(c) { made.push(c.className); this.children.push(c); return c; },
        };
        const document = {
          getElementById: (id) => (id === 'chat-history' ? box : null),
          createElement: node,
          querySelector: () => null,
        };
        globalThis.document = document;
        const uiModule = { el: () => null, scrollHistory() {} };""" % json.dumps(
        (ROOT / "static" / "js" / "agentStops.js").as_uri()) + """
        const _cancelThinkingTimer = () => calls.push('cancelThinkingTimer');
        const _removeThinkingSpinner = () => calls.push('removeThinkingSpinner');
        let _hideUserBubble = false, _pendingContinue = null;
        const holder = {};
        for (const [json, _isBg] of [[{ type: 'rounds_exhausted', rounds: 2 }, false]]) {
          %s
        }
        console.log(JSON.stringify({ calls, made }));
    """) % _rounds_exhausted_arm()
    proc = subprocess.run(["node", "--input-type=module", "-e", script],
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr[-3000:]
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert "cancelThinkingTimer" in out["calls"], "the Thinking spinner for a step that will not run is still scheduled"
    assert "removeThinkingSpinner" in out["calls"]
    assert "stopped-indicator rounds-exhausted" in out["made"], "the Continue box is gone"
