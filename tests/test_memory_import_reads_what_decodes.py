# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P2-05` — memory import reads any file whose bytes are text, not nine names.

`POST /api/memory/import` accepted `.txt .md .pdf .csv .log .json .py .js
.html` and answered everything else *"Unsupported file type"* — a `.yaml`, a
`.go`, a `.docx` never reached the reader. The row named sixteen to add and
five to leave out; `D-2026-08-26-06` decided the shape instead: *"drop the
allowlist entirely. Decode; reject only what fails. Keep the PDF extractor and
the `.json` fast path as branches. Size and rate become the real control."*

**The row's exclusion was a false premise, and a test below measures it.** It
left out `.scss .toml .ini .vue .svelte` because *"none of those is in
`is_document_file`'s `document_extensions`, so adding them here is unreachable
code."* This route never calls `is_document_file` — the browser posts the file
straight here — so on the old tree a `.toml` reached this handler and was
refused by name. With `is_document_file` made to explode, every one of the
five imports.

**What the list protected, and why nothing it blocked is ever executed or
rendered**: the bytes are decoded, put in a prompt, and the answer is a list of
`{text, category}` suggestions the browser draws with `textContent`. The file
is never stored and never served back; the temporary copy the extractors open
is gone before the response is, refusal or not — asserted here by watching the
temp directory.

`Law 20`: every test posts a real file through the real router.
"""
import io
import json
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

import routes.memory_routes as mr
import src.settings as S
from tests.helpers.js_source import js_definition
from tests.helpers.office_fixtures import OFFICE_SENTINEL, office_fixture

ROOT = Path(__file__).resolve().parent.parent
MEMORY_JS = ROOT / "static" / "js" / "memory.js"
INDEX_HTML = ROOT / "static" / "index.html"


# ── real files ──────────────────────────────────────────────────────────────

# The sixteen the row names, each an idiomatic file of its kind carrying a
# sentinel the test can find in the prompt the model is handed.
ROW_NAMED = {
    ".yaml": "owner: Priya\nhobby: beekeeping  # SENTINEL-yaml\n",
    ".yml": "services:\n  hive:\n    keeper: Priya  # SENTINEL-yml\n",
    ".ts": "const keeper: string = 'Priya'; // SENTINEL-ts\n",
    ".tsx": "export const Card = () => <p>Priya keeps bees</p>; // SENTINEL-tsx\n",
    ".jsx": "export const Hive = () => <div>Priya</div>; // SENTINEL-jsx\n",
    ".sh": "#!/bin/sh\n# SENTINEL-sh\necho \"Priya keeps bees\"\n",
    ".xml": "<?xml version=\"1.0\"?>\n<person name=\"Priya\"><!-- SENTINEL-xml --></person>\n",
    ".sql": "INSERT INTO keepers (name) VALUES ('Priya'); -- SENTINEL-sql\n",
    ".rs": "fn main() { println!(\"Priya keeps bees\"); } // SENTINEL-rs\n",
    ".go": "package main\n\n// SENTINEL-go\nfunc main() { println(\"Priya\") }\n",
    ".java": "class Keeper { String name = \"Priya\"; } // SENTINEL-java\n",
    ".c": "/* SENTINEL-c */\nint main(void) { return 0; }\n",
    ".cpp": "// SENTINEL-cpp\n#include <string>\nstd::string keeper = \"Priya\";\n",
    ".rb": "# SENTINEL-rb\nputs 'Priya keeps bees'\n",
    ".php": "<?php // SENTINEL-php\necho 'Priya keeps bees';\n",
}

# The five the row excluded as "unreachable".
ROW_EXCLUDED = {
    ".scss": "$keeper: 'Priya'; // SENTINEL-scss\n.hive { color: gold; }\n",
    ".toml": "[owner]\nname = \"Priya\"  # SENTINEL-toml\n",
    ".ini": "[owner]\nname = Priya ; SENTINEL-ini\n",
    ".vue": "<template><p>Priya</p></template>\n<!-- SENTINEL-vue -->\n",
    ".svelte": "<script>let keeper = 'Priya';</script>\n<!-- SENTINEL-svelte -->\n",
}

# The nine that always worked, less the PDF (its own case below).
ALWAYS_WORKED = {
    ".txt": "Priya keeps bees. SENTINEL-txt\n",
    ".md": "# Notes\n\nPriya keeps bees. SENTINEL-md\n",
    ".csv": "name,hobby\nPriya,beekeeping SENTINEL-csv\n",
    ".log": "2026-09-27 INFO keeper=Priya SENTINEL-log\n",
    ".json": json.dumps({"keeper": "Priya", "note": "SENTINEL-json"}),
    ".py": "keeper = 'Priya'  # SENTINEL-py\n",
    ".js": "const keeper = 'Priya'; // SENTINEL-js\n",
    ".html": "<p>Priya keeps bees. SENTINEL-html</p>\n",
}


def _text_pdf(line: str) -> bytes:
    """A real one-page PDF with one line of text, which pypdf reads back."""
    stream = f"BT /F1 18 Tf 72 720 Td ({line}) Tj ET".encode()
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % i + body + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1))
    for off in offsets:
        out.write(b"%010d 00000 n \n" % off)
    out.write(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
              % (len(objs) + 1, xref))
    return out.getvalue()


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (200, 30, 30)).save(buf, "PNG")
    return buf.getvalue()


def _zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("notes.txt", "Priya keeps bees " * 50)
    return buf.getvalue()


# ── the route, for real ─────────────────────────────────────────────────────

@pytest.fixture
def client(tmp_path, monkeypatch):
    """The real memory router. Only the model, the endpoint resolver and the
    caller's identity are faked; the reader, the size cap and the refusal are
    the shipped code."""
    calls = []

    async def fake_llm(url, model, messages, **kwargs):
        calls.append(messages[-1]["content"])
        return json.dumps([{"text": "Priya keeps bees", "category": "fact"}])

    settings_file = tmp_path / "settings.json"
    monkeypatch.setattr(S, "SETTINGS_FILE", str(settings_file))
    S._invalidate_caches()
    monkeypatch.delenv("PANTHEON_MEMORY_IMPORT_MAX_BYTES", raising=False)
    monkeypatch.setattr(mr, "get_current_user",
                        lambda request: request.headers.get("x-test-user", "alice"),
                        raising=False)
    monkeypatch.setattr("src.auth_helpers.require_privilege", lambda request, key: None)
    monkeypatch.setattr(mr, "resolve_task_endpoint", lambda *a, **k: ("http://llm", "m", {}))
    monkeypatch.setattr(mr, "llm_call_async", fake_llm)
    # Every temporary file the reader makes lands here, so "nothing is kept"
    # is a directory listing rather than a promise.
    scratch = tmp_path / "tmp"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))

    (tmp_path / "mem").mkdir()
    app = FastAPI()
    app.include_router(mr.setup_memory_routes(mr.MemoryManager(str(tmp_path / "mem")),
                                              MagicMock()))
    test_client = TestClient(app)
    test_client.calls = calls
    test_client.scratch = scratch
    yield test_client
    S._invalidate_caches()


def _post(client, name, data, user="alice"):
    if isinstance(data, str):
        data = data.encode("utf-8")
    return client.post("/api/memory/import", files={"file": (name, data)},
                       headers={"x-test-user": user})


@pytest.mark.parametrize("ext", sorted(ROW_NAMED))
def test_every_suffix_the_row_names_is_read(client, ext):
    res = _post(client, f"keeper{ext}", ROW_NAMED[ext])
    assert res.status_code == 200, res.text
    assert f"SENTINEL-{ext[1:]}" in client.calls[-1]
    assert res.json()["suggestions"] == [{"text": "Priya keeps bees", "category": "fact"}]


def test_a_word_document_is_read_through_the_office_reader(client):
    """`.docx` is a zip, so it is not text and not binary: it goes through
    `convert_to_markdown`, the reader chat ingest and the mailbox use. The
    fixture is a real LibreOffice file (`tests/helpers/office_fixtures.py`)."""
    res = _post(client, "report.docx", office_fixture(".docx"))
    assert res.status_code == 200, res.text
    assert OFFICE_SENTINEL in client.calls[-1]
    assert "Quarterly Report" in client.calls[-1]


@pytest.mark.parametrize("ext", sorted(ROW_EXCLUDED))
def test_the_five_the_row_excluded_are_reachable_and_read(client, monkeypatch, ext):
    """The row's premise, measured: this route never asks `is_document_file`.
    It is made to explode here, and all five import anyway."""
    import src.upload_handler as upload_handler

    def _explode(*_a, **_k):
        raise AssertionError("memory import consulted is_document_file")

    monkeypatch.setattr(upload_handler.UploadHandler, "is_document_file", _explode)
    res = _post(client, f"settings{ext}", ROW_EXCLUDED[ext])
    assert res.status_code == 200, res.text
    assert f"SENTINEL-{ext[1:]}" in client.calls[-1]


@pytest.mark.parametrize("ext", sorted(ALWAYS_WORKED))
def test_the_suffixes_that_always_worked_still_do(client, ext):
    """`Law 1`. All eight non-PDF suffixes are registered text, so none of
    them can be refused now."""
    res = _post(client, f"notes{ext}", ALWAYS_WORKED[ext])
    assert res.status_code == 200, res.text
    assert f"SENTINEL-{ext[1:]}" in client.calls[-1]


def test_a_pdf_still_goes_through_the_pdf_reader(client):
    res = _post(client, "notes.pdf", _text_pdf("I keep bees on the allotment"))
    assert res.status_code == 200, res.text
    assert "I keep bees on the allotment" in client.calls[-1]


def test_the_json_fast_path_still_skips_the_model(client):
    """The decision keeps it as a branch: a memories export round-trips with
    no model call."""
    res = _post(client, "memories.json",
                json.dumps([{"text": "User keeps bees", "category": "fact"}]))
    assert res.status_code == 200
    assert res.json()["suggestions"] == [{"text": "User keeps bees", "category": "fact"}]
    assert client.calls == []


def test_a_file_with_no_suffix_is_read_by_its_bytes(client):
    res = _post(client, "Makefile", "keeper:\n\techo Priya  # SENTINEL-makefile\n")
    assert res.status_code == 200, res.text
    assert "SENTINEL-makefile" in client.calls[-1]


def test_a_registered_text_suffix_is_never_refused(client):
    """`Law 1`, sharpened. A BOM-less UTF-16 `.txt` has NULs, so the probe
    alone would call it binary; a registered suffix is read the way chat
    ingest reads it, and the detector recovers it. The old route handed the
    model `P\\x00r\\x00i\\x00…` — valid UTF-8, so its decode never failed."""
    body = "Priya keeps bees on the allotment behind the house.\n"
    res = _post(client, "notes.txt", body.encode("utf-16-le"))
    assert res.status_code == 200, res.text
    assert "Priya keeps bees on the allotment" in client.calls[-1]


def test_text_whose_encoding_cannot_be_named_is_refused_as_that(client):
    """`B201`'s distinction reaches the person: eleven cp1251 bytes are text in
    an encoding nobody can identify from a sample that small, which is not the
    same sentence as "this is not text"."""
    res = _post(client, "server.conf", "сервер порт".encode("cp1251"))
    assert res.status_code == 400
    assert res.json()["detail"] == ("server.conf looks like text, but its encoding "
                                    "could not be identified from so few bytes.")
    assert client.calls == []


def test_a_legacy_encoded_file_is_read_in_its_own_encoding(client):
    """One decoder, the one chat ingest uses: a cp1251 `.ini` arrives as
    Cyrillic, not as replacement characters."""
    body = "[server]\nимя = Прия держит пчёл на участке за городом\nпорт = 8080\n"
    res = _post(client, "server.ini", body.encode("cp1251"))
    assert res.status_code == 200, res.text
    assert "Прия держит пчёл" in client.calls[-1]


# ── what fails to decode is refused, with the reason ─────────────────────────

@pytest.mark.parametrize("name, maker", [
    ("photo.png", _png), ("archive.zip", _zip), ("blob", lambda: b"\x00\x01\x02" * 400),
])
def test_what_is_not_text_is_refused_and_never_reaches_the_model(client, name, maker):
    res = _post(client, name, maker())
    assert res.status_code == 400
    detail = res.json()["detail"]
    assert detail.startswith(name) and "isn't text" in detail, detail
    assert client.calls == []


def test_an_office_file_nothing_can_read_is_refused_with_why(client):
    res = _post(client, "broken.docx", b"PK\x03\x04 not really a document")
    assert res.status_code == 400
    assert res.json()["detail"].startswith("Could not read broken.docx: ")
    assert client.calls == []


def test_nothing_is_kept_on_disk(client):
    """Read, refused, extracted: the temporary copy is gone every time."""
    for name, data in [("keeper.go", ROW_NAMED[".go"]), ("photo.png", _png()),
                       ("report.docx", office_fixture(".docx")),
                       ("notes.pdf", _text_pdf("bees"))]:
        _post(client, name, data)
        assert list(client.scratch.iterdir()) == [], name


# ── size is the real control, resolved for the person importing ──────────────

def test_the_byte_cap_is_resolved_for_the_caller(client, monkeypatch):
    """`D-2026-08-26-06`: size and rate become the real control, per role
    under `P12-01`. A role that caps one person at 1 KB caps that person —
    and only that person — which is what an owner-less resolve could not do."""
    monkeypatch.setattr(S, "_role_limit_provider",
                        lambda key, owner: 1024 if (key == "memory_import_max_bytes"
                                                    and owner == "alice") else None)
    big = "Priya keeps bees. " * 200
    refused = _post(client, "notes.txt", big, user="alice")
    assert refused.status_code == 413
    assert "Memory import exceeds 1 KB limit" in refused.json()["detail"]
    assert _post(client, "notes.txt", big, user="bob").status_code == 200


def test_the_instance_setting_caps_everyone(client):
    Path(S.SETTINGS_FILE).write_text(json.dumps({"memory_import_max_bytes": 2048}))
    S._invalidate_caches()
    assert _post(client, "notes.txt", "x" * 4096).status_code == 413
    assert _post(client, "notes.txt", "x" * 1024).status_code == 200


# ── the picker offers every file, and the refusal reaches the person ─────────

def test_the_file_picker_no_longer_filters_by_name():
    """`B02`'s rule: two lists that must agree is the bug. The server decides,
    so the input carries no `accept` — parsed, not grepped."""
    from html.parser import HTMLParser

    found = {}

    class _Finder(HTMLParser):
        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if attrs.get("id") == "memory-import-file":
                found.update(attrs, tag=tag)

    _Finder().feed(INDEX_HTML.read_text(encoding="utf-8"))
    assert found.get("tag") == "input" and found.get("type") == "file"
    assert "accept" not in found


@pytest.mark.skipif(not shutil.which("node"), reason="node not on PATH")
def test_the_person_is_told_why_a_file_was_refused(client):
    """The shipped `handleImportFile`, handed the route's own refusal: the
    reason is what the person reads (`Law 15`)."""
    detail = _post(client, "photo.png", _png()).json()["detail"]
    source = MEMORY_JS.read_text(encoding="utf-8")
    fn = js_definition(source, source.index("async function handleImportFile("))
    script = """
const errors = [];
const el = () => ({ disabled: false, innerHTML: '', value: 'x', style: {},
                    appendChild() {}, classList: { add() {}, remove() {} } });
const elements = { 'memory-import-btn': el(), 'memory-import-file': el() };
const document = { getElementById: (id) => elements[id] || null,
                   createTextNode: () => ({}), querySelector: () => null };
const window = { location: { origin: 'http://pantheon' } };
const spinnerModule = { createWhirlpool: () => ({ element: { style: {} }, destroy() {} }) };
const sessionModule = { getCurrentSessionId: () => null };
const fetch = async () => ({ ok: false, json: async () => ({ detail: %s }) });
const showError = (m) => errors.push(m);
const showToast = () => {};
const console = { error() {}, log() {} };
%s
handleImportFile({ name: 'photo.png' }).then(() => {
  process.stdout.write(JSON.stringify({ errors, reset: elements['memory-import-file'].value }));
});
""" % (json.dumps(detail), fn)
    proc = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["errors"] == [f"Import failed — {detail}"]
    assert out["reset"] == "", "the input is reset so the same file can be picked again"
