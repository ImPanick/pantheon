// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/voiceRecorder.js

/**
 * Voice recording with optional Speech-to-Text transcription.
 *
 * STT providers:
 *   "disabled"       — record audio as file attachment (original behavior)
 *   "browser"        — use Web Speech API for real-time transcription
 *   "local"          — send recording to server /api/stt/transcribe (Whisper)
 *   "endpoint:<id>"  — send recording to server /api/stt/transcribe (API)
 *
 * `B1718`. Dictation has its own button beside Send (`#composer-mic-btn`,
 * wired by `initDictation`), shown while a provider is chosen in
 * Settings → Voice. `refreshSttProvider` is the composer's one read of
 * `/api/stt/stats`; it answers it to the page as `pantheon:voice-settings`,
 * which the voice chat's button follows too (`voiceCall.js`).
 */

import { getAuthStatus } from './appConfig.js';

let mediaRecorder = null;
let audioChunks = [];
let isRecording = false;
// `B1718`. Asked for the microphone and not yet answered (a permission prompt
// can stay up for as long as the person leaves it), and stopped before it was.
let _starting = false;
let _cancelStart = false;
let recordingStartTime = null;
let recordingInterval = null;

// Browser STT state
let _recognition = null;
let _browserTranscript = '';
// `B1564`. Why the browser's recognition gave no words (its `error` code), and
// the promise of its `end`, which is when the last words have arrived.
let _recognitionError = '';
let _recognitionEnded = null;

// Cached STT provider — refreshed on settings change
let _sttProvider = 'disabled';
// `B1564`. The language set in Settings → Voice; blank is the browser's own.
let _sttLanguage = '';
// `B1718`. The dictation button and what it calls, once `initDictation` ran.
let _micBtn = null;
let _dictation = null;
// `B1726`. What was said is being written out (the server's Whisper, or the
// browser's last words after its `stop()`): the microphone is closed, and the
// words are not in the box yet.
let _transcribing = false;

/**
 * `B1726`. What dictation is doing, said in the message box itself. The owner,
 * 2026-11-01: *"When the "Transcribing" is on - and listening, the textbox
 * needs to say so.. When the voice is being processed and transfered into
 * text - it needs to also say "Transcribing . . ." so the user doesn't think
 * it's hanging/crashing."* An empty box says it where its prompt is; a box
 * with words in it says it in a pill beside them (`#dictation-status`). The
 * dots step while it lasts, and stand still under reduced motion.
 */
export const DICTATION_WORDS = Object.freeze({ listening: 'Listening', transcribing: 'Transcribing' });
export const DICTATION_DOTS = Object.freeze(['.', '. .', '. . .']);
const DOT_MS = 420;
const FULL = DICTATION_DOTS.length - 1;

/** `B1726`. The words for `state` at dot `step` ("Transcribing . . ."), or '' when dictation is idle. */
export function dictationWords(state, step = FULL) {
  const word = DICTATION_WORDS[state];
  if (!word) return '';
  const n = DICTATION_DOTS.length;
  return `${word} ${DICTATION_DOTS[((Math.trunc(Number(step)) || 0) % n + n) % n]}`;
}

let _boxState = '';
let _boxPrompt = null;   // the box's own prompt, given back when dictation ends
let _boxInput = null;
let _dot = FULL;
let _dotTimer = null;

function _stillDots() {
  try {
    return !!(typeof window !== 'undefined' && window.matchMedia
      && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  } catch (_) {
    return false;   // as `motion.js` answers a webview whose matchMedia throws
  }
}

/** `B1726`. The box's prompt and the pill, as dictation stands now. */
function _drawBoxState() {
  const input = _boxInput;
  const pill = typeof document !== 'undefined' ? document.getElementById('dictation-status') : null;
  if (input && _boxState) input.setAttribute('placeholder', dictationWords(_boxState, _dot));
  if (!pill) return;
  // A prompt shows only while the box is empty; once it has words, the pill says it.
  const show = !!_boxState && !!(input && input.value);
  if (show) {
    pill.dataset.state = _boxState;
    const word = pill.querySelector('.dictation-status-word');
    const dots = pill.querySelector('.dictation-status-dots');
    if (word) word.textContent = DICTATION_WORDS[_boxState];
    if (dots) dots.textContent = DICTATION_DOTS[_dot];
  } else {
    delete pill.dataset.state;
  }
  if (pill.hidden === show) pill.hidden = !show;
}

/** `B1726`. Dictation is `listening`, `transcribing`, or idle (''); the box says which. */
function _setBoxState(state) {
  const next = DICTATION_WORDS[state] ? state : '';
  if (next === _boxState) return;
  const input = typeof document !== 'undefined' ? document.getElementById('message') : null;
  if (next && !_boxState && input) {
    _boxInput = input;
    _boxPrompt = input.getAttribute('placeholder');
    // Words typed while it lasts move the saying from the prompt to the pill.
    input.addEventListener('input', _drawBoxState);
  }
  _boxState = next;
  if (_dotTimer) { clearInterval(_dotTimer); _dotTimer = null; }
  if (next) {
    if (_boxInput) _boxInput.dataset.dictation = next;
    _dot = _stillDots() ? FULL : 0;
    // Drawn again on a beat: the dots step (held still while reduced motion
    // is asked for, read each time, as `motion.js` reads it), and a box a
    // script emptied with no `input` (a message sent) shows its prompt again.
    _dotTimer = setInterval(() => {
      _dot = _stillDots() ? FULL : (_dot + 1) % DICTATION_DOTS.length;
      _drawBoxState();
    }, DOT_MS);
    _drawBoxState();
  } else if (_boxInput) {
    const box = _boxInput;
    box.removeEventListener('input', _drawBoxState);
    delete box.dataset.dictation;
    if (_boxPrompt === null) box.removeAttribute('placeholder');
    else box.setAttribute('placeholder', _boxPrompt);
    _boxInput = null;
    _boxPrompt = null;
    _drawBoxState();
  }
  // `app.js` keeps the box's own prompt to its width, and waits while this says it.
  try {
    if (typeof window !== 'undefined' && typeof CustomEvent !== 'undefined') {
      window.dispatchEvent(new CustomEvent('pantheon:dictation', { detail: { state: next } }));
    }
  } catch (_) { /* a listener that throws is its own problem */ }
}

/**
 * `B1564`. The browser's own speech recognition (the Web Speech API), or
 * `null` in a browser that has none — Firefox, for one. Chrome's sends the
 * audio to Google, which the Settings card says beside the choice.
 */
export function browserSpeechRecognition(win = (typeof window !== 'undefined' ? window : null)) {
  if (!win) return null;
  return win.SpeechRecognition || win.webkitSpeechRecognition || null;
}

/** `B1564`. Said where the browser provider is chosen and this browser has
 *  no recognition (the Settings card), and when a recording is started in one. */
export const NO_BROWSER_SPEECH = 'This browser has no speech recognition of its own, '
  + 'so a recording is attached to the message as a sound file instead.';

/**
 * `B1564`. Why the browser's recognition gave no words, as a sentence, or ''
 * when the reason is only that nothing was said (`no-speech`, `aborted`).
 * The codes are the Web Speech API's `SpeechRecognitionErrorEvent.error`.
 */
export function browserSpeechRefusal(code) {
  switch (code) {
    case 'not-allowed':
    case 'service-not-allowed':
      return 'The browser would not let this page use its speech recognition. '
        + 'Check its microphone and speech settings for this site.';
    case 'network':
      return 'The browser’s speech recognition could not reach its service (in Chrome, Google’s).';
    case 'audio-capture':
      return 'The browser’s speech recognition could not hear the microphone.';
    case 'language-not-supported':
      return 'The browser’s speech recognition does not know the language set in Settings → Voice.';
    default:
      return '';
  }
}

/**
 * `B1718`. The kinds of recording a browser can make, in the order asked for:
 * Chrome and Firefox make WebM (Opus), Safari makes MP4 (AAC). The server
 * reads what a recording is from its bytes (`sniff_audio_format`), so any of
 * them is heard; '' leaves the choice to the browser.
 */
const RECORDING_TYPES = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus', 'audio/ogg'];

export function recordingType(Recorder = (typeof MediaRecorder !== 'undefined' ? MediaRecorder : null)) {
  if (!Recorder || typeof Recorder.isTypeSupported !== 'function') return '';
  return RECORDING_TYPES.find((t) => {
    try { return Recorder.isTypeSupported(t); } catch (_) { return false; }
  }) || '';
}

/** `B1718`. The file name a recording of `type` is sent and attached under. */
export function recordingExtension(type) {
  const t = String(type || '');
  if (/mp4|aac|m4a/.test(t)) return 'm4a';
  if (/ogg/.test(t)) return 'ogg';
  if (/wav/.test(t)) return 'wav';
  return 'webm';
}

/**
 * Fetch current STT provider from server settings
 */
async function refreshSttProvider() {
  try {
    const res = await fetch('/api/stt/stats', { credentials: 'same-origin' });
    if (res.ok) {
      const stats = await res.json();
      _sttProvider = stats.provider || 'disabled';
      _sttLanguage = String(stats.language || '');
      _syncMicButton();
      // Notify the send button to update its icon
      if (window._updateSendBtnIcon) window._updateSendBtnIcon();
      // `B1718`: and the voice chat's button, which an admin is shown before
      // speech-to-text is set up (it says where), and a member only once it is.
      let isAdmin = null;
      try { isAdmin = !!(await getAuthStatus()).is_admin; } catch (_) { /* unknown */ }
      try {
        window.dispatchEvent(new CustomEvent('pantheon:voice-settings', { detail: { ...stats, is_admin: isAdmin } }));
      } catch (_) { /* a listener that throws is its own problem */ }
    }
  } catch (e) {
    console.warn('Failed to fetch STT stats:', e);
  }
}

/** `B1718`. The dictation button: shown while a provider is chosen, pressed while recording. */
function _syncMicButton(state = isRecording ? 'recording' : '') {
  const btn = _micBtn || (typeof document !== 'undefined' ? document.getElementById('composer-mic-btn') : null);
  if (!btn) return;
  btn.hidden = !_sttProvider || _sttProvider === 'disabled';
  const recording = state === 'recording';
  btn.setAttribute('aria-pressed', String(recording));
  if (state === 'transcribing') btn.dataset.state = 'transcribing'; else delete btn.dataset.state;
  const title = recording ? 'Stop dictating' : (state === 'transcribing' ? 'Writing out what was said' : 'Dictate');
  if (btn.title !== title) { btn.title = title; btn.setAttribute('aria-label', title); }
}

/**
 * Format seconds as MM:SS
 */
function formatTime(seconds) {
  const mins = Math.floor(seconds / 60).toString().padStart(2, '0');
  const secs = (seconds % 60).toString().padStart(2, '0');
  return `${mins}:${secs}`;
}

/**
 * Reset UI state after recording ends
 */
function _resetRecordingUI() {
  isRecording = false;
  _transcribing = false;
  if (recordingInterval) {
    clearInterval(recordingInterval);
    recordingInterval = null;
  }
  _syncMicButton('');
  _setBoxState('');
  // Reset send button via global callback. `B1718`: only from its own
  // recording state; dictation from its own button can end while a reply
  // streams, and that Stop is not this module's to reset.
  const sendBtn = document.querySelector('.send-btn');
  if (sendBtn && (sendBtn.dataset.mode === 'recording' || sendBtn.classList.contains('recording'))) {
    sendBtn.classList.remove('recording');
    sendBtn.dataset.mode = '';
  }
  if (window._updateSendBtnIcon) {
    setTimeout(window._updateSendBtnIcon, 50);
  }
}

/**
 * Start browser speech recognition alongside recording. `false` when this
 * browser has none (`B1564`: it used to return without a word, and the
 * recording ended in "No speech detected").
 */
function startBrowserSTT() {
  const Recognition = browserSpeechRecognition();
  _browserTranscript = '';
  _recognitionError = '';
  _recognition = null;
  _recognitionEnded = null;
  if (!Recognition) return false;

  const recognition = new Recognition();
  recognition.continuous = true;
  recognition.interimResults = false;
  // `B1564`: the language Settings holds; blank is the page's, as it was.
  recognition.lang = _sttLanguage;

  let ended;
  _recognitionEnded = new Promise((resolve) => { ended = resolve; });
  recognition.onend = () => ended();

  recognition.onresult = (event) => {
    for (let i = event.resultIndex; i < event.results.length; i++) {
      if (event.results[i].isFinal) {
        _browserTranscript += event.results[i][0].transcript + ' ';
      }
    }
  };

  recognition.onerror = (e) => {
    _recognitionError = String((e && e.error) || '');
    console.warn('Browser STT error:', _recognitionError);
  };

  try {
    recognition.start();
  } catch (e) {
    _recognitionError = 'not-allowed';
    ended();
  }
  _recognition = recognition;
  return true;
}

/**
 * Stop the browser's recognition and answer what it heard. `B1564`: the last
 * words arrive after `stop()` — the final `result`, then `end` — and this read
 * the transcript the moment it asked, so a short recording came back empty
 * and was said as "No speech detected". It waits for `end` now, a few
 * seconds at most.
 */
async function stopBrowserSTT() {
  const recognition = _recognition;
  const ended = _recognitionEnded;
  _recognition = null;
  if (recognition) {
    try { recognition.stop(); } catch (e) { /* already stopped */ }
  }
  if (ended) await Promise.race([ended, new Promise((resolve) => setTimeout(resolve, 4000))]);
  return _browserTranscript.trim();
}

/**
 * Send audio to server for transcription
 */
async function transcribeOnServer(audioBlob) {
  const formData = new FormData();
  formData.append('file', audioBlob, `audio.${recordingExtension(audioBlob.type)}`);

  const res = await fetch('/api/stt/transcribe', {
    method: 'POST',
    credentials: 'same-origin',
    body: formData,
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail?.message || 'Transcription failed');
  }

  const data = await res.json();
  return data.text || '';
}

/**
 * Insert transcribed text into the chat input
 */
function insertTranscription(text, showToast) {
  if (!text) return;
  const input = document.getElementById('message');
  if (!input) return;

  const existing = input.value.trim();
  input.value = existing ? existing + ' ' + text : text;

  // Trigger auto-resize and icon update
  input.dispatchEvent(new Event('input', { bubbles: true }));
  input.focus();

  if (showToast) showToast('Transcribed');
}

/**
 * Start voice recording
 */
export function startRecording(onFileCreated, showToast, showError) {
  // Check for secure context (getUserMedia requires HTTPS or localhost)
  if (!window.isSecureContext) {
    if (showError) showError('Microphone requires HTTPS. Use a reverse proxy with SSL or access via localhost.');
    _resetRecordingUI();
    return;
  }

  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    if (showError) showError('Microphone not supported in this browser.');
    _resetRecordingUI();
    return;
  }

  // `B1718`: one recording at a time. A second press while the first waited
  // on the permission prompt opened a second microphone, and the first one's
  // never closed.
  if (_starting || isRecording) return;
  _starting = true;
  _cancelStart = false;
  audioChunks = [];
  let opened = null;

  navigator.mediaDevices.getUserMedia({ audio: true })
    .then(stream => {
      opened = stream;
      _starting = false;
      if (_cancelStart) {
        // Stopped while the browser asked: the microphone it gave is closed.
        _cancelStart = false;
        stream.getTracks().forEach(track => track.stop());
        _resetRecordingUI();
        return;
      }
      // `B1718`: a kind this browser makes. `audio/webm` was asked for by
      // name, which Safari refuses, and the refusal was "Microphone error".
      const asked = recordingType();
      mediaRecorder = asked ? new MediaRecorder(stream, { mimeType: asked }) : new MediaRecorder(stream);
      const type = mediaRecorder.mimeType || asked || 'audio/webm';
      const fileName = () => `voice-message-${Date.now()}.${recordingExtension(type)}`;

      mediaRecorder.ondataavailable = event => {
        if (event.data.size > 0) {
          audioChunks.push(event.data);
        }
      };

      mediaRecorder.onstop = async () => {
        stream.getTracks().forEach(track => track.stop());

        const audioBlob = new Blob(audioChunks, { type: type.split(';')[0] });
        const provider = _sttProvider;

        if (provider === 'browser') {
          const heard = _recognitionEnded !== null;   // this browser has recognition
          if (heard) {
            // `B1726`: its last words come after `stop()`, a few seconds at most.
            _transcribing = true;
            _syncMicButton('transcribing');
            _setBoxState('transcribing');
          }
          const transcript = await stopBrowserSTT();
          // `B1726`: the box is given back before the words go into it, so it
          // is measured for them as it will stand.
          _setBoxState('');
          if (transcript) {
            insertTranscription(transcript, showToast);
          } else {
            // `B1564`: why there are no words, when the browser said why;
            // a browser with no recognition was told at the start.
            const why = heard ? browserSpeechRefusal(_recognitionError) : '';
            if (why && showError) showError(why + ' The recording is attached instead.');
            else if (heard && showToast) showToast('No speech detected');
            const audioFile = new File([audioBlob], fileName(), { type: audioBlob.type });
            if (onFileCreated) onFileCreated(audioFile);
          }
        } else if (provider === 'local' || provider.startsWith('endpoint:')) {
          // Show "Transcribing..." feedback. `B1726`: and the box says
          // "Transcribing . . ." for as long as it takes, not the toast's 5 s.
          _transcribing = true;
          if (showToast) showToast('Transcribing...', 5000);
          _syncMicButton('transcribing');
          _setBoxState('transcribing');
          try {
            const transcript = await transcribeOnServer(audioBlob);
            _setBoxState('');
            if (transcript) {
              insertTranscription(transcript, showToast);
            } else {
              if (showToast) showToast('No speech detected');
            }
          } catch (e) {
            _setBoxState('');
            console.error('STT transcription error:', e);
            if (showError) showError('Transcription failed: ' + e.message);
            // Fallback: attach as file
            const audioFile = new File([audioBlob], fileName(), { type: audioBlob.type });
            if (onFileCreated) onFileCreated(audioFile);
          }
        } else {
          // STT disabled — attach audio file
          const audioFile = new File([audioBlob], fileName(), { type: audioBlob.type });
          if (onFileCreated) onFileCreated(audioFile);
        }

        _resetRecordingUI();
      };

      mediaRecorder.start();
      isRecording = true;
      recordingStartTime = new Date();
      _syncMicButton('recording');
      // `B1726`: once the microphone is really recording, not while the
      // browser still asks for it.
      _setBoxState('listening');

      // Start browser STT if that's the provider. `B1564`: in a browser with
      // none, said now, before anyone speaks to it — in place of
      // "Recording...", which would take the same toast from it.
      if (_sttProvider === 'browser' && !startBrowserSTT() && showError) {
        showError(NO_BROWSER_SPEECH);
      } else if (showToast) {
        showToast('Recording...');
      }
    })
    .catch(error => {
      _starting = false;
      _cancelStart = false;
      // `B1718`: a recorder that could not be made or started leaves the
      // microphone it was given open (the browser's light stays on).
      if (opened && !(mediaRecorder && mediaRecorder.state === 'recording')) {
        try { opened.getTracks().forEach(track => track.stop()); } catch (_) { /* gone */ }
      }
      console.error('Microphone access error:', error);
      if (showError) {
        if (error.name === 'NotAllowedError') {
          showError('Microphone access denied. Check browser permissions.');
        } else if (error.name === 'NotFoundError') {
          showError('No microphone found.');
        } else {
          showError('Microphone error: ' + error.message);
        }
      }
      _resetRecordingUI();
    });
}

/**
 * Stop voice recording
 */
export function stopRecording() {
  if (mediaRecorder && mediaRecorder.state === 'recording') {
    mediaRecorder.stop();
    // isRecording will be set to false in _resetRecordingUI called from onstop
  } else if (_transcribing) {
    // `B1726`: the microphone is already closed and the words are on their
    // way; a press now (the dictation button, Send) took "Transcribing . . ."
    // out of the box while they were, and they arrived anyway.
    return;
  } else {
    // `B1718`: still waiting on the browser; the microphone is closed when it answers.
    if (_starting) _cancelStart = true;
    _resetRecordingUI();
  }
}

/**
 * Check if currently recording
 */
export function getIsRecording() {
  // `B1718`: and while the browser is still asking for the microphone.
  return isRecording || _starting;
}

/**
 * Initialize recording state
 */
export function init() {
  isRecording = false;
  refreshSttProvider();
}

/**
 * `B1718`. The dictation button beside Send: a press starts a recording and
 * the next one stops it; what was said is written into the message box
 * (`insertTranscription`), or attached as a sound file when it could not be
 * heard. Not while a voice chat has the microphone (`isCallOn`).
 */
export function initDictation({ onFileCreated, showToast, showError, isCallOn } = {}) {
  const btn = typeof document !== 'undefined' ? document.getElementById('composer-mic-btn') : null;
  if (!btn || _micBtn === btn) return;
  _micBtn = btn;
  _dictation = { onFileCreated, showToast, showError, isCallOn };
  btn.addEventListener('click', (e) => {
    e.preventDefault();
    if (isRecording || _starting || (mediaRecorder && mediaRecorder.state === 'recording')) {
      stopRecording();
      return;
    }
    if (btn.dataset.state === 'transcribing') return;
    if (_dictation.isCallOn && _dictation.isCallOn()) {
      if (_dictation.showToast) _dictation.showToast('The voice chat has the microphone. End it to dictate.', 4000);
      return;
    }
    _syncMicButton('recording');
    startRecording(_dictation.onFileCreated, _dictation.showToast, _dictation.showError);
  });
  _syncMicButton();
}

const voiceRecorderModule = {
  startRecording,
  stopRecording,
  getIsRecording,
  init,
  initDictation,
  refreshSttProvider,
  get _sttProvider() { return _sttProvider; },
  set _sttProvider(v) { _sttProvider = v; },
};

export default voiceRecorderModule;
