# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1870` — a parked step's yes or no is a person's, and only a person's.

`P22-17` parks a model-chosen action on a card the person answers from a
notification (`POST /api/workflows/{id}/runs/{run}/answer`), and `B1102` gave a
plain Prompt task the same door (`POST /api/tasks/{id}/runs/{run}/answer`).
Neither door asked `request_is_a_person`, the check `src/auth_helpers.py` names
for exactly "where only a person may answer". So anything acting in the owner's
name could answer — the agent's own `app_api` loopback (it carries the
internal-tool header) or a bearer API token. **Measured on `5e4c8ec`** with this
file's world: the loopback listed the card at `GET /api/workflows/waiting`,
answered it `approve_task`, got 200 "Allowed once by alice at …: bash", and the
sealed `bash` ran — while `PUT {checked: [...]}` from the same caller was a 403.

The adversary (`Law 17`): whoever wrote what the run read. Their words arm the
gate so the model's `bash` needs the owner's yes; if the assistant (driven by
those same words, in a chat turn that is not itself gated) can say the yes, the
gate asks the attacker's agent and not the person. A token is the same shape:
minted by a person, held by something else (`B70`).

Everything that decides is real (`Law 20`): the real scheduler and walker, the
real agent loop (only the model's words are scripted), the real gate and store,
the real routes over httpx's ASGI transport. The far end of a tool is the one
recorder, so "it did not run" is an empty list.
"""

import pytest

from core.middleware import INTERNAL_TOOL_HEADER
from src.tool_approvals import tool_approval_store
from src import workflow_store as store
from tests.helpers.walker_harness import client_for, runs_of, settle
# The two worlds are one world (the real loop, a scripted model, a recording far
# end), so the plain task's helpers run in the workflow file's fixture.
from tests.test_a_plain_task_waits_for_your_yes import _answer_url, _plain_task
from tests.test_a_plain_task_waits_for_your_yes import _park as _park_plain
from tests.test_a_step_that_needs_a_yes_waits_for_it import (  # noqa: F401 — the fixture
    _park, _reply_workflow, world,
)

pytestmark = pytest.mark.asyncio

# The assistant's own loopback: `app_api` sends the internal-tool header and
# `X-Pantheon-Owner`, and the auth middleware names the owner. Any value of the
# header counts against the request (`request_is_a_person`), so this is it.
LOOPBACK = {"x-test-user": "alice", INTERNAL_TOOL_HEADER: "anything"}
# A bearer token resolved back to the person who minted it.
TOKEN = {"x-test-user": "alice", "x-test-token": "1"}
ALICE = {"x-test-user": "alice"}


def _with_tokens(app):
    """The harness names the caller; this marks a bearer-token request the way
    the auth middleware does (`request.state.api_token`)."""
    @app.middleware("http")
    async def _token(request, call_next):
        if request.headers.get("x-test-token"):
            request.state.api_token = True
        return await call_next(request)
    return app


@pytest.mark.parametrize("caller", [LOOPBACK, TOKEN], ids=["assistant-loopback", "api-token"])
async def test_the_workflow_door_refuses_anything_but_a_person_and_consumes_nothing(world, caller):
    w = world
    _with_tokens(w.app)
    _reply_workflow(w)
    run, rec = await _park(w)
    card = rec["waiting"]["approval"]
    url = f"/api/workflows/w-wf/runs/{run['id']}/answer"
    async with client_for(w.app) as client:
        for decision in ("approve_task", "deny"):
            res = await client.post(url, headers=caller,
                                    json={"node_id": "reply", "item": None,
                                          "approval_id": card["approval_id"], "decision": decision})
            assert res.status_code == 403, res.text
            assert res.json()["detail"] == store.ONLY_A_PERSON_ANSWERS
        assert tool_approval_store.peek(card["approval_id"]) is not None, "nothing was consumed"
        await settle(w.s)
        assert w.executed == [], "the sealed action did not run"
        [still] = runs_of(w.factory, "wf")
        assert still["status"] == "waiting", "the card still waits for the person"
        # The person, from the page, still answers it.
        ok = await client.post(url, headers=ALICE,
                               json={"node_id": "reply", "item": None,
                                     "approval_id": card["approval_id"], "decision": "approve_task"})
        assert ok.status_code == 200, ok.text
    await settle(w.s)
    assert w.executed == [("bash", "printf reply-sent")]


@pytest.mark.parametrize("caller", [LOOPBACK, TOKEN], ids=["assistant-loopback", "api-token"])
async def test_the_plain_task_door_refuses_anything_but_a_person_and_consumes_nothing(world, caller):
    w = world
    _with_tokens(w.app)
    _plain_task(w)
    run, rec = await _park_plain(w)
    approval_id = rec["waiting"]["approval"]["approval_id"]
    async with client_for(w.app) as client:
        for decision in ("approve_task", "deny"):
            res = await client.post(_answer_url(run), headers=caller,
                                    json={"approval_id": approval_id, "decision": decision})
            assert res.status_code == 403, res.text
            assert res.json()["detail"] == store.ONLY_A_PERSON_ANSWERS
        assert tool_approval_store.peek(approval_id) is not None, "nothing was consumed"
        await settle(w.s)
        assert w.executed == []
        ok = await client.post(_answer_url(run), headers=ALICE,
                               json={"approval_id": approval_id, "decision": "approve_task"})
        assert ok.status_code == 200, ok.text
    await settle(w.s)
    assert w.executed == [("bash", "printf reply-sent")]


def test_the_sentence_says_who_may_answer_in_plain_words():
    """What the assistant reads back when it tries (`Law 15`): who may answer,
    and where — the same shape as the checked and fix doors' sentences."""
    assert store.ONLY_A_PERSON_ANSWERS == (
        "Only you can answer a step that is waiting for your yes, from the notification or "
        "the Workbench — not an API token and not your assistant.")
