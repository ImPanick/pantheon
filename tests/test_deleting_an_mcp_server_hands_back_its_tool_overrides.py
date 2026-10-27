# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1527` — deleting an MCP server dropped its tool overrides, and said nothing.

`mcp_servers.tool_overrides` is a column on the row (`P8-48`): the operator's
read-only answers, which decide what plan mode may run, and the descriptions
the model is shown in place of the server's own. `B864` made every delete hand
back the row's switched-off tools; the overrides went with the row unreported —
a lost *makes changes* lets plan mode run a tool the operator said writes, and
a lost description is lost work.

Now every door that deletes a server — the route, the agent's `manage_mcp
delete`, `pantheon-mcp delete` — hands them back as `dropped_tool_overrides`,
in the shape `PATCH /api/mcp/servers/{id}/tools` takes, and the route and the
agent say so in words. Driven through the real route functions over a real
SQLite schema (`Law 20`), reusing `B864`'s world; the row's `Verify:` is the
first test, and the second runs the whole delete → re-add → give back loop.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from tests.test_deleting_an_mcp_server_hands_back_what_it_switched_off import (
    _endpoint,
    _Manager,
    _Request,
)

_OVERRIDES = {
    "emit_metric": {"read_only": False, "description": "Writes a row to the metrics table."},
    "query_rows": {"read_only": True},
}


@pytest.fixture()
def Factory(monkeypatch):
    from core.database import Base, McpServer
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    # `B1223`: the routes read and write in a worker thread now, and an in-memory
    # SQLite is one per connection — one connection for every thread.
    from sqlalchemy.pool import StaticPool
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    db = factory()
    db.add(McpServer(id="abcd1234", name="Metrics", transport="stdio", command="npx",
                     args='["-y", "server-metrics"]', env="{}", url=None, is_enabled=True,
                     disabled_tools='["wipe"]', tool_overrides=json.dumps(_OVERRIDES)))
    db.add(McpServer(id="only0001", name="Notes", transport="stdio", command="npx",
                     args="[]", env="{}", url=None, is_enabled=True, disabled_tools=None,
                     tool_overrides=json.dumps({"find_note": {"description": "Search my notes."}})))
    db.add(McpServer(id="open0001", name="Open", transport="stdio", command="npx",
                     args="[]", env="{}", url=None, is_enabled=True, disabled_tools=None,
                     tool_overrides=None))
    db.commit()
    db.close()
    monkeypatch.setattr("routes.mcp.mcp_routes.SessionLocal", factory)
    monkeypatch.setattr("core.database.SessionLocal", factory)
    monkeypatch.setattr("src.mcp_manager.SessionLocal", factory)
    return factory


def _overrides(Factory, server_id):
    from src.mcp_manager import load_tool_overrides

    return load_tool_overrides(server_id).get(server_id, {})


def test_the_delete_hands_back_the_overrides_it_dropped_and_says_so(Factory):
    """The row's `Verify:`."""
    delete = _endpoint(_Manager(), "/api/mcp/servers/{server_id}", "DELETE")

    out = asyncio.run(delete(server_id="abcd1234", request=_Request()))

    assert out["status"] == "deleted"
    assert out["dropped_tool_overrides"] == _OVERRIDES
    assert out["dropped_disabled_tools"] == ["wipe"]   # `B864`, unchanged
    message = out["message"]
    assert "query_rows marked read-only" in message, message
    assert "emit_metric marked as making changes and given your own description" in message
    assert "set them again after adding it" in message


class _Describing(_Manager):
    """`B864`'s manager, plus the call a changed description makes (the
    prompt block and the tool index cache on its generation)."""

    def __init__(self):
        super().__init__()
        self.descriptions_changed = 0

    def tool_descriptions_changed(self):
        self.descriptions_changed += 1


def test_deleted_re_added_and_handed_back_the_answers_are_back(Factory):
    """The automated caller's loop: what the delete hands back is what the
    `PATCH` takes, and plan mode reads the same answers afterwards."""
    manager = _Describing()
    delete = _endpoint(manager, "/api/mcp/servers/{server_id}", "DELETE")
    add = _endpoint(manager, "/api/mcp/servers", "POST")
    patch = _endpoint(manager, "/api/mcp/servers/{server_id}/tools", "PATCH")

    dropped = asyncio.run(delete(server_id="abcd1234", request=_Request()))
    created = asyncio.run(add(
        request=_Request(), name="Metrics", transport="stdio", command="npx",
        args='["-y", "server-metrics"]', env="{}", url="", oauth_file="", oauth_config="",
    ))
    assert _overrides(Factory, created["id"]) == {}   # the premise, still true

    asyncio.run(patch(server_id=created["id"],
                      request=_Request({"overrides": dropped["dropped_tool_overrides"]})))

    assert _overrides(Factory, created["id"]) == _OVERRIDES
    assert manager.descriptions_changed == 1   # the model is told again


def test_a_server_with_only_overrides_says_them_alone(Factory):
    delete = _endpoint(_Manager(), "/api/mcp/servers/{server_id}", "DELETE")
    out = asyncio.run(delete(server_id="only0001", request=_Request()))
    assert out["dropped_disabled_tools"] == []
    assert out["dropped_tool_overrides"] == {"find_note": {"description": "Search my notes."}}
    assert out["message"] == (
        "Removed 'Notes'. 'Notes' had your answers for 1 tool (find_note given your own "
        "description). They went with the server: added again, it takes the server's own "
        "answers, so set it again after adding it.")


def test_a_server_with_nothing_said_about_its_tools_says_nothing_extra(Factory):
    delete = _endpoint(_Manager(), "/api/mcp/servers/{server_id}", "DELETE")
    out = asyncio.run(delete(server_id="open0001", request=_Request()))
    assert out["dropped_tool_overrides"] == {}
    assert out["message"] == "Removed 'Open'."


def test_the_agents_delete_hands_back_the_overrides(Factory, monkeypatch):
    from src.agent_tools import admin_tools

    monkeypatch.setattr(admin_tools, "get_mcp_manager", lambda: None)
    out = asyncio.run(admin_tools.do_manage_mcp(
        json.dumps({"action": "delete", "server_id": "abcd1234"})))

    assert out["exit_code"] == 0
    assert out["dropped_tool_overrides"] == _OVERRIDES
    assert "query_rows marked read-only" in out["response"]


def test_the_cli_delete_hands_back_the_overrides(Factory, monkeypatch, capsys):
    from tests.helpers.cli_loader import load_script

    cli = load_script("pantheon-mcp")
    monkeypatch.setattr(cli, "SessionLocal", Factory)
    cli.cmd_delete(SimpleNamespace(id="abcd1234", pretty=False))
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert out["dropped_tool_overrides"] == _OVERRIDES
