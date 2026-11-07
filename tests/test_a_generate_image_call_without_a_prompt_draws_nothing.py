# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2007`. A generate_image call with no prompt draws nothing, and the model is told why.

A native (or XML `<invoke>`) generate_image call is flattened to the four lines
the image server's parser reads, prompt first and every place kept (`B1357`).
A call with no prompt left line 1 empty, and `_parse_generate_image` stripped
the whole content before it split it, which dropped that empty line and moved
every value up one: `{"size": "512x512"}` drew a picture of the words
"512x512", `{"quality": "high"}` one of "high", `{"model": "gpt-image-1"}` one
of "gpt-image-1", each paid for on a cloud endpoint, and a model and a size
became a prompt and a model. The parser now splits first and strips each value
where it reads it, so the prompt stays empty and the server answers "Image
prompt is required", which reaches the model in the same turn.

From upstream Odysseus 6f0679bb (#6253), which refuses such a call when it is
converted (`_REQUIRED_NATIVE_TOOL_ARGS`) instead. Here that refusal would reach
neither the model nor the person (`B1383` explains only names nothing routes),
so the parser is fixed and the server's sentence kept. Driven (`Law 20`): the
real converter and dispatcher with `B1922`'s fake MCP manager, and the real
image server with its HTTP client refusing to be built.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from tests.helpers.signed_in import MEMBER, signed_in


class _FakeMcp:
    """The MCP manager, as far as the dispatcher sees it: what it was asked."""

    def __init__(self):
        self.calls = []

    async def call_tool(self, name, args):
        self.calls.append((name, dict(args)))
        return {"stdout": "Error: Image prompt is required", "exit_code": 0}


def _native(arguments: dict):
    import src.agent_tools  # noqa: F401  (tool_schemas <-> agent_tools import order)
    from src.tool_schemas import function_call_to_tool_block

    block = function_call_to_tool_block("generate_image", json.dumps(arguments))
    assert block is not None and block.tool_type == "generate_image"
    return block


@pytest.fixture
def dispatched(monkeypatch, tmp_path):
    """What the image server is sent for a native call, through the dispatcher."""
    import src.tool_execution as tool_execution

    signed_in(monkeypatch, tmp_path / "auth")
    mcp = _FakeMcp()
    monkeypatch.setattr(tool_execution, "get_mcp_manager", lambda: mcp)

    def run(arguments):
        mcp.calls.clear()
        asyncio.run(tool_execution.execute_tool_block(
            _native(arguments), owner=MEMBER,
            security_context=tool_execution.NO_TOOL_SECURITY_CONTEXT))
        [(name, sent)] = mcp.calls
        assert name == "mcp__image_gen__generate_image"
        return sent

    return run


@pytest.fixture
def image_server(monkeypatch):
    pytest.importorskip("mcp")
    import httpx
    import mcp_servers.image_gen_server as server

    class _NoClient:
        def __init__(self, *args, **kwargs):
            raise AssertionError("no image may be requested for this call")

    monkeypatch.setattr(httpx, "AsyncClient", _NoClient)

    def answer(arguments):
        return asyncio.run(server.call_tool("generate_image", dict(arguments)))[0].text

    return answer


@pytest.mark.parametrize("arguments", [
    {"size": "512x512"}, {"quality": "high"}, {"model": "gpt-image-1"},
], ids=["size", "quality", "model"])
def test_a_native_call_without_a_prompt_is_answered_that_it_needs_one(dispatched, image_server, arguments):
    sent = dispatched(arguments)

    assert sent == {"prompt": "", **arguments, "_pantheon_owner": MEMBER}
    assert image_server(sent) == "Error: Image prompt is required"


def test_each_value_of_a_call_stays_in_its_own_place():
    from src.tool_execution import _build_mcp_args

    def parsed(arguments):
        return _build_mcp_args("generate_image", _native(arguments).content)

    # A model and a size with no prompt were a prompt and a model.
    assert parsed({"model": "gpt-image-1", "size": "1024x1024"}) == {
        "prompt": "", "model": "gpt-image-1", "size": "1024x1024"}
    full = {"prompt": "a cat riding a bicycle", "model": "gpt-image-1",
            "size": "1024x1024", "quality": "high"}
    assert parsed(full) == full
    assert parsed({}) == parsed({"prompt": "   "}) == {"prompt": ""}
    # A fenced call's body: the prompt, and the quality on line 4.
    assert _build_mcp_args("generate_image", "a cat\n\n\nhigh") == {"prompt": "a cat", "quality": "high"}
