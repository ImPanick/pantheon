# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1923` — the agent's `manage_rag` searches and stores only the index of the
person it runs for, and only an admin's agent touches the index's folders.

**Before the fix** `manage_rag` reached the shared `pantheon_rag` store with no
owner. The `rag` server's own comment said the owner was "injected by the tool
dispatcher, mirroring the email MCP"; nothing injected it. So `search` ran with
`owner=None`, which `rag_vector.search` reads as no filter at all, and printed
every account's documents; `add_text` stored chunks that were nobody's; and a
`_pantheon_owner` the model wrote was believed until `B1922` dropped it from
every built-in server's arguments. `add_directory` indexed any
folder the server could read, the data directory with `auth.json` among them,
for an account that may not `read_file` on this machine; `list` printed every
indexed path and `remove_directory` deleted anyone's chunks. The Knowledge
index's routes hold all three to the operator's gate (`require_operator`) and a
folder to the personal documents folder (`PERSONAL_DIR`). It is `B1601`'s
defect, in another tool.

Now the dispatcher sends the person (after `B1922` drops every `_pantheon_` key
the model sent), refuses a call that names nobody (`B1601`'s rule), and refuses
list, add_directory and remove_directory to all but an admin, in a sentence
that names Settings → System → Knowledge index. The server indexes an admin's
folder under the admin's name and returns at most 20 matches. Chunks stored
with no owner before this are not found by anyone's search any more: they were
everyone's, and there is no owner to give them.

Driven (`Law 20`): the real dispatcher over real accounts with a fake MCP
manager, and the real server with its index stood in.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from tests.helpers.signed_in import ADMIN, MEMBER, signed_in


class _FakeMcp:
    def __init__(self):
        self.calls = []

    async def call_tool(self, name, args):
        self.calls.append((name, dict(args)))
        return {"stdout": "ok", "exit_code": 0}


@pytest.fixture
def dispatcher(monkeypatch, tmp_path):
    import src.tool_execution as tool_execution

    signed_in(monkeypatch, tmp_path / "auth")   # ada is the admin, bob a member
    mcp = _FakeMcp()
    monkeypatch.setattr(tool_execution, "get_mcp_manager", lambda: mcp)

    def run(call, owner, tool="manage_rag"):
        content = call if isinstance(call, str) else json.dumps(call)
        block = SimpleNamespace(tool_type=tool, content=content)
        return asyncio.run(tool_execution.execute_tool_block(
            block, owner=owner, security_context=tool_execution.NO_TOOL_SECURITY_CONTEXT))[1]

    return run, mcp


def test_a_search_and_what_is_stored_are_the_persons_own(dispatcher):
    run, mcp = dispatcher
    run({"action": "search", "query": "the lease", "_pantheon_owner": ADMIN}, MEMBER)
    run("add_text\nwhat the tool found", MEMBER)
    assert mcp.calls == [
        ("mcp__rag__manage_rag", {"action": "search", "query": "the lease", "_pantheon_owner": MEMBER}),
        ("mcp__rag__manage_rag", {"action": "add_text", "text": "what the tool found",
                                  "_pantheon_owner": MEMBER}),
    ]


@pytest.mark.parametrize("call", [
    {"action": "list"},
    {"action": "add_directory", "directory": "/app/data"},
    {"action": "remove_directory", "directory": "/srv/docs"},
    "add_directory\n/app/data",
])
def test_only_an_admins_agent_touches_the_indexs_folders(dispatcher, call):
    run, mcp = dispatcher
    refused = run(call, MEMBER)
    assert refused["exit_code"] == 1 and "Knowledge index" in refused["error"], refused
    assert mcp.calls == [], "a member's folder action reached the index"
    run(call, ADMIN)
    assert len(mcp.calls) == 1 and mcp.calls[0][1]["_pantheon_owner"] == ADMIN, mcp.calls


def test_with_nobody_to_scope_by_the_tool_refuses_in_a_sentence(dispatcher):
    run, mcp = dispatcher
    for call in ({"action": "search", "query": "x"}, {"action": "add_text", "text": "x"},
                 {"action": "list"}):
        out = run(call, None)
        assert out["exit_code"] == 1 and "person" in out["error"], out
    assert mcp.calls == []


def test_the_qualified_name_carries_the_admins_name_too(dispatcher):
    run, mcp = dispatcher
    run({"action": "search", "query": "x", "_pantheon_owner": MEMBER}, ADMIN, tool="mcp__rag__manage_rag")
    assert mcp.calls == [("mcp__rag__manage_rag",
                          {"action": "search", "query": "x", "_pantheon_owner": ADMIN})]


# ── the server ───────────────────────────────────────────────────────────────

class _Index:
    def __init__(self):
        self.calls = []

    def search(self, query, k=5, owner=None):
        self.calls.append(("search", k, owner))
        return []

    def index_personal_documents(self, directory, owner=None):
        self.calls.append(("index", directory, owner))
        return {"indexed_count": 1}


class _Folders:
    def __init__(self):
        self.calls = []

    def add_directory(self, directory, index=True, owner=None):
        self.calls.append((directory, index, owner))


@pytest.fixture
def server(monkeypatch):
    pytest.importorskip("mcp")
    import mcp_servers.rag_server as rag_server

    index, folders = _Index(), _Folders()
    monkeypatch.setattr(rag_server, "_rag_manager", index)
    monkeypatch.setattr(rag_server, "_personal_docs_manager", folders)
    monkeypatch.setattr(rag_server, "_initialized", True)

    def call(arguments):
        return asyncio.run(rag_server.call_tool("manage_rag", arguments))[0].text

    return call, index, folders


def test_a_search_asks_the_index_for_at_most_twenty_matches(server):
    call, index, _folders = server
    call({"action": "search", "query": "everything", "k": 10000, "_pantheon_owner": MEMBER})
    assert index.calls == [("search", 20, MEMBER)]


def test_an_admins_folder_is_indexed_under_their_name(server, tmp_path):
    call, index, folders = server
    said = call({"action": "add_directory", "directory": str(tmp_path), "_pantheon_owner": ADMIN})
    assert "added to RAG index" in said, said
    assert index.calls == [("index", str(tmp_path), ADMIN)]
    assert folders.calls == [(str(tmp_path), False, ADMIN)]
