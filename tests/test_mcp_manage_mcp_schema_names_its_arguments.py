# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B871` — the schema has to name the arguments the tool honours.

`check-tool-surface.py` pins the rule one level up: a tool NAME has to be in
every register. This is the same rule at the argument. `B867` gave
`manage_mcp list_tools` a `server_id` narrowing and a `tool` filter and neither
register named them:

    FUNCTION_TOOL_SCHEMAS["manage_mcp"] properties, at HEAD
      (src/tool_schemas.py:826-831)
        action, server_id, name, command, args, env
      — `tool` absent; `server_id`'s description read
        "Server ID (for delete/enable/disable/reconnect)", naming four actions
        and not `list_tools`.

    src/agent_loop.py:1031, the XML path's copy
        {"action": "list|add|delete|reconnect|list_tools", ...}
      — no filters, and `enable` and `disable` missing from the action list too,
        though the tool has honoured both since before `B867`.

So the capability existed and was undiscoverable, and the only thing teaching it
was `list_tools`' own response text ("pass server_id or tool to narrow this
list") — a workaround standing in for the register.

These cases DISCOVER what the tool honours by CALLING it and then hold the
registers to that (`Law 20`). Nothing here reads a schema to decide what the
tool does.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.agent_loop import TOOL_SECTIONS  # noqa: E402
from src.mcp_manager import McpManager  # noqa: E402
from src.tool_schemas import FUNCTION_TOOL_SCHEMAS  # noqa: E402

# Names a model might plausibly reach for. The honoured ones are found by
# driving, not by reading the schema — that is the whole point of the file.
CANDIDATE_ARGS = {
    "server_id": "srv1",
    "tool": "ping",
    "server": "srv1",
    "server_name": "Files",
    "filter": "ping",
    "query": "ping",
    "search": "ping",
    "name": "ping",
}


def _schema() -> dict:
    for entry in FUNCTION_TOOL_SCHEMAS:
        if entry["function"]["name"] == "manage_mcp":
            return entry["function"]
    raise AssertionError("manage_mcp has no function schema")


def _manager() -> McpManager:
    manager = McpManager()
    manager._tools["srv1"] = [
        {"name": "read_file", "description": "Read", "input_schema": {},
         "annotations": None},
        {"name": "write_file", "description": "Write", "input_schema": {},
         "annotations": None},
    ]
    manager._tools["srv2"] = [
        {"name": "ping", "description": "Ping", "input_schema": {},
         "annotations": None},
    ]
    manager._connections["srv1"] = {"status": "connected", "name": "Files"}
    manager._connections["srv2"] = {"status": "connected", "name": "Net"}
    return manager


def _call(manager, **payload) -> dict:
    import src.agent_tools.admin_tools as admin_tools
    from src.agent_tools.admin_tools import do_manage_mcp

    real = admin_tools.get_mcp_manager
    admin_tools.get_mcp_manager = lambda: manager
    try:
        return asyncio.run(do_manage_mcp(json.dumps(payload)))
    finally:
        admin_tools.get_mcp_manager = real


def _honoured_list_tools_args() -> set[str]:
    """Drive `list_tools` once per candidate; keep the ones that change it."""
    manager = _manager()
    baseline = [t["qualified_name"] for t in _call(manager, action="list_tools")["tools"]]
    assert len(baseline) == 3, baseline
    honoured = set()
    for arg, value in CANDIDATE_ARGS.items():
        got = _call(manager, action="list_tools", **{arg: value})
        if [t["qualified_name"] for t in got["tools"]] != baseline:
            honoured.add(arg)
    return honoured


def _honoured_actions(names) -> set[str]:
    """An action the tool does not know answers `Unknown action: <x>`."""
    manager = _manager()
    honoured = set()
    for action in names:
        got = _call(manager, action=action)
        if not str(got.get("error", "")).startswith("Unknown action"):
            honoured.add(action)
    return honoured


def test_the_probe_can_tell_an_honoured_argument_from_an_ignored_one():
    """Without this, every assertion below is vacuously true."""
    honoured = _honoured_list_tools_args()
    assert honoured == {"server_id", "tool"}, honoured
    assert _honoured_actions(["definitely_not_an_action"]) == set()


def test_every_argument_list_tools_honours_is_in_the_function_schema():
    """The register the function channel reads."""
    declared = set(_schema()["parameters"]["properties"])
    missing = _honoured_list_tools_args() - declared
    assert missing == set(), f"honoured but undeclared: {sorted(missing)}"


def test_every_argument_list_tools_honours_is_in_the_xml_register():
    """The register the fenced channel reads — one line, same rule."""
    line = TOOL_SECTIONS["manage_mcp"]
    missing = {a for a in _honoured_list_tools_args() if a not in line}
    assert missing == set(), f"honoured but unannounced in the prompt: {sorted(missing)}"


def test_server_id_description_names_the_action_it_now_serves():
    """It named four actions and not the one `B867` gave it."""
    desc = _schema()["parameters"]["properties"]["server_id"]["description"]
    assert "list_tools" in desc, desc


def test_both_registers_offer_exactly_the_actions_the_tool_answers():
    """Neither register may promise an action the tool refuses, or hide one."""
    enum = set(_schema()["parameters"]["properties"]["action"]["enum"])
    line = TOOL_SECTIONS["manage_mcp"]
    announced = set(line.split('"action": "')[1].split('"')[0].split("|"))

    assert _honoured_actions(enum) == enum, "the schema enum promises a refused action"
    assert _honoured_actions(announced) == announced, "the prompt promises a refused action"
    assert enum == announced, f"registers disagree: {sorted(enum ^ announced)}"


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"server_id": "srv1"}, ["mcp__srv1__read_file", "mcp__srv1__write_file"]),
        ({"server_id": "Net"}, ["mcp__srv2__ping"]),
        ({"tool": "ping"}, ["mcp__srv2__ping"]),
        ({"tool": "mcp__srv1__read_file"}, ["mcp__srv1__read_file"]),
        ({"server_id": "srv1", "tool": "write_file"}, ["mcp__srv1__write_file"]),
        ({"server_id": "srv1", "tool": "ping"}, []),
    ],
)
def test_the_filters_do_what_the_schema_now_says_they_do(payload, expected):
    """Every promise the new schema text makes, driven."""
    got = _call(_manager(), action="list_tools", **payload)
    assert [t["qualified_name"] for t in got["tools"]] == expected
    assert got["response"].endswith("MCP tools match")
