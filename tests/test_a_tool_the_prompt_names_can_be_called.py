# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B66`. The system prompt told the agent to offload large tool results into
`manage_rag`, and every such call was dropped without a trace.

The name was in no tag set. `parse_tool_blocks` gates on `TOOL_TAGS`, so the
fenced block never became a `ToolBlock` — which means the "Unknown tool" branch
in `tool_execution.py` never ran either, so there was no error, no `events` row,
and nothing in the receipt. `strip_tool_blocks` also gates on the same set, so
the raw fence stayed *visible in the reply* while the agent said it had stored
the data.

These tests exercise the path. They do not assert that a name appears in a file:
`check-tool-surface.py` is the structural rule, and a test that greps a source
file is testing the file (`Law 20`). Each one below runs the real parser, the
real argument builder, and the real registries.
"""
import json

import pytest

import src.agent_tools  # noqa: F401  — import first; tool_parsing needs it
from src.agent_tools import TOOL_TAGS
from src.tool_capabilities import ResultIntegrity, ToolEffect, TOOL_CAPABILITIES
from src.tool_execution import _MCP_TOOL_MAP, _build_mcp_args
from src.tool_parsing import parse_tool_blocks, strip_tool_blocks
from src.tool_schemas import FUNCTION_TOOL_SCHEMAS, function_call_to_tool_block
from src.tool_security import feature_disabled_tools


def _fence(tool: str, body: str) -> str:
    return f"Storing that now.\n\n```{tool}\n{body}\n```\n\nStored."


def test_the_fenced_call_the_prompt_teaches_actually_parses():
    """The prompt says: store it via `manage_rag` (action=add_text). This is
    that call, in the shape the prompt describes."""
    text = _fence("manage_rag", json.dumps({"action": "add_text", "text": "a big result"}))
    blocks = parse_tool_blocks(text)
    assert len(blocks) == 1, "the call the system prompt teaches is still dropped"
    assert blocks[0].tool_type == "manage_rag"


def test_a_dropped_call_used_to_stay_visible_in_the_reply():
    """The half that made it silent rather than merely broken. An unparsed fence
    is not stripped, so the user saw a raw ```manage_rag block underneath a
    sentence claiming the data was stored."""
    text = _fence("manage_rag", '{"action": "add_text", "text": "x"}')
    shown = strip_tool_blocks(text)
    assert "manage_rag" not in shown
    assert "action" not in shown
    assert "Storing that now." in shown and "Stored." in shown


def test_the_call_has_somewhere_to_go():
    """A parsed block with no route is the same silence one layer down."""
    assert _MCP_TOOL_MAP.get("manage_rag") == ("rag", "manage_rag")


@pytest.mark.parametrize("content,expected", [
    ('{"action": "search", "query": "what did I store", "k": 3}',
     {"action": "search", "query": "what did I store", "k": 3}),
    ('{"action": "add_text", "text": "a big result"}',
     {"action": "add_text", "text": "a big result"}),
])
def test_json_arguments_reach_the_server_unchanged(content, expected):
    assert _build_mcp_args("manage_rag", content) == expected


def test_add_text_keeps_every_line_of_what_it_was_given():
    """The line-based fallback. `add_text` exists to hold a large tool result, so
    taking only the first line would store a truncated one and report success —
    which is the failure this whole row is about, moved one layer in."""
    args = _build_mcp_args("manage_rag", "add_text\nline one\nline two\nline three")
    assert args["action"] == "add_text"
    assert args["text"] == "line one\nline two\nline three"


def test_the_other_actions_land_on_the_keys_the_server_declares():
    assert _build_mcp_args("manage_rag", "search\nmy query") == {
        "action": "search", "query": "my query"}
    assert _build_mcp_args("manage_rag", "add_directory\n/srv/docs") == {
        "action": "add_directory", "directory": "/srv/docs"}


def test_both_call_channels_agree():
    """Fenced blocks and native function calls are two doors to one dispatcher,
    and the cookbook family shipped broken because a name was behind only one."""
    assert "manage_rag" in TOOL_TAGS
    schema = next((s for s in FUNCTION_TOOL_SCHEMAS
                   if s.get("function", {}).get("name") == "manage_rag"), None)
    assert schema is not None, "the function-calling channel cannot reach manage_rag"
    assert schema["function"]["parameters"]["required"] == ["action"]


def test_a_function_call_round_trips_back_into_arguments():
    """`function_call_to_tool_block` serialises to fence content and
    `_build_mcp_args` decodes it again. The pair has to agree or arguments are
    lost between the two halves of one call."""
    args = {"action": "search", "query": "x", "k": 3}
    block = function_call_to_tool_block("manage_rag", json.dumps(args))
    assert block.tool_type == "manage_rag"
    assert _build_mcp_args("manage_rag", block.content) == args


def test_the_approval_card_knows_what_it_does():
    """`add_directory` indexes files off disk and `search` hands their contents
    to the next model round, so the result is workspace-untrusted for the same
    reason `read_file`'s is."""
    caps = TOOL_CAPABILITIES.get("manage_rag")
    assert caps is not None
    assert ToolEffect.READ_WORKSPACE in caps.effects
    assert ToolEffect.WRITE_PRIVATE in caps.effects
    assert caps.result_integrity is ResultIntegrity.WORKSPACE_UNTRUSTED


def test_switching_rag_off_now_reaches_the_tool_too():
    """The flag used to map to nothing, on the reasoning that retrieval is
    context and not a tool call. True of retrieval; not true once there is a
    tool that writes to and searches the same index."""
    assert "manage_rag" in feature_disabled_tools({"rag": False})
    assert "manage_rag" not in feature_disabled_tools({"rag": True})
