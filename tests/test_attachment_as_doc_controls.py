# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B04` — the controls on `POST /api/email/attachment-as-doc`.

`attachment_as_doc` shipped in `P2-07` with no tests and never had any. The
route reaches into a mailbox, writes a file to disk, and creates a Document
the editor will open, so the things worth pinning are not the happy path —
they are the four guards that decide whether it does any of that at all:

* **who is asking** — `owner` comes from the `require_owner` dependency and is
  the value handed to `_imap`. A route that resolved the owner and then opened
  the mailbox without it would pass every extension test in the suite.
* **where the bytes came from** — the extracted path is checked against the
  extraction root with `commonpath`, because the filename comes out of an
  attacker-supplied MIME header.
* **what a dotfile is** — `.bashrc`-shaped names are refused by name before
  anything reads them.
* **what a refusal says** — the callers depend on the *shape* of the answer:
  `emailLibrary.js` falls back to the download route on any `{error}`, and the
  outer handler must not put an exception's text on the wire.

`tests/test_attachment_extension_registers.py` already drives this route for
the question *which extractor answers these bytes* (`B05`/`B76`/`B100`), and
that question is deliberately not re-asked here. The one overlap is the `.log`
case, because that sentence is `B02`'s `Verify:` clause and deserves to fail
under its own name.

Only IMAP and the MIME extractor are faked. Everything from the containment
check through the decode decision and the Document write is the shipped code.
"""
import contextlib
import inspect

import pytest

import routes.email_routes as email_routes
from routes.email_helpers import require_owner

RAW_EMAIL = b"Subject: t\r\nMessage-ID: <m@x>\r\n\r\nbody\r\n"


def _endpoint():
    router = email_routes.setup_email_routes()
    for route in router.routes:
        if (route.path == "/api/email/attachment-as-doc/{uid}/{index}"
                and "POST" in getattr(route, "methods", set())):
            return route.endpoint
    raise AssertionError("POST /api/email/attachment-as-doc is not registered")


def _drive(tmp_path, monkeypatch, name, body: bytes, *, extracted=None,
           owner="tester", fetch_status="OK", extract_dir=None):
    """Call the real endpoint over one real file on disk.

    Returns ``(result, seen)`` where ``seen`` records what the route passed to
    ``_imap`` — the owner it opened the mailbox as.
    """
    target = tmp_path / "extract"
    target.mkdir(parents=True, exist_ok=True)
    if name is not None:
        (target / name).write_bytes(body)
    seen = {}

    @contextlib.contextmanager
    def fake_imap(account_id=None, owner=""):
        seen["account_id"] = account_id
        seen["owner"] = owner
        yield type("C", (), {"select": lambda self, *a, **k: None})()

    monkeypatch.setattr(email_routes, "_imap", fake_imap)
    monkeypatch.setattr(email_routes, "_imap_uid_fetch",
                        lambda *a, **k: (fetch_status, [(None, RAW_EMAIL)]))
    monkeypatch.setattr(email_routes, "attachment_extract_dir",
                        extract_dir or (lambda folder, uid: target))
    resolved = extracted if extracted is not None else (target / name if name else None)
    monkeypatch.setattr(email_routes, "_extract_attachment_to_disk",
                        lambda msg, index, d: resolved)
    monkeypatch.setattr("src.auth_helpers.get_current_user", lambda request: "tester")

    result = _endpoint()("42", 0, request=None, folder="INBOX",
                         account_id=None, owner=owner)
    return result, seen


# ── Who is asking ───────────────────────────────────────────────────────────

def test_the_route_is_wired_to_the_owner_dependency():
    """Read off the registered route, not out of the file. `require_owner`
    authenticates and, when `account_id` is in the query string, asserts the
    caller owns that mailbox — this route takes `account_id` as a query param,
    so it is the dependency that has to be there and not `require_user`."""
    params = inspect.signature(_endpoint()).parameters
    assert "owner" in params, "the route takes no owner"
    assert getattr(params["owner"].default, "dependency", None) is require_owner


def test_an_unauthenticated_caller_is_refused_by_that_dependency():
    """Driven rather than asserted about: the dependency itself 401s a
    non-loopback caller once an auth manager is configured."""
    from types import SimpleNamespace

    from fastapi import HTTPException

    request = SimpleNamespace(
        state=SimpleNamespace(current_user=None),
        app=SimpleNamespace(state=SimpleNamespace(
            auth_manager=SimpleNamespace(is_configured=True))),
        client=SimpleNamespace(host="203.0.113.9"),
    )
    with pytest.raises(HTTPException) as exc:
        require_owner(request, account_id=None)
    assert exc.value.status_code == 401


def test_the_resolved_owner_is_what_opens_the_mailbox(tmp_path, monkeypatch):
    """The gate is worth nothing if the route then opens IMAP as somebody
    else. The owner the dependency returned is the owner `_imap` receives."""
    result, seen = _drive(tmp_path, monkeypatch, "notes.txt", b"hello",
                          owner="alice")
    assert seen["owner"] == "alice"
    assert result.get("doc_id"), result


# ── Where the bytes came from ───────────────────────────────────────────────

def test_an_extracted_path_outside_the_extraction_root_is_refused(tmp_path, monkeypatch):
    """The attachment filename comes out of a MIME header the sender wrote.
    An extractor that resolved it to `../../etc/passwd` must not be read."""
    escape = tmp_path / "outside.txt"
    escape.write_text("secret")
    result, _ = _drive(tmp_path, monkeypatch, "notes.txt", b"hello", extracted=escape)
    assert result == {"error": "Invalid attachment path"}
    assert "doc_id" not in result


def test_a_path_inside_the_root_is_not_refused(tmp_path, monkeypatch):
    """The other side of the containment check: a legitimate nested path is
    still accepted, so the guard is a containment test and not a ban on
    subdirectories."""
    target = tmp_path / "extract" / "part1"
    target.mkdir(parents=True)
    nested = target / "notes.txt"
    nested.write_text("hello")
    result, _ = _drive(tmp_path, monkeypatch, None, b"", extracted=nested)
    assert result.get("doc_id"), result


def test_a_dotfile_attachment_is_refused_by_name(tmp_path, monkeypatch):
    result, _ = _drive(tmp_path, monkeypatch, ".bashrc", b"export PATH=/tmp\n")
    assert result == {"error": "Invalid filename", "filename": ".bashrc"}


# ── What a refusal says ─────────────────────────────────────────────────────

def test_a_missing_attachment_index_names_the_index(tmp_path, monkeypatch):
    result, _ = _drive(tmp_path, monkeypatch, None, b"", extracted=False)
    assert result == {"error": "Attachment index 0 not found"}


def test_a_failed_fetch_is_email_not_found(tmp_path, monkeypatch):
    result, _ = _drive(tmp_path, monkeypatch, "notes.txt", b"hello",
                       fetch_status="NO")
    assert result == {"error": "Email not found"}


def test_an_unexpected_failure_does_not_put_its_text_on_the_wire(tmp_path, monkeypatch):
    """The outer handler logs the real error and answers with a fixed string.
    A mailbox error carrying a server path or a credential fragment must not
    be echoed to the browser."""
    def boom(folder, uid):
        raise RuntimeError("imap://user:hunter2@mail.internal refused")

    result, _ = _drive(tmp_path, monkeypatch, "notes.txt", b"hello", extract_dir=boom)
    assert result == {"error": "Mail operation failed"}
    assert "hunter2" not in repr(result)


def test_a_binary_attachment_is_refused_with_the_shape_the_ui_falls_back_on(
        tmp_path, monkeypatch):
    """`emailLibrary.js` offers Open on every attachment now and falls back to
    the download route on any `{error}` answer. That contract is this key:
    an `{error}` with no `doc_id`, naming the extension."""
    png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + bytes(64)
    result, _ = _drive(tmp_path, monkeypatch, "photo.png", png)
    assert result.get("error") == "Unsupported attachment type: .png"
    assert "doc_id" not in result


# ── `B02`'s Verify clause, at the backend end ───────────────────────────────

def test_a_log_attachment_opens_as_a_document(tmp_path, monkeypatch):
    """`B02`: *"a `.log` attachment opens in the editor."* The button half is
    `tests/test_email_attachment_open_reaches_the_decode_fallback.py`; this is
    the half that has to answer when the button is pressed."""
    body = b"2026-08-26 06:00:01 INFO started\n2026-08-26 06:00:02 WARN slow\n"
    result, _ = _drive(tmp_path, monkeypatch, "server.log", body)
    assert result.get("doc_id"), result
    assert result.get("filename") == "server.log"


def test_an_extensionless_attachment_opens_too(tmp_path, monkeypatch):
    """The case no extension list can ever contain, which is why the gate had
    to come off the button rather than grow."""
    result, _ = _drive(tmp_path, monkeypatch, "LICENSE",
                       b"GNU AFFERO GENERAL PUBLIC LICENSE\nVersion 3\n")
    assert result.get("doc_id"), result
    assert result.get("filename") == "LICENSE"


def test_the_decoded_document_carries_the_attachment_text(tmp_path, monkeypatch):
    """A doc_id is not evidence the bytes arrived. Read the Document back."""
    from src.database import Document, SessionLocal

    body = b"col_a,col_b\nSENTINELrowsCSV,2\n"
    result, _ = _drive(tmp_path, monkeypatch, "rows.csv", body)
    db = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == result["doc_id"]).first()
        assert doc is not None
        assert "SENTINELrowsCSV" in doc.current_content
        assert doc.title == "rows"
    finally:
        db.close()
