# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1600` — `download_attachment` saves into a folder inside the person's
projects folder, and nowhere else.

It always wrote `MAIL_ATTACHMENTS_DIR/<folder>_<uid>/<name>`, so Attachment
Filer — whose whole job is "save attachments to the right project folder" —
could not do its job, and Tax Folder Builder's "download each into the
folder" step could not be followed. It takes a `destination` now (and a
`filename`, so a filer can add the date rather than overwrite), confined by
the file tools' own rule to this person's projects folder.

**The adversary (`Law 17`)** is whoever wrote the mail: the attachment's name
is theirs, and so may be the folder a model was steered into naming. Driven
through the real MCP mail server's `_download_attachment` over a fake IMAP,
and through the agents' evaluation world.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tests.test_a_mail_attachment_keeps_its_name_on_the_way_out import HOSTILE, PDF, Q3, _raw_mail

OWNER = "alice"


@pytest.fixture
def mailbox(tmp_path, monkeypatch):
    """The real server function, a fake IMAP holding one message per uid, the
    data folder in `tmp_path`, and the call made as Alice."""
    import mcp_servers.email_server as srv
    import src.constants as constants
    from src.tool_execution import projects_root

    messages = {"3": _raw_mail(Q3), "4": _raw_mail(HOSTILE["traversal"]), "5": _raw_mail(HOSTILE["dotfile"])}

    class _Imap:
        def select(self, *_a, **_k):
            return "OK", [b"1"]

        def uid(self, _cmd, uid, *_a, **_k):
            uid = uid.decode() if isinstance(uid, bytes) else str(uid)
            return "OK", [(f"1 (UID {uid} BODY[])".encode(), messages[uid])]

        def logout(self):
            pass

    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(constants, "DATA_DIR", str(data))
    monkeypatch.setattr(srv, "_imap_connect", lambda account=None: _Imap())
    monkeypatch.setattr(srv, "MAIL_ATTACHMENTS_DIR", str(tmp_path / "mail-attachments"))
    token = srv._CURRENT_OWNER.set(OWNER)
    try:
        yield srv, Path(projects_root(OWNER, create=True)), tmp_path
    finally:
        srv._CURRENT_OWNER.reset(token)


def test_it_saves_into_a_folder_inside_the_projects_folder(mailbox):
    srv, root, _tmp = mailbox
    out = srv._download_attachment(uid="3", index=0, destination="invoices/2026")
    assert "error" not in out, out
    assert Path(out["path"]) == root / "invoices" / "2026" / Q3
    assert Path(out["path"]).read_bytes() == PDF
    assert out["filename"] == Q3


def test_it_takes_a_name_and_never_overwrites(mailbox):
    srv, root, _tmp = mailbox
    srv._download_attachment(uid="3", index=0, destination="invoices")
    again = srv._download_attachment(uid="3", index=0, destination="invoices")
    assert "already in your projects folder; nothing was saved" in again["error"]
    dated = srv._download_attachment(uid="3", index=0, destination="invoices",
                                     filename="2026-10-01 " + Q3)
    assert Path(dated["path"]) == root / "invoices" / ("2026-10-01 " + Q3)
    assert sorted(p.name for p in (root / "invoices").iterdir()) == sorted([Q3, "2026-10-01 " + Q3])


@pytest.mark.parametrize("where", ["../../outside", "/tmp/elsewhere", "../bob", "invoices/../../.."])
def test_a_folder_outside_the_projects_folder_is_refused_in_a_sentence(mailbox, where):
    srv, root, tmp = mailbox
    before = sorted(str(p) for p in tmp.rglob("*"))
    out = srv._download_attachment(uid="3", index=0, destination=where)
    assert "is not a folder inside your projects folder" in out.get("error", ""), out
    assert sorted(str(p) for p in tmp.rglob("*")) == before, "something was written"


def test_a_symlink_out_of_the_projects_folder_is_refused(mailbox):
    srv, root, tmp = mailbox
    outside = tmp / "outside"
    outside.mkdir()
    (root / "escape").symlink_to(outside, target_is_directory=True)
    out = srv._download_attachment(uid="3", index=0, destination="escape")
    assert "is not a folder inside your projects folder" in out.get("error", ""), out
    assert list(outside.iterdir()) == []


def test_the_senders_name_is_a_file_name_never_a_path(mailbox):
    srv, root, _tmp = mailbox
    out = srv._download_attachment(uid="4", index=0, destination="inbox")
    assert Path(out["path"]) == root / "inbox" / "passwd"
    out = srv._download_attachment(uid="5", index=0, destination="inbox", filename="../../.bashrc")
    assert Path(out["path"]).parent == root / "inbox" and not Path(out["path"]).name.startswith(".")


def test_with_no_destination_it_goes_where_it_always_went(mailbox):
    """`Law 1`."""
    srv, root, tmp = mailbox
    out = srv._download_attachment(uid="3", index=0)
    assert Path(out["path"]) == tmp / "mail-attachments" / "INBOX_3" / Q3
    assert not any(root.rglob("*"))


def test_the_model_is_offered_the_destination():
    from src.tool_schemas import FUNCTION_TOOL_SCHEMAS
    fn = next(s["function"] for s in FUNCTION_TOOL_SCHEMAS if s["function"]["name"] == "download_attachment")
    assert {"destination", "filename"} <= set(fn["parameters"]["properties"])
    assert fn["parameters"]["required"] == ["uid", "index"]


def test_the_evaluation_world_files_an_attachment_by_the_same_rule():
    from src.agents import evals as E
    from src.tool_execution import projects_root
    world = E.World({"emails": [{"id": "m1", "from": "Heat Ltd <bills@heat.example>", "subject": "Invoice",
                                 "attachments": [{"filename": "invoice-118.pdf", "content": "Total 140"}]}]})
    with E.isolated():
        ask = lambda **a: json.loads(world.answer("download_attachment", json.dumps({"uid": "m1", "index": 0, **a}))[1]["output"])
        saved = ask(destination="bills/heat")
        root = projects_root(E.EVAL_OWNER, create=False)
        assert saved["path"] == os.path.join(root, "bills", "heat", "invoice-118.pdf")
        assert open(saved["path"], encoding="utf-8").read() == "Total 140"
        assert "nothing was saved" in ask(destination="bills/heat")["error"]
        assert "not a folder inside your projects folder" in ask(destination="../../x")["error"]
        assert ask() == {"saved": "attachment"}, "without a destination the world answers as before"
