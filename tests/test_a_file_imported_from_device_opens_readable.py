# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B400` — *Import from device* opens a file as a readable document, the way
the Library's Import does.

The Documents panel's *Import from device* was the third import path and it
converted nothing. Measured in Chromium on the tree before this row, with the
real files below:

  * it never opened a file picker while the panel showed anything but an email
    — `_eventInsideElement` counted the hidden Send button's 0x0 rect as
    containing (0, 0), where every `element.click()` lands, so the panel's
    capture-phase send handlers cancelled the click and ran `_sendEmail()`, and
    the page said "To and body are required";
  * behind the picker, a `.docx` and a `.pptx` were stored as their zip bytes
    (language `docx`/`pptx`), a photo as replacement characters, and a
    spreadsheet re-opened the Library so it could be picked a second time —
    while the Library's own Import gave the same `.docx` as markdown and the
    `.xlsx` as CSV.

The door now imports through the Library's one per-file function,
`importFileAsDocuments` (`static/js/documentLibrary.js`), and opens what it
made. Every door case below runs the whole door as it ships — the panel's
`_importFromDevice` picker, its `fi.click()` passing through the panel's real
capture-phase click handlers with the Send button hidden (a non-email document
open), `_importDeviceFile`, and the Library's reader and per-file import, all
cut out of the two modules with `js_source` and run under node with the
vendored mammoth and SheetJS — against the **real routers served on a loopback
socket** (the `P21-03` harness: real `UploadHandler`, real SQLite file), with
real LibreOffice-made files from `tests/helpers/office_fixtures.py`. What a test
asserts is what the server stored and what the panel was told to open
(`Law 20`), never a line of source.

Stand-ins, each at a boundary this row did not change: `htmlToMarkdown` returns
the HTML mammoth made (node has no `DOMParser`; the Chromium drive in the
handoff note runs the real one); `FileReader.readAsText` is the file's bytes
decoded as UTF-8, which is what the browser's does; the page's `document` is
the few members the door touches, and `element.click()` is what a browser does
with it — one click event at (0, 0) through the capture listeners, and the file
picker only if none of them cancelled it.
"""
import json
import os
import re
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest

import core.database as cdb
from tests.helpers.js_source import js_binding, js_function
from tests.helpers.office_fixtures import OFFICE_SENTINEL, office_fixture
from tests.test_an_uploaded_document_keeps_its_name import env  # noqa: F401
from tests.test_attachment_extension_registers import _minimal_pdf

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"
DOCLIB = (JS / "documentLibrary.js").read_text(encoding="utf-8")
DOCJS = (JS / "document.js").read_text(encoding="utf-8")


def _whole(source: str, signature: str) -> str:
    """One function declaration as it ships — signature, parameters, body."""
    at = source.index(signature)
    body = js_function(source, signature)
    return source[at:source.index(body, at) + len(body)]


def _have_markitdown() -> bool:
    from src.markitdown_runtime import load_markitdown
    try:
        load_markitdown()
        return True
    except RuntimeError:
        return False


HAVE_MARKITDOWN = _have_markitdown()

# What the browser runs, lifted whole: the Library's registers, its reader and
# its per-file import; the panel's door, its picker, and the panel's two
# capture-phase click handlers with the hit test they share.
_LIBRARY = "\n".join([
    js_binding(DOCLIB, "CLIENT_CONVERTED_EXTS"),
    js_binding(DOCLIB, "SERVER_EXTRACTED_EXTS"),
    js_binding(DOCLIB, "CONVERTED_TO"),
    _whole(DOCLIB, "async function readFileContent("),
    _whole(DOCLIB, "async function importFileAsDocuments("),
    _whole(DOCLIB, "async function libraryImportFiles("),
])
_DOOR = "\n".join([
    _whole(DOCJS, "async function _importDeviceFile("),
    _whole(DOCJS, "function _importFromDevice("),
])
_CAPTURE = "\n".join(js_binding(DOCJS, n) for n in (
    "_eventInsideElement", "handleSendIntent", "lastCaretToggleAt", "toggleSendMenu",
    "handleCaretIntent"))

# The page around them.
_PAGE = r"""
const Node = { TEXT_NODE: 3 };
const rect = (l, t, w, h) => ({ left: l, top: t, right: l + w, bottom: t + h, width: w, height: h });
// The panel is open on a document that is not an email: the email footer's
// Send button and its caret are in the DOM and hidden — 0x0 at (0, 0), as
// Chromium measures a `display: none` subtree.
const sendBtn = { disabled: false, r: rect(0, 0, 0, 0), getBoundingClientRect() { return this.r; } };
const caret = { r: rect(0, 0, 0, 0), getBoundingClientRect() { return this.r; }, setAttribute() {} };
const moreMenu = { style: { display: 'none' } };
const sentEmail = [];
async function _sendEmail() { sentEmail.push('send'); }
const capture = [];        // the page's capture-phase click listeners
const pickers = [];        // file pickers the browser opened
const document = {
  body: { appendChild(n) { n.isConnected = true; } },
  querySelectorAll: (sel) => sel === '#doc-email-send-btn' ? [sendBtn]
    : sel === '#doc-email-send-caret' ? [caret] : [],
  getElementById: (id) => id === 'doc-email-more-menu' ? moreMenu : null,
  createElement(tag) {
    return { tag, nodeType: 1, style: {}, listeners: {}, value: '', files: [],
      closest() { return null; },
      addEventListener(t, fn) { this.listeners[t] = fn; },
      remove() { this.isConnected = false; },
      // `HTMLElement.click()`: one click event at (0, 0) through the capture
      // listeners; an <input type=file> opens its picker unless one cancelled it.
      click() {
        const e = { type: 'click', target: this, clientX: 0, clientY: 0, defaultPrevented: false,
                    preventDefault() { this.defaultPrevented = true; }, stopPropagation() {} };
        for (const listener of capture) listener(e);
        if (!e.defaultPrevented && this.type === 'file') pickers.push(this);
      } };
  },
};
globalThis.requestAnimationFrame = (fn) => setTimeout(fn, 0);
"""

_PRELUDE = r"""
import { createRequire } from 'module';
import { readFileSync } from 'fs';
import { OFFICE_EXTS, documentLanguage, ingestKindFromName } from './attachmentLanguage.js';
const require = createRequire(import.meta.url);
globalThis.window = globalThis;
const API_BASE = __BASE__;
// The page loads its two vendored converters as window globals on first use.
async function ensureXLSX() { if (!window.XLSX) window.XLSX = require(__LIB__ + '/xlsx.full.min.js'); }
async function ensureMammoth() { if (!window.mammoth) window.mammoth = require(__LIB__ + '/mammoth.browser.min.js'); }
const htmlToMarkdown = (html) => html;
class FileReader {
  readAsText(f) {
    f.text().then((t) => { this.result = t; this.onload && this.onload(); },
                  (e) => { this.error = e; this.onerror && this.onerror(); });
  }
}
const shown = { errors: [], toasts: [], tabs: [], switched: [], libraryOpened: 0 };
const uiModule = { showError: (m) => shown.errors.push(m), showToast: (m) => shown.toasts.push(m) };
const sessionModule = { getCurrentSessionId: () => 'chat-1' };
let _lastSessionId = '';
function addDocToTabs(doc, sessionId) { shown.tabs.push({ id: doc.id, title: doc.title, sessionId }); }
function switchToDoc(id) { shown.switched.push(id); }
function openLibrary() { shown.libraryOpened++; }
let libraryRefreshed = 0;
async function libraryFetch() { libraryRefreshed++; }
const fileOf = (path, name, type) => new File([readFileSync(path)], name, { type });
""" + _PAGE + r"""
__CAPTURE__
capture.push(handleSendIntent, handleCaretIntent);
/** A person chooses *Import from device* and, if a picker opens, this file. */
async function pick(file) {
  _importFromDevice();
  const fi = pickers.shift();
  if (!fi) return { pickerOpened: false, sentEmail: sentEmail.length, ...shown };
  fi.files = [file];
  await fi.listeners.change();
  return { pickerOpened: true, inputLeft: !fi.isConnected, sentEmail: sentEmail.length, ...shown };
}
"""


def _run_js(work: Path, source: str) -> dict:
    """Run one ES module under node; its last line of stdout, as JSON."""
    work.mkdir(parents=True, exist_ok=True)
    (work / "case.mjs").write_text(source, encoding="utf-8")
    environ = dict(os.environ, NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost")
    proc = subprocess.run(["node", str(work / "case.mjs")], cwd=work, capture_output=True,
                          text=True, timeout=90, env=environ)
    assert proc.returncode == 0, proc.stderr
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert lines, f"node produced no stdout: {proc.stderr}"
    return json.loads(lines[-1])


def _node(tmp_path, base: str, body: str) -> dict:
    """Run *body* in the page, against the server at *base*."""
    work = tmp_path / "node"
    work.mkdir(parents=True, exist_ok=True)
    shutil.copy(JS / "attachmentLanguage.js", work / "attachmentLanguage.js")
    prelude = (_PRELUDE.replace("__BASE__", json.dumps(base))
               .replace("__LIB__", json.dumps(str(ROOT / "static" / "lib")))
               .replace("__CAPTURE__", _CAPTURE))
    return _run_js(work, prelude + _LIBRARY + "\n" + _DOOR + "\n" + body)


@pytest.fixture
def live(env, tmp_path):  # noqa: F811
    """The `P21-03` routers on a real loopback socket, so the browser's own
    `fetch`, `FormData` and `File` reach them the way a page does."""
    import uvicorn

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(env.client.app, host="127.0.0.1", port=port,
                                           log_level="warning", lifespan="off"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 20
    while not server.started:
        assert thread.is_alive() and time.monotonic() < deadline, "the test server did not start"
        time.sleep(0.02)
    env.base = f"http://127.0.0.1:{port}"
    env.tmp = tmp_path
    try:
        yield env
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def _file(env, name: str, body: bytes) -> str:  # noqa: F811
    path = env.tmp / "picked" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return str(path)


def _device(env, name, body, mime="") -> dict:  # noqa: F811
    """*Import from device*, one file: what the person saw."""
    path = _file(env, name, body)
    return _node(env.tmp, env.base, f"""
        console.log(JSON.stringify(await pick(fileOf({json.dumps(path)}, {json.dumps(name)}, {json.dumps(mime)}))));
    """)


def _docs(env):  # noqa: F811
    db = env.Session()
    try:
        return [{"id": d.id, "title": d.title, "source_name": d.source_name, "language": d.language,
                 "content": d.current_content or "", "session_id": d.session_id, "folder": d.folder,
                 "owner": d.owner}
                for d in db.query(cdb.Document).order_by(cdb.Document.created_at).all()]
    finally:
        db.close()


def _readable(content: str, *expected: str) -> None:
    assert "PK\x03\x04" not in content and "�" not in content and "\x00" not in content, \
        f"stored as raw bytes: {content[:80]!r}"
    for text in expected:
        assert text in content, f"{text!r} not in {content[:200]!r}"


def _opened(shown, *ids) -> None:
    """The panel showed exactly these, the first in front, in the open chat."""
    assert shown["pickerOpened"], f"no file picker opened; the page said {shown['errors']}"
    assert [t["id"] for t in shown["tabs"]] == list(ids)
    assert all(t["sessionId"] == "chat-1" for t in shown["tabs"])
    assert shown["switched"] == list(ids[:1])
    assert shown["sentEmail"] == 0 and shown["inputLeft"]


DOCX = "Q3 Board Pack – final (v2)"


# ── the door: each file opens as a readable document named as the file was ──

# (file name, bytes, browser type, language stored, text that must be in it)
READABLE = [
    (DOCX + ".docx", office_fixture(".docx"), "", "markdown", ("Quarterly Report", OFFICE_SENTINEL)),
    ("Minutes 1997.doc", office_fixture(".doc"), "", "markdown", (OFFICE_SENTINEL,)),
    ("Minutes.odt", office_fixture(".odt"), "", "markdown", (OFFICE_SENTINEL,)),
    ("Signed lease – 2026.pdf", _minimal_pdf("PDFSENTINEL lease"), "application/pdf", "markdown",
     ("PDFSENTINEL",)),
    ("Meeting notes.md", b"# Meeting notes\n\nWe agreed MDSENTINEL.\n", "text/markdown",
     "markdown", ("MDSENTINEL",)),
    ("Shopping list.txt", b"Eggs, milk TXTSENTINEL.\n", "text/plain", None, ("TXTSENTINEL",)),
    ("Landing page.html", b"<!doctype html><html><body><p>HTMLSENTINEL</p></body></html>",
     "text/html", "html", ("HTMLSENTINEL",)),
    # Typed `video/mp2t` by most systems' MIME tables; the name says text.
    ("Main.ts", b"export const TSSENTINEL = 1;\n", "video/mp2t", "typescript", ("TSSENTINEL",)),
    # `image/svg+xml` is XML text, and imported as it always was.
    ("Diagram.svg", b'<svg xmlns="http://www.w3.org/2000/svg"><title>SVGSENTINEL</title></svg>',
     "image/svg+xml", "svg", ("SVGSENTINEL",)),
]


@pytest.mark.parametrize("name,body,mime,language,expected", READABLE,
                         ids=[r[0].rsplit(".", 1)[1] for r in READABLE])
def test_a_file_from_device_opens_as_a_readable_document_named_as_it_was(
        live, name, body, mime, language, expected):
    shown = _device(live, name, body, mime)
    assert shown["errors"] == [], shown
    (doc,) = _docs(live)
    _readable(doc["content"], *expected)
    assert doc["title"] == name.rsplit(".", 1)[0]
    assert doc["source_name"] == name
    if language is not None:
        assert doc["language"] == language
    # Opened here, in front, attached to the chat that is open (as before),
    # owned, and Unfiled: nothing chose a folder at this door.
    _opened(shown, doc["id"])
    assert doc["session_id"] == "chat-1" and doc["owner"] == "alice" and doc["folder"] is None


@pytest.mark.parametrize("name,ext", [("Regional sales (FY26).xlsx", ".xlsx"),
                                      ("Regional sales 1997.xls", ".xls")],
                         ids=["xlsx", "xls"])
def test_a_spreadsheet_from_device_opens_here_and_is_not_picked_twice(live, name, ext):
    """Before: the panel opened the Library and clicked its Import button, so the
    person was asked for the file a second time. Now SheetJS reads it here."""
    shown = _device(live, name, office_fixture(ext))
    assert shown["errors"] == [] and shown["libraryOpened"] == 0, shown
    docs = _docs(live)
    assert docs and all(d["language"] == "csv" for d in docs)
    _readable(docs[0]["content"], OFFICE_SENTINEL)
    assert docs[0]["source_name"] == name
    assert docs[0]["title"].startswith(name.rsplit(".", 1)[0])
    _opened(shown, *[d["id"] for d in docs])
    assert all(d["session_id"] == "chat-1" for d in docs)


@pytest.mark.parametrize("name", ["Launch deck.pptx", "Field guide.epub"])
def test_a_format_only_markitdown_reads_opens_or_says_why_not(live, name):
    """`.pptx`/`.epub` are read by the server's markitdown, which is optional and
    not in the default image. Installed: the document opens. Not installed (CI,
    and the default `INSTALL_OPTIONAL=false` image): the person is told so in
    words, nothing opens, and nothing is stored as its bytes."""
    shown = _device(live, name, office_fixture("." + name.rsplit(".", 1)[1]))
    docs = _docs(live)
    if HAVE_MARKITDOWN:
        (doc,) = docs
        _readable(doc["content"], OFFICE_SENTINEL)
        _opened(shown, doc["id"])
    else:
        assert shown["pickerOpened"] and shown["sentEmail"] == 0, shown
        assert docs == [] and shown["tabs"] == []
        (said,) = shown["errors"]
        assert said.startswith(f"Couldn't import {name} — "), said
        assert "requires markitdown" in said and "requirements-optional.txt" in said, said


def test_a_photo_is_refused_in_words_and_reaches_nothing(live):
    """Before: a document of replacement characters, from a picker that did not
    open. Now: one sentence, and not a request sent."""
    png = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02"
           b"\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x03\x01"
           b"\x01\x00\xc9\xfe\x92\xef\x00\x00\x00\x00IEND\xaeB`\x82")
    shown = _device(live, "Team photo.png", png, "image/png")
    assert shown["pickerOpened"] and shown["sentEmail"] == 0, shown
    assert shown["errors"] == ["Couldn't import Team photo.png — it is an image, not a document"]
    assert shown["tabs"] == [] and shown["inputLeft"]
    assert _docs(live) == [] and live.handler._load_upload_index() == {}


def test_an_empty_workbook_is_said_not_counted(live):
    """The Library counted a workbook whose every sheet is empty as "Imported 1
    file" and made nothing. A workbook written by SheetJS itself: the question
    is what happens to no rows, not whether a reader agrees with a writer."""
    path = _file(live, "Empty.xlsx", b"")
    shown = _node(live.tmp, live.base, f"""
        await ensureXLSX();
        const wb = XLSX.utils.book_new();
        XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet([]), 'Blank');
        (await import('fs')).writeFileSync({json.dumps(path)}, XLSX.write(wb, {{ type: 'buffer', bookType: 'xlsx' }}));
        console.log(JSON.stringify(await pick(fileOf({json.dumps(path)}, 'Empty.xlsx', ''))));
    """)
    assert shown["pickerOpened"], shown
    assert shown["errors"] == ["Couldn't import Empty.xlsx — every sheet in it is empty"]
    assert shown["tabs"] == [] and _docs(live) == []


# ── one file, two doors, one document ───────────────────────────────────────

def _normalised(doc):
    keep = {k: doc[k] for k in ("title", "source_name", "language", "owner")}
    keep["content"] = re.sub(r'upload_id="[^"]+"', 'upload_id="…"', doc["content"])
    return keep


@pytest.mark.parametrize("name,body", [
    (DOCX + ".docx", office_fixture(".docx")),
    ("Minutes 1997.doc", office_fixture(".doc")),
    ("Regional sales (FY26).xlsx", office_fixture(".xlsx")),
    ("Signed lease – 2026.pdf", _minimal_pdf("PDFSENTINEL lease")),
    ("Meeting notes.md", b"# Meeting notes\n\nWe agreed MDSENTINEL.\n"),
], ids=["docx", "doc", "xlsx", "pdf", "md"])
def test_the_panel_and_the_library_make_the_same_document(live, name, body):
    """The row's `Verify`: a file imported from the Documents panel produces
    the same document as the same file given to the Library — and no third
    extension branch decides it, because both doors are one function. The
    Library's import is made from inside a folder, through the real routes
    (`B997`, whose branches moved with this row)."""
    path = _file(live, name, body)
    out = _node(live.tmp, live.base, f"""
        await libraryImportFiles([fileOf({json.dumps(path)}, {json.dumps(name)}, '')], 'Clients/Acme');
        console.log(JSON.stringify({{ libraryRefreshed,
          ...(await pick(fileOf({json.dumps(path)}, {json.dumps(name)}, ''))) }}));
    """)
    assert out["errors"] == [] and out["toasts"] == ["Imported 1 file"], out
    library, device = _docs(live)
    assert _normalised(device) == _normalised(library)
    _opened(out, device["id"])
    # Where the two doors always differed: the Library files into the folder
    # that is open and ties nothing to a chat; the panel's belongs to the open
    # chat and lands Unfiled.
    assert (library["folder"], library["session_id"]) == ("Clients/Acme", None)
    assert (device["folder"], device["session_id"]) == (None, "chat-1")


# ── the upload controls hold at this door (`FORBIDDEN.md` Part 2) ───────────

@pytest.mark.parametrize("name,body", [
    ("Signed lease – 2026.pdf", _minimal_pdf("PDFSENTINEL lease")),
    ("Minutes.odt", office_fixture(".odt")),
], ids=["pdf", "odt"])
def test_the_stored_file_is_served_as_an_attachment_and_never_sniffed(live, name, body):
    shown = _device(live, name, body)
    (doc,) = _docs(live)
    _opened(shown, doc["id"])
    (row,) = live.handler._load_upload_index().values()
    r = live.client.get(f"/api/upload/{row['id']}")
    assert r.status_code == 200
    assert r.headers["content-disposition"].startswith("attachment;"), r.headers["content-disposition"]
    assert r.headers["x-content-type-options"] == "nosniff"


def test_the_upload_byte_cap_holds_at_this_door_and_is_said(live):
    live.handler.max_upload_size = 64
    shown = _device(live, "Signed lease – 2026.pdf", _minimal_pdf("PDFSENTINEL lease"))
    assert shown["pickerOpened"], shown
    assert shown["errors"] == [
        "Couldn't import Signed lease – 2026.pdf — PDF import failed: File size exceeds 64 bytes limit"]
    assert shown["tabs"] == [] and _docs(live) == []


def test_cancelling_the_picker_imports_nothing_and_leaves_no_input(live):
    out = _node(live.tmp, live.base, """
        _importFromDevice();
        const fi = pickers.shift();
        fi.files = [];
        await fi.listeners.change();
        console.log(JSON.stringify({ picked: !!fi, left: !fi.isConnected, ...shown }));
    """)
    assert out["picked"] and out["left"]
    assert out["tabs"] == [] and out["errors"] == [] and _docs(live) == []


# ── the click that never reached the picker ─────────────────────────────────

def test_a_click_made_by_the_page_is_not_taken_for_the_hidden_send_button(tmp_path):
    """`element.click()` arrives at (0, 0) and a hidden button is 0x0 at (0, 0).
    Before: such a click was cancelled — no picker, for any file input in the
    page while the panel was open — and `_sendEmail()` ran. What the capture is
    for is kept: a click inside the visible Send button sends whatever element
    is on top, and the caret opens its menu."""
    out = _run_js(tmp_path / "capture", _PAGE + _CAPTURE + """
        const click = (x, y) => {
          const e = { type: 'click', target: { nodeType: 1, closest: () => null }, clientX: x, clientY: y,
                      defaultPrevented: false, preventDefault() { this.defaultPrevented = true; },
                      stopPropagation() {} };
          handleSendIntent(e);
          handleCaretIntent(e);
          return e.defaultPrevented;
        };
        const hidden = { prevented: click(0, 0), sent: sentEmail.length, menu: moreMenu.style.display };
        sendBtn.r = rect(900, 820, 80, 30);
        caret.r = rect(980, 820, 24, 30);
        const onSend = click(930, 835);
        const elsewhere = click(10, 10);
        // Last: the caret handler swallows any click for 350 ms after it
        // toggles (its own trailing click), which is not this row's.
        const onCaret = click(990, 835);
        console.log(JSON.stringify({ hidden, onSend, elsewhere, onCaret, sent: sentEmail.length,
                                     menu: moreMenu.style.display }));
    """)
    assert out["hidden"] == {"prevented": False, "sent": 0, "menu": "none"}
    assert out == {**out, "onSend": True, "elsewhere": False, "onCaret": True, "sent": 1, "menu": ""}
