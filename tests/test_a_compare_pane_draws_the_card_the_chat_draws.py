# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B918` — a compare pane draws a tool's card the way the main chat does.

`static/js/compare/stream.js` is the third stream that draws an agent turn,
beside the live chat and a resumed one (`P4-24`). It had no arm for
`tool_progress`, `tool_blocked` or `verifier`, and since `B904` the chat route
forwards all three to it. So in a pane:

  * a running command showed a wave and nothing else — no clock, and none of
    the output the command was printing — until it finished;
  * a call the policy refused was not drawn at all: it vanished;
  * the verifier's verdict was not shown.

It also kept its own copy of the card's life, and the copy had drifted: one
output pane holding stdout and stderr merged (`P4-19` split them in the chat),
and no screenshot. The drawing is one set of functions now, `agentTurn.js`,
moved out of `chat.js` where `P4-24` had put it, and all three streams import it.

Driven under node: the real `streamToPane`, the real `agentTurn.js`,
`agentThread.js` and `spinner.js`, in the page `P4-24`'s file sets up and
`B910`'s file lays a pane into. Nothing here reads a source file (`Law 20`).
"""

import json
import shutil

import pytest

from tests.helpers.js_source import js_definition
from tests.helpers.source_text import blank_text
from test_tool_effect_surfaces_js import _DOM, _run  # noqa: E402
from test_a_resumed_stream_draws_what_the_live_one_drew import _SHIM, _STUBS, JS  # noqa: E402
from test_a_compare_pane_says_why_it_stopped import (  # noqa: E402
    _COMPARE_PREAMBLE, _COMPARE_STUBS, COMPARE_STREAM,
)

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _real_demote() -> str:
    """`demoteSupersededTodoCards`, as shipped, cut out of `chatRenderer.js` —
    the pane's todo scope is only worth testing against the real one."""
    src = (JS / "chatRenderer.js").read_text(encoding="utf-8")
    code = blank_text(src, "js")
    return js_definition(src, code.index("export function demoteSupersededTodoCards("))


# The renderer a pane reads: B910's stub, with a todo card that exists and the
# real demotion, so a pane's scope can be seen doing its job.
_RENDERER = """
export function getModelCost() { return null; }
export function renderAskUserCard() { return null; }
export function safeDisplayImageSrc(s) { return s; }
export function buildDiffHtml(d) { return d ? '<div class="agent-diff">changed</div>' : ''; }
export function buildTodoCard(ev) {
  return ev && ev.tool === 'todowrite' ? '<div class="todo-card">plan</div>' : '';
}
export function safeToolScreenshotSrc(s) {
  return /^data:image\\/png;base64,/.test(String(s || '')) ? String(s) : '';
}
"""


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    d = tmp_path_factory.mktemp("comparecard")
    (d / "dom.js").write_text(_DOM, encoding="utf-8")
    (d / "shim.js").write_text(_SHIM, encoding="utf-8")
    stubs = dict(_STUBS, **_COMPARE_STUBS)
    stubs["chatRenderer.js"] = _RENDERER + _real_demote() + "\n"
    for name, src in stubs.items():
        (d / name).parent.mkdir(parents=True, exist_ok=True)
        (d / name).write_text(src, encoding="utf-8")
    (d / "compare").mkdir(exist_ok=True)
    shutil.copy(COMPARE_STREAM, d / "compare" / "stream.js")
    for name in ("agentThread.js", "agentStops.js", "spinner.js", "langIcons.js",
                 "agentTurn.js", "agentMeter.js"):
        if (JS / name).exists():
            shutil.copy(JS / name, d / name)
    return d


_PREAMBLE = _COMPARE_PREAMBLE + r"""
// `setInterval`, recorded, so a case can run a card's clock and see it stop.
const intervals = [];
globalThis.setInterval = (fn, ms) => { intervals.push({ fn, ms, live: true }); return intervals.length; };
globalThis.clearInterval = (id) => { const t = intervals[id - 1]; if (t) t.live = false; };
const tick = () => intervals.filter((t) => t.live).forEach((t) => t.fn());
const liveIntervals = () => intervals.filter((t) => t.live).length;

/** Stream `steps` into pane `pane`: an event, an array of events that land in
 *  one read, or a function run between reads to look at the pane mid-stream. */
async function run(steps, pane = { idx: 0, msg: ai, session: 's1' }) {
  const enc = new TextEncoder();
  let i = 0;
  globalThis.fetch = async () => ({ ok: true, body: { getReader: () => ({
    async read() {
      flushTimers(100);
      while (i < steps.length && typeof steps[i] === 'function') steps[i++]();
      if (i >= steps.length) return { done: true };
      const chunk = [].concat(steps[i++]);
      return { done: false, value: enc.encode(chunk.map((e) => (e === '[DONE]'
        ? 'data: [DONE]\n\n' : 'data: ' + JSON.stringify(e) + '\n\n')).join('')) };
    } }) } });
  await streamToPane(pane.idx, pane.session, 'go', pane.msg, {});
  flushTimers(1000);
}

const words = (n) => (n ? n.textContent.replace(/\s+/g, ' ').trim() : '');
/** The pane's message, top to bottom, as a person reads it. */
function describePane(msg = ai) {
  return msg.querySelector('.body').children.map((n) => {
    const cls = n._classes();
    if (cls.includes('agent-thread-node')) {
      return {
        card: words(n.querySelector('.agent-thread-tool')),
        state: cls.includes('running') ? 'running' : (cls.includes('error') ? 'failed' : 'done'),
        tail: words(n.querySelector('.agent-thread-tail')),
        clock: words(n.querySelector('.agent-thread-elapsed')),
        panes: n.querySelectorAll('.agent-tool-output').map((d) => words(d.querySelector('summary'))),
        note: words(n.querySelector('.agent-thread-blocked-reason, .agent-thread-verifier-list, .agent-thread-exit-code')),
      };
    }
    if (cls.includes('compare-text-content')) return { text: words(n) };
    if (cls.includes('agent-stop')) return { stop: words(n.querySelector('.agent-stop-headline')) };
    return { other: n.className };
  });
}
"""


def _pane(sandbox, script: str) -> dict:
    return _run(sandbox, _PREAMBLE, script)


def test_a_running_command_shows_its_clock_and_its_output_as_it_runs(sandbox):
    """The row's first half. The server says how long the command has run and
    what it last printed; the pane drew a wave and nothing else until it
    finished. The clock is the server's, not one started when the card was."""
    out = _pane(sandbox, """
        // The chat's own scroller, counted: a pane's card scrolls the pane.
        const ui = (await import('./ui.js')).default;
        let chatScrolls = 0;
        ui.scrollHistory = () => { chatScrolls += 1; };
        let running = null;
        await run([
          { type: 'tool_start', tool: 'bash', command: 'make test', round: 1 },
          { type: 'tool_progress', tool: 'bash', round: 1, elapsed_s: 42.5,
            tail: 'collected 12 items\\ntest_a.py ....' },
          () => { tick(); running = describePane(); },
          { type: 'tool_output', tool: 'bash', command: 'make test', round: 1, exit_code: 2,
            output: '4 passed', stdout: '4 passed', stderr: 'FAILED test_b.py::test_x' },
          '[DONE]',
        ]);
        const card = ai.querySelector('.agent-thread-node');
        console.log(JSON.stringify({ running, done: describePane(), live: liveIntervals(),
                                     wave: card._waveInterval, clock: card._elapsedTicker,
                                     chatScrolls }));
    """)
    [card] = out["running"]
    assert card["state"] == "running" and card["card"] == "Running", card
    assert card["tail"] == "collected 12 items test_a.py ....", card
    assert card["clock"].startswith("42.5"), f"the clock is not the server's: {card}"
    [done] = out["done"]
    assert done["state"] == "failed" and done["card"] == "Terminal", done
    # `P4-19`'s two panes, the chat's, where this pane had one with both merged.
    assert done["panes"] == ["Output", "Error output (stderr)"], done
    assert done["note"] == "Exited 2", done
    assert out["live"] == 0 and out["wave"] is None and out["clock"] is None, (
        "the finished card's wave or clock is still ticking")
    assert out["chatScrolls"] == 0, "a pane's card scrolled the chat behind the panes"


def test_a_refused_call_is_drawn_where_it_happened_and_stays_refused(sandbox):
    """A call the policy refuses gets no `tool_start`, and the pane drew
    nothing for it. It ends the text before it, as a card does; the
    `tool_output` that follows for the same call does not rewrite it; later
    text starts under it."""
    out = _pane(sandbox, """
        await run([
          { delta: 'Let me clear the cache.' },
          [{ type: 'tool_blocked', tool: 'bash', round: 1, command: 'rm -rf /var/cache/app',
             reason: 'Shell is switched off for this chat.' },
           { type: 'tool_output', tool: 'bash', command: 'rm -rf /var/cache/app', round: 1,
             exit_code: 1, output: 'Error: Shell is switched off for this chat.', status: 'blocked' }],
          { delta: 'The shell is off, so I left the cache alone.' },
          '[DONE]',
        ]);
        console.log(JSON.stringify({ pane: describePane(), previews }));
    """)
    assert out["pane"] == [
        {"text": "Let me clear the cache."},
        {"card": "Terminal · blocked", "state": "failed", "tail": "", "clock": "",
         "panes": [], "note": "Shell is switched off for this chat."},
        {"text": "The shell is off, so I left the cache alone."},
    ], out["pane"]
    assert out["previews"] == ["The shell is off, so I left the cache alone."]


def test_the_verdict_goes_with_the_work_and_the_answer_stays_the_last_text(sandbox):
    """`P4-17`'s card, which the pane did not draw. The main chat puts it in the
    thread of the work it judged, above the answer; here that is after the last
    card. The answer stays the pane's last text, so grading and the HTML
    preview still read the answer and not nothing."""
    out = _pane(sandbox, """
        await run([
          { type: 'tool_start', tool: 'write_file', command: 'notes.md', round: 1 },
          { type: 'tool_output', tool: 'write_file', command: 'notes.md', round: 1, exit_code: 0, output: 'wrote 3 lines' },
          { delta: 'Done: notes.md has the three items.' },
          { type: 'agent_step', round: 2 },
          { type: 'verifier', round: 2, outcome: 'pass', issues: [], detail: '' },
          '[DONE]',
        ]);
        console.log(JSON.stringify({ pane: describePane(), previews }));
    """)
    shape = [n.get("card") or n.get("text") for n in out["pane"] if "other" not in n]
    assert shape == ["Write File", "Verified", "Done: notes.md has the three items."], out["pane"]
    assert out["previews"] == ["Done: notes.md has the three items."]


def test_a_failed_verdict_lists_what_it_found(sandbox):
    out = _pane(sandbox, """
        await run([
          { type: 'tool_start', tool: 'write_file', command: 'notes.md', round: 1 },
          { type: 'tool_output', tool: 'write_file', command: 'notes.md', round: 1, exit_code: 0, output: 'wrote 2 lines' },
          { delta: 'Done.' },
          { type: 'verifier', round: 1, outcome: 'fail', issues: ['The third item is missing.'], detail: '' },
          '[DONE]',
        ]);
        console.log(JSON.stringify({ pane: describePane() }));
    """)
    verdict = out["pane"][1]
    assert verdict["card"] == "Verification failed" and verdict["state"] == "failed", out["pane"]
    assert verdict["note"] == "The third item is missing.", verdict


def test_a_card_still_running_when_the_stream_ends_stops_its_clock(sandbox):
    """A cancel, a timeout or an error ends the stream with no result for the
    card that was running. Its wave and clock stop and it stops saying it is
    running — what a resumed stream does with one (`P4-24`)."""
    out = _pane(sandbox, """
        await run([{ type: 'tool_start', tool: 'bash', command: 'sleep 600', round: 1 }]);
        const card = ai.querySelector('.agent-thread-node');
        console.log(JSON.stringify({ live: liveIntervals(), running: card._classes().includes('running') }))
    """)
    assert out["live"] == 0, "a card with no result kept ticking after the stream ended"
    assert out["running"] is False


def test_a_panes_new_plan_does_not_grey_out_another_panes(sandbox):
    """`P6-17` greys out an older todo card when a newer one lands, across the
    page. Two panes are two models' plans; one must not supersede the other."""
    out = _pane(sandbox, """
        const pane1 = document.body.appendChild(new Node('div'));
        pane1.className = 'compare-pane';
        pane1.setAttribute('data-pane', '1');
        const hist1 = pane1.appendChild(new Node('div'));
        hist1.setAttribute('id', 'cmp-history-1');
        const ai1 = hist1.appendChild(new Node('div'));
        ai1.className = 'msg msg-ai';
        ai1.innerHTML = '<div class="role">AI</div><div class="body"></div>';
        const plan = (i) => [
          { type: 'tool_start', tool: 'todowrite', command: '{}', round: 1 },
          { type: 'tool_output', tool: 'todowrite', command: '{}', round: 1, exit_code: 0, output: 'plan ' + i },
          '[DONE]'];
        await run(plan(0));
        await run(plan(1), { idx: 1, msg: ai1, session: 's2' });
        const greyed = (msg) => msg.querySelectorAll('.todo-card').map((c) => c._classes().includes('todo-card-superseded'));
        console.log(JSON.stringify({ pane0: greyed(ai), pane1: greyed(ai1) }));
    """)
    assert out["pane0"] == [False], f"pane 1's plan greyed out pane 0's: {out}"
    assert out["pane1"] == [False], out
