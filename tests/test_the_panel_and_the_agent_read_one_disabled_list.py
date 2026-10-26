# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1098` (with `B889` folded in) — one reader of the MCP disabled-tool list.

`routes/mcp/mcp_routes._load_disabled_map` repeated the query
`src.mcp_manager.load_disabled_map` holds, which the agent loop
(`_load_mcp_disabled_map`) and a workflow's MCP step already read. Two copies of
"which tools has an operator switched off" go stale apart (`Law 7`), and on a
gate the cost is concrete: the tools the browser says are hidden and the tools
the agent is denied stop being the same set, and nothing compared them.

`B889`'s `Verify:` — drive the route and the agent loop against one database
and assert they were handed the same map. The route is `GET /api/mcp/tools`,
called through its real endpoint; the manager records the map it is given.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class _Request:
    def __init__(self):
        from core.middleware import INTERNAL_TOOL_HEADER, INTERNAL_TOOL_TOKEN

        self.headers = {INTERNAL_TOOL_HEADER: INTERNAL_TOOL_TOKEN}
        self.state = SimpleNamespace(current_user="admin")
        self.app = SimpleNamespace(state=SimpleNamespace(auth_manager=SimpleNamespace(
            is_configured=True, is_admin=lambda user: user == "admin")))


class _RecordingManager:
    def __init__(self):
        self.handed = []

    def get_all_tools(self, disabled_map=None):
        self.handed.append(disabled_map)
        return []


@pytest.fixture()
def one_database(monkeypatch):
    """A real schema with three rows: a list, an empty list, and garbage."""
    from core.database import Base, McpServer
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Factory = sessionmaker(bind=engine)
    db = Factory()
    for sid, raw in (("files001", '["wipe", "chmod"]'), ("empty001", "[]"),
                     ("broken01", "{not json"), ("none0001", None)):
        db.add(McpServer(id=sid, name=sid, transport="stdio", command="npx",
                         args="[]", env="{}", url=None, is_enabled=True,
                         disabled_tools=raw))
    db.commit()
    db.close()
    # Every place the session could be read from, so a copy that imports it
    # differently still sees THIS database and the comparison is fair.
    monkeypatch.setattr("core.database.SessionLocal", Factory)
    monkeypatch.setattr("routes.mcp.mcp_routes.SessionLocal", Factory)
    return Factory


def _list_tools_endpoint(manager):
    from routes.mcp.mcp_routes import setup_mcp_routes

    for route in setup_mcp_routes(manager).routes:
        if route.path == "/api/mcp/tools" and "GET" in route.methods:
            return route.endpoint
    raise AssertionError("GET /api/mcp/tools not found")


def test_the_route_and_the_agent_loop_are_handed_the_same_map(one_database):
    from src.agent_loop import _load_mcp_disabled_map

    manager = _RecordingManager()
    _list_tools_endpoint(manager)(request=_Request())
    route_map = manager.handed[-1]
    loop_map = _load_mcp_disabled_map()

    assert route_map == loop_map == {"files001": {"wipe", "chmod"}}


def test_there_is_one_loader_and_both_names_lead_to_it():
    """`B1098`'s `Verify:` — one definition in the tree. The route module holds
    no copy of its own; the agent loop's name is kept (`Law 1`) and delegates."""
    import routes.mcp.mcp_routes as mcp_routes
    import src.mcp_manager as mcp_manager

    assert not hasattr(mcp_routes, "_load_disabled_map")
    assert mcp_routes.load_disabled_map is mcp_manager.load_disabled_map


def test_the_agent_loops_name_is_the_one_reader(one_database, monkeypatch):
    """Driven, not read: replace the one reader and the loop's name follows."""
    import src.mcp_manager as mcp_manager
    from src.agent_loop import _load_mcp_disabled_map

    monkeypatch.setattr(mcp_manager, "load_disabled_map", lambda: {"x": {"y"}})
    assert _load_mcp_disabled_map() == {"x": {"y"}}
