# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1528` — `resolve_contact` said *No contacts found* when mail was not searched.

`src/tools/contacts.py` read only `status_code == 200` from
`GET /api/email/resolve-contact`, and the route answers 200 with
`{"contacts": [], "error": "Mail operation failed"}` when the mail server
cannot be reached — so an empty address book and a mail server that is down
together read as *No contacts found matching 'Wren'*, and an assistant tells
the person nobody by that name exists. Now the tool says which source was not
searched and why, and the route says why in its own words.

Driven on the real app booted gated (`tests/helpers/gated_app.py`), as `B1182`'s
test drives it: the real dispatcher, tool, middleware and route, every httpx
client landing on the app from `127.0.0.1`. Only the mail server is replaced —
one that refuses the connection, an account with no inbox, and (the control)
one that answers and holds no Wren.
"""
import pytest

from tests.helpers.gated_app import gated_app_probe

_PROBE = r'''
import asyncio, contextlib, json, httpx

import routes.email_routes as email_routes
from routes.email_helpers import EmailNotConfiguredError


class _Empty:
    def select(self, *a, **k):
        return "OK", [b"0"]

    def search(self, *a, **k):
        return "OK", [b""]


def _mail(kind):
    @contextlib.contextmanager
    def _imap(account_id=None, owner=""):
        if kind == "refused":
            raise ConnectionRefusedError(111, "Connection refused")
        if kind == "no inbox":
            raise EmailNotConfiguredError("IMAP is not configured for account 'default'")
        yield _Empty()
    return _imap


import routes.contacts_routes as contacts_routes
contacts_routes._fetch_contacts = lambda *a, **k: []   # an empty address book

_Real = httpx.AsyncClient
_asgi = httpx.ASGITransport(app=app_module.app, client=("127.0.0.1", 40000))


class _Loopback(_Real):
    def __init__(self, *a, **k):
        k.pop("mounts", None)
        k["transport"] = _asgi
        super().__init__(*a, **k)


httpx.AsyncClient = _Loopback

from src.agent_tools import ToolBlock
from src.tool_execution import NO_TOOL_SECURITY_CONTEXT, execute_tool_block


def resolve(kind):
    email_routes._imap = _mail(kind)

    async def go():
        _, said = await execute_tool_block(
            ToolBlock("resolve_contact", json.dumps({"name": "Wren"})), owner=ADMIN,
            security_context=NO_TOOL_SECURITY_CONTEXT)
        return json.loads(json.dumps(said, default=str))
    return asyncio.run(go())


RESULT["refused"] = resolve("refused")
RESULT["no inbox"] = resolve("no inbox")
RESULT["searched"] = resolve("searched")
'''


@pytest.fixture(scope="module")
def probe(tmp_path_factory):
    return gated_app_probe(tmp_path_factory.mktemp("b1528"), _PROBE)


def _text(out):
    return " ".join(str(out.get(k) or "") for k in ("output", "stdout", "response", "error"))


def test_the_premise_the_app_is_gated(probe):
    assert probe["premise"]["auth_enabled"] is True


def test_a_mail_server_that_cannot_be_reached_is_said_not_searched(probe):
    """The row's `Verify:`."""
    said = _text(probe["refused"])
    assert "The mail history was not searched: the mail server could not be reached." in said, said
    assert "not an answer that nobody by that name exists" in said, said


def test_an_account_with_no_inbox_is_said_not_searched(probe):
    said = _text(probe["no inbox"])
    assert ("The mail history was not searched: no mail account with an inbox is set up."
            in said), said


def test_a_search_that_ran_and_found_nobody_still_says_so_plainly(probe):
    """The control: when the mail history was searched, *No contacts found* is
    the true answer and nothing is added to it."""
    assert _text(probe["searched"]).strip() == "No contacts found matching 'Wren'."
