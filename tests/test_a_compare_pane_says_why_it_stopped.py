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

`B2021` — and a pane says when its model failed. Every failure the server
reports — the provider's error, an endpoint that does not answer, a model it
could not load — reaches a pane as `event: error` on an ordinary-looking
stream. The pane read only `data:` lines, so it read past the name, found no
arm for the error's data, and took the stream's end for a finished answer: an
empty or cut-short reply, graded as if whole, and counted towards Fastest. A
stream that simply stopped before `[DONE]` read the same way. Both fail the
pane now, with the error under whatever it drew, and the stream is read the
way the protocol allows it to be written: a line may end in a lone `\\r`, and
`data:` may run over two lines. Ported from Odysseus `71e36499` (#6947).

Driven under node: the real `streamToPane`, the real `agentStops.js`,
`agentThread.js`, `spinner.js` and `chatStreamErrors.js`, in the page `P4-24`'s
file sets up.
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
export function demoteSupersededTodoCards() {}
export function safeToolScreenshotSrc(s) { return String(s || ''); }
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
    # `B918` / `B916`: the card's life and the meter, which a pane shares with
    # the main chat. `B2021`: and the error a failed stream is read as.
    for name in ("agentThread.js", "agentStops.js", "spinner.js", "langIcons.js",
                 "agentTurn.js", "agentMeter.js", "chatStreamErrors.js"):
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


# ── `B2021`: a pane whose model failed says so ──────────────────────────────

# The wire as the server writes it, one string per read: what `stream()` above
# cannot say — a named event, a comment, a line end split over two reads, a
# connection that stays open after the last event. And what `compare/index.js`
# gives a pane besides: the header with its finish badge, and a first spinner.
_WIRE = _COMPARE_PREAMBLE + r"""
const state = (await import('./compare/state.js')).default;
const spinnerModule = (await import('./spinner.js')).default;
globalThis.setInterval = () => 1;          // a spinner's frames are not what is read here
globalThis.clearInterval = () => {};
const header = pane.appendChild(new Node('div'));
header.className = 'pane-header';
const badge = header.appendChild(new Node('span'));
badge.className = 'pane-finish-badge';
badge.setAttribute('id', 'cmp-badge-0');
const first = spinnerModule.create('Processing...', 'right');
body().appendChild(first.createElement());
first.start();
ai._spinner = first;
let reads = 0;
let cancelled = false;
async function wire(chunks, { open = false, response = {} } = {}) {
  const enc = new TextEncoder();
  let i = 0;
  globalThis.fetch = async () => Object.assign({ ok: true, body: { getReader: () => ({
    async read() {
      reads += 1;
      flushTimers(100);
      if (i >= chunks.length) return open ? new Promise(() => {}) : { done: true };
      const c = chunks[i++];
      return { done: false, value: typeof c === 'string' ? enc.encode(c) : c };
    },
    cancel() { cancelled = true; return Promise.resolve(); },
  }) } }, response);
  await streamToPane(0, 's1', 'go', ai, {});
  flushTimers(1000);
  await new Promise((r) => setImmediate(r));   // whatever is still reading gets its turn
}
const frame = (e) => 'data: ' + JSON.stringify(e) + '\n\n';
const failed = (e) => 'event: error\ndata: ' + JSON.stringify(e) + '\n\n';
/** The pane as a person reads it, and what the page made of it. */
const look = () => ({
  badge: badge.textContent,
  finished: state._finishOrder,
  said: body().children.map((n) => n.textContent.replace(/\s+/g, ' ').trim()),
  spinning: first.isRunning || Boolean(body().querySelector('.ai-spinner')),
  grade: (header.querySelector('.pane-grade-badge') || {}).textContent || null,
  reads, cancelled,
});
"""


def _wire(sandbox, script: str) -> dict:
    return _run(sandbox, _WIRE, script)


def test_a_model_that_fails_before_it_answers_fails_the_pane_and_finishes_nowhere(compare_sandbox):
    """`B2021`. The provider's failure, after a heartbeat. The pane read past
    the event's name, had no arm for its data and ended on an empty answer it
    called finished — the first pane done, so the Fastest badge went to it."""
    out = _wire(compare_sandbox, """
        await wire([': heartbeat 1\\n\\n',
                    failed({ status: 400, text: 'local endpoint returned HTTP 400: model not loaded' })]);
        console.log(JSON.stringify(look()));
    """)
    assert out["said"] == ["Error: local endpoint returned HTTP 400: model not loaded"], out
    assert out["badge"] == "Failed", out
    assert out["finished"] == 0, f"a pane whose model failed counted towards Fastest: {out}"
    assert out["spinning"] is False, out


def test_a_blind_pane_says_the_request_failed_and_never_the_providers_words(compare_sandbox):
    """Blind mode hides which model answered. A provider's words can name it,
    or the address it sits at, so a Blind pane is told only that it failed."""
    out = _wire(compare_sandbox, """
        state._blindMode = true;
        await wire([failed({ error: 'Cannot reach 10.0.0.5:1234 (qwen3-8b)', status: 503 })]);
        console.log(JSON.stringify(look()));
    """)
    assert out["said"] == ["Error: Model request failed. Try again."], out
    assert out["badge"] == "Failed", out
    assert "10.0.0.5" not in json.dumps(out) and "qwen3" not in json.dumps(out), out


def test_a_reply_cut_short_by_an_error_keeps_its_words_and_is_not_graded(compare_sandbox):
    """The chat route saves a reply that failed part-way and says so with
    `message_saved` and `chat_terminal` before the error. The pane drew the
    words, then graded them as the whole answer and counted the pane as done.
    The words stay; the error goes under them; nothing is graded."""
    out = _wire(compare_sandbox, """
        state._expectedAnswer = '4';
        await wire([
          frame({ delta: 'The answer is 4' }),
          frame({ type: 'message_saved', id: 'm1' }),
          frame({ type: 'chat_terminal', data: { failed: true, failure: { status: 502 } } }),
          failed({ status: 502, text: 'Upstream protocol error' }),
        ]);
        console.log(JSON.stringify(look()));
    """)
    assert out["said"] == ["The answer is 4", "Error: Upstream protocol error"], out
    assert out["grade"] is None, f"a reply cut short was graded as an answer: {out}"
    assert out["badge"] == "Failed" and out["finished"] == 0, out


def test_the_work_drawn_before_the_model_failed_stays_above_the_error(compare_sandbox):
    """A step's card and the words after it, then the model fails. The error
    goes under them — a body replaced by the error would take the work the
    person watched with it — and the pane is not finished."""
    out = _wire(compare_sandbox, """
        await wire([
          frame({ type: 'tool_start', tool: 'bash', command: 'ls', round: 1 }),
          frame({ type: 'tool_output', tool: 'bash', command: 'ls', round: 1, exit_code: 0, output: 'a.txt' }),
          frame({ delta: 'There is one file.' }),
          failed({ status: 500, text: 'local endpoint returned HTTP 500' }),
        ]);
        console.log(JSON.stringify(Object.assign(look(), { shape: shape() })));
    """)
    assert out["shape"] == ["card", "text: There is one file.", ""], out
    assert out["said"][-1] == "Error: local endpoint returned HTTP 500", out
    assert out["badge"] == "Failed" and out["finished"] == 0, out


def test_a_stream_that_ends_without_done_is_not_a_finished_answer(compare_sandbox):
    """A connection that dropped mid-reply ends the stream as cleanly as a
    finished one, and the pane could not tell them apart."""
    out = _wire(compare_sandbox, """
        await wire([frame({ delta: 'Partial' })]);
        console.log(JSON.stringify(look()));
    """)
    assert out["said"] == ["Partial", "Error: Stream ended before completion."], out
    assert out["badge"] == "Failed" and out["finished"] == 0, out


def test_an_unreadable_frame_is_not_a_finished_answer(compare_sandbox):
    """A frame that does not parse is a reply the pane cannot have read
    whole. It was skipped, and what was left was called the answer."""
    out = _wire(compare_sandbox, """
        await wire([frame({ delta: 'Hello' }), 'data: {"delta": "wor\\n\\n', 'data: [DONE]\\n\\n']);
        console.log(JSON.stringify(look()));
    """)
    assert out["said"] == ["Hello", "Error: Invalid model stream data."], out
    assert out["badge"] == "Failed", out


def test_a_teachers_failure_keeps_the_students_answer_and_reads_the_stream_to_its_end(compare_sandbox):
    """The teacher's run fails after the student's answer was drawn, and the
    student's loop still sends its `[DONE]`. The answer stays with the error
    under it. And the rest of the stream is read, not cut off: a pane's
    stream is the run itself (`chat_stream` does not detach Compare's), and a
    connection closed while the server finishes the turn reads to it as Stop,
    which can save the reply a second time."""
    out = _wire(compare_sandbox, """
        await wire([
          frame({ delta: 'The student says 3.' }),
          frame({ type: 'teacher_takeover', teacher_model: 'big-model', model: 'big-model',
                  student_failure: 'two failed tool calls' }),
          failed({ error: 'Cannot reach 10.0.0.9:8080', status: 503 }),
          'data: [DONE]\\n\\n',
        ]);
        console.log(JSON.stringify(look()));
    """)
    assert out["said"] == ["The student says 3.", "Error: Cannot reach 10.0.0.9:8080"], out
    assert out["badge"] == "Failed", out
    assert out["reads"] == 5 and out["cancelled"] is False, (
        f"the stream was cut off before the server finished its turn: {out}")


def test_every_line_end_the_protocol_allows_reads_alike(compare_sandbox):
    """`\\n`, `\\r\\n` and a lone `\\r` all end a line, a `\\r\\n` may arrive
    split over two reads, a `data:` field may run over two lines, and a
    character may be split between reads. The pane read only `\\n`, one line
    at a time, so a server or proxy writing `\\r` produced no answer at all."""
    out = _wire(compare_sandbox, """
        const enc = new TextEncoder();
        const cr = enc.encode('data: {"delta":"Hé"}\\r\\r');
        const cut = enc.encode('data: {"delta":"H').length + 1;   // inside the é
        await wire([cr.slice(0, cut), cr.slice(cut),
                    'data:{"delta":"llo"}\\r\\n\\r\\n',
                    'data: {"delta":\\ndata: " world"}\\n\\n',
                    'data: [DONE]\\r', '\\n\\r\\n']);
        console.log(JSON.stringify(look()));
    """)
    assert out["said"] == ["Héllo world"], out
    assert out["badge"] == "" and out["finished"] == 1, out


def test_a_question_ends_the_turn_at_done_while_the_connection_stays_open(compare_sandbox):
    """`[DONE]` is the end. The pane read on to the end of the connection, so
    one held open after it left the pane running until the idle timeout. An
    `ask_user` turn ends with `[DONE]` like any other and still waits on the
    person's choice: no badge, no finish. Nothing cuts the connection."""
    out = _wire(compare_sandbox, """
        await wire([frame({ type: 'ask_user', data: { question: 'Which file?', options: ['a', 'b'] } }),
                    'data: [DONE]\\n\\n'], { open: true });
        console.log(JSON.stringify(look()));
    """)
    assert out["badge"] == "" and out["finished"] == 0, out
    assert out["cancelled"] is False, out


def test_a_pane_whose_request_fails_outright_stops_its_spinner(compare_sandbox):
    """An answer of 502 before any stream. The pane said so and left its
    spinner running behind the words — only a finished stream stopped it."""
    out = _wire(compare_sandbox, """
        await wire([], { response: { ok: false, status: 502 } });
        console.log(JSON.stringify(look()));
    """)
    assert out["said"] == ["Error: HTTP 502"], out
    assert out["spinning"] is False, f"the failed pane's spinner is still running: {out}"
