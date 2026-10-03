# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1111` — a step's question names its tool as the step's panel does, and
says what the action can do in words.

Measured by `integrate-d` (P22-17's drive) and again here on `7a7f9b2`: the
toast, the dialog and the run's log said "mcp__0e311a43__send_message" where
the step's own panel says "Chat: send_message" (`stepFields.js`: the server's
name and the tool's), and the dialog's "Effects:" line listed the stored
values ("admin_change, destructive, execute_code, …") — though every card the
server makes carries their words (`describe_effects`' `effect_labels`).

Now the walker names the tool once, where it first catches the question
(`task_scheduler.named_question` → `workflow_effects.tool_words`, read off the
MCP servers connected now), and keeps the words beside the sealed name in the
waiting record (`tool_label`): the run's log line, the notification's body and
`review`, the waiting list and the answer's sentence read it; the browser's
notice reads it, and the card's "Effects:" line reads `effect_labels`. The
card's sealed action keeps the name it calls. The dry run's plan of an MCP
step names it the same way (`workflow_document.mcp_tool_words`, the one
wording, which "Where it sends things" already used).

Driven (`Law 20`): the real scheduler, walker, `authored_call_context`,
approval store and answer route over a recording MCP far end at the strictest
rung (`test_a_step_you_configured_runs`' world), then the real notice and
card in node, handed the review the real scheduler queued.
"""
import json

import pytest

from src.tool_approvals import tool_approval_store
from tests.helpers.walker_harness import client_for, records_of, runs_of, seed_workflow, settle
from tests.test_a_step_you_configured_runs import POST, _post_step, _strict, _webhook, world  # noqa: F401

WORDS = "chat: send_message"      # the recording server's name and the tool's, as the panel says


async def _park(w, monkeypatch):
    _strict(monkeypatch)
    seed_workflow(w.factory, [_post_step("one", "Post first")], trigger_type="webhook", owner="alice")
    await w.s._execute_task("wf", trigger=_webhook("first words"))
    [run] = runs_of(w.factory, "wf")
    rec = {r["node_id"]: r for r in records_of(w.factory, run["id"])}["one"]
    return run, rec


@pytest.mark.asyncio
async def test_the_log_the_notification_and_the_waiting_list_say_the_panels_words(world, monkeypatch):
    w = world
    run, rec = await _park(w, monkeypatch)
    assert run["status"] == "waiting"
    [line] = [s for s in run["steps"] if s.get("node") == "one" and s.get("status") == "waiting"]
    assert line["detail"] == f"Waiting for your yes on {WORDS}"
    assert rec["waiting"]["tool_label"] == WORDS
    from core.database import TaskRunNode
    db = w.factory()
    stored = json.loads(db.query(TaskRunNode).filter(TaskRunNode.id == rec["id"]).first().waiting)
    db.close()
    assert stored["tool"] == POST and stored["tool_label"] == WORDS, "the record keeps the sealed name"
    assert rec["waiting"]["approval"]["action"]["tool"] == POST, "…and so does the card"
    [note] = [n for n in w.s.pop_notifications() if n["status"] == "waiting"]
    assert note["body"] == f"“Post first” is waiting for your yes: {WORDS}."
    assert note["review"]["tool_label"] == WORDS
    async with client_for(w.app) as client:
        listed = (await client.get("/api/workflows/waiting",
                                   headers={"x-test-user": "alice"})).json()["waiting"]
    assert [x["tool_label"] for x in listed] == [WORDS]


@pytest.mark.asyncio
async def test_the_answer_names_the_tool_as_the_panel_does(world, monkeypatch):
    w = world
    run, rec = await _park(w, monkeypatch)
    async with client_for(w.app) as client:
        res = await client.post(f"/api/workflows/w-wf/runs/{run['id']}/answer",
                                headers={"x-test-user": "alice"},
                                json={"node_id": "one", "approval_id": rec["waiting"]["approval"]["approval_id"],
                                      "decision": "deny"})
    assert res.status_code == 200, res.text
    assert res.json()["sentence"].endswith(f": {WORDS} — it was not done.")
    await settle(w.s)
    [run] = runs_of(w.factory, "wf")
    assert not any(POST in str(s.get("detail") or "") for s in run["steps"]), \
        "the run's log never says the qualified name"
    assert w.posted == []


@pytest.mark.asyncio
async def test_the_plan_names_an_mcp_tool_as_the_panel_does(world):
    from src import workflow_document as wd
    from src.workflow_effects import workflow_resources
    lines = wd.plan_lines(_post_step("one", "Post first"), workflow_resources("alice"))
    assert lines[0] == f"Would call the tool {WORDS}"
    # A tool whose server is not connected here keeps its own name (`Law 10`).
    assert wd.plan_lines(_post_step() | {"config": {"tool": "mcp__gone__x", "args": {}}},
                         workflow_resources("alice"))[0] == "Would call the tool mcp__gone__x"


@pytest.mark.asyncio
async def test_a_built_in_tool_keeps_its_own_name():
    from src.task_scheduler import named_question
    from src.builtin_actions import TaskWaiting
    parked = named_question(TaskWaiting("Waiting for your yes on bash", kind="approval", tool="bash"))
    assert parked.sentence == "Waiting for your yes on bash" and parked.detail["tool_label"] == "bash"
    timed = TaskWaiting("Waiting until 08:00", kind="time", until=1.0)
    assert named_question(timed) is timed, "only a question is named"


# ── the browser: the real notice and card, handed what the scheduler queued ──

@pytest.fixture(scope="module")
def notice_box(tmp_path_factory):
    """The sandbox of `test_a_workflow_question_is_answered_from_the_notice_js`:
    the real `workflowApprovalNotice.js`, `approvalBox.js` and
    `escMenuStack.js`; `ui.js` recorded."""
    import shutil

    from tests.test_a_workflow_question_is_answered_from_the_notice_js import (
        _CANVAS_SHIM, _UI, _WORKBENCH, JS, build_sandbox,
    )
    root = tmp_path_factory.mktemp("named")
    box = build_sandbox(root, _CANVAS_SHIM, stubs={"ui.js": _UI, "workbench/workbench.js": _WORKBENCH})
    shutil.copy(JS / "workflowApprovalNotice.js", root / "workflowApprovalNotice.js")
    return box


def _browser_case(box, review, script):
    from tests.test_a_workflow_question_is_answered_from_the_notice_js import _PREAMBLE, _run, palette_json
    return _run(box, _PREAMBLE % (palette_json(), json.dumps(review)), script)


@pytest.mark.asyncio
async def test_the_notice_and_the_card_say_the_tool_and_its_effects_in_words(world, monkeypatch, notice_box):
    w = world
    await _park(w, monkeypatch)
    [note] = [n for n in w.s.pop_notifications() if n["status"] == "waiting"]
    review = dict(note["review"], workflow=note["review"].get("workflow") or "Morning digest")
    card = review["approval"]
    assert card["effect_labels"] and card["action"]["effects"], "the real card carries both"
    o = _browser_case(notice_box, review, """
        notice.offerWorkflowApproval(REVIEW);
        const toast = ui.toasts[0];
        await ui.actions[0]();
        const d = dialog();
        out({ toast, sub: d.querySelector('.wf-approval-sub').textContent.split(' Waiting since')[0],
              action: d.querySelector('.skill-test-out').textContent });
    """)
    assert o["toast"][0] == f"“Morning digest” is waiting for your yes: “Post first” wants to use {WORDS}."
    assert o["sub"] == f"“Post first” wants to use {WORDS}."
    effects = [line for line in o["action"].split("\n") if line.startswith("Effects: ")]
    assert effects == ["Effects: " + ", ".join(card["effect_labels"])], o["action"]
    assert not any(v in effects[0] for v in card["action"]["effects"]), "no stored value is shown"
    assert o["action"].split("\n")[0] == POST, "the sealed action is shown as it will be called"
