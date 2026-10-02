# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B-NEW` (f-import) — the chat's `HEAD` for an upload's kind is answered.

`static/js/chat.js` `_uploadKind` asks ``HEAD /api/upload/{id}`` for
``X-Upload-Kind`` before it opens a chat attachment as a document, and its
comment says the route "registers GET and Starlette adds HEAD to it". FastAPI's
``APIRoute`` does not. Measured on the tree before this row through the real
upload router: ``HEAD`` → **405**, ``Allow: GET``, for a `.toml` whose ``GET``
said ``X-Upload-Kind: text``. So the verdict `B232` published never arrived;
every *open as document* fell back to ``ingestKindFromName``, which knows
nothing about `.toml`, and the chip opened a raw download.

Every case drives the code (`Law 20`): the real upload and document routers
(the `P21-03` harness — real ``UploadHandler``, real SQLite file), served on a
loopback socket where the client is a browser's ``fetch`` or a raw socket, and
the chat's own ``_uploadKind`` and ``openAttachment`` cut out of ``chat.js`` and
run under node.
"""
import json
import shutil
import socket
from pathlib import Path

import pytest

import core.database as cdb
from tests.helpers.js_source import js_definition
from tests.test_a_file_imported_from_device_opens_readable import _run_js, live  # noqa: F401
from tests.test_an_uploaded_document_keeps_its_name import OWNER, _upload, env  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"
CHAT = (JS / "chat.js").read_text(encoding="utf-8")

TOML = b'[server]\nport = 8080\nname = "TOMLSENTINEL"\n'


def _cut(source: str, signature: str) -> str:
    return js_definition(source, source.index(signature))


# ── the route ───────────────────────────────────────────────────────────────


def test_head_answers_what_get_answers_without_the_body(env):  # noqa: F811
    up = _upload(env, "settings.toml", TOML)
    url = f"/api/upload/{up['id']}"
    got = env.client.get(url)
    head = env.client.head(url)
    assert got.status_code == 200 and got.content == TOML
    assert head.status_code == 200, head.text
    assert head.headers["x-upload-kind"] == got.headers["x-upload-kind"] == "text"
    # `FORBIDDEN.md` Part 2: an attachment, never sniffed — the same headers.
    for name in ("content-disposition", "x-content-type-options", "content-type",
                 "content-length"):
        assert head.headers[name] == got.headers[name], name
    assert head.headers["content-disposition"].startswith("attachment")
    assert head.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize("name,body,kind", [
    ("settings.toml", TOML, "text"),
    ("Q3 notes.docx", b"PK\x03\x04 not really", "document"),
    ("photo.bin", b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x01\xff\xfe", "binary"),
])
def test_head_carries_the_servers_verdict_for_each_kind(env, name, body, kind):  # noqa: F811
    up = _upload(env, name, body)
    head = env.client.head(f"/api/upload/{up['id']}")
    assert head.status_code == 200, head.text
    assert head.headers["x-upload-kind"] == kind


def test_head_keeps_the_owner_check(env, monkeypatch):  # noqa: F811
    import routes.upload_routes as upload_routes

    up = _upload(env, "settings.toml", TOML)
    url = f"/api/upload/{up['id']}"

    class _Auth:
        is_configured = True

        def is_admin(self, user):
            return False

    env.client.app.state.auth_manager = _Auth()
    for who, status in (("mallory", 404), (None, 403), (OWNER, 200)):
        monkeypatch.setattr(upload_routes, "effective_user", lambda request, _w=who: _w)
        got, head = env.client.get(url), env.client.head(url)
        assert (got.status_code, head.status_code) == (status, status), who
        if status != 200:
            assert "x-upload-kind" not in head.headers


def test_head_sends_no_body_on_the_wire(live):  # noqa: F811
    """`TestClient` drops a HEAD body whatever the server sent; a socket does not."""
    up = _upload(live, "settings.toml", TOML)
    host, port = live.base.removeprefix("http://").split(":")
    with socket.create_connection((host, int(port)), timeout=10) as s:
        s.sendall(f"HEAD /api/upload/{up['id']} HTTP/1.1\r\nHost: {host}\r\n"
                  "Connection: close\r\n\r\n".encode())
        raw = b""
        while chunk := s.recv(65536):
            raw += chunk
    head, _, rest = raw.partition(b"\r\n\r\n")
    assert head.startswith(b"HTTP/1.1 200"), head[:80]
    assert b"x-upload-kind: text" in head.lower()
    assert rest == b"", rest[:80]


# ── the chat: a `.toml` chip opens as a document ────────────────────────────

_CHAT = r"""
import { readFileSync } from 'fs';
import { ingestKindFromName, documentLanguage, isExtractedExtension,
         INGEST_KIND_DOCUMENT, INGEST_KIND_TEXT } from './attachmentLanguage.js';
globalThis.window = globalThis;
const API_BASE = __BASE__;
const opened = { raw: [], docs: [], panel: 0 };
window.open = (url) => opened.raw.push(url);
const sessionModule = { getCurrentSessionId: () => 'chat-1' };
const documentModule = {
  openPanel() { opened.panel++; },
  injectFreshDoc(doc) { opened.docs.push({ id: doc.id, language: doc.language }); },
};
async function loadPanel() { throw new Error('not an image'); }
const _attachDocCache = new Map();
__CUT__
"""


def _chat(live, body: str) -> dict:  # noqa: F811
    work = live.tmp / "node-chat"
    work.mkdir(parents=True, exist_ok=True)
    shutil.copy(JS / "attachmentLanguage.js", work / "attachmentLanguage.js")
    cut = "\n".join(_cut(CHAT, sig) for sig in (
        "async function _importFileAsDocument(",
        "async function _uploadKind(",
        "async function openAttachment(",
    ))
    source = (_CHAT.replace("__BASE__", json.dumps(live.base)).replace("__CUT__", cut)
              + body)
    return _run_js(work, source)


def test_the_chat_hears_the_servers_kind(live):  # noqa: F811
    up = _upload(live, "settings.toml", TOML)
    out = _chat(live, f"""
        const url = API_BASE + '/api/upload/' + {json.dumps(up['id'])};
        console.log(JSON.stringify({{
          kind: await _uploadKind(url, 'settings.toml', ''),
          byName: ingestKindFromName('settings.toml', ''),
        }}));
    """)
    # The name alone says nothing about `.toml`; the server read the bytes.
    assert out == {"kind": "text", "byName": None}


def test_a_toml_chip_opens_as_a_document_not_a_download(live):  # noqa: F811
    up = _upload(live, "settings.toml", TOML)
    out = _chat(live, f"""
        await openAttachment({{ id: {json.dumps(up['id'])}, name: 'settings.toml', mime: '' }}, false);
        console.log(JSON.stringify(opened));
    """)
    assert out["raw"] == [], "the chip opened a raw download"
    assert out["panel"] == 1 and len(out["docs"]) == 1
    db = live.Session()
    try:
        doc = db.query(cdb.Document).filter(cdb.Document.id == out["docs"][0]["id"]).one()
        assert "TOMLSENTINEL" in doc.current_content
        assert doc.source_name == "settings.toml" and doc.session_id == "chat-1"
    finally:
        db.close()
