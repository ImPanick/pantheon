# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B1726` — while speech is turned into text, Pantheon says so, so it never
looks hung.

The owner, 2026-11-01: *"When the "Transcribing" is on - and listening, the
textbox needs to say so.. When the voice is being processed and transfered
into text - it needs to also say "Transcribing . . ." so the user doesn't think
it's hanging/crashing."* Dictation said "Recording..." and "Transcribing..." in
a toast that went after a few seconds, and the browser's own recognition said
nothing while its last words came; a press in the meantime took the little
there was away while the words were still on their way. The call's bar said
"Hearing you." for as long as the server took.

What is read:

  * the message box says "Listening . . ." in its prompt while the microphone
    records, and "Transcribing . . ." while what was said is written out, for
    the server's speech-to-text and the browser's own, for as long as it takes;
  * a box with words in it says the same in a pill beside them, and words typed
    while it listens move the saying there;
  * the dots step on the page's clock, and stand still under reduced motion;
  * a press while the words are on their way (the microphone, Send) leaves
    "Transcribing . . ." where it is;
  * the box's own prompt comes back however dictation ends: words, none, or a
    refusal, and no timer is left stepping;
  * a call's bar says "Transcribing . . ." while the server writes out a turn,
    "Hearing you." again the moment the person talks, and goes on to
    "Thinking." when the words are sent.

Driven (`Law 20`). Dictation: the real `static/js/voiceRecorder.js` under
node, imported unmodified beside a stub `appConfig.js` and a shim holding what
a page gives it (the box, the dictation button, the pill, a clock the case
moves, a microphone, a `MediaRecorder`, the server's two speech routes and the
browser's recognition). The call: `createVoiceCall` over
`tests/helpers/voice_call_sandbox.py`, the real `TurnDetector` fed frames. The
page itself is driven in Chromium by
`tests/test_voice_chat_is_set_up_and_talked_with_in_a_browser.py`.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from tests.helpers.voice_call_sandbox import build, run

ROOT = Path(__file__).resolve().parents[1]
RECORDER = ROOT / "static" / "js" / "voiceRecorder.js"
pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_APP_CONFIG = "export async function getAuthStatus() { return { is_admin: true }; }\n"

# What a page gives `voiceRecorder.js`, and no more.
_SHIM = r"""
export async function flush() { for (let i = 0; i < 20; i++) await new Promise((r) => setImmediate(r)); }

// The page's clock: the case moves it, so a 420 ms dot or a 5 s toast passes in no time.
let now = 0; let seq = 0; const due = new Map();
globalThis.setTimeout = (fn, ms, ...a) => { const k = ++seq; due.set(k, { at: now + (ms || 0), fn: () => fn(...a), every: 0 }); return k; };
globalThis.clearTimeout = (k) => { due.delete(k); };
globalThis.setInterval = (fn, ms, ...a) => { const k = ++seq; due.set(k, { at: now + ms, fn: () => fn(...a), every: ms }); return k; };
globalThis.clearInterval = (k) => { due.delete(k); };
export async function advance(ms) {
  const until = now + ms;
  for (;;) {
    let next = null;
    for (const [k, v] of due) if (v.at <= until && (!next || v.at < next[1].at)) next = [k, v];
    if (!next) break;
    const [k, v] = next;
    now = v.at;
    if (v.every) v.at += v.every; else due.delete(k);
    await v.fn();
    await flush();
  }
  now = until;
  await flush();
}

class El extends EventTarget {
  constructor(id) {
    super();
    this.id = id; this.dataset = {}; this.attrs = {}; this.kids = {};
    this.hidden = false; this.title = ''; this.value = ''; this.textContent = ''; this.focused = false;
    const c = new Set();
    this.classList = { add: (x) => c.add(x), remove: (x) => c.delete(x), contains: (x) => c.has(x) };
  }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; }
  removeAttribute(k) { delete this.attrs[k]; }
  querySelector(sel) { return this.kids[sel] || null; }
  focus() { this.focused = true; }
}
const els = new Map();
const make = (id) => { const e = new El(id); els.set(id, e); return e; };
const message = make('message');
message.setAttribute('placeholder', 'Message Pantheon...');
const mic = make('composer-mic-btn');
mic.hidden = true;
const pill = make('dictation-status');
pill.hidden = true;
pill.kids['.dictation-status-word'] = new El('');
pill.kids['.dictation-status-dots'] = new El('');
const send = make('send');
send.dataset.mode = 'idle';
globalThis.document = {
  getElementById: (id) => els.get(id) || null,
  querySelector: (sel) => (sel === '.send-btn' ? send : null),
};

let reduce = false;
const win = new EventTarget();
win.isSecureContext = true;
win.matchMedia = (q) => ({ matches: reduce && q.includes('reduce') });
win._updateSendBtnIcon = () => {};
globalThis.window = win;

// The microphone, the recorder and the browser's recognition.
const streams = [];
Object.defineProperty(globalThis, 'navigator', { configurable: true, writable: true, value: { mediaDevices: {
  getUserMedia: async () => {
    const track = { live: true, stop() { this.live = false; } };
    const stream = { getTracks: () => [track], track };
    streams.push(stream);
    return stream;
  },
} } });
class Recorder {
  static isTypeSupported(t) { return /webm/.test(t); }
  constructor(stream, o = {}) { this.stream = stream; this.mimeType = o.mimeType || 'audio/webm'; this.state = 'inactive'; }
  start() { this.state = 'recording'; }
  stop() {
    this.state = 'inactive';
    if (this.ondataavailable) this.ondataavailable({ data: new Blob(['sound'], { type: 'audio/webm' }) });
    Promise.resolve().then(() => this.onstop && this.onstop());
  }
}
globalThis.MediaRecorder = Recorder;
const recs = [];
class Recognition {
  constructor() { recs.push(this); }
  start() { this.live = true; }
  stop() { this.live = false; this.stopped = true; }
}
win.SpeechRecognition = Recognition;

// The server: `/api/stt/stats`, and `/api/stt/transcribe` held until the case answers it.
const stats = { provider: 'local', language: '' };
const asked = [];
const json = (body, status = 200) => ({ ok: status < 400, status, json: async () => body });
globalThis.fetch = async (url) => {
  if (url === '/api/stt/stats') return json({ ...stats, available: true });
  if (url === '/api/stt/transcribe') return new Promise((resolve) => asked.push((body, status = 200) => resolve(json(body, status))));
  return json({}, 404);
};

const toasts = []; const errors = []; const files = []; const said = [];
win.addEventListener('pantheon:dictation', (e) => said.push(e.detail.state));

export const page = {
  message, mic, pill, send, streams, recs, asked, toasts, errors, files, said,
  set provider(p) { stats.provider = p; },
  set reduceMotion(v) { reduce = !!v; },
  // Timers that repeat: a dot left stepping is one.
  get intervals() { return [...due.values()].filter((v) => v.every).length; },
  // What the box says now, as a person reads it.
  get box() {
    const word = pill.kids['.dictation-status-word'].textContent;
    const dots = pill.kids['.dictation-status-dots'].textContent;
    return {
      prompt: message.getAttribute('placeholder'),
      state: message.dataset.dictation || '',
      pill: pill.hidden ? null : `${word} ${dots}`,
      pillState: pill.dataset.state || '',
      value: message.value,
      mic: { pressed: mic.getAttribute('aria-pressed'), state: mic.dataset.state || '' },
    };
  },
  // A person typing in the box.
  type(text) { message.value = text; message.dispatchEvent(new Event('input')); },
  // The browser's recognition, after `stop()`: its last words, then `end`.
  finishRecognition(text) {
    const r = recs[recs.length - 1];
    if (text) r.onresult({ resultIndex: 0, results: [Object.assign([{ transcript: text }], { isFinal: true })] });
    r.onend();
  },
  callbacks: {
    onFileCreated: (f) => files.push(f.name),
    showToast: (m) => toasts.push(m),
    showError: (m) => errors.push(m),
    isCallOn: () => false,
  },
};
"""


def _box(tmp: Path) -> Path:
    shutil.copy(RECORDER, tmp / "voiceRecorder.js")
    # The real reduced-motion guard the recorder imports (`motion.js`, which
    # imports nothing), so the dots ask what the page asks.
    shutil.copy(RECORDER.parent / "motion.js", tmp / "motion.js")
    (tmp / "appConfig.js").write_text(_APP_CONFIG, encoding="utf-8")
    (tmp / "shim.mjs").write_text(_SHIM, encoding="utf-8")
    return tmp


def _dictate(box: Path, script: str, provider: str = "local") -> dict:
    case = box / "case.mjs"
    case.write_text(
        "import { page, flush, advance } from './shim.mjs';\n"
        "import * as VR from './voiceRecorder.js';\n"
        "const out = {};\n"
        f"page.provider = {json.dumps(provider)};\n"
        "VR.init(); await flush();\n"
        "VR.initDictation(page.callbacks);\n"
        "const press = async () => { page.mic.dispatchEvent(new Event('click', { cancelable: true })); await flush(); };\n"
        + textwrap.dedent(script)
        + "\nconsole.log(JSON.stringify(out));\n",
        encoding="utf-8",
    )
    try:
        proc = subprocess.run(["node", str(case)], cwd=box, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        raise AssertionError("node did not finish in 60 s") from None
    assert proc.returncode == 0, proc.stderr
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert lines, "node produced no stdout"
    return json.loads(lines[-1])


@pytest.fixture()
def dictation(tmp_path):
    return _box(tmp_path)


@pytest.fixture(scope="module")
def call(tmp_path_factory):
    return build(tmp_path_factory.mktemp("voicetranscribing"))


# ── dictation ──

def test_the_words_are_the_owners(dictation):
    o = _dictate(dictation, """
        out.listening = VR.dictationWords('listening');
        out.transcribing = VR.dictationWords('transcribing');
        out.steps = [0, 1, 2, 3].map((n) => VR.dictationWords('transcribing', n));
        out.idle = VR.dictationWords('');
    """)
    assert o["listening"] == "Listening . . ."
    assert o["transcribing"] == "Transcribing . . ."
    assert o["steps"] == ["Transcribing .", "Transcribing . .", "Transcribing . . .", "Transcribing ."]
    assert o["idle"] == ""


def test_an_empty_box_says_listening_while_the_microphone_records(dictation):
    o = _dictate(dictation, """
        out.before = page.box;
        await press();
        out.listening = page.box;
        out.steps = [page.box.prompt];
        for (let i = 0; i < 3; i++) { await advance(420); out.steps.push(page.box.prompt); }
        out.live = page.streams.map((s) => s.track.live);
        out.said = page.said.slice();
    """)
    assert o["before"]["prompt"] == "Message Pantheon..."
    assert o["listening"]["prompt"] == "Listening ."
    assert o["listening"]["state"] == "listening"
    assert o["listening"]["pill"] is None          # an empty box says it in its prompt
    assert o["listening"]["mic"] == {"pressed": "true", "state": ""}
    assert o["steps"] == ["Listening .", "Listening . .", "Listening . . .", "Listening ."]
    assert o["live"] == [True]
    assert o["said"] == ["listening"]


def test_the_box_says_transcribing_until_the_words_are_in_it(dictation):
    o = _dictate(dictation, """
        await press();
        await press();                     // stop: the server writes it out
        out.transcribing = page.box;
        out.asked = page.asked.length;
        out.micClosed = page.streams.every((s) => !s.track.live);
        await advance(6000);               // past the toast's 5 s, the words not back yet
        out.longAfter = page.box;
        await press();                     // a press while they are on their way
        VR.stopRecording();                // ... and Send's, which stops a recording
        await flush();
        out.afterPresses = page.box;
        page.asked[0]({ text: 'water the plants' });
        await flush();
        await advance(100);
        out.done = page.box;
        out.intervals = page.intervals;
        out.toasts = page.toasts.slice();
        out.said = page.said.slice();
        out.recordings = page.asked.length;
    """)
    assert o["transcribing"]["prompt"] == "Transcribing ."
    assert o["transcribing"]["state"] == "transcribing"
    assert o["transcribing"]["mic"] == {"pressed": "false", "state": "transcribing"}
    assert o["asked"] == 1
    assert o["micClosed"] is True
    assert o["longAfter"]["state"] == "transcribing"
    assert o["longAfter"]["prompt"].startswith("Transcribing")
    # Red before: the press reset dictation while the words were still coming.
    assert o["afterPresses"]["state"] == "transcribing"
    assert o["afterPresses"]["prompt"].startswith("Transcribing")
    assert o["afterPresses"]["mic"]["state"] == "transcribing"
    assert o["done"]["value"] == "water the plants"
    assert o["done"]["prompt"] == "Message Pantheon..."
    assert o["done"]["state"] == ""
    assert o["done"]["pill"] is None
    assert o["done"]["mic"] == {"pressed": "false", "state": ""}
    assert o["intervals"] == 0                    # no dot left stepping
    assert o["toasts"] == ["Recording...", "Transcribing...", "Transcribed"]
    assert o["said"] == ["listening", "transcribing", ""]
    assert o["recordings"] == 1


def test_a_box_with_words_says_it_in_a_pill_beside_them(dictation):
    o = _dictate(dictation, """
        page.type('Remind me to');
        await press();
        out.listening = page.box;
        await advance(420);
        out.stepped = page.box.pill;
        await press();
        out.transcribing = page.box;
        page.asked[0]({ text: 'water the plants' });
        await flush();
        out.done = page.box;
    """)
    assert o["listening"]["pill"] == "Listening ."
    assert o["listening"]["pillState"] == "listening"
    assert o["stepped"] == "Listening . ."
    assert o["transcribing"]["pill"] == "Transcribing ."
    assert o["transcribing"]["pillState"] == "transcribing"
    assert o["done"]["value"] == "Remind me to water the plants"
    assert o["done"]["pill"] is None
    assert o["done"]["pillState"] == ""
    assert o["done"]["prompt"] == "Message Pantheon..."


def test_words_typed_while_it_listens_move_the_saying_to_the_pill(dictation):
    o = _dictate(dictation, """
        await press();
        out.empty = page.box.pill;
        page.type('Also');
        out.typed = page.box.pill;
        page.type('');
        out.cleared = page.box.pill;
        await press();
        page.asked[0]({ text: '' });
        await flush();
        out.done = page.box;
        out.toasts = page.toasts.slice();
        page.type('more');
        out.afterwards = page.box.pill;
    """)
    assert o["empty"] is None
    assert o["typed"] == "Listening ."
    assert o["cleared"] is None
    assert o["done"]["prompt"] == "Message Pantheon..."
    assert o["done"]["state"] == ""
    assert "No speech detected" in o["toasts"]
    assert o["afterwards"] is None                # the box is not watched once it ends


def test_the_browsers_own_recognition_says_transcribing_while_its_last_words_come(dictation):
    o = _dictate(dictation, """
        await press();
        out.listening = page.box;
        await press();
        out.stopped = page.recs[0].stopped === true;
        out.transcribing = page.box;
        await advance(1000);
        out.second = page.box;
        page.finishRecognition('water the plants');
        await flush();
        await advance(100);
        out.done = page.box;
        out.intervals = page.intervals;
        out.said = page.said.slice();
    """, provider="browser")
    assert o["listening"]["prompt"] == "Listening ."
    assert o["stopped"] is True
    # Red before: the browser's path said nothing while it waited for `end`.
    assert o["transcribing"]["prompt"] == "Transcribing ."
    assert o["transcribing"]["mic"]["state"] == "transcribing"
    assert o["second"]["state"] == "transcribing"
    assert o["done"]["value"] == "water the plants"
    assert o["done"]["prompt"] == "Message Pantheon..."
    assert o["done"]["state"] == ""
    assert o["intervals"] == 0
    assert o["said"] == ["listening", "transcribing", ""]


def test_reduced_motion_holds_the_dots_still(dictation):
    o = _dictate(dictation, """
        page.reduceMotion = true;
        await press();
        out.listening = page.box.prompt;
        await advance(2000);
        out.later = page.box.prompt;
        page.reduceMotion = false;          // read each time, as motion.js reads it
        await advance(420);
        out.moving = page.box.prompt;
        page.reduceMotion = true;
        await press();
        out.transcribing = page.box.prompt;
        await advance(2000);
        out.stillTranscribing = page.box.prompt;
    """)
    assert o["listening"] == "Listening . . ."
    assert o["later"] == "Listening . . ."
    assert o["moving"] == "Listening ."
    assert o["transcribing"] == "Transcribing . . ."
    assert o["stillTranscribing"] == "Transcribing . . ."


def test_a_box_a_script_empties_shows_its_prompt_again(dictation):
    """A message sent while dictation listens empties the box with no `input`
    event; the pill gives the saying back to the prompt on the next beat."""
    o = _dictate(dictation, """
        page.type('Send this');
        await press();
        out.pill = page.box.pill;
        page.message.value = '';            // chat.js clearing the box after a send
        await advance(420);
        out.after = page.box;
    """)
    assert o["pill"] == "Listening ."
    assert o["after"]["pill"] is None
    assert o["after"]["prompt"].startswith("Listening")


def test_a_refused_transcription_gives_the_box_back_and_attaches_the_recording(dictation):
    o = _dictate(dictation, """
        await press();
        await press();
        page.asked[0]({ detail: { message: 'Whisper is not installed on this server.' } }, 503);
        await flush();
        await advance(100);
        out.done = page.box;
        out.errors = page.errors.slice();
        out.files = page.files.length;
        out.intervals = page.intervals;
    """)
    assert o["done"]["prompt"] == "Message Pantheon..."
    assert o["done"]["state"] == ""
    assert o["done"]["mic"] == {"pressed": "false", "state": ""}
    assert o["errors"] == ["Transcription failed: Whisper is not installed on this server."]
    assert o["files"] == 1
    assert o["intervals"] == 0


def test_a_box_with_no_prompt_is_given_none_back(dictation):
    o = _dictate(dictation, """
        page.message.removeAttribute('placeholder');
        await press();
        out.listening = page.box.prompt;
        await press();
        page.asked[0]({ text: 'hello' });
        await flush();
        out.done = page.box.prompt;
    """)
    assert o["listening"] == "Listening ."
    assert o["done"] is None


# ── the call ──

_TURN = """
    const h = setup({ tts: { provider: 'disabled', available: false }, sttDelays: true });
    await h.vc.start();
    await h.frames(SILENT, 25);
    await h.frames(LOUD, 30);
"""


def test_a_call_says_transcribing_while_the_server_writes_out_a_turn(call):
    o = run(call, _TURN + """
        out.talking = h.vc.state.words;
        await h.frames(SILENT, 45);        // the pause ends the turn
        out.asked = h.pendingStt.length;
        out.transcribing = { words: h.vc.state.words, phase: h.vc.state.phase };
        await h.T.advance(3000);
        out.stillTranscribing = h.vc.state.words;
        h.pendingStt[0](h.json({ text: 'What is the weather' }));
        await flush();
        out.back = h.vc.state.words;
        await h.T.advance(400);
        out.sent = h.sent;
        out.after = h.vc.state.words;
    """)
    assert o["talking"] == "Hearing you."
    assert o["asked"] == 1
    # Red before: "Hearing you." for as long as the server took.
    assert o["transcribing"] == {"words": "Transcribing . . .", "phase": "transcribing"}
    assert o["stillTranscribing"] == "Transcribing . . ."
    assert o["back"] == "Hearing you."          # heard, held a breath in case they go on
    assert o["sent"] == [["send", "What is the weather"]]
    assert o["after"] == "Thinking."


def test_talking_again_while_a_turn_is_written_out_is_hearing_you(call):
    o = run(call, _TURN + """
        await h.frames(SILENT, 45);
        out.first = h.vc.state.words;
        await h.frames(LOUD, 20);
        out.again = h.vc.state.words;
        await h.frames(SILENT, 45);
        out.both = { words: h.vc.state.words, asked: h.pendingStt.length };
        h.pendingStt[0](h.json({ text: 'Can you check the logs' }));
        await flush();
        out.oneBack = h.vc.state.words;
        h.pendingStt[1](h.json({ text: 'for the auth service' }));
        await flush(); await h.T.advance(400);
        out.sent = h.sent;
    """)
    assert o["first"] == "Transcribing . . ."
    assert o["again"] == "Hearing you."
    assert o["both"] == {"words": "Transcribing . . .", "asked": 2}
    assert o["oneBack"] == "Transcribing . . ."  # the second is still being written out
    assert o["sent"] == [["send", "Can you check the logs for the auth service"]]


def test_words_said_over_the_voice_say_transcribing_while_they_are_written_out(call):
    o = run(call, """
        const h = await speaking({ sttDelays: true });
        out.before = h.vc.state.words;
        await h.frames(LOUD, 30);
        out.over = { words: h.vc.state.words, paused: h.call.speaker.paused };
        await h.frames(SILENT, 50);
        out.transcribing = { words: h.vc.state.words, paused: h.call.speaker.paused };
        h.pendingStt[0](h.json({ text: 'Mm-hmm.' }));
        await flush();
        out.after = { words: h.vc.state.words, paused: h.call.speaker.paused };
    """)
    assert o["before"] == "Speaking."
    assert o["over"] == {"words": "Hearing you.", "paused": True}
    assert o["transcribing"] == {"words": "Transcribing . . .", "paused": True}
    assert o["after"] == {"words": "Speaking.", "paused": False}   # only listening: the voice goes on


def test_a_muted_call_waiting_on_its_words_says_transcribing(call):
    o = run(call, _TURN + """
        await h.frames(SILENT, 45);
        h.vc.toggleMute();
        out.muted = h.vc.state.words;
        h.pendingStt[0](h.json({ text: 'Hello there' }));
        await flush(); await h.T.advance(400);
        out.sent = h.sent;
    """)
    assert o["muted"] == "Transcribing . . ."
    assert o["sent"] == [["send", "Hello there"]]
