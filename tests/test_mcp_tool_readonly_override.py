# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P8-48` — an MCP server that says nothing about its tools, and the operator
who knows better having nowhere to say so.

**MEASURED ON THE TREE BEFORE THE CHANGE.** `mcp_tool_is_readonly`
(`src/mcp_manager.py:585` at `HEAD`) took one argument — the tool — and reached
its verdict from the server's `annotations` if there were any and otherwise
from `name.startswith(_MCP_READONLY_VERBS)`, sixteen leading words. The MCP
specification makes `annotations` optional and most servers ship none, so for
most tools in a real install that verb list **is** the answer, and it is wrong
in both directions:

* `list_and_purge_orphans` starts with `list`, so the heuristic calls it
  read-only and plan mode runs a purge;
* `tail_log` starts with nothing in the list, so the heuristic calls it a write
  and plan mode refuses a read.

`McpServer` (`core/database.py:576-604` at `HEAD`) had `disabled_tools` and no
per-tool column, so the operator's only lever was to hide the tool from the
model entirely — which is not the same act and costs them the tool. There was
nowhere to record *what a tool actually does*, and both misreadings above are
reproduced below against the real functions before the override is used.

**What this file drives.** The storage (`McpServer.tool_overrides` and its
migration), the verdict (`readonly_verdict`, and `mcp_tool_is_readonly` on top
of it), the gate (`plan_mode_blocked_mcp`) and the display (`get_all_tools`,
`GET /api/mcp/servers/{id}/tools`) reading **one** answer, the write route, and
`manage_mcp list_tools`. Every case calls the code (`Law 20`); nothing here
reads a file to check a fix.

The single property this file exists to hold: **the badge the panel draws and
the decision plan mode makes come from the same call.** A panel that showed an
override the gate did not honour would be worse than no panel — a person told
their correction was recorded, with plan mode still running on a verb.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


class _FakeRequest:
    """Enough of a request for `require_admin` plus a JSON body.

    The documented in-process loopback header, so the case does not depend on
    whether auth happens to be configured where it runs. The gate itself is
    `FORBIDDEN.md` Part 2 and is asserted once, below, on the route this row
    adds a key to.
    """

    def __init__(self, body=None):
        from core.middleware import INTERNAL_TOOL_HEADER, INTERNAL_TOOL_TOKEN

        self.headers = {INTERNAL_TOOL_HEADER: INTERNAL_TOOL_TOKEN}
        self.state = SimpleNamespace(current_user="admin")
        self.app = SimpleNamespace(state=SimpleNamespace(auth_manager=None))
        self._body = body

    async def json(self):
        return self._body


# The two tools the heuristic gets wrong, and one the server does declare.
_TOOLS = [
    # `list…` — reads as read-only to the verb list, and purges.
    {"name": "list_and_purge_orphans", "description": "Purge orphaned rows",
     "input_schema": {"type": "object", "properties": {}}, "annotations": None},
    # `tail…` — reads as a write to the verb list, and only reads.
    {"name": "tail_log", "description": "Tail the log",
     "input_schema": {"type": "object", "properties": {}}, "annotations": None},
    # The server did its job on this one.
    {"name": "wipe", "description": "Wipe the volume",
     "input_schema": {"type": "object", "properties": {}},
     "annotations": {"readOnlyHint": False, "destructiveHint": True}},
]


def _manager(tools=None):
    """A real `McpManager` with its two maps filled and no transport."""
    from src.mcp_manager import McpManager

    mgr = McpManager.__new__(McpManager)
    mgr._tools = {"srv1": [dict(t) for t in (tools or _TOOLS)]}
    mgr._connections = {"srv1": {"name": "Ops"}}
    mgr._generation = 0            # the prompt cache key reads it
    mgr._cached_prompt_desc = None
    mgr._cached_prompt_desc_key = None
    return mgr


def _db():
    from core.database import Base
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _seed(Factory, **kw):
    from core.database import McpServer

    fields = dict(id="srv1", name="Ops", transport="stdio", command="npx",
                  args='["-y", "ops"]', env="{}", url=None, is_enabled=True,
                  disabled_tools=None, tool_overrides=None)
    fields.update(kw)
    db = Factory()
    try:
        db.add(McpServer(**fields))
        db.commit()
    finally:
        db.close()
    return fields["id"]


def _row(Factory, server_id="srv1"):
    from core.database import McpServer

    db = Factory()
    try:
        srv = db.query(McpServer).filter(McpServer.id == server_id).first()
        return None if srv is None else {
            "disabled_tools": srv.disabled_tools, "tool_overrides": srv.tool_overrides,
            "command": srv.command, "args": srv.args,
        }
    finally:
        db.close()


def _endpoint(manager, path, method):
    from routes.mcp.mcp_routes import setup_mcp_routes

    for route in setup_mcp_routes(manager).routes:
        if route.path == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"{method} {path} not found")


def _patch(Factory, manager, body, server_id="srv1"):
    import unittest.mock as mock

    endpoint = _endpoint(manager, "/api/mcp/servers/{server_id}/tools", "PATCH")
    with mock.patch("routes.mcp.mcp_routes.SessionLocal", Factory), \
            mock.patch("src.mcp_manager.SessionLocal", Factory):
        return asyncio.run(endpoint(server_id=server_id, request=_FakeRequest(body)))


# ---------------------------------------------------------------------------
# The premise: the verb list is the answer, and it is wrong both ways
# ---------------------------------------------------------------------------


def test_the_heuristic_is_the_answer_for_a_server_that_declares_nothing():
    """Both misreadings, driven through the function the gate calls."""
    from src.mcp_manager import mcp_tool_is_readonly

    purge = {"name": "list_and_purge_orphans", "annotations": None}
    tail = {"name": "tail_log", "annotations": None}

    assert mcp_tool_is_readonly(purge) is True, (
        "the premise moved: `list…` no longer reads as read-only"
    )
    assert mcp_tool_is_readonly(tail) is False, (
        "the premise moved: `tail…` no longer reads as a write"
    )


def test_plan_mode_ran_the_purge_and_refused_the_tail():
    """The consequence of the above, at the gate, with no override stored."""
    import unittest.mock as mock

    Factory = _db()
    _seed(Factory)
    mgr = _manager()
    with mock.patch("src.mcp_manager.SessionLocal", Factory):
        blocked, qualified = mgr.plan_mode_blocked_mcp()

    assert "list_and_purge_orphans" not in blocked.get("srv1", set()), (
        "plan mode would run the purge"
    )
    assert "tail_log" in blocked.get("srv1", set()), "plan mode refuses the read"
    assert "mcp__srv1__tail_log" in qualified


# ---------------------------------------------------------------------------
# The storage
# ---------------------------------------------------------------------------


def test_the_column_is_on_the_model_and_the_migration_adds_it_to_an_old_database(tmp_path):
    """A column declared and not migrated exists on fresh boxes and no others.

    Driven: a `mcp_servers` table is created **without** the column, the
    migration function is pointed at it, and the column is read back from
    `PRAGMA table_info`. Running it twice must be a no-op, because `init_db`
    runs every migration on every boot.
    """
    import unittest.mock as mock
    from core.database import McpServer
    import core.database as database

    assert "tool_overrides" in McpServer.__table__.columns, "the column is not declared"

    db_path = tmp_path / "old.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE mcp_servers (id TEXT PRIMARY KEY, name TEXT, transport TEXT, "
        "disabled_tools TEXT)"
    )
    conn.execute("INSERT INTO mcp_servers (id, name) VALUES ('srv1', 'Ops')")
    conn.commit()
    conn.close()

    from sqlalchemy import create_engine

    engine = create_engine(f"sqlite:///{db_path}")
    with mock.patch.object(database, "engine", engine):
        database._migrate_add_mcp_tool_overrides_column()
        database._migrate_add_mcp_tool_overrides_column()  # idempotent

    conn = sqlite3.connect(db_path)
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(mcp_servers)")]
        rows = list(conn.execute("SELECT id, tool_overrides FROM mcp_servers"))
    finally:
        conn.close()
    assert cols.count("tool_overrides") == 1
    assert rows == [("srv1", None)], "the existing row means 'no opinion'"


def test_the_migration_is_wired_into_init_db():
    """A migration nobody calls is a column that exists on fresh boxes only."""
    import inspect
    import core.database as database

    source = inspect.getsource(database.init_db)
    assert "_migrate_add_mcp_tool_overrides_column()" in source


def test_a_database_that_cannot_answer_reads_as_no_opinion():
    """`load_tool_overrides` is on the plan-mode path and must not raise.

    An install whose schema predates the column, or a unit test with no
    database at all, gets `{}` — which is also the fail-closed answer, because
    an absent override leaves the server's annotation and the heuristic in
    charge rather than granting anything.
    """
    import unittest.mock as mock
    from src.mcp_manager import load_tool_overrides

    def _boom():
        raise RuntimeError("no such column: mcp_servers.tool_overrides")

    with mock.patch("src.mcp_manager.SessionLocal", _boom):
        assert load_tool_overrides() == {}


@pytest.mark.parametrize("raw,expect", [
    (None, {}),
    ("", {}),
    ("   ", {}),
    ("not json", {}),
    ("[1,2]", {}),
    ('{"t": "read_only"}', {}),                       # value is not an object
    ('{"t": {}}', {}),                                # says nothing
    ('{"t": {"read_only": "yes"}}', {}),              # not a boolean
    ('{"t": {"colour": true}}', {}),                  # not a key we know
    ('{"": {"read_only": true}}', {}),                # not a tool name
    ('{"t": {"read_only": false}}', {"t": {"read_only": False}}),
    ('{"t": {"read_only": true, "colour": "red"}}', {"t": {"read_only": True}}),
])
def test_only_an_answer_we_understand_is_stored(raw, expect):
    """`normalize_tool_overrides` is the one reader of this column.

    The keys are closed on purpose: this value is written through a route and
    read on the plan-mode path, so an unrecognised key is dropped rather than
    carried — a typo must not become a silent no-op that looks saved.
    """
    from src.mcp_manager import normalize_tool_overrides

    assert normalize_tool_overrides(raw) == expect


# ---------------------------------------------------------------------------
# The verdict, and who reached it
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tool,override,expect,source", [
    # Nobody said: the verb decides, and says so.
    ({"name": "list_and_purge_orphans"}, None, True, "heuristic"),
    ({"name": "tail_log"}, None, False, "heuristic"),
    # The server said: it beats the verb, both ways.
    ({"name": "tail_log", "annotations": {"readOnlyHint": True}}, None, True, "annotation"),
    ({"name": "list_rows", "annotations": {"destructiveHint": True}}, None, False, "annotation"),
    # The operator said: it beats the server, both ways.
    ({"name": "tail_log"}, {"read_only": True}, True, "override"),
    ({"name": "list_and_purge_orphans"}, {"read_only": False}, False, "override"),
    ({"name": "wipe", "annotations": {"readOnlyHint": True}}, {"read_only": False}, False, "override"),
    ({"name": "wipe", "annotations": {"destructiveHint": True}}, {"read_only": True}, True, "override"),
    # An override that says nothing usable is not an override.
    ({"name": "tail_log"}, {"read_only": "yes"}, False, "heuristic"),
    ({"name": "tail_log"}, {}, False, "heuristic"),
])
def test_the_operator_beats_the_server_and_the_server_beats_the_guess(tool, override, expect, source):
    from src.mcp_manager import mcp_tool_is_readonly, readonly_verdict

    assert readonly_verdict(tool, override) == (expect, source)
    # The boolean-only spelling seven call sites use is the same call.
    assert mcp_tool_is_readonly(tool, override) is expect


def test_the_source_is_returned_and_never_re_derived():
    """Why `readonly_verdict` exists beside `mcp_tool_is_readonly`.

    `read_only: true` reached from a declaration and `read_only: true` reached
    from a leading verb are different facts, and the browser has to be able to
    say which. Re-deriving that distinction in JavaScript would be a second
    copy of this precedence rule that could not be kept in step with the gate.
    """
    from src.mcp_manager import readonly_verdict

    declared = {"name": "anything_at_all", "annotations": {"readOnlyHint": True}}
    guessed = {"name": "list_anything"}
    assert readonly_verdict(declared)[0] is readonly_verdict(guessed)[0] is True
    assert readonly_verdict(declared)[1] != readonly_verdict(guessed)[1]


# ---------------------------------------------------------------------------
# The gate and the panel read one answer
# ---------------------------------------------------------------------------


def test_the_override_moves_the_gate_and_the_panel_together():
    """The property this whole row rests on, driven end to end.

    Both misreadings from the premise are corrected in the database, and then
    `plan_mode_blocked_mcp` (the gate) and `get_all_tools` (what the panel is
    drawn from) are asked independently and must agree about all three tools.
    """
    import unittest.mock as mock

    Factory = _db()
    _seed(Factory, tool_overrides=json.dumps({
        "list_and_purge_orphans": {"read_only": False},
        "tail_log": {"read_only": True},
    }))
    mgr = _manager()

    with mock.patch("src.mcp_manager.SessionLocal", Factory):
        blocked, qualified = mgr.plan_mode_blocked_mcp()
        payload = mgr.get_all_tools()

    by_name = {t["name"]: t for t in payload}

    # The purge is now refused by plan mode, and the panel says so.
    assert "list_and_purge_orphans" in blocked["srv1"]
    assert "mcp__srv1__list_and_purge_orphans" in qualified
    assert by_name["list_and_purge_orphans"]["is_readonly"] is False
    assert by_name["list_and_purge_orphans"]["readonly_source"] == "override"
    assert by_name["list_and_purge_orphans"]["override"] == {"read_only": False}

    # The read is now allowed, and the panel says so.
    assert "tail_log" not in blocked.get("srv1", set())
    assert by_name["tail_log"]["is_readonly"] is True
    assert by_name["tail_log"]["readonly_source"] == "override"

    # The tool the server declared is untouched and still attributed to it.
    assert "wipe" in blocked["srv1"]
    assert by_name["wipe"]["is_readonly"] is False
    assert by_name["wipe"]["readonly_source"] == "annotation"
    assert by_name["wipe"]["annotations"]["destructiveHint"] is True
    assert by_name["wipe"]["override"] is None

    # And every entry agrees with the gate, tool for tool.
    for entry in payload:
        in_gate = entry["name"] in blocked.get("srv1", set())
        assert entry["is_readonly"] is not in_gate, (
            f"{entry['name']}: the panel and the gate disagree"
        )


def test_an_override_for_one_server_does_not_reach_a_tool_of_the_same_name_elsewhere():
    """A tool name is only unique inside a server, which is why this is per-row."""
    import unittest.mock as mock
    from src.mcp_manager import McpManager

    Factory = _db()
    _seed(Factory, tool_overrides=json.dumps({"tail_log": {"read_only": True}}))
    _seed(Factory, id="srv2", name="Other")

    mgr = McpManager.__new__(McpManager)
    mgr._tools = {"srv1": [{"name": "tail_log"}], "srv2": [{"name": "tail_log"}]}
    mgr._connections = {"srv1": {"name": "Ops"}, "srv2": {"name": "Other"}}

    with mock.patch("src.mcp_manager.SessionLocal", Factory):
        payload = {(t["server_id"], t["name"]): t for t in mgr.get_all_tools()}

    assert payload[("srv1", "tail_log")]["is_readonly"] is True
    assert payload[("srv2", "tail_log")]["is_readonly"] is False
    assert payload[("srv2", "tail_log")]["readonly_source"] == "heuristic"


def test_the_prompt_text_is_unchanged_and_pays_for_no_query():
    """`Law 1`. The system-prompt rendering reads none of the three new fields.

    Asserted by driving it with `SessionLocal` replaced by something that
    raises: if the prompt path loaded overrides it would blow up here.
    """
    import unittest.mock as mock

    def _boom():
        raise AssertionError("the prompt path loaded overrides it does not read")

    mgr = _manager()
    with mock.patch("src.mcp_manager.SessionLocal", _boom):
        text = mgr.get_tool_descriptions_for_prompt()
    assert "tail_log" in text and "wipe" in text


# ---------------------------------------------------------------------------
# The write route
# ---------------------------------------------------------------------------


def test_one_tools_answer_is_stored_without_disturbing_the_others():
    Factory = _db()
    _seed(Factory, tool_overrides=json.dumps({"wipe": {"read_only": False}}))
    mgr = _manager()

    out = _patch(Factory, mgr, {"overrides": {"tail_log": {"read_only": True}}})

    assert out["override_count"] == 2
    assert out["overrides"] == {
        "wipe": {"read_only": False}, "tail_log": {"read_only": True},
    }
    assert json.loads(_row(Factory)["tool_overrides"]) == out["overrides"]


def test_clearing_an_override_returns_the_tool_to_the_servers_own_word():
    """`null` (and `{}`) is the erase, which a two-state control cannot express.

    And the point of erasing: `wipe` goes back to `annotation`, not to
    `heuristic` — the browser could not have worked that out for itself, which
    is why it reads the verdict back instead of assuming.
    """
    import unittest.mock as mock

    Factory = _db()
    _seed(Factory, tool_overrides=json.dumps({"wipe": {"read_only": True}}))
    mgr = _manager()

    with mock.patch("src.mcp_manager.SessionLocal", Factory):
        before = {t["name"]: t for t in mgr.get_all_tools()}
    assert before["wipe"]["is_readonly"] is True
    assert before["wipe"]["readonly_source"] == "override"

    out = _patch(Factory, mgr, {"overrides": {"wipe": None}})
    assert out["override_count"] == 0
    assert _row(Factory)["tool_overrides"] is None, "no opinion has one spelling"

    with mock.patch("src.mcp_manager.SessionLocal", Factory):
        after = {t["name"]: t for t in mgr.get_all_tools()}
    assert after["wipe"]["is_readonly"] is False
    assert after["wipe"]["readonly_source"] == "annotation"

    # `{}` is the same erase.
    _patch(Factory, mgr, {"overrides": {"wipe": {"read_only": True}}})
    _patch(Factory, mgr, {"overrides": {"wipe": {}}})
    assert _row(Factory)["tool_overrides"] is None


def test_neither_key_wipes_the_other():
    """`Law 1`: the caller that sends only `disabled` keeps its old behaviour.

    A key that is absent is left alone — otherwise the existing checkbox save
    path, which has never heard of overrides, would erase one every time
    somebody toggled a tool off.
    """
    Factory = _db()
    _seed(Factory)
    mgr = _manager()

    _patch(Factory, mgr, {"overrides": {"tail_log": {"read_only": True}}})
    out = _patch(Factory, mgr, {"disabled": ["wipe"]})

    row = _row(Factory)
    assert json.loads(row["disabled_tools"]) == ["wipe"]
    assert json.loads(row["tool_overrides"]) == {"tail_log": {"read_only": True}}
    assert out["disabled_count"] == 1 and out["override_count"] == 1

    # And the other way round.
    out = _patch(Factory, mgr, {"overrides": {"wipe": {"read_only": False}}})
    row = _row(Factory)
    assert json.loads(row["disabled_tools"]) == ["wipe"], "the disabled list survived"
    assert out["disabled_count"] == 1


def test_an_override_does_not_re_enable_a_hidden_tool():
    """Two columns, two acts. Marking a tool read-only does not un-hide it."""
    import unittest.mock as mock

    Factory = _db()
    _seed(Factory, disabled_tools=json.dumps(["tail_log"]))
    mgr = _manager()

    _patch(Factory, mgr, {"overrides": {"tail_log": {"read_only": True}}})
    assert json.loads(_row(Factory)["disabled_tools"]) == ["tail_log"]

    from routes.mcp.mcp_routes import _load_disabled_map

    with mock.patch("routes.mcp.mcp_routes.SessionLocal", Factory), \
            mock.patch("src.mcp_manager.SessionLocal", Factory):
        payload = {t["name"]: t for t in mgr.get_all_tools(_load_disabled_map())}
    assert payload["tail_log"]["is_disabled"] is True
    assert payload["tail_log"]["is_readonly"] is True


@pytest.mark.parametrize("body,contains", [
    ({"overrides": []}, "keyed by tool name"),
    ({"overrides": {"tail_log": "read_only"}}, "tail_log"),
    ({"overrides": {"tail_log": {"read_only": "yes"}}}, "true or false"),
    ({"overrides": {"tail_log": {"destructive": True}}}, "read_only"),
    ({"disabled": "wipe"}, "list of tool names"),
])
def test_a_refusal_names_the_tool_and_the_key(body, contains):
    """Written for a person: which tool, which key, and what would have worked."""
    Factory = _db()
    _seed(Factory)
    with pytest.raises(HTTPException) as caught:
        _patch(Factory, _manager(), body)
    assert caught.value.status_code == 400
    assert contains in str(caught.value.detail)
    assert _row(Factory)["tool_overrides"] is None, "a refused body stored nothing"


def test_an_override_for_a_tool_the_server_does_not_offer_is_kept_and_reported():
    """Same honesty as `P8-35`'s `stale_disabled_tools`, on the write.

    Kept because a command pointed back must not have lost the answer; reported
    because the operator should learn it now, not when plan mode surprises them.
    """
    Factory = _db()
    _seed(Factory)
    out = _patch(Factory, _manager(), {"overrides": {
        "tail_log": {"read_only": True},
        "tial_log": {"read_only": True},   # a typo, kept and named
    }})
    assert out["unknown_tools"] == ["tial_log"]
    assert set(json.loads(_row(Factory)["tool_overrides"])) == {"tail_log", "tial_log"}


def test_a_non_admin_cannot_write_one():
    """`require_admin` — the `FORBIDDEN.md` Part 2 control, not a second gate."""
    import unittest.mock as mock

    Factory = _db()
    _seed(Factory)
    endpoint = _endpoint(_manager(), "/api/mcp/servers/{server_id}/tools", "PATCH")

    class _Stranger:
        headers = {}
        state = SimpleNamespace(current_user="bob")
        app = SimpleNamespace(state=SimpleNamespace(
            auth_manager=SimpleNamespace(is_configured=True, is_admin=lambda u: False)))

        async def json(self):
            return {"overrides": {"wipe": {"read_only": True}}}

    with mock.patch("routes.mcp.mcp_routes.SessionLocal", Factory), \
            mock.patch("core.middleware.auth_disabled", return_value=False):
        with pytest.raises(HTTPException) as caught:
            asyncio.run(endpoint(server_id="srv1", request=_Stranger()))
    assert caught.value.status_code == 403
    assert _row(Factory)["tool_overrides"] is None, "it was written before the gate"


def test_an_unknown_server_is_404_and_not_a_new_row():
    Factory = _db()
    with pytest.raises(HTTPException) as caught:
        _patch(Factory, _manager(), {"overrides": {"wipe": {"read_only": True}}}, server_id="nope")
    assert caught.value.status_code == 404
    assert _row(Factory, "nope") is None


# ---------------------------------------------------------------------------
# An edit keeps it — `P8-35`'s ruling, extended
# ---------------------------------------------------------------------------


def _put(Factory, manager, **overrides):
    import unittest.mock as mock

    fields = {f: None for f in
              ("name", "transport", "command", "args", "env", "url", "oauth_config")}
    fields.update(overrides)
    endpoint = _endpoint(manager, "/api/mcp/servers/{server_id}", "PUT")
    with mock.patch("routes.mcp.mcp_routes.SessionLocal", Factory), \
            mock.patch("src.mcp_manager.SessionLocal", Factory):
        return asyncio.run(endpoint(server_id="srv1", request=_FakeRequest(), **fields))


class _EditManager:
    """Enough manager for `PUT`, with the tool list changing on reconnect."""

    def __init__(self, after):
        self.after = list(after)
        self.names = [t["name"] for t in _TOOLS]

    async def connect_server(self, server_id, name, transport, command=None,
                             args=None, env=None, url=None):
        self.names = list(self.after)
        return True

    async def disconnect_server(self, server_id):
        pass

    def get_server_status(self, server_id):
        return {"status": "connected", "name": "Ops", "tool_count": len(self.names)}

    def get_all_tools(self, disabled_map=None, overrides=None):
        return [{"server_id": "srv1", "name": n} for n in self.names]


def test_an_edit_keeps_the_override_and_names_the_ones_that_went_stale():
    """`P8-35`: an id is an identity, not a version — and so is this column.

    Fixing a path in the command line must not quietly return a tool the
    operator marked as writing to the server's word or to a guess at its name.
    """
    Factory = _db()
    _seed(Factory, tool_overrides=json.dumps({
        "tail_log": {"read_only": True},
        "list_and_purge_orphans": {"read_only": False},
    }), disabled_tools=json.dumps(["wipe"]))

    # The new command offers `tail_log` and nothing else.
    out = _put(Factory, _EditManager(["tail_log"]), command="npx", args='["-y", "ops@2"]')

    assert out["id"] == "srv1" and out["id_changed"] is False
    assert out["tool_overrides_kept"] == 2
    assert out["stale_tool_overrides"] == ["list_and_purge_orphans"]
    assert out["stale_disabled_tools"] == ["wipe"]

    row = _row(Factory)
    assert row["args"] == '["-y", "ops@2"]', "the edit landed"
    assert json.loads(row["tool_overrides"]) == {
        "tail_log": {"read_only": True},
        "list_and_purge_orphans": {"read_only": False},
    }, "a name the new command does not offer is kept, not deleted"
    assert json.loads(row["disabled_tools"]) == ["wipe"]


# ---------------------------------------------------------------------------
# What the browser and the model are handed
# ---------------------------------------------------------------------------


def test_the_tools_route_carries_the_verdict_its_source_and_the_override():
    """`GET /api/mcp/servers/{id}/tools` — the one payload the panel is drawn from."""
    import unittest.mock as mock

    Factory = _db()
    _seed(Factory, tool_overrides=json.dumps({"tail_log": {"read_only": True}}),
          disabled_tools=json.dumps(["wipe"]))
    mgr = _manager()
    endpoint = _endpoint(mgr, "/api/mcp/servers/{server_id}/tools", "GET")

    with mock.patch("routes.mcp.mcp_routes.SessionLocal", Factory), \
            mock.patch("src.mcp_manager.SessionLocal", Factory):
        payload = endpoint(server_id="srv1", request=_FakeRequest())

    by_name = {t["name"]: t for t in payload}
    assert by_name["tail_log"]["readonly_source"] == "override"
    assert by_name["tail_log"]["override"] == {"read_only": True}
    assert by_name["wipe"]["readonly_source"] == "annotation"
    assert by_name["wipe"]["annotations"] == {"readOnlyHint": False, "destructiveHint": True}
    assert by_name["wipe"]["is_disabled"] is True
    assert by_name["list_and_purge_orphans"]["readonly_source"] == "heuristic"
    # Everything the read half of this row put on the wire is still there.
    assert set(by_name["wipe"]) >= {
        "qualified_name", "input_schema", "description", "is_readonly", "is_disabled",
    }


def test_manage_mcp_says_where_its_read_only_answer_came_from():
    """The model and the operator cannot be told different things (`Law 13`)."""
    import unittest.mock as mock
    from src.agent_tools.admin_tools import do_manage_mcp

    Factory = _db()
    _seed(Factory, tool_overrides=json.dumps({"tail_log": {"read_only": True}}))
    mgr = _manager()

    with mock.patch("src.agent_tools.admin_tools.get_mcp_manager", return_value=mgr), \
            mock.patch("src.mcp_manager.SessionLocal", Factory):
        out = asyncio.run(do_manage_mcp(json.dumps({"action": "list_tools"})))

    by_name = {t["name"]: t for t in out["tools"]}
    assert by_name["tail_log"]["read_only"] is True
    assert by_name["tail_log"]["read_only_source"] == "override"
    assert by_name["tail_log"]["override"] == {"read_only": True}
    assert by_name["wipe"]["read_only_source"] == "annotation"
    assert by_name["list_and_purge_orphans"]["read_only_source"] == "heuristic"
    assert "override" not in by_name["wipe"], "a tool nobody corrected says nothing"
