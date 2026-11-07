# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2034` — two people's "INBOX 42" were one folder, and the agent's could leave it.

Both mail doors extract an attachment to disk before serving or copying it:
the routes through `routes/email_helpers.attachment_extract_dir`, the agent's
mail server in `mcp_servers/email_server._download_attachment`. Both named the
folder `<folder>_<uid>` and nothing else, and an IMAP UID is a small counter
of one mailbox, so every person's and every account's message 42 in INBOX was
extracted into `mail-attachments/INBOX_42/`, and each extraction rewrote the
file of the same name that someone else had just been handed: Bob opening an
`invoice.pdf` replaced the bytes at the path Alice's download was served
from. The agent's door also joined `folder` as it was given, so a folder of
`../../x` or an absolute name wrote outside the attachments area.

Now the folder is `mail-attachments/<scope>/<folder>_<uid>`, where `scope` is
32 hex characters of a hash of the owner and the account
(`src/mail_attachment_paths.attachment_scope_dir`, used by both doors) and the
leaf is the old name flattened to `[A-Za-z0-9._-]`, checked once resolved to
sit exactly two levels under the area. From upstream Odysseus 3d91ad82.

Driven through the real `GET /api/email/attachment/{uid}/{index}` handler and
the real `_download_attachment`, over fake mailboxes.
"""
from __future__ import annotations

import contextlib
import re
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from types import SimpleNamespace

import pytest


def _message_with_attachment(body: bytes) -> bytes:
    msg = MIMEMultipart()
    msg.attach(MIMEText("see attached", "plain"))
    part = MIMEApplication(body, Name="invoice.pdf")
    part["Content-Disposition"] = 'attachment; filename="invoice.pdf"'
    msg.attach(part)
    return msg.as_bytes()


def test_each_owner_and_each_account_has_a_folder_of_its_own(tmp_path, monkeypatch):
    import routes.email_helpers as helpers

    monkeypatch.setattr(helpers, "ATTACHMENTS_DIR", tmp_path)
    alice = helpers.attachment_extract_dir("INBOX", "42", owner="alice", account_id="a1")
    assert alice != helpers.attachment_extract_dir("INBOX", "42", owner="bob", account_id="a1")
    assert alice != helpers.attachment_extract_dir("INBOX", "42", owner="alice", account_id="a2")
    assert alice != helpers.attachment_extract_dir("INBOX/42", "", owner="alice", account_id="a1")
    assert alice == helpers.attachment_extract_dir("INBOX", 42, owner="alice", account_id="a1")
    # The old name is the leaf still: `B1600`'s "where it always went".
    assert alice.name == "INBOX_42" and alice.parent.parent == tmp_path.resolve()


def test_two_people_with_the_same_message_number_each_download_their_own_attachment(tmp_path, monkeypatch):
    """Alice and Bob, the same INBOX UID 42, the same attachment name."""
    import routes.email_helpers as helpers
    import routes.email_routes as email_routes

    monkeypatch.setattr(helpers, "ATTACHMENTS_DIR", tmp_path)
    mailboxes = {"alice": _message_with_attachment(b"%PDF alice private invoice"),
                 "bob": _message_with_attachment(b"%PDF bob controlled content")}

    @contextlib.contextmanager
    def _fake_imap(account_id=None, owner=""):
        yield SimpleNamespace(owner=owner, select=lambda *a, **k: ("OK", [b"1"]))

    monkeypatch.setattr(email_routes, "_start_poller", lambda: None)
    monkeypatch.setattr(email_routes, "_imap", _fake_imap)
    monkeypatch.setattr(email_routes, "_imap_uid_fetch",
                        lambda conn, uid, query: ("OK", [(b"42 (RFC822)", mailboxes[conn.owner])]))
    router = email_routes.setup_email_routes()
    download = next(r.endpoint for r in router.routes if r.path == "/api/email/attachment/{uid}/{index}")

    alice = download(uid="42", index=0, folder="INBOX", account_id=None, owner="alice")
    bob = download(uid="42", index=0, folder="INBOX", account_id=None, owner="bob")

    assert alice.path != bob.path
    assert Path(alice.path).read_bytes() == b"%PDF alice private invoice"
    assert Path(bob.path).read_bytes() == b"%PDF bob controlled content"


@pytest.mark.parametrize("level", ["scope", "leaf"])
def test_a_symlink_planted_in_the_attachments_area_cannot_send_an_extraction_elsewhere(tmp_path, level):
    from src.mail_attachment_paths import attachment_scope_dir

    root = tmp_path / "root"
    root.mkdir()
    target = attachment_scope_dir(root, "INBOX", "1", owner="o", account_id="a")
    outside = tmp_path / "outside"
    outside.mkdir()
    if level == "scope":
        target.parent.symlink_to(outside, target_is_directory=True)
    else:
        target.parent.mkdir()
        target.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        attachment_scope_dir(root, "INBOX", "1", owner="o", account_id="a")


# ── the agent's door ───────────────────────────────────────────────────────

@pytest.fixture
def agent_mail(tmp_path, monkeypatch):
    import mcp_servers.email_server as es

    root = tmp_path / "data" / "mail-attachments"
    root.mkdir(parents=True)
    monkeypatch.setattr(es, "MAIL_ATTACHMENTS_DIR", str(root))
    monkeypatch.setattr(es, "_load_config", lambda account=None: {"account_id": account})
    box = {"raw": _message_with_attachment(b"%PDF one")}

    class _Conn:
        def select(self, *a, **k):
            return ("OK", [b"1"])

        def uid(self, *a):
            return ("OK", [(b"42 (UID 42 BODY[])", box["raw"])])

        def logout(self):
            pass

    monkeypatch.setattr(es, "_imap_connect", lambda account=None: _Conn())
    return es, root.resolve(), box


@pytest.mark.parametrize("folder", ["../../escape", "an absolute name", "[Gmail]/All Mail"])
def test_the_agents_download_stays_in_its_folder_inside_the_attachments_area(agent_mail, tmp_path, folder):
    es, root, _box = agent_mail
    if folder == "an absolute name":
        folder = str(tmp_path / "abs" / "p")   # outside the area, inside this test's own folder
    out = es._download_attachment("42", 0, folder)

    path = Path(out["path"]).resolve()
    assert path.parent.parent.parent == root, path
    assert path.parent.name == re.sub(r"[^A-Za-z0-9._-]", "_", f"{folder}_42"), path
    assert path.read_bytes() == b"%PDF one"


def test_the_agents_download_is_its_owners_and_its_accounts_own(agent_mail):
    es, _root, box = agent_mail
    paths = {}
    for owner, account, body in (("alice", "acct-a", b"%PDF alice"), ("bob", "acct-a", b"%PDF bob"),
                                 ("alice", "acct-b", b"%PDF alice second mailbox")):
        token = es._CURRENT_OWNER.set(owner)
        try:
            box["raw"] = _message_with_attachment(body)
            paths[(owner, account)] = (es._download_attachment("42", 0, "INBOX", account=account)["path"], body)
        finally:
            es._CURRENT_OWNER.reset(token)

    assert len({path for path, _ in paths.values()}) == 3
    for path, body in paths.values():
        assert Path(path).read_bytes() == body
