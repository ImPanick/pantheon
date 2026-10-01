# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P22-06`'s API half — *Make this chain a workflow*, switch it on, *Put the
old chain back*; nothing is deleted (`D-2026-10-01-05` §1, `Law 1`).

**Measured before this file, on `5654cd4`:** `POST /api/workflows` did not
exist, so a chain could not become a document; and nothing paused a chain's
first step so that it and a copy of it would not both run.

The rules driven here, from `/work/notes/SLICE-B-DESIGN.md` § 5 and § 6.5 and
the integrator's call 3 (`/work/notes/P22-WAVE-C.md`): a conversion copies the
chain into a new workflow **switched off** and writes nothing to any task of
the chain; switching it on pauses the chain's first step and says so; *Put the
old chain back* resumes that step and switches the workflow off; a converted
webhook chain gets a new address and the person is told both, at conversion
and at switch-on. The workflow starts where the chain does — the one first
step that leads to the step picked; a second chain that only shares a step
further down is not part of it and is named as still running. Refused in
words: a step two chains reach (which one to start from is the person's
call), a chain with a workflow in it, a loop, another owner's task. Real
routes, real store, real SQLite file; the engine's `chain_to_document` is
`C1`'s (stood in for by `tests/helpers/workflow_contract.py` until
`wf-engine` merges, its checks and notes following wf-engine's `1b3dbb5`) —
so what the store says is asserted word for word, and what the engine says
by its reason key or by the names in it.
"""

from __future__ import annotations

import json

import pytest

from core.database import ScheduledTask, TaskRun
from tests.helpers import workflow_contract as wc
from test_a_workflow_is_kept_as_one_document import (  # noqa: F401
    admins, call, client, rows, sched, stored, versions, wf_db,
)


def _chain(factory, *, trigger="schedule", owner="alice", extra=()):
    """Nightly backup → (works) Tell me it worked; (fails) Clean up."""
    db = factory()
    try:
        common = dict(owner=owner, output_target="session", run_count=4)
        db.add(ScheduledTask(id="backup", name="Nightly backup", task_type="action",
                             action="tidy_sessions", trigger_type=trigger, schedule="daily",
                             scheduled_time="02:00", status="active",
                             webhook_token="old-token" if trigger == "webhook" else None,
                             **common))
        db.add(ScheduledTask(id="told", name="Tell me it worked", task_type="llm",
                             prompt="Say the backup worked.", trigger_type="webhook",
                             status="active", **common))
        db.add(ScheduledTask(id="clean", name="Clean up", task_type="action",
                             action="tidy_documents", trigger_type="webhook", status="active",
                             **common))
        for row in extra:
            db.add(row)
        db.commit()
        backup = db.query(ScheduledTask).filter(ScheduledTask.id == "backup").first()
        backup.then_task_id, backup.else_task_id = "told", "clean"
        db.commit()
    finally:
        db.close()


def _snapshot(factory):
    """Every task row as a tuple of its columns, and how many of everything."""
    Workflow, WorkflowVersion, TaskRunNode = wc.models()
    db = factory()
    try:
        tasks = {t.id: {c.name: getattr(t, c.name) for c in ScheduledTask.__table__.columns}
                 for t in db.query(ScheduledTask).all()}
        counts = {m.__name__: db.query(m).count()
                  for m in (ScheduledTask, TaskRun, Workflow, WorkflowVersion, TaskRunNode)}
        return tasks, counts
    finally:
        db.close()


def _convert(client, from_task_id="told", user="alice"):
    return call(client, "POST", "/api/workflows", user=user, json={"from_task_id": from_task_id})


def test_a_chain_is_copied_into_a_switched_off_workflow_and_no_task_changes(client, wf_db):
    _chain(wf_db)
    tasks_before, counts_before = _snapshot(wf_db)
    res = _convert(client, from_task_id="told")
    assert res.status_code == 200, res.text
    out = res.json()
    wf = out["workflow"]
    # Every step, by name; both outcomes kept as ports.
    labels = {n["id"]: n["label"] for n in wf["graph"]["nodes"]}
    assert sorted(labels.values()) == ["Clean up", "Nightly backup", "Tell me it worked"]
    by_label = {v: k for k, v in labels.items()}
    assert sorted((labels[e["from"]], e["port"], labels[e["to"]]) for e in wf["graph"]["edges"]) == [
        ("Nightly backup", "error", "Clean up"), ("Nightly backup", "success", "Tell me it worked")]
    assert {n["kind"] for n in wf["graph"]["nodes"] if n["id"] == by_label["Nightly backup"]} == {"action"}
    # The start takes the chain's schedule, switched off; named after it.
    trigger = wf["trigger_task"]
    assert (trigger["task_type"], trigger["status"], trigger["schedule"], trigger["scheduled_time"]) == (
        "workflow", "paused", "daily", "02:00")
    assert wf["name"] == "Nightly backup (workflow)"
    assert wf["converted_from"] == {"head_task_id": "backup", "head_name": "Nightly backup",
                                    "head_status": "active"}
    # The store says what only it knows; the engine says what was made from
    # what — and, picked mid-chain, where it starts.
    assert "“Nightly backup (workflow)” is switched off, and the chain still runs as before." in out["notes"]
    assert any("“Nightly backup”" in n for n in out["notes"]), "picked mid-chain: said where it starts"
    assert len(out["notes"]) == len(set(out["notes"])), "nothing said twice"
    (row,) = rows(wf_db, wc.models()[1], workflow_id=wf["id"])
    assert (row.version, row.source) == (1, "converted")
    # Nothing in the chain moved; one start, one document, one version added.
    tasks_after, counts_after = _snapshot(wf_db)
    assert {k: v for k, v in tasks_after.items() if k in tasks_before} == tasks_before
    assert counts_after == dict(counts_before, ScheduledTask=4, Workflow=1, WorkflowVersion=1)


def test_switch_on_pauses_the_chains_first_step_and_put_back_undoes_it(client, wf_db):
    _chain(wf_db)
    wf = _convert(client).json()["workflow"]
    _, counts = _snapshot(wf_db)

    on = call(client, "POST", f"/api/workflows/{wf['id']}/switch", json={"on": True})
    assert on.status_code == 200, on.text
    body = on.json()
    assert body["chain_paused"] == {"task_id": "backup", "name": "Nightly backup"}
    assert body["notes"][0] == ("Switched on. The chain's first step, “Nightly backup”, is paused "
                                "so the two do not both run.")
    assert body["workflow"]["trigger_status"] == "active"
    assert body["workflow"]["trigger_task"]["next_run"], "on a schedule, it has a next run"
    assert body["workflow"]["converted_from"]["head_status"] == "paused"
    (head,) = rows(wf_db, ScheduledTask, id="backup")
    assert head.status == "paused"

    back = call(client, "POST", f"/api/workflows/{wf['id']}/restore-chain")
    assert back.status_code == 200, back.text
    body = back.json()
    assert body["notes"] == ["The chain runs again and this workflow is switched off. Nothing was deleted."]
    assert body["chain_resumed"]["task_id"] == "backup" and body["chain_resumed"]["next_run"]
    assert body["workflow"]["trigger_status"] == "paused"
    (head,) = rows(wf_db, ScheduledTask, id="backup")
    assert head.status == "active" and head.next_run is not None
    # Nothing was deleted, and nothing new was written, by either.
    assert _snapshot(wf_db)[1] == counts


def test_switch_off_is_the_start_paused_and_nothing_else(client, wf_db):
    _chain(wf_db)
    wf = _convert(client).json()["workflow"]
    call(client, "POST", f"/api/workflows/{wf['id']}/switch", json={"on": True})
    off = call(client, "POST", f"/api/workflows/{wf['id']}/switch", json={"on": False})
    assert off.status_code == 200
    assert off.json()["chain_paused"] is None
    assert off.json()["notes"] == ["Switched off — it will not run until you switch it on."]
    assert off.json()["workflow"]["trigger_status"] == "paused"
    (head,) = rows(wf_db, ScheduledTask, id="backup")
    assert head.status == "paused", "switching off does not restart the chain; Put back does"
    bad = call(client, "POST", f"/api/workflows/{wf['id']}/switch", json={"on": "yes"})
    assert bad.status_code == 400


def test_a_converted_webhook_chain_has_a_new_address_and_both_are_told(client, wf_db):
    _chain(wf_db, trigger="webhook")
    out = _convert(client).json()
    trigger = out["workflow"]["trigger_task"]
    new_token = trigger["webhook_token"]
    assert new_token and new_token != "old-token"
    new_url = f"/api/tasks/{trigger['id']}/webhook/{new_token}"
    old_url = "/api/tasks/backup/webhook/old-token"
    said = " ".join(out["notes"])
    assert new_url in said and old_url in said
    assert "only answers while the chain is on" in said
    assert sum("webhook" in n.lower() for n in out["notes"]) == 1, (
        "the two addresses are said once, by the store — not again by the engine's note")
    on = call(client, "POST", f"/api/workflows/{out['workflow']['id']}/switch", json={"on": True})
    said = " ".join(on.json()["notes"])
    assert new_url in said and old_url in said


def _second_chain_into_clean_up(factory):
    """Weekly report → Clean up: a second chain sharing the backup's last step."""
    db = factory()
    try:
        db.add(ScheduledTask(id="second", owner="alice", name="Weekly report", task_type="llm",
                             prompt="x", trigger_type="webhook", status="active",
                             then_task_id="clean"))
        db.commit()
    finally:
        db.close()


def test_a_second_chain_sharing_a_step_is_left_running_and_named(client, wf_db):
    """Picked on a step only the backup's chain reaches, the workflow is that
    chain; the other chain into its last step is not a second start — it is
    named as one that keeps running as it does now."""
    _chain(wf_db)
    _second_chain_into_clean_up(wf_db)
    tasks_before, _ = _snapshot(wf_db)
    res = _convert(client, from_task_id="told")
    assert res.status_code == 200, res.text
    out = res.json()
    labels = sorted(n["label"] for n in out["workflow"]["graph"]["nodes"])
    assert labels == ["Clean up", "Nightly backup", "Tell me it worked"]
    assert out["workflow"]["converted_from"]["head_task_id"] == "backup"
    assert any("“Weekly report”" in n for n in out["notes"]), "the other chain is named"
    tasks_after, _ = _snapshot(wf_db)
    assert {k: v for k, v in tasks_after.items() if k in tasks_before} == tasks_before


@pytest.mark.parametrize("case", ["two_heads", "workflow_member", "loop", "other_owner", "missing"])
def test_a_chain_that_cannot_be_one_document_is_refused_in_words(client, wf_db, case):
    _chain(wf_db)
    picked = "told"
    if case == "two_heads":
        # Clean up is reached from both first steps: which one the workflow
        # starts at is the person's to say.
        _second_chain_into_clean_up(wf_db)
        picked = "clean"
    db = wf_db()
    try:
        if case == "loop":
            db.query(ScheduledTask).filter(ScheduledTask.id == "clean").first().then_task_id = "backup"
        elif case == "other_owner":
            db.add(ScheduledTask(id="bobs", owner="bob", name="Bob's", task_type="llm",
                                 prompt="x", trigger_type="webhook", status="active"))
            db.flush()
            db.query(ScheduledTask).filter(ScheduledTask.id == "told").first().then_task_id = "bobs"
        db.commit()
    finally:
        db.close()
    if case == "workflow_member":
        wf = _convert(client).json()["workflow"]
        db = wf_db()
        try:
            db.query(ScheduledTask).filter(ScheduledTask.id == "clean").first().then_task_id = wf["task_id"]
            db.commit()
        finally:
            db.close()
    before = _snapshot(wf_db)
    res = _convert(client, from_task_id="missing" if case == "missing" else picked)
    expected = {"two_heads": 400, "workflow_member": 400, "loop": 400, "other_owner": 400,
                "missing": 404}[case]
    assert res.status_code == expected, res.text
    detail = res.json()["detail"]
    assert isinstance(detail, str) and detail.strip()
    if case == "two_heads":
        assert detail == ("“Clean up” is reached from 2 first steps, “Nightly backup” and "
                          "“Weekly report”, and a workflow starts in one place. Make it from "
                          "the one it should start at.")
    if case == "workflow_member":
        assert res.json()["reason"] == "workflow_member", "the engine's own refusal"
    if case == "loop":
        from src.task_scheduler import CHAIN_REFUSAL_REASONS, CHAIN_CYCLE
        lead = CHAIN_REFUSAL_REASONS[CHAIN_CYCLE]
        assert detail.startswith(lead[:1].upper() + lead[1:]), "the engine's one sentence (`P22-01`)"
    if case == "other_owner":
        assert res.json()["reason"] == "cross_owner", "the engine's own refusal"
        assert "Bob's" not in detail, "another owner's task is never named"
    assert _snapshot(wf_db) == before, "a refusal writes nothing"


def test_switching_on_a_workflow_the_engine_refuses_says_why_and_changes_nothing(client, wf_db):
    res = call(client, "POST", "/api/workflows", json={"name": "Empty"})
    wf = res.json()["workflow"]
    on = call(client, "POST", f"/api/workflows/{wf['id']}/switch", json={"on": True})
    assert on.status_code == 400
    assert on.json()["detail"].strip() and "reason" in on.json()
    (trigger,) = rows(wf_db, ScheduledTask, id=wf["task_id"])
    assert trigger.status == "paused"


def test_put_back_on_a_workflow_that_was_not_a_chain_says_there_is_none(client):
    wf = call(client, "POST", "/api/workflows", json={"name": "Fresh"}).json()["workflow"]
    res = call(client, "POST", f"/api/workflows/{wf['id']}/restore-chain")
    assert res.status_code == 400
    assert res.json()["detail"] == "This workflow was not made from a chain, so there is no chain to put back."


def test_resume_from_the_tasks_window_is_the_same_switch(client, wf_db):
    """The Tasks window's Resume on a workflow's start runs the one switch
    rule — the document checked, the chain paused — or a converted workflow
    and its chain would both run after a Resume."""
    _chain(wf_db)
    wf = _convert(client).json()["workflow"]
    res = call(client, "POST", f"/api/tasks/{wf['task_id']}/resume")
    assert res.status_code == 200, res.text
    assert res.json()["chain_paused"] == {"task_id": "backup", "name": "Nightly backup"}
    (head,) = rows(wf_db, ScheduledTask, id="backup")
    (start,) = rows(wf_db, ScheduledTask, id=wf["task_id"])
    assert (head.status, start.status) == ("paused", "active")
    # And the plain task's Resume is untouched.
    assert call(client, "POST", "/api/tasks/backup/resume").json()["status"] == "active"


def test_deleting_a_converted_workflow_leaves_the_chain_and_says_if_it_is_paused(client, wf_db):
    _chain(wf_db)
    wf = _convert(client).json()["workflow"]
    call(client, "POST", f"/api/workflows/{wf['id']}/switch", json={"on": True})
    res = call(client, "DELETE", f"/api/workflows/{wf['id']}")
    assert res.status_code == 200
    assert res.json()["notes"] == ["The chain it was made from is still paused. Resume "
                                   "“Nightly backup” to run it again."]
    assert sorted(t.id for t in rows(wf_db, ScheduledTask)) == ["backup", "clean", "told"]
