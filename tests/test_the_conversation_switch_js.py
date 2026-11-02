# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B1730` — the Conversation switch and the voice card, under node.

`static/js/conversation.js` is each person's switch for the agent saying its
replies out loud: the composer's chip and the switch at the top of Settings →
Conversation are one switch, kept with the account (`/api/prefs/conversation`)
and mirrored in the browser so the chip is right before the server answers.
`static/js/conversationSettings.js` draws the voices on offer and says, under
the select, where the chosen one speaks.

Driven (`Law 20`): the real modules, copied beside a stand-in `ui.js` (whose
toast is kept) and run over a small DOM: elements, events, `localStorage`,
`fetch` answered per route, and the page's speaker (`aiTTSManager`, which the
real `tts-ai.js` puts on `window`) as a record of what it was told. The whole
flow in a real browser, with real speech, is
`tests/test_conversation_speaks_replies_in_a_browser.py`.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"
pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_UI = "export function showToast(message, ms) { globalThis.__toasts.push(String(message)); }\n"

_SHIM = r"""
// Only what conversation.js and conversationSettings.js touch.
class ClassList {
  constructor() { this.set = new Set(); }
  add(...c) { c.forEach((x) => this.set.add(x)); }
  remove(...c) { c.forEach((x) => this.set.delete(x)); }
  toggle(c, on) { const want = on === undefined ? !this.set.has(c) : !!on; if (want) this.set.add(c); else this.set.delete(c); return want; }
  contains(c) { return this.set.has(c); }
}
class El {
  constructor(tag, props = {}) {
    this.tagName = tag.toUpperCase(); this.children = []; this.attrs = {}; this.classList = new ClassList();
    this.style = {}; this.listeners = {}; this.hidden = false; this.title = ''; this._text = '';
    this.checked = false; this.disabled = false; this.label = ''; this._value = ''; this.type = '';
    Object.assign(this, props);
  }
  get textContent() { return this._text + this.children.map((c) => c.textContent).join(''); }
  set textContent(v) { this.children = []; this._text = String(v); }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  addEventListener(t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); }
  dispatchEvent(e) { (this.listeners[e.type] || []).slice().forEach((fn) => fn(e)); return true; }
  click() { this.dispatchEvent({ type: 'click', preventDefault() {} }); }
  appendChild(c) { this.children.push(c); c.parentNode = this; return c; }
  get options() { const all = []; const walk = (n) => n.children.forEach((c) => { if (c.tagName === 'OPTION') all.push(c); else walk(c); }); walk(this); return all; }
  querySelectorAll(sel) { const tag = sel.toUpperCase(); const all = []; const walk = (n) => n.children.forEach((c) => { if (c.tagName === tag) all.push(c); walk(c); }); walk(this); return all; }
  get value() {
    if (this.tagName !== 'SELECT') return this._value;
    const opts = this.options;
    const chosen = opts.find((o) => o.selected) || opts[0];
    return chosen ? chosen.value : '';
  }
  set value(v) {
    if (this.tagName !== 'SELECT') { this._value = String(v); return; }
    this.options.forEach((o) => { o.selected = o.value === String(v); });
  }
}
const byId = {};
const doc = new El('document');
doc.getElementById = (id) => byId[id] || null;
doc.createElement = (tag) => new El(tag);
doc.querySelectorAll = (sel) => sel === '[data-conversation-switch]'
  ? Object.values(byId).filter((n) => 'data-conversation-switch' in n.attrs) : [];
globalThis.document = doc;
const win = new El('window');
globalThis.window = win;
globalThis.CustomEvent = class { constructor(type, init = {}) { this.type = type; this.detail = init.detail; } };
const store = {};
globalThis.localStorage = { getItem: (k) => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); } };
globalThis.__toasts = [];
globalThis.__events = [];
doc.addEventListener('overflow-state-change', () => globalThis.__events.push('overflow-state-change'));

// The server, answered per route, and every request kept.
export const asked = [];
export const routes = {};
globalThis.fetch = async (url, opts = {}) => {
  asked.push([opts.method || 'GET', url, opts.body ? JSON.parse(opts.body) : null]);
  const answer = routes[`${opts.method || 'GET'} ${url}`] || { status: 404, body: { detail: 'not found' } };
  if (answer.throws) throw new TypeError('Failed to fetch');
  return { ok: answer.status < 400, status: answer.status, json: async () => answer.body,
           headers: { get: () => null }, blob: async () => ({}) };
};
export const flush = () => new Promise((r) => setTimeout(r, 0));
export async function settle() { for (let i = 0; i < 5; i++) await flush(); }

export function element(id, tag = 'button', props = {}, attrs = {}) {
  const n = new El(tag, props);
  n.id = id;
  Object.entries(attrs).forEach(([k, v]) => n.setAttribute(k, v));
  byId[id] = n;
  return n;
}

// The page's speaker, as `tts-ai.js` leaves it on `window`, keeping what it is told.
export function speaker(state = {}) {
  const mgr = { checked: true, speaks: true, off: false, reason: '', autoPlay: false, isPlaying: false,
                _processing: false, warmed: 0, stopped: 0, ...state };
  mgr.checkAvailability = ({ warm = false } = {}) => { if (warm) mgr.warmed += 1; };
  mgr.stop = () => { mgr.stopped += 1; mgr.isPlaying = false; mgr._processing = false; };
  window.aiTTSManager = mgr;
  return mgr;
}
export { store, El };
"""


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    d = tmp_path_factory.mktemp("conversation")
    for name in ("conversation.js", "conversationSettings.js"):
        shutil.copy(JS / name, d / name)
    (d / "ui.js").write_text(_UI, encoding="utf-8")
    (d / "shim.mjs").write_text(_SHIM, encoding="utf-8")
    return d


def run(box: Path, script: str) -> dict:
    """One case in a fresh node: each module is new, as a page load is."""
    case = box / "case.mjs"
    case.write_text(
        "import { asked, routes, flush, settle, element, speaker, store, El } from './shim.mjs';\n"
        "const out = {};\n"
        "const C = await import('./conversation.js');\n"
        "const S = await import('./conversationSettings.js');\n"
        + textwrap.dedent(script)
        + "\nout.toasts = globalThis.__toasts; out.events = globalThis.__events;\n"
        "console.log(JSON.stringify(out));\n",
        encoding="utf-8")
    proc = subprocess.run(["node", str(case)], cwd=box, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads([ln for ln in proc.stdout.splitlines() if ln.strip()][-1])


_PAGE = """
    const chip = element('conversation-toggle-btn', 'button', {}, { 'data-conversation-switch': '', 'aria-pressed': 'false' });
    const sw = element('conv-switch', 'input', { type: 'checkbox' }, { 'data-conversation-switch': '' });
"""


def test_the_chip_starts_as_this_browser_last_saw_it_and_the_account_wins(box):
    o = run(box, _PAGE + """
        store['pantheon.conversation'] = '1';
        const mgr = speaker();
        routes['GET /api/prefs/conversation'] = { status: 200, body: { key: 'conversation', value: false } };
        C.initConversation();
        out.first = [chip.getAttribute('aria-pressed'), chip.classList.contains('active'), sw.checked, mgr.autoPlay];
        await settle();
        out.after = [chip.getAttribute('aria-pressed'), sw.checked, mgr.autoPlay, C.conversationOn()];
        out.mirror = store['pantheon.conversation'];
        C.initConversation();   // once a page
        out.asked = asked.length;
    """)
    assert o["first"] == ["true", True, True, True], "the mirror draws it before the server answers"
    assert o["after"] == ["false", False, False, False], "what the account says wins"
    assert o["mirror"] == "0" and o["asked"] == 1


def test_turned_on_it_is_kept_with_the_account_and_the_voice_is_loaded(box):
    o = run(box, _PAGE + """
        const mgr = speaker();
        routes['GET /api/prefs/conversation'] = { status: 200, body: { value: null } };
        routes['PUT /api/prefs/conversation'] = { status: 200, body: { value: true } };
        C.initConversation();
        await settle();
        const seen = [];
        C.onConversationChange((on) => seen.push(on));
        chip.click();
        await settle();
        out.state = [chip.getAttribute('aria-pressed'), sw.checked, mgr.autoPlay, mgr.warmed, store['pantheon.conversation']];
        out.put = asked.filter((a) => a[0] === 'PUT');
        out.seen = seen;
    """)
    assert o["state"] == ["true", True, True, 1, "1"]
    assert o["put"] == [["PUT", "/api/prefs/conversation", {"value": True}]]
    assert o["toasts"] == ["Conversation on"] and o["seen"] == [True]


def test_an_account_that_did_not_keep_it_is_said(box):
    o = run(box, _PAGE + """
        speaker();
        routes['GET /api/prefs/conversation'] = { status: 200, body: { value: false } };
        routes['PUT /api/prefs/conversation'] = { status: 500, body: {} };
        C.initConversation();
        await settle();
        await C.toggleConversation();
        out.on = C.conversationOn();
    """)
    assert o["on"] is True, "on in this browser all the same"
    assert o["toasts"] == ["Conversation on here; your account did not keep it"]


def test_with_no_voice_that_speaks_it_is_not_turned_on_and_says_why(box):
    o = run(box, _PAGE + """
        const mgr = speaker({ speaks: false, reason: 'Speaking with Kokoro needs its model (about 350 MB).' });
        routes['GET /api/prefs/conversation'] = { status: 200, body: { value: false } };
        C.initConversation();
        await settle();
        window.dispatchEvent({ type: 'pantheon:speech', detail: { speaks: false, off: false, reason: mgr.reason } });
        out.cannot = [chip.classList.contains('conversation-cannot'), chip.title, chip.hidden];
        out.result = await C.toggleConversation();
        out.on = [C.conversationOn(), chip.getAttribute('aria-pressed'), mgr.autoPlay];
        out.put = asked.filter((a) => a[0] === 'PUT').length;
    """)
    assert o["cannot"] == [True, "Conversation: Speaking with Kokoro needs its model (about 350 MB).", False]
    assert o["result"] is False and o["on"] == [False, "false", False] and o["put"] == 0
    assert o["toasts"] == ["Speaking with Kokoro needs its model (about 350 MB)."]


def test_speech_off_on_the_server_takes_the_chip_away_and_the_row_measures_again(box):
    o = run(box, _PAGE + """
        speaker();
        routes['GET /api/prefs/conversation'] = { status: 404, body: {} };
        C.initConversation();
        await settle();
        window.dispatchEvent({ type: 'pantheon:speech', detail: { speaks: false, off: true, reason: 'Speech is turned off.' } });
        out.off = [chip.hidden, chip.style.display, globalThis.__events.length];
        window.dispatchEvent({ type: 'pantheon:speech', detail: { speaks: false, off: true } });
        out.again = globalThis.__events.length;
        window.dispatchEvent({ type: 'pantheon:speech', detail: { speaks: true, off: false } });
        out.on = [chip.hidden, chip.style.display, globalThis.__events.length, chip.classList.contains('conversation-cannot'),
                  chip.title];
    """)
    assert o["off"] == [True, "none", 1]
    assert o["again"] == 1, "measured again only when it changed"
    assert o["on"] == [False, "", 2, False, "Conversation: the agent says its replies out loud"]


def test_turned_off_while_it_speaks_it_stops(box):
    o = run(box, _PAGE + """
        const mgr = speaker();
        routes['GET /api/prefs/conversation'] = { status: 200, body: { value: true } };
        routes['PUT /api/prefs/conversation'] = { status: 200, body: { value: false } };
        C.initConversation();
        await settle();
        mgr.isPlaying = true;
        await C.setConversation(false);
        out.state = [mgr.stopped, mgr.autoPlay, sw.checked];
    """)
    assert o["state"] == [1, False, False]


# ── The voice card ──


_OFFER = {
    "off": False,
    "server": {"chosen": "auto", "provider": "kokoro", "voice": "af_heart",
               "label": "Kokoro, Heart · American English, woman", "available": True},
    "engines": [
        {"id": "kokoro", "name": "Kokoro", "where": "on this server", "available": True, "reason": None,
         "voices": [{"id": "af_heart", "label": "Heart · American English, woman", "language": "American English", "gender": "woman"},
                    {"id": "bf_emma", "label": "Emma · British English, woman", "language": "British English", "gender": "woman"}]},
        {"id": "chatterbox", "name": "Chatterbox", "where": "on this server's GPU", "available": False,
         "reason": "Chatterbox is not running.", "voices": []},
        {"id": "piper", "name": "Piper", "where": "on this server", "available": True, "reason": None,
         "voices": [{"id": "en_US-ljspeech-medium", "label": "en_US-ljspeech-medium"}]},
    ],
}


def test_a_kept_voice_is_a_select_value_and_back(box):
    o = run(box, """
        out.values = [S.valueOf(null), S.valueOf({ engine: '' }), S.valueOf({ engine: 'kokoro', voice: 'bf_emma' }),
                      S.valueOf({ engine: 'browser', voice: 'Google UK English Female' })];
        out.choices = [S.choiceOf('', ''), S.choiceOf('', '1.25'), S.choiceOf('kokoro:bf_emma', ''),
                       S.choiceOf('browser:Google: UK', '0.9'), S.choiceOf('piper', null)];
    """)
    assert o["values"] == ["", "", "kokoro:bf_emma", "browser:Google UK English Female"]
    assert o["choices"] == [None, {"engine": "", "voice": "", "speed": 1.25},
                            {"engine": "kokoro", "voice": "bf_emma", "speed": None},
                            {"engine": "browser", "voice": "Google: UK", "speed": 0.9},
                            {"engine": "piper", "voice": "", "speed": None}]


def test_the_voices_are_drawn_by_engine_and_by_language_with_what_does_not_run_shown_not_offered(box):
    o = run(box, f"""
        const sel = new El('select');
        S.drawVoices(sel, {json.dumps(_OFFER)}, [{{ name: 'Samantha', localService: true }}, {{ name: 'Google US English', localService: false }}]);
        out.first = [sel.options[0].value, sel.options[0].textContent];
        out.groups = sel.children.slice(1).map((g) => [g.label, g.children.map((o) => [o.value, o.textContent, o.disabled])]);
        S.drawVoices(sel, {{ ...{json.dumps(_OFFER)}, server: {{ available: false }} }}, []);
        out.cannot = sel.options[0].textContent;
        out.redrawn = sel.children.length;
    """)
    assert o["first"] == ["", "Pantheon’s voice (Kokoro, Heart · American English, woman)"]
    assert o["groups"] == [
        ["Kokoro · American English", [["kokoro:af_heart", "Heart · American English, woman", False]]],
        ["Kokoro · British English", [["kokoro:bf_emma", "Emma · British English, woman", False]]],
        ["Chatterbox · on this server's GPU", [["chatterbox:", "Chatterbox is not running here", True]]],
        ["Piper · on this server", [["piper:en_US-ljspeech-medium", "en_US-ljspeech-medium", False]]],
        ["This device’s voices", [["browser:Samantha", "Samantha", False],
                                  ["browser:Google US English", "Google US English (online)", False]]],
    ]
    assert o["cannot"] == "Pantheon’s voice (it cannot speak here yet)"
    assert o["redrawn"] == 1 + 4, "drawn again from nothing, not added to"


def test_the_note_says_where_the_voice_speaks_and_whose_words_leave_the_machine(box):
    o = run(box, f"""
        const offer = {json.dumps(_OFFER)};
        out.notes = ['', 'kokoro:bf_emma', 'chatterbox:default', 'piper:en_US-ljspeech-medium', 'browser:Samantha']
          .map((v) => S.noteFor(v, offer));
        out.serverCannot = S.noteFor('', {{ ...offer, server: {{ available: false, reason: 'No voice can speak here.' }} }});
    """)
    assert o["notes"] == [
        "The voice an admin chose for everyone (Settings → Voice). Choose your own to change it for you alone.",
        "Kokoro speaks on this server’s own processor, so a reply’s words stay here.",
        "Chatterbox is not running.",
        "Piper speaks on this server’s own processor, so a reply’s words stay here.",
        "Your browser speaks these. In Chrome, the voices named Google, and any marked online, are Google’s "
        "online service, so a reply’s words leave this machine for those.",
    ]
    assert o["serverCannot"] == "No voice can speak here."
