# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B905` — Message Stats' *Model wait* is measured once, on the clock it names.

`_compute_final_metrics` wrote `agent_model_wait_time = max(time_to_first_token
- prep_total, 0)`. But the loop starts `total_start`, the clock
`time_to_first_token` is read on, *after* the four preparation steps, so
preparation was taken off a figure that never contained it: 0.81s of prep and a
0.5s wait printed *Model wait 0s*, clamped from −0.31. A turn with no token at
all printed a measured-looking `0`. And `time_to_first_token` is the first
*token* of the turn — on a turn that goes straight to a tool that is a step
later, with the tool's own run inside it.

Now the loop measures the wait where it happens: from the end of preparation to
the model's first token (thinking included) or first tool call. The popup says
which clock each of *Prep*, *Model wait* and *Time* is on, because Prep and Time
are two windows side by side and it laid them out as one inside the other.

Driven, not read (`Law 20`): the loop under a clock this test moves, and the
popup under node.
"""

import asyncio
import json
import shutil
import time

import pytest

import src.agent_loop as agent_loop
from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402
from test_message_stats_surface_js import (  # noqa: E402
    CHAT_RENDERER, _PREAMBLE as _STATS_PREAMBLE, _STATS_SHIM, _STUBS as _STATS_STUBS, _rows,
)

HOUR = 3600.0


def _clock(monkeypatch):
    """The wall clock the loop reads, plus jumps this test makes. Real time keeps
    flowing, so nothing that waits can hang; an hour is far past anything a
    loaded machine adds, so the assertions are about which window holds which
    jump and cannot be turned by a slow box."""
    offset = [0.0]
    real = time.time
    monkeypatch.setattr(time, "time", lambda: real() + offset[0])

    def jump(hours):
        offset[0] += hours * HOUR
    return jump


def _loop_metrics(monkeypatch, rounds, *, tool_hours=0.0, prep_hours=1.0):
    """Run the loop against a scripted model. `rounds` is one list of frames per
    model call, each preceded by the hours that call makes the loop wait for its
    first frame; a number among the frames is a pause of that many hours before
    the next one. Preparation is made to take `prep_hours`, and a tool call
    `tool_hours`. Returns the final metrics."""
    jump = _clock(monkeypatch)
    # A per-step timeout long enough that the hours this test moves the clock
    # by are not taken for a stream that never ends (the round deadline is four
    # times it).
    monkeypatch.setattr(agent_loop, "get_setting",
                        lambda key, default=None: 86_400 if key == "agent_stream_timeout_seconds"
                        else default, raising=False)
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: None, raising=False)
    monkeypatch.setattr(agent_loop, "estimate_tokens", lambda *a, **k: 10, raising=False)
    monkeypatch.setattr(agent_loop, "blocked_tools_for_owner", lambda owner: set(),
                        raising=False)
    # Native tool calls, so a tool-first turn sends no token at all in step 1.
    monkeypatch.setattr(agent_loop, "_agent_route_tool_mode",
                        lambda *args, **kwargs: (True, False, False))
    real_prompt = agent_loop._build_system_prompt

    def slow_prompt(*args, **kwargs):
        jump(prep_hours)
        return real_prompt(*args, **kwargs)

    monkeypatch.setattr(agent_loop, "_build_system_prompt", slow_prompt)
    calls = iter(rounds)

    async def scripted(*args, **kwargs):
        wait, frames = next(calls)
        jump(wait)
        for frame in frames:
            if isinstance(frame, (int, float)):   # a pause inside the reply
                jump(frame)
                continue
            yield f"data: {json.dumps(frame)}\n\n"
        yield "data: [DONE]\n\n"

    async def slow_tool(block, *args, **kwargs):
        jump(tool_hours)
        return (block.tool_type, {"output": "ok", "exit_code": 0})

    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", scripted, raising=False)
    monkeypatch.setattr(agent_loop, "execute_tool_block", slow_tool, raising=False)

    async def _go():
        return [c async for c in agent_loop.stream_agent_loop(
            "http://x/v1", "m", [{"role": "user", "content": "check the disk usage"}],
            max_rounds=3, relevant_tools={"bash"}, _is_teacher_run=True)]

    metrics = None
    for chunk in asyncio.run(_go()):
        if chunk.startswith("data: {"):
            frame = json.loads(chunk[6:])
            if frame.get("type") == "metrics":
                metrics = frame["data"]
    assert metrics is not None, "the loop sent no metrics"
    return metrics


TOOL_CALL = {"type": "tool_calls", "calls": [
    {"name": "bash", "arguments": json.dumps({"command": "df -h"})}]}


def test_a_known_prep_and_a_known_wait_are_both_reported(monkeypatch):
    """The row's `Verify:`. One hour of preparation, then two before the first
    token: *Prep* is the hour, *Model wait* the two. The old subtraction said
    one — the prep hour taken off a wait that never contained it."""
    m = _loop_metrics(monkeypatch, [(2, [{"delta": "Your disk is 40% full."}])])
    assert HOUR <= m["agent_prep_time"] < 1.5 * HOUR, m["agent_prep_time"]
    assert 2 * HOUR <= m["agent_model_wait_time"] < 2.5 * HOUR, m["agent_model_wait_time"]


def test_a_turn_that_starts_with_a_tool_call_reports_the_wait_for_that_call(monkeypatch):
    """No token in step 1, so the first token of the turn is step 2's — four
    hours of tool and three more of waiting later. The model's wait is the two
    hours before it sent the call."""
    m = _loop_metrics(monkeypatch, [(2, [TOOL_CALL]), (3, [{"delta": "40% full."}])],
                      tool_hours=4)
    assert 2 * HOUR <= m["agent_model_wait_time"] < 2.5 * HOUR, (
        f"{m['agent_model_wait_time'] / HOUR:.2f}h — the tool's run is inside it")


def test_a_thinking_token_ends_the_wait_too(monkeypatch):
    """Reasoning is the model answering. It is the first thing a person sees."""
    m = _loop_metrics(monkeypatch, [(2, [{"delta": "Let me think.", "thinking": True},
                                         1, {"delta": "40% full."}])])
    assert 2 * HOUR <= m["agent_model_wait_time"] < 2.5 * HOUR


def test_nothing_back_from_the_model_is_no_figure_rather_than_zero(monkeypatch):
    """`Law 10`. It printed `0s` — a measurement of an instant reply. A usage
    report is the provider talking, not the model answering, so an empty reply
    with one is still no figure."""
    m = _loop_metrics(monkeypatch, [(2, [{"type": "usage",
                                          "data": {"input_tokens": 5, "output_tokens": 0}}])])
    assert "agent_prep_time" in m
    assert "agent_model_wait_time" not in m, m.get("agent_model_wait_time")


def test_the_final_metrics_take_the_measured_wait_and_nothing_else():
    """`_compute_final_metrics` reports the wait it is handed and does not
    derive one from `time_to_first_token`."""
    base = dict(messages=[{"role": "user", "content": "hi"}], full_response="hello",
                total_duration=5.0, time_to_first_token=1.25, context_length=8192,
                real_input_tokens=10, real_output_tokens=5, has_real_usage=True,
                tool_events=[], round_texts=[], model="m",
                prep_timings={"request_setup": 0.2, "tool_selection": 0.3, "prompt_build": 0.15})
    assert agent_loop._compute_final_metrics(**base, model_wait_time=0.5)["agent_model_wait_time"] == 0.5
    assert "agent_model_wait_time" not in agent_loop._compute_final_metrics(**base)
    assert "agent_model_wait_time" not in agent_loop._compute_final_metrics(
        **base, model_wait_time=True)


# ── the popup ───────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def stats_sandbox(tmp_path_factory):
    if not shutil.which("node"):
        pytest.skip("node binary not on PATH")
    return _make_sandbox(tmp_path_factory.mktemp("modelwait"), CHAT_RENDERER,
                         _STATS_SHIM, _STATS_STUBS)


def _popup(sandbox, metrics, *, raw=False):
    out = _run(sandbox, _STATS_PREAMBLE, """
        console.log(JSON.stringify(open(displayMetrics, %s)));
    """ % json.dumps(metrics))
    return out["popup"]["rowsHtml"] if raw else _rows(out["popup"])


AGENT = {"response_time": 7.4, "input_tokens": 900, "output_tokens": 300,
         "tokens_per_second": 60.0, "usage_source": "real", "model": "org/m",
         "agent_prep_time": 0.81, "agent_model_wait_time": 0.5}


def _timing(parsed):
    """The Prep / Model wait / Time rows and the line under each, in order."""
    rows = parsed.rows
    out = []
    for i, r in enumerate(rows):
        if r.split(" ")[0] in ("Prep", "Time") or r.startswith("Model wait"):
            under = rows[i + 1] if i + 1 < len(rows) and rows[i + 1] in parsed.tagged.get("ctx-sub", []) else ""
            out.append((r, under))
    return out


def test_the_popup_says_which_clock_each_figure_is_on(stats_sandbox):
    """Prep, then the wait, then the rest of the reply: three windows in the
    order they happen, each with the line saying where it starts and stops."""
    shown = _timing(_popup(stats_sandbox, AGENT))
    assert [r for r, _ in shown] == ["Prep 0.81s", "Model wait 0.5s", "Time 7.4s"], shown
    under = dict(shown)
    assert "before the model was asked" in under["Prep 0.81s"]
    assert "end of prep" in under["Model wait 0.5s"] and "first token" in under["Model wait 0.5s"]
    assert "end of prep" in under["Time 7.4s"] and "end of the reply" in under["Time 7.4s"]


def test_an_unmeasured_wait_is_not_printed_as_zero(stats_sandbox):
    metrics = dict(AGENT)
    del metrics["agent_model_wait_time"]
    shown = _timing(_popup(stats_sandbox, metrics))
    assert [r for r, _ in shown] == ["Prep 0.81s", "Time 7.4s"], shown


def test_a_chat_turn_keeps_its_one_time_row(stats_sandbox):
    """No prep, so no second clock to tell apart — the row it always had."""
    metrics = {k: v for k, v in AGENT.items() if not k.startswith("agent_")}
    shown = _timing(_popup(stats_sandbox, metrics))
    assert shown == [("Time 7.4s", "")], shown


def test_a_stored_figure_that_is_not_a_number_draws_nothing(stats_sandbox):
    """These are read out of stored metadata into an `innerHTML` template, so
    the raw markup is what is checked."""
    hostile = dict(AGENT, agent_model_wait_time="<img src=x onerror=1>")
    assert "<img" not in _popup(stats_sandbox, hostile, raw=True)
    shown = _timing(_popup(stats_sandbox, hostile))
    assert [r for r, _ in shown] == ["Prep 0.81s", "Time 7.4s"], shown
