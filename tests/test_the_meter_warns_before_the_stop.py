# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P4-23` — the step and tool-call limits, shown before either is reached.

A run is held to a step limit (`agent_max_rounds`, 20 by default, 1..200) and
optionally a tool-call limit (`agent_max_tool_calls`, `0` meaning none). The
row says *the agent already streams step events*, and it does — `agent_step`,
with the number of the step about to start. Measured on the tree this row
started from, that was all that was streamed:

  * **no limit was on the wire until it had been hit.** The step cap appeared
    in exactly one event, `rounds_exhausted`, and the tool-call cap in exactly
    one, `budget_exceeded` — the events that end the run. `total_tool_calls`
    was never sent at all. So the first a person learned of either limit was
    *"Reached the 20-step limit — not finished"* or *"Tool budget reached (10/10
    calls). Agent stopped."*;
  * **the limit that applies is not the one in Settings.** On local inference
    `H08` lifts a step cap nobody pinned to 100,000, so the 20 a person set is
    not the 20 the loop enforces. A meter reading the setting would draw a bar
    that fills at step 20 and a run that keeps going;
  * **a refused call counts.** The budget check counts every call the model
    makes, including one the policy then refuses — which draws no tool card.
    A meter counting cards would read low and the stop would still surprise.

So the loop now sends `agent_budget` — its own counters and its own caps, the
ones the `for` and the budget check read, after the lift — at the top of every
step and after every counted call. The browser draws *Step 3 of 20* and *Tool
calls 7 of 10* under the spinner, says what happens at each limit at the start
of the run and again when one is close, and says *limit lifted (local model)*
rather than drawing a bar toward 100,000.

Driven, not read (`Law 20`).
"""

import asyncio
import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

import src.agent_loop as agent_loop
import src.runtime_limits as runtime_limits
from tests.helpers.js_source import js_definition  # B876
from tests.helpers.source_text import blank, blank_text  # B290
from test_foreground_model_routing import _RouteRequest, _chat_stream_endpoint  # noqa: E402
from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402
from test_the_prep_steps_are_timed_live import (  # noqa: E402
    _METER_PREAMBLE, _METER_SHIM, drive_meter_arms,
)

ROOT = Path(__file__).resolve().parents[1]
AGENT_METER = ROOT / "static" / "js" / "agentMeter.js"
SPINNER = ROOT / "static" / "js" / "spinner.js"
CHAT_JS = ROOT / "static" / "js" / "chat.js"
STYLE = ROOT / "static" / "style.css"

node_only = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

# Three distinct calls in one reply: `update_plan` is a system-owned tool, so a
# run of them stays a loop-control test rather than an approval test.
PLAN = '```update_plan\n{"plan":"- [ ] step %d"}\n```'
BATCH = "\n".join(PLAN % i for i in range(3))


# ── the loop ────────────────────────────────────────────────────────────────


def _patch(monkeypatch, reply=BATCH):
    monkeypatch.setattr(agent_loop, "get_setting", lambda key, default=None: default,
                        raising=False)
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: None, raising=False)
    monkeypatch.setattr(agent_loop, "estimate_tokens", lambda *a, **k: 10, raising=False)
    monkeypatch.setattr(agent_loop, "blocked_tools_for_owner", lambda owner: set(),
                        raising=False)

    async def fake_stream(*args, **kwargs):
        yield f"data: {json.dumps({'delta': reply})}\n\n"
        yield "data: [DONE]\n\n"

    async def fake_execute(block, *args, **kwargs):
        return (block.tool_type, {"output": "ok", "exit_code": 0})

    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", fake_stream, raising=False)
    monkeypatch.setattr(agent_loop, "execute_tool_block", fake_execute, raising=False)


def _frames(url="http://x/v1", **kwargs):
    kwargs.setdefault("relevant_tools", {"update_plan"})

    async def _go():
        return [c async for c in agent_loop.stream_agent_loop(
            url, "m", [{"role": "user", "content": "work through the checklist"}], **kwargs)]

    out = []
    for chunk in asyncio.run(_go()):
        if chunk.startswith("data: ") and not chunk.startswith("data: [DONE]"):
            try:
                out.append(json.loads(chunk[6:]))
            except json.JSONDecodeError:
                pass
    return out


def _budget(frames):
    return [f for f in frames if f.get("type") == "agent_budget"]


def test_every_step_starts_by_saying_which_step_of_how_many(monkeypatch):
    _patch(monkeypatch)
    frames = _frames(max_rounds=3)
    budget = _budget(frames)
    tops = [f for i, f in enumerate(budget) if i == 0 or f["round"] != budget[i - 1]["round"]]
    assert [(f["round"], f["round_limit"]) for f in tops] == [(1, 3), (2, 3), (3, 3)]
    assert {f["round_limit_source"] for f in tops} == {"configured"}
    # The stop the meter was counting toward, after its last frame — and no
    # frame names a step past the limit (nor, since `B906`, does `agent_step`).
    stop = next(i for i, f in enumerate(frames) if f.get("type") == "rounds_exhausted")
    assert frames[stop]["rounds"] == 3
    assert max(i for i, f in enumerate(frames) if f.get("type") == "agent_budget") < stop
    assert all(f["round"] <= f["round_limit"] for f in _budget(frames))


def test_each_counted_call_is_reported_before_its_card(monkeypatch):
    _patch(monkeypatch)
    frames = _frames(max_rounds=1)
    counted = [(i, f["tool_calls"]) for i, f in enumerate(frames)
               if f.get("type") == "agent_budget"]
    assert [n for _, n in counted] == [0, 1, 2, 3]
    starts = [i for i, f in enumerate(frames) if f.get("type") == "tool_start"]
    for (frame_at, n), start_at in zip(counted[1:], starts):
        assert frame_at < start_at, f"call {n}'s frame came after its card"


def test_the_meter_reaches_the_limit_before_the_stop(monkeypatch):
    """The row. With a limit of two and a model asking for three, the meter
    reads *2 of 2* before `budget_exceeded` arrives — the surprise is gone."""
    _patch(monkeypatch)
    frames = _frames(max_rounds=3, max_tool_calls=2)
    stop = next(i for i, f in enumerate(frames) if f.get("type") == "budget_exceeded")
    last = [f for f in frames[:stop] if f.get("type") == "agent_budget"][-1]
    assert (last["tool_calls"], last["tool_call_limit"]) == (2, 2)
    assert (frames[stop]["used"], frames[stop]["limit"]) == (2, 2)


def test_no_tool_limit_is_sent_as_none_and_never_as_zero(monkeypatch):
    """`0` in the setting means unlimited. `0` on the wire would read as *no
    calls allowed*, which is the opposite (`Law 10`)."""
    _patch(monkeypatch, reply="All done.")
    [frame] = _budget(_frames(max_rounds=2, max_tool_calls=0))
    assert "tool_call_limit" in frame and frame["tool_call_limit"] is None


def test_a_refused_call_counts_because_the_budget_counts_it(monkeypatch):
    """A call the policy refuses never gets a card, and the budget check still
    counts it. The meter follows the budget, not the cards."""
    _patch(monkeypatch, reply=PLAN % 0)
    frames = _frames(max_rounds=1, max_tool_calls=5, disabled_tools={"update_plan"})
    assert any(f.get("type") == "tool_blocked" for f in frames), "nothing was refused"
    assert not any(f.get("type") == "tool_start" for f in frames)
    assert _budget(frames)[-1]["tool_calls"] == 1


def _pin(monkeypatch, pinned):
    monkeypatch.setattr(agent_loop, "_setting_pinned", lambda key: pinned)


def test_a_local_model_reports_the_lifted_limit_it_actually_enforces(monkeypatch):
    """`H08`: on your own hardware a step cap nobody pinned is lifted. The meter
    says the number the loop enforces and why — never the 20 in Settings."""
    _patch(monkeypatch, reply="All done.")
    _pin(monkeypatch, False)
    [frame] = _budget(_frames(url="http://127.0.0.1:8080/v1", max_rounds=20))
    assert frame["round_limit"] == 100_000
    assert frame["round_limit_source"] == "local_lift"
    assert frame["round_limit_configured"] == 20


def test_a_pinned_limit_is_reported_as_configured_even_on_a_local_model(monkeypatch):
    _patch(monkeypatch, reply="All done.")
    _pin(monkeypatch, True)
    [frame] = _budget(_frames(url="http://127.0.0.1:8080/v1", max_rounds=20))
    assert (frame["round_limit"], frame["round_limit_source"]) == (20, "configured")


def test_a_server_that_forces_the_lift_is_not_called_a_local_model(monkeypatch):
    _patch(monkeypatch, reply="All done.")
    _pin(monkeypatch, False)
    monkeypatch.setattr(runtime_limits, "_FORCE_UNLIMITED", True)
    [frame] = _budget(_frames(url="https://api.example.com/v1", max_rounds=20))
    assert (frame["round_limit"], frame["round_limit_source"]) == (100_000, "forced_lift")


@pytest.mark.asyncio
async def test_the_chat_route_forwards_the_meter(monkeypatch):
    """Before this row the route forwarded agent events from a fixed list and
    dropped everything else; a frame it did not name never reached a browser."""
    sent = {"type": "agent_budget", "round": 2, "round_limit": 20,
            "round_limit_source": "configured", "round_limit_configured": 20,
            "tool_calls": 3, "tool_call_limit": None}
    captured = {}
    endpoint = _chat_stream_endpoint(monkeypatch, "agent", captured, agent_chunks=[
        f"data: {json.dumps(sent)}\n\n", "data: [DONE]\n\n"])
    response = await endpoint(_RouteRequest("agent"))
    out = []
    async for chunk in response.body_iterator:
        text = chunk if isinstance(chunk, str) else chunk.decode()
        if text.startswith("data: {"):
            out.append(json.loads(text[6:]))
    assert sent in out


# ── what the meter says ─────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    if not shutil.which("node"):
        pytest.skip("node binary not on PATH")
    d = _make_sandbox(tmp_path_factory.mktemp("stepmeter"), AGENT_METER, _METER_SHIM, {})
    shutil.copy(SPINNER, d / "spinner.js")   # the real one: the meter hangs under it
    return d


def _budget_frame(round_, limit=20, calls=0, tool_limit=None, source="configured",
                  configured=None, **extra):
    frame = {"type": "agent_budget", "round": round_, "round_limit": limit,
             "round_limit_source": source,
             "round_limit_configured": configured if configured is not None else limit,
             "tool_calls": calls, "tool_call_limit": tool_limit}
    frame.update(extra)
    return frame


def _draw(sandbox, frames):
    """The meter after each frame, read as a person reads it."""
    return _run(sandbox, _METER_PREAMBLE, """
        const meter = m.createAgentMeter({ document, now: () => 0,
          setInterval: () => 1, clearInterval: () => {} });
        const out = [];
        for (const f of %s) { meter.update(f); out.push(read(meter.node)); }
        console.log(JSON.stringify(out));
    """ % json.dumps(frames))


@node_only
def test_the_meter_says_step_n_of_the_limit_and_draws_how_far(sandbox):
    [shown] = _draw(sandbox, [_budget_frame(3, limit=20, calls=7, tool_limit=10)])
    assert shown["steps"] == "Step 3 of 20"
    assert shown["tools"] == "Tool calls 7 of 10"
    steps, tools = shown["bars"]
    assert (steps["kind"], steps["width"], steps["now"], steps["max"]) == ("steps", "15%", "3", "20")
    assert (tools["kind"], tools["width"], tools["now"], tools["max"]) == ("tools", "70%", "7", "10")
    assert steps["role"] == "progressbar" and not steps["hidden"]


@node_only
def test_what_happens_at_each_limit_is_said_at_the_start_of_the_run(sandbox):
    """*Say plainly what happens at the limit before it happens.* Step 1 is
    the first moment the limits are known, and the note says both rules."""
    [shown] = _draw(sandbox, [_budget_frame(1, limit=20, calls=0, tool_limit=10)])
    assert shown["note"] == ("Stops after step 20 and offers Continue · "
                             "Stops outright after 10 tool calls")
    assert shown["noteTone"] == ""
    assert "stops after step 20 and offers Continue" in shown["budgetTitle"]
    assert "Settings › Agent Tools" in shown["budgetTitle"]


@node_only
def test_mid_run_the_meter_is_quiet_and_near_the_end_it_warns(sandbox):
    shown = _draw(sandbox, [
        _budget_frame(5, limit=20, calls=3, tool_limit=10),
        _budget_frame(16, limit=20, calls=3, tool_limit=10),
        _budget_frame(20, limit=20, calls=3, tool_limit=10),
    ])
    assert shown[0]["note"] is None, "a quiet mid-run meter still carries a note"
    assert shown[1]["note"] == "Stops after step 20 and offers Continue"
    assert shown[1]["noteTone"] == "near" and shown[1]["bars"][0]["tone"] == "near"
    assert shown[2]["note"] == "Last step — if it needs more, it stops here and offers Continue"
    assert shown[2]["noteTone"] == "at"


@node_only
def test_the_tool_call_limit_counts_down_and_then_says_the_next_call_stops_it(sandbox):
    shown = _draw(sandbox, [
        _budget_frame(4, calls=8, tool_limit=10),
        _budget_frame(4, calls=9, tool_limit=10),
        _budget_frame(4, calls=10, tool_limit=10),
    ])
    assert [s["note"] for s in shown] == [
        "2 tool calls left, then it stops",
        "1 tool call left, then it stops",
        "Tool-call limit reached — one more call stops it",
    ]
    assert [s["noteTone"] for s in shown] == ["near", "near", "at"]


@node_only
def test_the_stop_itself_is_what_the_meter_ends_on(sandbox):
    shown = _draw(sandbox, [
        _budget_frame(20, limit=20, calls=3),
        {"type": "rounds_exhausted", "rounds": 20},
    ])
    assert shown[-1]["note"] == "Stopped at the 20-step limit"
    shown = _draw(sandbox, [
        _budget_frame(3, calls=10, tool_limit=10),
        {"type": "budget_exceeded", "used": 10, "limit": 10},
    ])
    assert shown[-1]["note"] == "Stopped at the 10-tool-call limit"


@node_only
def test_a_lifted_limit_says_so_and_draws_no_bar_toward_it(sandbox):
    """A bar toward 100,000 is an empty bar and a claim nobody could read."""
    shown = _draw(sandbox, [
        _budget_frame(1, limit=100_000, source="local_lift", configured=20),
        _budget_frame(4, limit=100_000, source="local_lift", configured=20),
    ])
    assert shown[0]["steps"] == "Step 1 · limit lifted (local model)"
    assert shown[0]["note"] == ("Step limit lifted to 100,000 on this local model · "
                                "No tool-call limit")
    assert shown[0]["bars"][0]["hidden"] is True
    assert "20-step limit is lifted to 100,000" in shown[0]["budgetTitle"]
    assert shown[1]["note"] is None
    forced = _draw(sandbox, [_budget_frame(1, limit=100_000, source="forced_lift", configured=20)])
    assert forced[0]["steps"] == "Step 1 · limit lifted (this server)"
    assert "local" not in json.dumps(forced)


@node_only
def test_no_limit_and_an_unreported_limit_read_differently(sandbox):
    """`Law 10`. `null` is the server saying there is no tool-call limit; a
    frame without the key has not said anything, and must not be read as
    *no limit*."""
    none_set = _budget_frame(3, calls=4, tool_limit=None)
    unsaid = {k: v for k, v in none_set.items() if k != "tool_call_limit"}
    a, b = _draw(sandbox, [none_set]), _draw(sandbox, [unsaid])
    assert a[0]["tools"] == "Tool calls 4 · no limit"
    assert b[0]["tools"] == "Tool calls 4"
    assert "not reported" in b[0]["budgetTitle"]


@node_only
def test_a_takeover_starts_a_meter_of_its_own(sandbox):
    """The teacher's run has limits of its own; its first frame must not
    inherit the student's step count."""
    shown = _draw(sandbox, [
        _budget_frame(18, limit=20, calls=9, tool_limit=10),
        _budget_frame(1, limit=50, calls=0, tool_limit=None, teacher=True),
    ])
    assert shown[1]["steps"] == "Teacher · Step 1 of 50"
    assert shown[1]["tools"] == "Tool calls 0 · no limit"


@node_only
def test_junk_frames_draw_nothing_false(sandbox):
    shown = _draw(sandbox, [
        _budget_frame(0),
        _budget_frame("three"),
        _budget_frame(2, limit="<b>20</b>", calls=-1, tool_limit=True,
                      source="<script>", configured=None),
    ])
    assert shown[0] is None and shown[1] is None, "a frame with no real step drew a meter"
    last = shown[2]
    assert last["steps"] == "Step 2"
    assert last["tools"] is None
    text = json.dumps(last)
    assert "undefined" not in text and "NaN" not in text and "<" not in text
    assert last["html"] == ["", "", "", ""]


@node_only
def test_a_replayed_stream_rebuilds_the_same_meter(sandbox):
    """`P4-24` resumes a stream by replaying its buffer from the start. Each
    frame is whole state, so the replay lands exactly where the live view was."""
    frames = [_budget_frame(r, calls=c, tool_limit=10) for r, c in ((1, 0), (1, 2), (2, 2), (2, 5))]
    live = _draw(sandbox, frames)[-1]
    replayed = _draw(sandbox, frames + frames)[-1]
    assert live == replayed


# ── under the spinner ───────────────────────────────────────────────────────

_HOST = """
        const { Spinner } = await import('./spinner.js');
        const bodyA = document.body.appendChild(new Node('div'));
        const bodyB = document.body.appendChild(new Node('div'));
        const spin = (body, label) => {
          const s = new Spinner(label, 'right', 'wave');
          body.appendChild(s.createElement());
          return s;
        };
        const kids = (n) => n.childNodes.map((c) => c.className);
"""


@node_only
def test_the_meter_hangs_under_the_spinner_and_leaves_with_it(sandbox):
    out = _run(sandbox, _METER_PREAMBLE, _HOST + """
        const meter = m.createAgentMeter({ document, now: () => 0,
          setInterval: () => 1, clearInterval: () => {} });
        const a = spin(bodyA, 'Processing request');
        m.presentMeterEvent(meter, %s, a);
        const underA = kids(bodyA);
        const label = a.message;
        a.destroy();
        console.log(JSON.stringify({ underA, label, afterDestroy: kids(bodyA) }));
    """ % json.dumps({"type": "agent_prep", "status": "running", "phase": "prompt_build",
                      "data": {"request_setup": 0.01}}))
    assert out["underA"] == ["ai-spinner", "agent-meter"]
    assert out["label"] == "Building the prompt"
    assert out["afterDestroy"] == []


@node_only
def test_moving_to_the_next_spinner_survives_the_last_ones_late_destroy(sandbox):
    """One node moves from spinner to spinner through a turn. chat.js destroys
    spinners from twenty-odd places, some late; an old spinner going must not
    take the meter from the one now showing it."""
    out = _run(sandbox, _METER_PREAMBLE, _HOST + """
        const meter = m.createAgentMeter({ document, now: () => 0,
          setInterval: () => 1, clearInterval: () => {} });
        const a = spin(bodyA, 'Processing request');
        m.presentMeterEvent(meter, %s, a);
        const b = spin(bodyB, 'Thinking');
        m.presentMeterEvent(meter, %s, b);
        const beforeLateDestroy = [kids(bodyA), kids(bodyB)];
        a.destroy();
        console.log(JSON.stringify({ beforeLateDestroy, after: [kids(bodyA), kids(bodyB)],
          bLabel: b.message }));
    """ % (json.dumps(_budget_frame(1)), json.dumps(_budget_frame(2, calls=1))))
    assert out["beforeLateDestroy"] == [["ai-spinner"], ["ai-spinner", "agent-meter"]]
    assert out["after"] == [[], ["ai-spinner", "agent-meter"]]
    assert out["bLabel"] == "Thinking", "a budget frame relabelled the spinner"


@node_only
def test_an_empty_meter_attaches_nothing(sandbox):
    out = _run(sandbox, _METER_PREAMBLE, _HOST + """
        const meter = m.createAgentMeter({ document, now: () => 0,
          setInterval: () => 1, clearInterval: () => {} });
        const a = spin(bodyA, 'Thinking');
        const attached = meter.attachTo(a);
        m.presentMeterEvent(meter, { type: 'delta' }, a);
        console.log(JSON.stringify({ attached, kids: kids(bodyA) }));
    """)
    assert out == {"attached": False, "kids": ["ai-spinner"]}


@node_only
def test_the_counter_only_runs_while_a_step_does(sandbox):
    """The `~` count ticks once a second while a prep step is running and the
    meter is on the page — and stops by itself, so a turn that ends mid-prep
    leaves no timer behind."""
    out = _run(sandbox, _METER_PREAMBLE, _HOST + """
        let started = 0, stopped = 0, tick = null;
        const meter = m.createAgentMeter({ document, now: () => 0,
          setInterval: (fn) => { started++; tick = fn; return 7; },
          clearInterval: () => { stopped++; } });
        const a = spin(bodyA, 'Processing request');
        m.presentMeterEvent(meter, { type: 'agent_prep', status: 'running',
          phase: 'request_setup', data: {} }, a);
        const whileRunning = [started, stopped];
        tick();                       // not connected in this shim: stops itself
        const afterDetached = [started, stopped];
        m.presentMeterEvent(meter, %s, a);
        m.presentMeterEvent(meter, { type: 'agent_prep', status: 'done', data: {} }, a);
        console.log(JSON.stringify({ whileRunning, afterDetached, final: [started, stopped] }));
    """ % json.dumps(_budget_frame(1)))
    assert out["whileRunning"] == [1, 0]
    assert out["afterDetached"] == [1, 1]
    # Re-attaching while prep still runs starts one ticker; `done` stops it.
    assert out["final"][0] - out["final"][1] == 0


# ── the stream handler ──────────────────────────────────────────────────────


@node_only
def test_the_stream_handler_hands_budget_frames_to_the_meter():
    calls = drive_meter_arms([[_budget_frame(2, calls=1), False]])
    assert ["present", "agent_budget", "thinking-spinner", True] in calls
    assert ["fell-through", "agent_budget"] not in calls


@node_only
def test_the_stops_are_recorded_and_still_reach_their_own_arms():
    calls = drive_meter_arms([[{"type": "rounds_exhausted", "rounds": 20}, False],
                              [{"type": "budget_exceeded", "used": 2, "limit": 2}, False]])
    assert ["present", "rounds_exhausted", None, True] in calls
    assert ["fell-through", "rounds_exhausted"] in calls, (
        "the Continue button's arm no longer runs")
    assert ["present", "budget_exceeded", None, True] in calls
    assert ["fell-through", "budget_exceeded"] in calls


def _function(name: str) -> str:
    """One whole function declaration out of chat.js, through the suite's one
    JavaScript scanner (`B876`: a hand-counted brace walk is the defect it
    exists to stop). Located in comment-blanked text, whose offsets are the
    file's, so a name quoted in a comment cannot be mistaken for the code."""
    code = blank(CHAT_JS)
    return js_definition(CHAT_JS.read_text(encoding="utf-8"),
                         code.index(f"function {name}("))


@node_only
def test_every_new_wait_spinner_carries_the_meter():
    """The spinner between tools and the one a new step opens with are where a
    person waits, so both take the meter the moment they are made."""
    src = blank(CHAT_JS)
    show = _function("_showThinkingSpinner")
    wait = _function("_waitSpinner")
    script = textwrap.dedent("""
        const attached = [];
        const _meter = { attachTo: (s) => attached.push(s.label) };
        const made = [];
        const spinnerModule = { create: (label) => ({ label, element: {},
          createElement() { return { el: label }; }, start() {} }) };
        const nodes = [];
        const document = {
          querySelector: (sel) => nodes.find((n) => String(n.className).split(' ')
                                               .includes(sel.slice(1))) || null,
          createElement: () => { const n = { children: [], appendChild(c) { this.children.push(c); } };
                                  return n; },
          getElementById: () => ({ appendChild(n) { nodes.push(n); } }),
        };
        const uiModule = { scrollHistory() {} };
        let spinner = { element: {}, label: 'Generating response' };
        %s
        %s
        const before = _waitSpinner().label;
        _showThinkingSpinner('Thinking');
        const after = _waitSpinner().label;
        spinner = null; nodes.length = 0;
        console.log(JSON.stringify({ attached, before, after, none: _waitSpinner() }));
    """) % (show, wait)
    proc = subprocess.run(["node", "--input-type=module", "-e", script],
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out["attached"] == ["Thinking"]
    assert out["before"] == "Generating response" and out["after"] == "Thinking"
    assert out["none"] is None

    step_arm = src[src.index("} else if (json.type === 'agent_step') {"):]
    step_arm = step_arm[:step_arm.index("} else if (json.type === 'budget_exceeded') {")]
    made = step_arm[step_arm.index("spinner = spinnerModule.create('Generating response'"):]
    made = made[:made.index("spinner.start();")]
    assert "_meter.attachTo(spinner);" in made, (
        "the spinner a new step opens with no longer takes the meter")


# ── the stylesheet ──────────────────────────────────────────────────────────


def _meter_css() -> str:
    css = blank_text(STYLE.read_text(encoding="utf-8"), "css")
    start = css.index(".agent-meter {")
    return css[start:css.index("@media (prefers-reduced-motion: reduce)", start) + 200]


def test_a_hidden_part_of_the_meter_is_hidden_in_a_real_browser():
    """The module hides a line with the `hidden` attribute, and an author rule
    that sets `display` beats the browser's own `[hidden]` rule — so the meter
    has to say it, or a quiet note still takes up its line."""
    css = _meter_css()
    assert ".agent-meter [hidden]" in css and "display: none !important" in css


def test_the_meter_uses_theme_tokens_and_respects_reduced_motion():
    css = _meter_css()
    assert "var(--accent" not in css
    assert "var(--warn)" in css and "var(--color-muted-alt)" in css
    reduced = css[css.index("@media (prefers-reduced-motion: reduce)"):]
    assert ".agent-meter-fill" in reduced and "transition: none" in reduced
