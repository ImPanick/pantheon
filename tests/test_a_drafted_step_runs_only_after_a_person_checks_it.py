# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P22-19` (`SLICE-EF-DESIGN` § 1.1, § 1.2, § 5.2) — a step the model drafted,
or one a file carried, runs only after a person has checked it.

**Measured before this file, on `4cfb297`:** nothing could carry the mark —
`parse_graph` kept exactly `{id, kind, label, config, position, pinned}` and
dropped every other key, the version sources were `user`, `converted` and
`restored`, and `PUT /api/workflows/{id}` took four bodies, none of them a
person saying a step looks right. Every case below fails there (no
`create_from_document`, no mark kept, no `{checked}` door, no 409, no guard).

**The adversary (`Law 17`):** whoever wrote the third-party text the drafter
read (an MCP tool's, a skill's or an Integration's description), or the file.
The controls held here: the draft is saved switched OFF and every step marked;
the switch refuses while a mark remains — through the Workbench's switch, the
task route's resume and `manage_tasks resume` alike; only a PERSON clears a
mark (`request_is_a_person`: not a bearer token, not the assistant's loopback);
a save cannot set or clear a mark; a kept version never holds one; and the
walker refuses a real run of a marked document however its trigger came to be
on, before any step starts. The dry run still plans it.

Everything is real (`Law 20`): the store, the routes through an ASGI client on
a real SQLite file, the scheduler from `_execute_task` down, the rule, the
slots, and the real dispatcher (`execute_tool_block`), recorded as it is
called; the far end is a chat server that records each post.
"""

import json

import pytest

from core.database import ScheduledTask, TaskRun, TaskRunNode, Workflow, WorkflowVersion
from src import workflow_document as wd
from src import workflow_store as store
from tests.helpers.assist_harness import (
    ASSISTANT, PERSON, POST, TOKEN, build_world, marks_of, rows, stored, versions,
)
from tests.helpers.walker_harness import client_for, settle

pytestmark = pytest.mark.asyncio

GRAPH = {"v": 1, "nodes": [
    {"id": "opened", "kind": "if", "label": "Is it a new issue?",
     "config": {"conditions": [{"left": "{{ steps.start.data.json.action }}", "op": "equals",
                                "right": "opened"}]}},
    {"id": "summary", "kind": "llm", "label": "Summarise",
     "config": {"prompt": "Summarise the issue {{ steps.start.data.json.issue.title }}."}},
    {"id": "post", "kind": "mcp", "label": "Post to #dev",
     "config": {"tool": POST, "args": {"channel": "#dev", "text": "{{ steps.summary.text }}"}}},
], "edges": [{"from": "opened", "port": "then", "to": "summary"},
             {"from": "summary", "port": "success", "to": "post"}]}
IDS = ["opened", "summary", "post"]


@pytest.fixture()
def world(monkeypatch, tmp_path):
    w = build_world(monkeypatch, tmp_path)
    import src.tool_execution as tool_execution
    real = tool_execution.execute_tool_block
    w.dispatched = []

    async def recorder(block, **kw):
        w.dispatched.append(getattr(block, "tool_name", None) or getattr(block, "name", None)
                            or repr(block))
        return await real(block, **kw)
    monkeypatch.setattr(tool_execution, "execute_tool_block", recorder)
    return w


def _draft(w, graph=None, *, fields=None, origin="drafted"):
    db = w.factory()
    try:
        wf, trigger, notes = store.create_from_document(
            db, owner="alice", name="Issue digest", graph=json.loads(json.dumps(graph or GRAPH)),
            trigger_fields=fields if fields is not None else {"trigger_type": "webhook"},
            origin=origin)
        return wf.id, trigger.id, notes
    finally:
        db.close()


async def _call(w, method, path, headers=PERSON, **kw):
    async with client_for(w.app) as client:
        return await client.request(method, path, headers=headers, **kw)


async def test_a_draft_is_saved_off_marked_and_its_webhook_token_minted(world):
    w = world
    forged = {"trigger_type": "webhook", "webhook_token": "forged-token", "status": "active",
              "id": "forged-id", "owner": "mallory", "task_type": "llm"}
    graph = json.loads(json.dumps(GRAPH))
    graph["nodes"][0]["pinned"] = {"data": {"json": {"action": "opened"}}}
    graph["nodes"][1]["unchecked"] = None
    wf_id, task_id, notes = _draft(w, graph, fields=forged)
    wf, doc, trigger = stored(w.factory, wf_id)
    assert trigger.status == "paused" and trigger.task_type == "workflow"
    assert trigger.id == task_id != "forged-id" and trigger.owner == "alice"
    assert trigger.trigger_type == "webhook"
    assert trigger.webhook_token and trigger.webhook_token != "forged-token"
    assert [n["id"] for n in doc["nodes"]] == IDS
    assert all(n["pinned"] is None for n in doc["nodes"]), "a sample is never read from outside"
    for node_id, mark in marks_of(doc).items():
        assert mark["origin"] == "drafted" and mark["needs"] == [] and mark["at"], (node_id, mark)
    [v1] = versions(w.factory, wf_id)
    assert v1["version"] == 1 and v1["source"] == wd.VERSION_SOURCE_DRAFTED == "drafted"
    assert all("unchecked" not in n for n in v1["graph"]["nodes"]), "a version never holds a mark"
    assert any(n.endswith("It is off.") for n in notes)  # P23-05: said once, short
    assert any(f"/api/tasks/{task_id}/webhook/{trigger.webhook_token}" in n for n in notes)


async def test_its_webhook_answers_404_and_starts_nothing(world):
    w = world
    wf_id, task_id, _ = _draft(w)
    token = stored(w.factory, wf_id)[2].webhook_token
    res = await _call(w, "POST", f"/api/tasks/{task_id}/webhook/{token}",
                      json={"action": "opened", "issue": {"title": "Crash"}})
    assert res.status_code == 404
    assert rows(w.factory, TaskRun, task_id=task_id) == []
    assert w.chat.posted == [] and w.dispatched == []


async def test_switching_on_is_refused_while_a_step_is_unchecked(world):
    w = world
    wf_id, task_id, _ = _draft(w)
    res = await _call(w, "POST", f"/api/workflows/{wf_id}/switch", json={"on": True})
    assert res.status_code == 409, res.text
    body = res.json()
    assert body["reason"] == wd.REFUSE_UNCHECKED == "unchecked"
    assert body["node_ids"] == IDS
    # P23-05 (Doc 2 § 5, WB-U-2): the instruction is short; *Check them now* sits beside it.
    assert body["detail"] == ("The model drafted 3 steps nobody has checked yet: “Is it a new "
                              "issue?”, “Summarise”, “Post to #dev”. Check them first.")
    assert stored(w.factory, wf_id)[2].status == "paused"


async def test_the_task_routes_resume_and_the_assistants_resume_are_refused_the_same(world):
    from src.tools.system import do_manage_tasks
    w = world
    wf_id, task_id, _ = _draft(w)
    sentence = wd.unchecked_refusal(stored(w.factory, wf_id)[1]).sentence
    res = await _call(w, "POST", f"/api/tasks/{task_id}/resume")
    assert res.status_code == 409 and res.json()["detail"] == sentence
    said = await do_manage_tasks(json.dumps({"action": "resume", "task_id": task_id}),
                                 owner="alice")
    assert said == {"error": sentence, "exit_code": 1}
    assert stored(w.factory, wf_id)[2].status == "paused"


@pytest.mark.parametrize("who", ["a bearer token", "the assistant's loopback"])
async def test_only_a_person_says_a_step_looks_right(world, who):
    w = world
    wf_id, _, _ = _draft(w)
    headers = TOKEN if who == "a bearer token" else ASSISTANT
    res = await _call(w, "PUT", f"/api/workflows/{wf_id}", headers=headers,
                      json={"checked": ["summary"]})
    assert res.status_code == 403
    assert res.json() == {"detail": store.ONLY_A_PERSON_CHECKS}
    assert all(marks_of(stored(w.factory, wf_id)[1]).values())


async def test_a_person_checks_steps_and_no_version_is_written(world):
    w = world
    wf_id, _, _ = _draft(w)
    before = stored(w.factory, wf_id)[0].version
    res = await _call(w, "PUT", f"/api/workflows/{wf_id}", json={"checked": ["summary", "post"]})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["saved"] == store.SAVED_CHECKED == "checked"
    assert marks_of(body["workflow"]["graph"]) == {
        "opened": marks_of(stored(w.factory, wf_id)[1])["opened"], "summary": None, "post": None}
    assert stored(w.factory, wf_id)[0].version == before
    assert len(versions(w.factory, wf_id)) == 1
    nope = await _call(w, "PUT", f"/api/workflows/{wf_id}", json={"checked": ["ghost"]})
    assert nope.status_code == 400 and "ghost" in nope.json()["detail"]
    still = await _call(w, "POST", f"/api/workflows/{wf_id}/switch", json={"on": True})
    assert still.status_code == 409 and still.json()["node_ids"] == ["opened"]


async def test_a_save_keeps_marks_on_unchanged_steps_drops_them_on_changed_ones(world):
    w = world
    wf_id, _, _ = _draft(w)
    wf, doc, _ = stored(w.factory, wf_id)
    sent = json.loads(json.dumps(doc))
    for node in sent["nodes"]:
        node.pop("unchecked", None)                         # the client sends no marks…
    sent["nodes"][0]["position"] = [40, 80]                 # moved: not a change
    sent["nodes"][1]["label"] = "Summarise it"              # changed: the editor's now
    sent["nodes"][2]["unchecked"] = {"origin": "imported", "at": "x", "needs": []}  # forged
    sent["nodes"].append({"id": "extra", "kind": "llm", "label": "Extra",
                          "config": {"prompt": "Say hi."},
                          "unchecked": {"origin": "drafted", "at": "x", "needs": []}})
    sent["edges"].append({"from": "post", "port": "success", "to": "extra"})
    res = await _call(w, "PUT", f"/api/workflows/{wf_id}",
                      json={"graph": sent, "base_version": wf.version})
    assert res.status_code == 200 and res.json()["saved"] == "new_version", res.text
    marks = marks_of(stored(w.factory, wf_id)[1])
    assert marks["opened"] == marks_of(doc)["opened"], "unchanged (only moved): kept"
    assert marks["summary"] is None, "changed: the mark goes"
    assert marks["post"] == marks_of(doc)["post"], "a forged mark is not the stored one"
    assert marks["extra"] is None, "a save cannot set a mark"
    assert all("unchecked" not in n for v in versions(w.factory, wf_id) for n in v["graph"]["nodes"])


async def test_a_restore_keeps_a_mark_only_where_the_current_step_still_has_it(world):
    w = world
    wf_id, _, _ = _draft(w)
    wf, doc, _ = stored(w.factory, wf_id)
    sent = json.loads(json.dumps(doc))
    sent["nodes"][1]["config"]["prompt"] = "Summarise it in one line."
    await _call(w, "PUT", f"/api/workflows/{wf_id}", json={"graph": sent, "base_version": 1})
    res = await _call(w, "POST", f"/api/workflows/{wf_id}/versions/1/restore",
                      json={"base_version": 2})
    assert res.status_code == 200 and res.json()["saved"] == "new_version", res.text
    marks = marks_of(stored(w.factory, wf_id)[1])
    assert marks["summary"] is None, "a restore never brings a mark back"
    assert marks["opened"] and marks["post"]
    assert [v["source"] for v in versions(w.factory, wf_id)] == ["drafted", "user", "restored"]


async def test_a_marked_document_switched_on_in_the_database_does_not_run(world):
    """§ 5.2's last control: a document written straight to the database with
    its trigger on. The run ends `error` with the refusal's sentence, no step
    record is written, and the dispatcher is never reached."""
    w = world
    wf_id, task_id, _ = _draft(w)
    db = w.factory()
    try:
        db.query(ScheduledTask).filter(ScheduledTask.id == task_id).first().status = "active"
        db.commit()
    finally:
        db.close()
    sentence = wd.unchecked_refusal(stored(w.factory, wf_id)[1]).sentence
    await w.s._execute_task(task_id, trigger={"source": "webhook", "event": "webhook",
                                              "data": {"json": {"action": "opened"}}})
    [run] = rows(w.factory, TaskRun, task_id=task_id)
    assert run.status == "error" and sentence in (run.error or "")
    assert rows(w.factory, TaskRunNode, run_id=run.id) == []
    assert w.dispatched == [] and w.chat.posted == [] and w.s.calls == []


async def test_the_dry_run_still_plans_a_marked_draft(world):
    w = world
    wf_id, task_id, _ = _draft(w)
    run_id = await w.s.run_task_now(task_id, dry=True)
    await settle(w.s)
    [run] = rows(w.factory, TaskRun, task_id=task_id)
    assert run.id == run_id and run.status == "skipped"
    planned = rows(w.factory, TaskRunNode, run_id=run.id)
    assert sorted(r.node_id for r in planned) == sorted(IDS) and all(r.dry for r in planned)
    assert w.dispatched == [] and w.chat.posted == []


async def test_once_a_person_checks_every_step_it_switches_on_and_runs(world):
    w = world
    wf_id, task_id, _ = _draft(w)
    res = await _call(w, "PUT", f"/api/workflows/{wf_id}", json={"checked": IDS})
    assert res.status_code == 200
    on = await _call(w, "POST", f"/api/workflows/{wf_id}/switch", json={"on": True})
    assert on.status_code == 200, on.text
    token = stored(w.factory, wf_id)[2].webhook_token
    hook = await _call(w, "POST", f"/api/tasks/{task_id}/webhook/{token}", headers={},
                       json={"action": "opened", "issue": {"title": "Crash on save"}})
    assert hook.status_code == 200, hook.text
    await settle(w.s)
    [run] = rows(w.factory, TaskRun, task_id=task_id)
    assert run.status == "success", (run.status, run.error)
    assert w.chat.posted == [(POST, {"channel": "#dev", "text": "Issue digest · Summarise: done"})]
    assert len(rows(w.factory, WorkflowVersion, workflow_id=wf_id)) == 1
    assert rows(w.factory, Workflow, id=wf_id)[0].version == 1
