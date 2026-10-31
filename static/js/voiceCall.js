// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/voiceCall.js

/**
 * `B1718`. Voice chat: talking with the agent the way a call works.
 *
 * The person talks; the browser hears when they stop (`TurnDetector`); what
 * they said becomes text (`POST /api/stt/transcribe`, or the browser's own
 * recognition) and goes into the open chat as their next message — so it is
 * the same agent, with its tools, approvals and memory, and the call is a chat
 * that can be read afterwards. The reply is spoken sentence by sentence while
 * it is still being written (`SpeechChunker` over `pantheon:reply`, which
 * `chat.js` announces), and the call goes back to listening when it has been
 * said.
 *
 * Talking over the agent interrupts it, the way it does on a phone. The voice
 * ducks at the first sound and pauses once that sound is long enough to be
 * words; when the words come back from speech-to-text the rest of the reply is
 * dropped, and when they come back empty (a cough), or as the agent's own
 * sentence heard back through the speakers, or as "mm-hmm", the voice picks
 * up where it paused. What the person said then goes to the agent: as a steer
 * when it is part-way through an agent run that takes one (and as the next
 * message if the run ends before it reads the steer), otherwise after the
 * reply in flight is stopped. With "interrupt by talking" off the call takes
 * turns instead, and does not listen while the agent speaks.
 *
 * A short command is not sent: "stop" or "wait" stops the voice (and "stop"
 * the reply), "end the call" or "hang up" ends it. An approval is never given
 * by voice: the call says one is needed and waits for the card. Anything that
 * cannot work — no speech-to-text chosen, a model not downloaded, a microphone
 * refused — is said in the bar in the server's or the browser's own words, and
 * a voice that fails leaves the call going in text.
 *
 * `createVoiceCall` takes what it touches as arguments, so the tests drive the
 * whole loop under node with stand-ins (`tests/test_a_voice_call_*`);
 * `initVoiceCall` wires the page's.
 */

import { SpeechChunker } from './speechText.js';
import { VoiceCapture, TurnDetector, encodeWav, PAUSES } from './voiceCapture.js';

// A thirtieth of a second of silence, played inside the click that starts
// the call: Safari lets an audio element play later only once it has played
// in a gesture.
const SILENT_WAV = 'data:audio/wav;base64,UklGRhQBAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YfAAAACA'
  + 'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
  + 'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
  + 'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIA=';

/** What the bar says the call is doing: a word and a stop, as "Ready." does. */
export const PHASE_WORDS = Object.freeze({
  starting: 'Starting.',
  listening: 'Listening.',
  hearing: 'Hearing you.',
  thinking: 'Thinking.',
  speaking: 'Speaking.',
  waiting: 'Waiting for you.',
  muted: 'Muted.',
});

const STOP_WORDS = /^(?:stop|cancel|never ?mind|be quiet|quiet|shush|hold on|wait|pause)(?: (?:it|that|please|now|talking))?[.!]*$/i;
const STOP_REPLY = /^(?:stop|cancel|never ?mind)/i;
const END_WORDS = /^(?:(?:please )?end (?:the |this )?(?:call|voice chat)|hang up|goodbye|bye(?: bye)?)(?: please| now)?[.!]*$/i;
// What a person says to show they are listening, not to take a turn: while the
// agent is talking or working it is let go, and the agent goes on.
const BACKCHANNEL = /^(?:(?:m+(?:-?h?m+)?|uh[- ]?huh|h+m+|ok(?:ay)?|yeah|yep|yup|right|sure|cool|alright|all right|i see|got it|uh+|um+|ah+|oh)[ ,.!?-]*)+$/i;
// What Whisper writes for a noise it could not hear as words: the captions of
// the videos it learned from, and sound tags.
const PHANTOMS = /^(?:thanks? (?:you )?for watching|please subscribe|subtitles? by|transcri(?:bed|ption) by|you)[ .!]*$/i;
const SOUND_TAGS = /\[[^\]]*\]|\((?:[a-z ]*(?:music|applause|laughter|silence|noise|inaudible|blank_audio)[a-z ]*)\)|[♪♫]+/gi;

// How long a finished turn waits for the person to go on before it is sent:
// a breath between two sentences is not the end of what they meant to say.
const HOLD_MS = 300;
// How long after the voice stops its echo may still come back as words.
const ECHO_TAIL_MS = 700;
// With the browser's recognition: how long a voice paused by the person waits
// for their words before it goes on, and how recently the echo-cancelled
// microphone must have heard them for words said over the voice to count.
const RESUME_WAIT_MS = 1800;
const HEARD_THEM_MS = 4000;
// A sent turn with no reply started after this is said to have had none.
const AWAIT_REPLY_MS = 8000;
const SETTINGS_PLACE = 'Settings → Voice';

/** Why speech-to-text cannot carry a call, from `/api/stt/stats`; '' when it can. */
export function hearingRefusal(stats, hasRecognition) {
  const provider = String((stats && stats.provider) || 'disabled');
  if (provider === 'disabled') {
    return `Voice chat needs speech-to-text. Choose one in ${SETTINGS_PLACE} → Speech to text.`;
  }
  if (provider === 'browser') {
    return hasRecognition ? '' : 'This browser has no speech recognition of its own. Choose local Whisper or '
      + `an endpoint in ${SETTINGS_PLACE} → Speech to text, or use Chrome, Edge or Safari.`;
  }
  if (stats && stats.available === false) {
    return String(stats.unavailable_reason || 'Speech-to-text is not available on this server.');
  }
  return '';
}

/** How replies will be said, from `/api/tts/stats`: `{ mode, note, setup }`. */
export function speakingPlan(stats, hasSynthesis) {
  const provider = String((stats && stats.provider) || 'disabled');
  if (provider === 'browser') {
    return hasSynthesis ? { mode: 'browser', note: '', setup: false }
      : { mode: 'none', note: 'This browser cannot speak, so replies are shown and not said.', setup: true };
  }
  if (provider === 'disabled' || (stats && stats.available === false && !stats.unavailable_reason)) {
    return { mode: 'none', note: `Replies are shown and not said: choose a voice in ${SETTINGS_PLACE}.`, setup: true };
  }
  if (stats && stats.available === false) return { mode: 'none', note: String(stats.unavailable_reason), setup: true };
  return { mode: 'server', note: '', setup: false };
}

/** What was heard, without the sound tags and phantom captions Whisper writes for a noise. */
export function cleanHeard(text) {
  const s = String(text || '').replace(SOUND_TAGS, ' ').replace(/\s+/g, ' ').trim();
  if (!/[\p{L}\p{N}]/u.test(s) || PHANTOMS.test(s)) return '';
  return s;
}

/** "mm-hmm", "okay", "right": listening, not taking a turn. */
export function isBackchannel(text) {
  return BACKCHANNEL.test(String(text || '').trim());
}

const WORD = /[\p{L}\p{N}']+/gu;
const words = (s) => String(s || '').toLowerCase().match(WORD) || [];

/**
 * Whether words heard while the agent was talking are its own voice come back
 * through the speakers: (nearly) all of them are words it was saying. A
 * command is never taken for an echo.
 */
export function isEcho(heard, spoken) {
  const h = words(heard);
  if (!h.length || STOP_WORDS.test(String(heard).trim()) || END_WORDS.test(String(heard).trim())) return false;
  const pool = new Set(words((spoken || []).join(' ')));
  if (!pool.size) return false;
  let inPool = 0;
  for (const w of h) if (pool.has(w)) inPool += 1;
  return h.length <= 2 ? inPool === h.length : inPool / h.length >= 0.8;
}

async function detailOf(res) {
  try {
    const body = await res.json();
    const d = body && body.detail;
    return String((d && (d.message || (typeof d === 'string' ? d : ''))) || body.message || '');
  } catch (_) {
    return '';
  }
}

/**
 * Speaks pieces in order. `server`: each piece is synthesized
 * (`POST /api/tts/synthesize`) two ahead of the one playing, and played on the
 * one audio element the call unlocked. `browser`: `speechSynthesis`, one
 * utterance a piece. `none`: says nothing and is never busy.
 */
export class CallSpeaker {
  constructor({ mode, fetchImpl, player, synth, Utterance, onBusy, onPiece, onFailure, createUrl, revokeUrl,
                voiceName, rate }) {
    this.mode = mode;
    this.fetch = fetchImpl;
    this.player = player;
    this.synth = synth;
    this.Utterance = Utterance;
    // The browser's own voice, as Settings → Voice chose it: a speaker by
    // name and a speed. This server's voices are told by the server.
    this.voiceName = String(voiceName || '').trim().toLowerCase();
    this.rate = Number(rate) > 0 ? Math.min(2, Math.max(0.5, Number(rate))) : 1;
    this.onBusy = onBusy || (() => {});
    this.onPiece = onPiece || (() => {});
    this.onFailure = onFailure || (() => {});
    this.createUrl = createUrl || ((blob) => URL.createObjectURL(blob));
    this.revokeUrl = revokeUrl || ((url) => { try { URL.revokeObjectURL(url); } catch (_) { /* gone */ } });
    this.queue = [];
    this.playing = null;
    this.paused = false;
    this.ducked = false;
    this.generation = 0;
    this.failures = 0;
    this.silenced = false;
    this._busy = false;
    if (this.mode === 'server' && !this.player) this.mode = 'none';
    if (this.mode === 'browser' && !(this.synth && this.Utterance)) this.mode = 'none';
    // Chrome lists its voices only after it is first asked for them.
    if (this.mode === 'browser' && this.voiceName) { try { this.synth.getVoices(); } catch (_) { /* none */ } }
  }

  get busy() { return this.mode !== 'none' && !this.silenced && (!!this.playing || this.queue.length > 0); }

  _setBusy() {
    const busy = this.busy;
    if (busy !== this._busy) { this._busy = busy; this.onBusy(busy); }
  }

  enqueue(pieces) {
    if (this.mode === 'none' || this.silenced) return;
    for (const text of pieces || []) if (text && String(text).trim()) this.queue.push({ text: String(text).trim() });
    this._prefetch();
    this._next();
    this._setBusy();
  }

  _prefetch() {
    if (this.mode !== 'server') return;
    for (const item of this.queue.slice(0, 2)) {
      if (item.audio) continue;
      const gen = this.generation;
      item.controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
      item.audio = Promise.resolve().then(() => this.fetch('/api/tts/synthesize', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: item.text, format: 'audio' }),
        signal: item.controller ? item.controller.signal : undefined,
      })).then(async (res) => {
        if (!res.ok) return { error: (await detailOf(res)) || `the server answered ${res.status}` };
        const blob = await res.blob();
        if (gen !== this.generation) return { error: '' };
        return { url: this.createUrl(blob) };
      }).catch((e) => ({ error: e && e.name === 'AbortError' ? '' : String((e && e.message) || e) }));
    }
  }

  async _next() {
    if (this.playing || this.paused || !this.queue.length) { this._setBusy(); return; }
    const item = this.queue[0];
    const gen = this.generation;
    this.playing = item;
    if (this.mode === 'browser') {
      this._sayInBrowser(item, gen);
      return;
    }
    const got = await item.audio;
    if (gen !== this.generation || this.playing !== item) return;
    if (!got || !got.url) {
      this.queue.shift();
      this.playing = null;
      if (got && got.error) this._failed(got.error);
      this._prefetch();
      this._next();
      return;
    }
    item.url = got.url;
    item.done = () => {
      if (gen !== this.generation || this.playing !== item) return;
      this.revokeUrl(item.url);
      this.queue.shift();
      this.playing = null;
      this._prefetch();
      this._next();
    };
    this.player.onended = () => {
      // Said to the end: the failures before it were a hiccup.
      if (gen === this.generation && this.playing === item) this.failures = 0;
      item.done();
    };
    this.player.onerror = () => {
      if (gen !== this.generation || this.playing !== item) return;
      this._failed('the audio would not play');
      item.done();
    };
    this.player.src = item.url;
    this.player.volume = this.ducked ? 0.25 : 1;
    this.onPiece(item.text);
    // Paused while the sound was on its way: `resume` plays it.
    if (!this.paused) this._play(item, gen);
    this._setBusy();
  }

  _play(item, gen) {
    try {
      const played = this.player.play();
      if (played && played.catch) {
        played.catch((e) => {
          // A pause or a stop that lands before playback starts rejects the
          // promise too; that is not the audio failing.
          if ((e && e.name === 'AbortError') || gen !== this.generation || this.playing !== item || this.paused) return;
          this._failed(e && e.name === 'NotAllowedError'
            ? 'the browser would not play sound on this page' : String((e && e.message) || e));
          if (item.done) item.done();
        });
      }
    } catch (e) {
      this._failed(String((e && e.message) || e));
      if (item.done) item.done();
    }
  }

  _browserVoice() {
    if (!this.voiceName || !this.synth || typeof this.synth.getVoices !== 'function') return null;
    let voices = [];
    try { voices = this.synth.getVoices() || []; } catch (_) { return null; }
    const named = (v) => String((v && v.name) || '').toLowerCase();
    return voices.find((v) => named(v) === this.voiceName) || voices.find((v) => named(v).includes(this.voiceName)) || null;
  }

  _sayInBrowser(item, gen) {
    const u = new this.Utterance(item.text);
    if (this.rate !== 1) u.rate = this.rate;
    const voice = this._browserVoice();
    if (voice) u.voice = voice;
    // Held while it is said: Chrome never ends an utterance nothing holds.
    item.utterance = u;
    const done = () => {
      if (gen !== this.generation || this.playing !== item) return;
      this.queue.shift();
      this.playing = null;
      this._next();
    };
    u.onend = () => {
      if (gen === this.generation && this.playing === item) this.failures = 0;
      done();
    };
    u.onerror = (e) => {
      const why = e && e.error;
      if (gen === this.generation && why && why !== 'interrupted' && why !== 'canceled') {
        this._failed(`the browser’s voice failed (${why})`);
      }
      done();
    };
    this.onPiece(item.text);
    // A pause the browser kept through a stop would hold this one too.
    if (this.synth.paused) { try { this.synth.resume(); } catch (_) { /* gone */ } }
    this.synth.speak(u);
    this._setBusy();
  }

  _failed(why) {
    this.failures += 1;
    // Twice in a row is not a hiccup: the rest of the call goes on in text,
    // said once, rather than failing again on every sentence.
    if (this.failures >= 2) {
      this.silenced = true;
      this.stop();
      this.onFailure(`Replies are shown and not said: ${why}.`, true);
    } else {
      this.onFailure(`A sentence was not said: ${why}.`, false);
    }
  }

  /** Quieter while the person may be starting to talk. */
  duck(on) {
    this.ducked = !!on;
    if (this.mode === 'server' && this.player) this.player.volume = on ? 0.25 : 1;
  }

  /** Held, to be resumed if what interrupted was not words. */
  pause() {
    if (!this.busy || this.paused) return false;
    this.paused = true;
    if (this.mode === 'server' && this.playing && this.playing.url) { try { this.player.pause(); } catch (_) { /* gone */ } }
    if (this.mode === 'browser') { try { this.synth.pause(); } catch (_) { /* gone */ } }
    this._setBusy();
    return true;
  }

  resume() {
    if (!this.paused) return;
    this.paused = false;
    this.duck(false);
    const item = this.playing;
    if (this.mode === 'server' && item && item.url) this._play(item, this.generation);
    else if (this.mode === 'browser' && item) { try { this.synth.resume(); } catch (_) { /* gone */ } }
    else if (!item) this._next();
    this._setBusy();
  }

  /** Everything queued or playing, dropped. */
  stop() {
    this.generation += 1;
    for (const item of this.queue) {
      if (item.controller) { try { item.controller.abort(); } catch (_) { /* gone */ } }
      if (item.url) this.revokeUrl(item.url);
      else if (item.audio && item.audio.then) item.audio.then((got) => { if (got && got.url) this.revokeUrl(got.url); });
    }
    this.queue = [];
    this.playing = null;
    this.paused = false;
    if (this.mode === 'server' && this.player) {
      this.player.onended = null;
      this.player.onerror = null;
      try { this.player.pause(); this.player.removeAttribute('src'); this.player.load(); } catch (_) { /* gone */ }
    }
    if (this.mode === 'browser' && this.synth) { try { this.synth.cancel(); } catch (_) { /* gone */ } }
    this._setBusy();
  }
}

/**
 * The browser's own recognition (Chrome, Edge, Safari), for a call whose
 * speech-to-text is the browser's: it ends a turn itself, and is started
 * again whenever it stops while the call is on.
 */
class BrowserHearing {
  constructor(Recognition, { lang, onWords, onFailure, timers }) {
    this.Recognition = Recognition;
    this.lang = lang || '';
    this.onWords = onWords;
    this.onFailure = onFailure;
    this.T = timers;
    this.on = false;
    this.rec = null;
    this.paused = false;
  }

  start() {
    this.on = true;
    this._open();
  }

  _open() {
    if (!this.on || this.paused || this.rec) return;
    const rec = new this.Recognition();
    rec.continuous = true;
    rec.interimResults = false;
    if (this.lang) rec.lang = this.lang;
    rec.onresult = (event) => {
      if (this.rec !== rec) return;
      for (let i = event.resultIndex; i < event.results.length; i++) {
        if (event.results[i].isFinal) {
          const said = String(event.results[i][0].transcript || '').trim();
          if (said) this.onWords(said);
        }
      }
    };
    rec.onerror = (e) => {
      const code = String((e && e.error) || '');
      if (code === 'not-allowed' || code === 'service-not-allowed' || code === 'audio-capture') {
        this.on = false;
        this.onFailure(code);
      }
    };
    rec.onend = () => {
      if (this.rec === rec) this.rec = null;
      if (this.on && !this.paused) this.T.setTimeout(() => this._open(), 250);
    };
    this.rec = rec;
    try { rec.start(); } catch (_) { /* already started */ }
  }

  setPaused(on) {
    if (this.paused === !!on) return;
    this.paused = !!on;
    if (this.paused && this.rec) {
      const rec = this.rec;
      this.rec = null;
      try { rec.abort(); } catch (_) { /* gone */ }
    }
    if (!this.paused) this._open();
  }

  stop() {
    this.on = false;
    const rec = this.rec;
    this.rec = null;
    if (rec) { try { rec.abort(); } catch (_) { /* gone */ } }
  }
}

/**
 * One voice chat. `deps`:
 *   chat     { sendTurn(text) → 'sent'|'queued'|false, queueTurn(text) → bool,
 *              stopReply(), isBusy(), sessionId(),
 *              canSteer() → bool, steerTurn(text) → Promise<'steered'|'queued'|false> }
 *   fetch    the page's fetch
 *   render   (view) → draws the bar; view is
 *            { on, phase, words, caption, note, setup, muted, level, speaking }
 *   events   an EventTarget for `pantheon:reply` (window)
 *   media    { Capture, Detector, Audio, synth, Utterance, Recognition, createUrl, revokeUrl }
 *   timers   { setTimeout, clearTimeout, setInterval, clearInterval }
 *   now      () → milliseconds
 *   onEnd    (reason, { setup }) → after the call ends
 */
export function createVoiceCall(deps) {
  const chat = deps.chat;
  const fetchImpl = deps.fetch;
  const render = deps.render || (() => {});
  const events = deps.events;
  const media = deps.media || {};
  // The page's own timers, each called as itself: `T.setTimeout(…)` on the
  // bare functions runs them with `T` as `this`, which Chrome refuses
  // ("Illegal invocation") on the first word a call hears.
  const T = deps.timers || {
    setTimeout: (fn, ms) => setTimeout(fn, ms),
    clearTimeout: (id) => clearTimeout(id),
    setInterval: (fn, ms) => setInterval(fn, ms),
    clearInterval: (id) => clearInterval(id),
  };
  const now = deps.now || (() => Date.now());

  const call = {
    on: false,
    phase: 'listening',
    muted: false,
    caption: '',
    note: '',
    setup: false,
    level: 0,
    sessionId: '',
    bargeIn: true,
    awaitingReply: false,
    awaitTimer: null,
    replyMuted: false,
    replyDone: true,
    held: '',
    holdTimer: null,
    pendingHearing: 0,
    bargedIn: false,
    resumeTimer: null,
    hearingMode: 'server',
    speaker: null,
    capture: null,
    detector: null,
    hearing: null,
    chunker: new SpeechChunker(),
    roundText: '',
    loadingPoll: null,
    seq: 0,
    delivered: 0,
    results: new Map(),
    aborts: new Set(),
    steers: [],          // turns sent as steers that the run has not read yet
    spoken: [],          // the last pieces said, for the echo check
    speakerIdleAt: -Infinity,
    confirmedAt: -Infinity,
    onsetOverVoice: false,
    halfDuplexHeld: false,
  };

  const speaking = () => !!(call.speaker && call.speaker.busy);
  const audible = () => speaking() && !call.speaker.paused;

  function view() {
    const phase = call.muted && call.phase === 'listening' ? 'muted' : call.phase;
    return {
      on: call.on,
      phase,
      words: PHASE_WORDS[phase] || '',
      caption: call.caption,
      note: call.note,
      setup: call.setup,
      muted: call.muted,
      // The meter is the person's microphone: still while it is not listening.
      level: call.muted || phase === 'waiting' ? 0 : call.level,
      speaking: speaking(),
    };
  }
  const draw = () => render(view());

  function setNote(note, setup = false) {
    call.note = note || '';
    call.setup = !!(note && setup);
  }

  /** Where the call is, from what is happening to it. */
  function settle() {
    if (!call.on) return;
    let phase;
    if (call.phase === 'waiting' || call.phase === 'starting') phase = call.phase;
    else if (call.bargedIn) phase = 'hearing';
    else if (audible()) phase = 'speaking';
    else if (!call.muted && call.detector && call.detector.state === 'speech') phase = 'hearing';
    else if (call.pendingHearing > 0 || call.held) phase = 'hearing';
    else if (call.awaitingReply || (!call.replyDone && chat.isBusy())) phase = 'thinking';
    else phase = 'listening';
    call.phase = phase;
    // While the agent talks, what is left of its echo is quiet speech too:
    // louder and longer before it is the person.
    if (call.detector) call.detector.setStrict(speaking());
    draw();
  }

  function syncHearing() {
    if (!call.hearing) return;
    call.hearing.setPaused(call.muted || call.phase === 'waiting' || (!call.bargeIn && speaking()));
  }

  function clearHold() {
    if (call.holdTimer) { T.clearTimeout(call.holdTimer); call.holdTimer = null; }
  }

  /** What was heard goes once the person has stopped and nothing is still being heard. */
  function armHold() {
    clearHold();
    if (!call.on || !call.held) return;
    if ((call.detector && call.detector.state === 'speech') || call.pendingHearing > 0) return;
    call.holdTimer = T.setTimeout(sendHeld, HOLD_MS);
  }

  function resumeVoice() {
    if (call.resumeTimer) { T.clearTimeout(call.resumeTimer); call.resumeTimer = null; }
    if (!call.bargedIn) return;
    call.bargedIn = false;
    if (call.speaker) call.speaker.resume();
  }

  function remember(text) {
    call.spoken.push(text);
    if (call.spoken.length > 3) call.spoken.shift();
  }

  // ── hearing ──

  function onFrame(rms, pcm) {
    if (!call.on) return;
    const level = Math.max(0, Math.min(1, (20 * Math.log10(Math.max(rms || 0, 1e-5)) + 60) / 50));
    call.level = call.level * 0.6 + level * 0.4;
    if (call.muted || call.phase === 'waiting' || call.phase === 'starting' || !call.detector) return;
    if (!call.bargeIn && speaking()) {
      // Taking turns: not listening while the agent talks.
      call.halfDuplexHeld = true;
      return;
    }
    if (call.halfDuplexHeld) { call.halfDuplexHeld = false; call.detector.reset(); }
    const ev = call.detector.push(rms, pcm);
    if (!ev) return;
    if (ev.type === 'onset') {
      call.onsetOverVoice = speaking();
      if (call.onsetOverVoice) call.speaker.duck(true);
      clearHold();
      settle();
    } else if (ev.type === 'confirmed') {
      call.confirmedAt = now();
      if (speaking() && !call.bargedIn) call.bargedIn = call.speaker.pause();
      settle();
    } else if (ev.type === 'discard') {
      if (call.speaker) call.speaker.duck(false);
      resumeVoice();
      armHold();
      settle();
    } else if (ev.type === 'utterance') {
      if (call.speaker) call.speaker.duck(false);
      if (call.hearingMode === 'server') {
        transcribe(ev.samples, call.onsetOverVoice);
      } else if (call.bargedIn) {
        // The browser's words come on their own clock; the voice waits a
        // little for them and goes on if none come.
        if (call.resumeTimer) T.clearTimeout(call.resumeTimer);
        call.resumeTimer = T.setTimeout(() => { call.resumeTimer = null; resumeVoice(); settle(); }, RESUME_WAIT_MS);
      }
      settle();
    }
  }

  function transcribe(samples, overVoice) {
    const n = ++call.seq;
    call.pendingHearing += 1;
    const wav = encodeWav(samples);
    const form = new FormData();
    form.append('file', new Blob([wav], { type: 'audio/wav' }), 'voice-turn.wav');
    const controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
    if (controller) call.aborts.add(controller);
    Promise.resolve().then(() => fetchImpl('/api/stt/transcribe', {
      method: 'POST', credentials: 'same-origin', body: form,
      signal: controller ? controller.signal : undefined,
    })).then(async (res) => {
      if (res.ok) {
        const data = await res.json().catch(() => ({}));
        return { text: String((data && data.text) || '').trim() };
      }
      return { error: (await detailOf(res)) || `Speech-to-text answered ${res.status}.`, status: res.status };
    }).catch((e) => ({ error: e && e.name === 'AbortError' ? null : `Speech-to-text could not be reached (${(e && e.message) || e}).` }))
      .then((got) => {
        if (controller) call.aborts.delete(controller);
        if (!call.on) return;
        call.results.set(n, { ...got, overVoice });
        // Turns are heard in the order they were said, whichever answer
        // comes back first.
        while (call.results.has(call.delivered + 1)) {
          const next = call.results.get(call.delivered + 1);
          call.results.delete(call.delivered + 1);
          call.delivered += 1;
          call.pendingHearing = Math.max(0, call.pendingHearing - 1);
          heardBack(next);
        }
      });
  }

  function heardBack(got) {
    if (!call.on || !got || got.error === null) return;
    if (got.error) {
      if (got.status === 503) { end(got.error, { setup: true }); return; }
      setNote(`That was not heard: ${got.error}`);
      resumeVoice();
      armHold();
      settle();
      return;
    }
    heard(got.text, { overVoice: got.overVoice });
  }

  function heard(raw, { overVoice = false } = {}) {
    if (!call.on) return;
    const text = cleanHeard(raw);
    const nearVoice = overVoice || speaking() || now() - call.speakerIdleAt < ECHO_TAIL_MS;
    const letGo = !text
      || (nearVoice && isEcho(text, call.spoken))
      || ((speaking() || call.awaitingReply || (!call.replyDone && chat.isBusy())) && isBackchannel(text));
    if (letGo) {
      // Not a turn after all: the voice goes on from where it paused.
      resumeVoice();
      armHold();
      settle();
      return;
    }
    if (call.bargedIn || speaking()) {
      // The person spoke over the reply: the rest of it is not said.
      if (call.resumeTimer) { T.clearTimeout(call.resumeTimer); call.resumeTimer = null; }
      call.bargedIn = false;
      call.speaker.stop();
      call.replyMuted = true;
    }
    setNote('');
    call.held = call.held ? `${call.held} ${text}` : text;
    call.caption = call.held;
    armHold();
    settle();
  }

  function watchForReply() {
    if (call.awaitTimer) T.clearTimeout(call.awaitTimer);
    const check = () => {
      call.awaitTimer = null;
      if (!call.on || !call.awaitingReply) return;
      if (chat.isBusy()) { call.awaitTimer = T.setTimeout(check, AWAIT_REPLY_MS); return; }
      call.awaitingReply = false;
      setNote('No reply came. The chat says why.');
      settle();
    };
    call.awaitTimer = T.setTimeout(check, AWAIT_REPLY_MS);
  }

  async function sendHeld() {
    call.holdTimer = null;
    if (!call.on) return;
    if ((call.detector && call.detector.state === 'speech') || call.pendingHearing > 0) return;
    const text = call.held.trim();
    call.held = '';
    if (!text) { settle(); return; }
    if (END_WORDS.test(text)) { end('Voice chat ended.'); return; }
    if (STOP_WORDS.test(text)) {
      if (call.speaker) call.speaker.stop();
      call.replyMuted = true;
      if (STOP_REPLY.test(text) && chat.isBusy()) {
        call.steers = [];
        chat.stopReply();
      }
      call.caption = '';
      settle();
      return;
    }
    call.caption = text;
    call.awaitingReply = true;
    settle();
    let sent = false;
    try {
      if (chat.isBusy()) {
        if (chat.canSteer && chat.canSteer()) {
          sent = await chat.steerTurn(text);
        } else {
          // A reply that cannot take a correction is stopped, as talking
          // over someone stops them, and what was said goes next.
          chat.stopReply();
          sent = chat.queueTurn(text) ? 'queued' : false;
        }
      } else {
        sent = chat.sendTurn(text);
      }
    } catch (_) {
      sent = false;
    }
    if (!call.on) return;
    if (!sent) {
      call.awaitingReply = false;
      setNote('That could not be sent to this chat.');
      settle();
      return;
    }
    if (sent === 'steered') {
      // The run in flight reads it at its next step; its reply is the answer.
      call.steers.push(text);
      call.awaitingReply = false;
      settle();
      return;
    }
    watchForReply();
  }

  /** Steers the run ended before reading go as the next message instead. */
  function resendSteers() {
    if (!call.steers.length) return;
    const text = call.steers.splice(0).join(' ');
    const sent = chat.sendTurn(text);
    if (sent) {
      call.awaitingReply = true;
      watchForReply();
    } else {
      setNote('What you said while it worked did not reach it. Say it again.');
    }
  }

  // ── the reply ──

  function say(pieces) {
    if (call.speaker && pieces && pieces.length) call.speaker.enqueue(pieces);
  }

  function onReply(event) {
    if (!call.on) return;
    const d = (event && event.detail) || {};
    const current = chat.sessionId ? chat.sessionId() : '';
    if (d.sessionId && current && d.sessionId !== current) return;
    if (d.phase === 'start') {
      if (!call.sessionId && d.sessionId) call.sessionId = d.sessionId;
      call.chunker.reset();
      call.roundText = '';
      call.replyMuted = false;
      call.replyDone = false;
      call.awaitingReply = false;
      if (call.awaitTimer) { T.clearTimeout(call.awaitTimer); call.awaitTimer = null; }
      if (call.phase === 'waiting') {
        call.phase = 'thinking';
        setNote('');
        syncHearing();
      }
      settle();
    } else if (d.phase === 'text') {
      call.roundText = d.text || '';
      if (!call.replyMuted) say(call.chunker.push(call.roundText));
    } else if (d.phase === 'round') {
      if (!call.replyMuted) say(call.chunker.finish(call.roundText));
      call.chunker.reset();
      call.roundText = '';
    } else if (d.phase === 'steered') {
      call.steers.splice(0, Math.max(1, Number(d.count) || 1));
      // The run has the correction, so what it says from here answers it;
      // what it had already written before is not said. (A steer is read
      // as a step starts, so that is normally nothing.)
      call.chunker.reset();
      if (call.roundText) call.chunker.finish(call.roundText);
      call.replyMuted = false;
      settle();
    } else if (d.phase === 'end') {
      const last = typeof d.text === 'string' && d.text ? d.text : call.roundText;
      if (!call.replyMuted) say(call.chunker.finish(last));
      call.chunker.reset();
      call.roundText = '';
      call.replyDone = true;
      resendSteers();
      if (call.awaitingReply) watchForReply();
      settle();
    } else if (d.phase === 'stop') {
      call.replyDone = true;
      resendSteers();
      if (call.awaitingReply) watchForReply();
      settle();
    } else if (d.phase === 'ask') {
      const options = (d.options || []).map((o) => String(o || '').trim()).filter(Boolean);
      if (!call.replyMuted) say(call.chunker.finish(call.roundText));
      call.chunker.reset();
      call.roundText = '';
      call.replyDone = true;
      call.awaitingReply = false;
      // What the agent says after it asks is the card's stand-in, not words.
      call.replyMuted = true;
      if (d.kind === 'tool_approval') {
        // An approval is given on the card, never by voice: a word misheard
        // must not run a command. The call waits, not listening, until the
        // card is answered.
        say(['I need your approval in the chat to go on.']);
        call.phase = 'waiting';
        setNote('Approve or deny on the card in the chat. The call goes on after.');
        syncHearing();
        settle();
      } else {
        if (d.question) {
          const choices = options.length > 1
            ? ` You can say ${options.slice(0, -1).join(', ')} or ${options[options.length - 1]}.` : '';
          say(new SpeechChunker().finish(d.question + choices));
        }
        settle();
      }
    }
  }

  /** The approval card was answered: the run goes on, and so does the call. */
  function approvalAnswered() {
    if (!call.on || call.phase !== 'waiting') return;
    call.phase = 'thinking';
    setNote('');
    call.awaitingReply = true;
    syncHearing();
    watchForReply();
    settle();
  }

  // ── start and end ──

  async function getJson(url) {
    const res = await fetchImpl(url, { credentials: 'same-origin' });
    if (!res.ok) throw new Error((await detailOf(res)) || `${url} answered ${res.status}`);
    return res.json();
  }

  async function start() {
    if (call.on) return true;
    Object.assign(call, {
      on: true, phase: 'starting', caption: '', muted: false, held: '', bargedIn: false,
      seq: 0, delivered: 0, pendingHearing: 0, steers: [], spoken: [], awaitingReply: false,
      replyMuted: false, speakerIdleAt: -Infinity, confirmedAt: -Infinity, halfDuplexHeld: false,
    });
    setNote('');
    call.results.clear();
    call.chunker.reset();
    call.sessionId = chat.sessionId ? chat.sessionId() : '';
    // The audio element is unlocked now, inside the click that started the
    // call, before anything is awaited (Safari counts the gesture as gone
    // after the first await).
    const player = media.Audio ? new media.Audio() : null;
    if (player) {
      try {
        player.src = SILENT_WAV;
        const p = player.play();
        if (p && p.catch) p.catch(() => {});
      } catch (_) { /* nothing to unlock */ }
    }
    draw();
    let stt;
    let tts;
    try {
      [stt, tts] = await Promise.all([getJson('/api/stt/stats'), getJson('/api/tts/stats')]);
    } catch (e) {
      end(`Voice chat could not ask this server about speech (${(e && e.message) || e}).`);
      return false;
    }
    if (!call.on) return false;
    const voice = (stt && stt.voice_chat) || {};
    if (voice.enabled === false) { end(`Voice chat is turned off in ${SETTINGS_PLACE}.`, { setup: true }); return false; }
    const refusal = hearingRefusal(stt, !!media.Recognition);
    if (refusal) { end(refusal, { setup: true }); return false; }
    call.hearingMode = stt.provider === 'browser' ? 'browser' : 'server';
    const plan = speakingPlan(tts, !!(media.synth && media.Utterance));
    setNote(plan.note, plan.setup);
    call.bargeIn = voice.barge_in !== false;
    call.speaker = new CallSpeaker({
      mode: plan.mode,
      fetchImpl,
      player,
      synth: media.synth,
      Utterance: media.Utterance,
      voiceName: tts && tts.voice,
      rate: tts && tts.speed,
      createUrl: media.createUrl,
      revokeUrl: media.revokeUrl,
      onBusy: (busy) => {
        if (!busy) {
          call.speakerIdleAt = now();
          if (!call.bargeIn && call.detector) call.detector.reset();
        }
        syncHearing();
        settle();
      },
      onPiece: (text) => { remember(text); call.caption = text; draw(); },
      onFailure: (sentence, silenced) => { setNote(sentence, silenced); draw(); },
    });
    const Detector = media.Detector || TurnDetector;
    call.detector = new Detector({ endSilenceMs: PAUSES[voice.pause] || PAUSES.normal });
    const Capture = media.Capture || VoiceCapture;
    const capture = new Capture({
      onFrame,
      onEnded: (why) => { if (call.on && call.capture === capture) end(why); },
    });
    call.capture = capture;
    try {
      await capture.start();
    } catch (e) {
      // What it opened before it failed is closed (the browser's microphone
      // light goes off), then the call says why.
      try { capture.stop(); } catch (_) { /* gone */ }
      if (call.capture === capture) call.capture = null;
      end(String((e && e.message) || e));
      return false;
    }
    if (!call.on || call.capture !== capture) {
      // Ended while the browser was still asking for the microphone.
      try { capture.stop(); } catch (_) { /* gone */ }
      return false;
    }
    if (call.hearingMode === 'browser') {
      call.hearing = new BrowserHearing(media.Recognition, {
        lang: String(stt.language || ''),
        timers: T,
        onWords: (said) => {
          if (!call.on || call.muted || call.phase === 'waiting') return;
          // The browser's recognition is not echo-cancelled the way the
          // microphone is: words it hears while the agent talks count only
          // when the microphone heard the person too.
          const nearVoice = speaking() || now() - call.speakerIdleAt < ECHO_TAIL_MS;
          if (nearVoice && now() - call.confirmedAt > HEARD_THEM_MS) return;
          heard(said, { overVoice: nearVoice });
        },
        onFailure: (code) => end(code === 'audio-capture'
          ? 'The browser’s speech recognition could not hear the microphone.'
          : 'The browser would not let this page use its speech recognition.'),
      });
      call.hearing.start();
    }
    if (call.hearingMode === 'server' && stt.provider === 'local' && !stt.model_loaded) {
      if (!call.note) setNote('Loading the speech model. Your first turn waits for it.');
      call.loadingPoll = T.setInterval(async () => {
        try {
          const latest = await getJson('/api/stt/stats');
          if (!call.on) return;
          if (latest.model_loaded || latest.unavailable_reason) {
            T.clearInterval(call.loadingPoll);
            call.loadingPoll = null;
            if (latest.unavailable_reason) { end(String(latest.unavailable_reason), { setup: true }); return; }
            if (call.note.startsWith('Loading the speech model')) { setNote(plan.note, plan.setup); draw(); }
          }
        } catch (_) { /* asked again on the next tick */ }
      }, 2000);
    }
    if (events) events.addEventListener('pantheon:reply', onReply);
    call.replyDone = !chat.isBusy();
    call.phase = 'listening';
    settle();
    return true;
  }

  function end(reason, { setup = false } = {}) {
    if (!call.on) return;
    call.on = false;
    clearHold();
    for (const t of ['awaitTimer', 'resumeTimer']) if (call[t]) { T.clearTimeout(call[t]); call[t] = null; }
    if (call.loadingPoll) { T.clearInterval(call.loadingPoll); call.loadingPoll = null; }
    for (const c of call.aborts) { try { c.abort(); } catch (_) { /* gone */ } }
    call.aborts.clear();
    if (call.hearing) { call.hearing.stop(); call.hearing = null; }
    if (call.capture) { try { call.capture.stop(); } catch (_) { /* gone */ } call.capture = null; }
    if (call.speaker) call.speaker.stop();
    if (events) events.removeEventListener('pantheon:reply', onReply);
    call.bargedIn = false;
    call.held = '';
    call.steers = [];
    setNote(reason || '', setup);
    draw();
    if (deps.onEnd) deps.onEnd(reason || '', { setup: !!setup });
  }

  function toggleMute() {
    if (!call.on) return;
    call.muted = !call.muted;
    if (call.detector) call.detector.reset();
    if (call.speaker) call.speaker.duck(false);
    resumeVoice();
    syncHearing();
    settle();
  }

  /** The voice, stopped now; the reply goes on in text. */
  function interrupt() {
    if (!call.on || !call.speaker) return;
    if (call.resumeTimer) { T.clearTimeout(call.resumeTimer); call.resumeTimer = null; }
    call.bargedIn = false;
    call.speaker.stop();
    call.replyMuted = true;
    settle();
  }

  /** The chat on screen changed: a call belongs to the chat it started in. */
  function sessionChanged(id) {
    if (!call.on) return;
    if (!call.sessionId) { call.sessionId = id || ''; return; }
    if (id && id !== call.sessionId) end('Voice chat ended: another chat was opened.');
  }

  return {
    start, end, toggleMute, interrupt, sessionChanged, approvalAnswered,
    get active() { return call.on; },
    get state() { return view(); },
    // for the tests
    _call: call, _onReply: onReply, _onFrame: onFrame, _heard: heard,
  };
}

// ── the page ──

const MIC_SVG = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="2.5" width="6" height="12" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0"/><path d="M12 17.5V21"/></svg>';
const MIC_OFF_SVG = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 9.3V5.5a3 3 0 0 0-5.7-1.3"/><path d="M9 9v2.5a3 3 0 0 0 4.6 2.5"/><path d="M18.5 11a6.5 6.5 0 0 1-1 3.5M5.5 11a6.5 6.5 0 0 0 10.2 5.3"/><path d="M12 17.5V21"/><path d="M3.5 3.5l17 17"/></svg>';

let _call = null;

function _el(id) { return document.getElementById(id); }

function _renderBar(v) {
  const bar = _el('voice-call-bar');
  const btn = _el('composer-call-btn');
  if (btn) {
    btn.setAttribute('aria-pressed', String(!!v.on));
    if (v.on) btn.dataset.phase = v.phase; else delete btn.dataset.phase;
    const title = v.on ? 'End voice chat' : 'Voice chat';
    if (btn.title !== title) { btn.title = title; btn.setAttribute('aria-label', title); }
  }
  if (!bar) return;
  bar.hidden = !v.on;
  if (!v.on) return;
  bar.dataset.phase = v.phase;
  const state = _el('voice-call-state');
  if (state && state.textContent !== v.words) state.textContent = v.words;
  const caption = _el('voice-call-caption');
  const line = v.note || v.caption || '';
  if (caption && caption.textContent !== line) {
    caption.textContent = line;
    caption.title = line;
  }
  if (caption) caption.classList.toggle('is-note', !!v.note);
  const setup = _el('voice-call-setup');
  // Settings → Voice is an admin's page.
  if (setup) setup.hidden = !v.setup || window._isAdmin !== true;
  const mute = _el('voice-call-mute');
  if (mute) {
    mute.setAttribute('aria-pressed', String(!!v.muted));
    const title = v.muted ? 'Unmute' : 'Mute';
    if (mute.title !== title) { mute.title = title; mute.setAttribute('aria-label', title); }
    const icon = v.muted ? 'off' : 'on';
    if (mute.dataset.icon !== icon) { mute.innerHTML = v.muted ? MIC_OFF_SVG : MIC_SVG; mute.dataset.icon = icon; }
  }
  const skip = _el('voice-call-skip');
  if (skip) skip.hidden = !v.speaking;
  bar.style.setProperty('--vc-level', String(Math.round(v.level * 100) / 100));
}

let _openSettings = null;

function _openVoiceSettings() {
  try { if (_openSettings) _openSettings('voice'); } catch (_) { /* no settings here */ }
}

/** `true` while a voice chat is on in this page. */
export function isVoiceCallActive() {
  return !!(_call && _call.active);
}

export function toggleVoiceCall() {
  if (!_call) return;
  if (_call.active) _call.end('Voice chat ended.');
  else _call.start();
}

/**
 * Wires the call to the page: the composer's call button, the bar's mute,
 * skip, set-up and end buttons, the chat (`chat.js`'s spoken-turn exports and
 * `chatStream.js`'s steer, passed in by `app.js` so this module imports
 * neither), and the toast that says why a call ended when it was not the
 * person who ended it.
 */
export function initVoiceCall({ chatModule, sessionModule, showToast, steer, openSettings, beforeStart } = {}) {
  if (_call || typeof window === 'undefined' || !chatModule) return _call;
  _openSettings = openSettings || null;
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition || null;
  const sessionId = () => (sessionModule && sessionModule.getCurrentSessionId && sessionModule.getCurrentSessionId()) || '';
  let levelTimer = null;
  let wakeLock = null;
  _call = createVoiceCall({
    fetch: window.fetch.bind(window),
    events: window,
    render: _renderBar,
    chat: {
      sendTurn: (text) => chatModule.sendSpokenTurn(text),
      queueTurn: (text) => chatModule.queueSpokenTurn(text),
      stopReply: () => chatModule.stopCurrentReply(),
      isBusy: () => chatModule.isReplyRunning(),
      sessionId,
      canSteer: () => !!(steer && steer.canSteerNow && steer.canSteerNow()),
      steerTurn: async (text) => (steer && steer.submitSteer
        ? steer.submitSteer(text, { spoken: true })
        : (chatModule.queueSpokenTurn(text) ? 'queued' : false)),
    },
    media: {
      Audio: window.Audio,
      synth: window.speechSynthesis || null,
      Utterance: window.SpeechSynthesisUtterance || null,
      Recognition,
    },
    onEnd: (reason, { setup } = {}) => {
      window.__pantheonVoiceCall = false;
      if (levelTimer) { clearInterval(levelTimer); levelTimer = null; }
      if (wakeLock) { try { wakeLock.release(); } catch (_) { /* gone */ } wakeLock = null; }
      if (!reason || reason === 'Voice chat ended.' || !showToast) return;
      if (setup && window._isAdmin === true) {
        showToast(reason, { duration: 9000, action: 'Voice settings', onAction: _openVoiceSettings });
      } else {
        showToast(reason, { duration: 7000 });
      }
    },
  });
  const start = _call.start;
  _call.start = async () => {
    // Dictation lets go of the microphone first (what it heard goes in the box).
    try { if (beforeStart) beforeStart(); } catch (_) { /* nothing to let go of */ }
    window.__pantheonVoiceCall = true;
    // The meter is drawn ten times a second rather than on every frame.
    if (!levelTimer) levelTimer = setInterval(() => { if (_call.active) _renderBar(_call.state); }, 100);
    const ok = await start();
    if (!ok) { window.__pantheonVoiceCall = false; return ok; }
    // A phone's screen going dark stops the microphone with it.
    try {
      if (navigator.wakeLock && navigator.wakeLock.request) {
        navigator.wakeLock.request('screen').then((lock) => {
          if (_call.active) wakeLock = lock; else lock.release();
        }).catch(() => {});
      }
    } catch (_) { /* no wake lock here */ }
    return ok;
  };
  const btn = _el('composer-call-btn');
  if (btn) btn.addEventListener('click', (e) => { e.preventDefault(); toggleVoiceCall(); });
  // Shown while voice chat is on in Settings → Voice: to an admin before
  // speech-to-text is set up too (a press says where), to a member once it
  // is. `voiceRecorder.js` reads the settings and says them here.
  window.addEventListener('pantheon:voice-settings', (e) => {
    const s = (e && e.detail) || {};
    const on = !s.voice_chat || s.voice_chat.enabled !== false;
    const hears = !!s.provider && s.provider !== 'disabled';
    if (btn && !_call.active) btn.hidden = !(on && (hears || s.is_admin !== false));
  });
  const mute = _el('voice-call-mute');
  if (mute) mute.addEventListener('click', () => _call.toggleMute());
  const skip = _el('voice-call-skip');
  if (skip) skip.addEventListener('click', () => _call.interrupt());
  const setup = _el('voice-call-setup');
  if (setup) setup.addEventListener('click', _openVoiceSettings);
  const endBtn = _el('voice-call-end');
  if (endBtn) endBtn.addEventListener('click', () => _call.end('Voice chat ended.'));
  document.addEventListener('pantheon:session-changed', (e) => _call.sessionChanged(e && e.detail && e.detail.sessionId));
  document.addEventListener('pantheon:tool-approval', () => _call.approvalAnswered());
  window.addEventListener('pagehide', () => { if (_call.active) _call.end('Voice chat ended.'); });
  window.voiceCallModule = { toggle: toggleVoiceCall, isActive: isVoiceCallActive };
  return _call;
}

export default { initVoiceCall, toggleVoiceCall, isVoiceCallActive, createVoiceCall };
