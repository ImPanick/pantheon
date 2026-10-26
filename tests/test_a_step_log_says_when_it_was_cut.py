# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B612` — a run whose step log, or a tool's output in it, hit a cap says so,
in the step log, where the person is reading it.

**Measured before this file:** `_record_run_step` cut a step's `detail` and
`output` at 400 characters and appended "…"; `_close_run_step` cut the same
tool output at the same 400 and appended nothing — and closing a step that a
`tool_start` opened is the common path, so a tool's clipped output usually
read as complete. And past `_MAX_RUN_STEPS` (200) `_record_run_step` returned
`None` with nothing recorded: a run of 205 tool calls kept a log of exactly 200
steps, and Activity's summary said "200 steps" as though that were all.

Driven (`Law 20`): the real `TaskScheduler._run_agent_loop` reading the agent
loop's own event stream (the loop itself scripted, since a model is not what
is under test), the log it records, and the real `static/js/tasks.js`
`_renderRunSteps` drawing that log under node.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.task_scheduler import TaskScheduler  # noqa: E402
from test_show_me_what_this_would_do_js import _case, _steps_of, sandbox  # noqa: E402,F401

LONG = "line of tool output " * 60      # 1,200 characters


def _event(**data) -> str:
    return f"data: {json.dumps(data)}\n\n"


@pytest.fixture()
def loop(monkeypatch):
    """`stream_agent_loop`, scripted: each call yields the events it is given."""
    import src.agent_loop as agent_loop
    monkeypatch.setenv("BACKGROUND_TASK_FOREGROUND_GATE", "0")
    script = {"events": []}

    async def stream(**kwargs):
        for e in script["events"]:
            yield e
        yield _event(delta="Done.")
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(agent_loop, "stream_agent_loop", stream)
    return script


async def _run(events, loop):
    loop["events"] = events
    s = TaskScheduler(None)
    task = SimpleNamespace(id="t1", name="Chatty", prompt="Go.", owner="alice", max_steps=None)
    await s._run_agent_loop("http://127.0.0.1:9/v1", "m", task, None, run_id="r1")
    return s.run_steps("r1")


@pytest.mark.asyncio
async def test_a_tool_output_cut_on_the_common_path_ends_with_an_ellipsis(loop):
    """`tool_start` then `tool_output` — the step is opened, then closed with
    its output: the path `_close_run_step` takes, which appended nothing."""
    steps = await _run([
        _event(type="tool_start", tool="read_file", round=1, command="big.log"),
        _event(type="tool_output", tool="read_file", round=1, status="ok", output=LONG),
        # A `tool_output` with no open step records a new one: the other path,
        # which always said so.
        _event(type="tool_output", tool="web_fetch", round=2, status="ok", output=LONG),
    ], loop)
    closed, recorded = steps
    assert closed["tool"] == "read_file" and closed["status"] == "ok"
    assert recorded["tool"] == "web_fetch"
    for step in (closed, recorded):
        assert step["output"].endswith("…"), step["output"][-20:]
        assert len(step["output"]) <= TaskScheduler._MAX_STEP_DETAIL + 1
    assert closed["output"] == recorded["output"], "one fact, one clip"
    # A short output is kept whole, with no mark.
    steps = await _run([
        _event(type="tool_start", tool="read_file", round=1, command="a"),
        _event(type="tool_output", tool="read_file", round=1, status="ok", output="short"),
    ], loop)
    assert steps[0]["output"] == "short"


def _calls(n):
    out = []
    for i in range(n):
        out.append(_event(type="tool_start", tool="run_shell", round=i + 1, command=f"step {i}"))
        out.append(_event(type="tool_output", tool="run_shell", round=i + 1, status="ok",
                          output=f"ok {i}"))
    return out


@pytest.mark.asyncio
async def test_a_log_past_the_cap_ends_with_one_line_counting_what_it_left_out(loop):
    cap = TaskScheduler._MAX_RUN_STEPS
    steps = await _run(_calls(cap + 5), loop)
    assert len(steps) == cap + 1
    assert [s["kind"] for s in steps[:cap]] == ["tool"] * cap
    assert steps[cap - 1]["detail"] == f"step {cap - 1}", "the first 200 are the ones kept"
    note = steps[-1]
    assert note["kind"] == "capped" and note["dropped"] == 5, "the wire value tasks.js reads"
    assert note["detail"] == (f"The step log stops here: it keeps {cap} steps, "
                              f"and 5 more steps were not recorded.")
    # Exactly at the cap nothing was left out, and nothing says otherwise.
    steps = await _run(_calls(cap), loop)
    assert len(steps) == cap and all(s["kind"] == "tool" for s in steps)
    steps = await _run(_calls(cap + 1), loop)
    assert steps[-1]["detail"].endswith("and 1 more step was not recorded.")


@pytest.mark.asyncio
async def test_the_activity_view_says_it_too(loop, sandbox):
    """Where the person reads it: the summary counts the steps kept and says
    how many more there were, and the log's last line says why it stops."""
    cap = TaskScheduler._MAX_RUN_STEPS
    steps = await _run(_calls(cap + 5), loop)
    out = _case(sandbox, {}, """
        console.log(JSON.stringify({ html: __t._renderRunSteps({ steps: %s }) }));
    """ % json.dumps(steps))
    html = out["html"]
    assert f"<summary>{cap} steps · 5 more not recorded</summary>" in html, html[-400:]
    rows = _steps_of(html)
    assert len(rows) == cap + 1
    assert rows[-1]["kind"] == "log full"
    assert rows[-1]["detail"].startswith("The step log stops here")
    # A log that was never cut reads as it always did (`Law 1`).
    plain = _case(sandbox, {}, """
        console.log(JSON.stringify({ html: __t._renderRunSteps({ steps: %s }) }));
    """ % json.dumps(steps[:3]))
    assert "<summary>3 steps</summary>" in plain["html"]
