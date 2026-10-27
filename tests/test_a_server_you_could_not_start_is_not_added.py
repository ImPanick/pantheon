# SPDX-License-Identifier: AGPL-3.0-or-later
"""Upstream `#6215`, taken as a fix — and the two neighbours it left behind.

`D-2026-09-12-01`: *"Cherry-pick fixes, skip the rest."* Upstream `9d5c0319`
is a fix, and the reasoning in it is worth more than the diff:

    an unparseable value is silently discarded downstream (stdio spawns with
    an empty argv), so the caller must be told instead

**THAT ARGUMENT DOES NOT STOP AT `args`.** One line below it `env` did the same
thing, and four lines below that `oauth_config` did it with a bare `pass`. All
three are the same shape: a malformed value is dropped, the server is saved
anyway, and the operator is told it was **added**. What they then have is a
server that cannot work, failing as something else entirely — an empty argv
reads as a broken package, an empty env reads as a bad token, a dropped OAuth
config reads as the provider refusing. The typo is the one explanation nobody
reaches for, because the form said it worked.

So the fix is taken and extended. Fixing the field an issue names and leaving
its neighbours is `Law 13` in miniature.

**AND THE SHAPE A CLIENT-SIDE GUARD CANNOT CATCH.** `args=5` is valid JSON. It
parses, reaches `StdioServerParameters(args=5)` and 500s inside the error
formatter — so `JSON.parse` in the browser is not the check, it is the faster
half of it. The type assertion lives on the server.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SETTINGS_JS = ROOT / "static" / "js" / "settings.js"


class _FakeRequest:
    """Enough of a request for `require_admin`, via the documented loopback path.

    `require_admin` honours `X-Pantheon-Internal-Token` for in-process tool
    calls; using it here keeps the test independent of whether auth happens to
    be configured in the environment it runs in. The admin gate itself is
    `FORBIDDEN.md` Part 2 and is pinned elsewhere — this file is about what the
    route does *after* it lets you in.
    """

    def __init__(self):
        from core.middleware import INTERNAL_TOOL_HEADER, INTERNAL_TOOL_TOKEN

        self.headers = {INTERNAL_TOOL_HEADER: INTERNAL_TOOL_TOKEN}
        self.state = SimpleNamespace(current_user="admin")
        # `B1175`: on the loopback `require_admin` asks about the person the
        # request names, as their own request is asked — this one names the
        # admin, so the app knows them as one.
        self.app = SimpleNamespace(state=SimpleNamespace(auth_manager=SimpleNamespace(
            is_configured=True, is_admin=lambda user: user == "admin")))


class _NeverConnects:
    """An `McpManager` that refuses to launch anything.

    The point of the route is what it does with the *values*; actually
    spawning `npx` would make this test a network and subprocess test, and the
    valid-input cases are the ones that would reach the spawn.
    """

    async def connect_server(self, **kwargs):
        self.last = kwargs
        return False

    def get_server_status(self, server_id):
        return {"status": "disconnected", "tool_count": 0, "error": None}


def _add_server_endpoint(manager=None):
    from routes.mcp.mcp_routes import setup_mcp_routes

    router = setup_mcp_routes(manager or _NeverConnects())
    for route in router.routes:
        if route.path == "/api/mcp/servers" and "POST" in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError("add_server route not found")


def _add(**kwargs):
    """Call the endpoint with every Form parameter supplied.

    Calling an endpoint function directly bypasses FastAPI's dependency
    resolution, so an unpassed `Form(...)` parameter arrives as the marker
    object itself rather than its declared default — and `if oauth_file:` reads
    that marker as truthy. Upstream hit exactly this in CI. Not a production
    bug; a real request resolves these before `add_server` runs.
    """
    import unittest.mock as mock

    from core.database import Base
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    # `B1223`: the routes read and write in a worker thread now, and an in-memory
    # SQLite is one per connection — one connection for every thread.
    from sqlalchemy.pool import StaticPool
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Factory = sessionmaker(bind=engine)

    fields = {
        "name": "srv", "transport": "stdio", "command": "npx",
        "args": "[]", "env": "{}", "url": "", "oauth_file": "",
        "oauth_config": "",
    }
    fields.update(kwargs)
    manager = _NeverConnects()
    endpoint = _add_server_endpoint(manager)
    with mock.patch("routes.mcp.mcp_routes.SessionLocal", Factory):
        result = asyncio.run(endpoint(request=_FakeRequest(), **fields))
    result["_spawned_with"] = getattr(manager, "last", None)
    return result


# --------------------------------------------------------------------------
# The three fields, and the same rule on each
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field,bad",
    [
        ("args", "[-y, pkg]"),          # unquoted — the typo a person makes
        ("args", "['-y']"),             # single quotes — the other one
        ("env", '{"API_KEY": "x"'),     # unclosed brace
        ("oauth_config", "{not json}"),
    ],
)
def test_unparseable_json_is_refused_rather_than_dropped(field, bad):
    with pytest.raises(HTTPException) as caught:
        _add(**{field: bad})
    assert caught.value.status_code == 400
    assert field in caught.value.detail
    assert "valid JSON" in caught.value.detail


@pytest.mark.parametrize(
    "field,bad",
    [("args", "5"), ("args", '"-y"'), ("args", '{"a": 1}'),
     ("env", "5"), ("env", '["API_KEY"]')],
)
def test_valid_json_of_the_wrong_shape_is_refused(field, bad):
    """The case the browser's `JSON.parse` guard cannot see.

    `args=5` parses cleanly, reaches `StdioServerParameters(args=5)` and 500s
    in the error formatter — a rejection that arrives as a server fault.
    """
    with pytest.raises(HTTPException) as caught:
        _add(**{field: bad})
    assert caught.value.status_code == 400
    assert field in caught.value.detail
    assert "JSON array" in caught.value.detail or "JSON object" in caught.value.detail


def test_the_message_shows_the_shape_that_would_have_worked():
    """`Law 15`. *"args must be valid JSON"* tells somebody what they already know."""
    with pytest.raises(HTTPException) as caught:
        _add(args="[-y, pkg]")
    assert '["-y", "pkg"]' in caught.value.detail


# --------------------------------------------------------------------------
# What must keep working
# --------------------------------------------------------------------------


def test_a_valid_args_array_is_still_accepted():
    result = _add(args='["-y", "@modelcontextprotocol/server-filesystem"]')
    assert result.get("id")


def test_an_empty_field_still_means_the_empty_default():
    """`Law 1`. Blank is not malformed — most servers take no args and no env."""
    for blank in ("", None):
        result = _add(args=blank or "", env=blank or "")
        assert result.get("id")


def test_a_valid_env_object_is_still_accepted():
    assert _add(env='{"API_KEY": "sk-test"}').get("id")


# --------------------------------------------------------------------------
# The browser halves — both forms post to this endpoint
# --------------------------------------------------------------------------


# `B902`. Two tests stood here that sliced the admin MCP form in
# `static/js/admin.js` for its Args check and its `res.ok` read. That form
# returned on ids no template rendered and is deleted; the Settings form below
# is the one place a server is added (`D-2026-09-27-01`), and its check is
# driven in `tests/test_the_mcp_form_names_the_field_js.py`.


def test_the_settings_form_does_not_swallow_the_parse_error():
    """It read `catch (_) {}` — the empty catch is the defect, written out.

    The block it slices changed shape in `P8-46`: the two inline `JSON.parse`
    calls are now one `collectMcpStdioFields` call against the two field
    editors, and the values appended are the ones that call returned. What
    must not come back is a path from this handler to `fd.append` that does
    not pass a refusal, so that is what is asserted — the reading itself is
    driven in `tests/test_the_mcp_form_names_the_field_js.py`.
    """
    settings = SETTINGS_JS.read_text(encoding="utf-8")
    block = settings[settings.index("fd.append('command', el('uf-mcp-cmd').value);"):]
    block = block[: block.index("fd.append('env', collected.env);")]
    assert "catch (_) {}" not in block
    assert "collectMcpStdioFields(argsField, envField)" in block
    assert "if (!collected.ok)" in block
    assert block.index("if (!collected.ok)") < block.index("fd.append('args', collected.args)")
    assert "return;" in block


def test_the_settings_form_no_longer_throws_away_the_reason_it_was_given():
    """`P8-46`. The 400 branch read `r.status` and discarded the body.

    `add_server` answers with a `detail` that names the field and the shape
    that would have worked; `settings.js` rendered `Failed (${r.status})`.
    The dead Admin form prints `data.detail` (asserted above), so the panel
    nobody can reach explained itself and the live one did not — `Law 13`,
    with the two copies disagreeing.
    """
    settings = SETTINGS_JS.read_text(encoding="utf-8")
    handler = settings[settings.index(
        "const r = await fetch('/api/mcp/servers', { method: 'POST'"
    ):]
    handler = handler[: handler.index("finally { _setBtnLoading(saveBtn, false")]
    assert "`Failed (${r.status})`" not in handler
    assert "describeServerRefusal(r.status, data)" in handler
