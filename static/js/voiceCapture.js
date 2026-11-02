// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/voiceCapture.js

/**
 * `B1718`. Hearing a person in a voice chat: the microphone, turn detection,
 * and the recording of one turn as a WAV file.
 *
 * `VoiceCapture` opens the microphone with the browser's echo cancellation,
 * noise suppression and gain control on — the echo canceller is what lets the
 * agent's own voice, coming out of the speakers, not be heard as the person
 * talking — and hands 20 ms frames at 16 kHz to whoever listens
 * (`voiceCaptureWorklet.js`).
 *
 * `TurnDetector` decides, frame by frame, when the person started talking and
 * when they finished. It learns the room's own noise first, then calls a frame
 * speech when it is well above that floor, and the turn over when it has been
 * back near the floor for the pause the person chose in Settings. A sound too
 * short to be words (a click, a cough) is let go, and so is one too steady to
 * be words (a fan or a heater switched on: speech rises and falls between
 * syllables, a fan does not), whose level becomes the room's. While the agent
 * is speaking it asks for louder and longer speech before it calls it the
 * person (`strict`), because what is left of the echo is quiet speech too.
 * Pure, so `tests/test_voice_turns_*` drive it with frames under node.
 *
 * `encodeWav` writes a turn as 16-bit PCM WAV, which every speech-to-text this
 * server can use reads, and which `sniff_audio_format` names honestly.
 */

export const CAPTURE_RATE = 16000;
export const FRAME_SAMPLES = 320;
export const FRAME_MS = 20;

/** Loudness in dBFS, floored so silence is a number. */
export function levelDb(rms) {
  return 20 * Math.log10(Math.max(Number(rms) || 0, 1e-5));
}

/** A turn as WAV bytes: mono, 16-bit, little-endian. */
export function encodeWav(samples, rate = CAPTURE_RATE) {
  const count = samples ? samples.length : 0;
  const buffer = new ArrayBuffer(44 + count * 2);
  const view = new DataView(buffer);
  const text = (at, s) => { for (let i = 0; i < s.length; i++) view.setUint8(at + i, s.charCodeAt(i)); };
  text(0, 'RIFF');
  view.setUint32(4, 36 + count * 2, true);
  text(8, 'WAVE');
  text(12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);          // PCM
  view.setUint16(22, 1, true);          // mono
  view.setUint32(24, rate, true);
  view.setUint32(28, rate * 2, true);   // bytes a second
  view.setUint16(32, 2, true);          // bytes a frame
  view.setUint16(34, 16, true);         // bits a sample
  text(36, 'data');
  view.setUint32(40, count * 2, true);
  for (let i = 0; i < count; i++) {
    const v = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(44 + i * 2, v < 0 ? v * 0x8000 : v * 0x7fff, true);
  }
  return new Uint8Array(buffer);
}

/** How long a pause ends a turn, by the Settings choice (`voice_chat_pause`). */
export const PAUSES = Object.freeze({ short: 550, normal: 850, relaxed: 1400 });

function concat(frames) {
  let total = 0;
  for (const f of frames) total += f.length;
  const out = new Float32Array(total);
  let at = 0;
  for (const f of frames) { out.set(f, at); at += f.length; }
  return out;
}

/**
 * Frame by frame: `push(rms, pcm)` answers `null` or one event —
 *   `{ type: 'onset' }`      the person may be talking (the agent's voice ducks)
 *   `{ type: 'confirmed' }`  they are: long and loud enough to be words
 *   `{ type: 'utterance', samples }`  their turn, ended by the pause
 *   `{ type: 'discard' }`    it was a sound, not words
 */
export class TurnDetector {
  constructor({
    frameMs = FRAME_MS,
    calibrateMs = 400,
    endSilenceMs = PAUSES.normal,
    minSpeechMs = 260,
    maxTurnMs = 45000,
    preRollMs = 320,
    tailMs = 240,
    startOverNoise = 11,
    stayOverNoise = 6,
    floorDb = -54,
    strictExtraDb = 9,
    strictMinSpeechMs = 420,
    steadyAfterMs = 3000,
    steadyWindowMs = 2000,
    steadyRangeDb = 6,
  } = {}) {
    this.frameMs = frameMs;
    this.calibrateFrames = Math.round(calibrateMs / frameMs);
    this.endSilenceFrames = Math.max(1, Math.round(endSilenceMs / frameMs));
    this.minSpeechFrames = Math.max(1, Math.round(minSpeechMs / frameMs));
    this.maxTurnFrames = Math.round(maxTurnMs / frameMs);
    this.preRollFrames = Math.round(preRollMs / frameMs);
    this.tailFrames = Math.round(tailMs / frameMs);
    this.startOverNoise = startOverNoise;
    this.stayOverNoise = stayOverNoise;
    this.floorDb = floorDb;
    this.strictExtraDb = strictExtraDb;
    this.strictMinSpeechFrames = Math.max(1, Math.round(strictMinSpeechMs / frameMs));
    this.steadyAfterFrames = Math.round(steadyAfterMs / frameMs);
    this.steadyWindowFrames = Math.max(2, Math.round(steadyWindowMs / frameMs));
    this.steadyRangeDb = steadyRangeDb;
    this.strict = false;
    this.reset();
  }

  /** Back to listening for a new turn; the noise floor is kept. */
  reset() {
    this.state = this.noise === undefined ? 'calibrating' : 'silence';
    if (this.noise === undefined) this._calibration = [];
    this._pre = [];
    this._turn = [];
    this._levels = [];
    this._onset = 0;
    this._voiced = 0;
    this._quiet = 0;
    this._confirmed = false;
  }

  setPause(ms) { this.endSilenceFrames = Math.max(1, Math.round(ms / this.frameMs)); }

  /** While the agent speaks: louder and longer before it is the person. */
  setStrict(on) { this.strict = !!on; }

  get noiseDb() { return this.noise; }

  _startDb() {
    return Math.max(this.floorDb, this.noise + this.startOverNoise) + (this.strict ? this.strictExtraDb : 0);
  }

  _stayDb() { return Math.max(this.floorDb - 4, this.noise + this.stayOverNoise); }

  push(rms, pcm) {
    const db = levelDb(rms);
    const frame = pcm || new Float32Array(0);
    if (this.state === 'calibrating') {
      this._calibration.push(db);
      this._pre.push(frame);
      if (this._pre.length > this.preRollFrames) this._pre.shift();
      if (this._calibration.length >= this.calibrateFrames) {
        // The quieter third of what was heard: a word said while the room
        // was being learned does not become the room.
        const sorted = this._calibration.slice().sort((a, b) => a - b);
        this.noise = Math.max(-90, Math.min(-30, sorted[Math.floor(sorted.length / 3)]));
        this._calibration = null;
        this.state = 'silence';
      }
      return null;
    }
    if (this.state === 'silence') {
      // The floor falls quickly and rises slowly, so a door shutting does not
      // raise it and a fan switched on is learned within a few seconds.
      this.noise += (db - this.noise) * (db < this.noise ? 0.08 : 0.004);
      this.noise = Math.max(-90, Math.min(-30, this.noise));
      this._pre.push(frame);
      if (this._pre.length > this.preRollFrames) this._pre.shift();
      if (db > this._startDb()) {
        this._onset += 1;
        const onsetNeeded = this.strict ? 5 : 3;
        if (this._onset >= onsetNeeded) {
          this.state = 'speech';
          this._turn = this._pre.slice();
          this._pre = [];
          this._levels = [];
          this._voiced = this._onset;
          this._quiet = 0;
          this._confirmed = false;
          return { type: 'onset' };
        }
      } else {
        this._onset = 0;
      }
      return null;
    }
    // speech
    this._turn.push(frame);
    this._levels.push(db);
    if (this._levels.length > this.steadyWindowFrames) this._levels.shift();
    if (this._turn.length >= this.steadyAfterFrames && this._levels.length >= this.steadyWindowFrames) {
      let lo = Infinity;
      let hi = -Infinity;
      for (const l of this._levels) { if (l < lo) lo = l; if (l > hi) hi = l; }
      if (hi - lo < this.steadyRangeDb) {
        // Too even to be someone talking: the room got louder. Its level
        // is the floor from now on, and this was never a turn.
        this.noise = Math.max(-90, Math.min(-30, (hi + lo) / 2));
        this._endTurn();
        return { type: 'discard' };
      }
    }
    if (db > this._startDb()) this._voiced += 1;
    if (db > this._stayDb()) this._quiet = 0;
    else this._quiet += 1;
    const needed = this.strict ? this.strictMinSpeechFrames : this.minSpeechFrames;
    if (!this._confirmed && this._voiced >= needed) {
      this._confirmed = true;
      return { type: 'confirmed' };
    }
    if (this._quiet >= this.endSilenceFrames || this._turn.length >= this.maxTurnFrames) {
      const confirmed = this._confirmed;
      const keep = this._turn.length - Math.max(0, this._quiet - this.tailFrames);
      const samples = concat(this._turn.slice(0, keep));
      this._endTurn();
      return confirmed ? { type: 'utterance', samples } : { type: 'discard' };
    }
    return null;
  }

  _endTurn() {
    this.state = 'silence';
    this._turn = [];
    this._levels = [];
    this._onset = 0;
    this._voiced = 0;
    this._quiet = 0;
    this._confirmed = false;
  }
}

/** The same box-filter decimation as the worklet, for `ScriptProcessorNode`. */
class Decimator {
  constructor(rate, onFrame) {
    this.ratio = rate / CAPTURE_RATE;
    this.t = 0; this.acc = 0; this.accN = 0;
    this.frame = new Float32Array(FRAME_SAMPLES); this.n = 0;
    this.onFrame = onFrame;
  }

  feed(channel) {
    for (let i = 0; i < channel.length; i++) {
      this.acc += channel[i]; this.accN += 1; this.t += 1;
      if (this.t < this.ratio) continue;
      this.t -= this.ratio;
      this.frame[this.n++] = this.acc / this.accN;
      this.acc = 0; this.accN = 0;
      if (this.n < FRAME_SAMPLES) continue;
      let sum = 0;
      for (let k = 0; k < FRAME_SAMPLES; k++) sum += this.frame[k] * this.frame[k];
      const pcm = this.frame;
      this.frame = new Float32Array(FRAME_SAMPLES); this.n = 0;
      this.onFrame(Math.sqrt(sum / FRAME_SAMPLES), pcm);
    }
  }
}

/** Why the microphone could not be opened, as a sentence. */
export function microphoneRefusal(error) {
  const name = error && error.name;
  if (name === 'NotAllowedError' || name === 'SecurityError') {
    return 'The browser would not let this page use the microphone. Allow it for this site and try again.';
  }
  if (name === 'NotFoundError' || name === 'OverconstrainedError') return 'No microphone was found.';
  if (name === 'NotReadableError' || name === 'AbortError') {
    return 'The microphone is in use by another program, or the system would not open it.';
  }
  return 'The microphone could not be opened' + (error && error.message ? ` (${error.message})` : '') + '.';
}

/**
 * The microphone, as 20 ms frames: `new VoiceCapture({ onFrame, onEnded })`,
 * `await start()` (throws with `microphoneRefusal`'s sentence), `stop()`.
 */
export class VoiceCapture {
  constructor({ onFrame, onEnded, workletUrl = '/static/js/voiceCaptureWorklet.js' } = {}) {
    this.onFrame = onFrame || (() => {});
    this.onEnded = onEnded || (() => {});
    this.workletUrl = workletUrl;
    this.stream = null;
    this.ctx = null;
    this.nodes = [];
    this.stopped = false;
  }

  async start() {
    if (typeof window !== 'undefined' && !window.isSecureContext) {
      throw new Error('The microphone needs a secure page: open Pantheon over HTTPS or on localhost.');
    }
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      throw new Error('This browser cannot use a microphone.');
    }
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
      });
    } catch (e) {
      throw new Error(microphoneRefusal(e));
    }
    // Stopped while the browser asked: what it gave is let go at once.
    if (this.stopped) { this.stop(); return; }
    const track = this.stream.getAudioTracks()[0];
    if (track) track.addEventListener('ended', () => this.onEnded('The microphone stopped.'));
    const Ctx = window.AudioContext || window.webkitAudioContext;
    this.ctx = new Ctx({ latencyHint: 'interactive' });
    const source = this.ctx.createMediaStreamSource(this.stream);
    const sink = this.ctx.createGain();
    sink.gain.value = 0;
    sink.connect(this.ctx.destination);
    let node = null;
    if (this.ctx.audioWorklet && typeof AudioWorkletNode !== 'undefined') {
      try {
        await this.ctx.audioWorklet.addModule(this.workletUrl);
        node = new AudioWorkletNode(this.ctx, 'pantheon-voice-capture', {
          numberOfInputs: 1, numberOfOutputs: 1, outputChannelCount: [1],
        });
        node.port.onmessage = (event) => {
          const d = event.data || {};
          this.onFrame(d.rms, d.pcm);
        };
      } catch (e) {
        console.warn('Voice capture worklet unavailable, using the script processor:', e);
        node = null;
      }
    }
    if (!node) {
      // Safari before 14.1 and anything else without AudioWorklet.
      const decimator = new Decimator(this.ctx.sampleRate, (rms, pcm) => this.onFrame(rms, pcm));
      node = this.ctx.createScriptProcessor(2048, 1, 1);
      node.onaudioprocess = (event) => decimator.feed(event.inputBuffer.getChannelData(0));
    }
    if (this.stopped) { this.stop(); return; }
    source.connect(node);
    node.connect(sink);
    this.nodes = [source, node, sink];
    if (this.ctx.state === 'suspended') {
      // A context the browser will not start yet answers `resume()` only once
      // it may: not forever on "Starting."
      await Promise.race([this.ctx.resume(), new Promise((r) => setTimeout(r, 4000))]);
      if (this.stopped) { this.stop(); return; }
      if (this.ctx && this.ctx.state === 'suspended') {
        throw new Error('The browser would not let this page listen yet. Press the call button again.');
      }
    }
  }

  stop() {
    this.stopped = true;
    for (const n of this.nodes) {
      try { if (n.port) n.port.postMessage({ type: 'stop' }); } catch (_) { /* gone */ }
      try { n.disconnect(); } catch (_) { /* gone */ }
    }
    this.nodes = [];
    if (this.stream) this.stream.getTracks().forEach((t) => { try { t.stop(); } catch (_) { /* gone */ } });
    this.stream = null;
    if (this.ctx) { try { this.ctx.close(); } catch (_) { /* gone */ } }
    this.ctx = null;
  }
}

export default { VoiceCapture, TurnDetector, encodeWav, levelDb, PAUSES, microphoneRefusal };
