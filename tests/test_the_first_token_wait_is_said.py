# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B907` — the wait for a first token is said, and says only what is known.

`scheduleFirstTokenWaitMessages()` set three spinner messages at 20s, 60s and
120s, and `markFirstVisibleOutput()` called them off on the first `data:` line of
*any* kind. The first line of every stream is `stream_steerable` (`B14`), so they
were called off within milliseconds and never shown — they could only fire while
the route was still building context, before it streamed. The 60s one also
stated a guess as a fact: *Large local model is pre-filling context*, about
every model, local or not.

Now the model's first output — a token, thinking included, or a tool call and
what only follows one — calls them off, and the words come from
`firstTokenWaitText` (`static/js/agentMeter.js`), which reads what the prep line
already knows: while a prep step runs it leaves that step's label alone; once
preparation is done it says *Waiting for the model* with the time since, counted
in the browser and marked `~`; with no prep at all it says that no token has
come, and for about how long, in words that stay true while they are shown.

Driven, not read (`Law 20`): the module under node, and the live stream code —
the timers, the marker and the dispatcher's first lines — cut out of `chat.js`
and run against a clock the test moves.
"""

import json
import shutil
from pathlib import Path

import pytest

from tests.helpers.js_source import js_definition  # B876
from tests.helpers.source_text import blank  # B290
from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
AGENT_METER = ROOT / "static" / "js" / "agentMeter.js"
CHAT_JS = ROOT / "static" / "js" / "chat.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_SHIM = "export const nothing = 0;\n"


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    return _make_sandbox(tmp_path_factory.mktemp("firsttoken"), AGENT_METER, _SHIM, {})


def _module(sandbox, script):
    return _run(sandbox, "const m = await import('./agentMeter.js');\n", script)


_PREP_RUNNING = {"type": "agent_prep", "status": "running", "phase": "tool_selection",
                 "data": {"request_setup": 0.01}}
_PREP_DONE = {"type": "agent_prep", "status": "done", "total": 0.9,
              "data": {"request_setup": 0.01, "tool_selection": 0.5,
                       "prompt_build": 0.3, "context_trim": 0.09}}


# ── the words ───────────────────────────────────────────────────────────────


def test_with_no_preparation_it_says_that_no_token_has_come(sandbox):
    out = _module(sandbox, """
        console.log(JSON.stringify([5000, 20000, 59000, 60000, 119000, 120000, 600000]
          .map((ms) => m.firstTokenWaitText(null, ms, 0))));
    """)
    # `P23-04` (PERF-U-3): from 5 s, counted, in the words used after prep.
    assert out == [
        "Waiting for the model · ~5s",
        "Waiting for the model · ~20s", "Waiting for the model · ~59s",
        "Waiting for the model · ~1m 00s",
        "Waiting for the model · ~1m 59s",
        "Waiting for the model · ~2m 00s",
        "Waiting for the model · ~10m 00s",
    ]
    assert not any("pre-filling" in t for t in out)


def test_while_a_prep_step_runs_its_own_label_is_left_alone(sandbox):
    """The step's label (*Choosing tools*) and the `~` count under it say more
    than any of the three sentences."""
    out = _module(sandbox, """
        const meter = m.createAgentMeter({ now: () => 0, setInterval: () => 1, clearInterval() {} });
        meter.update(%s);
        console.log(JSON.stringify([20000, 60000, 130000]
          .map((ms) => m.firstTokenWaitText(meter.state, ms, ms))));
    """ % json.dumps(_PREP_RUNNING))
    assert out == ["", "", ""]


def test_once_prepared_it_says_how_long_the_model_has_had_the_prompt(sandbox):
    """Counted from the frame that said preparation was done — in the browser,
    so marked `~` like every figure the browser counts (`Law 10`)."""
    out = _module(sandbox, """
        let clock = 4000;
        const meter = m.createAgentMeter({ now: () => clock, setInterval: () => 1, clearInterval() {} });
        meter.update(%s);
        console.log(JSON.stringify([4500, 5000, 16000, 64000, 190000]
          .map((now) => m.firstTokenWaitText(meter.state, now, now))));
    """ % json.dumps(_PREP_DONE))
    assert out == ["Waiting for the model", "Waiting for the model · ~1s",
                   "Waiting for the model · ~12s", "Waiting for the model · ~1m 00s",
                   "Waiting for the model · ~3m 06s"]


def test_the_wait_is_ended_by_the_model_and_by_nothing_else(sandbox):
    """What every stream opens with — the steer verdict, the model's name, the
    prep and budget frames, the skills it was shown — is not the model
    answering."""
    out = _module(sandbox, """
        const events = %s;
        console.log(JSON.stringify(events.map((e) => [e.type || 'delta', m.endsFirstTokenWait(e)])));
    """ % json.dumps([
        {"type": "stream_steerable", "steerable": True}, {"type": "model_info", "model": "m"},
        _PREP_RUNNING, {"type": "agent_budget", "round": 1}, {"type": "skills_injected", "data": []},
        {"type": "model_actual", "model": "m"}, {"type": "steer_applied", "round": 1},
        {"type": "web_sources", "data": []}, {"delta": ""},
        {"delta": "Let me think", "thinking": True}, {"delta": "Hello"},
        {"type": "tool_start", "tool": "bash"}, {"type": "tool_blocked", "tool": "bash"},
        {"type": "tool_output", "tool": "bash"}, {"type": "research_progress", "data": {}},
    ]))
    assert out == [
        ["stream_steerable", False], ["model_info", False], ["agent_prep", False],
        ["agent_budget", False], ["skills_injected", False], ["model_actual", False],
        ["steer_applied", False], ["web_sources", False], ["delta", False],
        ["delta", True], ["delta", True], ["tool_start", True], ["tool_blocked", True],
        ["tool_output", True], ["research_progress", True],
    ]


# ── the live stream ─────────────────────────────────────────────────────────


def _declaration(anchor: str) -> str:
    code = blank(CHAT_JS)
    assert code.count(anchor) == 1, f"{anchor!r} is no longer a unique anchor"
    return js_definition(CHAT_JS.read_text(encoding="utf-8"), code.index(anchor))


def _live_handler() -> str:
    """Comment-blanked `handleChatSubmit`, the function the live stream runs
    in. The dispatcher is cut from here rather than from the whole file: a
    resumed stream (`resumeStream`, `P4-24`) has arms that open the same way."""
    code = blank(CHAT_JS)
    start = code.index("export async function handleChatSubmit(")
    return code[start:start + len(js_definition(CHAT_JS.read_text(encoding="utf-8"), start))]


def _dispatch_head() -> str:
    """The live dispatcher from the moment a `data:` line is read up to its
    first event arm: background detection, `[DONE]`, the parse, the error check
    and whatever marks the first output. Cut from comment-blanked text by its
    own delimiters; it opens a `try` that the harness closes."""
    code = _live_handler()
    opening = "const data = line.slice(6);"
    closing = "if (json.type === 'generated_image') {"
    assert code.count(opening) == 1 and code.count(closing) == 1
    start = code.index(opening)
    return code[start:code.index(closing, start)]


def _meter_statement() -> str:
    """Where the turn's meter is made — and, since `B907`, handed to the wait
    messages. Cut out and run, so the hand-over is the file's, not the test's."""
    code = blank(CHAT_JS)
    opening = "const _meter = createAgentMeter();"
    assert code.count(opening) == 1
    start = code.index(opening)
    return code[start:code.index("const _generatedImagesForTurn = [];", start)]


def _stream(sandbox, body):
    """The real timers, marker and dispatcher head from `chat.js`, a clock the
    test moves, and the reply's spinner as the one thing they write to."""
    script = """
        let clock = 0;
        const timers = [];
        let nextId = 1;
        const setTimeout = (fn, ms) => { const t = { id: nextId++, fn, at: clock + ms }; timers.push(t); return t.id; };
        const setInterval = (fn, ms) => { const t = { id: nextId++, fn, at: clock + ms, every: ms }; timers.push(t); return t.id; };
        const clearTimeout = (id) => { const i = timers.findIndex((t) => t.id === id); if (i >= 0) timers.splice(i, 1); };
        const clearInterval = clearTimeout;
        Date.now = () => clock;
        function advance(to) {
          for (;;) {
            const due = timers.filter((t) => t.at <= to).sort((a, b) => a.at - b.at)[0];
            if (!due) break;
            clock = due.at;
            if (due.every) due.at += due.every; else timers.splice(timers.indexOf(due), 1);
            due.fn();
          }
          clock = to;
        }
        const { FIRST_TOKEN_WAIT_FROM_MS, endsFirstTokenWait, firstTokenWaitText,
                createAgentMeter, presentMeterEvent } = m;
        let accumulated = '';
        const abortCtrl = { signal: { aborted: false } };
        const spinner = { element: {}, message: 'Processing request',
          updateMessage(t) { this.message = t; } };
        const shown = [];
        const origUpdate = spinner.updateMessage;
        spinner.updateMessage = function (t) { shown.push([clock, t]); origUpdate.call(this, t); };
        const sessionModule = { getCurrentSessionId: () => 's1' };
        const streamSessionId = 's1';
        const _backgroundStreams = new Map();
        let _nextIsError = false, _streamTerminalError = null, _streamSawDone = false;
        const createTerminalStreamError = (j) => ({ message: String(j.status) });
        const clearResponseTimeout = () => {};
        const clearProcessingProbe = () => {};
        let firstTokenWaitTimers = [];
        let firstTokenWaitMeter = null;
        %s
        %s
        let _firstVisibleOutputSeen = false;
        %s
        function feed(obj) {
          const line = 'data: ' + JSON.stringify(obj);
          for (const _ of [0]) {
            if (line.startsWith('data: ')) {
              %s
              } catch (e) { throw e; }
            }
          }
        }
        %s
    """ % (
        _declaration("const clearFirstTokenWaitTimers = () => {"),
        _declaration("const scheduleFirstTokenWaitMessages = () => {"),
        _declaration("const markFirstVisibleOutput = ("),
        _dispatch_head(),
        body,
    )
    return _run(sandbox, "const m = await import('./agentMeter.js');\n", script)


def test_a_stream_that_opens_and_then_goes_quiet_says_so_at_twenty_seconds(sandbox):
    """The row's `Verify:`. `stream_steerable`, then nothing for 25s."""
    out = _stream(sandbox, """
        scheduleFirstTokenWaitMessages();
        advance(10); feed({ type: 'stream_steerable', steerable: true });
        advance(25000);
        console.log(JSON.stringify({ label: spinner.message }));
    """)
    assert out["label"] == "Waiting for the model · ~25s"


def test_a_slow_model_after_preparation_is_counted_on_the_spinner(sandbox):
    """Preparation took 30s, the model a minute and a half more. While a step
    runs its label stays; once prep is done the spinner counts the model's
    wait, and the count moves rather than freezing at a mark."""
    out = _stream(sandbox, """
        scheduleFirstTokenWaitMessages();
        %s
        const prep = (frame) => { feed(frame); presentMeterEvent(_meter, frame, spinner); };
        advance(10); feed({ type: 'stream_steerable', steerable: true });
        advance(20); prep(%s);
        advance(25000);
        const during = spinner.message;
        advance(30000); prep(%s);
        advance(45000);
        const at45 = spinner.message;
        advance(95000);
        console.log(JSON.stringify({ during, at45, at95: spinner.message }));
    """ % (_meter_statement(), json.dumps(_PREP_RUNNING), json.dumps(_PREP_DONE)))
    assert out["during"] == "Choosing tools", "a running step's label was overwritten"
    assert out["at45"] == "Waiting for the model · ~15s", out
    assert out["at95"] == "Waiting for the model · ~1m 05s", out


def test_the_first_token_calls_it_off(sandbox):
    out = _stream(sandbox, """
        scheduleFirstTokenWaitMessages();
        advance(10); feed({ type: 'stream_steerable', steerable: true });
        advance(21000);
        const before = spinner.message;
        feed({ delta: 'Hello' });
        advance(200000);
        console.log(JSON.stringify({ before, after: spinner.message, left: timers.length }));
    """)
    assert out["before"] == "Waiting for the model · ~21s"
    assert out["after"] == out["before"], "a message was set after the first token"
    assert out["left"] == 0


@pytest.mark.parametrize("first", [
    {"type": "tool_start", "tool": "bash", "command": "ls"},
    {"type": "tool_blocked", "tool": "bash"},
    {"delta": "Considering it", "thinking": True},
])
def test_a_tool_call_or_a_thinking_token_calls_it_off_too(sandbox, first):
    out = _stream(sandbox, """
        scheduleFirstTokenWaitMessages();
        advance(10); feed({ type: 'stream_steerable', steerable: true });
        feed({ type: 'model_actual', model: 'm' });
        advance(4000); feed(%s);
        advance(200000);
        console.log(JSON.stringify({ shown, left: timers.length }));
    """ % json.dumps(first))
    assert out["shown"] == [] and out["left"] == 0, out


def test_nothing_is_written_once_text_has_arrived(sandbox):
    """The guard it always had: a reply already on screen is never relabelled."""
    out = _stream(sandbox, """
        scheduleFirstTokenWaitMessages();
        advance(10); feed({ type: 'stream_steerable', steerable: true });
        accumulated = 'partial';
        advance(130000);
        console.log(JSON.stringify({ shown }));
    """)
    assert out["shown"] == []
