# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1980`. A UID that was an IMAP set acted on the whole folder.

An IMAP UID names one message, but every command that takes one also takes a
set: `1:*` is every message in the folder, `5,7` two of them, `*` the last.
Nothing checked. `DELETE /api/email/delete/1:*` moved the whole folder to
Trash and `delete-permanent/1:*` expunged it, until `B2010` taught
`_uid_exists` the rule and `B1979` the two delete routes; `GET
/api/email/read/1:*` still fetched every message and marked every one read,
and the attachment routes and the unsubscribe fetched the whole folder. The
agent's mail tools took a free-string `uid` and handed it to UID STORE and
MOVE: `delete_email` with `permanent` and uid `1:*` flagged and expunged the
folder, `archive_email` moved it, and `bulk_email` joined its `uids` into one
set unchecked.

Now a UID is one plain ASCII number before it reaches any command, at every
door: every route with a `{uid}` in its path answers 400 (a router
dependency, so a route added later is covered too), the unsubscribe routes
read their body's UID by the same rule, and the agent's tools refuse in words
the model can read, before connecting. The rule is one function,
`src.mail_headers.one_uid`, which the routes' `_uid_exists` (`B2010`) already
asked. Pantheon's own finding, made while verifying `B1979`; no upstream
commit.

`bulk_email` with `all_unread` now works: its UIDs come back from SEARCH as
bytes, were joined as `b'5',b'6'`, and every server refused them.

Driven (`Law 20`): every `{uid}` route of the real router under `TestClient`,
and the agent's tools through the MCP server's own `call_tool`, over fakes
that record whether a mailbox was opened at all.
"""
import contextlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

SETS = ["1:*", "5,7", "*", "1:5", "\uff15", "5031 "]


# ── the routes ──────────────────────────────────────────────────────────────


class Recorder:
    """A mailbox that holds UID 5031 and records every command."""

    def __init__(self):
        self.commands = []

    def select(self, mailbox, readonly=False):
        self.commands.append(("SELECT", mailbox))
        return "OK", [b"1"]

    def list(self, *_args):
        return "OK", [b'(\\HasNoChildren \\Trash) "/" "Trash"']

    def uid(self, command, *args):
        self.commands.append((command, *args))
        if command == "FETCH":
            return "OK", [b"1 (UID 5031)"]
        if command == "SEARCH":
            return "OK", [b"5031"]
        return "OK", [b""]

    def expunge(self):
        self.commands.append(("EXPUNGE",))
        return "OK", [b""]


@pytest.fixture
def mail(tmp_path, monkeypatch):
    import routes.email_helpers as EH
    import routes.email_routes as E
    from routes.email_helpers import require_owner, require_user

    db = tmp_path / "email.db"
    monkeypatch.setattr(EH, "SCHEDULED_DB", db)
    monkeypatch.setattr(E, "SCHEDULED_DB", db)
    EH._init_scheduled_db()

    box = {"opened": 0, "conn": Recorder()}

    @contextlib.contextmanager
    def fake_imap(account_id=None, owner=""):
        box["opened"] += 1
        yield box["conn"]

    monkeypatch.setattr(E, "_start_poller", lambda: None)
    monkeypatch.setattr(E, "_imap", fake_imap)
    router = E.setup_email_routes()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_owner] = lambda: "alice"
    app.dependency_overrides[require_user] = lambda: "alice"
    box["client"] = TestClient(app)
    box["doors"] = sorted(
        (method, route.path)
        for route in router.routes if "{uid}" in getattr(route, "path", "")
        for method in route.methods
    )
    return box


def _knock(mail, method, path, uid):
    url = path.replace("{uid}", uid).replace("{index}", "0")
    return mail["client"].request(method, url, params={"folder": "INBOX", "dest": "Junk"})


def test_every_uid_door_is_counted(mail):
    """The doors this file drives, so a route can only leave the list in sight."""
    paths = {path for _method, path in mail["doors"]}
    assert {
        "/api/email/read/{uid}", "/api/email/delete/{uid}", "/api/email/delete-permanent/{uid}",
        "/api/email/archive/{uid}", "/api/email/move/{uid}", "/api/email/mark-read/{uid}",
        "/api/email/mark-unread/{uid}", "/api/email/flag/{uid}", "/api/email/mark-answered/{uid}",
        "/api/email/clear-answered/{uid}", "/api/email/attachments/{uid}",
        "/api/email/attachment/{uid}/{index}", "/api/email/attachments-download/{uid}",
        "/api/email/inline-image/{uid}", "/api/email/attachment-as-doc/{uid}/{index}",
        "/api/email/compose-from-attachment/{uid}/{index}",
    } <= paths


@pytest.mark.parametrize("uid", SETS, ids=["all", "two", "star", "range", "fullwidth", "space"])
def test_a_uid_set_is_refused_at_every_door_before_a_mailbox_opens(mail, uid):
    assert len(mail["doors"]) >= 16
    for method, path in mail["doors"]:
        r = _knock(mail, method, path, uid)
        assert r.status_code == 400, (method, path, r.status_code, r.text)
        assert r.json()["detail"] == "An email UID is one number, such as 5031.", (method, path)
    assert mail["opened"] == 0
    assert mail["conn"].commands == []


@pytest.mark.parametrize("path", ["/api/email/delete/{uid}", "/api/email/delete-permanent/{uid}"])
def test_one_number_is_still_deleted(mail, path):
    r = _knock(mail, "DELETE", path, "5031")
    assert r.status_code == 200 and r.json() == {"success": True}
    assert mail["opened"] == 1


def test_an_unsubscribe_names_one_message(mail):
    r = mail["client"].post("/api/email/unsubscribe/execute", json={"uid": "1:*", "folder": "INBOX"})
    assert r.status_code == 400
    assert r.json()["detail"] == "An email UID is one number, such as 5031."
    assert mail["opened"] == 0


def test_an_unsubscribe_cleanup_moves_only_messages_it_can_name(mail):
    r = mail["client"].post("/api/email/unsubscribe/cleanup",
                            json={"action": "delete", "uids": ["1:*", "\uff15", "*"]})
    assert r.json() == {"success": False, "error": "No email UIDs provided", "changed": 0, "failed": 0}
    assert mail["opened"] == 0


# ── the agent's tools ───────────────────────────────────────────────────────


class AgentMailbox:
    """The MCP server's connection: holds UIDs 5 and 6, records every command."""

    def __init__(self):
        self.commands = []

    def select(self, mailbox, readonly=False):
        self.commands.append(("SELECT", mailbox))
        return "OK", [b"2"]

    def list(self, *_args):
        return "OK", []

    def uid(self, command, *args):
        self.commands.append((command, *args))
        if command == "SEARCH":
            return "OK", [b"5 6"]
        if command == "FETCH":
            wanted = args[0].decode().split(",")
            return "OK", [f"{i} (UID {u})".encode() for i, u in enumerate(wanted, 1) if u in ("5", "6")]
        return "OK", [b"1"]

    def expunge(self):
        self.commands.append(("EXPUNGE",))
        return "OK", [b""]

    def logout(self):
        pass


@pytest.fixture
def agent(tmp_path, monkeypatch):
    pytest.importorskip("mcp")
    import mcp_servers.email_server as es

    for key in es._OWNER_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(es, "APP_DB", str(tmp_path / "no-app.db"))
    box = {"connects": 0, "conn": AgentMailbox()}

    def connect(account=None):
        box["connects"] += 1
        return box["conn"]

    monkeypatch.setattr(es, "_imap_connect", connect)
    monkeypatch.setattr(es, "_load_config", lambda account=None: {
        "trash_folder": "Trash", "archive_folder": "Archive", "junk_folder": "Junk"})
    box["es"] = es
    return box


_TOOLS = [
    ("delete_email", {}),
    ("delete_email", {"permanent": True}),
    ("archive_email", {}),
    ("mark_email_read", {}),
    ("read_email", {}),
    ("reply_to_email", {"body": "Thanks"}),
    ("draft_email_reply", {"body": "Thanks"}),
    ("ai_draft_email_reply", {}),
    ("download_attachment", {"index": 0}),
    ("unsubscribe_email", {}),
]


@pytest.mark.parametrize("uid", ["1:*", "1,2", "*", "\uff15"], ids=["all", "two", "star", "fullwidth"])
async def test_the_agent_cannot_name_a_set_for_one_message(agent, uid):
    for tool, extra in _TOOLS:
        out = await agent["es"].call_tool(tool, {"uid": uid, **extra})
        assert out[0].text == f"Error: {uid!r} is not an email UID. A UID is one number, such as 5031, from list_emails or search_emails.", tool
    assert agent["connects"] == 0


@pytest.mark.parametrize("uids", [["1:*"], ["5", "1:*"], "5,6", ["*"]], ids=["all", "mixed", "joined", "star"])
async def test_bulk_email_refuses_a_set_among_its_uids(agent, uids):
    for action in ("delete", "archive", "junk", "mark_read"):
        out = await agent["es"].call_tool("bulk_email", {"action": action, "uids": uids, "permanent": True})
        assert out[0].text.startswith("Error: "), (action, out[0].text)
        assert "one number" in out[0].text
    assert agent["connects"] == 0


async def test_one_number_still_reaches_the_mailbox(agent):
    out = await agent["es"].call_tool("delete_email", {"uid": "5"})
    assert out[0].text == "Deleted UID 5"
    assert ("MOVE", b"5", '"Trash"') in agent["conn"].commands


async def test_a_uid_sent_as_a_number_is_one_number(agent):
    out = await agent["es"].call_tool("mark_email_read", {"uid": 5})
    assert out[0].text == "Marked UID 5 as read"
    assert ("STORE", b"5", "+FLAGS", "\\Seen") in agent["conn"].commands


async def test_all_unread_reaches_the_server_as_numbers(agent):
    out = await agent["es"].call_tool("bulk_email", {"action": "mark_read", "all_unread": True})
    assert out[0].text == "Done — 2 email(s) marked read."
    assert ("STORE", b"5,6", "+FLAGS", "\\Seen") in agent["conn"].commands


@pytest.mark.parametrize("helper, args", [
    ("_set_flag", ("1:*", "INBOX", "\\Deleted")),
    ("_move_message", ("1:*", "INBOX", "Trash")),
    ("_bulk_set_flag", (["1:*"], "INBOX", "\\Deleted")),
    ("_bulk_move", (["5", "1:*"], "INBOX", "Trash")),
])
def test_the_helpers_that_change_mail_refuse_a_set_themselves(agent, helper, args):
    """A caller that skips `call_tool` still cannot hand one a set."""
    assert not getattr(agent["es"], helper)(*args)
    assert agent["connects"] == 0
