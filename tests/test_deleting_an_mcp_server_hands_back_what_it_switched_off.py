# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B864` — deleting and re-adding an MCP server re-enabled every hidden tool.

`mcp_servers.disabled_tools` is a column on the row. `DELETE
/api/mcp/servers/{id}` dropped the row and the list with it and answered
`{"status": "deleted"}`; a server added again starts with `disabled_tools`
NULL — every tool the operator had hidden from the agent is offered again, and
nothing said so. The row asked for one of two fixes and named the one an
automated caller can act on: **echo the dropped list in the delete response**.

So every door that deletes a server hands it back — the route, the agent's
`manage_mcp delete`, and `pantheon-mcp delete` — and the browser shows the
route's sentence. Driven through the real route functions over a real SQLite
schema (`Law 20`), and the row's `Verify:` is the second test: delete, re-add,
give the list back, and the tool is hidden again.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class _Request:
    def __init__(self, body=None):
        from core.middleware import INTERNAL_TOOL_HEADER, INTERNAL_TOOL_TOKEN

        self.headers = {INTERNAL_TOOL_HEADER: INTERNAL_TOOL_TOKEN}
        self.state = SimpleNamespace(current_user="admin")
        self.app = SimpleNamespace(state=SimpleNamespace(auth_manager=SimpleNamespace(
            is_configured=True, is_admin=lambda user: user == "admin")))
        self._body = body

    async def json(self):
        return self._body


class _Manager:
    def __init__(self):
        self._tools, self._status = {}, {}

    async def connect_server(self, server_id, name, transport, command=None,
                             args=None, env=None, url=None):
        self._tools[server_id] = ["echo", "wipe"]
        self._status[server_id] = {"status": "connected", "name": name, "tool_count": 2}
        return True

    async def disconnect_server(self, server_id):
        self._tools.pop(server_id, None)
        self._status.pop(server_id, None)

    def get_server_status(self, server_id):
        return self._status.get(server_id, {"status": "disconnected"})

    def get_all_tools(self, disabled_map=None):
        disabled_map = disabled_map or {}
        return [{"server_id": sid, "name": n, "qualified_name": f"mcp__{sid}__{n}",
                 "is_disabled": n in disabled_map.get(sid, set())}
                for sid, names in self._tools.items() for n in names]


@pytest.fixture()
def Factory(monkeypatch):
    from core.database import Base, McpServer
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    db = factory()
    db.add(McpServer(id="abcd1234", name="Files", transport="stdio", command="npx",
                     args='["-y", "server-filesystem", "/tmp"]', env="{}", url=None,
                     is_enabled=True, disabled_tools='["wipe"]'))
    db.add(McpServer(id="open0001", name="Open", transport="stdio", command="npx",
                     args="[]", env="{}", url=None, is_enabled=True, disabled_tools=None))
    db.commit()
    db.close()
    monkeypatch.setattr("routes.mcp.mcp_routes.SessionLocal", factory)
    monkeypatch.setattr("core.database.SessionLocal", factory)
    return factory


def _endpoint(manager, path, method):
    from routes.mcp.mcp_routes import setup_mcp_routes

    for route in setup_mcp_routes(manager).routes:
        if route.path == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"{method} {path} not found")


def _disabled(Factory, server_id):
    from core.database import McpServer

    db = Factory()
    try:
        return db.query(McpServer).filter(McpServer.id == server_id).first().disabled_tools
    finally:
        db.close()


def test_the_delete_hands_back_the_list_it_dropped_and_says_so(Factory):
    manager = _Manager()
    delete = _endpoint(manager, "/api/mcp/servers/{server_id}", "DELETE")

    out = asyncio.run(delete(server_id="abcd1234", request=_Request()))

    assert out["status"] == "deleted"
    assert out["dropped_disabled_tools"] == ["wipe"]
    assert "wipe" in out["message"] and "every tool on" in out["message"]


def test_deleted_re_added_and_handed_back_the_tool_is_hidden_again(Factory):
    """The row's `Verify:` — the whole sequence an automated caller runs."""
    manager = _Manager()
    delete = _endpoint(manager, "/api/mcp/servers/{server_id}", "DELETE")
    add = _endpoint(manager, "/api/mcp/servers", "POST")
    patch = _endpoint(manager, "/api/mcp/servers/{server_id}/tools", "PATCH")

    dropped = asyncio.run(delete(server_id="abcd1234", request=_Request()))
    created = asyncio.run(add(
        request=_Request(), name="Files", transport="stdio", command="npx",
        args='["-y", "server-filesystem", "/srv"]', env="{}",
        url="", oauth_file="", oauth_config="",
    ))
    assert _disabled(Factory, created["id"]) is None   # the premise, still true

    asyncio.run(patch(server_id=created["id"],
                      request=_Request({"disabled": dropped["dropped_disabled_tools"]})))

    assert json.loads(_disabled(Factory, created["id"])) == ["wipe"]
    from src.mcp_manager import load_disabled_map
    shown = {t["name"]: t["is_disabled"] for t in manager.get_all_tools(load_disabled_map())}
    assert shown == {"echo": False, "wipe": True}


def test_a_server_with_nothing_switched_off_says_nothing_extra(Factory):
    delete = _endpoint(_Manager(), "/api/mcp/servers/{server_id}", "DELETE")
    out = asyncio.run(delete(server_id="open0001", request=_Request()))
    assert out["dropped_disabled_tools"] == []
    assert out["message"] == "Removed 'Open'."


def test_the_agents_delete_says_which_tools_went_with_it(Factory, monkeypatch):
    from src.agent_tools import admin_tools

    monkeypatch.setattr(admin_tools, "get_mcp_manager", lambda: None)
    out = asyncio.run(admin_tools.do_manage_mcp(
        json.dumps({"action": "delete", "server_id": "abcd1234"})))

    assert out["exit_code"] == 0
    assert out["dropped_disabled_tools"] == ["wipe"]
    assert "wipe" in out["response"] and "switch it off again" in out["response"]
    assert _disabled_gone(Factory, "abcd1234")


def test_the_cli_delete_hands_back_the_list(Factory, monkeypatch, capsys):
    from tests.helpers.cli_loader import load_script

    cli = load_script("pantheon-mcp")
    monkeypatch.setattr(cli, "SessionLocal", Factory)
    cli.cmd_delete(SimpleNamespace(id="abcd1234", pretty=False))
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert out["dropped_disabled_tools"] == ["wipe"]


def _disabled_gone(Factory, server_id):
    from core.database import McpServer

    db = Factory()
    try:
        return db.query(McpServer).filter(McpServer.id == server_id).first() is None
    finally:
        db.close()
