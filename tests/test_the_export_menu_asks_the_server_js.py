# SPDX-License-Identifier: AGPL-3.0-or-later
"""fx6-export — what the chat's Export menu asks for, and what it writes out.

The owner, 2026-10-09: *"it only exports 1 page (top portion of the chat) -
never the FULL chat."* Every item in the menu read `#chat-history`, and the
chat renders a page at a time (`sessions.js` `HISTORY_PAGE_LIMIT_DESKTOP` 24,
`…_MOBILE` 8). Measured in Chromium on a 42-message chat before this lane: 24
`.msg` in the box and Question 1 not among them.

Three functions out of `static/app.js`, driven under node on the shared DOM
shim (`tests/test_tool_effect_surfaces_js.py`'s `installDom`, extended here
with the one thing a print frame needs and the shim has not got — an iframe
with a document of its own):

* `_fetchWholeChat(fmt)` — the one door to `GET /api/session/{sid}/export`,
  and what it does when the server will not answer;
* `_printWholeChat(name)` — the PDF item: the server's whole-chat HTML in a
  frame of its own, and that frame is what prints;
* `_serializeChatTranscript()` — the fallback, which is still the rendered
  page, and which used to write a multi-round agent turn out **twice** because
  `chat.js` puts the turn's whole text on the bubble its footer sits under as
  well as on the first one. The owner's own export shows it: the same `<think>`
  block byte for byte under two `gemma-4-26b:` headings
  (`/work/notes/owner-shots/2026-10-09-osrs-chat-export.md`, lines 52-76 and
  78-102).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.helpers.js_source import js_definition

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "static" / "app.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _cut(*signatures) -> str:
    src = APP.read_text(encoding="utf-8")
    out = []
    for sig in signatures:
        assert src.count(sig) == 1, f"{sig!r} appears {src.count(sig)} times in app.js"
        out.append(js_definition(src, src.index(sig)))
    return "\n\n".join(out)


@pytest.fixture(scope="module")
def dom_dir(tmp_path_factory):
    """The suite's own DOM shim on disk, so this file extends it rather than
    writing a second one (`Law 14`)."""
    import test_tool_effect_surfaces_js as harness

    directory = tmp_path_factory.mktemp("exportmenu")
    (directory / "dom.js").write_text(harness._DOM)
    (directory / "shim.js").write_text(_SHIM)
    return directory


# An iframe with a document of its own, which the shared shim has not got: the
# print path writes the server's export into one and prints that.
_SHIM = r"""
import { installDom, Node } from './dom.js';
export const document = installDom();

const makeFrameDoc = () => {
  const doc = new Node('#document');
  doc.head = doc.appendChild(new Node('head'));
  doc.body = doc.appendChild(new Node('body'));
  doc.title = '';
  doc._written = '';
  doc.open = () => { doc._written = ''; };
  doc.write = (html) => { doc._written += html; };
  doc.close = () => {
    // Enough of a parse for what the cases ask: the document's title, and
    // everything that is not a tag as its text.
    const m = /<title>([\s\S]*?)<\/title>/i.exec(doc._written);
    doc.title = m ? m[1] : '';
    doc.body.textContent = doc._written.replace(/<[^>]*>/g, '');
  };
  return doc;
};

// The print path arms a long fallback timer so a browser that never fires
// `afterprint` still takes the frame out; under node an un-unref'd handle
// would hold the process open past the end of the case.
const realTimeout = globalThis.setTimeout;
globalThis.setTimeout = (fn, ms) => { const t = realTimeout(fn, ms); if (t && t.unref) t.unref(); return t; };

export const printed = [];
const create = document.createElement;
document.createElement = (tag) => {
  const el = create(tag);
  if (String(tag).toLowerCase() === 'iframe') {
    el.contentDocument = makeFrameDoc();
    el.contentWindow = {
      addEventListener: (type, fn) => { el._after = type === 'afterprint' ? fn : el._after; },
      focus: () => {},
      // A browser fires `afterprint` when the dialog closes; the print path
      // takes the frame out on it.
      print: () => { printed.push(el.contentDocument._written); if (el._after) el._after(); },
    };
  }
  return el;
};
"""

_PRE = r"""
import { document, printed } from './shim.js';
const API_BASE = '';
const asked = [];
let answer = null;
globalThis.fetch = async (url) => {
  asked.push(String(url));
  if (answer === null) return { ok: false, status: 500, text: async () => '' };
  return { ok: true, status: 200, text: async () => answer };
};
let currentSession = 's-1';
const sessionModule = { getCurrentSessionId: () => currentSession, getSessions: () => [] };
const uiModule = { showToast: () => {}, showError: () => {} };
__SOURCE__
"""


def _run(dom_dir: Path, script: str) -> dict:
    body = _PRE.replace("__SOURCE__", _cut(
        "async function _fetchWholeChat(",
        "async function _printWholeChat(",
        "function _serializeChatTranscript(",
    )) + script
    out = subprocess.run(["node", "--input-type=module"], input=body, capture_output=True,
                         text=True, cwd=dom_dir, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


# ── the one door to the server ──────────────────────────────────────────────

def test_the_whole_chat_is_asked_of_the_export_route(dom_dir):
    out = _run(dom_dir, """
        answer = '# Conversation: x\\n\\nQuestion 1';
        const md = await _fetchWholeChat('md');
        const html = await _fetchWholeChat('html');
        console.log(JSON.stringify({ md, asked, html: html.length > 0 }));
    """)
    assert out["asked"] == [
        "/api/session/s-1/export?fmt=md",
        "/api/session/s-1/export?fmt=html",
    ]
    assert out["md"].endswith("Question 1")


def test_a_server_that_refuses_is_not_mistaken_for_an_empty_chat(dom_dir):
    """`null`, not `''` — so the caller falls back to the rendered page rather
    than exporting nothing and reporting success."""
    out = _run(dom_dir, """
        answer = null;                      // HTTP 500
        const refused = await _fetchWholeChat('md');
        answer = '   ';                     // 200, nothing in it
        const blank = await _fetchWholeChat('md');
        globalThis.fetch = async () => { throw new Error('offline'); };
        const offline = await _fetchWholeChat('md');
        currentSession = null;
        const nochat = await _fetchWholeChat('md');
        console.log(JSON.stringify({ refused, blank, offline, nochat }));
    """)
    assert out == {"refused": None, "blank": None, "offline": None, "nochat": None}


# ── the PDF item prints the whole chat ──────────────────────────────────────

WHOLE = ("<!DOCTYPE html><html><head><title>The long chat</title></head><body>"
         "<div class='msg user'>Question 1</div><div class='msg ai'>Answer 1</div>"
         "<div class='msg user'>Question 21</div><div class='msg ai'>Answer 21</div>"
         "</body></html>")


def test_the_pdf_item_prints_the_servers_whole_chat_not_the_page(dom_dir):
    out = _run(dom_dir, """
        answer = %s;
        const ok = await _printWholeChat('The long chat');
        console.log(JSON.stringify({ ok, asked, printed,
          left: document.body.children.filter((n) => n.id === 'export-print-frame').length }));
    """ % json.dumps(WHOLE))
    assert out["ok"] is True
    assert out["asked"] == ["/api/session/s-1/export?fmt=html"], "the whole chat, as HTML"
    assert len(out["printed"]) == 1
    document = out["printed"][0]
    assert "Question 1" in document and "Answer 21" in document, "the first and last messages"
    assert out["left"] == 0, "the frame is taken out again"


def test_the_pdf_item_says_no_when_the_server_cannot_be_asked(dom_dir):
    """False, so the click handler falls back to printing the page — a PDF of
    one page beats no PDF at all."""
    out = _run(dom_dir, """
        answer = null;
        const ok = await _printWholeChat('x');
        console.log(JSON.stringify({ ok, printed,
          frames: document.body.children.filter((n) => n.tagName === 'IFRAME').length }));
    """)
    assert out == {"ok": False, "printed": [], "frames": 0}


# ── the fallback writes one turn once ───────────────────────────────────────

_TURN = r"""
const mk = (cls, raw, role, extra) => {
  const n = document.createElement('div');
  n.className = cls;
  if (raw !== null) n.dataset.raw = raw;
  Object.assign(n.dataset, extra || {});
  const r = document.createElement('div'); r.className = 'role'; r.textContent = role || '';
  const b = document.createElement('div'); b.className = 'body'; b.textContent = raw || '';
  n.appendChild(r); n.appendChild(b);
  return n;
};
const box = document.createElement('div');
box.id = 'chat-history';
document.body.appendChild(box);
"""

THINK = "<think>The user is asking for research into the Fractured Archive.</think>"


def test_one_agent_turn_is_one_entry_not_two(dom_dir):
    """The owner's export, reproduced: `chat.js` writes the turn's whole text
    onto the first bubble of the turn and onto the bubble its footer ends up
    under, so a walk that reads `dataset.raw` off every bubble wrote the reply
    out twice. The second copy says it is one (`data-raw-echo`)."""
    out = _run(dom_dir, _TURN + """
        box.appendChild(mk('msg msg-user', 'Research: the Fractured Archive', ''));
        // `holder` — the turn's first bubble, hidden because its step only thought
        const first = mk('msg msg-ai', %s, 'gemma-4-26b');
        first.style.display = 'none';
        box.appendChild(first);
        // `footerTarget` — the bubble the turn shows, carrying the same text
        box.appendChild(mk('msg msg-ai', %s, 'gemma-4-26b', { rawEcho: '1' }));
        const t = _serializeChatTranscript();
        console.log(JSON.stringify({ t, headings: (t.match(/gemma-4-26b:/g) || []).length,
                                     thinks: (t.match(/<think>/g) || []).length }));
    """ % (json.dumps(THINK), json.dumps(THINK)))
    assert out["headings"] == 1, out["t"]
    assert out["thinks"] == 1, "the same reasoning twice is what the owner got"
    assert "Research: the Fractured Archive" in out["t"]


def test_a_turn_whose_only_carrier_is_the_echo_is_still_written(dom_dir):
    """The skip is "a copy of something already written", never "skip copies":
    when the first bubble carried nothing, the copy is the only carrier and the
    reply must not be lost to this."""
    out = _run(dom_dir, _TURN + """
        box.appendChild(mk('msg msg-user', 'hello', ''));
        box.appendChild(mk('msg msg-ai', null, 'gemma-4-26b'));   // no raw at all
        box.appendChild(mk('msg msg-ai', 'the whole reply', 'gemma-4-26b', { rawEcho: '1' }));
        console.log(JSON.stringify({ t: _serializeChatTranscript() }));
    """)
    assert "the whole reply" in out["t"]


def test_two_replies_that_happen_to_match_are_both_written(dom_dir):
    """Only a bubble that says it is a copy is ever skipped. Two separate
    replies with the same words are two replies."""
    out = _run(dom_dir, _TURN + """
        box.appendChild(mk('msg msg-user', 'again?', ''));
        box.appendChild(mk('msg msg-ai', 'Done.', 'gemma-4-26b'));
        box.appendChild(mk('msg msg-user', 'again?', ''));
        box.appendChild(mk('msg msg-ai', 'Done.', 'gemma-4-26b'));
        const t = _serializeChatTranscript();
        console.log(JSON.stringify({ dones: (t.match(/Done\\./g) || []).length,
                                     asks: (t.match(/again\\?/g) || []).length }));
    """)
    assert out == {"dones": 2, "asks": 2}


def test_the_tool_calls_the_page_drew_are_still_in_the_fallback(dom_dir):
    out = _run(dom_dir, _TURN + """
        const thread = document.createElement('div');
        thread.className = 'agent-thread';
        const node = document.createElement('div');
        node.className = 'agent-thread-node';
        const t = document.createElement('div'); t.className = 'agent-thread-tool'; t.textContent = 'Web Search';
        const c = document.createElement('div'); c.className = 'agent-thread-cmd'; c.textContent = 'fractured archive';
        node.appendChild(t); node.appendChild(c);
        thread.appendChild(node);
        box.appendChild(thread);
        console.log(JSON.stringify({ t: _serializeChatTranscript() }));
    """)
    assert "[Tool calls]" in out["t"]
    assert "- Web Search [done]" in out["t"]
    assert "cmd: fractured archive" in out["t"]


# ── the wiring ──────────────────────────────────────────────────────────────

def test_every_item_in_the_export_menu_goes_through_the_server(dom_dir):
    """`Law 13`: the menu's handlers, in `app.js`, must actually call it.
    Scoped to each handler rather than grepping the file (`Law 20`)."""
    src = APP.read_text(encoding="utf-8")
    for anchor, want, fallback in (
        ("exportCopyBtn.addEventListener", "_fetchWholeChat('txt')", "_serializeChatTranscript()"),
        # The PDF item's fallback is printing the page, not serializing it.
        ("exportPdfBtn.addEventListener", "_printWholeChat(sessionName)", "window.print()"),
        ("exportDocBtn.addEventListener", "_fetchWholeChat('md')", "_serializeChatTranscript()"),
    ):
        at = src.index(anchor)
        handler = js_definition(src, at)
        assert want in handler, f"{anchor} does not ask the server: {want!r}"
        assert fallback in handler, \
            f"{anchor} lost its fallback for a server that cannot be asked"


def test_the_menu_has_a_download_and_every_item_has_a_handler():
    """The four server formats existed and only `/export` in the composer could
    reach them. The markup's item and the handler's id are the same id."""
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    start = html.index('id="export-dropdown-menu"')
    end = html.index("</div></span></div>", start)
    ids = re.findall(r'class="export-dropdown-item[^"]*" id="([^"]+)"', html[start:end])
    assert ids == ["export-rename-btn", "export-compact-btn", "export-copy-btn",
                   "export-file-btn", "export-pdf-btn", "export-doc-btn",
                   "export-delete-btn"], ids
    app = APP.read_text(encoding="utf-8")
    for item in ids:
        assert f"el('{item}')" in app, f"{item} is in the markup with nothing behind it"
    assert "Download Chat (.md)" in html[start:end]


def test_the_copy_on_the_footer_bubble_says_it_is_a_copy():
    """The other half of the one-turn-one-entry rule lives in `chat.js`, where
    the copy is made. Scoped to the assignment, not the file."""
    src = (ROOT / "static" / "js" / "chat.js").read_text(encoding="utf-8")
    at = src.index("if (footerTarget !== holder) {")
    block = src[at:src.index("}", src.index("rawEcho", at)) + 1]
    assert "footerTarget.dataset.raw = accumulated;" in block, \
        "Copy, TTS and regenerate read the raw here — the assignment stays"
    assert "footerTarget.dataset.rawEcho = '1';" in block
