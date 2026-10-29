# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1654` — the log of a plain task a person denied ends with one line saying so.

**Measured on the tree before this row**, through the agents' own harness
(`src.agents.evals`): Chart Maker's *it-never-installs-a-package* — the person
says no to the `pip install` — ended its run `error` with *Denied by eval at
…: python — it was not done.*, and its step log ended *Waiting for your yes on
python*, *Resumed*. `TaskScheduler._run_plain_prompt` wrote the verdict's line
only for the sweeper's verdicts (a lapse, a restart, a withdrawn card), on the
word that a person's answer was already in the log as *Resumed: …* — which
`B1110` says only for an Allow.

Now the verdict's line is written for a person's no as for the sweeper's, once:
the log's last line is the sentence the run ended with.

Driven (`Law 20`): the real scheduler, agent loop, gate, approval store and the
task's answer route — `test_a_plain_task_waits_for_your_yes.py`'s world — and
the row's own case through the agents' harness.
"""
from __future__ import annotations

import time
from datetime import timedelta

import pytest

from tests.helpers.walker_harness import client_for, runs_of, settle
from tests.test_a_plain_task_waits_for_your_yes import (  # noqa: F401
    ALICE, _answer_url, _park, _plain_task, world,
)


def _said(log, sentence):
    return sum(1 for s in log or () if sentence in str(s.get("detail") or ""))


@pytest.mark.asyncio
async def test_a_plain_task_a_person_denied_ends_its_log_saying_so(world):  # noqa: F811
    w = world
    _plain_task(w)
    run, rec = await _park(w)
    async with client_for(w.app) as client:
        res = await client.post(_answer_url(run), headers=ALICE,
                                json={"approval_id": rec["waiting"]["approval"]["approval_id"],
                                      "decision": "deny"})
    assert res.status_code == 200 and res.json()["outcome"] == "denied"
    await settle(w.s)
    [run] = runs_of(w.factory, "plain")
    sentence = run["error"]
    assert run["status"] == "error" and sentence.startswith("Denied by alice at "), run
    details = [str(s.get("detail") or "") for s in run["steps"]]
    assert "Resumed" in details, "premise: the run went on to hear the answer"
    assert details[-1] == sentence, details[-3:]
    assert _said(run["steps"], sentence) == 1, "said once, not again at *Resumed*"


@pytest.mark.asyncio
async def test_a_lapse_is_still_said_once_and_last(world, monkeypatch):  # noqa: F811
    """The sweeper's verdict, which already had its line: unchanged."""
    import src.task_scheduler as ts
    import src.tool_approvals as ta

    w = world
    _plain_task(w)
    await _park(w)
    later = time.time() + 13 * 60 * 60
    monkeypatch.setattr(ta.time, "time", lambda: later)
    real_now = ts._utcnow
    monkeypatch.setattr(ts, "_utcnow", lambda: real_now() + timedelta(hours=13))
    assert await w.s._resume_due_waits() == 1
    await settle(w.s)
    [run] = runs_of(w.factory, "plain")
    assert run["error"].startswith("Nobody answered by ")
    assert str(run["steps"][-1].get("detail")) == run["error"]
    assert _said(run["steps"], run["error"]) == 1


def test_chart_makers_denied_install_ends_its_log_saying_so():
    """The row's case: the steps ended *Waiting for your yes on python*,
    *Resumed*, while the result said it was denied."""
    from test_a_step_allowed_from_a_card_is_one_step import _case, _run

    r, steps = _run("chart-maker", _case("chart-maker", "it-never-installs-a-package"))
    assert r.status == "error" and r.passed, r.checks
    details = [str(s.get("detail") or "") for s in steps]
    assert details[-3:-1] == ["Waiting for your yes on python", "Resumed"], details[-3:]
    assert details[-1].startswith("Denied by ") and details[-1].endswith(
        ": python — it was not done."), details[-1]
