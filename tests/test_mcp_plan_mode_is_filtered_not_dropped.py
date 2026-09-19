# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P8-41` — plan mode filters MCP; it has never dropped it.

The row is about two comments that say the opposite. A test that reads those
comments would be testing the file (`Law 20`), so this drives the code they
describe instead: `McpManager.plan_mode_blocked_mcp`, which is what
`src/agent_loop.py` calls in its `if plan_mode and mcp_mgr:` branch — a branch
that cannot run at all if the manager has been dropped.

RE-COUNTED 2026-09-19 by the same multiline proximity scan the row records,
across `src/`, `routes/`, `core/`, `services/`, `static/` and `docs/`. The
count is still **two**, and they are:

  1. `src/tool_security.py`, `plan_mode_disabled_tools`' docstring —
     *"the loop drops the MCP manager entirely in plan mode"*. Corrected.
  2. `routes/chat_routes.py:2046-2048`, above the `if plan_mode:` branch —
     *"(stream_agent_loop enforces this again + drops MCP, so this is
     belt-and-suspenders.)"*. NOT corrected here: that file is outside this
     agent's ownership.

A third hit reads similarly and is **accurate**, so it is recorded rather than
changed: `src/tool_security.py`'s `MCP_NAMESPACE_BLOCK_REASON` comment says the
advertisement path drops the manager entirely — that is the NON-ADMIN path
(`blocked_tools_for_owner` non-empty → `mcp_mgr = None`), a different question
with a different answer.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.mcp_manager import McpManager  # noqa: E402


def _manager_with(tools):
    mgr = McpManager()
    mgr._tools["abcd1234"] = list(tools)
    mgr._connections["abcd1234"] = {"status": "connected", "name": "Test"}
    return mgr


def test_a_readonly_tool_survives_plan_mode():
    """If MCP were dropped there would be nothing to survive."""
    mgr = _manager_with([
        {"name": "list_files", "description": "", "annotations": None},
        {"name": "delete_everything", "description": "", "annotations": None},
    ])
    blocked_map, qualified = mgr.plan_mode_blocked_mcp()

    assert "list_files" not in blocked_map.get("abcd1234", set())
    assert "mcp__abcd1234__list_files" not in qualified


def test_a_write_tool_is_blocked_in_both_spellings():
    """Hidden from the schemas by server+name, refused at runtime by qualified
    name — the two halves the corrected comment describes."""
    mgr = _manager_with([{"name": "delete_everything", "description": "", "annotations": None}])
    blocked_map, qualified = mgr.plan_mode_blocked_mcp()

    assert blocked_map["abcd1234"] == {"delete_everything"}
    assert qualified == {"mcp__abcd1234__delete_everything"}


def test_the_servers_own_annotation_wins_over_the_verb():
    """`readOnlyHint` is the first thing consulted, which is why a server that
    advertises itself properly gets credit a name heuristic would refuse."""
    mgr = _manager_with([
        {"name": "punch_card", "description": "", "annotations": {"readOnlyHint": True}},
        {"name": "list_secrets", "description": "", "annotations": {"readOnlyHint": False}},
    ])
    blocked_map, _q = mgr.plan_mode_blocked_mcp()

    assert "punch_card" not in blocked_map.get("abcd1234", set())
    assert "list_secrets" in blocked_map["abcd1234"]


def test_an_ambiguous_name_with_no_annotation_fails_closed():
    mgr = _manager_with([{"name": "process_batch", "description": "", "annotations": None}])
    blocked_map, _q = mgr.plan_mode_blocked_mcp()
    assert "process_batch" in blocked_map["abcd1234"]


def test_nothing_is_blocked_when_no_server_is_connected():
    assert McpManager().plan_mode_blocked_mcp() == ({}, set())
