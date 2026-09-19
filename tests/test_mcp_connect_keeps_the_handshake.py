# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P8-38` and `P8-40` — what the three connect sites threw away.

MEASURED ON THE TREE BEFORE THE CHANGE, by driving the manager rather than
reading it.

`P8-38`. All three connect sites spelled the handshake `await
session.initialize()` — statement, not assignment (`src/mcp_manager.py:296`
stdio, `:365` SSE, `:452` HTTP at `HEAD`). The `InitializeResult` it returns
carries the server's own `name` and `version`, the negotiated
`protocolVersion`, the `capabilities` it advertises, and `instructions` — prose
the MCP spec has the server write *for the model*. None of it was stored, so
`get_server_status` returned `{status, name, transport, tool_count}` and there
was nowhere in the product it could have been shown from.

`P8-40`. `annotations` was captured at the stdio site (`:308`) and the SSE site
(`:377`) and NOT at the HTTP site (`:456-461`), which built its tool dict from
three keys. So one server behind Streamable HTTP got no plan-mode read-only
credit however loudly it advertised `readOnlyHint`, while the same server over
SSE did. Three inline copies of one record, one of them short: `Law 13`.

The fakes here are the SDK's REAL `InitializeResult`, `Tool` and
`ToolAnnotations` models, so these cases fail if the manager only handles a
shape a test invented.
"""
from __future__ import annotations

import asyncio
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

pytest.importorskip("mcp")

from mcp.types import (  # noqa: E402
    Implementation,
    InitializeResult,
    ListToolsResult,
    ServerCapabilities,
    Tool,
    ToolAnnotations,
    ToolsCapability,
)

from src.mcp_manager import McpManager, mcp_tool_is_readonly  # noqa: E402

TRANSPORTS = ("stdio", "sse", "http")


def _tools():
    # The three names are chosen so the verb heuristic gets BOTH annotated ones
    # wrong on its own: "slurp" is not a read verb and "fetch" is. If the
    # annotation is dropped, the plan-mode verdicts below invert.
    return [
        Tool(
            name="slurp_file",
            description="Read a file",
            inputSchema={"type": "object", "properties": {"path": {"type": "string"}},
                         "required": ["path"]},
            annotations=ToolAnnotations(readOnlyHint=True),
        ),
        Tool(
            name="fetch_and_delete",
            description="Fetch a page and remove it",
            inputSchema={"type": "object", "properties": {}},
            annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True),
        ),
        Tool(
            name="wipe_index",
            description="Wipe the index",
            inputSchema={"type": "object", "properties": {}},
            annotations=None,  # the server advertises nothing
        ),
    ]


def _initialize_result():
    return InitializeResult(
        protocolVersion="2025-06-18",
        capabilities=ServerCapabilities(tools=ToolsCapability(listChanged=True)),
        serverInfo=Implementation(name="filesystem-mcp", version="1.4.2"),
        instructions="Call read_file before write_file. Paths must be absolute.",
    )


class _Session:
    """A session that answers the handshake and the tool list, and nothing else."""

    def __init__(self, init_result, tools):
        self._init = init_result
        self._tools = tools
        self.initialize_calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def initialize(self):
        self.initialize_calls += 1
        return self._init

    async def list_tools(self):
        return ListToolsResult(tools=self._tools)


@pytest.fixture()
def connect(monkeypatch):
    """Drive one real connect site over a faked wire. Returns (manager, session)."""

    def _factory(transport, *, init_result=None, tools=None):
        session = _Session(
            _initialize_result() if init_result is None else init_result,
            _tools() if tools is None else tools,
        )

        monkeypatch.setattr("mcp.ClientSession", lambda *a, **k: session, raising=True)

        @asynccontextmanager
        async def _two(*a, **k):
            yield ("read", "write")

        @asynccontextmanager
        async def _three(*a, **k):
            yield ("read", "write", lambda: "session-id")

        monkeypatch.setattr("mcp.client.stdio.stdio_client", _two, raising=True)
        monkeypatch.setattr("mcp.client.sse.sse_client", _two, raising=True)
        monkeypatch.setattr(
            "mcp.client.streamable_http.streamablehttp_client", _three, raising=True
        )
        monkeypatch.setattr("src.mcp_oauth.build_provider",
                            lambda *a, **k: None, raising=True)

        manager = McpManager()
        if transport == "stdio":
            coro = manager._connect_stdio("srv", "Files", sys.executable, [], {})
        elif transport == "sse":
            coro = manager._connect_sse("srv", "Files", "https://example.invalid/sse")
        else:
            coro = manager._connect_http("srv", "Files", "https://example.invalid/mcp")
        assert asyncio.run(coro) is True
        return manager, session

    return _factory


# ---------------------------------------------------------------------------
# `P8-40` — the annotation must survive every transport
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("transport", TRANSPORTS)
def test_the_server_annotation_is_captured_on_every_transport(connect, transport):
    manager, _ = connect(transport)
    by_name = {t["name"]: t for t in manager.get_all_tools()}

    assert by_name["slurp_file"]["annotations"] == {"readOnlyHint": True}
    assert by_name["fetch_and_delete"]["annotations"] == {"readOnlyHint": False,
                                                          "destructiveHint": True}
    assert by_name["wipe_index"]["annotations"] is None


@pytest.mark.parametrize("transport", TRANSPORTS)
def test_plan_mode_reads_the_annotation_on_every_transport(connect, transport):
    """The consequence the row is actually about.

    Both verdicts here are only reachable through the server's annotation.
    `slurp_file` is not a read verb, so the heuristic alone would refuse it;
    `fetch_and_delete` starts with one, so the heuristic alone would allow it.
    Drop `annotations` on a transport and this case inverts on that transport.
    """
    manager, _ = connect(transport)
    blocked_map, blocked_qualified = manager.plan_mode_blocked_mcp()

    assert "slurp_file" not in blocked_map.get("srv", set())
    assert "fetch_and_delete" in blocked_map["srv"]
    assert "mcp__srv__fetch_and_delete" in blocked_qualified
    # No annotation, unreadable verb -> refused, which is the fail-closed rule.
    assert "wipe_index" in blocked_map["srv"]


@pytest.mark.parametrize("transport", TRANSPORTS)
def test_the_payload_annotation_is_plain_json(connect, transport):
    """It goes on the wire, so it leaves the manager as data, not as a model."""
    manager, _ = connect(transport)
    for entry in manager.get_all_tools():
        ann = entry["annotations"]
        assert ann is None or isinstance(ann, dict), type(ann)
        assert entry["is_readonly"] is mcp_tool_is_readonly(
            {"name": entry["name"], "annotations": ann}
        )


# ---------------------------------------------------------------------------
# `P8-38` — keep the handshake
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("transport", TRANSPORTS)
def test_the_handshake_is_kept_on_every_transport(connect, transport):
    manager, session = connect(transport)
    status = manager.get_server_status("srv")

    assert session.initialize_calls == 1
    # `name` stays the operator's label; the server's own identity is new.
    assert status["name"] == "Files"
    assert status["server_name"] == "filesystem-mcp"
    assert status["server_version"] == "1.4.2"
    assert status["protocol_version"] == "2025-06-18"
    assert status["capabilities"] == ["tools"]
    assert status["instructions"].startswith("Call read_file before write_file.")


@pytest.mark.parametrize("transport", TRANSPORTS)
def test_a_server_that_advertises_nothing_adds_nothing(connect, transport):
    """Absent fields must be absent, not empty strings pretending to be data."""
    bare = InitializeResult(
        protocolVersion="2025-06-18",
        capabilities=ServerCapabilities(),
        serverInfo=Implementation(name="tiny", version="0.1"),
    )
    manager, _ = connect(transport, init_result=bare)
    status = manager.get_server_status("srv")

    assert status["server_name"] == "tiny"
    assert "instructions" not in status
    assert "capabilities" not in status


def test_the_instructions_reach_the_model(connect):
    """What can be shown now that could not before: the server's own note.

    `instructions` is the one handshake field the MCP spec writes for the model
    rather than for the client, and it was discarded, so the agent got the tool
    list and never the note that came with it.
    """
    manager, _ = connect("stdio")
    prompt = manager.get_tool_descriptions_for_prompt()

    assert "server instructions: Call read_file before write_file." in prompt
    assert "mcp__srv__slurp_file" in prompt


def test_long_instructions_are_bounded_in_the_prompt(connect):
    """Third-party prose, paid for on every turn, so it is capped and marked."""
    from src.mcp_manager import _MCP_PROMPT_INSTRUCTIONS_MAX

    shouty = InitializeResult(
        protocolVersion="2025-06-18",
        capabilities=ServerCapabilities(),
        serverInfo=Implementation(name="loud", version="9"),
        instructions="line one\n\n" + ("padding " * 4000),
    )
    manager, _ = connect("stdio", init_result=shouty)
    line = [l for l in manager.get_tool_descriptions_for_prompt().splitlines()
            if "server instructions:" in l][0]

    assert len(line) < _MCP_PROMPT_INSTRUCTIONS_MAX + 60
    assert line.endswith("…)"), line[-40:]
    assert "\n" not in line


def test_the_handshake_is_gone_when_the_server_is(connect):
    """A disconnected server reports nothing, rather than stale identity."""
    manager, _ = connect("stdio")
    asyncio.run(manager.disconnect_server("srv"))
    assert manager.get_server_status("srv") == {"status": "disconnected"}


# ---------------------------------------------------------------------------
# `P8-00` — where a person actually reads it
# ---------------------------------------------------------------------------


def _server_row(Factory, server_id="srv"):
    from core.database import McpServer
    from datetime import datetime

    db = Factory()
    db.add(McpServer(id=server_id, name="Files", transport="stdio", command="npx",
                     args="[]", env="{}", is_enabled=True,
                     created_at=datetime.utcnow(), updated_at=datetime.utcnow()))
    db.commit()
    db.close()


def _throwaway_db():
    from core.database import Base
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine("sqlite:///:memory:",
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def test_the_operator_can_read_it_through_manage_mcp(connect):
    """Asking the assistant *"what MCP servers do I have"* now answers with what
    the servers say about themselves, not only with the label that was typed in.
    """
    import json
    import unittest.mock as mock

    import src.agent_tools.admin_tools as admin_tools
    from src.agent_tools.admin_tools import do_manage_mcp

    manager, _ = connect("stdio")
    Factory = _throwaway_db()
    _server_row(Factory)

    real = admin_tools.get_mcp_manager
    admin_tools.get_mcp_manager = lambda: manager
    try:
        with mock.patch("core.database.SessionLocal", Factory):
            out = asyncio.run(do_manage_mcp(json.dumps({"action": "list"})))
    finally:
        admin_tools.get_mcp_manager = real

    entry = out["servers"][0]
    assert entry["name"] == "Files"
    assert entry["server_name"] == "filesystem-mcp"
    assert entry["server_version"] == "1.4.2"
    assert entry["protocol_version"] == "2025-06-18"
    assert entry["capabilities"] == ["tools"]
    assert entry["instructions"].startswith("Call read_file")


def test_the_servers_route_carries_it_too(connect):
    """`GET /api/mcp/servers` is what the Settings list is drawn from."""
    import unittest.mock as mock
    from types import SimpleNamespace

    from routes.mcp.mcp_routes import setup_mcp_routes

    manager, _ = connect("stdio")
    Factory = _throwaway_db()
    _server_row(Factory)

    class _Req:
        def __init__(self):
            from core.middleware import INTERNAL_TOOL_HEADER, INTERNAL_TOOL_TOKEN
            self.headers = {INTERNAL_TOOL_HEADER: INTERNAL_TOOL_TOKEN}
            self.state = SimpleNamespace(current_user="admin")
            self.app = SimpleNamespace(state=SimpleNamespace(auth_manager=None))

    router = setup_mcp_routes(manager)
    endpoint = [r.endpoint for r in router.routes
                if r.path == "/api/mcp/servers"
                and "GET" in getattr(r, "methods", set())][0]
    with mock.patch("routes.mcp.mcp_routes.SessionLocal", Factory):
        rows = endpoint(request=_Req())

    assert rows[0]["server_name"] == "filesystem-mcp"
    assert rows[0]["server_version"] == "1.4.2"
    assert rows[0]["instructions"].startswith("Call read_file")
    # A disconnected server reports nothing rather than a stale identity.
    assert all(k in rows[0] for k in ("protocol_version", "capabilities"))
