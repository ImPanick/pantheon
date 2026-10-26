# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1415` — a truncated `update_plan` is sent back, and a tick with no work is checked.

Measured from the owner's transcript: an eleven-step plan was rewritten by a
model whose output ran out mid-line — the plan text ends `  - Card` — and
`update_plan` took it as a full replacement: "0 of 11 done" became "Plan
updated (4/6 steps complete)", five approved steps gone, no event, no warning.
The same turn ticked six steps with no effectful call, and the completion
verifier, gated on `_effectful_used`, skipped exactly that turn.

Now the loop hands the tool the plan the turn holds, and a write with fewer
steps than it is answered in-band — unless the call names the steps it drops —
so the model resends; and a turn that ticks steps having run nothing effectful
is verified. Driven: the real tool, and the real loop with a scripted model.
"""
import asyncio
import json

import pytest

import src.agent_tools  # noqa: F401  (break the agent_tools <-> tool_parsing import cycle)
from src.active_plan import ActivePlan, bind_active_plan
from src.agent_tools.interaction_tools import UpdatePlanTool

ELEVEN = "\n".join(f"- [ ] Step {i}: card {i}" for i in range(1, 12))
CUT_OFF = ("- [x] Step 1: card 1\n- [x] Step 2: card 2\n- [x] Step 3: card 3\n"
           "- [x] Step 4: card 4\n- [ ] Step 5: card 5\n- [ ] Step 6: card 6\n  - Card")


def _update(content, holder):
    async def go():
        bind_active_plan(holder)
        return await UpdatePlanTool().execute(content, {})
    return asyncio.run(go())


def test_a_write_that_would_delete_steps_is_refused_in_band():
    holder = ActivePlan(ELEVEN)

    _desc, result = _update(json.dumps({"plan": CUT_OFF}), holder)

    assert result["exit_code"] == 1 and "plan_update" not in result
    assert result["error"].startswith(
        "update_plan was not applied: the plan has 11 steps and this checklist has 6, "
        "so 5 would be deleted")
    assert "it ends “- Card”" in result["error"]
    assert holder.plan == ELEVEN


def test_a_cut_off_call_whose_json_never_closed_is_refused_too():
    holder = ActivePlan(ELEVEN)
    _desc, result = _update('{"plan": "' + CUT_OFF.replace("\n", "\\n"), holder)
    assert result["exit_code"] == 1 and "plan_update" not in result


def test_dropping_steps_the_person_asked_to_drop_is_named_and_applied():
    holder = ActivePlan(ELEVEN)
    kept = "\n".join(ELEVEN.splitlines()[:9])
    _desc, result = _update(json.dumps({"plan": kept, "removing_steps": [
        "Step 10: card 10", "Step 11: card 11"]}), holder)
    assert result["exit_code"] == 0 and result["plan_update"] == {"plan": kept}
    assert holder.plan == kept


def test_the_complete_checklist_with_ticks_is_applied_and_counts_its_ticks():
    holder = ActivePlan(ELEVEN)
    ticked = ELEVEN.replace("- [ ] Step 1:", "- [x] Step 1:").replace("- [ ] Step 2:", "- [x] Step 2:")
    _desc, result = _update(json.dumps({"plan": ticked}), holder)
    assert result["exit_code"] == 0 and result["plan_ticked"] == 2
    assert result["output"] == "Plan updated (2/11 steps complete)."
    assert holder.plan == ticked


def test_with_no_plan_held_the_tool_is_unchanged():
    _desc, result = _update(json.dumps({"plan": CUT_OFF}), None)
    assert result["exit_code"] == 0 and result["plan_update"] == {"plan": CUT_OFF}
    assert "plan_ticked" not in result


# ── Through the real agent loop ─────────────────────────────────────────────

def _drive(monkeypatch, rounds, *, verifier=False):
    import src.agent_loop as agent_loop

    monkeypatch.setattr(
        agent_loop, "get_setting",
        lambda key, default=None: (verifier if key == "agent_verifier_subagent"
                                   else "gate_on_untrusted" if key == "trust_rung" else default),
        raising=False,
    )
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: None, raising=False)
    monkeypatch.setattr(agent_loop, "estimate_tokens", lambda *a, **k: 10)
    monkeypatch.setattr(agent_loop, "blocked_tools_for_owner", lambda owner: set(), raising=False)
    scripted = iter(rounds)

    async def fake_stream(*args, **kwargs):
        yield f"data: {json.dumps({'delta': next(scripted, 'Done.')})}\n\n"
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", fake_stream)
    verdicts = []

    async def fake_verifier(instruction, snapshot, **kwargs):
        verdicts.append(instruction)
        return agent_loop.VerifierVerdict("pass")

    monkeypatch.setattr(agent_loop, "_run_verifier_subagent", fake_verifier)

    async def collect():
        return [chunk async for chunk in agent_loop.stream_agent_loop(
            "http://local.test/v1", "small-local-model",
            [{"role": "user", "content": "Execute the approved plan."}],
            max_rounds=len(rounds) + 1, relevant_tools={"update_plan"}, owner="alice",
            session_id="b1415", approved_plan=ELEVEN)]

    events = []
    for chunk in asyncio.run(collect()):
        if chunk.startswith("data: ") and not chunk.startswith("data: [DONE]"):
            try:
                events.append(json.loads(chunk[6:]))
            except json.JSONDecodeError:
                pass
    return events, verdicts


def _call(plan):
    return "```update_plan\n" + json.dumps({"plan": plan}) + "\n```"


def test_through_the_loop_the_window_keeps_eleven_steps_and_the_resend_lands(monkeypatch):
    complete = ELEVEN.replace("- [ ] Step 1:", "- [x] Step 1:")
    events, _ = _drive(monkeypatch, [_call(CUT_OFF), _call(complete), "Done."])

    updates = [e["data"]["plan"] for e in events if e.get("type") == "plan_update"]
    assert updates == [complete], "the cut-off plan reached the window"
    refused = [e for e in events if e.get("type") == "tool_output" and e.get("tool") == "update_plan"]
    assert "was not applied" in str(refused[0].get("output") or refused[0])


def test_a_turn_that_ticks_steps_having_run_nothing_effectful_is_verified(monkeypatch):
    ticked = ELEVEN.replace("- [ ] Step 1:", "- [x] Step 1:").replace("- [ ] Step 2:", "- [x] Step 2:")
    _events, verdicts = _drive(monkeypatch, [_call(ticked), "All done."], verifier=True)
    assert len(verdicts) == 1
    assert "Approved plan:" in verdicts[0]


def test_a_turn_that_only_reads_the_plan_back_is_not(monkeypatch):
    _events, verdicts = _drive(monkeypatch, [_call(ELEVEN), "Nothing done yet."], verifier=True)
    assert verdicts == []
