# SPDX-License-Identifier: AGPL-3.0-or-later
"""The installed `mcp` SDK carries the OAuth provider to a remote MCP server.

`B626`, then `B621`. `McpManager._connect_http` is the only remote transport
OAuth runs on, and the provider `src/mcp_oauth.py` builds is the only way a
token reaches the server. On mcp 1.x it went in as
`streamablehttp_client(url, auth=provider)`; mcp 2.x renamed the transport
`streamable_http_client` and **dropped `auth=`** — it takes the HTTP client,
and the provider rides on that. Measured 2026-09-18 on 2.2.0: no test failed
on either break, because the import is lazy and the one test that faked the
symbol took `**k`.

`B626`'s version of this file read the call out of the source with `ast` and
bound it against the installed signature. That proved the call *binds*; it
could not prove the token *arrives* — a client built and never handed the
provider binds perfectly. So this drives it (`Law 20`): a real streamable-HTTP
MCP server on loopback, built with the installed SDK, that answers 401 to any
request without `Authorization: Bearer <token>`; the manager's real
`_connect_http`; and the real `build_provider`, whose storage holds that token.
Connected with the server's one tool listed means the provider was on the wire.
"""
import asyncio
import socket
import threading
import time

import pytest

TOKEN = "b621-the-token-the-server-wants"


class _RequireBearer:
    """ASGI middleware: 401 unless the request carries the bearer token. Records
    what each request carried, so a failure can say what arrived instead."""

    def __init__(self, app):
        self.app = app
        self.seen = []

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            header = dict(scope.get("headers") or []).get(b"authorization", b"").decode()
            self.seen.append(header)
            if header != f"Bearer {TOKEN}":
                from starlette.responses import JSONResponse
                await JSONResponse({"error": "invalid_token"}, status_code=401)(scope, receive, send)
                return
        await self.app(scope, receive, send)


@pytest.fixture
def remote_server():
    import uvicorn
    import mcp.types as types
    from mcp.server.lowlevel import Server

    async def on_list_tools(ctx, params):
        return types.ListToolsResult(tools=[types.Tool(
            name="whoami", description="Says who the server thinks you are.",
            input_schema={"type": "object", "properties": {}})])

    server = Server("authed-probe", on_list_tools=on_list_tools)
    app = _RequireBearer(server.streamable_http_app())

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(16)
    port = sock.getsockname()[1]
    live = uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False))
    thread = threading.Thread(target=lambda: asyncio.run(live.serve(sockets=[sock])), daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not live.started:
        assert thread.is_alive() and time.monotonic() < deadline, "the MCP server did not start"
        time.sleep(0.02)
    try:
        yield f"http://127.0.0.1:{port}/mcp", app
    finally:
        live.should_exit = True
        thread.join(timeout=10)
        sock.close()


def _storage(monkeypatch, token):
    """`build_provider`'s storage. Only the database read is replaced; the
    provider, and everything it does with what storage holds, is real."""
    from mcp.shared.auth import OAuthToken
    from src import mcp_oauth

    async def get_tokens(self):
        return OAuthToken(access_token=token, token_type="Bearer") if token else None

    async def nothing(self, *_):
        return None

    monkeypatch.setattr(mcp_oauth.DbTokenStorage, "get_tokens", get_tokens)
    for name in ("get_client_info", "set_tokens", "set_client_info"):
        monkeypatch.setattr(mcp_oauth.DbTokenStorage, name, nothing)


def test_the_oauth_provider_reaches_a_streamable_http_server(remote_server, monkeypatch):
    """A token already granted — the state after a person has signed in once —
    is what the server sees on every request, and the session comes up."""
    from src.mcp_manager import McpManager

    _storage(monkeypatch, TOKEN)
    url, app = remote_server

    async def go():
        mgr = McpManager()
        try:
            ok = await asyncio.wait_for(mgr._connect_http("b621srv", "authed", url), timeout=30)
            return ok, dict(mgr._connections.get("b621srv") or {}), list(mgr._tools.get("b621srv") or [])
        finally:
            await mgr.disconnect_server("b621srv")

    ok, status, tools = asyncio.run(go())
    assert ok is True, (status, app.seen)
    assert status["status"] == "connected" and status["transport"] == "http", status
    assert [t["name"] for t in tools] == ["whoami"]
    assert app.seen and all(h == f"Bearer {TOKEN}" for h in app.seen), app.seen


def test_without_the_token_the_server_refuses(remote_server, monkeypatch):
    """The control: the same server, a provider with nothing stored, and the
    first request goes out with no `Authorization` — so the 401 is real, and
    the test above passing is the token's doing. The flow then waits on a
    person to sign in; it is cancelled rather than waited out."""
    from src.mcp_manager import McpManager

    _storage(monkeypatch, None)
    url, app = remote_server

    async def go():
        mgr = McpManager()
        task = asyncio.ensure_future(mgr._connect_http("b621none", "authed", url))
        deadline = time.monotonic() + 10
        while not app.seen and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await mgr.disconnect_server("b621none")

    asyncio.run(go())
    assert app.seen and app.seen[0] == "", app.seen
