# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P23-08` — the Library and Mail do what they say (the server half).

Measured on `9560d50` by the docs auditor (`Doc1-Mechanism-report.md`), each
case below names its finding:

* DOCS-M-1 — every Reply and Compose made an "Email: <subject>" chat with no
  messages that outlived the draft (six Replies, six empty chats). The editor
  now lets go of such a chat when the draft closes; the server half is
  `DELETE /api/session/{id}?only_if_empty=true`, which counts the messages
  itself, because the browser's count can be a message behind.
* DOCS-M-3 — the scheduled Documents Tidy proposed an unsent compose ("junk
  title 'new email'") and four reply drafts of one mail ("a duplicate").
* DOCS-M-5 — a failed send toasted ``[Errno 111] Connection refused``.
* DOCS-M-6 — a PDF whose pages this server cannot draw was found out by a 503
  from ``render-pages``; the document answer now says ``can_render_pages``.
* DOCS-M-10 — a Subject with a bare 8-bit "—" read "���".

Driven (`Law 20`): the real session, document and mail routers under
`TestClient` over a real SQLite file, the real scheduled tidy, the real SMTP
client against a port nobody listens on, and the list parser on raw header
bytes. Nothing reads a source file.
"""

import asyncio
import contextlib
import email
import smtplib
import socket
import uuid
from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.test_the_documents_tidy_asks_first import LONG_AGO, cdb, doc, world  # noqa: F401
from tests.test_a_document_the_ai_tidy_keeps_is_not_edited import library  # noqa: F401

OWNER = "bob"
REPLY_SUBJECT = "Q3 Board Pack – final (v2)"
REPLY_BODY = ("To: priya@example.test\nSubject: Re: Q3 Board Pack – final (v2)\n"
              "In-Reply-To: <m1@example.test>\nX-Source-UID: 7\nX-Source-Folder: INBOX\n---\n"
              "Thanks — I'll read it tonight.\n\n> the pack is attached")


def draft(world, title, content, created=LONG_AGO, owner=OWNER):
    """A mail draft as Reply and Compose make one: a document in `email`."""
    doc_id = "e-" + uuid.uuid4().hex[:10]
    db = world.db()
    db.add(cdb.Document(id=doc_id, title=title, current_content=content, owner=owner,
                        language="email", is_active=True, created_at=created,
                        updated_at=created))
    db.commit()
    db.close()
    return doc_id


def alive(world, doc_id):
    db = world.db()
    try:
        row = db.query(cdb.Document).filter(cdb.Document.id == doc_id).first()
        return bool(row and row.is_active)
    finally:
        db.close()


# ── DOCS-M-3 · no tidy offers to delete a draft ─────────────────────────────

@pytest.fixture
def drafts_world(world):
    """The audit's world: an unsent compose, four reply drafts of one mail,
    and the clutter a tidy is for."""
    ids = {
        "compose": draft(world, "New Email", "To: \nSubject: \n---\n"),
        "compose_typed": draft(world, "New Email",
                               "To: ana@example.test\nSubject: lunch\n---\nFriday at one?"),
        "replies": [draft(world, REPLY_SUBJECT, REPLY_BODY) for _ in range(4)],
        "junk": doc(world, "test"),
        "copy": doc(world, "Notes", content="the same notes"),
        "copy2": doc(world, "Notes", content="the same notes",
                     created=LONG_AGO + timedelta(days=1)),
        "keep": doc(world, "Budget 2026", content="real numbers"),
    }
    return ids


def _drafts(ids):
    return {ids["compose"], ids["compose_typed"], *ids["replies"]}


def test_the_scheduled_tidy_never_proposes_a_draft(world, drafts_world):
    """The row's `Verify:` — the Tidy on a world with drafts does not propose them."""
    from src import document_actions

    plan, judged, _kept = document_actions.propose_document_tidy(OWNER)
    proposed = {c["id"] for c in plan.changes if c.get("change") == "deleted"}
    assert judged == 10
    assert not proposed & _drafts(drafts_world), [
        (c["title"], c.get("reason")) for c in plan.changes if c["id"] in _drafts(drafts_world)]
    # It still does its job on what is clutter.
    assert drafts_world["junk"] in proposed
    assert len(proposed & {drafts_world["copy"], drafts_world["copy2"]}) == 1
    assert drafts_world["keep"] not in proposed
    labels = [i["label"] for i in plan.review["items"]]
    assert "New Email" not in labels and REPLY_SUBJECT not in labels


def test_the_scheduled_run_deletes_nothing_and_asks_about_no_draft(world, drafts_world):
    from src import document_actions

    said = asyncio.run(document_actions.run_document_tidy(OWNER))
    assert "test" in said and "New Email" not in said and "Q3 Board Pack" not in said
    assert all(alive(world, d) for d in _drafts(drafts_world))


def test_the_rules_both_tidies_read_leave_drafts_out(world, drafts_world):
    """`tidy_reasons` is what the agent's `manage_documents tidy` reads too."""
    from src.document_actions import tidy_reasons

    db = world.db()
    try:
        docs = db.query(cdb.Document).filter(cdb.Document.owner == OWNER).all()
        reasons = tidy_reasons(docs)
    finally:
        db.close()
    assert not set(reasons) & _drafts(drafts_world)
    assert reasons[drafts_world["junk"]] == "junk title 'test'"


def test_a_draft_alone_is_not_a_reason_to_ask(world):
    from src import document_actions
    from src.builtin_actions import TaskNoop

    for _ in range(3):
        draft(world, REPLY_SUBJECT, REPLY_BODY)
    draft(world, "New Email", "To: \nSubject: \n---\n")
    with pytest.raises(TaskNoop, match="no junk"):
        asyncio.run(document_actions.run_document_tidy(OWNER))


def test_the_library_tidy_keeps_a_typed_draft_and_clears_an_empty_envelope(world, library):
    """The person's own Tidy: its title rule no longer deletes a draft somebody
    typed into ("New Email" is a draft's title by construction); an envelope
    nobody typed into still goes, as its dialog says."""
    typed = draft(world, "New Email", "To: ana@example.test\nSubject: lunch\n---\nFriday at one?")
    reply = draft(world, REPLY_SUBJECT, REPLY_BODY)
    envelope = draft(world, "New Email", "To: \nSubject: \n---\n")
    junk = doc(world, "test")
    import routes.document.document_routes as droutes

    app = FastAPI()
    app.include_router(droutes.setup_document_routes(None, None))
    res = TestClient(app).post("/api/documents/tidy")
    assert res.status_code == 200, res.text
    db = world.db()
    try:
        left = {d.id for d in db.query(cdb.Document).all()}
    finally:
        db.close()
    assert typed in left and reply in left
    assert envelope not in left and junk not in left


def test_the_ai_tidy_never_hands_a_draft_to_the_model(world, library):
    """The library's AI pass deletes what the model calls junk; a short reply
    is easy to call junk, so a draft is never asked about."""
    reply = draft(world, REPLY_SUBJECT, REPLY_BODY)
    doc(world, "scratch idea", content="maybe")
    library.verdicts.update({REPLY_SUBJECT: "junk", "scratch idea": "junk"})
    out = library.tidy()
    assert (out["reviewed"], out["deleted"]) == (1, 1), out
    assert REPLY_SUBJECT not in "\n".join(library.asked)
    assert alive(world, reply)


# ── DOCS-M-6 · the document answer says whether its pages can be drawn ──────

PDF_DOC = '<!-- pdf_source upload_id="' + "a" * 32 + '" -->\n\n# Lease\n\n[Page 1 text]: rent'


def _get(client, doc_id):
    res = client.get(f"/api/document/{doc_id}")
    assert res.status_code == 200, res.text
    return res.json()


@pytest.fixture
def documents(world, monkeypatch):
    import routes.document.document_routes as droutes

    monkeypatch.setattr(droutes, "SessionLocal", world.db)
    monkeypatch.setattr(droutes, "get_current_user", lambda request: OWNER)
    app = FastAPI()
    app.include_router(droutes.setup_document_routes(None, None))
    return TestClient(app)


def test_a_pdf_says_it_cannot_be_drawn_where_pymupdf_is_missing(world, documents, monkeypatch):
    import src.pdf_runtime as pr

    def missing():
        raise RuntimeError(pr.PDF_VIEWER_PYMUPDF_MISSING)

    monkeypatch.setattr(pr, "load_pymupdf_for_pdf_viewer", missing)
    pdf = doc(world, "Lease", content=PDF_DOC)
    assert _get(documents, pdf)["can_render_pages"] is False


def test_a_pdf_says_it_can_be_drawn_where_pymupdf_is_there(world, documents, monkeypatch):
    import src.pdf_runtime as pr

    monkeypatch.setattr(pr, "load_pymupdf_for_pdf_viewer", lambda: object())
    pdf = doc(world, "Lease", content=PDF_DOC)
    assert _get(documents, pdf)["can_render_pages"] is True


def test_a_document_that_is_not_a_pdf_does_not_carry_the_flag(world, documents):
    plain = doc(world, "Budget 2026", content="real numbers")
    assert "can_render_pages" not in _get(documents, plain)


# ── DOCS-M-1 · a helper chat is deleted only while it is empty ──────────────

@pytest.fixture
def sessions(world, monkeypatch):
    """The real session routes and a real session manager over the world's DB."""
    import core.session_manager as csm
    import routes.session_routes as session_routes

    for mod in (csm, session_routes):
        monkeypatch.setattr(mod, "SessionLocal", world.db)
    manager = csm.SessionManager()
    app = FastAPI()

    @app.middleware("http")
    async def _as_bob(request, call_next):
        request.state.current_user = OWNER
        request.state.api_token = False
        return await call_next(request)

    app.include_router(session_routes.setup_session_routes(manager, {}))
    return type("Sessions", (), {"client": TestClient(app), "manager": manager})


def chat(world, name="Email: " + REPLY_SUBJECT, messages=0):
    sid = "s-" + uuid.uuid4().hex[:10]
    db = world.db()
    db.add(cdb.Session(id=sid, owner=OWNER, name=name, model="m", endpoint_url="http://x"))
    for i in range(messages):
        db.add(cdb.ChatMessage(id=str(uuid.uuid4()), session_id=sid, role="user",
                               content=f"message {i}", timestamp=datetime.utcnow()))
    db.commit()
    db.close()
    return sid


def chat_exists(world, sid):
    db = world.db()
    try:
        return db.query(cdb.Session.id).filter(cdb.Session.id == sid).first() is not None
    finally:
        db.close()


def test_an_empty_helper_chat_is_deleted_and_its_draft_stays_in_the_library(world, sessions):
    sid = chat(world)
    kept = draft(world, REPLY_SUBJECT, REPLY_BODY)
    db = world.db()
    db.query(cdb.Document).filter(cdb.Document.id == kept).update({cdb.Document.session_id: sid})
    db.commit()
    db.close()
    res = sessions.client.delete(f"/api/session/{sid}?only_if_empty=true")
    assert res.status_code == 200, res.text
    assert not chat_exists(world, sid)
    db = world.db()
    try:
        row = db.query(cdb.Document).filter(cdb.Document.id == kept).one()
        assert row.is_active and row.session_id is None
    finally:
        db.close()


def test_a_helper_chat_somebody_wrote_in_is_kept(world, sessions):
    sid = chat(world, messages=1)
    res = sessions.client.delete(f"/api/session/{sid}?only_if_empty=true")
    assert res.status_code == 409
    assert res.json()["detail"] == "This chat has messages, so it stays."
    assert chat_exists(world, sid)


def test_a_message_only_the_live_transcript_holds_also_keeps_it(world, sessions):
    """A message the session manager holds but has not written yet: the
    server's own count, not the stored rows alone, decides."""
    sid = chat(world)
    live = sessions.manager.get_session(sid)
    from core.models import ChatMessage
    live.history.append(ChatMessage("user", "just typed"))
    res = sessions.client.delete(f"/api/session/{sid}?only_if_empty=true")
    assert res.status_code == 409
    assert chat_exists(world, sid)


def test_without_the_flag_a_chat_is_deleted_as_before(world, sessions):
    sid = chat(world, name="My chat", messages=2)
    res = sessions.client.delete(f"/api/session/{sid}")
    assert res.status_code == 200, res.text
    assert not chat_exists(world, sid)


# ── DOCS-M-5 · a failed send names the server ───────────────────────────────

def _closed_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def mailer(monkeypatch):
    """The real mail router; `/send` goes through the real SMTP client to
    whatever `host`/`port` the test sets."""
    import routes.email_helpers as EH
    import routes.email_routes as E

    target = {"host": "127.0.0.1", "port": _closed_port()}
    monkeypatch.setattr(E, "_start_poller", lambda: None)
    monkeypatch.setattr(E, "_resolve_send_config", lambda account_id=None, owner="": {
        "from_address": "me@example.test", "smtp_host": target["host"],
        "smtp_port": target["port"], "smtp_security": "none",
        "smtp_user": "", "smtp_password": ""})
    app = FastAPI()
    app.include_router(E.setup_email_routes())
    # The integrator's note: a purge earlier in a full run can leave the two
    # modules holding different `require_owner`s — override both.
    for dep in {EH.require_owner, E.require_owner, EH.require_user, E.require_user}:
        app.dependency_overrides[dep] = lambda: ""
    return TestClient(app), target


def test_a_send_to_a_server_that_is_not_there_names_it(mailer):
    client, target = mailer
    res = client.post("/api/email/send", json={
        "to": "priya@example.test", "subject": "Re: lunch", "body": "Friday works.",
        "wait_for_delivery": True})
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["success"] is False
    assert out["error"] == (f"Couldn't reach the mail server (127.0.0.1:{target['port']}). "
                            "Check the account's SMTP settings.")
    assert "Errno" not in out["error"]


def test_each_kind_of_send_failure_says_what_to_check():
    from routes.email_helpers import _smtp_send_failure

    host, port = "smtp.example.test", 587
    said = {
        "auth": _smtp_send_failure(host, port, smtplib.SMTPAuthenticationError(
            535, b"5.7.8 Username and Password not accepted")),
        "rcpt": _smtp_send_failure(host, port, smtplib.SMTPRecipientsRefused(
            {"x@y": (550, b"no such user")})),
        "sender": _smtp_send_failure(host, port, smtplib.SMTPSenderRefused(
            553, b"sender rejected", "me@example.test")),
        "size": _smtp_send_failure(host, port, smtplib.SMTPDataError(
            552, b"5.3.4 Message size exceeds fixed limit")),
        "hung_up": _smtp_send_failure(host, port, smtplib.SMTPServerDisconnected("gone")),
        "greeting": _smtp_send_failure(host, port, smtplib.SMTPConnectError(421, b"busy")),
        "timeout": _smtp_send_failure(host, port, TimeoutError("timed out")),
        "dns": _smtp_send_failure(host, port, socket.gaierror(-2, "Name or service not known")),
        "other": _smtp_send_failure(host, port, ValueError("odd")),
    }
    where = "(smtp.example.test:587)"
    assert said["auth"] == (f"The mail server {where} did not accept the sign-in. "
                            "Check the account's SMTP user and password.")
    assert said["rcpt"] == (f"The mail server {where} refused every recipient. "
                            "Check the addresses in To, Cc and Bcc.")
    assert said["sender"] == (f"The mail server {where} refused the sender address. "
                              "Check the account's email address.")
    assert said["size"] == f"The mail server {where} refused this mail: 5.3.4 Message size exceeds fixed limit"
    unreachable = f"Couldn't reach the mail server {where}. Check the account's SMTP settings."
    for kind in ("hung_up", "greeting", "timeout", "dns"):
        assert said[kind] == unreachable, kind
    assert said["other"] == "Couldn't send this mail through smtp.example.test:587."
    assert not any("Errno" in s or "b'" in s for s in said.values())


def test_microsoft_s_own_rule_is_still_said_for_its_sign_in():
    from routes.email_helpers import _smtp_send_failure

    out = _smtp_send_failure("smtp.office365.com", 587, smtplib.SMTPAuthenticationError(
        535, b"5.7.139 Authentication unsuccessful, basic authentication is disabled."))
    assert "Sign in with Microsoft" in out


# ── DOCS-M-10 · an 8-bit Subject decodes ────────────────────────────────────

def _list_row(raw_header: bytes):
    from routes.email_routes import _parse_email_list_record
    return _parse_email_list_record(b"1 (UID 7 FLAGS (\\Seen) RFC822.SIZE 120)", raw_header)


@pytest.mark.parametrize("raw, shown", [
    ("Spring menu site — quote accepted".encode("utf-8"), "Spring menu site — quote accepted"),
    ("Café menu".encode("latin-1"), "Café menu"),            # 8-bit, not UTF-8
    (b"=?utf-8?q?Re=3A_Jos=C3=A9?= and plain", "Re: José and plain"),   # RFC 2047 unchanged
    (b"Plain ascii", "Plain ascii"),
])
def test_the_list_shows_the_subject_the_sender_wrote(raw, shown):
    row = _list_row(b"From: Ana <ana@example.test>\r\nSubject: " + raw
                    + b"\r\nDate: Mon, 5 Oct 2026 09:00:00 +0000\r\n\r\n")
    assert row["subject"] == shown
    assert "�" not in row["subject"]


def test_the_reader_s_header_decodes_too():
    from routes.email_helpers import _decode_header

    msg = email.message_from_bytes(
        "From: Ana <ana@example.test>\r\nSubject: Spring menu site — quote accepted\r\n\r\nhi"
        .encode("utf-8"))
    assert _decode_header(msg.get("Subject")) == "Spring menu site — quote accepted"
    # The same bytes reaching a str path surrogate-escaped.
    assert _decode_header("x \udce2\udc80\udc94 y") == "x — y"
