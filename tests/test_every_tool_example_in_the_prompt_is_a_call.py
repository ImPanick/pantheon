# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1010` — every tool example the prompt teaches is a call the parser reads.

The fenced prompt teaches each tool by example, and a model on the fenced
channel copies the example. `get_workspace`'s was an empty fence —
```` ```get_workspace ```` and a closing ```` ``` ```` — and
`tool_parsing.parse_tool_blocks` reads an empty fence as a call only for the
email tools, so a model that copied the prompt's own example called nothing
and got no answer. The example's body is now `{}`.

Driven (`Law 20`): each example is cut out of the prompt the loop really
assembles and handed to the real parser; and the real agent loop is given a
model that answers with the example cut out of the system prompt it was sent —
the call runs and the answer comes back.
"""
from __future__ import annotations

import asyncio
import json
import re

import pytest

import src.agent_loop as al
from src.tool_parsing import parse_tool_blocks

# A fence that opens a line with a tool's tag and closes on a line of its own:
# the shape every full-block section in `TOOL_SECTIONS` teaches. The inline
# ```` ```tool``` ```` that one-line sections name a tool with is not a fence.
_FENCE = re.compile(r"(?ms)^```([A-Za-z_]\w*)[ \t]*\n(.*?)^```[ \t]*$")


def _prompt() -> str:
    """The fenced-channel prompt with every tool in it, as the loop builds it."""
    return al._assemble_prompt(set(al.TOOL_SECTIONS))


def _examples():
    return [(m.group(1), m.group(0)) for m in _FENCE.finditer(_prompt())]


def test_get_workspaces_own_example_is_one_call():
    """The row's `Verify:`."""
    example = next(text for tag, text in _examples() if tag == "get_workspace")
    blocks = parse_tool_blocks(example)
    assert [b.tool_type for b in blocks] == ["get_workspace"], example
    assert blocks[0].content == "{}"


def test_every_section_that_teaches_by_example_is_checked():
    """The parametrized case below sees every full-block section's examples —
    so a section whose fence this file's pattern cannot see is a red here, not
    a tool nobody checked."""
    taught = {tag for tag, _ in _examples()}
    full_blocks = {name for name, section in al.TOOL_SECTIONS.items()
                   if section.startswith("```")}
    assert full_blocks and full_blocks <= taught, sorted(full_blocks - taught)


@pytest.mark.parametrize("tag, example", _examples(),
                         ids=[f"{tag}-{i}" for i, (tag, _) in enumerate(_examples())])
def test_each_example_in_the_prompt_is_one_call_of_its_tool(tag, example):
    blocks = parse_tool_blocks(example)
    assert [b.tool_type for b in blocks] == [tag], example


def test_a_model_that_copies_the_example_is_answered(monkeypatch):
    """The real loop: the model's reply is the `get_workspace` example cut out
    of the system prompt the loop sent it. The call runs, and its answer is
    what the next round is sent."""
    monkeypatch.setattr(al, "get_mcp_manager", lambda: None, raising=False)
    monkeypatch.setattr(al, "estimate_tokens", lambda *a, **k: 10, raising=False)
    monkeypatch.setattr(al, "blocked_tools_for_owner", lambda owner: set(), raising=False)
    # The dispatcher the loop calls, by its own globals (`B1002`: one patch,
    # undone in one step).
    monkeypatch.setitem(al.execute_tool_block.__globals__, "_owner_is_admin",
                        lambda owner: True)
    sent = []

    async def fake_stream(_candidates, messages, **kwargs):
        sent.append(messages)
        if len(sent) == 1:
            system = next(m["content"] for m in messages if m.get("role") == "system")
            example = next(m.group(0) for m in _FENCE.finditer(system)
                           if m.group(1) == "get_workspace")
            reply = f"Let me check.\n{example}"
        else:
            reply = "Done."
        yield f"data: {json.dumps({'delta': reply})}\n\n"
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(al, "stream_llm_with_fallback", fake_stream, raising=False)

    async def drain():
        return [c async for c in al.stream_agent_loop(
            "http://local.test/v1", "small-local-model",
            [{"role": "user", "content": "which folder is the project?"}],
            max_rounds=2, owner=None, session_id="s1", workspace=None,
            relevant_tools={"get_workspace"})]

    events = [json.loads(c[6:]) for c in asyncio.run(drain())
              if c.startswith("data: {")]
    outs = [e for e in events if e.get("type") == "tool_output"]
    assert len(outs) == 1 and outs[0]["exit_code"] == 0, events
    assert outs[0]["output"].startswith("No workspace is set."), outs[0]
    assert len(sent) == 2 and "No workspace is set." in json.dumps(sent[1])
