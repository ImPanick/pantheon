# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P24-09` — the contract checker's optional judge model.

`delivers` is checked by code first (`tests/test_an_agent_delivers_or_says_why.py`).
This file is the second half: when an admin turns on *A model reads each
delivery too* (`agents_judge`), and the code's checks pass, a model reads the
delivery against what the agent's file promises. Its verdict and reasons sit in
the run's report beside the code's checks; a `not_delivered` feeds the same
single repair pass; a reading it could not give does not fail a run that
passed its checks, and the report says only they counted.

Driven through the real `TaskScheduler._execute_llm_task` on a real SQLite file
with hires from the shipped manifests (the harness of
`test_a_hired_agent_runs_as_its_file_says.py`, imported — `Law 14`). The two
stand-ins are the agent loop and `task_llm_call_async`, the person's own
background-task chain — so what is asserted is what the judge is handed and
which endpoint it is asked through (`Law 16`: the run's own, as the chain's
fallback, never a new one).

**Measured before this file, on `a16e7d75`:** no judge anywhere in
`src/agents/runtime.py`; a run that passed its code checks was `success` with
nothing else read.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap

import pytest

from tests.test_a_hired_agent_runs_as_its_file_says import _hire, _run, _task, world  # noqa: F401
from tests.test_a_workflow_is_kept_as_one_document import wf_db  # noqa: F401  (fixture)
from tests.test_an_agent_delivers_or_says_why import _loop_answers, _report, _settings
from core.database import AgentHire
from src.agents import runtime as R

# `P24-27`: Morning Brief promises four headings now, so its fixtures say all four.
GOOD = "Today: two meetings and a dentist. Mail that needs you: nothing. Due: nothing. Overnight: nothing.\n\n## Report\n- read the calendar"


@pytest.fixture()
def judge(monkeypatch):
    """The person's background-task chain, scripted: answers each reply in turn
    and keeps what it was asked and through which endpoint."""
    import src.task_endpoint as TE
    state = {"replies": [], "asked": []}

    async def call(messages, *, fallback_url=None, fallback_model=None, owner=None, **kw):
        state["asked"].append({"messages": messages, "fallback_url": fallback_url,
                               "fallback_model": fallback_model, "owner": owner})
        reply = state["replies"].pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(TE, "task_llm_call_async", call)
    return state


def _verdict(verdict, *reasons):
    return json.dumps({"verdict": verdict, "reasons": list(reasons)})


def test_off_as_shipped_nothing_is_asked_and_the_checks_are_the_codes(world, judge):
    factory, sched, seen = world
    db = factory()
    h, _ = _hire(db, "morning-brief", inputs={"at": "06:00"})
    _loop_answers(sched, seen, GOOD)
    run_id, _ = _run(sched, db, _task(db, h.id))
    assert judge["asked"] == [], "no model was asked to judge"
    assert [c["check"] for c in _report(db, run_id)["checks"]] == ["the answer"]


def test_on_its_verdict_and_reasons_sit_beside_the_code_checks(world, judge, monkeypatch):
    factory, sched, seen = world
    db = factory()
    _settings(monkeypatch, agents_judge=True)
    h, _ = _hire(db, "morning-brief", inputs={"at": "06:00"})
    _loop_answers(sched, seen, GOOD)
    judge["replies"].append("<think>hm</think>" + _verdict("delivered", "It lists today's meetings."))
    run_id, _ = _run(sched, db, _task(db, h.id))

    asked = judge["asked"][0]
    # The run's own endpoint (as the scheduler resolved it) is the chain's
    # fallback; the chain itself is the person's configured models.
    assert asked["fallback_url"].startswith("http://endpoint"), asked["fallback_url"]
    assert (asked["fallback_model"], asked["owner"]) == ("m-1", "alice")
    system, answer_msg = asked["messages"][0]["content"], asked["messages"][1]
    assert "Morning Brief" in system and "- An answer, which says: Today" in system
    assert "- It answered, with Today, Mail that needs you, Due, Overnight." in system, "it is told what the code found"
    assert "two meetings and a dentist" in answer_msg["content"]
    assert answer_msg["role"] != "system" and answer_msg["metadata"]["trusted"] is False, \
        "the answer is handed in as data, never as instructions"

    checks = _report(db, run_id)["checks"]
    assert checks[0]["check"] == "the answer" and checks[0]["ok"] is True
    assert checks[1] == {"check": R.JUDGE_CHECK, "ok": True, "verdict": "delivered",
                         "reasons": ["It lists today's meetings."],
                         "detail": "The judge model read it and agrees it delivers: "
                                   "It lists today's meetings."}


def test_a_no_gets_the_one_more_try_told_the_judges_reasons(world, judge, monkeypatch):
    factory, sched, seen = world
    db = factory()
    _settings(monkeypatch, agents_judge=True)
    h, _ = _hire(db, "morning-brief", inputs={"at": "06:00"})
    calls = _loop_answers(sched, seen, "Today: see your calendar. Mail that needs you: nothing. Due: nothing. Overnight: nothing.", GOOD)
    judge["replies"] += [_verdict("not_delivered", "It names no meeting"),
                         _verdict("delivered", "Now it lists them.")]
    run_id, answer = _run(sched, db, _task(db, h.id))
    assert len(calls) == 2
    assert ("- The judge model read it and says it does not deliver: It names no meeting."
            in calls[1]["override_user_message"])
    assert answer == GOOD
    report = _report(db, run_id)
    assert report["repaired"] is True
    assert [c["verdict"] for c in report["checks"] if c["check"] == R.JUDGE_CHECK] == ["delivered"]
    db.expire_all()
    assert db.query(AgentHire).get(h.id).status == "on"


def test_two_noes_fail_the_run_and_park_the_hire_with_the_judges_sentence(world, judge, monkeypatch):
    factory, sched, seen = world
    db = factory()
    _settings(monkeypatch, agents_judge=True)
    h, _ = _hire(db, "morning-brief", inputs={"at": "06:00"})
    _loop_answers(sched, seen, "Today: see your calendar. Mail that needs you: nothing. Due: nothing. Overnight: nothing.", "Today: still see it. Mail that needs you: nothing. Due: nothing. Overnight: nothing.")
    judge["replies"] += [_verdict("not_delivered", "It names no meeting")] * 2
    with pytest.raises(R.AgentDidNotDeliver) as caught:
        _run(sched, db, _task(db, h.id))
    assert "says it does not deliver: It names no meeting." in str(caught.value)
    db.expire_all()
    hire = db.query(AgentHire).get(h.id)
    assert hire.status == "attention" and hire.attention == str(caught.value)


def test_the_judge_is_asked_only_once_the_codes_checks_pass(world, judge, monkeypatch):
    factory, sched, seen = world
    db = factory()
    _settings(monkeypatch, agents_judge=True)
    h, _ = _hire(db, "morning-brief", inputs={"at": "06:00"})
    _loop_answers(sched, seen, "Two meetings.", GOOD)          # the first misses "Today"
    judge["replies"].append(_verdict("delivered", "Fine."))
    _run(sched, db, _task(db, h.id))
    assert len(judge["asked"]) == 1, "the first answer failed the code; no model was asked about it"


@pytest.mark.parametrize("reply", ["Looks good to me!", '{"verdict": "yes"}', RuntimeError("no endpoint")])
def test_a_reading_it_cannot_give_does_not_fail_a_run_and_says_so(world, judge, monkeypatch, reply):
    factory, sched, seen = world
    db = factory()
    _settings(monkeypatch, agents_judge=True)
    h, _ = _hire(db, "morning-brief", inputs={"at": "06:00"})
    calls = _loop_answers(sched, seen, GOOD)
    judge["replies"].append(reply)
    run_id, _ = _run(sched, db, _task(db, h.id))
    assert len(calls) == 1, "no repair: the code's checks passed"
    last = _report(db, run_id)["checks"][-1]
    assert last["verdict"] == "unread" and last["ok"] is True
    assert last["detail"].endswith("so only the checks above count.")


@pytest.mark.parametrize("stored", ["true", 1, "yes"])
def test_only_a_stored_true_turns_the_judge_on(world, monkeypatch, stored):
    _settings(monkeypatch, agents_judge=stored)
    assert R.judge_enabled() is False


# ── the settings door ───────────────────────────────────────────────────────

from tests.test_the_workstation_is_admin_controlled import (  # noqa: E402,F401  (fixtures)
    ADMIN, PLAIN, app, as_user, auth, datadir, stored,
)


def test_an_admin_turns_the_judge_on_and_a_non_bool_is_refused(app):
    admin = as_user(app, ADMIN)
    assert stored("agents_judge") is False, "off as shipped"
    r = admin.post("/api/auth/settings", json={"agents_judge": "on"})
    assert r.status_code == 400 and r.json()["detail"] == "agents_judge must be true or false"
    assert admin.post("/api/auth/settings", json={"agents_judge": True}).status_code == 200
    assert stored("agents_judge") is True
    assert as_user(app, PLAIN).post("/api/auth/settings", json={"agents_judge": False}).status_code == 403
    assert stored("agents_judge") is True


# ── the panel, under node ───────────────────────────────────────────────────

@pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")
def test_the_switch_draws_what_is_stored_and_saves_its_one_key(tmp_path):
    from tests.test_the_agents_settings_panel_js import IDS, ROOT, _PREAMBLE, _SHIM
    ids = IDS + ["agents-judgeToggle"]
    (tmp_path / "shim.js").write_text(_SHIM.replace("%IDS%", json.dumps(ids)))
    (tmp_path / "appConfig.js").write_text(
        "import { server } from './shim.js';\nexport function invalidateSettings() { server.invalidated += 1; }\n")
    shutil.copy(ROOT / "static" / "js" / "agentsSettings.js", tmp_path / "agentsSettings.js")
    (tmp_path / "case.mjs").write_text(_PREAMBLE + textwrap.dedent("""
        server.stored.agents_judge = true;
        await mod.open();
        const drawn = els['agents-judgeToggle'].checked;
        els['agents-judgeToggle'].checked = false; els['agents-judgeToggle'].fire('change'); await settle();
        out({ drawn, posts: server.posts, stored: server.stored.agents_judge,
              said: els['agents-settingsResult'].textContent });
    """))
    proc = subprocess.run(["node", "case.mjs"], cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out == {"drawn": True, "posts": [{"agents_judge": False}], "stored": False,
                   "said": "From the next run, deliveries are checked by code only."}
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    panel = html[html.index('<div data-settings-panel="agents"'):html.index('<div data-settings-panel="workstation"')]
    assert 'id="agents-judgeToggle"' in panel
