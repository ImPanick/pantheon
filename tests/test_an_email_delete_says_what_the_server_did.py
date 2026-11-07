# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1979`. Deleting an email said it worked whatever the server did, and a
search result was deleted in the wrong folder.

The library's five delete doors (Delete on an open message, Move to Trash and
Delete Permanently in its More menu, Delete on a card, bulk Delete) awaited
the request and never read the answer. A refused move, a folder that would
not open and a dropped connection all ended with the card gone, and the first
said "Moved to Trash"; the message came back on the next refresh. Bulk Delete
hid even a network failure and took every selected card away.

The server could not have said better. Both delete routes answered "Email not
found" whether the message was gone or the move had failed, and a message
deleted in another mail app stays in Pantheon's index, which nothing prunes,
so it came back on every open and, once the page read the answer, could never
be cleared. Now a lookup that worked and found nothing is a success with
`already_deleted`, and the stale row leaves the index; a move or delete the
server refuses says so and keeps the row; a lookup that failed is a failure
(`_uid_exists(strict=True)`, `B2010`).

And every per-message delete, archive and Spam sent the folder the picker
showed, not the message's own. A search from INBOX lists messages from other
folders (Gmail's All Mail, any indexed folder), so Delete moved to Trash, and
Delete Permanently expunged, whichever message held that UID number in INBOX,
and left the one the person chose. They send the message's folder and account
now.

From upstream Odysseus 218d7624 (`_emailMutationQuery`,
`_requireSuccessfulEmailMutation`, the idempotent delete). Not taken: its
Message-ID re-resolution (it picks the newest of the messages carrying a header
the sender chose), its creating a Trash folder, and its async routes (`B1609`
keeps these plain `def`).

Driven (`Law 20`): the real routes under `TestClient` over a fake mailbox and
the real message index; the library's own functions, cut out of
`static/js/emailLibrary.js`, run under node.
"""
import contextlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.helpers.js_source import js_definition
from tests.helpers.source_text import blank_text
from tests.test_email_read_mark_seen import _route_endpoint

ROOT = Path(__file__).resolve().parents[1]
LIBRARY_JS = (ROOT / "static" / "js" / "emailLibrary.js").read_text(encoding="utf-8")
INBOX_JS = (ROOT / "static" / "js" / "emailInbox.js").read_text(encoding="utf-8")

DELETE = "/api/email/delete/{uid}"
PERMANENT = "/api/email/delete-permanent/{uid}"


# ── the server ──────────────────────────────────────────────────────────────


class Mailbox:
    """One folder of an IMAP server: the UIDs in it, and how each command
    answers. `fetch` and `search` script the probe (an exception is raised);
    `move`, `copy` and `store` are those commands' answers."""

    def __init__(self, *uids, fetch=None, search=None, move="OK", copy="OK", store="OK"):
        self.present = {str(u) for u in uids}
        self.flagged = set()
        self.fetch, self.search = fetch, search
        self.move, self.copy, self.store = move, copy, store
        self.commands = []

    def select(self, mailbox, readonly=False):
        self.commands.append(("SELECT", mailbox))
        return "OK", [str(len(self.present)).encode()]

    def list(self, *_args):
        return "OK", [b'(\\HasNoChildren \\Trash) "/" "Trash"']

    def uid(self, command, *args):
        self.commands.append((command, *args))
        if command == "FETCH":
            if isinstance(self.fetch, BaseException):
                raise self.fetch
            if self.fetch is not None:
                return self.fetch
            uid = args[0].decode()
            return "OK", [f"1 (UID {uid})".encode()] if uid in self.present else [None]
        if command == "SEARCH":
            if self.search is not None:
                return self.search
            uid = args[-1].split()[-1]
            return "OK", [uid.encode() if uid in self.present else b""]
        uid = args[0].decode()
        if command == "MOVE":
            if self.move == "OK":
                self.present.discard(uid)
            return self.move, [b""]
        if command == "COPY":
            return self.copy, [b""]
        if command == "STORE":
            if self.store == "OK":
                self.flagged.add(uid)
            return self.store, [b""]
        raise AssertionError(f"unexpected IMAP command {command}")

    def expunge(self):
        self.commands.append(("EXPUNGE",))
        self.present -= self.flagged
        return "OK", [b""]

    def changes(self):
        return [c[0] for c in self.commands if c[0] in ("MOVE", "COPY", "STORE", "EXPUNGE")]


@pytest.fixture
def mail(tmp_path, monkeypatch):
    import routes.email_helpers as EH
    import routes.email_routes as E
    from routes.email_helpers import require_owner, require_user

    db = tmp_path / "email.db"
    monkeypatch.setattr(EH, "SCHEDULED_DB", db)
    monkeypatch.setattr(E, "SCHEDULED_DB", db)
    EH._init_scheduled_db()

    box = {"mailbox": Mailbox("5031"), "opened": 0}

    @contextlib.contextmanager
    def fake_imap(account_id=None, owner=""):
        box["opened"] += 1
        yield box["mailbox"]

    monkeypatch.setattr(E, "_start_poller", lambda: None)
    monkeypatch.setattr(E, "_imap", fake_imap)
    app = FastAPI()
    box["router"] = E.setup_email_routes()
    app.include_router(box["router"])
    app.dependency_overrides[require_owner] = lambda: "alice"
    app.dependency_overrides[require_user] = lambda: "alice"
    box["client"] = TestClient(app)
    E._email_index_upsert("alice", None, "INBOX", [{
        "uid": "5031", "message_id": "<invoice@example.test>", "subject": "Invoice",
        "from_address": "billing@example.test", "date_epoch": 1.0,
    }])
    box["indexed"] = lambda uid="5031": uid in E._email_index_rows("alice", None, "INBOX", [uid])
    return box


def _delete(mail, route, uid="5031", folder="INBOX"):
    path = route.replace("{uid}", uid)
    return mail["client"].delete(path, params={"folder": folder}).json()


@pytest.mark.parametrize("route", [DELETE, PERMANENT])
def test_a_message_already_gone_is_deleted_and_leaves_the_index(mail, route):
    """Deleted in another mail app: the lookup worked and found nothing."""
    mail["mailbox"] = Mailbox()
    assert mail["indexed"]()

    assert _delete(mail, route) == {"success": True, "already_deleted": True}
    assert mail["mailbox"].changes() == []
    assert not mail["indexed"]()


def test_a_move_the_server_refuses_says_so_and_keeps_the_row(mail):
    mail["mailbox"] = Mailbox("5031", move="NO", copy="NO")

    assert _delete(mail, DELETE) == {"success": False, "error": "Could not move email to Trash"}
    assert "5031" in mail["mailbox"].present
    assert mail["indexed"]()


def test_a_permanent_delete_the_server_refuses_says_so_and_keeps_the_row(mail):
    mail["mailbox"] = Mailbox("5031", store="NO")

    assert _delete(mail, PERMANENT) == {"success": False, "error": "Could not delete email"}
    assert "EXPUNGE" not in mail["mailbox"].changes()
    assert mail["indexed"]()


@pytest.mark.parametrize("route", [DELETE, PERMANENT])
@pytest.mark.parametrize("probe", [
    {"fetch": OSError("connection reset")},
    {"fetch": ("OK", [None]), "search": ("NO", [b"search refused"])},
], ids=["fetch-raises", "search-no"])
def test_a_lookup_that_failed_is_not_called_gone(mail, route, probe):
    mail["mailbox"] = Mailbox("5031", **probe)

    assert _delete(mail, route) == {"success": False, "error": "Mail operation failed"}
    assert mail["mailbox"].changes() == []
    assert mail["indexed"]()


@pytest.mark.parametrize("route", [DELETE, PERMANENT])
def test_a_uid_that_is_not_one_number_reaches_no_mailbox(mail, route):
    """`1:*` is every message in the folder; the strict lookup never sees it.
    The handler is asked itself, so the answer is the route's own."""
    delete = _route_endpoint(mail["router"], route, "DELETE")
    assert delete("1:*", folder="INBOX", account_id=None, owner="alice") == {
        "success": False, "error": "Invalid email UID"}
    assert mail["opened"] == 0


def test_a_message_that_is_there_moves_to_trash_and_leaves_the_index(mail):
    assert _delete(mail, DELETE) == {"success": True}
    assert ("MOVE", b"5031", '"Trash"') in mail["mailbox"].commands
    assert not mail["indexed"]()


def test_a_message_that_is_there_is_deleted_for_good_and_leaves_the_index(mail):
    assert _delete(mail, PERMANENT) == {"success": True}
    assert mail["mailbox"].changes() == ["STORE", "EXPUNGE"]
    assert "5031" not in mail["mailbox"].present
    assert not mail["indexed"]()


# ── the library ─────────────────────────────────────────────────────────────

needs_node = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _cut(source: str, *signatures: str) -> str:
    """Each declaration as it ships, found in code rather than in a comment."""
    code = blank_text(source, "js")
    missing = [sig for sig in signatures if sig not in code]
    assert not missing, f"not in the module: {missing}"
    return "\n".join(js_definition(source, code.index(sig)) for sig in signatures)


def _library() -> str:
    return _cut(
        LIBRARY_JS,
        "function _emailMutationQuery(",
        "async function _requireSuccessfulEmailMutation(",
        "function _toastEmailAlreadyGone(",
        "async function _deleteEmailAndAdvance(",
        "async function _bulkAction(",
    ) + "\n" + _cut(INBOX_JS, "function folderDisplayName(")

_PAGE = r"""
const API_BASE = '';
const state = {
  _libFolder: 'INBOX', _libAccountId: 'acct-a', _libFilter: 'all',
  _libEmails: [], _selectedUids: new Set(), _selectMode: true,
};
const toasts = [], calls = [];
const answers = new Map();   // uid -> { status, body } | an Error to throw
const showToast = (m) => { toasts.push(String(m)); };
const styledConfirm = async () => true;
globalThis.fetch = async (url, init = {}) => {
  calls.push([init.method || 'GET', String(url)]);
  const uid = decodeURIComponent(String(url).split('?')[0].split('/').pop());
  const a = answers.has(uid) ? answers.get(uid) : { body: { success: true } };
  if (a instanceof Error) throw a;
  const status = a.status || 200;
  return {
    ok: status < 400, status,
    json: async () => { if (a.body === undefined) throw new SyntaxError('not JSON'); return a.body; },
  };
};
const document = { getElementById: () => null, querySelector: () => null };
const CSS = { escape: (s) => String(s) };
const spinnerModule = { create: () => ({ createElement: () => ({ classList: { add() {} } }), start() {}, destroy() {} }) };
const _showEmailDeleteOverlay = (card) => (card ? { ready: Promise.resolve(), remove() {} } : null);
const _animateEmailCardRemoval = async () => {};
const _findSiblingEmailCard = () => null;
const _updateBulkBar = () => {}, _renderGrid = () => {}, _libCacheWriteBack = () => {};
const _toggleCardPreview = async () => {};
const _clearDoneResponseTagsLocal = () => {}, _syncEmailReadState = () => {};
const scrollBehavior = () => 'auto';
const left = () => state._libEmails.map((e) => String(e.uid));
"""


def _page(script: str) -> dict:
    proc = subprocess.run(
        ["node", "--input-type=module"], input=_PAGE + _library() + "\n" + script,
        capture_output=True, text=True, cwd=str(ROOT), timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


@needs_node
def test_a_change_to_one_message_names_its_own_folder_and_account():
    out = _page("""
      const q = (em) => Object.fromEntries(new URLSearchParams(_emailMutationQuery(em)));
      console.log(JSON.stringify({
        result: q({ uid: 7, folder: '[Gmail]/All Mail' }),
        listed: q({ uid: 8 }),
        other: q({ uid: 9, folder: 'Archive', account_id: 'acct-b' }),
      }));
    """)
    assert out == {
        "result": {"folder": "[Gmail]/All Mail", "account_id": "acct-a"},
        "listed": {"folder": "INBOX", "account_id": "acct-a"},
        "other": {"folder": "Archive", "account_id": "acct-b"},
    }


@needs_node
def test_only_a_success_the_server_states_is_a_success():
    out = _page("""
      const said = async (res) => {
        try { return { ok: await _requireSuccessfulEmailMutation(res, 'Failed to delete email') }; }
        catch (e) { return { error: e.message, server: e.serverError || null }; }
      };
      const r = (status, body) => ({ ok: status < 400, status,
        json: async () => { if (body === undefined) throw new SyntaxError('x'); return body; } });
      console.log(JSON.stringify({
        refused: await said(r(200, { success: false, error: 'Could not move email to Trash' })),
        silent: await said(r(200, {})),
        broken: await said(r(500)),
        bad: await said(r(400, { detail: 'Invalid email UID' })),
        gone: await said(r(200, { success: true, already_deleted: true })),
      }));
    """)
    assert out["refused"] == {"error": "Could not move email to Trash", "server": "Could not move email to Trash"}
    assert out["silent"] == {"error": "Failed to delete email (HTTP 200)", "server": None}
    assert out["broken"] == {"error": "Failed to delete email (HTTP 500)", "server": None}
    assert out["bad"] == {"error": "Invalid email UID", "server": "Invalid email UID"}
    assert out["gone"] == {"ok": {"success": True, "already_deleted": True}}


_SEARCH_RESULTS = """
  const found = { uid: 7, folder: '[Gmail]/All Mail', subject: 'Invoice' };
  state._libEmails = [found, { uid: 8, subject: 'Lunch' }];
"""


@needs_node
@pytest.mark.parametrize("answer, kept, toast", [
    ("{ body: { success: false, error: 'Could not move email to Trash' } }", True, "Could not move email to Trash"),
    ("{ status: 500 }", True, "Failed to delete email"),
    ("new TypeError('Failed to fetch')", True, "Failed to delete email"),
    ("{ body: { success: true } }", False, "Moved to Trash"),
    ("{ body: { success: true, already_deleted: true } }", False, "Already gone from Archive / All Mail"),
], ids=["refused", "http-500", "offline", "moved", "already-gone"])
def test_a_delete_takes_the_card_away_only_when_the_server_did_it(answer, kept, toast):
    out = _page(_SEARCH_RESULTS + f"""
      answers.set('7', {answer});
      await _deleteEmailAndAdvance(found, null, {{ confirm: false }});
      console.log(JSON.stringify({{ left: left(), toasts, calls }}));
    """)
    assert ("7" in out["left"]) is kept
    assert out["toasts"] == [toast]
    # The search result's own folder, never the picker's INBOX.
    assert out["calls"] == [["DELETE", "/api/email/delete/7?folder=%5BGmail%5D%2FAll+Mail&account_id=acct-a"]]


@needs_node
def test_bulk_delete_takes_away_only_what_the_server_deleted():
    out = _page(_SEARCH_RESULTS + """
      state._libEmails.push({ uid: 9, folder: 'INBOX', subject: 'Report' });
      state._selectedUids = new Set([7, 8, 9]);
      answers.set('9', { body: { success: false, error: 'Could not move email to Trash' } });
      await _bulkAction('delete');
      console.log(JSON.stringify({ left: left(), toasts, calls }));
    """)
    assert out["left"] == ["9"]
    assert out["toasts"] == ["Failed to delete 1 email"]
    assert sorted(out["calls"]) == [
        ["DELETE", "/api/email/delete/7?folder=%5BGmail%5D%2FAll+Mail&account_id=acct-a"],
        ["DELETE", "/api/email/delete/8?folder=INBOX&account_id=acct-a"],
        ["DELETE", "/api/email/delete/9?folder=INBOX&account_id=acct-a"],
    ]


@needs_node
def test_bulk_delete_offline_takes_nothing_away_and_says_so():
    out = _page(_SEARCH_RESULTS + """
      state._selectedUids = new Set([7, 8]);
      answers.set('7', new TypeError('Failed to fetch'));
      answers.set('8', new TypeError('Failed to fetch'));
      await _bulkAction('delete');
      console.log(JSON.stringify({ left: left(), toasts }));
    """)
    assert out["left"] == ["7", "8"]
    assert out["toasts"] == ["Failed to delete 2 emails"]


_MUTATION = re.compile(r"fetch\(`\$\{API_BASE\}/api/email/(delete|delete-permanent|archive|move)/[^`]*`")


def test_every_delete_archive_and_spam_sends_the_messages_own_folder():
    """The shape (`Law 20` option 3), over every such request in the module:
    the reader's and the card's menus build theirs inside closures no harness
    reaches. `emailInbox.js` keeps two in `_showEmailMenu`, which nothing calls."""
    code = blank_text(LIBRARY_JS, "js")
    sites = list(_MUTATION.finditer(code))
    assert len(sites) >= 10
    for m in sites:
        url = m.group(0)
        assert "_emailMutationQuery(" in url, url
        assert "state._libFolder" not in url, url


def test_every_delete_reads_the_servers_answer():
    code = blank_text(LIBRARY_JS, "js")
    deletes = [m for m in _MUTATION.finditer(code) if m.group(1).startswith("delete")]
    assert len(deletes) >= 5
    for m in deletes:
        rest = code[m.end():]
        after = rest[rest.index(";") + 1:].lstrip()
        assert after.split(";", 1)[0].count("_requireSuccessfulEmailMutation("), m.group(0)
