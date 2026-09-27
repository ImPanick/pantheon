# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B899`. A paused scheduled task must explain itself from the card's own
state, not assert "after untrusted context" for every `tool_approval` card.

Since `P7-03` a strict rung mints an approval card in a run nothing tainted, and
since `P7-02` so does the assistant asking to widen its own reach. The old
summary blamed untrusted content on all of them (`Law 10`). The sentence is now
the card's own `description` — `P4-04`'s `default_reason()` (or the producer's
reason), already derived from whether the run was tainted (`Law 7`/`Law 14`).

Driven through the real `TaskScheduler._run_agent_loop` with a stubbed loop that
yields one real `public_payload` — the same harness the retirement test uses.
"""

from __future__ import annotations

import json

import pytest

from src.task_scheduler import TaskScheduler
from src.tool_approvals import tool_approval_store
from src.tool_capabilities import capabilities_for_action
from types import SimpleNamespace


def _make_task():
    return SimpleNamespace(
        crew_member_id=None, endpoint_url="http://ep/v1", model="m",
        session_id="s", owner="admin", prompt="run the digest",
        name="job", max_steps=5, character_id=None,
    )


async def _pause_summary(monkeypatch, *, tainted, reason=None):
    """Build a real card with the given taint, feed it through the real pause
    path, and return the scheduler's summary string."""
    pending = tool_approval_store.create(
        owner="admin",
        session_id="s",
        origin_run_id="scheduled-run",
        tool_name="bash",
        content="printf exact",
        workspace=None,
        external_untrusted_context_seen=tainted,
        capabilities=capabilities_for_action("bash", "printf exact"),
    )
    approval = pending.public_payload(reason=reason)

    async def fake_stream_agent_loop(*args, **kwargs):
        yield "data: " + json.dumps({
            "type": "tool_output",
            "tool": "bash",
            "output": "Waiting for an exact user approval.",
            "ask_user": approval,
        }) + "\n\n"

    monkeypatch.setattr("src.agent_loop.stream_agent_loop", fake_stream_agent_loop)
    monkeypatch.setattr("src.task_endpoint.resolve_task_candidates", lambda **kw: [])

    result = await TaskScheduler(session_manager=None)._run_agent_loop(
        "http://ep/v1", "model", _make_task(), "s",
    )
    # The card is retired either way (the pre-existing safety property).
    assert tool_approval_store.peek(pending.approval_id) is None
    return result


@pytest.mark.asyncio
async def test_clean_run_pause_does_not_blame_untrusted_content(monkeypatch):
    """A rung/self-escalation card in a run nothing tainted (`P7-03`/`P7-02`)."""
    result = await _pause_summary(monkeypatch, tainted=False)
    assert "paused safely" in result
    assert "That action was not executed" in result
    assert "untrusted" not in result.lower()
    # It still says a person must approve (the true reason it paused).
    assert "approve" in result.lower()


@pytest.mark.asyncio
async def test_a_self_escalation_card_carries_its_own_words(monkeypatch):
    """`P7-02` clean-run widening card: the producer's reason flows through and
    still names no untrusted content."""
    reason = (
        "The assistant wants to turn on Shell access. Only you can give it more "
        "access, so it asks every time — even after you have allowed other actions."
    )
    result = await _pause_summary(monkeypatch, tainted=False, reason=reason)
    assert "paused safely" in result
    assert "Shell access" in result
    assert "untrusted" not in result.lower()


@pytest.mark.asyncio
async def test_a_tainted_run_pause_still_says_untrusted_content(monkeypatch):
    """The property that used to be asserted for every card is kept for the one
    it is true of."""
    result = await _pause_summary(monkeypatch, tainted=True)
    assert "paused safely" in result
    assert "That action was not executed" in result
    assert "untrusted" in result.lower()
