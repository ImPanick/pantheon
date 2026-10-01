# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1000`. The mailbox renamed attachments on the way out.

`P21-03` gave every door by which a person's file becomes a document one
naming module, `src/file_names.py`. The mailbox's own doors out kept
`re.sub(r"[^\\w\\s\\-.]", "_", name)`: the extraction cache (so
`GET /api/email/attachment/{uid}/{i}` downloaded `Q3 Board Pack _ final
_v2_.pdf`), the compose token (`compose-upload`, `compose-from-attachment`,
`compose-from-pantheon`), and from the token the `Content-Disposition` of
every message sent with an attachment. Measured on `0317787` with a fake IMAP
and a captured SMTP message, before a line was written:

* `Q3 Board Pack – final (v2).pdf` downloaded, was forwarded, was uploaded to
  compose and was received as `Q3 Board Pack _ final _v2_.pdf`;
* a 250-letter Cyrillic name could not be forwarded or uploaded at all
  (`ENAMETOOLONG`) — the regex keeps `\\w`, and had no cap;
* a sender's name carrying CR/LF (`evil"\\r\\nX-Injected: yes.pdf`, one RFC 2231
  parameter) reached the extraction cache, the forward token, and the
  outgoing header; Python 3.11.15's generator refused to write it
  (`HeaderWriteError`), so the forward failed — on a Python without that
  check it is a header the sender wrote into a message the person sends;
* an inline image named `схема.png` failed to load: its name went into the
  header raw and could not be encoded.

Everything here is driven: the real email router under `TestClient` over a
fake IMAP that hands back raw message bytes, `/send` with the SMTP call
captured and the captured message parsed back, and the naming functions
themselves. Nothing reads a source file (`Law 20`).
"""

from __future__ import annotations

import contextlib
import email
import email.policy
import json
import re
from pathlib import Path
from urllib.parse import quote, unquote

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.file_names import (
    ascii_filename,
    display_name,
    mime_attachment_disposition,
    stored_name,
)

Q3 = "Q3 Board Pack – final (v2).pdf"
PDF = b"%PDF-1.4 the board pack"

# The adversary is the sender: every name below arrives in a message somebody
# else wrote, as one RFC 2231 parameter, and the person downloads or forwards it.
HOSTILE = {
    "crlf": 'evil"\r\nX-Injected: yes.pdf',
    "quotes": 'the "final" one.pdf',
    "traversal": "../../etc/passwd",
    "rtl": "invoice‮FDP.exe",
    "long": "ж" * 250 + ".pdf",
    "dotfile": ".bashrc",
    "windows": "Minutes: what we agreed?.pdf",
}


def _raw_mail(name: str, payload: bytes = PDF, *, ctype="application/pdf",
              disposition="attachment", cid: str | None = None) -> bytes:
    """A message whose one attachment is called *name*, written the way a
    mail client writes a name it cannot put in a quoted string."""
    import base64
    head = (f"Content-Type: {ctype}\r\nContent-Transfer-Encoding: base64\r\n"
            f"Content-Disposition: {disposition}; filename*=utf-8''{quote(name, safe='')}\r\n")
    if cid:
        head += f"Content-ID: <{cid}>\r\n"
    return (
        "Message-ID: <m@example.com>\r\nSubject: the pack\r\nMIME-Version: 1.0\r\n"
        "Content-Type: multipart/mixed; boundary=B\r\n\r\n"
        "--B\r\nContent-Type: text/plain\r\n\r\nsee attached\r\n"
        "--B\r\n" + head + "\r\n" + base64.b64encode(payload).decode() + "\r\n--B--\r\n"
    ).encode()


class _Conn:
    def select(self, *_a, **_k):
        return "OK", [b"1"]


@pytest.fixture
def mailbox(tmp_path, monkeypatch):
    """The real email router over a fake IMAP and a captured SMTP send.

    Returns ``(client, messages, sent, dirs)``: put raw bytes in
    ``messages[uid]``; every delivered message's text lands in ``sent``."""
    import routes.email_helpers as EH
    import routes.email_routes as E
    from routes.email_helpers import require_owner, require_user

    messages: dict[str, bytes] = {}
    sent: list[str] = []
    extract = tmp_path / "extract"
    compose = tmp_path / "compose"
    compose.mkdir()

    @contextlib.contextmanager
    def fake_imap(account_id=None, owner=""):
        yield _Conn()

    def fake_fetch(_conn, uid, _query):
        uid = uid.decode() if isinstance(uid, bytes) else str(uid)
        if uid not in messages:
            return "NO", []
        return "OK", [(f"1 (UID {uid} BODY[])".encode(), messages[uid])]

    monkeypatch.setattr(E, "_start_poller", lambda: None)
    monkeypatch.setattr(E, "_imap", fake_imap)
    monkeypatch.setattr(E, "_imap_uid_fetch", fake_fetch)
    monkeypatch.setattr(E, "attachment_extract_dir", lambda folder, uid: extract / str(uid))
    monkeypatch.setattr(E, "_email_attachment_meta_cache_get", lambda *_a, **_k: None)
    monkeypatch.setattr(E, "_email_attachment_meta_cache_put", lambda *_a, **_k: None)
    monkeypatch.setattr(EH, "COMPOSE_UPLOADS_DIR", compose)
    monkeypatch.setattr(E, "COMPOSE_UPLOADS_DIR", compose)
    monkeypatch.setattr(E, "_resolve_send_config", lambda account_id=None, owner="": {
        "from_address": "me@example.com", "smtp_host": "smtp.example.com",
        "smtp_port": 465, "smtp_user": "me", "smtp_password": "pw"})
    monkeypatch.setattr(E, "_send_smtp_message",
                        lambda cfg, frm, rcpts, msg: sent.append(msg))

    app = FastAPI()
    app.include_router(E.setup_email_routes())
    app.dependency_overrides[require_owner] = lambda: ""
    app.dependency_overrides[require_user] = lambda: ""
    return TestClient(app), messages, sent, {"extract": extract, "compose": compose}


def _send(client, sent, tokens):
    r = client.post("/api/email/send", json={
        "to": "you@example.com", "subject": "fwd", "body": "here",
        "attachments": tokens, "wait_for_delivery": True})
    assert r.status_code == 200, r.text
    assert r.json().get("success") is True, r.json()
    return sent[-1]


def _sent_attachments(wire: str):
    """``[(name, Content-Disposition)]`` of each attached part, as a mail
    client parsing the delivered text would see them."""
    out = []
    for policy in (email.policy.compat32, email.policy.default):
        msg = email.message_from_string(wire, policy=policy)
        out.append([(p.get_filename(), str(p.get("Content-Disposition")))
                    for p in msg.walk() if p.get_filename()])
    assert [n for n, _ in out[0]] == [n for n, _ in out[1]], "two parsers disagree"
    return out[0]


def _assert_no_injection(wire: str):
    """Nothing the sender wrote became a header, and no line breaks the
    transport: every line under RFC 5322's 998, every header line short."""
    for policy in (email.policy.compat32, email.policy.default):
        msg = email.message_from_string(wire, policy=policy)
        for part in msg.walk():
            assert "X-Injected" not in part.keys(), "a sender's name wrote a header"
    lines = wire.split("\n")
    assert max(len(line) for line in lines) <= 998
    head_lines = [line for line in lines if "filename" in line]
    assert head_lines and max(len(line) for line in head_lines) <= 80


# ── the row's `Verify:` ──────────────────────────────────────────────────────

def test_the_board_pack_downloads_under_its_own_name(mailbox):
    client, messages, _sent, dirs = mailbox
    messages["42"] = _raw_mail(Q3)
    r = client.get("/api/email/attachment/42/0")
    assert r.status_code == 200
    assert r.content == PDF
    assert r.headers["content-type"] == "application/octet-stream"
    assert r.headers["content-disposition"] == (
        "attachment; filename=\"Q3 Board Pack final (v2).pdf\"; "
        "filename*=UTF-8''Q3%20Board%20Pack%20%E2%80%93%20final%20%28v2%29.pdf")
    assert [p.name for p in (dirs["extract"] / "42").iterdir()] == [Q3], \
        "the extraction cache keeps the readable name"


def test_the_board_pack_is_forwarded_under_its_own_name(mailbox):
    client, messages, sent, dirs = mailbox
    messages["42"] = _raw_mail(Q3)
    staged = client.post("/api/email/compose-from-attachment/42/0").json()
    assert staged["success"] is True
    assert staged["filename"] == Q3
    key, stored = staged["token"].split("_", 1)
    assert re.fullmatch(r"[0-9a-f]{32}", key), "the hex key stays the token's key"
    assert stored == Q3
    wire = _send(client, sent, [staged["token"]])
    [(name, header)] = _sent_attachments(wire)
    assert name == Q3
    assert header.startswith("attachment;")
    _assert_no_injection(wire)
    assert list(dirs["compose"].iterdir()) == [], "delivery cleans up the staged file"


def test_a_file_uploaded_to_compose_is_sent_under_its_own_name(mailbox):
    client, _messages, sent, _dirs = mailbox
    up = client.post("/api/email/compose-upload",
                     files={"file": (Q3, PDF, "application/pdf")}).json()
    assert up["success"] is True and up["filename"] == Q3
    [(name, _)] = _sent_attachments(_send(client, sent, [up["token"]]))
    assert name == Q3


# ── hostile names, for the download header and the outgoing MIME part ───────

@pytest.mark.parametrize("case", sorted(HOSTILE))
def test_a_hostile_name_downloads_as_an_attachment_and_writes_no_header(mailbox, case):
    client, messages, _sent, dirs = mailbox
    raw_name = HOSTILE[case]
    messages["7"] = _raw_mail(raw_name)
    r = client.get("/api/email/attachment/7/0")
    assert r.status_code == 200, r.text
    assert r.content == PDF
    cd = r.headers["content-disposition"]
    assert cd.startswith("attachment; "), "FORBIDDEN.md Part 2: never inline"
    assert "\r" not in cd and "\n" not in cd
    assert "x-injected" not in {k.lower() for k in r.headers.keys()}
    quoted = re.fullmatch(r'attachment; filename="([^"]*)"; filename\*=UTF-8\'\'(\S+)', cd)
    assert quoted, cd
    assert unquote(quoted.group(2)) == display_name(raw_name)
    assert quoted.group(1).isascii()
    [stored] = list((dirs["extract"] / "7").iterdir())
    assert stored.name == stored_name(raw_name)
    assert not stored.name.startswith(".") and "\n" not in stored.name and "\r" not in stored.name
    assert len(stored.name.encode("utf-8")) <= 200


@pytest.mark.parametrize("case", sorted(HOSTILE))
def test_a_hostile_name_is_forwarded_under_that_name_and_writes_no_header(mailbox, case):
    client, messages, sent, _dirs = mailbox
    raw_name = HOSTILE[case]
    messages["7"] = _raw_mail(raw_name)
    staged = client.post("/api/email/compose-from-attachment/7/0").json()
    assert staged["success"] is True, staged
    assert staged["filename"] == display_name(raw_name)
    assert "\n" not in staged["token"] and "\r" not in staged["token"]
    wire = _send(client, sent, [staged["token"]])
    [(name, header)] = _sent_attachments(wire)
    assert name == display_name(raw_name), "the recipient gets the person's name for it"
    assert header.startswith("attachment;")
    _assert_no_injection(wire)


def test_what_the_reader_lists_is_what_downloads_and_what_is_forwarded(mailbox):
    """One name: the chip, the download and the forward agree — an RTL
    override cannot make the chip say `invoiceexe.PDF` while the file is an
    `.exe`, and a folder in a sender's name is not shown."""
    client, messages, _sent, _dirs = mailbox
    messages["9"] = _raw_mail(HOSTILE["rtl"])
    listed = client.get("/api/email/attachments/9").json()["attachments"]
    assert [a["filename"] for a in listed] == ["invoiceFDP.exe"]
    cd = client.get("/api/email/attachment/9/0").headers["content-disposition"]
    assert cd.endswith("filename*=UTF-8''invoiceFDP.exe")
    assert client.post("/api/email/compose-from-attachment/9/0").json()["filename"] == "invoiceFDP.exe"


def test_a_listing_cached_before_this_is_shown_the_same_way(tmp_path, monkeypatch):
    """`email_attachment_metadata_cache` holds listings made before the
    listing named attachments by `display_name`. A cached one is shown as a
    fresh one would be, so the chip still agrees with the download — through
    the real cache table, written the way the listing writes it."""
    import routes.email_helpers as EH
    import routes.email_routes as E

    db_path = tmp_path / "email.db"
    monkeypatch.setattr(EH, "SCHEDULED_DB", db_path)
    monkeypatch.setattr(E, "SCHEDULED_DB", db_path)
    EH._init_scheduled_db()
    E._email_attachment_meta_cache_put("alice", None, "INBOX", "9", "<m@x>", [
        {"index": 0, "filename": HOSTILE["rtl"], "content_type": "application/x-msdownload"},
        {"index": 1, "filename": "../../etc/passwd", "content_type": "text/plain"},
        {"index": 2, "filename": "​", "content_type": "image/png"},
        {"index": 3, "filename": Q3, "content_type": "application/pdf"},
    ])
    cached = E._email_attachment_meta_cache_get("alice", None, "INBOX", "9")
    assert [a["filename"] for a in cached] == [
        "invoiceFDP.exe", "passwd", "attachment_2.png", Q3]


def test_a_name_that_cannot_be_stored_as_given_is_still_sent_as_given(mailbox):
    """`Minutes: what we agreed?.pdf` is stored `Minutes_ what we agreed_.pdf`
    (Windows refuses `:` and `?`). The person's name is kept beside the staged
    file, and the recipient receives that."""
    client, _messages, sent, dirs = mailbox
    up = client.post("/api/email/compose-upload", files={
        "file": (HOSTILE["windows"], PDF, "application/pdf")}).json()
    assert up["filename"] == HOSTILE["windows"]
    assert up["token"].split("_", 1)[1] == "Minutes_ what we agreed_.pdf"
    [(name, _)] = _sent_attachments(_send(client, sent, [up["token"]]))
    assert name == HOSTILE["windows"]
    assert list(dirs["compose"].iterdir()) == [], "the name beside it is cleaned up too"


def test_removing_a_staged_file_removes_the_name_kept_beside_it(mailbox):
    client, _messages, _sent, dirs = mailbox
    up = client.post("/api/email/compose-upload", files={
        "file": (HOSTILE["windows"], PDF, "application/pdf")}).json()
    assert len(list(dirs["compose"].iterdir())) == 2
    r = client.delete(f"/api/email/compose-upload/{quote(up['token'], safe='')}")
    assert r.json() == {"success": True}
    assert list(dirs["compose"].iterdir()) == []


def test_a_token_staged_before_this_is_sent_under_the_name_it_was_staged_with(mailbox):
    """`Law 1`: a draft or a scheduled email saved before `B1000` holds a
    token `<hex>_<mangled name>` and no name beside it. It still sends, under
    the name it was staged with."""
    client, _messages, sent, dirs = mailbox
    token = "0123456789abcdef0123456789abcdef_Q3 Board Pack _ final _v2_.pdf"
    (dirs["compose"] / token).write_bytes(PDF)
    [(name, _)] = _sent_attachments(_send(client, sent, [token]))
    assert name == "Q3 Board Pack _ final _v2_.pdf"


def test_a_name_kept_beside_a_file_cannot_be_reached_by_another_token(mailbox):
    """The kept name is looked up only by a 32-hex key: a token that names a
    path, or a key that is not hex, finds nothing beside it."""
    import routes.email_helpers as EH
    _client, _messages, _sent, dirs = mailbox
    assert EH._compose_name_path("../../x_y.pdf") is None
    assert EH._compose_name_path("NOTHEX_y.pdf") is None
    key = "0123456789abcdef0123456789abcdef"
    assert EH._compose_name_path(f"../{key}_y.pdf") == dirs["compose"] / f"{key}.name"


def test_a_document_is_attached_under_its_title(mailbox, monkeypatch):
    """`compose-from-pantheon` names a document by its title; a `/` in the
    title is part of it, not a folder to drop."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    import core.database as D

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    D.Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine)
    monkeypatch.setattr(D, "SessionLocal", maker)
    db = maker()
    db.add(D.Document(id="d1", title="Q3 Board Pack – final (v2)", language="markdown",
                      current_content="# Q3", is_active=True))
    db.add(D.Document(id="d2", title="Q3/Q4 plan", language="markdown",
                      current_content="# plan", is_active=True))
    db.commit()
    db.close()
    client, _messages, sent, _dirs = mailbox
    one = client.post("/api/email/compose-from-pantheon", json={"kind": "document", "id": "d1"}).json()
    two = client.post("/api/email/compose-from-pantheon", json={"kind": "document", "id": "d2"}).json()
    assert one["filename"] == "Q3 Board Pack – final (v2).md"
    assert two["filename"] == "Q3_Q4 plan.md"
    names = [n for n, _ in _sent_attachments(_send(client, sent, [one["token"], two["token"]]))]
    assert names == ["Q3 Board Pack – final (v2).md", "Q3_Q4 plan.md"]
    engine.dispose()


# ── the guards that had to keep their meaning ───────────────────────────────

def test_a_dotfile_attachment_is_still_refused_as_a_document_by_its_name(mailbox, monkeypatch):
    """`B04`'s dotfile refusal in `attachment-as-doc` read the extracted
    file's name. The extraction is `stored_name` now, which is never a
    dotfile (`.bashrc` is stored `bashrc`), so the refusal asks the sender's
    name — driven here through a real extraction, not a stub."""
    client, messages, _sent, dirs = mailbox
    monkeypatch.setattr("src.auth_helpers.get_current_user", lambda request: "")
    messages["5"] = _raw_mail(".bashrc", b"export PATH=/tmp\n", ctype="text/plain")
    r = client.post("/api/email/attachment-as-doc/5/0")
    assert r.json() == {"error": "Invalid filename", "filename": ".bashrc"}
    assert [p.name for p in (dirs["extract"] / "5").iterdir()] == ["bashrc"]


def test_an_inline_image_in_another_script_loads(mailbox):
    """The one route that serves sender bytes inline (its `image/` check is
    `FORBIDDEN.md` Part 2 and is pinned in
    `test_small_email_images_are_attachments_too`). Its header took the name
    raw; `схема.png` could not be encoded and the image failed to load."""
    client, messages, _sent, _dirs = mailbox
    png = b"\x89PNG\r\n\x1a\nfake"
    messages["8"] = _raw_mail("схема.png", png, ctype="image/png",
                              disposition="inline", cid="shot@x")
    r = client.get("/api/email/inline-image/8", params={"cid": "shot@x"})
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content == png
    assert r.headers["content-disposition"] == 'inline; filename="image.png"'


# ── the agent's door: the MCP mail server's `download_attachment` ───────────

def test_the_agent_downloads_an_attachment_under_its_own_name(tmp_path, monkeypatch):
    import mcp_servers.email_server as srv

    class _Imap:
        def select(self, *_a, **_k):
            return "OK", [b"1"]

        def uid(self, *_a, **_k):
            return "OK", [(b"1 (UID 3 BODY[])", _raw_mail(Q3))]

        def logout(self):
            pass

    monkeypatch.setattr(srv, "_imap_connect", lambda account=None: _Imap())
    monkeypatch.setattr(srv, "MAIL_ATTACHMENTS_DIR", str(tmp_path))
    out = srv._download_attachment(uid="3", index=0)
    assert out["filename"] == Q3
    assert Path(out["path"]).name == Q3
    assert Path(out["path"]).read_bytes() == PDF
    monkeypatch.setattr(srv, "_imap_connect", lambda account=None: type(
        "I", (_Imap,), {"uid": lambda self, *a, **k: ("OK", [(b"1", _raw_mail(HOSTILE["long"]))])})())
    out = srv._download_attachment(uid="4", index=0)
    assert out["filename"] == HOSTILE["long"]
    assert len(Path(out["path"]).name.encode("utf-8")) <= 200


# ── the naming functions themselves ─────────────────────────────────────────

@pytest.mark.parametrize("case", sorted(HOSTILE))
def test_the_mime_disposition_round_trips_through_two_mail_parsers(case):
    """What any mail client reads back is the person's name, under the old
    parser and the modern one, and the header is only ever `attachment`."""
    from email.mime.base import MIMEBase
    from email.mime.multipart import MIMEMultipart

    raw_name = HOSTILE[case]
    outer = MIMEMultipart("mixed")
    part = MIMEBase("application", "octet-stream")
    part.set_payload(b"x")
    part.add_header("Content-Disposition", mime_attachment_disposition(raw_name))
    outer.attach(part)
    for wire in (outer.as_string(), outer.as_bytes(policy=email.policy.SMTP).decode()):
        [(name, header)] = _sent_attachments(wire.replace("\r\n", "\n"))
        assert name == display_name(raw_name)
        assert header.startswith("attachment;") and "inline" not in header
        _assert_no_injection(wire.replace("\r\n", "\n"))


def test_a_short_plain_name_is_a_plain_quoted_parameter():
    assert mime_attachment_disposition("notes.txt") == 'attachment; filename="notes.txt"'
    assert mime_attachment_disposition('say "hi".txt') == (
        "attachment;\n filename*=utf-8''say%20%22hi%22.txt"), "a quote is encoded, never escaped"
    assert mime_attachment_disposition("") == 'attachment; filename="attachment"'


def test_a_long_name_is_folded_into_continuations_never_inside_an_escape():
    header = mime_attachment_disposition("ж" * 250 + ".pdf")
    lines = header.split("\n")
    assert len(lines) > 2 and all(line.startswith(" ") for line in lines[1:])
    values = [re.sub(r"^ ?filename\*\d+\*=(utf-8'')?", "", line).rstrip(";") for line in lines[1:]]
    assert all(not re.search(r"%[0-9A-F]?$", v) for v in values), "an escape split across lines"
    assert unquote("".join(values)) == "ж" * 250 + ".pdf"


def test_a_name_in_another_script_folds_to_a_name_not_a_dotfile():
    assert ascii_filename("схема.png", "image") == "image.png"
    assert ascii_filename(Q3) == "Q3 Board Pack final (v2).pdf"
    assert ascii_filename(".env") == ".env", "a real dotfile name is still its name"
    assert ascii_filename('the "final" one.pdf') == "the _final_ one.pdf"
