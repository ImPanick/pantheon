# SPDX-License-Identifier: AGPL-3.0-or-later
"""A chat server for the showcase's fictional world, as an MCP server.

The Workbench's headline flow (`P22-19`, the README's *Describe it* animation)
drafts "when mail arrives from my bank, summarise it and post it to my chat
server" — so the demo world needs a chat server to post to. This is one: two
tools, `send_message` and `list_channels`, served over stdio by the `mcp`
package Pantheon already depends on, registered through the admin route by
`scenes.gif_describe` for that scene alone and removed after it. A post is
appended to the file named on the command line and goes nowhere else
(`Law 16`).

    python scripts/showcase/demo_chat.py <posts.jsonl>
"""
from __future__ import annotations

import json
import sys
import time

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

POSTS = sys.argv[1] if len(sys.argv) > 1 else None
mcp = FastMCP("chat")


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
def send_message(channel: str, text: str) -> str:
    """Post a message to a channel, such as #general."""
    if POSTS:
        with open(POSTS, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"channel": channel, "text": text, "at": time.time()}) + "\n")
    return f"Posted to {channel}."


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def list_channels() -> str:
    """List the channels you can post to."""
    return json.dumps(["#general", "#bank", "#launch"])


if __name__ == "__main__":
    mcp.run()
