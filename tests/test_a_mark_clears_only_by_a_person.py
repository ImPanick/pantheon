# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P22-19`, the integrator's call on wb-assist's `B-NEW-2` (`integrate-e`) — a
step's `unchecked` mark clears only by a person.

**Measured before this file, on the merged tree `0b9adaa`:** `_marks_kept`
dropped a mark from any step whose kind, name or settings a save changed, and
`PUT /api/workflows/{id}` with a graph is not person-only — so the assistant
could draft (`manage_tasks draft_workflow`), touch each step through `app_api`
(`PUT` with a label changed), and `manage_tasks resume`: every mark gone, the
switch no longer refused, and the drafted steps ran with nobody pressing
*Looks right*. The first case below is exactly that, and is red there (the
save answered 200 and left no mark).

**The rule now:** a mark clears only by a person (`request_is_a_person`) — a
person's *Looks right*, or a person's own save of that step. A change to a
step by anything that is not a person (the assistant's loopback, a bearer
token) marks that step `assistant` — even one a person had checked — and so
does a step it adds or a version it restores. Switching on stays refused while
any mark remains, and the walker refuses a real run of a marked document, so
an assistant's change to a workflow that is already on stops its next run
before any step starts.

**The adversary (`Law 17`):** text the assistant read in a turn the
post-external gate does not hold — a person asked it to "tidy up my draft",
and something in what it read steered the change. The control: whatever the
assistant writes into a step, a person reads before it runs.

Everything is real (`Law 20`): the routes through an ASGI client on a real
SQLite file, the store, the rule, `do_manage_tasks`, the scheduler from the
webhook down and the dispatcher, recorded as it is called.
"""

import json

import pytest

from core.database import TaskRun, TaskRunNode
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
WHO = {"the assistant's loopback": ASSISTANT, "a bearer token": TOKEN}


@pytest.fixture()
def world(monkeypatch, tmp_path):
    w = build_world(monkeypatch, tmp_path)
    import src.tool_execution as tool_execution
    real = tool_execution.execute_tool_block
    w.dispatched = []

    async def recorder(block, **kw):
        w.dispatched.append(getattr(block, "tool_name", None) or repr(block))
        return await real(block, **kw)
    monkeypatch.setattr(tool_execution, "execute_tool_block", recorder)
    return w


def _draft(w):
    db = w.factory()
    try:
        wf, trigger, _ = store.create_from_document(
            db, owner="alice", name="Issue digest", graph=json.loads(json.dumps(GRAPH)),
            trigger_fields={"trigger_type": "webhook"}, origin="drafted")
        return wf.id, trigger.id
    finally:
        db.close()


async def _call(w, method, path, headers=PERSON, **kw):
    async with client_for(w.app) as client:
        return await client.request(method, path, headers=headers, **kw)


def _sent(w, wf_id):
    """The stored document as a browser (or the assistant) would send it back:
    no marks — a save's body cannot carry one."""
    wf, doc, _ = stored(w.factory, wf_id)
    sent = json.loads(json.dumps(doc))
    for node in sent["nodes"]:
        node.pop("unchecked", None)
    return wf.version, sent


async def _save(w, wf_id, change, headers):
    version, sent = _sent(w, wf_id)
    change(sent)
    res = await _call(w, "PUT", f"/api/workflows/{wf_id}", headers=headers,
                      json={"graph": sent, "base_version": version})
    assert res.status_code == 200, res.text
    return res.json()


async def _check_all(w, wf_id):
    res = await _call(w, "PUT", f"/api/workflows/{wf_id}", json={"checked": IDS})
    assert res.status_code == 200, res.text
    assert not any(marks_of(stored(w.factory, wf_id)[1]).values())


def _origins(w, wf_id):
    return {i: (m or {}).get("origin") for i, m in marks_of(stored(w.factory, wf_id)[1]).items()}


async def test_the_assistant_touching_every_step_leaves_each_marked_and_the_switch_refused(world):
    """wb-assist's `B-NEW-2`, the attack itself: draft, touch each step through
    `app_api`, resume. Every step is still unchecked — now the assistant's —
    and both the switch and `manage_tasks resume` refuse."""
    from src.tools.system import do_manage_tasks
    w = world
    wf_id, task_id = _draft(w)

    def touch_each(sent):
        for node in sent["nodes"]:
            node["label"] += "."
    body = await _save(w, wf_id, touch_each, ASSISTANT)
    assert body["saved"] == "new_version"
    assert wd.ORIGIN_ASSISTANT == "assistant"
    assert _origins(w, wf_id) == {i: "assistant" for i in IDS}
    assert all(m["at"] and m["needs"] == [] for m in marks_of(stored(w.factory, wf_id)[1]).values())
    assert all("unchecked" not in n for v in versions(w.factory, wf_id) for n in v["graph"]["nodes"]), \
        "a kept version never holds a mark"

    refused = await _call(w, "POST", f"/api/workflows/{wf_id}/switch", headers=ASSISTANT,
                          json={"on": True})
    assert refused.status_code == 409, refused.text
    assert refused.json()["reason"] == "unchecked" and refused.json()["node_ids"] == IDS
    sentence = refused.json()["detail"]
    assert sentence.startswith("Your assistant (or an API token) changed 3 steps nobody has "
                               "checked yet: “Is it a new issue?.”"), sentence
    said = await do_manage_tasks(json.dumps({"action": "resume", "task_id": task_id}), owner="alice")
    assert said == {"error": sentence, "exit_code": 1}
    nope = await _call(w, "PUT", f"/api/workflows/{wf_id}", headers=ASSISTANT,
                       json={"checked": IDS})
    assert nope.status_code == 403
    assert stored(w.factory, wf_id)[2].status == "paused"


@pytest.mark.parametrize("who", list(WHO))
async def test_a_step_a_person_checked_is_marked_again_when_something_else_changes_it(world, who):
    w = world
    wf_id, _ = _draft(w)
    await _check_all(w, wf_id)

    def widen(sent):
        sent["nodes"][2]["config"]["args"]["channel"] = "#leak"
    await _save(w, wf_id, widen, WHO[who])
    assert _origins(w, wf_id) == {"opened": None, "summary": None, "post": "assistant"}, \
        "only the changed step, and it is marked even though a person had checked it"
    refused = await _call(w, "POST", f"/api/workflows/{wf_id}/switch", json={"on": True})
    assert refused.status_code == 409 and refused.json()["node_ids"] == ["post"]
    assert refused.json()["detail"].startswith(
        "Your assistant (or an API token) changed 1 step nobody has checked yet: “Post to #dev”. "
        "Open it and press Looks right")
    looked = await _call(w, "PUT", f"/api/workflows/{wf_id}", json={"checked": ["post"]})
    assert looked.status_code == 200
    on = await _call(w, "POST", f"/api/workflows/{wf_id}/switch", json={"on": True})
    assert on.status_code == 200, on.text


async def test_a_persons_own_save_of_the_step_clears_the_assistants_mark(world):
    w = world
    wf_id, _ = _draft(w)
    await _check_all(w, wf_id)

    def widen(sent):
        sent["nodes"][2]["config"]["args"]["channel"] = "#leak"
    await _save(w, wf_id, widen, ASSISTANT)
    assert _origins(w, wf_id)["post"] == "assistant"

    def put_back(sent):
        sent["nodes"][2]["config"]["args"]["channel"] = "#dev"
    await _save(w, wf_id, put_back, PERSON)
    assert _origins(w, wf_id) == {i: None for i in IDS}, "a person's change makes the step theirs"
    on = await _call(w, "POST", f"/api/workflows/{wf_id}/switch", json={"on": True})
    assert on.status_code == 200, on.text


async def test_a_step_the_assistant_adds_is_marked_and_one_it_only_moves_is_not(world):
    w = world
    wf_id, _ = _draft(w)
    await _check_all(w, wf_id)

    def add(sent):
        sent["nodes"][0]["position"] = [40, 80]          # moved: not a change
        sent["nodes"].append({"id": "extra", "kind": "mcp", "label": "Also post",
                              "config": {"tool": POST, "args": {"channel": "#leak",
                                                                "text": "{{ steps.summary.text }}"}}})
        sent["edges"].append({"from": "summary", "port": "success", "to": "extra"})
    await _save(w, wf_id, add, ASSISTANT)
    assert _origins(w, wf_id) == {"opened": None, "summary": None, "post": None, "extra": "assistant"}

    nothing = await _save(w, wf_id, lambda sent: None, ASSISTANT)
    assert nothing["saved"] == "unchanged"
    assert _origins(w, wf_id)["opened"] is None, "a save that changes nothing marks nothing"


async def test_a_version_the_assistant_restores_marks_what_it_changes(world):
    w = world
    wf_id, _ = _draft(w)
    await _check_all(w, wf_id)

    def reword(sent):
        sent["nodes"][1]["config"]["prompt"] = "Summarise it in one line."
    await _save(w, wf_id, reword, PERSON)
    res = await _call(w, "POST", f"/api/workflows/{wf_id}/versions/1/restore", headers=ASSISTANT,
                      json={"base_version": 2})
    assert res.status_code == 200 and res.json()["saved"] == "new_version", res.text
    assert _origins(w, wf_id) == {"opened": None, "summary": "assistant", "post": None}
    assert [v["source"] for v in versions(w.factory, wf_id)] == ["drafted", "user", "restored"]


async def test_the_assistants_change_to_a_workflow_that_is_on_stops_its_next_run(world):
    """A workflow already switched on: the assistant points its post at #leak.
    The webhook still starts a run, and the walker ends it `error` with the
    refusal's sentence before any step — nothing reaches the dispatcher and
    nothing is posted, to #leak or anywhere."""
    w = world
    wf_id, task_id = _draft(w)
    await _check_all(w, wf_id)
    on = await _call(w, "POST", f"/api/workflows/{wf_id}/switch", json={"on": True})
    assert on.status_code == 200, on.text

    def widen(sent):
        sent["nodes"][2]["config"]["args"]["channel"] = "#leak"
    await _save(w, wf_id, widen, ASSISTANT)
    token = stored(w.factory, wf_id)[2].webhook_token
    hook = await _call(w, "POST", f"/api/tasks/{task_id}/webhook/{token}", headers={},
                       json={"action": "opened", "issue": {"title": "Crash on save"}})
    assert hook.status_code == 200, hook.text
    await settle(w.s)
    [run] = rows(w.factory, TaskRun, task_id=task_id)
    sentence = wd.unchecked_refusal(stored(w.factory, wf_id)[1]).sentence
    assert run.status == "error" and sentence in (run.error or ""), (run.status, run.error)
    assert rows(w.factory, TaskRunNode, run_id=run.id) == []
    assert w.dispatched == [] and w.chat.posted == []


async def test_only_a_draft_or_a_file_marks_a_whole_document():
    """`assistant` is set step by step by a save, never as a document's origin."""
    with pytest.raises(ValueError):
        store.create_from_document(None, owner="alice", name="x", graph=GRAPH,
                                   trigger_fields={}, origin=wd.ORIGIN_ASSISTANT)
