# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B916` — a compare pane says which step it is on, and why it stopped at a limit.

The chat route forwards `agent_prep` and `agent_budget` to a compare pane as it
does to the main chat, and `static/js/compare/stream.js` had no arm for either,
nor for `rounds_exhausted` or `budget_exceeded`. So a pane's spinner said
*Processing...* through preparation, a pane never said which step it was on or
how close it was to a limit, and a pane that hit one simply stopped — no warning
before and no word after.

The meter is `agentMeter.js`'s, fed through `presentMeterEvent`, the one call
the main chat and a resumed stream make. The part to design was where it hangs:
a pane had no spinner at all after its first tool. It waits on the spinner a new
step opens with in the main chat now (`openRoundSpinner`, moved to
`agentTurn.js` for the purpose). And a pane has no Continue box at the step
limit, so the meter's words there do not promise one, and at a stop the meter
stays in the pane as its last word on why.

Driven under node: the real `streamToPane`, `agentMeter.js`, `agentTurn.js`
and `spinner.js`, in the page `P4-24`'s file sets up (`Law 20`).
"""

import shutil

import pytest

from test_tool_effect_surfaces_js import _run  # noqa: E402
from test_a_compare_pane_draws_the_card_the_chat_draws import (  # noqa: E402,F401
    _PREAMBLE as _CARD_PREAMBLE, sandbox,
)

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


_PREAMBLE = _CARD_PREAMBLE + r"""
const { spinnerWords, meterWords } = await import('./shim.js');
const spinnerModule = (await import('./spinner.js')).default;
// The pane's first spinner, as `compare/index.js` makes it before streaming.
const first = spinnerModule.create('Processing...', 'right');
ai.querySelector('.body').appendChild(first.createElement());
first.start();
ai._spinner = first;
/** What the pane shows right now: its spinner's words and the meter's. */
const look = () => ({ spinner: spinnerWords(ai), meter: meterWords(ai) });
const budget = (round, calls, extra = {}) => Object.assign({ type: 'agent_budget', round,
  round_limit: 20, round_limit_source: 'configured', round_limit_configured: 20,
  tool_calls: calls, tool_call_limit: null }, extra);
"""


def _pane(sandbox, script: str) -> dict:
    return _run(sandbox, _PREAMBLE, script)


def test_while_it_prepares_the_spinner_names_the_step_and_the_line_times_the_rest(sandbox):
    """`P4-08` in a pane: the spinner said *Processing...* for all of it."""
    out = _pane(sandbox, """
        const seen = [];
        await run([
          { type: 'agent_prep', status: 'running', phase: 'request_setup', data: {} },
          () => seen.push(look()),
          { type: 'agent_prep', status: 'running', phase: 'tool_selection', data: { request_setup: 0.12 } },
          () => seen.push(look()),
          { type: 'agent_prep', status: 'done', total: 0.9,
            data: { request_setup: 0.12, tool_selection: 0.5, prompt_build: 0.2, context_trim: 0.08 } },
          () => seen.push(look()),
          { delta: 'Hello.' },
          () => seen.push(look()),
          '[DONE]',
        ]);
        console.log(JSON.stringify({ seen }));
    """)
    s = out["seen"]
    assert s[0]["spinner"] == "Reading the request", s
    assert s[1]["spinner"] == "Choosing tools", s
    assert s[1]["meter"].startswith("Preparing · Request setup 0.12s · Tool selection"), s
    assert s[2]["spinner"] == "Waiting for the model", s
    assert s[2]["meter"] == ("Prepared in 0.90s · Request setup 0.12s · Tool selection 0.50s · "
                             "Prompt build 0.20s · Context trim 0.08s"), s
    assert s[3] == {"spinner": None, "meter": None}, "the prep line outlived the reply's first words"


def test_between_steps_the_pane_waits_on_a_spinner_that_says_which_step(sandbox):
    """The row's `Verify:` — *Step n of N* while it works. After its first tool a
    pane had no spinner at all, so there was nowhere for the meter to hang."""
    out = _pane(sandbox, """
        const seen = [];
        const last = () => { const k = ai.querySelector('.body').children; return k[k.length - 1].className; };
        await run([
          budget(1, 0),
          () => seen.push(look()),
          [budget(1, 1), { type: 'tool_start', tool: 'bash', command: 'ls', round: 1 }],
          { type: 'tool_output', tool: 'bash', command: 'ls', round: 1, exit_code: 0, output: 'a b' },
          [{ type: 'agent_step', round: 2 }, budget(2, 1)],
          () => seen.push(look()),
          [budget(2, 2), { type: 'tool_start', tool: 'bash', command: 'wc -l a', round: 2 }],
          () => seen.push({ ...look(), last: last() }),
          { type: 'tool_output', tool: 'bash', command: 'wc -l a', round: 2, exit_code: 0, output: '3 a' },
          [{ type: 'agent_step', round: 3 }, budget(3, 2)],
          () => seen.push(look()),
          { delta: 'There are two files.' },
          () => seen.push(look()),
          '[DONE]',
        ]);
        console.log(JSON.stringify({ seen }));
    """)
    s = out["seen"]
    assert s[0] == {"spinner": "Processing...",
                    "meter": "Step 1 of 20 | Tool calls 0 · no limit | Stops after step 20 · No tool-call limit"}, s
    assert s[1] == {"spinner": "Generating response",
                    "meter": "Step 2 of 20 | Tool calls 1 · no limit"}, s
    assert s[2] == {"spinner": None, "meter": None, "last": "agent-thread-node running"}, (
        f"the step's spinner outlived the card that ended its wait: {s}")
    assert s[3] == {"spinner": "Generating response",
                    "meter": "Step 3 of 20 | Tool calls 2 · no limit"}, s
    assert s[4] == {"spinner": None, "meter": None}, "the step's spinner outlived its first words"


def test_a_new_steps_spinner_carries_the_meter_before_its_own_frame_arrives(sandbox):
    """The step's spinner opens with the meter under it, as the chat's does
    (`openRoundSpinner(body, meter)`), so between `agent_step` and the step's
    own budget frame the pane still says where it was rather than nothing."""
    out = _pane(sandbox, """
        const seen = [];
        await run([
          budget(1, 0),
          [budget(1, 1), { type: 'tool_start', tool: 'bash', command: 'ls', round: 1 }],
          { type: 'tool_output', tool: 'bash', command: 'ls', round: 1, exit_code: 0, output: 'a' },
          { type: 'agent_step', round: 2 },
          () => seen.push(look()),
          budget(2, 1),
          () => seen.push(look()),
          '[DONE]',
        ]);
        console.log(JSON.stringify({ seen }));
    """)
    s = out["seen"]
    assert s[0] == {"spinner": "Generating response",
                    "meter": "Step 1 of 20 | Tool calls 1 · no limit | Stops after step 20 · No tool-call limit"}, s
    assert s[1] == {"spinner": "Generating response",
                    "meter": "Step 2 of 20 | Tool calls 1 · no limit"}, s


def test_a_meter_whose_first_frame_comes_during_a_step_hangs_under_that_step(sandbox):
    """A stream with no prep frame (an older server, or a run relayed without
    one) says nothing to the meter until a step is already waiting. The first
    budget frame then has to find the step's spinner to hang under."""
    out = _pane(sandbox, """
        const seen = [];
        await run([
          { type: 'tool_start', tool: 'bash', command: 'ls', round: 1 },
          { type: 'tool_output', tool: 'bash', command: 'ls', round: 1, exit_code: 0, output: 'a' },
          { type: 'agent_step', round: 2 },
          budget(2, 1),
          () => seen.push(look()),
          '[DONE]',
        ]);
        console.log(JSON.stringify({ seen }));
    """)
    assert out["seen"] == [{"spinner": "Generating response",
                            "meter": "Step 2 of 20 | Tool calls 1 · no limit"}], out


def test_a_step_announced_while_the_first_spinner_is_up_keeps_one_spinner(sandbox):
    """The pane's first spinner already carries the meter; a second one under
    it would be two spinners for one wait."""
    out = _pane(sandbox, """
        await run([
          [{ type: 'agent_step', round: 2 }, budget(2, 0)],
          () => console.log(JSON.stringify({ spinners: ai.querySelectorAll('.ai-spinner').length, ...look() })),
          '[DONE]',
        ]);
    """)
    assert out == {"spinners": 1, "spinner": "Processing...",
                   "meter": "Step 2 of 20 | Tool calls 0 · no limit"}, out


def test_a_meter_left_in_place_is_not_taken_by_the_spinner_it_hung_under(sandbox):
    """`placeIn`, on its own: a spinner removes the meter only while it is the
    meter's host (`Spinner.attachDetail`), so a meter left in place must stop
    being hosted, or a late `destroy` takes the pane's last word away."""
    out = _pane(sandbox, """
        const { createAgentMeter } = await import('./agentMeter.js');
        const m = createAgentMeter({ offersContinue: false });
        const box = document.body.appendChild(new Node('div'));
        const s = spinnerModule.create('Generating response', 'right');
        box.appendChild(s.createElement());
        m.update(budget(20, 3));
        m.attachTo(s);
        m.update({ type: 'rounds_exhausted', rounds: 20 });
        const end = document.body.appendChild(new Node('div'));
        m.placeIn(end);
        s.destroy();
        console.log(JSON.stringify({ inEnd: end.querySelectorAll('.agent-meter').length,
                                     words: meterWords(end) }));
    """)
    assert out == {"inEnd": 1, "words": "Step 20 of 20 | Tool calls 3 · no limit | Stopped at the 20-step limit"}, out


def test_near_a_limit_it_warns_and_never_promises_a_continue_it_has_not_got(sandbox):
    """The main chat's meter says *and offers Continue*: its step-limit box has
    the button. A pane has no such box, so here the same words would be a
    promise nothing keeps (`Law 10`)."""
    out = _pane(sandbox, """
        const seen = [];
        await run([
          budget(17, 10, { tool_call_limit: 12 }),
          () => seen.push({ ...look(), title: ai.querySelector('.agent-meter-budget').title }),
          { type: 'tool_start', tool: 'bash', command: 'ls', round: 17 },
          { type: 'tool_output', tool: 'bash', command: 'ls', round: 17, exit_code: 0, output: 'a' },
          [{ type: 'agent_step', round: 20 }, budget(20, 11, { tool_call_limit: 12 })],
          () => seen.push(look()),
          '[DONE]',
        ]);
        console.log(JSON.stringify({ seen }));
    """)
    s = out["seen"]
    assert s[0]["meter"] == ("Step 17 of 20 | Tool calls 10 of 12 | "
                             "Stops after step 20 · 2 tool calls left, then it stops"), s
    assert s[1]["meter"] == ("Step 20 of 20 | Tool calls 11 of 12 | "
                             "Last step — if it needs more, it stops here · "
                             "1 tool call left, then it stops"), s
    assert "Continue" not in s[0]["title"] and "stops after step 20." in s[0]["title"], s[0]


def test_a_stop_at_the_step_limit_stays_in_the_pane_as_its_word_on_why(sandbox):
    """A pane that hit the limit just stopped. The meter now ends on the stop and
    stays at the bottom of the pane's message, after the work, when the stream
    is over."""
    out = _pane(sandbox, """
        await run([
          [{ type: 'agent_step', round: 20 }, budget(20, 7)],
          { type: 'tool_start', tool: 'bash', command: 'make', round: 20 },
          { type: 'tool_output', tool: 'bash', command: 'make', round: 20, exit_code: 0, output: 'ok' },
          { type: 'rounds_exhausted', rounds: 20 },
          '[DONE]',
        ]);
        const kids = ai.querySelector('.body').children;
        console.log(JSON.stringify({ last: kids[kids.length - 1].className, look: look(),
                                     spinners: ai.querySelectorAll('.ai-spinner').length }));
    """)
    assert out["last"] == "agent-meter", out
    assert out["look"]["meter"] == "Step 20 of 20 | Tool calls 7 · no limit | Stopped at the 20-step limit", out
    assert out["spinners"] == 0, out


def test_a_stop_at_the_tool_call_limit_says_that_limit(sandbox):
    out = _pane(sandbox, """
        await run([
          [{ type: 'agent_step', round: 4 }, budget(4, 12, { tool_call_limit: 12 })],
          { type: 'tool_start', tool: 'bash', command: 'ls', round: 4 },
          { type: 'tool_output', tool: 'bash', command: 'ls', round: 4, exit_code: 0, output: 'a' },
          { type: 'budget_exceeded', limit: 12, used: 12 },
          '[DONE]',
        ]);
        console.log(JSON.stringify({ look: look() }));
    """)
    assert out["look"]["meter"].endswith("Stopped at the 12-tool-call limit"), out


def test_a_step_left_waiting_when_the_stream_ends_takes_its_spinner_with_it(sandbox):
    """A step announced and then the end — the verifier's step with nothing to
    say, or a stream cut off — leaves no spinner going in a finished pane."""
    out = _pane(sandbox, """
        await run([
          { type: 'tool_start', tool: 'bash', command: 'ls', round: 1 },
          { type: 'tool_output', tool: 'bash', command: 'ls', round: 1, exit_code: 0, output: 'a' },
          [{ type: 'agent_step', round: 2 }, budget(2, 1)],
          '[DONE]',
        ]);
        console.log(JSON.stringify({ spinners: ai.querySelectorAll('.ai-spinner').length,
                                     meter: look().meter }));
    """)
    assert out == {"spinners": 0, "meter": None}, out
