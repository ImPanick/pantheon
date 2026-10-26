# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1210`, the owner's call (`D-2026-10-26-01` §12) — both sentence drafters
stay, in the same words, and the task one offers to describe a workflow when
the work has several steps.

Tasks → Add → *Draft it* drafts one task; Workbench → New workflow → *Or
describe it* → *Draft it* drafts a workflow. A task runs its prompt as one
thing; a workflow runs each thing as its own step, checked before it can run.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.helpers.js_source import js_function

ROOT = Path(__file__).resolve().parents[1]


def _parse(monkeypatch, answer):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import routes.task.task_routes as task_routes
    import src.endpoint_resolver as er
    import src.llm_core as llm_core

    monkeypatch.setattr(er, "resolve_endpoint", lambda prefix, *a, owner=None, **k: ("http://m", "m-1", {}))

    async def call(**kw):
        return answer

    monkeypatch.setattr(llm_core, "llm_call_async", call)
    app = FastAPI()

    @app.middleware("http")
    async def _who(request, call_next):
        request.state.current_user = "alice"
        return await call_next(request)

    app.include_router(task_routes.setup_task_routes(None))
    return TestClient(app).post("/api/tasks/parse", json={"description": "x"}).json()


@pytest.mark.parametrize("steps, several", [(3, True), (2, True), (1, False), (None, False), ("3", False)])
def test_the_draft_says_when_the_work_is_several_things(monkeypatch, steps, several):
    import json
    body = {"prompt": "Check the NAS, then email me", "schedule": "daily"}
    if steps is not None:
        body["steps"] = steps
    got = _parse(monkeypatch, json.dumps(body))
    assert got["success"] is True
    assert bool(got["draft"].get("several_steps")) is several


def test_tasks_offers_the_workbench_drafter_with_the_same_words():
    src = (ROOT / "static" / "js" / "tasks.js").read_text(encoding="utf-8")
    draft = js_function(src, "async function _aiDraftTask")
    assert "draft.several_steps" in draft and "_offerWorkflowDraft(desc)" in draft
    offer = js_function(src, "function _offerWorkflowDraft")
    assert "openWorkbench({ room: 'automations', describe: desc" in offer
    assert "'Describe it as a workflow'" in offer


def test_the_workbench_fills_or_describe_it_and_drafts_nothing():
    room = (ROOT / "static" / "js" / "workbench" / "workflowRoom.js").read_text(encoding="utf-8")
    body = js_function(room, "function describeIt")
    assert "openNewForm()" in body and "describeBox.value" in body
    assert "draftIt" not in body and "createWorkflow" not in body, "filled, never sent"
    wb = (ROOT / "static" / "js" / "workbench" / "workbench.js").read_text(encoding="utf-8")
    assert "handle.describe(describe)" in wb


def test_both_doors_say_draft_it():
    tasks = (ROOT / "static" / "js" / "tasks.js").read_text(encoding="utf-8")
    room = (ROOT / "static" / "js" / "workbench" / "workflowRoom.js").read_text(encoding="utf-8")
    assert ">Draft it</button>" in tasks and "_button('wf-new-draft', 'Draft it'" in room
