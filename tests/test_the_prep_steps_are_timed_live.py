# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P4-08` — the agent's preparation, step by step, while it happens.

The loop times four preparation steps — request setup, tool selection, prompt
build, context trim — into `prep_timings`, and has done since before this fork.
Measured on the tree this row started from, three things stood between those
figures and a person:

  * **they were sent once, after the fact.** One `agent_prep` frame, yielded
    after the fourth step had finished — the only live signal about preparation
    could only ever arrive once there was no preparation left to report;
  * **the chat route dropped it.** `/api/chat_stream` forwards an agent event
    only if its type is on a list, and `agent_prep` was not on it. Driven
    through the route with a stubbed loop, the frame went in and did not come
    out. So what a person saw for the whole of preparation and the model's
    first token was the static label *Processing request*;
  * **the handler that would have drawn it was static too.** It replaced the
    spinner with the words *Preparing agent* — at the moment preparing ended.

Now: a frame as each step **starts** (`status: running`, the step's `phase`,
and the steps before it with their measured times), then one `status: done`
with all four and the `total` Message Stats reports as *Prep*. The route
forwards the loop's own list of meter events. The spinner names the running
step; the line under it names the finished ones with the server's figures, and
the running one with a `~` count from the browser — measured and estimated are
told apart on the screen (`Law 10`). Message Stats names the four the same way.

Driven, not read (`Law 20`): the loop under stubs, the route with a stubbed
loop, the module and the popup under node, and the chat.js arm cut out of the
real file and executed.
"""

import asyncio
import json
import shutil
import textwrap
import time
from pathlib import Path

import pytest

import src.agent_loop as agent_loop
from tests.helpers.source_text import blank  # B290
from test_foreground_model_routing import _RouteRequest, _chat_stream_endpoint  # noqa: E402
from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402
from test_message_stats_surface_js import (  # noqa: E402
    _PREAMBLE as _STATS_PREAMBLE,
    _STATS_SHIM,
    _STUBS as _STATS_STUBS,
    _rows,
)

ROOT = Path(__file__).resolve().parents[1]
AGENT_METER = ROOT / "static" / "js" / "agentMeter.js"
CHAT_RENDERER = ROOT / "static" / "js" / "chatRenderer.js"
CHAT_JS = ROOT / "static" / "js" / "chat.js"

node_only = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

PHASES = ["request_setup", "tool_selection", "prompt_build", "context_trim"]


# ── the loop ────────────────────────────────────────────────────────────────


def _patch(monkeypatch, reply="All done, here is the answer."):
    monkeypatch.setattr(agent_loop, "get_setting", lambda key, default=None: default,
                        raising=False)
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: None, raising=False)
    monkeypatch.setattr(agent_loop, "estimate_tokens", lambda *a, **k: 10, raising=False)
    monkeypatch.setattr(agent_loop, "blocked_tools_for_owner", lambda owner: set(),
                        raising=False)

    async def fake_stream(*args, **kwargs):
        yield f"data: {json.dumps({'delta': reply})}\n\n"
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", fake_stream, raising=False)


def _loop(**kwargs):
    return agent_loop.stream_agent_loop(
        "http://x/v1", "m",
        [{"role": "user", "content": "look into why the nightly build fails"}],
        max_rounds=2, relevant_tools={"update_plan"}, **kwargs,
    )


def _drain(generator, on_frame=None):
    """Every JSON frame, in order. `on_frame(frame)` runs as each arrives —
    before the generator is resumed, exactly as a slow consumer would."""
    async def _go():
        frames = []
        async for chunk in generator:
            if not chunk.startswith("data: ") or chunk.startswith("data: [DONE]"):
                continue
            try:
                frame = json.loads(chunk[6:])
            except json.JSONDecodeError:
                continue
            frames.append(frame)
            if on_frame is not None:
                on_frame(frame)
        return frames
    return asyncio.run(_go())


def _prep(frames):
    return [f for f in frames if f.get("type") == "agent_prep"]


def test_each_step_is_announced_as_it_starts_then_once_when_all_are_done(monkeypatch):
    _patch(monkeypatch)
    prep = _prep(_drain(_loop()))
    assert [(f["status"], f.get("phase")) for f in prep] == [
        ("running", "request_setup"),
        ("running", "tool_selection"),
        ("running", "prompt_build"),
        ("running", "context_trim"),
        ("done", None),
    ], prep
    # Each frame carries exactly the steps that have finished before it.
    assert [list(f["data"]) for f in prep] == [
        [], PHASES[:1], PHASES[:2], PHASES[:3], PHASES,
    ]


def test_a_step_is_announced_before_its_work_runs_not_after(monkeypatch):
    """The row's word is *live*. Hook one function inside three of the four
    steps and record which frames the consumer already holds when it runs: the
    step's own frame must be there, and the next step's must not."""
    _patch(monkeypatch)
    seen = []
    at_call = {}

    def spy(name, real):
        def wrapped(*args, **kwargs):
            at_call.setdefault(name, [(f.get("status"), f.get("phase")) for f in seen])
            return real(*args, **kwargs)
        return wrapped

    import src.context_compactor as compactor
    monkeypatch.setattr(agent_loop, "_classify_agent_request",
                        spy("request_setup", agent_loop._classify_agent_request))
    monkeypatch.setattr(agent_loop, "_build_system_prompt",
                        spy("prompt_build", agent_loop._build_system_prompt))
    monkeypatch.setattr(compactor, "trim_for_context",
                        spy("context_trim", compactor.trim_for_context))

    _drain(_loop(), on_frame=lambda f: seen.append(f) if f.get("type") == "agent_prep" else None)

    for step in ("request_setup", "prompt_build", "context_trim"):
        held = at_call[step]
        assert held and held[-1] == ("running", step), (
            f"{step} ran while the consumer held {held} — its frame was not out yet"
        )


def _jumping_clock(monkeypatch):
    """The wall clock the loop reads, plus a jump this test controls.

    Real time keeps flowing, so nothing that waits on the clock can hang; the
    jump is what a step's figure must or must not contain. An hour is far past
    anything a loaded machine adds, so the assertions below are about *which
    window holds the jump* and cannot be turned by a slow CI box."""
    offset = [0.0]
    real = time.time
    monkeypatch.setattr(time, "time", lambda: real() + offset[0])

    def jump():
        offset[0] += 3600.0
    return jump


def test_the_figures_are_measured_on_the_step_they_name(monkeypatch):
    """A step that takes an hour is the one whose figure says so, and only once
    it has finished — the frame announcing it carries no figure for it yet."""
    _patch(monkeypatch)
    jump = _jumping_clock(monkeypatch)
    real = agent_loop._build_system_prompt

    def slow(*args, **kwargs):
        jump()
        return real(*args, **kwargs)

    monkeypatch.setattr(agent_loop, "_build_system_prompt", slow)
    prep = _prep(_drain(_loop()))
    announcing = next(f for f in prep if f.get("phase") == "prompt_build")
    after = next(f for f in prep if f.get("phase") == "context_trim")
    assert "prompt_build" not in announcing["data"]
    assert after["data"]["prompt_build"] >= 3600
    assert after["data"]["request_setup"] < 1800
    assert after["data"]["tool_selection"] < 1800


def test_the_frame_is_sent_outside_the_window_it_times(monkeypatch):
    """A consumer that takes its time over each frame must not make a step look
    slow. Every frame the consumer receives moves the clock an hour, so a yield
    sitting inside a step's window would put an hour into that step's figure."""
    _patch(monkeypatch)
    jump = _jumping_clock(monkeypatch)
    frames = _drain(_loop(), on_frame=lambda f: jump() if f.get("type") == "agent_prep" else None)
    done = _prep(frames)[-1]["data"]
    for step in PHASES:
        assert done[step] < 1800, (step, done)


def test_the_live_total_is_the_one_message_stats_reports(monkeypatch):
    """`Law 7`: the last frame and the final metrics are two readings of one
    measurement, and they must print the same figures."""
    _patch(monkeypatch)
    frames = _drain(_loop())
    done = _prep(frames)[-1]
    metrics = next(f for f in frames if f.get("type") == "metrics")["data"]
    assert done["data"] == metrics["agent_prep_breakdown"]
    assert done["total"] == metrics["agent_prep_time"]


# ── the route ───────────────────────────────────────────────────────────────


async def _through_route(monkeypatch, chunks):
    captured = {}
    endpoint = _chat_stream_endpoint(monkeypatch, "agent", captured, agent_chunks=chunks)
    response = await endpoint(_RouteRequest("agent"))
    out = []
    async for chunk in response.body_iterator:
        text = chunk if isinstance(chunk, str) else chunk.decode()
        if text.startswith("data: {"):
            out.append(json.loads(text[6:]))
    return out


@pytest.mark.asyncio
async def test_the_chat_route_forwards_the_prep_frames(monkeypatch):
    """The route dropped `agent_prep` before this row — measured by pushing it
    through with a stubbed loop and getting nothing back."""
    sent = [
        {"type": "agent_prep", "status": "running", "phase": "tool_selection",
         "data": {"request_setup": 0.012}},
        {"type": "agent_prep", "status": "done", "total": 0.9,
         "data": dict.fromkeys(PHASES, 0.225)},
    ]
    chunks = [f"data: {json.dumps(f)}\n\n" for f in sent] + ["data: [DONE]\n\n"]
    out = await _through_route(monkeypatch, chunks)
    assert [f for f in out if f.get("type") == "agent_prep"] == sent


@pytest.mark.asyncio
async def test_the_route_forwards_what_the_loop_lists_not_a_copy(monkeypatch):
    """Every type on the loop's own list gets through — so an event added to it
    cannot be dropped by a route that kept its own list."""
    chunks = [f"data: {json.dumps({'type': t, 'round': 1})}\n\n"
              for t in agent_loop.AGENT_METER_EVENT_TYPES] + ["data: [DONE]\n\n"]
    out = await _through_route(monkeypatch, chunks)
    assert [f["type"] for f in out if f.get("type") in agent_loop.AGENT_METER_EVENT_TYPES] \
        == list(agent_loop.AGENT_METER_EVENT_TYPES)


# ── the line under the spinner ──────────────────────────────────────────────

_METER_SHIM = r"""
import { installDom, Node } from './dom.js';
export const document = installDom();
export { Node };

/** The meter's node, read the way a person reads it. `html` is the raw markup
 *  behind each text part: '' unless something wrote markup into it. */
export function read(node) {
  if (!node) return null;
  const part = (cls) => node.querySelector('.' + cls);
  const txt = (cls) => { const n = part(cls); return n && !n.hidden ? n.textContent : null; };
  return {
    prep: txt('agent-meter-prep'),
    prepTitle: part('agent-meter-prep') ? part('agent-meter-prep').title : '',
    steps: txt('agent-meter-steps'),
    tools: txt('agent-meter-tools'),
    note: txt('agent-meter-note'),
    noteTone: part('agent-meter-note') ? (part('agent-meter-note').dataset.tone || '') : '',
    budgetTitle: part('agent-meter-budget') ? part('agent-meter-budget').title : '',
    budgetHidden: part('agent-meter-budget') ? !!part('agent-meter-budget').hidden : true,
    bars: node.querySelectorAll('.agent-meter-bar').map((b) => ({
      kind: b.dataset.kind, hidden: !!b.hidden, tone: b.dataset.tone || '',
      width: b.querySelector('.agent-meter-fill').style.width || '',
      now: b.getAttribute('aria-valuenow'), max: b.getAttribute('aria-valuemax'),
      role: b.getAttribute('role'),
    })),
    html: ['agent-meter-prep', 'agent-meter-steps', 'agent-meter-tools', 'agent-meter-note']
      .map((c) => (part(c) ? part(c)._html : '')),
    hidden: !!node.hidden,
  };
}
"""

_METER_PREAMBLE = (
    "import { document, read, Node } from './shim.js';\n"
    "const m = await import('./agentMeter.js');\n"
)


@pytest.fixture(scope="module")
def meter_sandbox(tmp_path_factory):
    if not shutil.which("node"):
        pytest.skip("node binary not on PATH")
    return _make_sandbox(tmp_path_factory.mktemp("agentmeter"), AGENT_METER, _METER_SHIM, {})


def _frames_script(frames, clock_steps):
    """A meter driven through `frames`, with the browser clock at
    `clock_steps[i]` ms when frame i arrives; reports the label and the line
    after each."""
    return """
        let clock = 0;
        const meter = m.createAgentMeter({ document, now: () => clock,
          setInterval: () => 1, clearInterval: () => {} });
        const out = [];
        const frames = %s;
        const clocks = %s;
        frames.forEach((f, i) => {
          clock = clocks[i];
          meter.update(f);
          out.push({ label: meter.spinnerLabel(), meter: read(meter.node) });
        });
        console.log(JSON.stringify(out));
    """ % (json.dumps(frames), json.dumps(clock_steps))


_RUNNING = [
    {"type": "agent_prep", "status": "running", "phase": "request_setup", "data": {}},
    {"type": "agent_prep", "status": "running", "phase": "tool_selection",
     "data": {"request_setup": 0.012}},
    {"type": "agent_prep", "status": "running", "phase": "prompt_build",
     "data": {"request_setup": 0.012, "tool_selection": 0.84}},
    {"type": "agent_prep", "status": "running", "phase": "context_trim",
     "data": {"request_setup": 0.012, "tool_selection": 0.84, "prompt_build": 3.214}},
    {"type": "agent_prep", "status": "done", "total": 4.1,
     "data": {"request_setup": 0.012, "tool_selection": 0.84, "prompt_build": 3.214,
              "context_trim": 0.034}},
]


@node_only
def test_the_browser_names_exactly_the_steps_the_loop_times(monkeypatch, meter_sandbox):
    """One vocabulary across the wire: the browser's table of step names is
    held equal to the steps the loop is observed to announce and measure — not
    to a third list either side could drift from."""
    _patch(monkeypatch)
    prep = _prep(_drain(_loop()))
    announced = [f["phase"] for f in prep if f["status"] == "running"]
    assert list(prep[-1]["data"]) == announced
    named = _run(meter_sandbox, _METER_PREAMBLE,
                 "console.log(JSON.stringify(m.PREP_PHASES.map((p) => p.key)));")
    assert named == announced


@node_only
def test_the_spinner_names_the_step_that_is_running(meter_sandbox):
    """The row: *replaces a static spinner label*. Four steps, four labels, and
    the fifth says what is actually being waited on once they are done."""
    out = _run(meter_sandbox, _METER_PREAMBLE, _frames_script(_RUNNING, [0, 10, 900, 4100, 4200]))
    assert [o["label"] for o in out] == [
        "Reading the request", "Choosing tools", "Building the prompt",
        "Fitting the context window", "Waiting for the model",
    ]


@node_only
def test_the_line_under_it_gives_each_finished_step_its_measured_time(meter_sandbox):
    out = _run(meter_sandbox, _METER_PREAMBLE, _frames_script(_RUNNING, [0, 10, 900, 4100, 4200]))
    assert out[1]["meter"]["prep"] == "Preparing · Request setup 0.01s · Tool selection…"
    assert out[3]["meter"]["prep"].startswith(
        "Preparing · Request setup 0.01s · Tool selection 0.84s · Prompt build 3.21s")
    assert out[4]["meter"]["prep"] == (
        "Prepared in 4.10s · Request setup 0.01s · Tool selection 0.84s · "
        "Prompt build 3.21s · Context trim 0.03s")


@node_only
def test_measured_and_counted_figures_are_told_apart(meter_sandbox):
    """`Law 10`. A step still running shows the browser's own count, marked
    `~` (the mark Message Stats already uses for an estimate); the moment the
    server's figure lands it replaces the count and the mark goes. No figure
    the server measured ever carries it."""
    frames = [_RUNNING[2], _RUNNING[3]]
    out = _run(meter_sandbox, _METER_PREAMBLE, """
        let clock = 0;
        const meter = m.createAgentMeter({ document, now: () => clock,
          setInterval: () => 1, clearInterval: () => {} });
        meter.update(%s);
        clock = 2600; meter.refresh();
        const counting = read(meter.node).prep;
        meter.update(%s);
        console.log(JSON.stringify({ counting, measured: read(meter.node).prep,
          title: read(meter.node).prepTitle }));
    """ % (json.dumps(frames[0]), json.dumps(frames[1])))
    assert "Prompt build ~2s" in out["counting"]
    assert "0.84s" in out["counting"] and "~0.84" not in out["counting"]
    assert "Prompt build 3.21s" in out["measured"]
    assert "~" not in out["measured"].split("Context trim")[0]
    assert "measured on the server" in out["title"] and "~" in out["title"]


@node_only
def test_the_prep_line_gives_way_once_the_run_is_under_way(meter_sandbox):
    """It is about the wait before the first answer. It stays through step 1
    until a tool call is counted, and then stops riding every spinner for the
    rest of the turn saying the same finished thing."""
    budget = {"type": "agent_budget", "round": 1, "round_limit": 20,
              "round_limit_source": "configured", "round_limit_configured": 20,
              "tool_calls": 0, "tool_call_limit": None}
    out = _run(meter_sandbox, _METER_PREAMBLE, _frames_script(
        [_RUNNING[4], budget, dict(budget, tool_calls=1), dict(budget, round=2, tool_calls=1)],
        [0, 0, 0, 0]))
    shown = [o["meter"]["prep"] for o in out]
    assert shown[0].startswith("Prepared in 4.10s") and shown[1] == shown[0]
    assert shown[2] is None and shown[3] is None
    assert out[3]["meter"]["steps"] == "Step 2 of 20"


@node_only
def test_a_step_timed_under_ten_milliseconds_is_not_printed_as_zero(meter_sandbox):
    """The server rounds to the millisecond, so a fast step arrives as `0.0`.
    `0.00s` would read as a step that did not run."""
    out = _run(meter_sandbox, _METER_PREAMBLE, """
        console.log(JSON.stringify([0, 0.004, 0.012, 12.34, 75].map(m.formatPrepSeconds)));
    """)
    assert out == ["<0.01s", "<0.01s", "0.01s", "12.3s", "1m 15s"]


@node_only
def test_a_frame_from_before_this_row_still_reads_as_done(meter_sandbox):
    """The single frame the loop used to send had no `status`. It only ever went
    out once everything was finished, so that is what it means."""
    out = _run(meter_sandbox, _METER_PREAMBLE, _frames_script(
        [{"type": "agent_prep", "data": {"request_setup": 0.2, "tool_selection": 0.3}}], [0]))
    assert out[0]["label"] == "Waiting for the model"
    assert out[0]["meter"]["prep"] == "Prepared · Request setup 0.20s · Tool selection 0.30s"


@node_only
def test_junk_never_reaches_the_screen(meter_sandbox):
    """An unknown step is ignored rather than named, a non-number is no figure
    at all, and nothing prints `undefined` or `NaN`; every part is text."""
    out = _run(meter_sandbox, _METER_PREAMBLE, _frames_script([
        {"type": "agent_prep", "status": "running", "phase": "<b>x</b>", "data": {}},
        {"type": "agent_prep", "status": "running", "phase": "prompt_build",
         "data": {"request_setup": "fast", "tool_selection": -1, "<i>": 3}},
    ], [0, 5]))
    assert out[0]["meter"] is None, "an unknown step drew something"
    shown = out[1]["meter"]
    assert shown["prep"] == "Preparing · Prompt build…"
    assert "undefined" not in json.dumps(out) and "NaN" not in json.dumps(out)
    assert shown["html"] == ["", "", "", ""]


@node_only
def test_a_replayed_stream_draws_the_same_line(meter_sandbox):
    """`P4-24` resumes a stream by replaying its buffer from the start. The
    same frames twice over, into a fresh meter, draw the same thing — and a
    step announced twice keeps the moment it first started."""
    out = _run(meter_sandbox, _METER_PREAMBLE, """
        const frames = %s;
        const draw = () => {
          const meter = m.createAgentMeter({ document, now: () => 0,
            setInterval: () => 1, clearInterval: () => {} });
          frames.forEach((f) => meter.update(f));
          return read(meter.node);
        };
        let s = m.createMeterState();
        s = m.reduceMeter(s, frames[2], 100);
        s = m.reduceMeter(s, frames[2], 900);
        console.log(JSON.stringify({ a: draw(), b: draw(), since: s.prep.phaseSince }));
    """ % json.dumps(_RUNNING))
    assert out["a"] == out["b"]
    assert out["since"] == 100


# ── Message Stats ───────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def stats_sandbox(tmp_path_factory):
    if not shutil.which("node"):
        pytest.skip("node binary not on PATH")
    return _make_sandbox(tmp_path_factory.mktemp("prepstats"), CHAT_RENDERER,
                         _STATS_SHIM, _STATS_STUBS)


@node_only
def test_message_stats_names_the_steps_the_way_the_live_line_did(stats_sandbox):
    """The popup printed the raw keys — `tool_selection: 0.84s` — so the same
    four figures had two names depending on when you looked."""
    metrics = {
        "response_time": 3.0, "input_tokens": 900, "output_tokens": 300,
        "tokens_per_second": 60.0, "usage_source": "real", "model": "org/m",
        "agent_prep_time": 4.1, "agent_model_wait_time": 1.0,
        "agent_prep_breakdown": {"request_setup": 0.012, "tool_selection": 0.84,
                                 "prompt_build": 3.214, "context_trim": 0.034},
    }
    out = _run(stats_sandbox, _STATS_PREAMBLE, """
        console.log(JSON.stringify(open(displayMetrics, %s)));
    """ % json.dumps(metrics))
    html = out["popup"]["rowsHtml"]
    assert "tool_selection" not in html and "request_setup" not in html
    text = " ".join(_rows(out["popup"]).rows)
    for words in ("Request setup 0.01s", "Tool selection 0.84s",
                  "Prompt build 3.21s", "Context trim 0.03s"):
        assert words in text, (words, text)


@node_only
def test_a_stored_key_cannot_become_markup_in_the_popup(stats_sandbox):
    metrics = {
        "response_time": 3.0, "input_tokens": 900, "output_tokens": 300,
        "tokens_per_second": 60.0, "usage_source": "real", "model": "org/m",
        "agent_prep_breakdown": {"<img src=x onerror=alert(1)>": 1.5},
    }
    out = _run(stats_sandbox, _STATS_PREAMBLE, """
        console.log(JSON.stringify(open(displayMetrics, %s)));
    """ % json.dumps(metrics))
    assert "<img" not in out["popup"]["rowsHtml"]


# ── the stream handler ──────────────────────────────────────────────────────


def _meter_arms() -> str:
    """The three meter arms of chat.js's stream dispatcher, cut out of the real
    file by their own delimiters — comments blanked first, so a delimiter
    quoted in prose cannot be taken for code."""
    src = blank(CHAT_JS)
    opening = "if (json.type === 'agent_prep') {"
    closing = "if (json.type === 'tool_approval_resolved') {"
    assert src.count(opening) == 1, "the agent_prep arm is no longer a unique anchor"
    start = src.index(opening)
    return src[start:src.index(closing, start)]


def drive_meter_arms(events):
    """Run the real arms over `[json, isBg]` pairs with every collaborator
    stubbed; report each call they make, and whether each event fell through."""
    import subprocess
    script = textwrap.dedent("""
        const calls = [];
        const thinking = { element: {}, id: 'thinking-spinner' };
        const _meter = { spinnerLabel: () => 'Choosing tools' };
        const presentMeterEvent = (meter, json, host) => {
          calls.push(['present', json.type, host ? host.id : null, meter === _meter]);
        };
        const _cancelThinkingTimer = () => calls.push(['cancelThinkingTimer']);
        const _replaceThinkingSpinner = (l) => calls.push(['replaceThinkingSpinner', l]);
        let hostAvailable = true;
        const _waitSpinner = () => (hostAvailable ? thinking : null);
        for (const [json, _isBg, withHost] of %s) {
          hostAvailable = withHost !== false;
          %s
          calls.push(['fell-through', json.type]);
        }
        console.log(JSON.stringify(calls));
    """) % (json.dumps(events), _meter_arms())
    proc = subprocess.run(["node", "--input-type=module", "-e", script],
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


@node_only
def test_the_stream_handler_hands_prep_frames_to_the_meter():
    calls = drive_meter_arms([[{"type": "agent_prep", "status": "running",
                                "phase": "tool_selection", "data": {}}, False]])
    assert ["present", "agent_prep", "thinking-spinner", True] in calls
    assert ["cancelThinkingTimer"] in calls
    assert ["fell-through", "agent_prep"] not in calls, "the frame fell through to later arms"
    assert not any(c[0] == "replaceThinkingSpinner" for c in calls), (
        "the static 'Preparing agent' spinner is still being swapped in")


@node_only
def test_a_background_stream_advances_the_meter_and_draws_nothing():
    calls = drive_meter_arms([[{"type": "agent_prep", "status": "done", "data": {}}, True]])
    assert ["present", "agent_prep", None, True] in calls
    assert ["cancelThinkingTimer"] not in calls


@node_only
def test_with_no_spinner_on_screen_the_prep_label_opens_one():
    """This arm has always opened a thinking spinner when it found none; it
    still does, now carrying the running step instead of fixed words."""
    calls = drive_meter_arms([[{"type": "agent_prep", "status": "running",
                                "phase": "tool_selection", "data": {}}, False, False]])
    assert ["present", "agent_prep", None, True] in calls
    assert ["replaceThinkingSpinner", "Choosing tools"] in calls
