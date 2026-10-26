# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B404` — what an upload is, decided once when it is saved.

`B232` made the verdict — `text`, `document` or `binary` — the server's, and
published it per request: `GET /api/upload/{id}` (and its `HEAD`) opened the
file and read 8 KiB to answer `X-Upload-Kind` every time, though its inputs,
the name and the bytes, were both in hand at `save_upload` and immutable
afterwards. Measured on `03f50081`: the `uploads.json` row had `mime`, `size`,
`width`, `height`, `checksum_sha256` and no `kind`; the chat's attachment
metadata had none either, so `chat.js` `openAttachment` spent a `HEAD` per
click to ask, and an attachment rendered from history could not be answered
without one.

Now `save_upload` records `kind` in the row; the upload response, the download
header and the message's attachment metadata read it; a row saved before this
has none and is probed on read, as every row was (no backfill of files on disk;
a duplicate upload's write-back fills it in).

Driven (`Law 20`): the real upload/download routes over a temp store (the
`env` harness of `test_an_uploaded_document_keeps_its_name.py`), the real
`ChatHandler.preprocess_message`, the real probe counted; and `chat.js`'
`openAttachment` cut out and run under node against a recording `fetch`.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import src.upload_handler as upload_handler_mod
from tests.helpers.js_source import js_definition
from tests.test_an_uploaded_document_keeps_its_name import OWNER, _upload, env  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
CHAT_JS = ROOT / "static" / "js" / "chat.js"
LANG_JS = ROOT / "static" / "js" / "attachmentLanguage.js"


@pytest.fixture
def probes(monkeypatch):
    """Every time the bytes are probed for a kind, by any door — the routes
    module included, which is where the probe lived before `B404` (so this
    measures the tree before the fix too, instead of erroring on it)."""
    import routes.upload_routes as upload_routes
    from src.document_processor import ingest_kind as real

    calls = []

    def counted(path, name=None):
        calls.append(name)
        return real(path, name)

    for mod in (upload_handler_mod, upload_routes):
        if hasattr(mod, "ingest_kind"):
            monkeypatch.setattr(mod, "ingest_kind", counted)
    return calls


def _row(env, file_id):  # noqa: F811
    index = env.handler._load_upload_index()
    return next(v for v in index.values() if v.get("id") == file_id)


def test_the_verdict_for_one_upload_is_computed_once(env, probes):  # noqa: F811
    """`Verify:` (first half). Saved, downloaded twice, asked by `HEAD`: one
    probe, at the save, and every door answers what it recorded."""
    up = _upload(env, "notes.txt", b"plain words\n", "text/plain")
    assert up["kind"] == "text"
    assert _row(env, up["id"])["kind"] == "text", "the row does not record the kind"
    for _ in range(2):
        r = env.client.get(f"/api/upload/{up['id']}")
        assert r.status_code == 200 and r.headers["X-Upload-Kind"] == "text"
    h = env.client.head(f"/api/upload/{up['id']}")
    assert h.headers["X-Upload-Kind"] == "text"
    assert probes == ["notes.txt"], probes


def test_each_kind_is_recorded_as_the_probe_answers_it(env, probes):  # noqa: F811
    for name, body, want in [("Main.kt", b"fun main() {}\n", "text"),
                             ("memo.doc", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64, "document"),
                             ("photo.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, "binary")]:
        up = _upload(env, name, body)
        assert up["kind"] == want and _row(env, up["id"])["kind"] == want, name


def test_a_row_saved_before_the_kind_was_recorded_is_answered_by_the_probe(env, probes):  # noqa: F811
    """Recompute on read, no backfill: the files already on disk keep working."""
    up = _upload(env, "notes.txt", b"plain words\n", "text/plain")
    index = env.handler._load_upload_index(fail_on_error=True)
    for v in index.values():
        v.pop("kind", None)
    env.handler._atomic_write_json(str(Path(env.handler.upload_dir) / "uploads.json"), index)
    probes.clear()
    r = env.client.get(f"/api/upload/{up['id']}")
    assert r.headers["X-Upload-Kind"] == "text"
    assert len(probes) == 1, probes
    # The same file uploaded again takes the duplicate path, whose write-back
    # records the kind on the old row.
    again = _upload(env, "notes.txt", b"plain words\n", "text/plain")
    assert again["id"] == up["id"] and again["kind"] == "text"
    assert _row(env, up["id"])["kind"] == "text"


def test_the_message_carries_the_kind_with_the_attachment(env, probes):  # noqa: F811
    """What a chip drawn from history reads: the attachment metadata saved with
    the message — and saving it probes nothing."""
    from src.chat_handler import ChatHandler

    up = _upload(env, "notes.txt", b"plain words\n", "text/plain")
    probes.clear()
    sess = SimpleNamespace(id="chat-1", owner=OWNER, model="m", endpoint_url="")
    handler = ChatHandler(None, None, None, None, None, env.handler)
    _m, _c, _t, _y, meta = asyncio.run(handler.preprocess_message("read this", [up["id"]], sess))
    assert meta[0]["id"] == up["id"] and meta[0]["kind"] == "text", meta
    assert probes == [], probes


# ── the chip ────────────────────────────────────────────────────────────────

def _open(tmp_path: Path, att: dict) -> list:
    """`openAttachment(att)` as `chat.js` ships it; returns what it asked."""
    src = CHAT_JS.read_text(encoding="utf-8")
    cut = "\n".join(js_definition(src, src.index(sig)) for sig in (
        "async function _uploadKind(", "async function openAttachment("))
    shutil.copy(LANG_JS, tmp_path / "attachmentLanguage.js")
    case = tmp_path / "case.mjs"
    case.write_text(
        "import { documentLanguage, ingestKindFromName, isExtractedExtension, INGEST_KIND_TEXT,"
        " INGEST_KIND_DOCUMENT, INGEST_KIND_BINARY } from './attachmentLanguage.js';\n"
        "const asked = [];\n"
        "globalThis.fetch = async (url, opts = {}) => {\n"
        "  asked.push(`${(opts.method || 'GET')} ${url}`);\n"
        "  const headers = { get: (k) => (k === 'X-Upload-Kind' ? 'text' : null) };\n"
        "  return { ok: true, status: 200, headers, text: async () => 'plain words',\n"
        "    json: async () => ({ id: 'doc-1' }), blob: async () => new Blob(['x']) };\n"
        "};\n"
        "globalThis.window = { open: (u) => asked.push('OPEN ' + u) };\n"
        "const API_BASE = '';\n"
        "const _attachDocCache = new Map();\n"
        "const sessionModule = { getCurrentSessionId: () => 'chat-1' };\n"
        "const documentModule = { openPanel() {}, injectFreshDoc() {}, loadDocument: async () => {} };\n"
        "const loadPanel = async () => ({});\n"
        "const _importFileAsDocument = async () => ({ id: 'doc-2' });\n"
        + cut + "\n"
        f"await openAttachment({json.dumps(att)}, false);\n"
        "console.log(JSON.stringify(asked));\n",
        encoding="utf-8")
    proc = subprocess.run(["node", str(case)], capture_output=True, text=True, timeout=60, cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")
def test_an_attachment_from_history_opens_as_a_document_without_a_second_request(tmp_path):
    """`Verify:` (second half). With the kind in the message's metadata the
    chip fetches the file and makes the document — no `HEAD` first."""
    asked = _open(tmp_path, {"id": "u1", "name": "notes.txt", "mime": "text/plain", "kind": "text"})
    assert not [a for a in asked if a.startswith("HEAD")], asked
    assert asked == ["GET /api/upload/u1", "POST /api/document"], asked


@pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")
def test_an_attachment_saved_before_the_kind_was_recorded_still_asks(tmp_path):
    asked = _open(tmp_path, {"id": "u1", "name": "notes.txt", "mime": "text/plain"})
    assert asked[0] == "HEAD /api/upload/u1", asked
