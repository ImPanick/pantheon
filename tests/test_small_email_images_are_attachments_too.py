# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P2-12` — a real screenshot under 30 KB is an attachment, not a signature.

The reader's signature filter hid two kinds of image: the two filename shapes
mail clients stamp on signature and quoted-header images (`image001.png`,
`logo.png`, `signature_2.jpg` …), and **any** image under 30 KB. The second
clause is the defect. A 640×400 screenshot saved by PIL is 15.9 KB; a 320×240
JPEG is 17.3 KB. Both were demoted into the collapsed "Hidden inline
attachments" section, left out of the "Download all" ZIP, and did not count
toward the four-attachment threshold that shows the ZIP button at all.

`D-2026-08-26-06` settles the shape: drop the size clause in **both** files —
`routes/email_helpers.py` and `static/js/emailLibrary.js`, because fixing one
leaves the reader and the ZIP disagreeing — keep the two filename patterns,
and **pin the related-thread lookup to the old predicate**, which is out of
scope and stays out.

What the restriction protected, and why lifting it renders nothing new: it is
a clutter filter, not a security control. A demoted chip was still a chip —
still clickable, still downloadable one at a time. The change moves chips from
one section to another and lets the ZIP carry them. The ZIP is served
`application/zip` with `Content-Disposition: attachment`; a single chip goes
through `GET /api/email/attachment/…`, `application/octet-stream`, attachment.
The one route that serves sender bytes **inline**, `/api/email/inline-image`,
is untouched and keeps its `image/` check (`FORBIDDEN.md` Part 2) — the last
test here drives it to prove that.

Everything below calls the code (`Law 20`): the predicate over real image
bytes, the ZIP route and the read route through the real router with only IMAP
faked, and the reader's markup builder under node.
"""
import contextlib
import email
import email.utils
import io
import json
import shutil
import subprocess
import zipfile
from email.message import EmailMessage
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

import routes.email_helpers as email_helpers
import routes.email_routes as email_routes
from routes.email_helpers import (
    _has_visible_attachments,
    _is_likely_signature_image_attachment,
    _list_attachments_from_msg,
    require_owner,
)
from tests.helpers.esc_stub import esc_source
from tests.helpers.js_source import js_definition

ROOT = Path(__file__).resolve().parent.parent
EMAIL_LIBRARY = ROOT / "static" / "js" / "emailLibrary.js"
ICONS_SOURCE = ROOT / "tests" / "harness" / "icons_source.js"


# ── real images, measured rather than assumed ───────────────────────────────

def _screenshot_png(width=640, height=400, rows=14) -> bytes:
    """A UI-shaped screenshot: a title bar, rows of text, a highlighted box."""
    img = Image.new("RGB", (width, height), (246, 247, 249))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, width, 36], fill=(40, 44, 52))
    for i in range(rows):
        y = 52 + i * 24
        draw.rectangle([16, y, 16 + (i * 37 % 300) + 180, y + 10], fill=(90, 96, 110))
        draw.text((width - 150, y - 2), f"row {i}: value {i * 7}", fill=(30, 30, 30))
    draw.rectangle([width - 140, height - 50, width - 20, height - 20],
                   outline=(200, 60, 60), width=2)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _photo_jpeg(width=320, height=240) -> bytes:
    img = Image.new("RGB", (width, height))
    px = img.load()
    for x in range(width):
        for y in range(height):
            px[x, y] = ((x * 3 + y) % 256, (y * 2) % 256, (x * y) % 256)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=70)
    return buf.getvalue()


def _logo_png() -> bytes:
    img = Image.new("RGB", (120, 40), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.ellipse([4, 4, 36, 36], fill=(200, 30, 30))
    draw.text((44, 12), "ACME", fill=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


SCREENSHOT = _screenshot_png()
PHOTO = _photo_jpeg()
LOGO = _logo_png()
PDF = b"%PDF-1.4\n" + b"0" * (60 * 1024) + b"\n%%EOF\n"


def test_the_fixtures_are_the_case_the_row_is_about():
    """Guard the premise, so a PIL that encodes differently cannot turn every
    test below into a test of large images."""
    assert SCREENSHOT.startswith(b"\x89PNG") and 0 < len(SCREENSHOT) < 30 * 1024
    assert PHOTO.startswith(b"\xff\xd8\xff") and 0 < len(PHOTO) < 30 * 1024
    assert len(LOGO) < 30 * 1024


# ── the predicate ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("name, data", [
    pytest.param("screenshot.png", SCREENSHOT, id="screenshot.png"),
    pytest.param("Screen Shot 2026-09-27 at 10.14.03.png", SCREENSHOT, id="macos-name"),
    pytest.param("holiday.jpg", PHOTO, id="holiday.jpg"),
    pytest.param("diagram.webp", SCREENSHOT, id="diagram.webp"),
])
def test_a_real_small_image_is_not_a_signature_image(name, data):
    assert not _is_likely_signature_image_attachment(
        {"filename": name, "size": len(data), "content_type": "image/png"})


@pytest.mark.parametrize("name", [
    "image001.png", "IMAGE0042.JPG", "image123.gif",
    "logo.png", "signature_2.jpg", "sig.svg", "footer-1.gif", "banner.png",
])
def test_the_two_filename_patterns_still_hide_signature_images(name):
    """Kept, per the decision. The name is what a mail client stamps on the
    images it inlines, and that is evidence; the size never was."""
    for size in (len(LOGO), 90 * 1024):
        assert _is_likely_signature_image_attachment({"filename": name, "size": size})


def test_a_non_image_is_never_a_signature_image():
    assert not _is_likely_signature_image_attachment({"filename": "report.pdf", "size": 900})
    assert not _is_likely_signature_image_attachment({"filename": "logo.pdf", "size": 900})


# ── a real message, through the real routes ─────────────────────────────────

def _message(*, message_id, attachments, references=None):
    msg = EmailMessage()
    msg["From"] = "Sender <sender@example.com>"
    msg["To"] = "Alice <alice@example.com>"
    msg["Subject"] = "Here is the screenshot"
    msg["Message-ID"] = message_id
    msg["Date"] = email.utils.format_datetime(email.utils.localtime())
    if references:
        msg["References"] = references
        msg["In-Reply-To"] = references
    msg.set_content("See attached.")
    for name, data, maintype, subtype in attachments:
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    return msg.as_bytes()


CURRENT = _message(message_id="<current@example.com>", attachments=[
    ("screenshot.png", SCREENSHOT, "image", "png"),
    ("holiday.jpg", PHOTO, "image", "jpeg"),
    ("image001.png", LOGO, "image", "png"),
    ("logo.png", LOGO, "image", "png"),
    ("report.pdf", PDF, "application", "pdf"),
])


class _Conn:
    def select(self, *_a, **_k):
        return "OK", [b"1"]


def _install_imap(monkeypatch, tmp_path, messages: dict):
    """Only IMAP and the caches are faked; parsing, extraction and the ZIP
    builder are the shipped code over the message bytes above."""
    db_path = tmp_path / "email.db"
    monkeypatch.setattr(email_helpers, "SCHEDULED_DB", db_path)
    monkeypatch.setattr(email_routes, "SCHEDULED_DB", db_path)
    email_helpers._init_scheduled_db()

    @contextlib.contextmanager
    def fake_imap(account_id=None, owner=""):
        yield _Conn()

    def fake_fetch(_conn, uid, _query):
        uid = uid.decode() if isinstance(uid, bytes) else str(uid)
        if uid not in messages:
            return "NO", []
        return "OK", [(f"1 (UID {uid} BODY[])".encode(), messages[uid])]

    def fake_search(_conn, criteria):
        for uid, raw in messages.items():
            mid = email.message_from_bytes(raw).get("Message-ID", "")
            if mid and mid in criteria:
                return "OK", [uid.encode()]
        return "OK", [b""]

    monkeypatch.setattr(email_routes, "_start_poller", lambda: None)
    monkeypatch.setattr(email_routes, "_imap", fake_imap)
    monkeypatch.setattr(email_routes, "_imap_uid_fetch", fake_fetch)
    monkeypatch.setattr(email_routes, "_imap_uid_search", fake_search)
    monkeypatch.setattr(email_routes, "attachment_extract_dir",
                        lambda folder, uid: tmp_path / "extract" / str(uid))
    for name in ("_email_preview_cache_get", "_email_attachment_meta_cache_get"):
        monkeypatch.setattr(email_routes, name, lambda *_a, **_k: None)
    for name in ("_email_preview_cache_put", "_email_attachment_meta_cache_put",
                 "_email_index_update_flags"):
        monkeypatch.setattr(email_routes, name, lambda *_a, **_k: None)

    app = FastAPI()
    app.include_router(email_routes.setup_email_routes())
    app.dependency_overrides[require_owner] = lambda: "alice"
    return TestClient(app)


def test_download_all_carries_the_small_screenshot_and_photo(tmp_path, monkeypatch):
    """What `P2-CORRECTED` says was genuinely lost: the ZIP. The two real
    images under 30 KB are in it now; the two signature-named ones are not."""
    client = _install_imap(monkeypatch, tmp_path, {"42": CURRENT})
    res = client.get("/api/email/attachments-download/42")
    assert res.status_code == 200, res.text
    assert res.headers["content-type"] == "application/zip"
    assert res.headers["content-disposition"].startswith("attachment;")
    names = sorted(zipfile.ZipFile(io.BytesIO(res.content)).namelist())
    assert names == ["holiday.jpg", "report.pdf", "screenshot.png"]
    with zipfile.ZipFile(io.BytesIO(res.content)) as zf:
        assert zf.read("screenshot.png") == SCREENSHOT, "the ZIP carries the bytes, not a stub"


def test_a_single_small_image_downloads_as_an_attachment(tmp_path, monkeypatch):
    """Nothing about the single-file route moves: octet-stream, attachment."""
    client = _install_imap(monkeypatch, tmp_path, {"42": CURRENT})
    index = next(a["index"] for a in _list_attachments_from_msg(email.message_from_bytes(CURRENT))
                 if a["filename"] == "screenshot.png")
    res = client.get(f"/api/email/attachment/42/{index}")
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/octet-stream"
    assert res.headers["content-disposition"].startswith("attachment;")
    assert res.content == SCREENSHOT


# ── the related-thread lookup is pinned, not changed (`D-2026-08-26-06`) ─────

REFERENCED = _message(message_id="<earlier@example.com>", attachments=[
    ("earlier-screenshot.png", SCREENSHOT, "image", "png"),
    ("contract.pdf", PDF, "application", "pdf"),
])
REPLY_WITH_ONLY_A_SCREENSHOT = _message(
    message_id="<reply@example.com>", references="<earlier@example.com>",
    attachments=[("screenshot.png", SCREENSHOT, "image", "png")])


def test_the_lookup_still_asks_the_old_question():
    """`_has_visible_attachments` decides whether the reader goes looking
    through the thread. It keeps the pre-`P2-12` answer: a message whose only
    attachment is a small image still counts as having none."""
    msg = email.message_from_bytes(REPLY_WITH_ONLY_A_SCREENSHOT)
    assert not _has_visible_attachments(msg)
    assert _has_visible_attachments(email.message_from_bytes(CURRENT))


def test_the_related_thread_lookup_returns_what_it_always_did(tmp_path, monkeypatch):
    """Driven through `GET /api/email/read/{uid}?full=1`: the lookup still runs
    for a reply carrying only a screenshot, and it still returns the earlier
    message's PDF and not its small image — both unchanged."""
    client = _install_imap(monkeypatch, tmp_path,
                           {"43": REPLY_WITH_ONLY_A_SCREENSHOT, "7": REFERENCED})
    res = client.get("/api/email/read/43", params={"full": "1", "mark_seen": "0"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert [a["filename"] for a in body["attachments"]] == ["screenshot.png"]
    assert [a["filename"] for a in body["related_attachments"]] == ["contract.pdf"]
    assert body["related_attachments"][0]["source_uid"] == "7"


# ── the one inline route is untouched (`FORBIDDEN.md` Part 2) ────────────────

def test_the_inline_image_route_still_refuses_a_non_image(tmp_path, monkeypatch):
    """The `image/` check on the only route that serves sender bytes inline.
    `P2-12` does not reach it; this proves it did not move."""
    hostile = EmailMessage()
    hostile["Message-ID"] = "<hostile@example.com>"
    hostile.set_content("x")
    hostile.add_attachment(b"<script>alert(1)</script>", maintype="text",
                           subtype="html", filename="page.html", cid="<evil@x>")
    hostile.add_attachment(SCREENSHOT, maintype="image", subtype="png",
                           filename="shot.png", cid="<shot@x>")
    client = _install_imap(monkeypatch, tmp_path, {"44": hostile.as_bytes()})
    refused = client.get("/api/email/inline-image/44", params={"cid": "evil@x"})
    assert refused.status_code == 415
    served = client.get("/api/email/inline-image/44", params={"cid": "shot@x"})
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/png"
    assert served.content == SCREENSHOT


# ── the reader, under node ──────────────────────────────────────────────────

pytestmark_node = pytest.mark.skipif(not shutil.which("node"), reason="node not on PATH")


def _reader_markup(attachments, related=()):
    """Run the shipped `_isLikelySignatureImage` + `_buildAttsHtmlFor`."""
    source = EMAIL_LIBRARY.read_text(encoding="utf-8")
    defs = "\n".join(
        js_definition(source, source.index(f"function {name}("))
        for name in ("_isLikelySignatureImage", "_buildAttsHtmlFor"))
    script = (
        "const { iconsSource } = require(%s);\n"
        "const make = new Function('_esc', 'state', iconsSource() + '\\n' + %s + "
        "'\\nreturn { _buildAttsHtmlFor, _isLikelySignatureImage };');\n"
        "const api = make(_esc, { _libFolder: 'INBOX' });\n"
        "const data = %s;\n"
        "const html = api._buildAttsHtmlFor('42', data);\n"
        "const cut = html.indexOf('email-reader-atts-hidden-note\">Filtered');\n"
        "const visiblePart = cut < 0 ? html : html.slice(0, cut);\n"
        "const hiddenPart = cut < 0 ? '' : html.slice(cut);\n"
        "const names = (part) => [...part.matchAll(/data-att-name=\"([^\"]*)\"/g)]"
        ".map(m => m[1]);\n"
        "const label = (html.match(/<span>((?:Attachments|Thread attachments|Hidden inline"
        " attachments) \\(\\d+\\))<\\/span>/) || [])[1] || null;\n"
        "const zip = html.match(/email-attachments-download-all\"[^>]*data-att-count=\"(\\d+)\"/);\n"
        "console.log(JSON.stringify({ visible: names(visiblePart), hidden: names(hiddenPart),"
        " label, zipCount: zip ? Number(zip[1]) : null,"
        " collapsed: html.includes('email-reader-atts-wrap collapsed') }));\n"
    ) % (json.dumps(str(ICONS_SOURCE)), json.dumps(defs), json.dumps({
        "folder": "INBOX",
        "attachments": [dict(a, index=i) for i, a in enumerate(attachments)],
        "related_attachments": list(related),
    }))
    # `B874`: the shipped escaper, not a hand-written one (`test_one_esc_stub_js`).
    script = esc_source("_esc") + script
    proc = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _att(name, data):
    return {"filename": name, "size": len(data)}


@pytestmark_node
def test_the_reader_shows_a_small_screenshot_as_an_attachment():
    out = _reader_markup([_att("screenshot.png", SCREENSHOT), _att("image001.png", LOGO)])
    assert out["visible"] == ["screenshot.png"]
    assert out["hidden"] == ["image001.png"]
    assert out["label"] == "Attachments (1)"
    assert out["collapsed"] is False


@pytestmark_node
def test_small_images_count_toward_the_download_all_button():
    """The ZIP button appears above four visible attachments and its count is
    what the server's ZIP will contain — both sides now agree on five."""
    out = _reader_markup([
        _att("screenshot.png", SCREENSHOT), _att("holiday.jpg", PHOTO),
        _att("diagram.png", SCREENSHOT), _att("report.pdf", PDF),
        _att("notes.txt", b"x" * 900),
        _att("image001.png", LOGO), _att("logo.png", LOGO),
    ])
    assert out["visible"] == ["screenshot.png", "holiday.jpg", "diagram.png",
                              "report.pdf", "notes.txt"]
    assert out["hidden"] == ["image001.png", "logo.png"]
    assert out["zipCount"] == 5
    assert out["label"] == "Attachments (5)"


@pytestmark_node
def test_a_message_of_only_signature_images_still_starts_collapsed():
    """`Law 1`: the clutter case the filter exists for keeps its behaviour."""
    out = _reader_markup([_att("image001.png", LOGO), _att("logo.png", LOGO)])
    assert out["visible"] == []
    assert out["hidden"] == ["image001.png", "logo.png"]
    assert out["label"] == "Hidden inline attachments (2)"
    assert out["collapsed"] is True
