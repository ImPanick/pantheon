# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1175` — the assistant acts with its person's privileges, never more.

The agent reaches Pantheon's own routes over an in-process loopback that
carries the internal-tool token, and `app.py`'s `AuthMiddleware` names the
request as its `X-Pantheon-Owner`. `require_admin` returned early on the token
**whoever it named**. Measured 2026-10-03 through the real `do_app_api` against
the real app with `AUTH_ENABLED=true` (`w10-skills` found it working `B1130`):
bob, not an admin, got **403** from `GET /api/mcp/servers` in person and **200**
through his loopback — every server's `command`, `args` and `env` raw, where MCP
servers keep their tokens — and `DELETE /api/sessions/all`, which no blocklist
names, emptied every chat on the instance.

**The first gate held, and this is the second.** The dispatcher refuses
`app_api` to a non-admin owner (`_ADMIN_ONLY_TOOLS`) before `do_app_api` runs, so
the hole was one gate deep rather than open: a tool-name list was all that stood
between a non-admin's assistant and every admin route. Now the route's own
control holds under it — on the loopback, `require_admin` asks whether the
person the request names is an admin, as that person's own request is asked.

**The adversary (`Law 17`):** text a non-admin's assistant reads — a mail, a
page, a document — steering it at an admin route.

**What does not change:** a loopback that names nobody is Pantheon itself (the
scheduler, the Forge lifecycle loop) and passes; an admin's assistant passes; a
single-user install's owner is its first account, the admin; an auth-off
install passes. `FORBIDDEN.md` Part 2 lists `require_admin`: tightened, never
lifted.

Driven, not read (`Law 20`): the real app booted out of process
(`tests/helpers/gated_app.py`), the real `do_app_api` — blocklists and all —
with its httpx loopback landing in process on that app from `127.0.0.1`, the
address `_is_trusted_loopback` accepts, so the real `AuthMiddleware` attributes
it and the real `require_admin` answers.
"""
import pytest

from tests.helpers.gated_app import gated_app_probe

# The MCP server row carries a token in its environment, as a GitHub server's
# does; the chat row is someone's history on the instance.
_SECRET = "ghp_B1175_NOT_FOR_BOB"

_PROBE = r'''
import asyncio
import httpx
from core.database import McpServer, Session as DbSession, SessionLocal
from core.middleware import INTERNAL_TOOL_HEADER, INTERNAL_TOOL_TOKEN

_db = SessionLocal()
_db.add(McpServer(id="gh1", name="github", transport="stdio", command="npx",
                  args='["-y", "server-github"]', env=json.dumps({"GITHUB_TOKEN": %(secret)r}),
                  is_enabled=False))
_db.add(DbSession(id="ada-chat", name="Quarterly numbers", endpoint_url="http://127.0.0.1:9",
                  model="m", owner=ADMIN))
_db.commit()
_db.close()

# Every httpx client the tool opens lands on this app, from loopback — the one
# substitution; the token, the header, the middleware and the gate are real.
_Real = httpx.AsyncClient
reached = []

class _Loopback(_Real):
    def __init__(self, *a, **k):
        k.pop("mounts", None)
        k["transport"] = httpx.ASGITransport(app=app_module.app, client=("127.0.0.1", 40000))
        super().__init__(*a, **k)

    async def request(self, method, url, *a, **k):
        res = await super().request(method, url, *a, **k)
        reached.append([method, httpx.URL(str(url)).path, res.status_code])
        return res

httpx.AsyncClient = _Loopback

from src.tools.system import do_app_api


def assistant(owner, method, path):
    """The agent's `app_api` tool for `owner`, and what reached a route."""
    reached.clear()
    said = asyncio.run(do_app_api(json.dumps({"action": "call", "method": method,
                                              "path": path}), owner=owner))
    return {"status": said.get("status_code"), "exit_code": said.get("exit_code"),
            "leaked": %(secret)r in json.dumps(said, default=str),
            "reached": list(reached)}


def chats():
    db = SessionLocal()
    try:
        return sorted(r[0] for r in db.query(DbSession.id).all())
    finally:
        db.close()


READS = %(reads)r
RESULT["auth_enabled"] = bool(app_module.AUTH_ENABLED)
RESULT["in_person"] = {who: {p: client(who).get(p).status_code for p in READS}
                       for who in (MEMBER, ADMIN)} if app_module.AUTH_ENABLED else {}
WHO = {"bob": MEMBER, "ada": ADMIN, "local owner": "__pantheon_local__", "nobody": None}
RESULT["reads"] = {label: {p: assistant(who, "GET", p) for p in READS}
                   for label, who in WHO.items()}
RESULT["member_wipe"] = assistant(MEMBER, "DELETE", "/api/sessions/all")
RESULT["chats_after_member_wipe"] = chats()


def raw(headers):
    async def go():
        async with _Loopback() as c:
            return (await c.get("http://127.0.0.1:7000/api/mcp/servers", headers=headers)).status_code
    return asyncio.run(go())


RESULT["raw"] = {
    "nobody named": raw({INTERNAL_TOOL_HEADER: INTERNAL_TOOL_TOKEN}),
    "no account": raw({INTERNAL_TOOL_HEADER: INTERNAL_TOOL_TOKEN, "X-Pantheon-Owner": "ghost"}),
    "member": raw({INTERNAL_TOOL_HEADER: INTERNAL_TOOL_TOKEN, "X-Pantheon-Owner": MEMBER}),
    "admin": raw({INTERNAL_TOOL_HEADER: INTERNAL_TOOL_TOKEN, "X-Pantheon-Owner": ADMIN}),
    "wrong token": raw({INTERNAL_TOOL_HEADER: "0" * 64, "X-Pantheon-Owner": ADMIN}),
}

# The first gate, kept: the dispatcher refuses `app_api` to a non-admin owner
# before the tool runs.
from src.agent_tools import ToolBlock
from src.tool_execution import NO_TOOL_SECURITY_CONTEXT, execute_tool_block
reached.clear()
_, said = asyncio.run(execute_tool_block(
    ToolBlock("app_api", json.dumps({"path": "/api/mcp/servers"})),
    owner=MEMBER, security_context=NO_TOOL_SECURITY_CONTEXT))
RESULT["dispatcher_member"] = {"said": said, "reached": list(reached)}
''' % {"secret": _SECRET, "reads": ("/api/mcp/servers", "/api/mcp/tools",
                                     "/api/vault/config", "/api/cookbook/state")}

_READS = ("/api/mcp/servers", "/api/mcp/tools", "/api/vault/config", "/api/cookbook/state")


@pytest.fixture(scope="module")
def gated(tmp_path_factory):
    return gated_app_probe(tmp_path_factory.mktemp("b1175"), _PROBE)


@pytest.fixture(scope="module")
def no_login(tmp_path_factory):
    return gated_app_probe(tmp_path_factory.mktemp("b1175-off"), _PROBE,
                           env_overrides={"AUTH_ENABLED": "false"})


def test_the_app_is_gated_and_the_accounts_are_what_they_say(gated):
    assert gated["premise"] == {
        "auth_enabled": True, "localhost_bypass": False,
        "admin_is_admin": True, "member_is_admin": False,
    }, gated["premise"]
    # The reference answer: bob in person is refused every one of the routes,
    # ada is not.
    assert set(gated["in_person"]["bob"].values()) == {403}, gated["in_person"]
    assert set(gated["in_person"]["ada"].values()) == {200}, gated["in_person"]


def test_a_non_admins_assistant_is_refused_where_the_person_is(gated):
    """The row's `Verify:`, on four `require_admin` reads the `app_api`
    blocklists do not name. The loopback reached each route (the refusal is the
    route's, not the blocklist's) and nothing it read came back. On the tree
    before `B1175`: 200 from all four, and the MCP server's token in the
    answer."""
    for path in _READS:
        row = gated["reads"]["bob"][path]
        assert row["reached"] == [["GET", path, 403]], (path, row)
        assert row["status"] == 403 and row["exit_code"] == 1, (path, row)
        assert not row["leaked"], (path, row)


def test_a_non_admins_assistant_cannot_empty_every_chat(gated):
    """A write no blocklist names: `DELETE /api/sessions/all`. Before `B1175`
    bob's loopback deleted ada's chat with everyone else's."""
    row = gated["member_wipe"]
    assert row["reached"] == [["DELETE", "/api/sessions/all", 403]], row
    assert gated["chats_after_member_wipe"] == ["ada-chat"], gated["chats_after_member_wipe"]


def test_an_admins_assistant_still_reads_what_the_admin_reads(gated):
    """`Law 1`. A single-user install's owner is its first account — ada — and
    her assistant answers as she does: the MCP inventory, environment included,
    as the admin's own panel shows it."""
    for path in _READS:
        row = gated["reads"]["ada"][path]
        assert row["reached"] == [["GET", path, 200]], (path, row)
        assert row["exit_code"] == 0, (path, row)
    assert gated["reads"]["ada"]["/api/mcp/servers"]["leaked"]


def test_a_loopback_that_names_nobody_is_pantheon_itself(gated):
    """The scheduler's actions and the Forge lifecycle loop call with the token
    and no owner; they keep the reach they had. A tool call with no owner is the
    same request."""
    assert gated["raw"]["nobody named"] == 200, gated["raw"]
    for path in _READS:
        assert gated["reads"]["nobody"][path]["reached"] == [["GET", path, 200]], path


def test_a_name_that_is_no_account_is_asked_about_not_dropped(gated):
    """The middleware attributes a loopback only to an account that exists and
    otherwise stamps the internal tool user — which, before `B1175`, read as
    "nobody named" and passed. A person named is a person asked about: one who
    is not an account is not an admin. So is the reserved local owner on a gated
    install."""
    assert gated["raw"]["no account"] == 403, gated["raw"]
    assert gated["raw"]["member"] == 403, gated["raw"]
    assert gated["raw"]["admin"] == 200, gated["raw"]
    for path in _READS:
        assert gated["reads"]["local owner"][path]["reached"] == [["GET", path, 403]], path


def test_a_wrong_token_is_a_caller_with_no_session(gated):
    """The loopback is the token and a loopback address together; a token that
    is not this process's is just an unsigned-in request."""
    assert gated["raw"]["wrong token"] == 401, gated["raw"]


def test_the_dispatcher_still_refuses_app_api_to_a_non_admin_first(gated):
    """The first gate (`_ADMIN_ONLY_TOOLS`), kept. Nothing reached a route."""
    row = gated["dispatcher_member"]
    assert row["said"]["exit_code"] == 1, row
    assert "requires an admin user" in row["said"]["error"], row
    assert row["reached"] == [], row


def test_a_no_login_install_keeps_what_it_had(no_login):
    """`AUTH_ENABLED=false`: no middleware, and whoever the loopback names is
    the owner of a box with no logins — the local owner, an account that exists
    on disk, or nobody."""
    assert no_login["premise"]["auth_enabled"] is False, no_login["premise"]
    for who in ("local owner", "bob", "nobody"):
        for path in _READS:
            row = no_login["reads"][who][path]
            assert row["reached"] == [["GET", path, 200]], (who, path, row)
