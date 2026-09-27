# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P8-48`, re-cut 2026-09-27 (`D-2026-09-27-02`) — what the model reads about
an MCP tool, and an operator who knows better having somewhere to say so.

**What the row asked for, and why half of it is dropped.** The row asked for a
*tool schema editor*. Measured before a line was written: `McpManager.call_tool`
(`src/mcp_manager.py`) hands `arguments` to `session.call_tool` with no
client-side check of any kind, and the MCP server enforces its own
`inputSchema`. So an edited schema changes only what the model is *told* —
narrowing it refuses nothing the server would accept, widening it produces a
server-side error whose cause the operator cannot see. The first case below
drives `call_tool` with arguments the tool's own schema forbids and shows them
arriving at the session untouched; that is the measurement, pinned, so the
day somebody adds client-side validation this file says the decision should be
looked at again.

What *is* worth overriding is how a tool is **described**, because that is the
one thing the model reads to decide whether to call it — and a third-party
server's description is often a single word, or wrong about this install. The
override is stored beside `read_only` on `McpServer.tool_overrides`, one
column, one reader (`normalize_tool_overrides`), one verdict
(`description_verdict`), and it reaches the model in every channel the model
reads a tool through:

* the function schema (`get_all_openai_schemas`), which is what a native
  tool-calling model is handed;
* the MCP block of the prompt (`get_tool_descriptions_for_prompt`), which is
  also the text `src/tool_index.py` indexes for retrieval;
* `manage_mcp list_tools`, the model's own view of its tools.

A description the function schema carried and the prompt block did not would
tell the model two different things about one tool in the same turn, so the
three are asserted to agree (`Law 13`).

**Found on the way and fixed here:** an override for a tool whose name was
longer than 40 characters was stored under a truncated key
(`…_with_permi…`) that no tool name could ever match, so the operator's answer
was accepted with a 200 and then silently ignored — including by plan mode.
The first read-only case below reproduces it.

Every case calls the code (`Law 20`).
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


# ---------------------------------------------------------------------------
# Harness — the same shape `tests/test_mcp_tool_readonly_override.py` uses
# ---------------------------------------------------------------------------


class _FakeRequest:
    def __init__(self, body=None):
        from core.middleware import INTERNAL_TOOL_HEADER, INTERNAL_TOOL_TOKEN

        self.headers = {INTERNAL_TOOL_HEADER: INTERNAL_TOOL_TOKEN}
        self.state = SimpleNamespace(current_user="admin")
        self.app = SimpleNamespace(state=SimpleNamespace(auth_manager=None))
        self._body = body

    async def json(self):
        return self._body


_TOOLS = [
    {"name": "query", "description": "Run a query",
     "input_schema": {"type": "object",
                      "properties": {"sql": {"type": "string"}},
                      "required": ["sql"]},
     "annotations": None},
    {"name": "wipe", "description": "Wipe the volume",
     "input_schema": {"type": "object", "properties": {}},
     "annotations": {"readOnlyHint": False, "destructiveHint": True}},
]

_BETTER = ("Read-only SQL against the reporting replica. Use it for questions "
           "about sales figures; it cannot change anything.")


def _manager(tools=None):
    from src.mcp_manager import McpManager

    mgr = McpManager.__new__(McpManager)
    mgr._tools = {"srv1": [dict(t) for t in (tools or _TOOLS)]}
    mgr._connections = {"srv1": {"name": "Ops"}}
    mgr._generation = 0
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


def _stored(Factory, server_id="srv1"):
    from core.database import McpServer

    db = Factory()
    try:
        srv = db.query(McpServer).filter(McpServer.id == server_id).first()
        return json.loads(srv.tool_overrides) if srv and srv.tool_overrides else None
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


def _schemas(mgr, Factory):
    import unittest.mock as mock

    with mock.patch("src.mcp_manager.SessionLocal", Factory):
        return {s["function"]["name"]: s["function"] for s in mgr.get_all_openai_schemas({})}


def _prompt(mgr, Factory):
    import unittest.mock as mock

    with mock.patch("src.mcp_manager.SessionLocal", Factory):
        return mgr.get_tool_descriptions_for_prompt({})


# ---------------------------------------------------------------------------
# Why there is no schema editor: the measurement, pinned
# ---------------------------------------------------------------------------


def test_call_tool_hands_the_server_arguments_its_own_schema_forbids():
    """The reason the input-schema editor was dropped, driven.

    `query` declares one required string, `sql`. It is called with a number
    for `sql` and an argument it never declared, and the session receives both
    exactly as sent. Nothing on Pantheon's side reads `input_schema` before a
    call, so an edited schema could only change what the model is told: the
    server is the one that enforces it.
    """
    received = []

    class _Session:
        async def call_tool(self, name, arguments):
            received.append((name, arguments))
            return SimpleNamespace(content=[SimpleNamespace(text="ok")], isError=False)

    mgr = _manager()
    mgr._sessions = {"srv1": _Session()}
    sent = {"sql": 5, "not_in_the_schema": True}
    out = asyncio.run(mgr.call_tool("mcp__srv1__query", sent))

    assert out["exit_code"] == 0
    assert received == [("query", sent)], (
        "call_tool now inspects arguments against input_schema — the premise that "
        "dropped P8-48's schema editor has changed; re-read the row"
    )


# ---------------------------------------------------------------------------
# The stored shape
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value,expect", [
    ("  A better sentence.  ", "A better sentence."),
    ("line one\r\nline two", "line one\nline two"),
    ("tab\tkept, bell\x07 and nul\x00 gone", "tab\tkept, bell and nul gone"),
    ("<b>not markup</b> & plain", "<b>not markup</b> & plain"),
    ("", None),
    ("   \n\t ", None),
    (42, None),
    (None, None),
    (["a"], None),
])
def test_a_description_is_read_as_plain_text_or_not_at_all(value, expect):
    """One reader for the value, the same on the write and on every read.

    Markup is kept as the characters it is. The browser draws the value with
    `textContent` and the model reads it as text, so escaping it here would
    store something other than what the operator typed.
    """
    from src.mcp_manager import normalize_tool_overrides

    out = normalize_tool_overrides({"query": {"description": value}})
    if expect is None:
        assert out == {}
    else:
        assert out == {"query": {"description": expect}}


def test_a_description_is_stored_beside_the_read_only_answer():
    from src.mcp_manager import normalize_tool_overrides

    raw = json.dumps({"query": {"read_only": True, "description": _BETTER}})
    assert normalize_tool_overrides(raw) == {
        "query": {"read_only": True, "description": _BETTER},
    }


def test_a_hand_edited_row_past_the_cap_is_cut_at_the_cap_and_no_further():
    """The route refuses an over-long description; this is the backstop for a
    row written some other way, so a prompt can never carry an unbounded one."""
    from src.mcp_manager import MCP_TOOL_DESCRIPTION_MAX, normalize_tool_overrides

    out = normalize_tool_overrides({"query": {"description": "x" * (MCP_TOOL_DESCRIPTION_MAX + 50)}})
    assert len(out["query"]["description"]) == MCP_TOOL_DESCRIPTION_MAX


def test_a_long_tool_name_keeps_its_override():
    """Found while extending the column, and fixed here.

    Tool names were passed through `_sanitize_schema_token(name, 40)`, so a
    46-character name was stored as `list_repository_collaborators_with_permi…`
    — a key no tool is called. The operator marked it as writing, got a 200,
    and plan mode still ran it on the verb heuristic (`list…` reads as
    read-only).
    """
    from src.mcp_manager import normalize_tool_overrides

    name = "list_repository_collaborators_with_permissions"
    assert len(name) > 40
    mgr = _manager([{"name": name, "description": "Lists collaborators"}])
    overrides = {"srv1": normalize_tool_overrides({name: {"read_only": False, "description": _BETTER}})}

    entry = mgr.get_all_tools(overrides=overrides)[0]
    assert entry["readonly_source"] == "override"
    assert entry["is_readonly"] is False
    assert entry["description"] == _BETTER

    blocked = _gate(mgr, overrides)
    assert name in blocked.get("srv1", set()), "plan mode ignored the operator's answer"


def _gate(mgr, overrides):
    import unittest.mock as mock

    with mock.patch("src.mcp_manager.load_tool_overrides", return_value=overrides):
        return mgr.plan_mode_blocked_mcp()[0]


@pytest.mark.parametrize("name", [
    "x" * 129,           # past the cap: refused at the route, dropped on read
    "tail\x00log",       # a control character is not part of any name we can match
    "   ",
    "",
])
def test_a_name_that_cannot_be_a_tool_name_is_not_stored(name):
    from src.mcp_manager import normalize_tool_overrides

    assert normalize_tool_overrides({name: {"read_only": True}}) == {}


# ---------------------------------------------------------------------------
# One verdict
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("override,expect", [
    (None, ("Run a query", "server")),
    ({}, ("Run a query", "server")),
    ({"read_only": True}, ("Run a query", "server")),
    ({"description": _BETTER}, (_BETTER, "override")),
    ({"description": "   "}, ("Run a query", "server")),
    ({"description": 7}, ("Run a query", "server")),
])
def test_the_operator_wins_over_the_server_and_says_so(override, expect):
    from src.mcp_manager import description_verdict

    assert description_verdict(_TOOLS[0], override) == expect


# ---------------------------------------------------------------------------
# What the model reads — every channel, and they agree
# ---------------------------------------------------------------------------


def test_the_function_schema_carries_the_operators_words():
    Factory = _db()
    _seed(Factory, tool_overrides=json.dumps({"query": {"description": _BETTER}}))
    schemas = _schemas(_manager(), Factory)

    assert schemas["mcp__srv1__query"]["description"] == f"[MCP:Ops] {_BETTER}"
    # A tool nobody rewrote keeps the server's own description.
    assert schemas["mcp__srv1__wipe"]["description"] == "[MCP:Ops] Wipe the volume"
    # Only the description moved; the parameters are still the server's.
    assert schemas["mcp__srv1__query"]["parameters"] == _TOOLS[0]["input_schema"]


def test_with_nothing_stored_the_schema_is_what_it_always_was():
    Factory = _db()
    _seed(Factory)
    schemas = _schemas(_manager(), Factory)
    assert schemas["mcp__srv1__query"]["description"] == "[MCP:Ops] Run a query"


def test_the_prompt_block_carries_the_operators_words_too():
    """The second channel, and the one `src/tool_index.py` indexes."""
    Factory = _db()
    _seed(Factory, tool_overrides=json.dumps({"query": {"description": "Sales SQL, read-only"}}))
    text = _prompt(_manager(), Factory)

    assert "mcp__srv1__query: Sales SQL, read-only" in text
    assert "Run a query" not in text, "the server's words and the operator's both reached the model"


def test_the_schema_and_the_prompt_never_tell_the_model_two_things():
    """`Law 13`: one tool, one description, in every channel the model reads."""
    Factory = _db()
    _seed(Factory, tool_overrides=json.dumps({"query": {"description": "Sales SQL, read-only"}}))
    mgr = _manager()
    schemas = _schemas(mgr, Factory)
    text = _prompt(mgr, Factory)

    for qualified, fn in schemas.items():
        told = fn["description"].split("] ", 1)[1]
        assert f"{qualified}: {told[:120]}" in text, (qualified, told)


def test_an_override_is_scoped_to_its_own_server():
    """A tool name is only unique inside a server."""
    from src.mcp_manager import McpManager

    Factory = _db()
    _seed(Factory, tool_overrides=json.dumps({"query": {"description": _BETTER}}))
    _seed(Factory, id="srv2", name="Other")
    mgr = McpManager.__new__(McpManager)
    mgr._tools = {"srv1": [dict(_TOOLS[0])], "srv2": [dict(_TOOLS[0])]}
    mgr._connections = {"srv1": {"name": "Ops"}, "srv2": {"name": "Other"}}
    schemas = _schemas(mgr, Factory)

    assert schemas["mcp__srv1__query"]["description"].endswith(_BETTER)
    assert schemas["mcp__srv2__query"]["description"] == "[MCP:Other] Run a query"


def test_the_panel_payload_says_whose_words_these_are():
    import unittest.mock as mock
    from src.mcp_manager import MCP_TOOL_DESCRIPTION_MAX

    Factory = _db()
    _seed(Factory, tool_overrides=json.dumps({"query": {"description": _BETTER}}))
    with mock.patch("src.mcp_manager.SessionLocal", Factory):
        by_name = {t["name"]: t for t in _manager().get_all_tools()}

    assert by_name["query"]["description"] == _BETTER
    assert by_name["query"]["server_description"] == "Run a query"
    assert by_name["query"]["description_source"] == "override"
    assert by_name["query"]["description_max"] == MCP_TOOL_DESCRIPTION_MAX
    assert by_name["wipe"]["description"] == by_name["wipe"]["server_description"] == "Wipe the volume"
    assert by_name["wipe"]["description_source"] == "server"


def test_manage_mcp_hands_the_model_the_same_words():
    """The model's own view of its tools cannot disagree with its prompt."""
    import unittest.mock as mock
    from src.agent_tools.admin_tools import do_manage_mcp

    Factory = _db()
    _seed(Factory, tool_overrides=json.dumps({"query": {"description": _BETTER}}))
    mgr = _manager()
    with mock.patch("src.agent_tools.admin_tools.get_mcp_manager", return_value=mgr), \
            mock.patch("src.mcp_manager.SessionLocal", Factory):
        out = asyncio.run(do_manage_mcp(json.dumps({"action": "list_tools"})))

    by_name = {t["name"]: t for t in out["tools"]}
    assert by_name["query"]["description"] == _BETTER
    assert by_name["query"]["description_source"] == "override"
    assert "description_source" not in by_name["wipe"], "a tool nobody rewrote says nothing"


# ---------------------------------------------------------------------------
# The prompt cache: a write is seen at once, a hit costs nothing
# ---------------------------------------------------------------------------


class _Counting:
    """A session factory that counts how often the prompt path opens one."""

    def __init__(self, Factory):
        self.Factory = Factory
        self.opened = 0

    def __call__(self):
        self.opened += 1
        return self.Factory()


def test_a_saved_description_reaches_the_next_prompt_without_a_restart():
    """The prompt text is cached on the manager's generation, and so is the
    tool index. A write that did not move the generation would sit behind a
    cache until something else happened to reconnect."""
    import unittest.mock as mock

    Factory = _db()
    _seed(Factory)
    mgr = _manager()
    before = _prompt(mgr, Factory)
    assert "Run a query" in before

    _patch(Factory, mgr, {"overrides": {"query": {"description": "Sales SQL, read-only"}}})

    after = _prompt(mgr, Factory)
    assert "mcp__srv1__query: Sales SQL, read-only" in after
    assert mgr._generation >= 1, "the tool index keys its re-index on this counter"

    counting = _Counting(Factory)
    with mock.patch("src.mcp_manager.SessionLocal", counting):
        again = mgr.get_tool_descriptions_for_prompt({})
    assert again == after
    assert counting.opened == 0, "a cache hit opened a database session"


def test_saving_only_a_read_only_answer_does_not_re_index_the_tools():
    """The generation is the tool index's re-embed signal. A change that does
    not alter any text the model reads must not cost a re-embed of every tool."""
    Factory = _db()
    _seed(Factory)
    mgr = _manager()
    _patch(Factory, mgr, {"overrides": {"query": {"read_only": True}}})
    assert mgr._generation == 0


# ---------------------------------------------------------------------------
# The write route
# ---------------------------------------------------------------------------


def test_a_description_is_saved_without_disturbing_the_read_only_answer():
    Factory = _db()
    _seed(Factory, tool_overrides=json.dumps({"query": {"read_only": True}}))
    out = _patch(Factory, _manager(), {"overrides": {"query": {"description": _BETTER}}})

    assert out["overrides"] == {"query": {"read_only": True, "description": _BETTER}}
    assert _stored(Factory) == out["overrides"]


def test_a_read_only_answer_is_saved_without_disturbing_the_description():
    Factory = _db()
    _seed(Factory, tool_overrides=json.dumps({"query": {"description": _BETTER}}))
    _patch(Factory, _manager(), {"overrides": {"query": {"read_only": False}}})
    assert _stored(Factory) == {"query": {"read_only": False, "description": _BETTER}}


def test_null_takes_back_one_answer_and_leaves_the_other():
    """Per key. `Server's answer` on the read-only buttons must not take the
    operator's wording with it, and `Use the server's` on the wording must not
    take the read-only answer."""
    Factory = _db()
    both = {"query": {"read_only": True, "description": _BETTER}}
    _seed(Factory, tool_overrides=json.dumps(both))
    mgr = _manager()

    _patch(Factory, mgr, {"overrides": {"query": {"description": None}}})
    assert _stored(Factory) == {"query": {"read_only": True}}

    _patch(Factory, mgr, {"overrides": {"query": {"description": _BETTER}}})
    _patch(Factory, mgr, {"overrides": {"query": {"read_only": None}}})
    assert _stored(Factory) == {"query": {"description": _BETTER}}

    # Taking back the last answer leaves no entry at all: one spelling of "none".
    _patch(Factory, mgr, {"overrides": {"query": {"description": None}}})
    assert _stored(Factory) is None


def test_the_whole_entry_erase_still_erases_the_whole_entry():
    """`Law 1`: `{"tool": null}` and `{"tool": {}}` keep their old meaning."""
    Factory = _db()
    _seed(Factory, tool_overrides=json.dumps({"query": {"read_only": True, "description": _BETTER}}))
    mgr = _manager()
    _patch(Factory, mgr, {"overrides": {"query": None}})
    assert _stored(Factory) is None

    _patch(Factory, mgr, {"overrides": {"query": {"read_only": True, "description": _BETTER}}})
    _patch(Factory, mgr, {"overrides": {"query": {}}})
    assert _stored(Factory) is None


@pytest.mark.parametrize("value,contains", [
    (7, "must be text"),
    (["a"], "must be text"),
    ("", "send null"),
    ("   \n ", "send null"),
])
def test_a_description_that_is_not_text_is_refused_and_says_what_would_work(value, contains):
    Factory = _db()
    _seed(Factory)
    with pytest.raises(HTTPException) as caught:
        _patch(Factory, _manager(), {"overrides": {"query": {"description": value}}})
    assert caught.value.status_code == 400
    assert contains in str(caught.value.detail)
    assert "query" in str(caught.value.detail), "the refusal names the tool"
    assert _stored(Factory) is None


def test_an_over_long_description_is_refused_with_both_numbers():
    """Refused, not truncated: storing less than the operator typed, with a
    200, would be the silent kind of wrong."""
    from src.mcp_manager import MCP_TOOL_DESCRIPTION_MAX

    Factory = _db()
    _seed(Factory)
    text = "y" * (MCP_TOOL_DESCRIPTION_MAX + 1)
    with pytest.raises(HTTPException) as caught:
        _patch(Factory, _manager(), {"overrides": {"query": {"description": text}}})
    detail = str(caught.value.detail)
    assert caught.value.status_code == 400
    assert str(MCP_TOOL_DESCRIPTION_MAX + 1) in detail and str(MCP_TOOL_DESCRIPTION_MAX) in detail
    assert _stored(Factory) is None

    # And exactly at the cap is fine.
    out = _patch(Factory, _manager(), {"overrides": {"query": {"description": "y" * MCP_TOOL_DESCRIPTION_MAX}}})
    assert len(out["overrides"]["query"]["description"]) == MCP_TOOL_DESCRIPTION_MAX


def test_the_unknown_key_refusal_names_both_keys():
    Factory = _db()
    _seed(Factory)
    with pytest.raises(HTTPException) as caught:
        _patch(Factory, _manager(), {"overrides": {"query": {"schema": {}}}})
    detail = str(caught.value.detail)
    assert "read_only" in detail and "description" in detail


def test_a_name_past_the_cap_is_refused_rather_than_stored_under_another_key():
    Factory = _db()
    _seed(Factory)
    with pytest.raises(HTTPException) as caught:
        _patch(Factory, _manager(), {"overrides": {"q" * 129: {"read_only": True}}})
    assert caught.value.status_code == 400
    assert "128" in str(caught.value.detail)
    assert _stored(Factory) is None


def test_markup_is_stored_as_the_characters_it_is():
    Factory = _db()
    _seed(Factory)
    text = 'Say "hi" <img src=x onerror=alert(1)> & run'
    out = _patch(Factory, _manager(), {"overrides": {"query": {"description": text}}})
    assert out["overrides"]["query"]["description"] == text


def test_a_non_admin_cannot_rewrite_what_the_model_is_told():
    """`require_admin` — the same `FORBIDDEN.md` Part 2 gate the route had."""
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
            return {"overrides": {"query": {"description": "call me for everything"}}}

    with mock.patch("routes.mcp.mcp_routes.SessionLocal", Factory), \
            mock.patch("core.middleware.auth_disabled", return_value=False):
        with pytest.raises(HTTPException) as caught:
            asyncio.run(endpoint(server_id="srv1", request=_Stranger()))
    assert caught.value.status_code == 403
    assert _stored(Factory) is None


def test_an_edit_to_the_command_keeps_the_wording():
    """`P8-35`'s ruling: the id is an identity, and so is what the operator
    said about its tools."""
    import unittest.mock as mock

    Factory = _db()
    _seed(Factory, tool_overrides=json.dumps({"query": {"description": _BETTER}}))

    class _EditManager:
        async def connect_server(self, *a, **k):
            return True

        async def disconnect_server(self, server_id):
            pass

        def get_server_status(self, server_id):
            return {"status": "connected", "tool_count": 1}

        def get_all_tools(self, disabled_map=None, overrides=None):
            return [{"server_id": "srv1", "name": "query"}]

    fields = {f: None for f in ("name", "transport", "command", "args", "env", "url", "oauth_config")}
    fields["args"] = '["-y", "ops@2"]'
    endpoint = _endpoint(_EditManager(), "/api/mcp/servers/{server_id}", "PUT")
    with mock.patch("routes.mcp.mcp_routes.SessionLocal", Factory):
        out = asyncio.run(endpoint(server_id="srv1", request=_FakeRequest(), **fields))

    assert out["tool_overrides_kept"] == 1
    assert _stored(Factory) == {"query": {"description": _BETTER}}
