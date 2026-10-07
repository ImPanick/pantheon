# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P23-04` — the chat's words, by Doc 2 § 5's voice guide: a failed reply
(CHAT-M-13, CHAT-U-26, PERF-U-6, CHAT-M-23), the no-model state (CHAT-M-14,
CHAT-U-13), the welcome line (CHAT-U-12, COPY-U-14, COPY-M-3/4/5), the header's
count (CHAT-M-22) and the tool splash bubbles (CHAT-M-18, CHAT-U-14).

**What was wrong** (measured on `9560d50`, `mech-chat.md`/`ux-chat.md`):

  * a model 500 drew red italics "[Error: local endpoint is having an outage
    (HTTP 500). … CUDA out of memory]", an unreachable one "[Error: Cannot
    reach http://127.0.0.1:47111]" — no Retry, and the picker went on offering
    the dead endpoint as if it were up;
  * with no model, Enter threw the typed message away and a sender called "…"
    listed three options;
  * the welcome screen said "New chat ready." over a random tip per load, three
    of them false ("Right-click a session…", "the + button next to the
    input", "Switch to Agent mode for web search");
  * the header counted the "Response ready in …" note as a message;
  * the first two switches of Web/Shell/Deep Research wrote an explainer into
    the transcript as a reply.

Driven under node (`Law 20`) through the real functions.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.helpers.js_source import js_definition
from tests.helpers.source_text import blank_text
from test_tool_effect_surfaces_js import _make_sandbox, _run

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_SHIM = r"""
import { installDom, Node } from './dom.js';
export const document = installDom();
export { Node };
globalThis.window = globalThis;
globalThis.CustomEvent = class CustomEvent { constructor(type, init) { this.type = type; this.detail = (init || {}).detail; } };
globalThis.__events = [];
globalThis.dispatchEvent = (e) => { globalThis.__events.push({ type: e.type, detail: e.detail }); return true; };
"""


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    return _make_sandbox(tmp_path_factory.mktemp("chatwords"), JS / "chatStreamErrors.js", _SHIM, {})


_PRE = "import { document, Node } from './shim.js';\nconst errs = await import('./chatStreamErrors.js');\n"


def _text(node_expr: str) -> str:
    return "(function t(n){ return (n.textContent || '') + n.childNodes.map(t).join('|'); })(%s)" % node_expr


def test_a_model_500_says_one_sentence_with_retry_and_details(sandbox):
    out = _run(sandbox, _PRE, """
        let retried = 0;
        const err = { message: 'local endpoint is having an outage (HTTP 500). CUDA out of memory', status: 500 };
        const box = errs.buildReplyError(document, err, { model: 'scripted-demo', onRetry: () => { retried += 1; } });
        const retry = box.querySelector('.reply-error-retry');
        retry.listeners.click[0]();
        console.log(JSON.stringify({ sentence: box.querySelector('.reply-error-text').textContent,
          retry: retry.textContent, retried, details: %s, events: globalThis.__events }));
    """ % _text("box.querySelector('.reply-error-details')"))
    assert out["sentence"] == "The model didn't answer (HTTP 500)."
    assert out["retry"] == "Retry" and out["retried"] == 1
    assert "Details" in out["details"] and "CUDA out of memory" in out["details"]
    assert out["events"] == [], "a 500 is not an unreachable endpoint"


def test_an_unreachable_model_is_named_and_the_picker_is_told(sandbox):
    out = _run(sandbox, _PRE, """
        const err = { message: 'Cannot reach http://127.0.0.1:47111' };
        const box = errs.buildReplyError(document, err, { model: 'library/broken-demo', onRetry: () => {} });
        console.log(JSON.stringify({ sentence: box.querySelector('.reply-error-text').textContent,
          events: globalThis.__events }));
    """)
    assert out["sentence"] == "broken-demo isn't answering."
    assert out["events"] == [{"type": "pantheon:endpoint-unanswered",
                              "detail": {"url": "http://127.0.0.1:47111"}}]


def test_the_words_are_never_markup(sandbox):
    out = _run(sandbox, _PRE, """
        const box = errs.buildReplyError(document, { message: 'invalid key <img src=x>', status: 401 });
        console.log(JSON.stringify({ html: box.innerHTML || '', pre: box.querySelector('pre').textContent }));
    """)
    assert out["pre"] == "invalid key <img src=x>"
    assert "<img" not in out["html"]


# ── no model ────────────────────────────────────────────────────────────────

def _chat_cut(anchor: str) -> str:
    src = (JS / "chat.js").read_text(encoding="utf-8")
    code = blank_text(src, "js")
    assert code.count(anchor) == 1, anchor
    return js_definition(src, code.index(anchor)).replace("export function", "function", 1)


def test_with_no_model_the_message_is_kept_and_the_door_is_offered(sandbox):
    out = _run(sandbox, _PRE, """
        const box = document.createElement('div'); box.id = 'chat-history'; document.body.appendChild(box);
        const door = document.createElement('button'); door.id = 'model-picker-add-models-btn'; document.body.appendChild(door);
        let opened = 0; door.click = () => { opened += 1; };
        const message = document.createElement('textarea'); message.id = 'message'; message.value = 'hello there';
        document.body.appendChild(message);
        let welcomeHidden = 0;
        const hideWelcomeScreen = () => { welcomeHidden += 1; };
        const uiModule = { scrollHistory() {} };
        %s
        _sayNoModel();
        _sayNoModel();   // twice: still one line
        const notes = box.querySelectorAll('.no-model-note');
        const add = notes[0].querySelector('.no-model-add');
        add.listeners.click[0]();
        console.log(JSON.stringify({ count: notes.length, text: %s, opened, kept: message.value,
          welcomeHidden, msgs: box.querySelectorAll('.msg').length, after: box.querySelectorAll('.no-model-note').length }));
    """ % (_chat_cut("export function _sayNoModel("), _text("notes[0]")))
    assert out["count"] == 1
    assert "No model yet." in out["text"] and "Add a model" in out["text"]
    assert out["opened"] == 1 and out["after"] == 0
    assert out["kept"] == "hello there", "the typed message was thrown away"
    assert out["msgs"] == 0, "the no-model line is not a reply from someone"


def test_the_send_path_keeps_the_box_when_there_is_no_model(tmp_path):
    """The no-session branch of `handleChatSubmit`, cut out whole: with no
    default model it says so and returns, and the box keeps its text."""
    src = (JS / "chat.js").read_text(encoding="utf-8")
    code = blank_text(src, "js")
    start = code.index("export async function handleChatSubmit(")
    handler = js_definition(src, start)
    hcode = code[start:start + len(handler)]
    said = hcode.index("_sayNoModel();")
    branch = js_definition(handler, hcode.rindex("if (!sessionModule.getCurrentSessionId()) {", 0, said))
    script = """
        const calls = { said: 0, released: 0 };
        const box = { value: 'keep me' };
        const el = (id) => (id === 'message' ? box : null);
        const uiModule = { autoResize() {} };
        const sessionModule = { getCurrentSessionId: () => null };
        const _sendPerf = { mark() {} };
        const _sayNoModel = () => { calls.said += 1; };
        const _releaseSendFlag = () => { calls.released += 1; };
        const addMessage = () => { calls.added = true; };
        globalThis.window = globalThis;
        globalThis.localStorage = { getItem: () => null, setItem() {} };
        globalThis.fetch = async () => ({ json: async () => ({}) });
        async function run() { %s }
        await run();
        console.log(JSON.stringify(Object.assign(calls, { value: box.value })));
    """ % branch
    (tmp_path / "case.mjs").write_text(script, encoding="utf-8")
    proc = subprocess.run(["node", "case.mjs"], cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out == {"said": 1, "released": 1, "value": "keep me"}


# ── the welcome line ────────────────────────────────────────────────────────

def _welcome_script() -> str:
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    for m in re.finditer(r"<script>(.*?)</script>", html, re.S):
        if "welcome-tip" in m.group(1):
            return m.group(1)
    raise AssertionError("the welcome script is gone")


@pytest.mark.parametrize("phone, line", [
    (False, "Drop files here to attach them."),
    (True, "Tap ^ beside the message box to attach files."),
])
def test_the_welcome_says_one_true_line(tmp_path, phone, line):
    script = """
        const tip = { textContent: '' };
        globalThis.window = { matchMedia: () => ({ matches: %s }) };
        globalThis.document = { getElementById: (id) => (id === 'welcome-tip' ? tip : null) };
        globalThis.fetch = () => Promise.resolve({ json: () => ({}) });
        globalThis.location = { hash: '' };
        const seen = new Set();
        for (let i = 0; i < 40; i++) { (function () { %s }).call(globalThis); seen.add(tip.textContent); }
        console.log(JSON.stringify([...seen]));
    """ % ("true" if phone else "false", _welcome_script().replace("window.", "globalThis.window."))
    (tmp_path / "case.mjs").write_text(script, encoding="utf-8")
    proc = subprocess.run(["node", "case.mjs"], cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout.strip().splitlines()[-1]) == [line]


def test_the_welcome_heading_says_nothing_under_the_name():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    m = re.search(r'<div class="welcome-sub" id="welcome-sub">([^<]*)</div>', html)
    assert m and m.group(1) == ""


# ── the header's count, and the splash ─────────────────────────────────────

def test_the_header_counts_what_was_said(tmp_path):
    src = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    code = blank_text(src, "js")
    fn = js_definition(src, code.index("const _updateMsgCount = () => {"))
    script = """
        // Children of #chat-history, by class. The selector the count asks
        // with is evaluated here for `:scope > .msg` with any `:not(.x)`s.
        const kids = ['msg msg-user', 'msg msg-ai', 'msg msg-ai msg-continuation',
                      'msg msg-system stream-done-toast', 'agent-thread', 'msg msg-user', 'msg msg-ai'];
        const _chatHistEl = { querySelectorAll(sel) {
          const m = /^:scope > \\.msg((?::not\\(\\.[\\w-]+\\))*)$/.exec(sel);
          if (!m) throw new Error('unexpected selector ' + sel);
          const nots = [...m[1].matchAll(/:not\\(\\.([\\w-]+)\\)/g)].map((x) => x[1]);
          return kids.filter((c) => c.split(' ').includes('msg') && !nots.some((n) => c.split(' ').includes(n)));
        } };
        const _metaCountEl = { textContent: '' };
        let _countScheduled = true;
        %s;
        _updateMsgCount();
        console.log(JSON.stringify(_metaCountEl.textContent));
    """ % fn
    (tmp_path / "case.mjs").write_text(script, encoding="utf-8")
    proc = subprocess.run(["node", "case.mjs"], cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout.strip().splitlines()[-1]) == "· 4 msgs"


def test_no_tool_switch_writes_into_the_transcript():
    """Absence across the whole file is the one thing a file-wide check may
    prove (`Law 20`): the splash builder and its class are gone everywhere."""
    app = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    code = blank_text(app, "js")
    assert "_showToolSplash" not in code
    assert "tool-splash" not in code


@pytest.mark.parametrize("hash, hidden", [
    ("#7cf2a1b0-1c2d-4e5f-8a9b-0c1d2e3f4a5b", True),
    ("", False),
    ("#document-12", False),
])
def test_an_address_that_names_a_chat_skips_the_welcome_hero(tmp_path, hash, hidden):
    """`P23-04` (PERF-U-2): measured on `9560d50`, `/#<id>` painted the welcome
    hero for 1.7 s (5.9 s at 4x CPU) under a header already naming the chat."""
    script = """
        const cls = (start) => { const s = new Set(start); return { add: (c) => s.add(c), remove: (c) => s.delete(c), has: (c) => s.has(c) }; };
        const ws = { classList: cls([]) }, cc = { classList: cls(['welcome-active']) }, tip = { textContent: '' };
        globalThis.window = { matchMedia: () => ({ matches: false }) };
        globalThis.location = { hash: %s };
        globalThis.document = { getElementById: (id) => ({ 'welcome-screen': ws, 'chat-container': cc, 'welcome-tip': tip })[id] || null };
        globalThis.fetch = () => Promise.resolve({ json: () => ({}) });
        (function () { %s }).call(globalThis);
        console.log(JSON.stringify({ hidden: ws.classList.has('hidden'), welcome: cc.classList.has('welcome-active'),
          flag: !!globalThis.window.__pantheonDeepLinkHidWelcome }));
    """ % (json.dumps(hash), _welcome_script().replace("window.", "globalThis.window."))
    (tmp_path / "case.mjs").write_text(script, encoding="utf-8")
    proc = subprocess.run(["node", "case.mjs"], cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out == {"hidden": hidden, "welcome": not hidden, "flag": hidden}


def test_the_pickers_forge_door_never_writes_a_dead_address(sandbox):
    """fx-back's `B-NEW-1` (P23-01, NAV-M-9's second half), in this lane's
    file: with neither Forge door on the page the picker wrote `#cookbook`,
    which nothing reads — it stuck in the address and opened nothing."""
    src = (JS / "modelPicker.js").read_text(encoding="utf-8")
    code = blank_text(src, "js")
    fn = js_definition(src, code.index("function _openPickerShortcut("))
    out = _run(sandbox, _PRE, """
        globalThis.location = { hash: '' };
        globalThis.window.cookbookModule = undefined;
        const _close = () => {};
        const settingsModule = null;
        %s
        _openPickerShortcut('cookbook');
        const btn = document.createElement('button'); btn.id = 'tool-cookbook-btn'; document.body.appendChild(btn);
        let clicked = 0; btn.click = () => { clicked += 1; };
        _openPickerShortcut('cookbook');
        console.log(JSON.stringify({ hash: location.hash, clicked }));
    """ % fn)
    assert out == {"hash": "", "clicked": 1}


def test_the_picker_dims_an_endpoint_that_did_not_answer_even_before_it_loaded(sandbox):
    """CHAT-M-23, driven on the showcase: the reply failed before the picker
    had loaded its list, so marking the list's entries marked nothing and the
    dead endpoint was offered as up. The address is kept; the picker's own
    `_getAllModels` dims every model on it, and a refresh's probe replaces it."""
    src = (JS / "modelPicker.js").read_text(encoding="utf-8")
    code = blank_text(src, "js")

    def cut(anchor):
        assert code.count(anchor) == 1, anchor
        return js_definition(src, code.index(anchor))

    listener = cut("(ev) => {\n      const base = String((ev && ev.detail && ev.detail.url)")
    out = _run(sandbox, _PRE, """
        let _localProbe = {}, _localProbeFetchedAt = 123;
        const _unansweredBases = new Set();
        const sortModelObjects = (x) => x;
        let items = [];
        globalThis.window.modelsModule = { getCachedItems: () => items };
        %s
        %s
        const onUnanswered = %s;
        onUnanswered({ detail: { url: 'http://127.0.0.1:9' } });   // the list is still empty
        items = [{ endpoint_id: 'e1', url: 'http://127.0.0.1:9/v1', models: ['office-llm'], category: 'local' },
                 { endpoint_id: 'e2', url: 'http://127.0.0.1:90/v1', models: ['other'], category: 'local' }];
        const rows = _getAllModels().map((r) => [r.mid, r.stale, r.staleReason]);
        _unansweredBases.clear();   // what the refresh's probe does
        const after = _getAllModels().map((r) => [r.mid, r.stale]);
        console.log(JSON.stringify({ rows, after, refetch: _localProbeFetchedAt }));
    """ % (cut("function _unansweredFor("), cut("function _getAllModels("), listener))
    assert out["rows"] == [["office-llm", True, "not answering"], ["other", False, ""]]
    assert out["after"] == [["office-llm", False], ["other", False]]
    assert out["refetch"] == 0, "the refresh button must ask again"
