# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B910` — a compare pane says why the agent stopped itself.

`static/js/compare/stream.js` is a third dispatch chain for the same agent
events, beside the live chat and a resumed stream (`P4-24`). It had no arm for
`loop_breaker_triggered` or `intent_nudge_exhausted`, so a pane whose model
looped, or kept saying what it would do without doing it, just stopped — with
nothing to say why.

The row said to draw the line into the pane's history. Compare draws a whole
turn as one message, with its tool cards in that message's body, so a line in
the history lands after the message — while the loop-breaker's answer, which
the line announces as "the answer below", keeps streaming into the message
above it. So the line goes in the message, after the work it stopped, and the
answer starts in a fresh text block under it.

Driven under node: the real `streamToPane`, the real `agentStops.js`,
`agentThread.js` and `spinner.js`, in the page `P4-24`'s file sets up.
"""

import json
import shutil

import pytest

from tests.helpers.esc_stub import esc_source  # B874
from test_tool_effect_surfaces_js import _DOM, _run  # noqa: E402
from test_a_resumed_stream_draws_what_the_live_one_drew import (  # noqa: E402
    _SHIM, _STUBS, _STOP, JS,
)

COMPARE_STREAM = JS / "compare" / "stream.js"
pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


_COMPARE_STUBS = {
    "compare/state.js": """
export default {
  _abortControllers: [], _timeout: 60, _compareMode: 'agent', _blindMode: false,
  _selectedModels: [{ model: 'm' }], _paneMetrics: [], _paneElapsed: [], _finishOrder: 0,
  _parallel: true, _expectedAnswer: '', API_BASE: '', isActive: true, _paneSessionIds: ['s1'],
};
""",
    "compare/vote.js": "export function addFinishBadge() {}\n",
    "chatRenderer.js": """
export function getModelCost() { return null; }
export function renderAskUserCard() { return null; }
export function safeDisplayImageSrc(s) { return s; }
export function buildTodoCard() { return ''; }
export function buildDiffHtml() { return ''; }
""",
    # `B874`: the shipped `esc`, not a copy of it.
    "markdown.js": esc_source() + """
export default {
  processWithThinking: (s) => '<p>' + esc(String(s == null ? '' : s)) + '</p>',
  squashOutsideCode: (s) => String(s == null ? '' : s),
};
""",
    "presets.js": "export default { getSelectedPreset() { return null; } };\n",
}


@pytest.fixture(scope="module")
def compare_sandbox(tmp_path_factory):
    d = tmp_path_factory.mktemp("comparestop")
    (d / "dom.js").write_text(_DOM, encoding="utf-8")
    (d / "shim.js").write_text(_SHIM, encoding="utf-8")
    for name, src in dict(_STUBS, **_COMPARE_STUBS).items():
        (d / name).parent.mkdir(parents=True, exist_ok=True)
        (d / name).write_text(src, encoding="utf-8")
    (d / "compare").mkdir(exist_ok=True)
    shutil.copy(COMPARE_STREAM, d / "compare" / "stream.js")
    for name in ("agentThread.js", "agentStops.js", "spinner.js", "langIcons.js"):
        shutil.copy(JS / name, d / name)
    return d


_COMPARE_PREAMBLE = r"""
import { document, Node, flushTimers } from './shim.js';
const { streamToPane, registerStreamActions } = await import('./compare/stream.js');
const previews = [];
registerStreamActions({ rerollPane() {}, autoPreviewHtml(i, text) { previews.push(text); }, setSendBtn() {} });
const pane = document.body.appendChild(new Node('div'));
pane.className = 'compare-pane';
pane.setAttribute('data-pane', '0');
const hist = pane.appendChild(new Node('div'));
hist.setAttribute('id', 'cmp-history-0');
const ai = hist.appendChild(new Node('div'));
ai.className = 'msg msg-ai';
ai.innerHTML = '<div class="role">AI</div><div class="body"></div>';
async function stream(events) {
  const enc = new TextEncoder();
  let i = 0;
  globalThis.fetch = async () => ({ ok: true, body: { getReader: () => ({
    async read() {
      flushTimers(100);                       // a throttled render gets its turn between reads
      if (i >= events.length) return { done: true };
      const chunk = [].concat(events[i++]);   // an array is one chunk: its events land together
      return { done: false, value: enc.encode(chunk.map((e) => (e === '[DONE]'
        ? 'data: [DONE]\n\n' : 'data: ' + JSON.stringify(e) + '\n\n')).join('')) };
    } }) } });
  await streamToPane(0, 's1', 'go', ai, {});
  flushTimers(1000);
}
const body = () => ai.querySelector('.body');
const shape = () => body().children.map((n) => {
  const cls = n._classes();
  if (cls.includes('agent-stop')) return 'stop: ' + n.querySelector('.agent-stop-headline').textContent;
  if (cls.includes('agent-thread-node')) return 'card';
  if (cls.includes('compare-text-content')) return 'text: ' + n.textContent;
  return n.className;
});
"""


def _compare(sandbox, script: str) -> dict:
    return _run(sandbox, _COMPARE_PREAMBLE, script)


def test_compare_draws_the_loop_breaker_between_the_work_and_the_answer(compare_sandbox):
    """`B910`. A compare pane whose model looped showed nothing about why it
    stopped. The line says the answer is below it, so the answer is below it:
    the text so far is drawn final and the answer starts under the line."""
    out = _compare(compare_sandbox, """
        await stream([
          { type: 'tool_start', tool: 'bash', command: 'tail -n 50 /var/log/app.log', round: 1 },
          { type: 'tool_output', tool: 'bash', command: 'tail -n 50 /var/log/app.log', round: 1, exit_code: 0, output: 'x' },
          [{ delta: 'Checking again.' }, %s],     // the stop lands while that text waits to be drawn
          { delta: 'Here is what I found.' },
          '[DONE]',
        ]);
        console.log(JSON.stringify({ shape: shape(), previews }));
    """ % json.dumps(_STOP))
    assert out["shape"] == ["card", "text: Checking again.", "stop: " + _STOP["message"],
                            "text: Here is what I found."]
    assert out["previews"] == ["Here is what I found."]


def test_compare_draws_the_unkept_promise_after_the_text_and_grades_the_text(compare_sandbox):
    promise = {"type": "intent_nudge_exhausted", "reason": "intent_without_action_nudge_cap",
               "kind": "unkept_promise", "round": 3, "matched": "Let me check the logs",
               "message": "Stopped: said “Let me check the logs” 3 times without making a call.",
               "next": "Nothing was run."}
    out = _compare(compare_sandbox, """
        await stream([[{ delta: 'Let me check the logs' }, %s], '[DONE]']);
        console.log(JSON.stringify({ shape: shape(), previews }));
    """ % json.dumps(promise))
    assert out["shape"] == ["text: Let me check the logs", "stop: " + promise["message"]]
    assert out["previews"] == ["Let me check the logs"]
