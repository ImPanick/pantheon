# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2031`. The mail composer's Gallery tab listed documents, and lit both tabs.

Writing mail in the document editor, the paperclip opens a menu that attaches
from Pantheon: Upload file, two tabs, Documents and Gallery, a search box and
a list. `P0-31` renamed the tabs' attribute from `data-ody-attach-kind` to
`data-pan-attach-kind` in the markup and in the two selectors, and left the
two reads of it on the old name (`btn.dataset.odyAttachKind`), which no button
has. So the menu opened with no tab lit, and a tab press loaded the list with
no kind: the Gallery tab asked `/api/documents/library` and listed documents,
both tabs lit up, a search typed after it searched documents too, and what
was picked from the list was sent to `/api/email/compose-from-pantheon`
without a kind it knows, which it refuses.

Now the tab press and the highlight read the buttons' own attribute,
`btn.dataset.panAttachKind`. The menu still keeps the kind it shows in
`menu.dataset.odyAttachKind`, for the search box.

Pantheon's own finding, from reviewing a port. Upstream Odysseus kept the old
name on both sides, so it does not have this fault.

Driven (`Law 20`): `_showComposeAttachMenu`, `_loadPantheonAttachItems`,
`_attachSelectedPantheonItems` and the helpers they call are cut out of
`static/js/document.js` with `tests/helpers/js_source` and run under node on
the shared DOM shim with its HTML parsing, so the menu is built from its own
markup. Stand-ins: the two library routes and the attach route answer from a
table, and the composer's attachment chips and autosave do nothing.
"""

import shutil
import sys
from pathlib import Path

import pytest

from tests.helpers.esc_stub import esc_source
from tests.helpers.js_source import js_binding

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_a_late_ai_reply_leaves_your_draft_alone_js import DOCJS, cut  # noqa: E402
from test_tool_effect_surfaces_js import _DOM, _run  # noqa: E402

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


_PAGE = esc_source() + r"""
const API_BASE = '';
const docs = new Map([['M1', { id: 'M1', language: 'email' }]]);
let activeDocId = 'M1';
let _autoSaveDebounce = null;
const told = [];
const uiModule = { esc, showToast: (m) => told.push(String(m)), showError: (m) => told.push('error: ' + m),
                   renderEmptyState: (host, spec) => { host.textContent = spec.title; } };
const spinnerModule = { createLoadingRow: () => document.createElement('div') };
const langIcon = () => '';
const _renderComposeAttachments = () => {};
const saveDocument = () => {};
globalThis.innerWidth = 1280;
globalThis.innerHeight = 800;
globalThis.requestAnimationFrame = (cb) => setTimeout(cb, 0);
// The person's documents and pictures, as the two library routes answer, and
// the attach route, which stages what it is sent.
const LIBRARY = {
  '/api/documents/library': { documents: [{ id: 'd1', title: 'Q3 figures', language: 'markdown' }] },
  '/api/gallery/library': { items: [{ id: 'g1', filename: 'harbour.png', caption: 'The harbour at dawn',
                                      url: '/api/gallery/image/harbour.png' }] },
};
const asked = [];
const sent = [];
globalThis.fetch = async (url, init = {}) => {
  const u = new URL(url, 'http://pantheon.test');
  if (init.method === 'POST') {
    sent.push(JSON.parse(init.body));
    return { ok: true, status: 200,
             json: async () => ({ success: true, token: 't1', filename: 'harbour.png', size: 2048 }) };
  }
  const search = u.searchParams.get('search');
  asked.push(u.pathname + (search ? ' search=' + search : ''));
  return { ok: true, status: 200, json: async () => LIBRARY[u.pathname] };
};
// A press or a keystroke, as the browser hands it to the element's own
// listeners; a disabled button is not pressed.
const press = (node) => node.disabled || node.dispatchEvent({ type: 'click', target: node,
  currentTarget: node, preventDefault() {}, stopPropagation() {} });
const type = (input, text) => { input.value = text; input.dispatchEvent({ type: 'input', target: input }); };
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const menu = () => document.querySelector('.email-pantheon-attach-menu');
const tabs = () => menu().querySelector('.email-pantheon-attach-tabs').querySelectorAll('button');
const tab = (label) => tabs().find((b) => b.textContent.trim() === label);
const lit = () => tabs().filter((b) => b.classList.contains('active')).map((b) => b.textContent.trim());
const listed = () => menu().querySelectorAll('.email-pantheon-attach-title').map((t) => t.textContent);
const paperclip = document.body.appendChild(document.createElement('button'));
"""

_FUNCTIONS = js_binding(DOCJS, "_pantheonAttachMenu") + "\n" + cut(
    "function _closePantheonAttachMenu(", "function _attachMenuOutsideClick(",
    "function _attachMenuEscape(", "function _positionPantheonAttachMenu(",
    "function _pantheonAttachLabel(", "async function _stagePantheonAttachment(",
    "function _afterPantheonAttachmentsAdded(", "function _selectedPantheonAttachRows(",
    "function _syncPantheonAttachSelection(", "async function _attachSelectedPantheonItems(",
    "async function _loadPantheonAttachItems(", "function _showComposeAttachMenu(",
    "function _activeDocLanguage(", "function _escHtml(")


@pytest.fixture(scope="module")
def page(tmp_path_factory):
    d = tmp_path_factory.mktemp("b2031")
    (d / "dom.js").write_text(_DOM)
    return d


def run(page, script: str) -> dict:
    preamble = ("import { installDom, installHtmlParsing } from './dom.js';\n"
                "const document = installDom();\ninstallHtmlParsing();\n")
    return _run(page, preamble, _PAGE + _FUNCTIONS + "\n" + script)


def test_the_gallery_tab_lists_the_gallery_and_lights_only_itself(page):
    """The menu opens on the documents under a lit Documents tab. Gallery
    lists the pictures and lights only Gallery, and Documents goes back.
    Before, the menu opened with no tab lit, and either tab listed the
    documents with both tabs lit."""
    out = run(page, """
        _showComposeAttachMenu(paperclip);
        await wait(10);
        const opened = { asked: asked.splice(0), lit: lit(), listed: listed() };
        press(tab('Gallery'));
        await wait(10);
        const gallery = { asked: asked.splice(0), lit: lit(), listed: listed() };
        press(tab('Documents'));
        await wait(10);
        const documents = { asked: asked.splice(0), lit: lit(), listed: listed() };
        console.log(JSON.stringify({ opened, gallery, documents }));
    """)
    on_documents = {"asked": ["/api/documents/library"], "lit": ["Documents"], "listed": ["Q3 figures"]}
    assert out["opened"] == on_documents
    assert out["gallery"] == {"asked": ["/api/gallery/library"], "lit": ["Gallery"],
                              "listed": ["The harbour at dawn"]}, (
        "the Gallery tab must ask the gallery and be the only tab lit")
    assert out["documents"] == on_documents


def test_a_search_typed_on_the_gallery_tab_searches_the_gallery(page):
    out = run(page, """
        _showComposeAttachMenu(paperclip);
        await wait(10);
        press(tab('Gallery'));
        await wait(10);
        asked.splice(0);
        type(menu().querySelector('.email-pantheon-attach-search'), 'harbour');
        await wait(300);
        console.log(JSON.stringify({ asked, lit: lit() }));
    """)
    assert out == {"asked": ["/api/gallery/library search=harbour"], "lit": ["Gallery"]}


def test_a_picture_picked_on_the_gallery_tab_is_what_the_email_carries(page):
    """Gallery, the first thing it lists, Attach: the picture is staged as a
    gallery image and goes on the email."""
    out = run(page, """
        _showComposeAttachMenu(paperclip);
        await wait(10);
        press(tab('Gallery'));
        await wait(10);
        press(menu().querySelector('.email-pantheon-attach-row'));
        press(menu().querySelector('.email-pantheon-attach-selected'));
        await wait(10);
        clearTimeout(_autoSaveDebounce);
        console.log(JSON.stringify({ sent, carries: (docs.get('M1')._composeAtts || []).map((a) => a.filename) }));
    """)
    assert out == {"sent": [{"kind": "gallery", "id": "g1"}], "carries": ["harbour.png"]}
