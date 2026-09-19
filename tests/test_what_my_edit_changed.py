# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P8-09` — run the old text and the new text against ONE task and say what moved.

**What was on the tree before this file**, re-measured 2026-09-19 by driving it:

  * `_run_skill_test_once(md, task, url, model, headers, owner)` — six
    positional parameters, and on a gated run it called
    `tool_approval_store.consume(..., decision="deny", owner=owner,
    session_id=None)` at `routes/skills_routes.py:744-749`. Driven twice
    against a stubbed loop emitting one `tool_approval`, `consume` was called
    `[('appr-1', 'deny'), ('appr-1', 'deny')]`. That is exactly what `B592`
    recorded — **and it is not what was blocking this row.** That function
    cannot pause: it breaks out of the stream and keeps no continuation state,
    so an approval it declined to deny would be a card nobody could answer.
    A comparison is built on `_run_skill_test_job`, which already pauses,
    already keeps `_transcript` and `_run`, and already has an endpoint that
    answers the card with the owner check. `B592`'s parameter is therefore in
    the wrong function and was never added; the first case below is the
    control that says the deny is still exactly where it was.
  * `POST /{skill_id}/test` kept one job slot per `(owner, skill_name)`, so the
    first half's answer was destroyed when the second half started. That is
    `B879`, it was the only real blocker, and
    `tests/test_testing_a_skill_twice_keeps_both.py` is its file.

This file is the row: a comparison, reachable, honest about what it can and
cannot tell you.

**The third thing, stated rather than hidden.** Two runs of one skill are not
two measurements of one quantity — the run is sampled (`temperature=0.3`, and
`grep -n seed src/llm_core.py` returns nothing, so no endpoint in this repo
takes a seed), so two runs of the *same* markdown differ. The diff therefore
compares the verdict, the tool sequence and the round count, never the prose,
and carries `same_text` so that a comparison of a skill against an identical
earlier copy says in its first line that everything below it is noise. That
line is tested here, because it is the difference between a diff and a lie.
"""

import asyncio
import json
import textwrap

import pytest
from fastapi import HTTPException, Request
from fastapi.datastructures import State

import routes.skills_routes as skills_routes
from routes.skills_routes import (
    _run_skill_test_once,
    _skill_run_diff,
    setup_skills_routes,
)
import inspect
from services.memory.skills import SkillsManager

OWNER = "alice"

APPROVAL = {"kind": "tool_approval", "approval_id": "appr-1",
            "question": "Allow this exact action once?"}


def _write_skill(root, name, procedure="- step 1"):
    d = root / "skills" / "general" / name
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
        owner: {OWNER}
        created: 2026-01-01T00:00:00Z
        ---

        # When to use
        testing

        # Procedure
        {procedure}
        """), encoding="utf-8")


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


# ── half one: the deny `B592` named, and why it stayed ──────────────────────

def _gated_loop(monkeypatch):
    async def fake_loop(*a, **k):
        yield "data: " + json.dumps({
            "type": "tool_output", "tool": "bash",
            "output": "Waiting for an exact user approval.",
            "ask_user": APPROVAL,
        })
    monkeypatch.setattr("src.agent_loop.stream_agent_loop", fake_loop)


def _spy_store(monkeypatch):
    seen = []

    class FakeStore:
        def consume(self, approval_id, **kw):
            seen.append((approval_id, kw.get("decision")))
            return None

    monkeypatch.setattr("src.tool_approvals.tool_approval_store", FakeStore())
    return seen


def test_an_unattended_run_still_denies_the_card_it_cannot_answer(monkeypatch):
    """`B592`'s measurement, re-run. Nothing here moved, deliberately."""
    _gated_loop(monkeypatch)
    seen = _spy_store(monkeypatch)

    text, verdict = asyncio.run(_run_skill_test_once(
        "md", "task", "http://x", "m", None, OWNER))

    assert seen == [("appr-1", "deny")]
    assert verdict["approval_required"] is True
    assert "Waiting for an exact user approval" in text


def test_the_unblocking_parameter_b592_names_was_not_added(monkeypatch):
    """The correction this row carries. `B592` says the fix is a parameter on
    `_run_skill_test_once`; building the comparison showed that function cannot
    host it — it has no pause and no continuation state, so an approval it left
    pending is one nobody could answer. The comparison uses
    `_run_skill_test_job`, which has both, so the parameter would have had no
    caller and the second runner would have been `Law 14`."""
    params = list(inspect.signature(_run_skill_test_once).parameters)
    assert params == ["md", "task", "url", "model", "headers", "owner"]
    # The runner the comparison really uses is the one that can stop and wait.
    job_params = inspect.signature(skills_routes._run_skill_test_job).parameters
    assert "exact_approval" in job_params and "transcript" in job_params


def test_both_unattended_callers_still_take_the_deny():
    """Two call sites, both unattended, both unchanged — stated as a fact about
    the tree rather than as an assumption."""
    import src.builtin_actions as builtin_actions

    src = inspect.getsource(skills_routes._audit_one_skill)
    assert "_run_skill_test_once(md, task, url, model, headers, owner)" in src
    assert "_run_skill_test_once(md, task, url, model, headers, owner)" in \
        inspect.getsource(builtin_actions.action_test_skills)


# ── half two: the diff itself ───────────────────────────────────────────────

def _run(log_tools, verdict, **extra):
    log = [{"type": "skill_test_start"}]
    for t in log_tools:
        log.append({"type": "agent_step", "round": len(log)})
        log.append({"type": "tool_start", "tool": t})
    run = {"run_id": "r", "status": "done", "log": log,
           "verdict": verdict, "task": "t", "model": "m"}
    run.update(extra)
    return run


def test_the_diff_reads_the_verdict_the_tools_and_the_rounds():
    before = _run(["bash", "bash"], {"verdict": "needs_work",
                                     "issues": ["step 2 is vague"]},
                  source_label="earlier copy 0001-1.0.0")
    after = _run(["read_file"], {"verdict": "pass", "issues": []},
                 source_label="current version")

    d = _skill_run_diff(before, after)

    assert d["verdict_changed"] is True
    assert (d["before_verdict"], d["after_verdict"]) == ("needs_work", "pass")
    assert d["before_tools"] == ["bash", "bash"]
    assert d["after_tools"] == ["read_file"]
    assert d["tools_added"] == ["read_file"]
    assert d["tools_removed"] == ["bash"]
    assert (d["before_rounds"], d["after_rounds"]) == (2, 1)
    assert d["issues_resolved"] == ["step 2 is vague"]
    assert d["issues_introduced"] == []
    assert d["both_finished"] is True
    assert d["same_text"] is False


def test_repeats_are_a_difference_and_are_not_collapsed():
    d = _skill_run_diff(_run(["bash"], {"verdict": "pass"}),
                        _run(["bash", "bash", "bash"], {"verdict": "pass"}))
    assert d["tools_changed"] is True
    assert d["tools_added"] == [] and d["tools_removed"] == []


def test_an_unfinished_half_is_not_reported_as_a_result():
    before = _run(["bash"], {"verdict": "pass"})
    after = _run([], None)
    after["status"] = "queued"
    d = _skill_run_diff(before, after)
    assert d["both_finished"] is False
    assert d["after_verdict"] is None


def test_identical_text_is_carried_so_the_panel_can_say_it_is_noise():
    before = _run(["bash"], {"verdict": "pass"})
    before["_same_text_as_after"] = True
    d = _skill_run_diff(before, _run(["read_file"], {"verdict": "needs_work"}))
    assert d["same_text"] is True
    assert d["verdict_changed"] is True  # and the panel leads with the caveat


# ── half three: the route ───────────────────────────────────────────────────

@pytest.fixture()
def wired(tmp_path, monkeypatch):
    _write_skill(tmp_path, "packer")
    sm = SkillsManager(str(tmp_path), library_root="")
    sm.update_skill("packer", {"procedure": ["step 1", "step 2 — be specific"]},
                    owner=OWNER)
    router = setup_skills_routes(sm)
    monkeypatch.setattr("src.endpoint_resolver.resolve_endpoint",
                        lambda *a, **k: ("http://model.test", "m1", None))
    monkeypatch.setattr("src.llm_core.list_model_ids", lambda *a, **k: [])
    skills_routes._skill_test_jobs.clear()
    try:
        yield {"router": router, "sm": sm, "root": tmp_path}
    finally:
        skills_routes._skill_test_jobs.clear()


@pytest.mark.asyncio
async def test_a_skill_with_no_earlier_copy_is_told_so_in_words(tmp_path, monkeypatch):
    _write_skill(tmp_path, "fresh")
    sm = SkillsManager(str(tmp_path), library_root="")
    router = setup_skills_routes(sm)
    monkeypatch.setattr("src.endpoint_resolver.resolve_endpoint",
                        lambda *a, **k: ("http://model.test", "m1", None))
    with pytest.raises(HTTPException) as e:
        await _route(router, "/api/skills/{skill_id}/test-diff", "POST")(
            _request(OWNER, {}), "fresh")
    assert e.value.status_code == 400
    assert "no earlier copy" in e.value.detail
    assert "kept automatically" in e.value.detail


@pytest.mark.asyncio
async def test_the_versions_route_serves_the_history_p8_10_already_keeps(wired):
    out = await _route(wired["router"], "/api/skills/{skill_id}/versions", "GET")(
        _request(OWNER, method="GET"), "packer")
    assert out["ok"] is True
    assert [v["id"] for v in out["versions"]] == ["0001-1.0.0"]


@pytest.mark.asyncio
async def test_the_two_halves_run_in_order_against_one_task(wired, monkeypatch):
    """Driven end to end: the before half runs the text that is no longer on
    disk, the after half is queued behind it and starts when it finishes, and
    the diff comes back on one `/test-status` call."""
    seen = []

    async def fake_loop(url, model, messages, **kw):
        # messages[1] is the untrusted skill-under-test block.
        seen.append(messages[1]["content"])
        yield "data: " + json.dumps({"type": "tool_start", "tool": "bash",
                                     "round": 1})
        yield "data: " + json.dumps({"type": "tool_output", "output": "ok",
                                     "round": 1})
        yield "data: [DONE]"

    monkeypatch.setattr("src.agent_loop.stream_agent_loop", fake_loop)

    async def fake_eval(md, task, text, url, model, headers):
        return {"verdict": "pass" if "step 2" in md else "needs_work",
                "confidence": 0.9, "summary": "judged", "issues": []}

    monkeypatch.setattr(skills_routes, "_eval_skill_run", fake_eval)

    start = await _route(wired["router"], "/api/skills/{skill_id}/test-diff", "POST")(
        _request(OWNER, {"task": "pack a box"}), "packer")
    assert start["same_text"] is False
    assert start["before_source"] == "earlier copy 0001-1.0.0"

    for _ in range(40):
        await asyncio.sleep(0)
        st = await _route(wired["router"], "/api/skills/{skill_id}/test-status", "GET")(
            _request(OWNER, method="GET"), "packer")
        if st.get("diff", {}).get("both_finished"):
            break
    d = st["diff"]

    assert d["both_finished"] is True
    assert d["task"] == "pack a box"
    assert d["before_verdict"] == "needs_work"
    assert d["after_verdict"] == "pass"
    assert d["verdict_changed"] is True
    assert d["before_tools"] == ["bash"] and d["after_tools"] == ["bash"]
    # Both halves saw the same task, and DIFFERENT markdown — the before half
    # ran the copy on disk before the edit.
    assert len(seen) == 2
    assert "step 2 — be specific" not in seen[0]
    assert "step 2 — be specific" in seen[1]


@pytest.mark.asyncio
async def test_the_before_half_does_not_record_a_verdict_against_the_skill(
        wired, monkeypatch):
    """The before half runs text that is no longer on disk. Writing its verdict
    onto the skill would make "what did my edit change?" change the thing it is
    asking about."""
    async def fake_loop(*a, **k):
        yield "data: [DONE]"

    monkeypatch.setattr("src.agent_loop.stream_agent_loop", fake_loop)

    async def fake_eval(md, task, text, url, model, headers):
        return {"verdict": "fail" if "step 2" not in md else "pass",
                "confidence": 0.9, "summary": "judged", "issues": []}

    monkeypatch.setattr(skills_routes, "_eval_skill_run", fake_eval)
    recorded = []
    monkeypatch.setattr(wired["sm"], "set_audit",
                        lambda name, v, **kw: recorded.append(v))

    await _route(wired["router"], "/api/skills/{skill_id}/test-diff", "POST")(
        _request(OWNER, {"task": "t"}), "packer")
    for _ in range(40):
        await asyncio.sleep(0)
        st = await _route(wired["router"], "/api/skills/{skill_id}/test-status", "GET")(
            _request(OWNER, method="GET"), "packer")
        if st.get("diff", {}).get("both_finished"):
            break

    # Only the after half's verdict reached the skill.
    assert recorded == ["pass"]


@pytest.mark.asyncio
async def test_both_halves_are_kept_so_the_comparison_survives_being_read(
        wired, monkeypatch):
    """`B879` in the shape `P8-09` needs it: two runs of ONE skill, both still
    there when the panel asks."""
    async def fake_loop(*a, **k):
        yield "data: [DONE]"

    monkeypatch.setattr("src.agent_loop.stream_agent_loop", fake_loop)

    async def fake_eval(*a, **k):
        return {"verdict": "pass", "confidence": 0.9, "summary": "", "issues": []}

    monkeypatch.setattr(skills_routes, "_eval_skill_run", fake_eval)

    start = await _route(wired["router"], "/api/skills/{skill_id}/test-diff", "POST")(
        _request(OWNER, {"task": "t"}), "packer")
    for _ in range(40):
        await asyncio.sleep(0)
        st = await _route(wired["router"], "/api/skills/{skill_id}/test-status", "GET")(
            _request(OWNER, method="GET"), "packer")
        if st.get("diff", {}).get("both_finished"):
            break

    key = (OWNER, "packer")
    runs = skills_routes._skill_test_runs(key)
    assert [r["label"] for r in runs] == ["before", "after"]
    assert runs[0]["run_id"] == start["before_run"]
    assert runs[1]["run_id"] == start["after_run"]
    assert all(r["status"] == "done" for r in runs)
    # Either half is readable on its own.
    one = await _route(wired["router"], "/api/skills/{skill_id}/test-status", "GET")(
        _request(OWNER, method="GET"), "packer", run=start["before_run"])
    assert one["label"] == "before"
    assert one["source_label"] == "earlier copy 0001-1.0.0"


@pytest.mark.asyncio
async def test_a_lapsed_approval_ends_its_half_instead_of_stalling_the_pair(
        wired, monkeypatch):
    """The approval store retires an unanswered card on its own TTL (`P12-10`
    records it as `denied_timeout`). Before this, the run stayed
    `awaiting_approval` for the life of the process — and a comparison whose
    first half lapsed left its second half `queued` forever."""
    approval = {"kind": "tool_approval", "approval_id": "appr-lapsed"}

    async def gated_loop(*a, **k):
        yield "data: " + json.dumps({
            "type": "tool_output", "tool": "bash", "output": "wait",
            "ask_user": approval, "round": 1,
        })

    monkeypatch.setattr("src.agent_loop.stream_agent_loop", gated_loop)

    start = await _route(wired["router"], "/api/skills/{skill_id}/test-diff", "POST")(
        _request(OWNER, {"task": "t"}), "packer")
    for _ in range(20):
        await asyncio.sleep(0)
    key = (OWNER, "packer")
    before = skills_routes._skill_test_run(key, start["before_run"])
    after = skills_routes._skill_test_run(key, start["after_run"])
    assert before["status"] == "awaiting_approval"
    assert after["status"] == "queued"

    # The card is gone from the store — nobody answered it in time.
    class Lapsed:
        def peek(self, _id):
            return None

    monkeypatch.setattr("src.tool_approvals.tool_approval_store", Lapsed())

    async def quiet_loop(*a, **k):
        yield "data: [DONE]"

    monkeypatch.setattr("src.agent_loop.stream_agent_loop", quiet_loop)

    async def fake_eval(*a, **k):
        return {"verdict": "pass", "confidence": 0.9, "summary": "", "issues": []}

    monkeypatch.setattr(skills_routes, "_eval_skill_run", fake_eval)

    with pytest.raises(HTTPException) as e:
        await _route(wired["router"], "/api/skills/{skill_id}/test-approval", "POST")(
            _request(OWNER, {"approval_id": "appr-lapsed", "decision": "approve"}),
            "packer")
    assert e.value.status_code == 409
    for _ in range(40):
        await asyncio.sleep(0)
        if after["status"] == "done":
            break

    assert before["status"] == "done"
    assert before["verdict"]["verdict"] == "inconclusive"
    assert "not approved in time" in before["verdict"]["summary"]
    # And the half that was queued behind it actually ran.
    assert after["status"] == "done"
