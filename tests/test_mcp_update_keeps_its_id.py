# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P8-35` — editing a server used to mean replacing it, and an id is identity.

MEASURED ON THE TREE BEFORE THE CHANGE. Of the eleven routes `setup_mcp_routes`
registered, exactly one mutated a configured server: `PATCH
/api/mcp/servers/{id}` (`routes/mcp/mcp_routes.py:357` at `HEAD`), whose only
parameter is `is_enabled`. Changing a command, an argument, a URL or a token
had no route at all, so the procedure was `DELETE` then `POST` — and `POST
/api/mcp/servers` opens with `server_id = str(uuid.uuid4())[:8]`. The
replacement is a different server as far as everything holding a reference is
concerned:

* `McpManager.call_tool` splits `mcp__<server_id>__<tool>` and looks the id up
  in `self._sessions`. A scheduled task whose `output_target` is that string —
  the scheduler dispatches on exactly that prefix, `src/task_scheduler.py:2956`
  — stops resolving, silently.
* `disabled_tools` is a **column on the row**. `DELETE` takes the row and the
  column with it, so every tool the operator had hidden from the agent comes
  back enabled on the replacement. That is a privilege change disguised as an
  edit, and nothing anywhere reports it.

Both are reproduced below against the real routes before the new one is used,
so the premise is measured rather than asserted.

THE DECISION THIS ROW ASKS FOR, WRITTEN DOWN: **the id survives an edit.**
`PUT /api/mcp/servers/{id}` mutates the row in place; `id` and `disabled_tools`
are the two fields it will not touch. Stored `mcp__<id>__<tool>` references
keep resolving, and a tool switched off stays off even when the command under
it changed completely (fail closed — an edit must not re-enable anything). The
one thing an edit can invalidate is a tool NAME, so those entries are kept and
reported back as `stale_disabled_tools` instead of being dropped or hidden.

These tests DRIVE THE ROUTES (`Law 20`).
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class _FakeRequest:
    def __init__(self):
        from core.middleware import INTERNAL_TOOL_HEADER, INTERNAL_TOOL_TOKEN

        self.headers = {INTERNAL_TOOL_HEADER: INTERNAL_TOOL_TOKEN}
        self.state = SimpleNamespace(current_user="admin")
        self.app = SimpleNamespace(state=SimpleNamespace(auth_manager=None))


class _Manager:
    """Tracks connections by server id, the way the real manager keys them."""

    def __init__(self, tools=("echo", "wipe")):
        self._tools = {}
        self._status = {}
        self.default_tools = list(tools)
        self.connects = []
        self.disconnects = []

    async def connect_server(self, server_id, name, transport, command=None,
                             args=None, env=None, url=None):
        self.connects.append(dict(server_id=server_id, name=name, transport=transport,
                                  command=command, args=args, env=env, url=url))
        self._tools[server_id] = list(self.default_tools)
        self._status[server_id] = {"status": "connected", "name": name,
                                   "tool_count": len(self.default_tools)}
        return True

    async def disconnect_server(self, server_id):
        self.disconnects.append(server_id)
        self._tools.pop(server_id, None)
        self._status.pop(server_id, None)

    def get_server_status(self, server_id):
        return self._status.get(server_id, {"status": "disconnected"})

    def get_all_tools(self, disabled_map=None):
        return [
            {"server_id": sid, "server_name": self._status[sid]["name"], "name": n,
             "qualified_name": f"mcp__{sid}__{n}", "description": "",
             "input_schema": {}, "is_disabled": False}
            for sid, names in self._tools.items() for n in names
        ]


def _db():
    from core.database import Base
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _seed(Factory, **kw):
    from core.database import McpServer

    fields = dict(id="abcd1234", name="Files", transport="stdio", command="npx",
                  args='["-y", "server-filesystem", "/tmp"]', env='{"TOKEN": "t1"}',
                  url=None, is_enabled=True, disabled_tools='["wipe"]')
    fields.update(kw)
    db = Factory()
    try:
        db.add(McpServer(**fields))
        db.commit()
    finally:
        db.close()
    return fields["id"]


def _row(Factory, server_id):
    from core.database import McpServer

    db = Factory()
    try:
        srv = db.query(McpServer).filter(McpServer.id == server_id).first()
        if srv is None:
            return None
        return {"id": srv.id, "name": srv.name, "transport": srv.transport,
                "command": srv.command, "args": srv.args, "env": srv.env,
                "url": srv.url, "is_enabled": srv.is_enabled,
                "disabled_tools": srv.disabled_tools}
    finally:
        db.close()


def _endpoint(manager, path, method):
    from routes.mcp.mcp_routes import setup_mcp_routes

    for route in setup_mcp_routes(manager).routes:
        if route.path == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"{method} {path} not found")


_PUT_FIELDS = ("name", "transport", "command", "args", "env", "url", "oauth_config")


def _put(Factory, manager, server_id="abcd1234", **overrides):
    """Every `Form` parameter is passed explicitly.

    Calling an endpoint function directly bypasses FastAPI's dependency
    resolution, so an unpassed `Form(None)` arrives as the marker object rather
    than `None` — the same trap the `add_server` tests document.
    """
    import unittest.mock as mock

    fields = {f: None for f in _PUT_FIELDS}
    fields.update(overrides)
    endpoint = _endpoint(manager, "/api/mcp/servers/{server_id}", "PUT")
    with mock.patch("routes.mcp.mcp_routes.SessionLocal", Factory):
        return asyncio.run(endpoint(server_id=server_id, request=_FakeRequest(), **fields))


# ---------------------------------------------------------------------------
# The premise, measured against the routes that were already there
# ---------------------------------------------------------------------------


def test_delete_then_add_mints_a_new_id_and_loses_the_disabled_list():
    """What an operator had to do before, and what it cost them."""
    import unittest.mock as mock

    Factory = _db()
    old_id = _seed(Factory)
    manager = _Manager()
    asyncio.run(manager.connect_server(old_id, "Files", "stdio"))

    delete = _endpoint(manager, "/api/mcp/servers/{server_id}", "DELETE")
    add = _endpoint(manager, "/api/mcp/servers", "POST")
    with mock.patch("routes.mcp.mcp_routes.SessionLocal", Factory):
        asyncio.run(delete(server_id=old_id, request=_FakeRequest()))
        created = asyncio.run(add(
            request=_FakeRequest(), name="Files", transport="stdio", command="npx",
            args='["-y", "server-filesystem", "/srv"]', env='{"TOKEN": "t1"}',
            url="", oauth_file="", oauth_config="",
        ))

    assert created["id"] != old_id, "the premise does not hold any more"
    assert _row(Factory, old_id) is None
    assert _row(Factory, created["id"])["disabled_tools"] is None, (
        "the disabled list survived — the premise does not hold any more"
    )
    # And the stored reference no longer resolves.
    assert manager.get_server_status(old_id)["status"] == "disconnected"


# ---------------------------------------------------------------------------
# The decision
# ---------------------------------------------------------------------------


def test_an_edit_keeps_the_id():
    Factory = _db()
    manager = _Manager()
    asyncio.run(manager.connect_server("abcd1234", "Files", "stdio"))
    _seed(Factory)

    out = _put(Factory, manager, args='["-y", "server-filesystem", "/srv"]')

    assert out["id"] == "abcd1234"
    assert out["id_changed"] is False
    assert _row(Factory, "abcd1234")["args"] == '["-y", "server-filesystem", "/srv"]'


def test_a_stored_qualified_reference_still_resolves_after_an_edit():
    """`mcp__<id>__<tool>` is what a scheduled task's `output_target` holds and
    what `call_tool` parses. The id is the whole reference."""
    from src.mcp_manager import McpManager

    Factory = _db()
    manager = _Manager()
    asyncio.run(manager.connect_server("abcd1234", "Files", "stdio"))
    _seed(Factory)

    stored_reference = "mcp__abcd1234__echo"
    _put(Factory, manager, command="python3", args='["server.py"]')

    server_id = stored_reference.split("__", 2)[1]
    assert manager.get_server_status(server_id)["status"] == "connected"
    assert stored_reference in {
        t["qualified_name"] for t in manager.get_all_tools()
    }
    # And the real parser agrees about which server that name means.
    assert McpManager().is_builtin(server_id) is False


def test_the_disabled_list_survives_the_edit():
    """Fail closed. An edit is not a request to re-enable anything."""
    Factory = _db()
    manager = _Manager()
    asyncio.run(manager.connect_server("abcd1234", "Files", "stdio"))
    _seed(Factory)

    out = _put(Factory, manager, command="python3")

    assert _row(Factory, "abcd1234")["disabled_tools"] == '["wipe"]'
    assert out["disabled_tools_kept"] == 1
    assert out["stale_disabled_tools"] == []


def test_a_disabled_name_the_new_command_no_longer_offers_is_reported():
    """Kept, not dropped — pointing back must not have lost it — but named, so
    the operator learns it now instead of wondering later."""
    Factory = _db()
    manager = _Manager(tools=("echo",))       # `wipe` is gone after the edit
    asyncio.run(manager.connect_server("abcd1234", "Files", "stdio"))
    _seed(Factory)

    out = _put(Factory, manager, command="python3", args='["other_server.py"]')

    assert out["stale_disabled_tools"] == ["wipe"]
    assert _row(Factory, "abcd1234")["disabled_tools"] == '["wipe"]', "it was dropped"


# ---------------------------------------------------------------------------
# What an edit means field by field
# ---------------------------------------------------------------------------


def test_a_field_left_out_is_left_alone():
    Factory = _db()
    manager = _Manager()
    asyncio.run(manager.connect_server("abcd1234", "Files", "stdio"))
    _seed(Factory)

    _put(Factory, manager, name="Filesystem")

    row = _row(Factory, "abcd1234")
    assert row["name"] == "Filesystem"
    assert row["command"] == "npx"
    assert json.loads(row["env"]) == {"TOKEN": "t1"}
    assert json.loads(row["args"])[0] == "-y"


def test_a_field_sent_empty_is_cleared():
    """The only way to say "no env" — and it has to be sayable, or a token can
    be rotated but never removed."""
    Factory = _db()
    manager = _Manager()
    asyncio.run(manager.connect_server("abcd1234", "Files", "stdio"))
    _seed(Factory)

    _put(Factory, manager, env="", args="")

    row = _row(Factory, "abcd1234")
    assert json.loads(row["env"]) == {}
    assert json.loads(row["args"]) == []


def test_a_rotated_token_reaches_the_relaunched_server():
    Factory = _db()
    manager = _Manager()
    asyncio.run(manager.connect_server("abcd1234", "Files", "stdio"))
    _seed(Factory)

    _put(Factory, manager, env='{"TOKEN": "t2"}')

    assert manager.connects[-1]["env"] == {"TOKEN": "t2"}


def test_an_enabled_server_is_relaunched_so_the_edit_is_visible_now():
    Factory = _db()
    manager = _Manager()
    asyncio.run(manager.connect_server("abcd1234", "Files", "stdio"))
    _seed(Factory)

    out = _put(Factory, manager, command="python3")

    assert manager.disconnects == ["abcd1234"]
    assert manager.connects[-1]["command"] == "python3"
    assert out["connected"] is True
    assert out["status"] == "connected"


def test_a_disabled_server_is_edited_but_not_started():
    """An edit is a config change. It is not an enable."""
    Factory = _db()
    manager = _Manager()
    _seed(Factory, is_enabled=False)

    out = _put(Factory, manager, command="python3")

    assert manager.connects == []
    assert out["connected"] is False
    assert out["is_enabled"] is False
    assert _row(Factory, "abcd1234")["command"] == "python3"


# ---------------------------------------------------------------------------
# `Law 15` — the refusals
# ---------------------------------------------------------------------------


def test_an_unknown_server_is_404():
    Factory = _db()
    with pytest.raises(HTTPException) as caught:
        _put(Factory, _Manager(), server_id="nosuch", name="x")
    assert caught.value.status_code == 404


def test_switching_transport_without_the_field_it_needs_is_refused():
    """Validated against the MERGED row, not against what was sent — otherwise
    this saves a server that cannot start and reports success."""
    Factory = _db()
    manager = _Manager()
    _seed(Factory)

    with pytest.raises(HTTPException) as caught:
        _put(Factory, manager, transport="http")
    assert caught.value.status_code == 400
    assert "url is required" in caught.value.detail
    assert _row(Factory, "abcd1234")["transport"] == "stdio", "it saved anyway"


def test_clearing_the_command_of_a_stdio_server_is_refused():
    Factory = _db()
    _seed(Factory)
    with pytest.raises(HTTPException) as caught:
        _put(Factory, _Manager(), command="")
    assert caught.value.status_code == 400
    assert "command is required" in caught.value.detail


def test_an_empty_name_is_refused():
    Factory = _db()
    _seed(Factory)
    with pytest.raises(HTTPException) as caught:
        _put(Factory, _Manager(), name="   ")
    assert caught.value.status_code == 400
    assert "name" in caught.value.detail


def test_an_unknown_transport_is_refused():
    Factory = _db()
    _seed(Factory)
    with pytest.raises(HTTPException) as caught:
        _put(Factory, _Manager(), transport="carrier-pigeon")
    assert caught.value.status_code == 400
    assert "stdio" in caught.value.detail


@pytest.mark.parametrize(
    "field,bad,word",
    [("args", "[-y, pkg]", "valid JSON"),
     ("env", '{"A": "b"', "valid JSON"),
     ("args", "5", "JSON array"),
     ("env", '["A"]', "JSON object"),
     ("oauth_config", "{nope}", "valid JSON")],
)
def test_the_json_fields_are_refused_by_the_same_rule_as_add(field, bad, word):
    """`Law 13`/`Law 14`: `_parsed_json_field` moved to module scope rather
    than being written out a second time, so both routes refuse identically
    and an operator learns one set of messages."""
    Factory = _db()
    _seed(Factory)
    with pytest.raises(HTTPException) as caught:
        _put(Factory, _Manager(), **{field: bad})
    assert caught.value.status_code == 400
    assert word in caught.value.detail
    assert _row(Factory, "abcd1234")["env"] == '{"TOKEN": "t1"}', "it saved anyway"


def test_a_non_admin_cannot_edit_a_server():
    """Same gate as `add_server`: the command runs on this host."""
    import unittest.mock as mock

    Factory = _db()
    _seed(Factory)
    endpoint = _endpoint(_Manager(), "/api/mcp/servers/{server_id}", "PUT")
    stranger = SimpleNamespace(
        headers={}, state=SimpleNamespace(current_user="bob"),
        app=SimpleNamespace(state=SimpleNamespace(
            auth_manager=SimpleNamespace(is_configured=True, is_admin=lambda u: False))))

    fields = {f: None for f in _PUT_FIELDS}
    fields["command"] = "curl"
    with mock.patch("routes.mcp.mcp_routes.SessionLocal", Factory), \
            mock.patch("core.middleware.auth_disabled", return_value=False):
        with pytest.raises(HTTPException) as caught:
            asyncio.run(endpoint(server_id="abcd1234", request=stranger, **fields))
    assert caught.value.status_code == 403
    assert _row(Factory, "abcd1234")["command"] == "npx"


def test_the_toggle_still_does_only_what_it_did():
    """`Law 1`. `PATCH` keeps its one job; `PUT` is the new door beside it."""
    import unittest.mock as mock

    Factory = _db()
    manager = _Manager()
    _seed(Factory)
    patch_endpoint = _endpoint(manager, "/api/mcp/servers/{server_id}", "PATCH")
    with mock.patch("routes.mcp.mcp_routes.SessionLocal", Factory):
        out = asyncio.run(patch_endpoint(
            server_id="abcd1234", request=_FakeRequest(), is_enabled="false"))
    assert out == {"id": "abcd1234", "is_enabled": False}
    assert _row(Factory, "abcd1234")["command"] == "npx"
