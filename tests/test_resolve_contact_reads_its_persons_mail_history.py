# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1182` — `resolve_contact`'s mail-history half looped back as nobody.

`src/tools/contacts.py` called `GET /api/email/resolve-contact` with no headers
at all. The app always authenticates (`D-2026-10-07-02` §2), so the middleware
answered 401 and the tool read only `status_code == 200` and dropped it — an
admin's assistant (the tool is in `NON_ADMIN_BLOCKED_TOOLS`) resolved contacts
from the address book only, never from the mail they had sent and received.
Not a hole: it failed closed. Now the call carries `_internal_headers(owner)`,
which names the call's person (`B1179`), so the route answers from that
person's own mailbox (`require_owner`).

Driven on the real app booted gated (`tests/helpers/gated_app.py`): the real
dispatcher, the real tool, the real middleware and route, with every httpx
client landing on the app from `127.0.0.1`. Only the mail server is replaced —
a mailbox that holds one name, and records whose mailbox was opened.
"""
import pytest

from tests.helpers.gated_app import gated_app_probe

_PROBE = r'''
import asyncio, contextlib, json, httpx

# The mail server: one message whose From names Wren, and a record of whose
# mailbox the route opened.
opened = []


class _Conn:
    def select(self, *a, **k):
        return "OK", [b"1"]

    def search(self, *a, **k):
        return "OK", [b"1"]

    def fetch(self, *a, **k):
        return "OK", [(b"1 (BODY[HEADER.FIELDS (FROM TO CC)])",
                       b"From: Wren Hollis <wren@example.test>\r\n\r\n")]


@contextlib.contextmanager
def _imap(account_id=None, owner=""):
    opened.append(owner)
    yield _Conn()


import routes.email_routes as email_routes
email_routes._imap = _imap
import routes.contacts_routes as contacts_routes
contacts_routes._fetch_contacts = lambda *a, **k: []   # an empty address book

_Real = httpx.AsyncClient
reached = []
_asgi = httpx.ASGITransport(app=app_module.app, client=("127.0.0.1", 40000))


class _Switch(httpx.AsyncBaseTransport):
    async def handle_async_request(self, request):
        res = await _asgi.handle_async_request(request)
        reached.append([request.url.path, res.status_code,
                        request.headers.get("X-Pantheon-Owner")])
        return res


class _Loopback(_Real):
    def __init__(self, *a, **k):
        k.pop("mounts", None)
        k["transport"] = _Switch()
        super().__init__(*a, **k)


httpx.AsyncClient = _Loopback

from src.agent_tools import ToolBlock
from src.tool_execution import NO_TOOL_SECURITY_CONTEXT, execute_tool_block


def resolve(owner):
    reached.clear(); opened.clear()

    async def go():
        _, said = await execute_tool_block(
            ToolBlock("resolve_contact", json.dumps({"name": "Wren"})), owner=owner,
            security_context=NO_TOOL_SECURITY_CONTEXT)
        return json.loads(json.dumps(said, default=str))
    out = asyncio.run(go())
    return {"out": out, "reached": list(reached), "opened": list(opened)}


RESULT["admin"] = resolve(ADMIN)
RESULT["member"] = resolve(MEMBER)
'''


@pytest.fixture(scope="module")
def probe(tmp_path_factory):
    return gated_app_probe(tmp_path_factory.mktemp("b1182"), _PROBE)


def _text(result):
    out = result["out"]
    return " ".join(str(out.get(k) or "") for k in ("output", "stdout", "response", "error"))


def test_the_premise_the_app_is_gated(probe):
    assert probe["premise"]["auth_enabled"] is True
    assert probe["premise"]["admin_is_admin"] is True


def test_an_admins_assistant_finds_a_name_only_their_mail_history_holds(probe):
    """The row's `Verify:`."""
    admin = probe["admin"]
    assert "wren@example.test" in _text(admin), admin
    assert "(email history)" in _text(admin), admin
    # Asked as the admin, and the admin's own mailbox was the one opened.
    assert admin["reached"] == [["/api/email/resolve-contact", 200, probe_admin(probe)]]
    assert admin["opened"] == [probe_admin(probe)]


def test_a_member_never_reaches_anyones_mailbox(probe):
    """The tool stays an admin's (`NON_ADMIN_BLOCKED_TOOLS`): a member's call
    is refused before any loopback, and no mailbox is opened."""
    member = probe["member"]
    assert "wren@example.test" not in _text(member)
    assert member["reached"] == [] and member["opened"] == []


def probe_admin(probe):
    from tests.helpers.signed_in import ADMIN
    return ADMIN
