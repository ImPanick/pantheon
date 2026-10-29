# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P24-09` / `P24-10` / `P24-13` / `P24-15` — a hired agent delivers what its
file promises or says why; the install's brakes hold; a trial runs only when
asked.

Driven through the real `TaskScheduler._execute_llm_task` on a real SQLite
file, with hires made from the real shipped manifests (the harness is
`test_a_hired_agent_runs_as_its_file_says.py`'s, imported — `Law 14`). The
agent loop is the one stand-in, at `_run_agent_loop`: what is asserted is what
it is handed on the repair pass and what the run then keeps. The brakes are
the real settings, saved through the real `POST /api/auth/settings`.

**Measured before this file, on `6f51844`:** a run whose answer had none of
the words its manifest promised was recorded `success` with nothing said;
there was no `agents_paused`, no limit on agent runs at once, and no trial.
"""

from __future__ import annotations

import json
import uuid

import pytest

from tests.test_a_hired_agent_runs_as_its_file_says import _hire, _run, _task, world  # noqa: F401
from tests.test_a_workflow_is_kept_as_one_document import wf_db  # noqa: F401  (fixture)
from core.database import AgentHire, AgentRunReport, Document, ScheduledTask, TaskRun
from src.agents import hires as H
from src.agents import runtime as R
from src.builtin_actions import TaskDeferred, TaskNoop


def _settings(monkeypatch, **values):
    import src.settings as S
    real = S.get_setting
    monkeypatch.setattr(S, "get_setting", lambda key, default=None: values[key] if key in values
                        else real(key, default))


def _loop_answers(sched, seen, *answers):
    """The loop answers each of `answers` in turn and records what it was handed."""
    queue = list(answers)
    calls = []

    async def loop(endpoint_url, model, task, session_id, **kw):
        calls.append(kw)
        seen.update(kw)
        return queue.pop(0)

    sched._run_agent_loop = loop
    return calls


def _report(db, run_id):
    db.expire_all()
    return json.loads(db.query(AgentRunReport).get(run_id).report)


# `P24-27`: Morning Brief's file promises four headings now (Today, Mail that
# needs you, Due, Overnight), so its fixtures say all four.

# ── `P24-09` · the contract ─────────────────────────────────────────────────

def test_an_answer_with_its_promised_words_is_checked_and_kept(world):
    factory, sched, seen = world
    db = factory()
    h, _ = _hire(db, "morning-brief", inputs={"at": "06:00"})
    calls = _loop_answers(sched, seen, "Today: two meetings. Mail that needs you: nothing. Due: nothing. Overnight: nothing.\n\n## Report\n- read the calendar")
    run_id, answer = _run(sched, db, _task(db, h.id))
    assert len(calls) == 1, "nothing was missing, so there is no second pass"
    report = _report(db, run_id)
    assert report["checks"] == [{"check": "the answer", "ok": True, "detail": "It answered, with Today, Mail that needs you, Due, Overnight."}]
    assert report["repaired"] is False


def test_a_missing_word_gets_one_more_try_that_is_told_what_is_missing(world):
    factory, sched, seen = world
    db = factory()
    h, _ = _hire(db, "morning-brief", inputs={"at": "06:00"})
    calls = _loop_answers(sched, seen, "Two meetings.", "Today: two meetings. Mail that needs you: nothing. Due: nothing. Overnight: nothing.\n\n## Report\n- fixed")
    run_id, answer = _run(sched, db, _task(db, h.id))
    assert len(calls) == 2
    repair = calls[1]
    assert repair["override_user_message"].startswith("Your run is not finished")
    assert "- The answer does not say: Today, Mail that needs you, Due, Overnight." in repair["override_user_message"]
    so_far = repair["context_msgs"][-1]
    assert "Two meetings." in so_far["content"]
    assert so_far["metadata"]["tool_gate_untrusted"] is False, "its own words are data, not a taint"
    assert answer.startswith("Today:")
    report = _report(db, run_id)
    assert report["repaired"] is True and report["checks"][0]["ok"] is True
    db.expire_all()
    assert db.query(AgentHire).get(h.id).status == "on"


def test_a_run_that_still_does_not_deliver_fails_and_parks_the_hire_saying_what_is_missing(world):
    factory, sched, seen = world
    db = factory()
    h, _ = _hire(db, "morning-brief", inputs={"at": "06:00"})
    calls = _loop_answers(sched, seen, "Two meetings.", "Still two meetings.")
    with pytest.raises(R.AgentDidNotDeliver) as caught:
        _run(sched, db, _task(db, h.id))
    assert len(calls) == 1 + R.REPAIR_PASSES
    sentence = str(caught.value)
    assert "The answer does not say: Today, Mail that needs you, Due, Overnight." in sentence
    db.expire_all()
    hire = db.query(AgentHire).get(h.id)
    assert hire.status == "attention" and hire.attention == sentence
    assert _task(db, h.id).status == "paused"
    report = json.loads(db.query(AgentRunReport).one().report)
    assert report["checks"][0]["ok"] is False, "the report is kept even when the run fails"


def _plan(db, h):
    return R.plan_for_task(db, _task(db, h.id))


def test_a_document_is_found_by_its_title_and_read_for_its_sections(world):
    factory, sched, seen = world
    db = factory()
    h, _ = _hire(db, "inbox-triage")
    plan = _plan(db, h)
    doc_check = lambda: R.check_contract(db, plan, "done", [])[0]  # noqa: E731
    assert doc_check() == {"check": "a document titled “Inbox triage”", "ok": False,
                           "detail": "No document titled “Inbox triage” was written in this run."}
    d = Document(id=str(uuid.uuid4()), owner="alice", title="Inbox triage — Tuesday",
                 current_content="## Urgent\n- x\n## FYI\n- y")
    db.add(d)
    db.commit()
    assert doc_check()["detail"] == "“Inbox triage — Tuesday” has no Needs a reply."
    d.current_content += "\n## Needs a reply\n- z"
    db.commit()
    assert doc_check()["ok"] is True
    d.owner = "bob"
    db.commit()
    assert doc_check()["ok"] is False, "another person's document is not this hire's delivery"


def test_drafts_are_counted_against_their_limit(world):
    factory, sched, seen = world
    db = factory()
    h, _ = _hire(db, "inbox-triage")
    plan = _plan(db, h)
    steps = [{"kind": "tool", "tool": "draft_email", "status": "ok"} for _ in range(11)]
    steps.append({"kind": "tool", "tool": "draft_email", "status": "blocked"})
    draft = [c for c in R.check_contract(db, plan, "x", steps) if "drafts" in c["check"]][0]
    assert draft == {"check": "at most 10 drafts", "ok": False, "detail": "It made 11 drafts; its limit is 10."}
    mcp = [{"kind": "tool", "tool": "mcp__email__draft_email_reply", "status": "ok"} for _ in range(11)]
    draft = [c for c in R.check_contract(db, plan, "x", mcp) if "drafts" in c["check"]][0]
    assert draft["ok"] is False, "`B1433`: the loop's own spelling of a draft counts too"
    assert R.build_report("x", mcp[:1])["wrote"] == ["draft_email_reply"]
    draft = [c for c in R.check_contract(db, plan, "x", steps[:10]) if "drafts" in c["check"]][0]
    assert draft["ok"] is True and draft["detail"] == "It made 10 drafts.", "the limit itself is allowed"


def test_a_file_must_be_inside_the_projects_folder(world, monkeypatch, tmp_path):
    factory, sched, seen = world
    db = factory()
    h, _ = _hire(db, "morning-brief")
    plan = _plan(db, h)
    import src.tool_execution as te
    root = tmp_path / "projects"
    (root / "site").mkdir(parents=True)
    (root / "site" / "index.html").write_text("<h1>Hello</h1>")
    (tmp_path / "secret.txt").write_text("x")
    monkeypatch.setattr(te, "projects_root", lambda owner, create=False: str(root))
    from dataclasses import replace
    for rel, words, ok in [("site/index.html", ["Hello"], True), ("site/index.html", ["Bye"], False),
                           ("../secret.txt", [], False), ("site/none.html", [], False)]:
        p = replace(plan, delivers=({"kind": "file", "title": rel, "must_contain": words},))
        assert R.check_contract(db, p, "", [])[0]["ok"] is ok, rel


def test_a_plan_that_promises_nothing_has_nothing_checked(world):
    factory, sched, seen = world
    db = factory()
    h, _ = _hire(db, "notes-gardener")
    from dataclasses import replace
    assert R.check_contract(db, replace(_plan(db, h), delivers=()), "", []) == []


# ── `P24-10` / `P24-15` · the brakes ────────────────────────────────────────

def test_pause_all_skips_every_agent_run_with_its_sentence_and_parks_nobody(world, monkeypatch):
    factory, sched, seen = world
    db = factory()
    h, _ = _hire(db, "morning-brief")
    _settings(monkeypatch, agents_paused=True)
    with pytest.raises(R.AgentRunRefused) as caught:
        _run(sched, db, _task(db, h.id))
    assert isinstance(caught.value, TaskNoop), "the engine records it `skipped` with the sentence"
    assert str(caught.value) == R.ALL_PAUSED
    assert "system_prompt" not in seen, "nothing was asked of the model"
    db.expire_all()
    assert db.query(AgentHire).get(h.id).status == "on", "the hire is not this run's to change"
    plain = ScheduledTask(id="plain", owner="alice", name="Plain", prompt="hi", task_type="llm")
    db.add(plain)
    db.commit()
    _run(sched, db, plain)
    assert "system_prompt" in seen, "pause-all is for agents; a plain task runs"


@pytest.mark.parametrize("stored", ["true", 1, "yes"])
def test_only_a_stored_true_pauses(world, monkeypatch, stored):
    _settings(monkeypatch, agents_paused=stored)
    assert R.agents_paused() is False


def test_past_the_limit_a_run_waits_and_is_not_lost(world, monkeypatch):
    factory, sched, seen = world
    db = factory()
    a, _ = _hire(db, "morning-brief")
    b, _ = _hire(db, "notes-gardener")
    _settings(monkeypatch, agents_max_concurrent=1)
    other = str(uuid.uuid4())
    db.add(TaskRun(id=other, task_id=_task(db, b.id).id, status="running"))
    db.commit()
    first = str(uuid.uuid4())
    with pytest.raises(TaskDeferred) as caught:
        _run(sched, db, _task(db, a.id), run_id=first)
    db.query(TaskRun).filter(TaskRun.id == first).delete()     # as the engine does
    db.commit()
    assert caught.value.delay_seconds == R.CAPACITY_RETRY_SECONDS
    assert "1 agent runs are going already" in str(caught.value)
    assert "Morning Brief runs when one finishes" in str(caught.value)
    db.query(TaskRun).filter(TaskRun.id == other).update({"status": "success"})
    db.commit()
    seen["answer"] = "Today: nothing. Mail that needs you: nothing. Due: nothing. Overnight: nothing."
    _run(sched, db, _task(db, a.id))
    assert "system_prompt" in seen


def test_a_plain_tasks_run_is_not_counted_against_the_agents_limit(world, monkeypatch):
    factory, sched, seen = world
    db = factory()
    a, _ = _hire(db, "morning-brief")
    _settings(monkeypatch, agents_max_concurrent=1)
    plain = ScheduledTask(id="plain", owner="alice", name="Plain", prompt="hi", task_type="llm")
    db.add(plain)
    db.add(TaskRun(id=str(uuid.uuid4()), task_id="plain", status="running"))
    db.commit()
    seen["answer"] = "Today: nothing. Mail that needs you: nothing. Due: nothing. Overnight: nothing."
    _run(sched, db, _task(db, a.id))
    assert "system_prompt" in seen


def test_a_budget_hit_parks_the_hire_so_its_trigger_stops_asking(world):
    factory, sched, seen = world
    db = factory()
    h, _ = _hire(db, "model-steward")          # runs_per_day: 1
    task = _task(db, h.id)
    # `P24-27`. Model Steward's answer is checked for its three headings now;
    # the first run delivers, so the second meets the budget, not the contract.
    seen["answer"] = ("**Serving**\n- nothing\n\n**Downloaded, not served**\n- nothing\n\n"
                      "**Newer releases**\n- none found")
    _run(sched, db, task)
    db.query(TaskRun).update({"status": "success"})
    db.commit()
    with pytest.raises(R.AgentRunRefused, match="its limit, so it is paused. Switch it back on in Agents."):
        _run(sched, db, task)
    db.expire_all()
    assert db.query(AgentHire).get(h.id).status == "attention"
    assert _task(db, h.id).status == "paused"


# ── `P24-13` · a trial ──────────────────────────────────────────────────────

def test_a_trial_runs_only_when_asked_and_hiring_it_gives_back_its_triggers(world):
    factory, sched, seen = world
    db = factory()
    h, m = _hire(db, "morning-brief", status="trial")
    t = _task(db, h.id)
    assert (t.status, t.trigger_type, t.cron_expression, t.next_run, t.webhook_token) == \
        ("active", "webhook", None, None, None), "active so a forced run runs; no token, so no caller can"
    seen["answer"] = "Today: a quiet day. Mail that needs you: nothing. Due: nothing. Overnight: nothing."
    _run(sched, db, t)
    assert "system_prompt" in seen, "a trial run is a real run"
    H.set_status(db, h, m, "on")
    db.commit()
    t = _task(db, h.id)
    assert t.trigger_type == "schedule" and t.next_run is not None
    h2, m2 = _hire(db, "inbox-triage", status="trial")
    assert _task(db, h2.id).trigger_event is None
    H.set_status(db, h2, m2, "on")
    db.commit()
    t2 = _task(db, h2.id)
    assert (t2.status, t2.trigger_type, t2.trigger_event) == ("active", "event", "email_received")


def test_a_trial_paused_is_paused(world):
    factory, sched, seen = world
    db = factory()
    h, m = _hire(db, "morning-brief", status="trial")
    H.set_status(db, h, m, "paused")
    db.commit()
    assert _task(db, h.id).status == "paused"


# ── the settings door ───────────────────────────────────────────────────────

from tests.test_the_workstation_is_admin_controlled import (  # noqa: E402,F401  (fixtures)
    ADMIN, PLAIN, app, as_user, auth, datadir, stored,
)


def test_an_admin_pauses_all_agents_and_a_non_bool_is_refused(app):
    admin = as_user(app, ADMIN)
    assert stored("agents_paused") is False and stored("agents_max_concurrent") == 2
    r = admin.post("/api/auth/settings", json={"agents_paused": "yes"})
    assert r.status_code == 400 and r.json()["detail"] == "agents_paused must be true or false"
    assert stored("agents_paused") is False
    assert admin.post("/api/auth/settings", json={"agents_paused": True}).status_code == 200
    assert stored("agents_paused") is True
    assert as_user(app, PLAIN).post("/api/auth/settings", json={"agents_paused": False}).status_code == 403
    assert stored("agents_paused") is True


@pytest.mark.parametrize("sent,kept", [(0, 1), (5, 5), (99, 16)])
def test_the_limit_is_kept_inside_its_range(app, sent, kept):
    r = as_user(app, ADMIN).post("/api/auth/settings", json={"agents_max_concurrent": sent})
    assert r.status_code == 200, r.text
    assert stored("agents_max_concurrent") == kept


@pytest.mark.parametrize("key,value", [("agents_paused", True), ("agents_max_concurrent", 16)])
def test_the_assistant_cannot_move_its_own_brakes(datadir, key, value):
    """Through the real `manage_settings`, both ways: a `set`, and a `reset`
    back from a value an admin chose."""
    import asyncio
    import src.settings as S
    from src.agent_tools.admin_tools import do_manage_settings

    def agent(**args):
        out = asyncio.run(do_manage_settings(json.dumps(args)))
        S._invalidate_caches()
        return out

    shipped = S.get_setting(key)
    answer = agent(action="set", key=key, value=value)
    assert S.get_setting(key) == shipped
    assert "Settings" in str(answer.get("response", ""))
    S.save_settings({**S.load_settings(), key: value})
    S._invalidate_caches()
    agent(action="reset", key=key)
    assert S.get_setting(key) == value


# ── `B1434`: a hire works in the folder it names ────────────────────────────

def test_a_hire_runs_in_its_project_or_the_projects_folder(world, monkeypatch):
    import os
    from src.tool_execution import projects_root
    factory, sched, seen = world
    db = factory()
    root = projects_root("alice", create=True)
    os.makedirs(os.path.join(root, "shop"), exist_ok=True)
    h, _ = _hire(db, "morning-brief", inputs={"at": "06:00"}, project="shop")
    seen["answer"] = "Today: nothing. Mail that needs you: nothing. Due: nothing. Overnight: nothing."
    _run(sched, db, _task(db, h.id))
    assert seen["slot"]["workspace"] == os.path.realpath(os.path.join(root, "shop"))
    h2, _ = _hire(db, "morning-brief", inputs={"at": "06:00"})
    seen["answer"] = "Today: nothing. Mail that needs you: nothing. Due: nothing. Overnight: nothing."
    _run(sched, db, _task(db, h2.id))
    assert seen["slot"]["workspace"] == os.path.realpath(root)
    import src.workstation_access as wa
    monkeypatch.setattr(wa, "routes_tools", lambda owner, **kw: True)
    from src.agents.runtime import workspace_for
    # `B1642` changed this: it was `None` in the workstation, where the tools
    # then started in the home while the runbook's `cd` went to the projects
    # folder. The same folder on either machine; the workstation names it as
    # it does (`tests/test_a_hires_files_and_its_cd_meet_in_the_workstation.py`).
    assert workspace_for("alice", "shop") == os.path.realpath(os.path.join(root, "shop"))
