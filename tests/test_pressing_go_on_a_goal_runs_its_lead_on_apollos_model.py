# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pressing go on a goal runs its lead on the model Apollo talks on.

The owner's test on the dev build (2026-11-25): "Setting up a goal, and then
pressing "go" doesn't start the LLM on the goal." The goal read Working, with
no tokens, and stayed so.

The lead's run named no model, so it took the scheduled-work chain (the model
for scheduled tasks, then Utility, then the default chat model). On an install
where none of those is set, the run stopped at "No model yet" while Apollo
itself was talking on a local model. And a run that stopped before it reported
never told the goal, so the goal kept saying Working.

These run the real scheduler on a scripted model (`world`): a goal started
with Apollo's chat on a model reaches that model; a lead that can't run says
why on the goal and asks; a run that never starts does the same.
"""
from __future__ import annotations

import pytest

from tests.test_a_plain_task_waits_for_your_yes import world  # noqa: F401
from tests.helpers.walker_harness import runs_of, settle

OWNER = "alice"
APOLLO_URL = "http://127.0.0.1:9/v1"      # the world's scripted endpoint
APOLLO_MODEL = "scripted"


@pytest.fixture
def leads_dir(monkeypatch, tmp_path):
    from src.apollo import goal_lead
    monkeypatch.setattr(goal_lead, "BASE_DIR", str(tmp_path / "leads"))
    from src.apollo import lead
    monkeypatch.setattr(lead, "pick_lead", lambda owner, text: None)


def _apollo_chat(db, *, url=APOLLO_URL, model=APOLLO_MODEL):
    """Apollo's own chat, on the model the person picked for it."""
    from core.database import CrewMember, Session as DbSession, utcnow_naive
    now = utcnow_naive()
    db.add(DbSession(id="apollo-chat", name="Apollo", endpoint_url=url, model=model, owner=OWNER,
                     mode="agent", folder="Apollo", created_at=now, updated_at=now))
    db.add(CrewMember(id="apollo", owner=OWNER, name="Apollo", is_default_assistant=True,
                      session_id="apollo-chat"))
    db.commit()


def _go(db, title):
    """What "Start it" does: make the goal and prepare its lead's run."""
    from src.apollo import runs as R, tasks as T
    t = T.create(db, OWNER, title=title, started_by="person")
    run, why = R.prepare(db, OWNER, t)
    db.commit()
    return t.id, run, why


@pytest.mark.asyncio
async def test_a_new_goal_runs_its_lead_on_apollos_model(world, leads_dir):
    from core.database import ScheduledTask
    from src.apollo import tasks as T
    db = world.factory()
    _apollo_chat(db)
    tid, run, why = _go(db, "Update and prep the VM for DevOps")
    assert run and why == ""
    st = db.query(ScheduledTask).filter(ScheduledTask.id == run).first()
    assert (st.endpoint_url, st.model) == (APOLLO_URL, APOLLO_MODEL)
    db.close()

    world.script.append("## Plan\n1. Check the VM.\n\n## Report\nThe VM is ready for DevOps work.")
    await world.s._execute_task(run)
    await settle(world.s)

    assert len(world.seen) >= 1, "pressing go never reached the model"
    said = " ".join(str(m.get("content") or "") for m in world.seen[0]["messages"])
    assert "Update and prep the VM for DevOps" in said, "the lead was not told the goal"
    [r] = runs_of(world.factory, run)
    assert r["status"] == "success", r["error"]
    db = world.factory()
    assert T.get(db, OWNER, tid).state != "working", "the goal never moved on after its lead reported"
    db.close()


@pytest.mark.asyncio
async def test_a_lead_that_cant_run_says_why_on_the_goal_and_asks(world, leads_dir):
    """No model anywhere: the run stops, and the goal says so instead of Working."""
    from src.apollo import tasks as T
    posted = []
    world.s._post_to_apollo = lambda owner, line, meta: posted.append((owner, line, meta))
    db = world.factory()
    tid, run, _why = _go(db, "Plan the garden")
    db.close()

    await world.s._execute_task(run)
    await settle(world.s)

    assert world.seen == []
    [r] = runs_of(world.factory, run)
    assert r["status"] == "error"
    db = world.factory()
    t = T.get(db, OWNER, tid)
    assert t.state == "needs_you"
    assert t.question.startswith("The lead's run stopped:") and t.question.endswith("Run it again?")
    db.close()
    assert len(posted) == 1 and posted[0][0] == OWNER and "Plan the garden" in posted[0][1]
    assert posted[0][2] == {"apollo_task": tid, "kind": "run_failed"}


def test_a_run_that_never_starts_leaves_the_goal_asking(world, leads_dir):
    from src.apollo import runs as R, tasks as T
    db = world.factory()
    _apollo_chat(db)
    tid, run, _why = _go(db, "Write the release notes")
    assert T.get(db, OWNER, tid).state == "working"
    t = R.did_not_start(db, OWNER, tid)
    assert t.state == "needs_you" and t.question == R.NOT_STARTED
    db.close()


def test_a_saved_agents_own_model_is_kept_and_a_written_lead_follows_apollo():
    from types import SimpleNamespace as NS
    from src.apollo import goal_lead as G, runs as R
    saved = NS(endpoint_url="http://gpu:8000/v1", model="their-pick")
    R._run_on(saved, NS(lead_agent="researcher"), APOLLO_URL, APOLLO_MODEL)
    assert (saved.endpoint_url, saved.model) == ("http://gpu:8000/v1", "their-pick")
    bare = NS(endpoint_url=None, model=None)
    R._run_on(bare, NS(lead_agent="researcher"), APOLLO_URL, APOLLO_MODEL)
    assert (bare.endpoint_url, bare.model) == (APOLLO_URL, APOLLO_MODEL)
    written = NS(endpoint_url="http://old:1/v1", model="old")
    R._run_on(written, NS(lead_agent=G.lead_id("0" * 20)), APOLLO_URL, APOLLO_MODEL)
    assert (written.endpoint_url, written.model) == (APOLLO_URL, APOLLO_MODEL)


@pytest.mark.parametrize("title,name", [
    ("Update and prep the VM for DevOps", "Ops lead"),
    ("Research local LLM hosting options", "Research lead"),
    ("Write the release notes", "Writing lead"),
    ("Fix the login bug", "Build lead"),
    ("Plan the garden", "Planning lead"),
    ("Something else entirely", "Goal lead"),
])
def test_a_written_lead_has_a_short_role_name_not_the_goals_title(title, name):
    from src.apollo import goal_lead as G
    assert G.fields("0" * 20, title=title)["name"] == name


def test_a_lead_written_before_short_names_answers_to_its_role_name(tmp_path):
    """The owner's goal already under way read "Lead: Update and Prep the VM
    for DevOps" on every card; it reads "Ops lead" without being written again."""
    import os
    from src.apollo import goal_lead as G
    m = G.write("alice", "0" * 20, title="Update and Prep the VM for DevOps", data_dir=str(tmp_path))
    path = G._path("alice", m.id, str(tmp_path))
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text.replace("Ops lead", "Lead: Update and Prep the VM for DevOps"))
    from src.agents import workshop
    workshop._forget(path)
    assert os.path.exists(path)
    assert G.get("alice", m.id, data_dir=str(tmp_path)).name == "Ops lead"
