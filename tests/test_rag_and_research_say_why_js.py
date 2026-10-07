# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P23-02` — the browser halves of RAG and Deep Research saying why.

  * `BRAIN-M-4` / `BRAIN-M-5`: the real `static/js/rag.js` under node — a
    refused upload is the app's toast with the server's sentence (it was a
    native alert dialog reading `Upload failed: {"detail":"RAG system is not
    available — is the embedding service running?"}`), and a dead index puts
    the server's reason under the heading (it said "Drop files above to add to
    RAG" and let the upload find out).
  * `BRAIN-M-6` / `D-34`: `research/panel.js`'s fail note and report count, cut
    out of the module and run (`Law 20`'s second option — the panel imports
    the theme, the synapse and the run-mode picker, and the note is two
    bindings).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402
from tests.helpers.esc_stub import ui_default_stub
from tests.helpers.js_source import js_binding, js_definition

ROOT = Path(__file__).resolve().parents[1]
RAG_JS = ROOT / "static" / "js" / "rag.js"
PANEL_JS = ROOT / "static" / "js" / "research" / "panel.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_STUBS = {
    "ui.js": ui_default_stub(
        "showToast: (m) => calls.toasts.push(String(m)), showError: (m) => calls.errors.push(String(m)),"
        " styledConfirm: async () => true,",
        before="export const calls = { toasts: [], errors: [] };"),
    "spinner.js": ("export default { createWhirlpool: () => ({ element: globalThis.document.createElement('span'),"
                   " destroy(){} }) };\n"),
}

_SHIM = r"""
import { installDom, installHtmlParsing } from './dom.js';
export const document = installDom();
installHtmlParsing();
document.body.innerHTML = `
  <div class="memory-tab-panel" data-memory-panel="rag">
    <p id="rag-health" hidden></p>
    <button id="rag-upload-zone">Drop files here or click to upload</button>
    <input type="file" id="rag-file-input">
    <div id="docs-view"></div>
  </div>`;
export const tick = async (n = 8) => { for (let i = 0; i < n; i++) await new Promise((r) => setTimeout(r, 0)); };
"""

_PREAMBLE = """
import { document, tick } from './shim.js';
import { calls } from './ui.js';
const alerts = [];
globalThis.alert = (m) => alerts.push(String(m));
globalThis.MutationObserver = class { observe() {} disconnect() {} };
const rag = (await import('./rag.js')).default;
const $ = (id) => document.getElementById(id);
const reply = (status, body) => ({ ok: status >= 200 && status < 300, status,
  json: async () => body, text: async () => JSON.stringify(body) });
const out = (o) => console.log(JSON.stringify(o));
"""


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    return _make_sandbox(tmp_path_factory.mktemp("ragwhy"), RAG_JS, _SHIM, _STUBS)


def test_a_dead_index_says_why_under_the_heading(box):
    o = _run(box, _PREAMBLE, """
        const reason = 'RAG is off: the embedding model is not downloaded — Settings › System › Download models from the internet.';
        globalThis.fetch = async () => reply(200, { files: [], healthy: false, reason });
        await rag.loadPersonalDocs();
        const down = { hidden: $('rag-health').hidden, text: $('rag-health').textContent, list: $('docs-view').textContent.trim() };
        globalThis.fetch = async () => reply(200, { files: [], healthy: true, reason: '' });
        await rag.loadPersonalDocs();
        out({ down, up: { hidden: $('rag-health').hidden, text: $('rag-health').textContent } });
    """)
    assert o["down"]["hidden"] is False
    assert o["down"]["text"].startswith("RAG is off: the embedding model is not downloaded")
    assert o["down"]["list"] == "No files yet."
    assert o["up"] == {"hidden": True, "text": ""}


def test_a_non_admins_rag_tab_offers_no_upload_and_logs_nothing(box):
    """`B-NEW-8` (P23 round 2). Measured on `a936b5c` as `guest`: the RAG tab
    offered *Drop files here or click to upload* above *Admin only*, and the
    console logged `Error: Admin only at loadPersonalDocs` — the refusal was
    thrown, then `console.error`ed. Every `/api/personal` route is
    `require_admin`; the refusal is the tab's one line now."""
    o = _run(box, _PREAMBLE, """
        const logged = [];
        console.error = (...a) => logged.push(a.map(String).join(' '));
        globalThis.fetch = async () => reply(403, { detail: 'Admin only' });
        await rag.loadPersonalDocs();
        const guest = { zone: $('rag-upload-zone').style.display, health: $('rag-health').hidden,
                        list: $('docs-view').textContent.trim(), logged: logged.slice() };
        globalThis.fetch = async () => reply(200, { files: [], healthy: true });
        await rag.loadPersonalDocs();
        out({ guest, admin: { zone: $('rag-upload-zone').style.display, list: $('docs-view').textContent.trim() },
              errors: calls.errors });
    """)
    assert o["guest"] == {"zone": "none", "health": True, "list": "Admin only", "logged": []}
    assert o["admin"] == {"zone": "block", "list": "No files yet."}, "the upload comes back for someone the list answers"
    assert o["errors"] == [], "a refusal is not an error toast either"


def test_a_refused_upload_is_a_toast_with_the_servers_sentence(box):
    o = _run(box, _PREAMBLE, """
        globalThis.fetch = async (url, init = {}) => init.method === 'POST'
          ? reply(503, { detail: 'RAG is off: the document index did not start. The server log says why.' })
          : reply(200, { files: [] });
        await rag.uploadRagFiles([{ name: 'n.txt' }]);
        globalThis.fetch = async (url, init = {}) => init.method === 'DELETE'
          ? reply(403, { detail: 'Only an admin can remove files.' }) : reply(200, { files: [] });
        out({ alerts, errors: calls.errors, zone: $('rag-upload-zone').textContent });
    """)
    assert o["alerts"] == [], "a native alert dialog again"
    assert o["errors"] == ["RAG is off: the document index did not start. The server log says why."]
    assert o["zone"] == "Drop files here or click to upload"


def test_a_research_card_says_why_it_found_nothing(tmp_path):
    """`BRAIN-M-6`. On `32df791` every empty run read "Couldn't extract
    anything — try rephrasing the question, or switch the search engine in
    Settings.", including one whose model planned no search at all."""
    src = PANEL_JS.read_text(encoding="utf-8")
    table = js_binding(src, "_FAIL_NOTE")
    count = js_definition(src, src.index("function _reportCount("))
    case = tmp_path / "note.mjs"
    case.write_text(table + "\n" + count + """
console.log(JSON.stringify({
  notes: ['no_queries', 'no_results', 'no_search_provider', '', undefined].map((k) => _FAIL_NOTE[k] || _FAIL_NOTE['']),
  counts: [0, 1, 3].map(_reportCount),
}));
""", encoding="utf-8")
    proc = subprocess.run(["node", str(case)], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    got = json.loads(proc.stdout.strip().splitlines()[-1])
    assert got["notes"] == ["The model gave no search queries.", "The search engine returned nothing.",
                            "No search engine is set up — Settings → Search.", "Nothing was found.",
                            "Nothing was found."]
    assert got["counts"] == ["No reports", "1 report", "3 reports"]
