# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B879` — testing a skill twice used to destroy the first result.

**What was measured on the tree before this file existed**, by driving the real
route rather than by reading it:

  * `POST /api/skills/{id}/test` assigned `_skill_test_jobs[key] = {...}`
    unconditionally at `routes/skills_routes.py:1599`, where `key` is
    `(owner, skill_name)` — one slot per skill, for all time.
  * `:1591`, immediately above it, hand-denied the previous job's pending
    approval: `tool_approval_store.consume(..., decision="deny", owner=user,
    session_id=None)`.
  * Driven: post a test, park `appr-1` and a `needs_work` verdict on the job,
    post the same skill again. `consume` was called `[('appr-1', 'deny')]`,
    `GET /test-status` then answered `verdict: None, approval: None`, and
    `len(_skill_test_jobs)` was still 1.

That is the second, unrecorded blocker on `P8-09`: a before/after comparison is
two runs of ONE skill, and the second one erased the first one's answer before
anybody could read it.

The fix is a **list** of runs per skill, newest last, capped. Every case here
drives the shipped route functions with a stubbed job coroutine and a stubbed
endpoint resolver, because the defect was never in the agent loop — it was in
what the endpoint did with the slot before the loop was even started.

The deny did not disappear and this file proves it did not: it moved to
`_append_skill_test_run`, which is the one place a card genuinely stops being
reachable — eviction past the cap.
"""

import asyncio
import json
import textwrap

import pytest
from fastapi import HTTPException, Request
from fastapi.datastructures import State

import routes.skills_routes as skills_routes
from routes.skills_routes import setup_skills_routes
from services.memory.skill_format import slugify
from services.memory.skills import SkillsManager

OWNER = "alice"


def _write_skill(root, name, owner=OWNER, body="- step 1"):
    d = root / "skills" / slugify("general", fallback="general") / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(textwrap.dedent(f"""\
        ---
        name: {name}
        description: a skill
        version: 1.0.0
        category: general
        tags: []
        status: draft
        confidence: 0.8
        source: learned
        owner: {owner}
        created: 2026-01-01T00:00:00Z
        ---

        # When to use
        testing

        # Procedure
        {body}
        """), encoding="utf-8")
    return d / "SKILL.md"


def _request(user, body=None, method="POST"):
    class DummyApp:
        state = State()

    payload = json.dumps(body).encode("utf-8") if body is not None else b""
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent = True
        return {"type": "http.request", "body": payload, "more_body": False}

    return Request(scope={
        "type": "http",
        "method": method,
        "headers": [(b"content-type", b"application/json")],
        "app": DummyApp(),
        "state": {"current_user": user},
    }, receive=receive)


def _route(router, path, method):
    return next(r.endpoint for r in router.routes
                if r.path == path and method in r.methods)


@pytest.fixture()
def wired(tmp_path, monkeypatch):
    """A real router over a real SkillsManager, with no model anywhere near it."""
    _write_skill(tmp_path, "packer")
    sm = SkillsManager(str(tmp_path), library_root="")
    router = setup_skills_routes(sm)

    monkeypatch.setattr("src.endpoint_resolver.resolve_endpoint",
                        lambda *a, **k: ("http://model.test", "m1", None))
    monkeypatch.setattr("src.llm_core.list_model_ids", lambda *a, **k: [])

    started = []

    async def fake_job(key, name, md, task, url, model, headers, owner,
                       manager=None, **kw):
        started.append({"key": key, "md": md, "task": task,
                        "run_id": kw.get("run_id")})

    monkeypatch.setattr(skills_routes, "_run_skill_test_job", fake_job)

    denied = []

    class FakeStore:
        def consume(self, approval_id, **kw):
            denied.append((approval_id, kw.get("decision")))
            return None

    monkeypatch.setattr("src.tool_approvals.tool_approval_store", FakeStore())
    skills_routes._skill_test_jobs.clear()
    try:
        yield {"router": router, "sm": sm, "started": started, "denied": denied,
               "root": tmp_path}
    finally:
        skills_routes._skill_test_jobs.clear()


async def _post_test(wired, name="packer", task="do the thing"):
    return await _route(wired["router"], "/api/skills/{skill_id}/test", "POST")(
        _request(OWNER, {"task": task}), name)


async def _status(wired, name="packer", run=""):
    return await _route(wired["router"], "/api/skills/{skill_id}/test-status", "GET")(
        _request(OWNER, method="GET"), name, run=run)


@pytest.mark.asyncio
async def test_a_second_test_does_not_erase_the_first_result(wired):
    """The measurement at the top of this file, re-run against the fix."""
    first = await _post_test(wired, task="task one")
    await asyncio.sleep(0)
    key = (OWNER, "packer")
    run_one = skills_routes._skill_test_run(key, first["run_id"])
    # Park exactly what the old measurement parked.
    run_one["status"] = "awaiting_approval"
    run_one["approval"] = {"kind": "tool_approval", "approval_id": "appr-1"}
    run_one["verdict"] = {"verdict": "needs_work", "confidence": 0.6,
                          "summary": "vague step 2", "issues": []}

    second = await _post_test(wired, task="task two")
    await asyncio.sleep(0)

    # Nothing was denied: the first card is still answerable.
    assert wired["denied"] == []
    # Two runs, not one slot.
    assert len(skills_routes._skill_test_runs(key)) == 2
    assert second["run_id"] != first["run_id"]

    # The first answer is still readable, by id.
    kept = await _status(wired, run=first["run_id"])
    assert kept["verdict"]["verdict"] == "needs_work"
    assert kept["approval"]["approval_id"] == "appr-1"
    assert kept["task"] == "task one"

    # And the default answer is still the newest run, which is what every
    # existing caller of /test-status meant.
    latest = await _status(wired)
    assert latest["run_id"] == second["run_id"]
    assert latest["task"] == "task two"
    assert [r["run_id"] for r in latest["runs"]] == [first["run_id"], second["run_id"]]


@pytest.mark.asyncio
async def test_either_run_can_answer_its_own_approval(wired):
    """The approval route used to look in "the" job slot, so with two runs the
    card belonging to the older one could not be answered at all."""
    first = await _post_test(wired)
    await asyncio.sleep(0)
    second = await _post_test(wired)
    await asyncio.sleep(0)
    key = (OWNER, "packer")
    older = skills_routes._skill_test_run(key, first["run_id"])
    older["status"] = "awaiting_approval"
    older["approval"] = {"kind": "tool_approval", "approval_id": "appr-older"}

    assert skills_routes._skill_test_run_for_approval(key, "appr-older") is older
    # The newest run is not awaiting anything, and the id belongs to the older
    # one — the route must find it rather than 409 on "not awaiting".
    assert skills_routes._skill_test_run_for_approval(key, "appr-newer") is None
    assert skills_routes._skill_test_run(key, second["run_id"])["status"] == "running"


@pytest.mark.asyncio
async def test_an_unknown_approval_id_is_still_refused(wired):
    """`B879` widened the lookup; it did not widen what may be consumed."""
    first = await _post_test(wired)
    await asyncio.sleep(0)
    key = (OWNER, "packer")
    skills_routes._skill_test_run(key, first["run_id"])["status"] = "awaiting_approval"
    skills_routes._skill_test_run(key, first["run_id"])["approval"] = {
        "kind": "tool_approval", "approval_id": "appr-1"}

    approve = _route(wired["router"], "/api/skills/{skill_id}/test-approval", "POST")
    with pytest.raises(HTTPException) as e:
        await approve(_request(OWNER, {"approval_id": "not-mine",
                                       "decision": "approve"}), "packer")
    assert e.value.status_code == 409
    assert wired["denied"] == []


@pytest.mark.asyncio
async def test_eviction_is_where_the_deny_went(wired):
    """The deny the endpoint used to do on every second test still exists — at
    the one point where a pending card stops being reachable."""
    runs = []
    for i in range(skills_routes.MAX_SKILL_TEST_RUNS):
        r = await _post_test(wired, task=f"task {i}")
        await asyncio.sleep(0)
        runs.append(r["run_id"])
    key = (OWNER, "packer")
    oldest = skills_routes._skill_test_run(key, runs[0])
    oldest["status"] = "awaiting_approval"
    oldest["approval"] = {"kind": "tool_approval", "approval_id": "appr-evicted"}
    assert wired["denied"] == []

    extra = await _post_test(wired, task="one too many")
    await asyncio.sleep(0)

    assert wired["denied"] == [("appr-evicted", "deny")]
    assert skills_routes._skill_test_run(key, runs[0]) is None
    assert len(skills_routes._skill_test_runs(key)) == skills_routes.MAX_SKILL_TEST_RUNS
    assert skills_routes._skill_test_runs(key)[-1]["run_id"] == extra["run_id"]


@pytest.mark.asyncio
async def test_status_for_a_skill_with_no_runs_is_unchanged(wired):
    assert await _status(wired) == {"status": "none"}


@pytest.mark.asyncio
async def test_another_owners_skill_is_still_not_found(wired):
    """`_require_own_skill` replaced four copies of this check; it is the same
    check, and it still 404s rather than leaking the name."""
    with pytest.raises(HTTPException) as e:
        await _route(wired["router"], "/api/skills/{skill_id}/test", "POST")(
            _request("mallory", {"task": "x"}), "packer")
    assert e.value.status_code == 404
