# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B74` — thirteen tools carried two hand-maintained schemas, and no pair matched.

A tool served by an `mcp_servers/*.py` that Pantheon also declares in
`FUNCTION_TOOL_SCHEMAS` used to be spelled out twice. The two copies are read
by **different audiences** — this register by Pantheon's own model, the
server's `list_tools()` by any third-party MCP client pointed at
`mcp_servers/` — so the copy that rotted was the one nobody here runs.

What had drifted was not only wording. `send_email` accepted `cc` and `bcc` in
the handler and declared them on the server, and the register the model reads
named neither, so **the agent could not cc anybody** on a capability that
worked. `reply_to_email` was the same story for `reply_all`.

The tests below split into three jobs: that the capability gaps are closed and
stay closed, that the schemas agree, and that they agree *by derivation* rather
than by a coincidence somebody will paste over.
"""
import asyncio
import importlib

import pytest

from src.agent_tools import TOOL_TAGS
from src.tool_schemas import FUNCTION_TOOL_SCHEMAS, mcp_tool_schema

SERVERS = ("memory_server", "rag_server", "email_server", "image_gen_server")


@pytest.fixture(scope="module")
def declared():
    return {
        entry["function"]["name"]: entry["function"]
        for entry in FUNCTION_TOOL_SCHEMAS
        if entry.get("type") == "function"
    }


@pytest.fixture(scope="module")
def served():
    out = {}
    for name in SERVERS:
        module = importlib.import_module(f"mcp_servers.{name}")
        for tool in asyncio.run(module.list_tools()):
            out[tool.name] = (name, tool)
    return out


# --- the capability the agent could not reach ------------------------------

def test_the_agent_can_cc_somebody(declared):
    """The handler passed `cc`/`bcc` to `_send_email`; the model was never told.

    This is `B66`'s shape — a capability that runs, that no register the model
    reads mentions — arriving through a schema written twice instead of a tag
    left out.
    """
    props = declared["send_email"]["parameters"]["properties"]
    assert "cc" in props
    assert "bcc" in props


def test_the_agent_can_reply_to_everyone(declared):
    props = declared["reply_to_email"]["parameters"]["properties"]
    assert "reply_all" in props
    assert props["reply_all"]["type"] == "boolean"


def test_read_email_stops_demanding_a_uid_it_does_not_need(declared):
    """`_read_email` takes a UID *or* a Message-ID and errors with neither.

    One copy required `uid` and never mentioned `message_id`; the other
    required nothing and had both. Requiring `uid` is the false half.
    """
    schema = declared["read_email"]["parameters"]
    assert "message_id" in schema["properties"]
    assert schema["required"] == []


def test_the_prompt_says_so_too():
    """The fenced channel is the one email actually travels on.

    `BUILTIN_EMAIL_TOOLS` routes a bare `send_email` fence to the MCP server,
    and built-in Python servers are skipped from the function schemas — so for
    email the system prompt is the register the model reads. A parameter added
    to the schema and not to the prompt would still be unreachable.
    """
    from src.agent_loop import TOOL_SECTIONS
    assert "bcc" in TOOL_SECTIONS["send_email"]
    assert "reply_all" in TOOL_SECTIONS["reply_to_email"]


# --- one schema ------------------------------------------------------------

def test_every_shared_tool_serves_exactly_what_pantheon_declares(declared, served):
    shared = [n for n in served if n in declared]
    assert len(shared) == 13, shared
    for name in shared:
        module_name, tool = served[name]
        assert tool.description == declared[name]["description"], f"{module_name}:{name}"
        assert tool.inputSchema == declared[name]["parameters"], f"{module_name}:{name}"


def test_a_tool_with_no_function_schema_is_still_reachable(declared, served):
    """The legitimate shape, told apart from a missed registration.

    `download_attachment`, the three drafting tools, `search_emails` and
    `generate_image` have no function schema on purpose — they travel the
    fenced channel, which carries no schema at all. What makes that honest
    rather than an oversight is that every one of them is in `TOOL_TAGS`.
    """
    fenced = [n for n in served if n not in declared]
    assert fenced, "expected some server tools to be fenced-channel only"
    for name in fenced:
        assert name in TOOL_TAGS, name


def test_the_schema_is_a_copy_the_caller_cannot_corrupt():
    """A server that edits what it gets back must not reach the register."""
    first = mcp_tool_schema("manage_memory")
    first["inputSchema"]["properties"]["action"]["enum"].append("detonate")
    second = mcp_tool_schema("manage_memory")
    assert "detonate" not in second["inputSchema"]["properties"]["action"]["enum"]


def test_deriving_a_tool_that_is_not_declared_is_an_error():
    """Loud, because the two reasons a name is missing look identical here.

    Either it is a fenced-channel tool that correctly has no schema, or it is a
    registration somebody missed. `mcp_tool_schema` cannot tell them apart, so
    it refuses; `.pantheon/check-mcp-schemas.py` is what decides, because that
    is a question about the whole surface.
    """
    with pytest.raises(KeyError):
        mcp_tool_schema("download_attachment")
    with pytest.raises(KeyError):
        mcp_tool_schema("no_such_tool_anywhere")


# --- derived, not merely equal ---------------------------------------------

def test_every_shared_tool_is_derived_rather_than_retyped(declared, served):
    """Equality is the property; derivation is what keeps it true.

    A hand-written schema that happens to match today passes the equality test
    and rots tomorrow, which is the whole history of this row.
    """
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    result = subprocess.run(
        [sys.executable, str(root / ".pantheon" / "check-mcp-schemas.py")],
        capture_output=True, text=True, cwd=str(root),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "13 shared tools derived" in result.stdout
