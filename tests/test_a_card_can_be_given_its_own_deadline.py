# SPDX-License-Identifier: AGPL-3.0-or-later
"""`D-2026-10-02-01` §1 — a workflow step's question waits twelve hours.

One deadline governed every card (`approval_timeout_seconds`, 10 minutes by
default), so an overnight workflow's question lapsed long before morning. The
owner's call: a workflow card waits `workflow_approval_timeout_seconds`
(wf-walker's setting, default 12 h); the store's `create` takes an optional
`ttl_seconds`, **clamped to the store's own bounds**, and `stream_agent_loop`
passes one through. Chat cards keep their deadline. The TTL, the seal, single
use and owner binding are `FORBIDDEN.md` Part 2's and do not move — the
clamp is what keeps a caller from naming a card that never lapses.

Driven for real (`Law 20`): the store's own `create`/`consume`, and the agent
loop minting a card from a tainted run with a scripted model.
"""
import asyncio
import json

import pytest

from src.tool_approvals import (
    MAX_APPROVAL_TTL_SECONDS,
    MIN_APPROVAL_TTL_SECONDS,
    ToolApprovalStore,
)
from src.tool_capabilities import capabilities_for_action

TWELVE_HOURS = 12 * 60 * 60


def _mint(store, **kw):
    return store.create(owner="alice", session_id="", origin_run_id="run-1:reply:",
                        tool_name="bash", content="echo hi", workspace=None,
                        external_untrusted_context_seen=True,
                        capabilities=capabilities_for_action("bash", "echo hi"), **kw)


def _ttl(pending):
    return round(pending.expires_at - pending.created_at)


def test_a_card_waits_as_long_as_its_caller_says():
    store = ToolApprovalStore(ttl_seconds=600)
    assert _ttl(_mint(store)) == 600                                   # Law 1: chat cards
    assert _ttl(_mint(store, ttl_seconds=TWELVE_HOURS)) == TWELVE_HOURS
    assert _mint(store, ttl_seconds=TWELVE_HOURS).public_payload()["ttl_seconds"] == TWELVE_HOURS


@pytest.mark.parametrize("asked,expected", [
    (0, MIN_APPROVAL_TTL_SECONDS),                  # never "never expires"
    (-5, MIN_APPROVAL_TTL_SECONDS),
    (5, MIN_APPROVAL_TTL_SECONDS),
    (10 ** 9, MAX_APPROVAL_TTL_SECONDS),            # not a week, not forever
    (MAX_APPROVAL_TTL_SECONDS + 1, MAX_APPROVAL_TTL_SECONDS),
    ("7200", 7200),
])
def test_a_deadline_is_clamped_to_the_stores_bounds(asked, expected):
    assert _ttl(_mint(ToolApprovalStore(ttl_seconds=600), ttl_seconds=asked)) == expected


@pytest.mark.parametrize("asked", [None, True, False, "soon", float("inf"), float("nan"), [3600]])
def test_anything_that_is_not_a_number_is_the_stores_deadline(asked):
    assert _ttl(_mint(ToolApprovalStore(ttl_seconds=600), ttl_seconds=asked)) == 600


def test_a_long_deadline_changes_nothing_else_about_the_card():
    store = ToolApprovalStore(ttl_seconds=600)
    pending = _mint(store, ttl_seconds=TWELVE_HOURS)
    outcome = {}
    assert store.consume(pending.approval_id, decision="approve_task", owner="mallory",
                         session_id="", allow_continuation=False, outcome=outcome) is None
    assert outcome["reason"] == "not_yours"
    assert store.peek(pending.approval_id) is not None                # still waiting for alice
    granted = store.consume(pending.approval_id, decision="approve_task", owner="alice",
                            session_id="", allow_continuation=False)
    assert granted is not None and granted.allow_remaining_actions is False
    assert store.consume(pending.approval_id, decision="approve_task", owner="alice",
                         session_id="") is None                         # single use
    # The seal: it answers for exactly the content it was minted for.
    assert granted.claim(owner="alice", session_id="", tool_name="bash",
                         content="echo something else", workspace=None) is False
    assert granted.claim(owner="alice", session_id="", tool_name="bash",
                         content="echo hi", workspace=None) is True


# ── the loop passes it through ────────────────────────────────────────────────

def _card_from_a_tainted_run(monkeypatch, **loop_kwargs):
    import src.agent_loop as al

    monkeypatch.setattr(al, "get_setting", lambda key, default=None: default, raising=False)
    monkeypatch.setattr(al, "get_mcp_manager", lambda: None, raising=False)
    monkeypatch.setattr(al, "estimate_tokens", lambda *a, **k: 10)
    monkeypatch.setattr(al, "blocked_tools_for_owner", lambda owner: set(), raising=False)

    async def scripted(*args, **kwargs):
        yield "data: " + json.dumps({"delta": "```bash\necho from the model\n```"}) + "\n\n"
        yield "data: [DONE]\n\n"

    async def must_not_run(block, *a, **k):
        raise AssertionError(f"{block.tool_type} ran without a yes")

    monkeypatch.setattr(al, "stream_llm_with_fallback", scripted)
    monkeypatch.setattr(al, "execute_tool_block", must_not_run)

    async def collect():
        return [c async for c in al.stream_agent_loop(
            "http://local.test/v1", "scripted", [{"role": "user", "content": "reply to it"}],
            max_rounds=1, relevant_tools={"bash"}, owner="alice",
            external_untrusted_context_seen=True, **loop_kwargs)]

    events = [json.loads(c[6:]) for c in asyncio.run(collect())
              if c.startswith("data: ") and not c.startswith("data: [DONE]")]
    cards = [e["ask_user"] for e in events
             if e.get("type") == "tool_output" and e.get("ask_user", {}).get("kind") == "tool_approval"]
    assert len(cards) == 1, events
    return cards[0]


def test_a_run_given_a_deadline_mints_its_card_with_it(monkeypatch):
    card = _card_from_a_tainted_run(monkeypatch, approval_ttl_seconds=TWELVE_HOURS)
    assert card["ttl_seconds"] == TWELVE_HOURS


def test_a_run_given_none_keeps_the_operators_deadline(monkeypatch):
    from src.tool_approvals import tool_approval_store
    card = _card_from_a_tainted_run(monkeypatch)
    assert card["ttl_seconds"] == tool_approval_store.ttl_seconds("alice")


def test_a_run_cannot_name_a_deadline_past_the_bounds(monkeypatch):
    assert _card_from_a_tainted_run(monkeypatch, approval_ttl_seconds=1)["ttl_seconds"] \
        == MIN_APPROVAL_TTL_SECONDS
