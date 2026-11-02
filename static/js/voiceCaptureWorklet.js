// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/voiceCaptureWorklet.js

/**
 * `B1718`. The microphone for a voice chat, on the audio thread.
 *
 * Whatever rate the device records at (48 kHz, 44.1 kHz) becomes 16 kHz mono,
 * the rate Whisper and every `/audio/transcriptions` take, and goes to the
 * page in 20 ms frames of 320 samples with each frame's loudness (RMS). The
 * page decides what is speech (`TurnDetector` in `voiceCapture.js`); this only
 * listens. On the audio thread because a timer on the page is slowed to once
 * a second in a background tab, and a call goes on while the person looks at
 * another one.
 *
 * Each output sample is the mean of the input samples it stands for: a box
 * filter, the plainest low-pass there is, so what is above 8 kHz is damped
 * before it can fold down into the speech band. `voiceCapture.js` carries the
 * same loop for a browser with no AudioWorklet (`ScriptProcessorNode`).
 */

const TARGET_RATE = 16000;
const FRAME = 320;

class PantheonVoiceCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this._ratio = sampleRate / TARGET_RATE;
    this._t = 0;
    this._acc = 0;
    this._accN = 0;
    this._frame = new Float32Array(FRAME);
    this._n = 0;
    this._on = true;
    this.port.onmessage = (event) => {
      if (event.data && event.data.type === 'stop') this._on = false;
    };
  }

  _emit(sample) {
    this._frame[this._n++] = sample;
    if (this._n < FRAME) return;
    let sum = 0;
    for (let i = 0; i < FRAME; i++) sum += this._frame[i] * this._frame[i];
    const pcm = this._frame;
    this._frame = new Float32Array(FRAME);
    this._n = 0;
    this.port.postMessage({ rms: Math.sqrt(sum / FRAME), pcm }, [pcm.buffer]);
  }

  process(inputs, outputs) {
    const input = inputs[0];
    const channel = input && input[0];
    if (channel) {
      for (let i = 0; i < channel.length; i++) {
        this._acc += channel[i];
        this._accN += 1;
        this._t += 1;
        if (this._t >= this._ratio) {
          this._t -= this._ratio;
          this._emit(this._acc / this._accN);
          this._acc = 0;
          this._accN = 0;
        }
      }
    }
    // Silence out: the node is wired to the speakers through a muted gain so
    // that every browser keeps pulling it, and nothing should be heard.
    const out = outputs[0];
    if (out) for (const ch of out) ch.fill(0);
    return this._on;
  }
}

registerProcessor('pantheon-voice-capture', PantheonVoiceCapture);
