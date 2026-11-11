# SPDX-License-Identifier: AGPL-3.0-or-later
"""Two text-channel tool-call parsing faults.

* `[TOOL_CALL]` read `command: "…"` lazily to the first quote of either kind, so
  `rm -rf ./dist/'old build'` ran as `rm -rf ./dist/`: a wider delete than asked.
* The Hermes, `<invoke>` and bare-JSON readers lowercased every name, so a
  camelCase MCP tool (`getJiraIssue`) was unreachable on those channels and
  slipped past denylists that hold the name as written.
"""
import pytest

import src.agent_tools  # noqa: F401  (registers the tool tags)
from src.tool_parsing import parse_tool_blocks


@pytest.mark.parametrize("text, command", [
    ("[TOOL_CALL]{tool: \"shell\", command: \"rm -rf ./dist/'old build'\"}[/TOOL_CALL]",
     "rm -rf ./dist/'old build'"),
    ("[TOOL_CALL]{tool => \"shell\", args => {--command \"grep -r 'TODO' src | wc -l\"}}[/TOOL_CALL]",
     "grep -r 'TODO' src | wc -l"),
    ('[TOOL_CALL]{tool: "shell", command: "echo \\"hi\\""}[/TOOL_CALL]', 'echo "hi"'),
])
def test_a_tool_call_command_runs_to_its_own_closing_quote(text, command):
    (block,) = parse_tool_blocks(text)
    assert block.content == command


@pytest.mark.parametrize("text", [
    '<tool_call>{"name": "mcp__ab12cd34__getUser", "arguments": {}}</tool_call>',
    '<tool_call><invoke name="mcp__ab12cd34__getUser"></invoke></tool_call>',
    '{"name": "mcp__ab12cd34__getUser", "arguments": {}}',
])
def test_an_mcp_tool_name_keeps_its_case(text):
    (block,) = parse_tool_blocks(text)
    assert block.tool_type == "mcp__ab12cd34__getUser"


def test_a_builtin_name_is_still_read_case_insensitively():
    (block,) = parse_tool_blocks('<tool_call><invoke name="Bash"><parameter name="command">ls</parameter></invoke></tool_call>')
    assert block.tool_type == "bash"
