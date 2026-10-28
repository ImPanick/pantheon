# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P24-27` — a run report counts a memory search as a read.

A hired run's report sorts the tools it used into *Read with* and *Wrote
with*, by what each call did (`runtime._effect_bucket`). It looked at a call's
arguments only when they were JSON — and `manage_memory`, `manage_session` and
`network` reach the step log in their line form (`search\\nAna`, `list`), so
every memory search was counted by the tool's widest reach: Gift & Date
Keeper's report, and its sample, said it *wrote* memory when it had only
searched it, and Memory Auditor — whose whole promise is that it changes
nothing — reported "wrote: manage_memory" for one listing. The gate's own
classifier (`capabilities_for_action`) reads the line form; the report now
asks it the same question the gate asked.
"""

from __future__ import annotations

from src.agents import runtime as R


def _step(tool, detail, status="ok"):
    return {"kind": "tool", "tool": tool, "detail": detail, "status": status}


def test_a_memory_listing_or_search_is_a_read():
    rep = R.build_report("x", [_step("manage_memory", "list"), _step("manage_memory", "search\nAna")])
    assert rep["read"] == ["manage_memory"] and rep["wrote"] == [], rep


def test_a_memory_added_edited_or_deleted_is_a_write():
    for detail in ("add\nAna likes tea", "edit\nab12cd34\nAna likes coffee", "delete\nab12cd34"):
        rep = R.build_report("x", [_step("manage_memory", detail)])
        assert rep["wrote"] == ["manage_memory"] and rep["read"] == [], (detail, rep)


def test_the_json_form_is_read_as_before():
    rep = R.build_report("x", [_step("manage_notes", '{"action": "search", "query": "Ana"}'),
                               _step("manage_calendar", '{"action": "create_event", "title": "x"}')])
    assert rep["read"] == ["manage_notes"] and rep["wrote"] == ["manage_calendar"], rep


def test_a_tool_with_no_action_is_read_by_its_reach():
    rep = R.build_report("x", [_step("bash", "df -P /"), _step("ls", "")])
    assert rep["wrote"] == ["bash"] and rep["read"] == ["ls"], rep
