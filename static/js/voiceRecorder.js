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
 */

let mediaRecorder = null;
let audioChunks = [];
let isRecording = false;
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
// `B1564`. The language set in Settings → AI Defaults; blank is the browser's own.
let _sttLanguage = '';

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
      return 'The browser’s speech recognition does not know the language set in Settings → AI Defaults.';
    default:
      return '';
  }
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
      // Notify the send button to update its icon
      if (window._updateSendBtnIcon) window._updateSendBtnIcon();
    }
  } catch (e) {
    console.warn('Failed to fetch STT stats:', e);
  }
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
  if (recordingInterval) {
    clearInterval(recordingInterval);
    recordingInterval = null;
  }
  // Reset send button via global callback
  const sendBtn = document.querySelector('.send-btn');
  if (sendBtn) {
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
  formData.append('file', audioBlob, 'audio.webm');

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

  audioChunks = [];

  navigator.mediaDevices.getUserMedia({ audio: true })
    .then(stream => {
      mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });

      mediaRecorder.ondataavailable = event => {
        if (event.data.size > 0) {
          audioChunks.push(event.data);
        }
      };

      mediaRecorder.onstop = async () => {
        stream.getTracks().forEach(track => track.stop());

        const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
        const provider = _sttProvider;

        if (provider === 'browser') {
          const heard = _recognitionEnded !== null;   // this browser has recognition
          const transcript = await stopBrowserSTT();
          if (transcript) {
            insertTranscription(transcript, showToast);
          } else {
            // `B1564`: why there are no words, when the browser said why;
            // a browser with no recognition was told at the start.
            const why = heard ? browserSpeechRefusal(_recognitionError) : '';
            if (why && showError) showError(why + ' The recording is attached instead.');
            else if (heard && showToast) showToast('No speech detected');
            const audioFile = new File([audioBlob], `voice-message-${Date.now()}.webm`, { type: 'audio/webm' });
            if (onFileCreated) onFileCreated(audioFile);
          }
        } else if (provider === 'local' || provider.startsWith('endpoint:')) {
          // Show "Transcribing..." feedback
          if (showToast) showToast('Transcribing...', 5000);
          try {
            const transcript = await transcribeOnServer(audioBlob);
            if (transcript) {
              insertTranscription(transcript, showToast);
            } else {
              if (showToast) showToast('No speech detected');
            }
          } catch (e) {
            console.error('STT transcription error:', e);
            if (showError) showError('Transcription failed: ' + e.message);
            // Fallback: attach as file
            const audioFile = new File([audioBlob], `voice-message-${Date.now()}.webm`, { type: 'audio/webm' });
            if (onFileCreated) onFileCreated(audioFile);
          }
        } else {
          // STT disabled — attach audio file
          const audioFile = new File([audioBlob], `voice-message-${Date.now()}.webm`, { type: 'audio/webm' });
          if (onFileCreated) onFileCreated(audioFile);
        }

        _resetRecordingUI();
      };

      mediaRecorder.start();
      isRecording = true;
      recordingStartTime = new Date();

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
  } else {
    _resetRecordingUI();
  }
}

/**
 * Check if currently recording
 */
export function getIsRecording() {
  return isRecording;
}

/**
 * Initialize recording state
 */
export function init() {
  isRecording = false;
  refreshSttProvider();
}

const voiceRecorderModule = {
  startRecording,
  stopRecording,
  getIsRecording,
  init,
  refreshSttProvider,
  get _sttProvider() { return _sttProvider; },
  set _sttProvider(v) { _sttProvider = v; },
};

export default voiceRecorderModule;
