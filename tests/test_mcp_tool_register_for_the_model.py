# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B867` — the register the model reads was narrower than the one we hold.

MEASURED ON THE TREE BEFORE THE CHANGE by calling the tool, not by reading it.
`do_manage_mcp('{"action":"list_tools"}')` against a manager holding one tool
with a two-property schema and `readOnlyHint: true` returned exactly:

    {"response": "1 MCP tools available",
     "tools": [{"name": "read_file", "server": "Files",
                "description": "Read a file from disk and return the conte…"}],
     "exit_code": 0}

Three things are missing from that and each one is the difference between
listing a tool and being able to use it:

  * `mcp__srv1__read_file` — the name the model has to emit to call it. Not
    present in any form, so a model that found a tool here still could not.
  * the parameters. `input_schema` is carried the whole way to
    `src/agent_tools/admin_tools.py:360-367` by `McpManager.get_all_tools`
    (`src/mcp_manager.py:606-622` at `HEAD`) and was dropped by the projection.
  * `readOnlyHint` — which was not even available to drop, because
    `get_all_tools` never copied `annotations` onto its entries at all. That is
    the same missing line `P8-48`'s annotation UI was blocked on.

These cases DRIVE `do_manage_mcp` and `McpManager` (`Law 20`).
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

from src.mcp_manager import (  # noqa: E402
    McpManager,
    _MCP_PARAM_MAX,
    _format_mcp_params,
    summarize_tool_parameters,
)

READ_FILE_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "Absolute path to read"},
        "encoding": {"type": "string", "enum": ["utf8", "latin1", "ascii"]},
    },
    "required": ["path"],
}


def _manager():
    manager = McpManager()
    manager._tools["srv1"] = [
        {
            "name": "read_file",
            "description": "Read a file from disk and return the contents. " + "x" * 400,
            "input_schema": READ_FILE_SCHEMA,
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "write_file",
            "description": "Write a file",
            "input_schema": {"type": "object",
                             "properties": {"path": {"type": "string"}},
                             "required": ["path"]},
            "annotations": {"readOnlyHint": False, "destructiveHint": True},
        },
    ]
    manager._tools["srv2"] = [
        {"name": "ping", "description": "Ping", "input_schema": {}, "annotations": None},
    ]
    manager._connections["srv1"] = {"status": "connected", "name": "Files"}
    manager._connections["srv2"] = {"status": "connected", "name": "Net"}
    return manager


def _list_tools(manager, **extra):
    import src.agent_tools.admin_tools as admin_tools
    from src.agent_tools.admin_tools import do_manage_mcp

    real = admin_tools.get_mcp_manager
    admin_tools.get_mcp_manager = lambda: manager
    try:
        return asyncio.run(do_manage_mcp(json.dumps({"action": "list_tools", **extra})))
    finally:
        admin_tools.get_mcp_manager = real


@pytest.fixture()
def listed():
    manager = _manager()
    return manager, _list_tools(manager)


def test_the_model_is_given_the_name_it_must_actually_call(listed):
    """The whole point. A tool it cannot name is a tool it cannot use."""
    _, out = listed
    by_name = {t["name"]: t for t in out["tools"]}

    assert by_name["read_file"]["qualified_name"] == "mcp__srv1__read_file"
    assert by_name["ping"]["qualified_name"] == "mcp__srv2__ping"
    assert by_name["read_file"]["server_id"] == "srv1"


def test_the_qualified_name_it_is_given_is_the_one_call_tool_accepts(listed):
    """Round trip, so the two cannot drift into different spellings."""
    manager, out = listed
    qualified = [t["qualified_name"] for t in out["tools"]]

    seen = {}

    class _Session:
        def __init__(self, sid):
            self.sid = sid

        async def call_tool(self, name, arguments, **kw):
            seen[self.sid] = name
            raise RuntimeError("stop here — routing is what is under test")

    manager._sessions = {"srv1": _Session("srv1"), "srv2": _Session("srv2")}
    for name in qualified:
        result = asyncio.run(manager.call_tool(name, {}))
        assert "not connected" not in result.get("error", ""), name

    assert seen == {"srv1": "write_file", "srv2": "ping"}


def test_the_parameters_are_there_and_they_are_the_ones_the_prompt_shows(listed):
    """`input_schema` reached this line and was thrown away. It arrives now.

    The second assertion is the `Law 14` one: `manage_mcp list_tools` and the
    system prompt's argument hint are two renderings of ONE read, so a tool
    cannot be described one way to the model in its prompt and another way in
    the answer to its own tool call.
    """
    _, out = listed
    read_file = [t for t in out["tools"] if t["name"] == "read_file"][0]

    assert read_file["parameters"] == [
        {"name": "path", "type": "string", "required": True,
         "description": "Absolute path to read"},
        {"name": "encoding", "type": "string", "required": False,
         "enum": ["utf8", "latin1", "ascii"]},
    ]
    hint = _format_mcp_params(READ_FILE_SCHEMA)
    for param in read_file["parameters"]:
        assert f'"{param["name"]}"' in hint
    assert "(required)" in hint.split('"encoding"')[0]


def test_the_read_only_verdict_travels_with_the_tool(listed):
    """`annotations` was never on the payload at all — this is `P8-48`'s blocker."""
    _, out = listed
    by_name = {t["name"]: t for t in out["tools"]}

    assert by_name["read_file"]["read_only"] is True
    assert by_name["read_file"]["annotations"] == {"readOnlyHint": True}
    assert by_name["write_file"]["read_only"] is False
    assert by_name["write_file"]["annotations"]["destructiveHint"] is True
    # A server that advertises nothing still gets a verdict and claims no hint.
    assert by_name["ping"]["read_only"] is False
    assert "annotations" not in by_name["ping"]


def test_a_truncated_description_says_that_it_is_truncated(listed):
    """It was cut at 100 with no marker, so half a sentence read as a whole one."""
    _, out = listed
    read_file = [t for t in out["tools"] if t["name"] == "read_file"][0]

    assert read_file["description"].endswith("…")
    assert read_file["description"].startswith(
        "Read a file from disk and return the contents."
    )
    assert [t for t in out["tools"] if t["name"] == "ping"][0]["description"] == "Ping"


def test_the_listing_can_be_narrowed_and_says_so():
    """A model with 200 tools needs a way down, and has to be told there is one."""
    manager = _manager()
    everything = _list_tools(manager)
    assert "pass server_id or tool to narrow this list" in everything["response"]
    assert len(everything["tools"]) == 3

    by_id = _list_tools(manager, server_id="srv1")
    assert [t["name"] for t in by_id["tools"]] == ["read_file", "write_file"]
    assert by_id["response"] == "2 of 3 MCP tools match"

    by_name = _list_tools(manager, server_id="Net")
    assert [t["name"] for t in by_name["tools"]] == ["ping"]

    one = _list_tools(manager, tool="mcp__srv1__read_file")
    assert len(one["tools"]) == 1 and one["tools"][0]["name"] == "read_file"


def test_a_hostile_schema_cannot_run_away_with_the_answer():
    """Third-party input. The cap and the sanitizer are the manager's, reused."""
    manager = _manager()
    manager._tools["srv1"] = [{
        "name": "wide",
        "description": "",
        "input_schema": {
            "type": "object",
            "properties": {f"p{i}": {"type": "string"} for i in range(40)},
        },
        "annotations": None,
    }]
    out = _list_tools(manager, server_id="srv1")
    tool = out["tools"][0]

    assert len(tool["parameters"]) == _MCP_PARAM_MAX
    assert tool["parameters_omitted"] == 40 - _MCP_PARAM_MAX

    newline = summarize_tool_parameters(
        {"type": "object", "properties": {"a\nb": {"type": "str\ning"}}}
    )["parameters"][0]
    assert "\n" not in newline["name"] and "\n" not in newline["type"]


def test_a_disabled_tool_is_listed_as_disabled():
    manager = _manager()
    manager._tools["srv1"][1]["name"] = "write_file"
    out = _list_tools(manager)
    assert all("disabled" not in t for t in out["tools"])

    entries = manager.get_all_tools({"srv1": {"write_file"}})
    assert [e["is_disabled"] for e in entries if e["name"] == "write_file"] == [True]
