# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P24-27` — the evaluation world answers `manage_rag`.

Found bringing RAG Builder to the bar. `manage_rag` is the RAG MCP server's
tool, and a world has no MCP manager: every call answered *"MCP manager not
available for tool 'manage_rag'"*, so an agent that indexes a folder and
checks what comes back could not be measured at all.

A world with `rag` — the passages its index finds, by words in a query —
answers through the real server's own `call_tool`, with the index alone
standing in: a folder is indexed only if it is there (one chunk per file),
`list` shows what was indexed, and a search answers in the server's words.
A relative folder is refused as the server refuses it, which is why the
runbook passes the full path `ls` prints. A world without `rag` answers as before.
"""

from __future__ import annotations

import asyncio
import json

from src.agents import evals as E
from src.agents.catalogue import get_agent


def _run(world, calls, inputs=None):
    seen = []
    real = E.World.rag

    async def spy(self, content):
        out = await real(self, content)
        seen.append(out[1]["output"])
        return out

    E.World.rag = spy
    try:
        m = get_agent(None, "rag-builder")
        case = {"id": "drive", "world": world, "inputs": inputs or {"folder": "docs", "questions": "How long do refunds take?"},
                "script": [{"call": [c]} for c in calls] + [{"say": "Done."}], "checks": [{"called": "manage_rag"}]}
        (r,) = asyncio.run(E.run_agent(m, cases=[case]))
    finally:
        E.World.rag = real
    return seen, r


def test_a_folder_is_indexed_listed_and_searched_in_the_servers_words():
    world = {"files": {"docs/refunds.md": "Refunds are paid within 14 days.", "docs/shipping.md": "Shipping takes 3 days."},
             "rag": {"refund": [{"file": "refunds.md", "text": "Refunds are paid within 14 days.", "similarity": 0.82}]}}
    # `$WORLD_PROJECTS` is the world's projects folder, as `ls` prints it.
    calls = [["manage_rag", {"action": "add_directory", "directory": "$WORLD_PROJECTS/docs"}],
             ["manage_rag", {"action": "list"}],
             ["manage_rag", {"action": "search", "query": "how long do refunds take"}],
             ["manage_rag", {"action": "search", "query": "opening hours"}]]
    seen, r = _run(world, calls)
    added, listed, found, nothing = seen
    assert "added to RAG index (2 chunks indexed)" in added, added
    assert "/docs`" in listed and "pantheon-eval-" in listed, listed
    assert "**Top 1 matches for 'how long do refunds take':**" in found and "[refunds.md] (similarity 0.82)" in found, found
    assert "No matches found for 'opening hours'." in nothing, nothing
    assert "MCP manager not available" not in " ".join(seen)


def test_a_relative_folder_fails_as_it_fails_in_the_server():
    seen, _ = _run({"files": {"docs/a.md": "x"}, "rag": {}}, [["manage_rag", {"action": "add_directory", "directory": "docs"}]])
    # The server refuses a relative folder (`test_a_relative_folder_is_not_indexed_from_the_install`).
    assert seen and seen[0].startswith("Error:") and "not a full path" in seen[0], seen


def test_without_rag_the_tool_answers_as_before():
    import src.tool_execution as tool_execution
    out = []
    real = tool_execution._execute_tool_block_impl

    async def spy(block, *a, **kw):
        res = await real(block, *a, **kw)
        out.append(json.dumps(res[1] if isinstance(res, tuple) else res))
        return res

    tool_execution._execute_tool_block_impl = spy
    try:
        _run({}, [["manage_rag", {"action": "list"}]])
    finally:
        tool_execution._execute_tool_block_impl = real
    assert any("MCP manager not available" in o for o in out), out


def test_a_world_lints_its_index():
    m = get_agent(None, "rag-builder")
    ok = {"cases": [{"id": "a-case", "world": {"rag": {"refund": [{"file": "a.md", "text": "x"}]}}, "checks": [{"status": "success"}]}]}
    assert E.lint_evals(ok, m)
    bad = {"cases": [{"id": "a-case", "world": {"rag": [{"file": "a.md"}]}, "checks": [{"status": "success"}]}]}
    try:
        E.lint_evals(bad, m)
    except E.EvalRefused as exc:
        assert "rag" in exc.sentence
    else:
        raise AssertionError("a malformed index was accepted")
