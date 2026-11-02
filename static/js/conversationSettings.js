// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `B1730`. Settings → Conversation: each person's own switch for the agent
// saying its replies out loud, and the voice Pantheon speaks to them in.
//
// The owner, 2026-11-01: *"This should be a "Conversation" switch not speak
// replies aloud - we make it personal-able"*. Everything here is the
// person's: the switch is `conversation.js`'s (the composer's chip is the same
// one), and the voice is `PUT /api/prefs/conversation_voice` —
// `{engine, voice, speed}`, checked by `services/tts/personal_voice.py`, or
// `null` for the server's voice (Settings → Voice, an admin's). The voices
// on offer are `GET /api/tts/voices`: Kokoro on this server's processor,
// Chatterbox on its GPU when one runs it, Piper's voices on disk, and the
// voices of this device's own browser, which the page speaks with and the
// server never sees. "Hear it" says a sentence in what is chosen, before or
// after it is kept.

import { setConversation, conversationOn } from './conversation.js';

const $ = (id) => document.getElementById(id);
const PREVIEW = 'Hi, I’m ready when you are. This is how I’ll sound when we talk.';
const BROWSER = 'browser';
let _wired = false;
let _voices = null;      // `GET /api/tts/voices`
let _saved = null;       // `conversation_voice` as kept
let _audio = null;       // the preview playing, if any

function _say(text, { bad = false } = {}) {
  const out = $('conv-status');
  if (!out) return;
  out.textContent = text || '';
  out.classList.toggle('settings-voice-why', !!bad);
}

async function _json(url, opts) {
  const res = await fetch(url, { credentials: 'same-origin', ...(opts || {}) });
  let body = null;
  try { body = await res.json(); } catch (_) { body = null; }
  return { ok: res.ok, status: res.status, body };
}

function _option(value, text, { disabled = false } = {}) {
  const o = document.createElement('option');
  o.value = value;
  o.textContent = text;
  o.disabled = disabled;
  return o;
}

function _group(label) {
  const g = document.createElement('optgroup');
  g.label = label;
  return g;
}

function _browserVoices() {
  try {
    return (window.speechSynthesis && window.speechSynthesis.getVoices()) || [];
  } catch (_) {
    return [];
  }
}

/** The select's value for a kept voice: "" for the server's, else "engine:voice". */
export function valueOf(choice) {
  if (!choice || !choice.engine) return '';
  return `${choice.engine}:${choice.voice || ''}`;
}

/** The kept voice for a select value and a speed ("" is the voice's own). */
export function choiceOf(value, speed) {
  const sp = speed === '' || speed == null ? null : Number(speed);
  const s = String(value || '');
  if (!s) return sp == null ? null : { engine: '', voice: '', speed: sp };
  const i = s.indexOf(':');
  return { engine: i < 0 ? s : s.slice(0, i), voice: i < 0 ? '' : s.slice(i + 1), speed: sp };
}

/** Fill the voice select from what the server offers, grouped by engine and,
 *  for Kokoro, by language. */
export function drawVoices(select, voices, browserVoices = []) {
  select.textContent = '';
  const server = (voices && voices.server) || {};
  select.appendChild(_option('', server.available === false
    ? 'Pantheon’s voice (it cannot speak here yet)'
    : `Pantheon’s voice (${server.label || 'chosen by an admin'})`));
  for (const engine of (voices && voices.engines) || []) {
    const where = `${engine.name} · ${engine.where}`;
    if (!engine.available) {
      const g = _group(where);
      g.appendChild(_option(`${engine.id}:`, `${engine.name} is not running here`, { disabled: true }));
      select.appendChild(g);
      continue;
    }
    if (engine.id === 'kokoro') {
      const byLanguage = new Map();
      for (const v of engine.voices || []) {
        if (!byLanguage.has(v.language)) byLanguage.set(v.language, []);
        byLanguage.get(v.language).push(v);
      }
      for (const [language, list] of byLanguage) {
        const g = _group(`${engine.name} · ${language}`);
        // The whole label ("Emma · British English, woman"): a closed select
        // shows the option alone, without its group's name.
        list.forEach((v) => g.appendChild(_option(`kokoro:${v.id}`, v.label)));
        select.appendChild(g);
      }
      continue;
    }
    const g = _group(where);
    (engine.voices || []).forEach((v) => g.appendChild(_option(`${engine.id}:${v.id}`, v.label || v.id)));
    if (!(engine.voices || []).length) g.appendChild(_option(`${engine.id}:`, `${engine.name}’s own`));
    select.appendChild(g);
  }
  if (browserVoices.length) {
    const g = _group('This device’s voices');
    browserVoices.forEach((v) => g.appendChild(_option(`${BROWSER}:${v.name}`, v.name + (v.localService === false ? ' (online)' : ''))));
    select.appendChild(g);
  }
}

/** The sentence under the select: where the chosen voice speaks, and why it
 *  cannot when it cannot. */
export function noteFor(value, voices) {
  const choice = choiceOf(value, null);
  if (!choice || !choice.engine) {
    const server = (voices && voices.server) || {};
    if (server.available === false) return server.reason || 'The server’s voice cannot speak here yet.';
    return 'The voice an admin chose for everyone (Settings → Voice). Choose your own to change it for you alone.';
  }
  if (choice.engine === BROWSER) {
    return 'Your browser speaks these. In Chrome, the voices named Google, and any marked online, are Google’s '
      + 'online service, so a reply’s words leave this machine for those.';
  }
  const engine = ((voices && voices.engines) || []).find((e) => e.id === choice.engine);
  if (engine && !engine.available) return engine.reason || `${engine.name} is not running here.`;
  if (choice.engine === 'kokoro') return 'Kokoro speaks on this server’s own processor, so a reply’s words stay here.';
  if (choice.engine === 'chatterbox') return 'Chatterbox speaks on this server’s GPU, so a reply’s words stay here.';
  if (choice.engine === 'piper') return 'Piper speaks on this server’s own processor, so a reply’s words stay here.';
  return '';
}

function _stopPreview() {
  if (_audio) {
    try { _audio.pause(); } catch (_) { /* gone */ }
    try { URL.revokeObjectURL(_audio.src); } catch (_) { /* gone */ }
    _audio = null;
  }
  try { if (window.speechSynthesis) window.speechSynthesis.cancel(); } catch (_) { /* none */ }
  const btn = $('conv-preview');
  if (btn) btn.textContent = 'Hear it';
}

async function _preview() {
  const btn = $('conv-preview');
  if (_audio || (btn && btn.textContent === 'Stop')) { _stopPreview(); return; }
  const choice = choiceOf($('conv-voice').value, $('conv-speed').value);
  if (choice && choice.engine === BROWSER) {
    const voice = _browserVoices().find((v) => v.name === choice.voice);
    if (!window.speechSynthesis || !window.SpeechSynthesisUtterance) { _say('This browser cannot speak.', { bad: true }); return; }
    const u = new window.SpeechSynthesisUtterance(PREVIEW);
    if (voice) u.voice = voice;
    if (choice.speed) u.rate = choice.speed;
    u.onend = () => _stopPreview();
    u.onerror = () => _stopPreview();
    if (btn) btn.textContent = 'Stop';
    window.speechSynthesis.speak(u);
    return;
  }
  if (btn) btn.textContent = 'Stop';
  _say('Speaking… the first sentence can take a few seconds while the voice loads.');
  let res;
  try {
    res = await fetch('/api/tts/synthesize', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: PREVIEW, format: 'audio', engine: (choice && choice.engine) || '',
                             voice: (choice && choice.voice) || '', speed: choice ? choice.speed : null }),
    });
  } catch (_) {
    _stopPreview();
    _say('Pantheon’s server did not answer.', { bad: true });
    return;
  }
  if (!res.ok) {
    let why = '';
    try { const b = await res.json(); why = (b && b.detail && (b.detail.message || b.detail)) || ''; } catch (_) { why = ''; }
    _stopPreview();
    _say(String(why || `The voice did not speak (the server answered ${res.status}).`), { bad: true });
    return;
  }
  const spoke = res.headers.get('X-Pantheon-Voice') || '';
  const blob = await res.blob();
  if (!btn || btn.textContent !== 'Stop') return;   // stopped while it was on its way
  _audio = new Audio(URL.createObjectURL(blob));
  _audio.onended = () => { _stopPreview(); };
  _audio.onerror = () => { _stopPreview(); _say('The sound would not play.', { bad: true }); };
  try {
    await _audio.play();
    _say(spoke ? `Speaking with ${_spokeName(spoke)}.` : '');
  } catch (e) {
    _stopPreview();
    _say(e && e.name === 'NotAllowedError' ? 'The browser would not play sound on this page.' : 'The sound would not play.', { bad: true });
  }
}

/** "kokoro/bf_emma" in the words the select uses. */
function _spokeName(spoke) {
  const [engine, voice] = String(spoke).split('/');
  const found = ((_voices && _voices.engines) || []).find((e) => e.id === engine);
  const v = found && (found.voices || []).find((x) => x.id === voice);
  const name = found ? found.name : engine;
  return v ? `${name}, ${v.label}` : name;
}

async function _keep() {
  const choice = choiceOf($('conv-voice').value, $('conv-speed').value);
  $('conv-voice-note').textContent = noteFor($('conv-voice').value, _voices);
  const { ok, body } = await _json('/api/prefs/conversation_voice', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ value: choice }),
  });
  if (!ok) {
    _say(String((body && body.detail) || 'That was not kept.'), { bad: true });
    return;
  }
  _saved = body ? body.value : choice;
  _say('Kept. Replies are said in this voice from now on.');
  // The page's speaker asks again which voice it is, and loads it.
  if (window.aiTTSManager) window.aiTTSManager.checkAvailability({ warm: true });
}

function _drawSaved() {
  const select = $('conv-voice');
  const value = valueOf(_saved);
  // A kept voice this server no longer offers is kept, and named as gone.
  if (value && !Array.from(select.options).some((o) => o.value === value)) {
    select.appendChild(_option(value, `${value.split(':').slice(1).join(':') || value} (not offered here now)`));
  }
  select.value = value;
  const speed = _saved && _saved.speed != null ? String(_saved.speed) : '';
  const sp = $('conv-speed');
  if (speed && !Array.from(sp.options).some((o) => o.value === speed)) sp.appendChild(_option(speed, `${speed}×`));
  sp.value = speed;
  $('conv-voice-note').textContent = noteFor(select.value, _voices);
}

/** Read what the server offers and what this person keeps, and draw both. */
export async function open() {
  const select = $('conv-voice');
  if (!select) return;
  const sw = $('conv-switch');
  if (sw) sw.checked = conversationOn();
  if (!_wired) {
    _wired = true;
    if (sw) sw.addEventListener('change', () => {
      setConversation(sw.checked).then((kept) => {
        _say(kept ? (sw.checked ? 'Conversation on.' : 'Conversation off.') : 'Your account did not keep that.', { bad: !kept });
      });
    });
    select.addEventListener('change', _keep);
    $('conv-speed').addEventListener('change', _keep);
    $('conv-preview').addEventListener('click', _preview);
    // Chrome lists its voices only after it is first asked for them.
    try {
      if (window.speechSynthesis && 'onvoiceschanged' in window.speechSynthesis) {
        window.speechSynthesis.addEventListener('voiceschanged', () => {
          if (!_voices) return;
          drawVoices(select, _voices, _browserVoices());
          _drawSaved();
        });
      }
    } catch (_) { /* no voices to list */ }
  }
  _say('');
  const [voices, saved] = await Promise.all([
    _json('/api/tts/voices').catch(() => ({ ok: false })),
    _json('/api/prefs/conversation_voice').catch(() => ({ ok: false })),
  ]);
  if (!voices.ok || !voices.body) {
    select.textContent = '';
    select.appendChild(_option('', 'Pantheon’s voice'));
    _say('Pantheon’s server did not say which voices it has.', { bad: true });
    return;
  }
  _voices = voices.body;
  _saved = saved.ok && saved.body ? saved.body.value : null;
  const off = !!_voices.off;
  [select, $('conv-speed'), $('conv-preview'), sw].forEach((n) => { if (n) n.disabled = off; });
  if (off) {
    select.textContent = '';
    select.appendChild(_option('', 'No voice: speech is off on this server'));
    $('conv-voice-note').textContent = _voices.reason || 'Speech is turned off on this server.';
    return;
  }
  drawVoices(select, _voices, _browserVoices());
  _drawSaved();
}

export default { open, drawVoices, noteFor, valueOf, choiceOf };
