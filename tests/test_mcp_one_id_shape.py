# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B870` — three doors, one id shape.

MEASURED ON THE TREE BEFORE THE CHANGE by registering a server through each
door and reading back the id it minted:

    POST /api/mcp/servers        routes/mcp/mcp_routes.py:262   str(uuid.uuid4())[:8]   → 8
    manage_mcp {"action":"add"}  src/agent_tools/admin_tools.py:299  same              → 8
    pantheon-mcp add             scripts/pantheon-mcp:150       str(uuid.uuid4())      → 36

All three pass `validate_mcp_server_id`, so nothing was broken on the day —
which is the whole shape of `Law 13`. Anything that assumes eight characters is
right for two callers and wrong for the third, and it would have been found by
whoever registered their first server from the CLI.

Eight wins and the reasoning is in `src/mcp_manager.new_mcp_server_id`, which is
now the only place that mints one — beside `validate_mcp_server_id`, which is
the only place that says what a legal one is (`Law 14`).

EXISTING IDS ARE UNTOUCHED, and the last two cases drive that: a stored
thirty-six-character id — every server anybody registered from the CLI before
today — is still valid and still routes to its tools.

These cases DRIVE the three doors (`Law 20`); none of them reads a mint site.
"""
from __future__ import annotations

import asyncio
import json
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import core.database as core_db  # noqa: E402
from core.database import Base, McpServer  # noqa: E402
import src.mcp_manager as mcp_manager  # noqa: E402
from src.mcp_manager import (  # noqa: E402
    McpManager,
    new_mcp_server_id,
    qualify_mcp_tool_name,
    split_mcp_tool_name,
    validate_mcp_server_id,
)


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """A real table. `sqlite:///:memory:` gives each connection a fresh one."""
    engine = create_engine(f"sqlite:///{tmp_path}/mcp.db",
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    maker = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr(core_db, "SessionLocal", maker)
    monkeypatch.setattr(core_db, "engine", engine)
    monkeypatch.setattr(mcp_manager, "SessionLocal", maker)
    import src.database as src_db
    monkeypatch.setattr(src_db, "SessionLocal", maker, raising=False)
    # The agent's `add` branch tries to CONNECT after it stores the row. The id
    # is what is under test, so the connect is stubbed — a real one here would
    # spawn a process that is not an MCP server and leave anyio streams behind
    # for whatever test ran next.
    import src.agent_tools.admin_tools as admin_tools
    monkeypatch.setattr(admin_tools, "get_mcp_manager", lambda: _StubManager())
    return maker


# ---------------------------------------------------------------------------
# The three doors
# ---------------------------------------------------------------------------


def _id_from_the_agent_tool(db, monkeypatch) -> str:
    from src.agent_tools.admin_tools import do_manage_mcp

    # The agent path refuses interpreters and runners outright and takes
    # anything else only from the operator's allowlist. That control is not
    # weakened here; this opts one harmless binary in, exactly as an operator
    # would, so the door can be driven at all.
    monkeypatch.setenv("PANTHEON_MCP_ALLOWED_COMMANDS", "true")
    out = asyncio.run(do_manage_mcp(json.dumps({
        "action": "add", "name": "from-agent", "command": "true", "args": [],
    })))
    assert out.get("exit_code") == 0, out
    session = db()
    try:
        row = session.query(McpServer).filter(McpServer.name == "from-agent").first()
        assert row is not None, "manage_mcp add stored nothing"
        return row.id
    finally:
        session.close()


def _id_from_the_cli(db, monkeypatch, capsys) -> str:
    from tests.helpers.cli_loader import load_script

    cli = load_script("pantheon-mcp")
    monkeypatch.setattr(cli, "SessionLocal", db)
    parser = cli.build_parser() if hasattr(cli, "build_parser") else None
    args = type("A", (), {
        "transport": "stdio", "command": "python3", "args": '["-c","pass"]',
        "env": "{}", "url": None, "name": "from-cli", "disabled": False,
        "pretty": False, "json": True,
    })()
    cli.cmd_add(args)
    capsys.readouterr()
    session = db()
    try:
        row = session.query(McpServer).filter(McpServer.name == "from-cli").first()
        assert row is not None, "pantheon-mcp add stored nothing"
        return row.id
    finally:
        session.close()
    assert parser is None or True


class _FakeRequest:
    def __init__(self):
        from core.middleware import INTERNAL_TOOL_HEADER, INTERNAL_TOOL_TOKEN
        from types import SimpleNamespace

        self.headers = {INTERNAL_TOOL_HEADER: INTERNAL_TOOL_TOKEN}
        self.state = SimpleNamespace(current_user="admin")
        self.app = SimpleNamespace(state=SimpleNamespace(auth_manager=None))


class _StubManager:
    """Connects nothing. The id is what is under test, not the subprocess."""

    async def connect_server(self, server_id, name, transport, command=None,
                             args=None, env=None, url=None):
        return True

    async def disconnect_server(self, server_id):
        return None

    def get_server_status(self, server_id):
        return {"status": "connected", "name": "from-route", "tool_count": 0}

    def get_all_tools(self, disabled_map=None):
        return []


def _id_from_the_route(db, monkeypatch) -> str:
    """`POST /api/mcp/servers`, driven — not the mint it calls."""
    import unittest.mock as mock
    from routes.mcp.mcp_routes import setup_mcp_routes

    endpoint = None
    for route in setup_mcp_routes(_StubManager()).routes:
        if route.path == "/api/mcp/servers" and "POST" in getattr(route, "methods", set()):
            endpoint = route.endpoint
    assert endpoint is not None, "POST /api/mcp/servers not found"

    with mock.patch("routes.mcp.mcp_routes.SessionLocal", db):
        created = asyncio.run(endpoint(
            request=_FakeRequest(), name="from-route", transport="stdio",
            command="npx", args='["-y", "server-filesystem", "/tmp"]', env="{}",
            url="", oauth_file="", oauth_config="",
        ))
    return created["id"]


def test_the_three_doors_mint_the_same_shape(db, monkeypatch, capsys):
    """The row's `Verify:` clause. Drive all three, compare what came back."""
    ids = {
        "route": _id_from_the_route(db, monkeypatch),
        "agent": _id_from_the_agent_tool(db, monkeypatch),
        "cli": _id_from_the_cli(db, monkeypatch, capsys),
    }
    lengths = {door: len(sid) for door, sid in ids.items()}
    assert set(lengths.values()) == {8}, lengths
    for door, sid in ids.items():
        assert validate_mcp_server_id(sid) is None, (door, sid)
        assert sid == sid.lower() and all(c in "0123456789abcdef" for c in sid), (door, sid)


def test_the_mint_asks_the_table_before_it_hands_one_out(db, monkeypatch):
    """`str(uuid.uuid4())[:8]` never checked; a collision was an IntegrityError."""
    session = db()
    try:
        taken = "aaaaaaaa"
        session.add(McpServer(id=taken, name="squatter", transport="stdio",
                              command="python3", is_enabled=False))
        session.commit()
    finally:
        session.close()

    draws = iter([uuid.UUID(int=0xAAAAAAAA << 96), uuid.UUID(int=0xBBBBBBBB << 96)])
    monkeypatch.setattr(mcp_manager.uuid, "uuid4", lambda: next(draws))

    minted = new_mcp_server_id()
    assert minted != taken
    assert minted == "bbbbbbbb"


def test_the_mint_survives_a_missing_table(monkeypatch):
    """First boot, or a test with no schema: still hands out a legal id."""
    class _Boom:
        def query(self, *a, **k):
            raise RuntimeError("no such table: mcp_servers")

        def close(self):
            pass

    monkeypatch.setattr(mcp_manager, "SessionLocal", lambda: _Boom())
    sid = new_mcp_server_id()
    assert len(sid) == 8 and validate_mcp_server_id(sid) is None


# ---------------------------------------------------------------------------
# What must NOT change: the ids already out there
# ---------------------------------------------------------------------------


def test_a_stored_thirty_six_character_id_is_still_a_legal_id():
    """Every server registered from the CLI before today has one of these."""
    legacy = str(uuid.uuid4())
    assert len(legacy) == 36
    assert validate_mcp_server_id(legacy) is None


def test_a_stored_thirty_six_character_id_still_routes_to_its_tools():
    """The shape change is a mint, not a migration. Driven through call_tool."""
    legacy = str(uuid.uuid4())
    manager = McpManager()
    manager._tools[legacy] = [{"name": "ping", "description": "", "input_schema": {},
                               "annotations": None}]
    manager._connections[legacy] = {"status": "connected", "name": "legacy"}

    qualified = qualify_mcp_tool_name(legacy, "ping")
    assert split_mcp_tool_name(qualified) == (legacy, "ping")
    assert [t["qualified_name"] for t in manager.get_all_tools()] == [qualified]

    seen = {}

    class _Session:
        async def call_tool(self, name, arguments, **kw):
            seen["name"] = name
            raise RuntimeError("stop here — routing is what is under test")

    manager._sessions[legacy] = _Session()
    result = asyncio.run(manager.call_tool(qualified, {}))
    assert "not connected" not in result.get("error", "")
    assert seen["name"] == "ping"


def test_both_shapes_coexist_in_one_table(db):
    """A tree mid-history holds both. Neither is refused, neither is rewritten."""
    old, new = str(uuid.uuid4()), new_mcp_server_id()
    session = db()
    try:
        session.add(McpServer(id=old, name="from-the-cli-last-week",
                              transport="stdio", command="python3", is_enabled=False))
        session.add(McpServer(id=new, name="from-the-ui-today",
                              transport="stdio", command="python3", is_enabled=False))
        session.commit()
        rows = {r.name: r.id for r in session.query(McpServer).all()}
    finally:
        session.close()
    assert rows["from-the-cli-last-week"] == old and len(old) == 36
    assert rows["from-the-ui-today"] == new and len(new) == 8
