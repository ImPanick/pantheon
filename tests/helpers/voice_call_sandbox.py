# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B1718`. The voice chat's own modules under node, with stand-ins for what
a browser and the server give them.

The sandbox holds the real `static/js/speechText.js`, `voiceCapture.js` and
`voiceCall.js`, and `harness.mjs`:

  * a clock the case moves (`T.advance(ms)`), so a 300 ms hold or an 8 s
    watchdog runs in no time and in a known order;
  * a microphone that is fed frames at a level (`frames(SILENT, n)`,
    `talk(ms)`), into the real `TurnDetector`, and that can be held as a
    permission prompt holds it (`holdMic`, then `capture.allow()`);
  * a server answering `/api/stt/stats`, `/api/tts/stats`,
    `/api/stt/transcribe` (the next of `transcripts`) and
    `/api/tts/synthesize` (each text asked for is kept in `said`);
  * an audio element that is told when a sentence has played (`finish()`);
  * the browser's own voice, when asked for (`synth: true`): it keeps each
    utterance it is given (`synth.said`) and is told when one has been said
    (`synth.finish()`);
  * the browser's speech recognition, for a call whose provider is the
    browser's (`hear(text)` is a final result);
  * a chat that records what the call sends (`sent`) and is busy when told.

`run(box, script)` runs one case and answers what it put in `out`.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JS = ROOT / "static" / "js"
MODULES = ("speechText.js", "voiceCapture.js", "voiceCall.js")

HARNESS = r"""
import { createVoiceCall } from './voiceCall.js';

export const SILENT = Math.pow(10, -70 / 20);
export const LOUD = Math.pow(10, -20 / 20);

export async function flush() { for (let i = 0; i < 20; i++) await new Promise((r) => setImmediate(r)); }

export function makeTimers() {
  let t = 0; let id = 0; const q = new Map();
  const timers = {
    setTimeout(fn, ms) { const k = ++id; q.set(k, { at: t + (ms || 0), fn, every: 0 }); return k; },
    clearTimeout(k) { q.delete(k); },
    setInterval(fn, ms) { const k = ++id; q.set(k, { at: t + ms, fn, every: ms }); return k; },
    clearInterval(k) { q.delete(k); },
  };
  async function advance(ms) {
    const until = t + ms;
    for (;;) {
      let next = null;
      for (const [k, v] of q) if (v.at <= until && (!next || v.at < next[1].at)) next = [k, v];
      if (!next) break;
      const [k, v] = next;
      t = v.at;
      if (v.every) v.at += v.every; else q.delete(k);
      await v.fn();
      await flush();
    }
    t = until;
    await flush();
  }
  return { timers, advance, now: () => t };
}

export class FakePlayer {
  constructor() { this.src = ''; this.volume = 1; this.paused = true; this.plays = 0; this.onended = null; this.onerror = null; }
  play() { this.paused = false; this.plays += 1; return Promise.resolve(); }
  pause() { this.paused = true; }
  removeAttribute(a) { if (a === 'src') this.src = ''; }
  load() {}
  finish() { const f = this.onended; if (f) f(); }
}

export class FakeUtterance {
  constructor(text) { this.text = text; this.rate = 1; this.voice = null; this.onend = null; this.onerror = null; }
}

export function makeSynth(voices = [{ name: 'Samantha', lang: 'en-US' }, { name: 'Daniel (en-GB)', lang: 'en-GB' }]) {
  return {
    said: [], paused: false, cancels: 0, asked: 0,
    getVoices() { this.asked += 1; return voices; },
    speak(u) { this.said.push(u); },
    pause() { this.paused = true; },
    resume() { this.paused = false; },
    cancel() { this.cancels += 1; for (const u of this.said) if (!u.ended) { u.ended = true; if (u.onerror) u.onerror({ error: 'canceled' }); } },
    // The utterance being said, said to its end.
    finish() { const u = this.said.find((x) => !x.ended); if (u) { u.ended = true; if (u.onend) u.onend({}); } return u; },
  };
}

export function setup({ stt = {}, tts = {}, transcripts = [], chat = {}, sttStatus = 200, sttDelays = null, synth = false,
                        holdMic = false } = {}) {
  const T = makeTimers();
  const players = [];
  const log = [];
  const sent = [];
  const said = [];
  const ends = [];
  const events = new EventTarget();
  const recs = [];
  const pendingStt = [];
  let busy = false;
  const heard = [...transcripts];
  const json = (body, status = 200) => ({ ok: status < 400, status, json: async () => body, blob: async () => null });
  const sttStats = { provider: 'local', available: true, model_loaded: true,
    voice_chat: { enabled: true, pause: 'normal', barge_in: true }, ...stt };
  const fetchImpl = async (url, opts = {}) => {
    log.push(url);
    if (url === '/api/stt/stats') return json(sttStats);
    if (url === '/api/tts/stats') return json({ provider: 'piper', available: true, ...tts });
    if (url === '/api/stt/transcribe') {
      if (sttStatus !== 200) return json({ detail: { message: 'Whisper is not installed on this server.' } }, sttStatus);
      if (sttDelays) return new Promise((resolve) => pendingStt.push(resolve));
      return json({ text: heard.length ? heard.shift() : '' });
    }
    if (url === '/api/tts/synthesize') {
      const text = JSON.parse(opts.body).text;
      said.push(text);
      return { ok: true, status: 200, blob: async () => ({ text }), json: async () => ({}) };
    }
    return json({}, 404);
  };
  let capture = null;
  class Capture {
    constructor(o) { this.o = o; capture = this; }
    // `holdMic`: the browser is still asking for the microphone until
    // `capture.allow()`. `released`: stopped once it was open, as a real
    // microphone must be (a stop before it opened closes nothing).
    async start() { if (holdMic) await new Promise((r) => { this.allow = r; }); this.open = true; }
    stop() { this.stopped = true; if (this.open) this.released = true; }
  }
  class Audio extends FakePlayer { constructor() { super(); players.push(this); } }
  class Recognition {
    constructor() { recs.push(this); this.aborted = 0; }
    start() { this.started = true; }
    abort() { this.aborted += 1; if (this.onend) this.onend(); }
  }
  const c = {
    sendTurn: (t) => { sent.push(['send', t]); return 'sent'; },
    queueTurn: (t) => { sent.push(['queue', t]); return true; },
    stopReply: () => { sent.push(['stop']); },
    isBusy: () => busy,
    sessionId: () => 's1',
    canSteer: () => false,
    steerTurn: async (t) => { sent.push(['steer', t]); return 'steered'; },
    ...chat,
  };
  const speech = synth ? makeSynth() : null;
  const vc = createVoiceCall({
    chat: c, fetch: fetchImpl, events, timers: T.timers, now: T.now,
    media: { Capture, Audio, Recognition: sttStats.provider === 'browser' ? Recognition : null,
      synth: speech, Utterance: speech ? FakeUtterance : null,
      createUrl: (b) => `blob:${b.text}`, revokeUrl: () => {} },
    onEnd: (r, o) => ends.push([r, o]),
  });
  const frames = async (rms, n) => {
    for (let i = 0; i < n; i++) { capture.o.onFrame(rms, new Float32Array(320)); await T.advance(20); }
  };
  const reply = (phase, extra = {}) => events.dispatchEvent(
    Object.assign(new Event('pantheon:reply'), { detail: { phase, sessionId: 's1', ...extra } }));
  return {
    vc, T, log, sent, said, ends, frames, reply, recs, pendingStt, json, synth: speech,
    get call() { return vc._call; },
    get player() { return players[players.length - 1]; },
    get capture() { return capture; },
    setBusy(b) { busy = b; },
    // A turn: talking for `ms`, then the pause that ends it.
    async talk(ms = 600) { await frames(LOUD, ms / 20); await frames(SILENT, 50); },
    // A final result from the browser's recognition.
    hear(text) {
      const r = recs[recs.length - 1];
      r.onresult({ resultIndex: 0, results: [Object.assign([{ transcript: text }], { isFinal: true })] });
    },
    // Every sentence queued, played to its end.
    async playAll() {
      for (let i = 0; i < 12; i++) {
        if (!vc._call.speaker || !vc._call.speaker.busy) break;
        if (vc._call.speaker.mode === 'browser') speech.finish(); else this.player.finish();
        await flush();
      }
    },
  };
}

// A call that has started, learned the room, and is saying a reply that is
// still being written.
export async function speaking(opts = {}, text = 'Here is a long answer about the history of the city and its rivers. It goes on for a while with more detail.') {
  const h = setup(opts);
  await h.vc.start();
  await h.frames(SILENT, 25);
  h.setBusy(true);
  h.reply('start');
  h.reply('text', { text });
  await flush();
  return h;
}
"""


def build(directory: Path) -> Path:
    for name in MODULES:
        shutil.copy(JS / name, directory / name)
    (directory / "harness.mjs").write_text(HARNESS, encoding="utf-8")
    return directory


def run(box: Path, script: str, timeout: float = 60) -> dict:
    case = box / "case.mjs"
    case.write_text(
        "import { setup, speaking, flush, makeTimers, SILENT, LOUD } from './harness.mjs';\n"
        "import * as VC from './voiceCall.js';\n"
        "import * as CAP from './voiceCapture.js';\n"
        "import * as ST from './speechText.js';\n"
        "const out = {};\n"
        + textwrap.dedent(script)
        + "\nconsole.log(JSON.stringify(out));\n",
        encoding="utf-8",
    )
    try:
        proc = subprocess.run(["node", str(case)], cwd=box, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise AssertionError(f"node did not finish in {timeout:g} s") from None
    assert proc.returncode == 0, proc.stderr
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert lines, "node produced no stdout"
    return json.loads(lines[-1])
