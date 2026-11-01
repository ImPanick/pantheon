# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1718` — voice chat, as a person meets it: set up in Settings → Voice,
started from the button beside Send, talked with, and ended.

The owner, 2026-10-31: *"Voice chatting with the agents … similar to OpenAI's
"Call" mode - we should have "Speech-to-text" as well as "Voice chatting with
your agent" settings with the ability to hook that up (and chatbox icons to
match)"*, and *"done as correctly as possible because I don't wanna spend
months chasing bugs"*.

Driven (`Law 20`) in the real app: `capture.Server` boots this checkout's
`app.py` with sign-in on, the chat's model is the showcase's scripted
stand-in (`demo_model.DemoModel`), and a headless Chromium does what a
person does. Two things are stood in for, because Chrome's own would send the
audio and the words to Google: its speech recognition (`webkitSpeechRecognition`,
which hears what the drive says, as Chrome's answers) and its voices
(`speechSynthesis`, which keeps what it is asked to say and takes a while
saying each sentence). The microphone is Chromium's fake device playing a
silent file, through the call's real capture, worklet and turn detector.

What is read: who sees the two buttons (an admin before speech-to-text is set
up, a member only once it is); a press with nothing set up saying why and
opening Settings → Voice; every control there saved and read back from the
server; the test button hearing; the voice preview speaking as chosen; a
call that hears a question, sends it as the person's message, says the reply
a sentence at a time while it is written, goes back to listening, mutes, and
closes the microphone when it ends; and the bar and the composer at desktop
and phone width, dark and light, with no sideways scroll.
"""
from __future__ import annotations

import json
import re
import secrets
import struct
import subprocess
import sys
import wave
from pathlib import Path

import pytest

from test_the_command_palette_in_a_browser import NODE, _SKIP  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SHOWCASE = ROOT / "scripts" / "showcase"
sys.path.insert(0, str(SHOWCASE))

import demo_model  # noqa: E402
import seed  # noqa: E402

pytestmark = pytest.mark.skipif(NODE is None, reason=_SKIP or "")

ASKED = "What is the tallest mountain in Africa"
ANSWER = ("The tallest mountain in Africa is Kilimanjaro, in Tanzania, at about 5,895 metres high. "
          "It is a dormant volcano with three cones, and most people take about a week to climb it.")
ASKED_ON_A_PHONE = "And what is the longest river there"
ANSWER_ON_A_PHONE = ("The longest river in Africa is the Nile, which runs north for about 6,650 kilometres. "
                     "It flows through eleven countries before it reaches the Mediterranean Sea.")
TESTED = "testing one two three"
# `B1726`. Said to dictation, and typed before it.
DICTATED = "remind me to water the plants"
TYPED = "Before I forget,"
SCRIPT = [{"key": "call", "title": "Mountains", "turns": [
    {"user": ASKED, "steps": [{"say": ANSWER}]},
    {"user": ASKED_ON_A_PHONE, "steps": [{"say": ANSWER_ON_A_PHONE}]},
]}]
MEMBER = {"username": "mira", "password": "mira-pass-" + secrets.token_hex(4)}

_DRIVE = r"""
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const C = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const out = { errors: [], shots: [] };
const COLOURS = { dark: { bg: '#282c34', fg: '#9cdef2', panel: '#111111', border: '#355a66', red: '#e06c75' },
                  light: { bg: '#f0ebe3', fg: '#5a5248', panel: '#faf6f0', border: '#d4cdc2', red: '#c47d5a' } };

// Every wait is on a named condition (`B1638`): a step that times out says
// which condition never came.
async function until(page, what, fn, ms = 60000, arg = null) {
  try { await page.waitForFunction(fn, arg, { timeout: ms, polling: 100 }); }
  catch (e) {
    // What the call and the page were doing when it did not come.
    const seen = await page.evaluate(() => ({
      words: (document.getElementById('voice-call-state') || {}).textContent,
      caption: (document.getElementById('voice-call-caption') || {}).textContent,
      recs: (window.__recs || []).map((r) => ({ live: !!r.live, heard: !!r.onresult })),
      said: (window.__said || []).length,
      toasts: (window.__toasts || []).slice(-3),
    })).catch(() => null);
    const why = /Timeout/.test(String(e && e.name) + String(e && e.message)) ? `not within ${ms / 1000} s`
      : String((e && e.message) || e).split('\n')[0];
    throw new Error(`${what}: ${why}; ${JSON.stringify(seen)}`);
  }
}

// What Chrome gives a page, stood in: recognition that hears what the drive
// says (`__hear`), or, for a test that stops it, the words it was given
// (`__testWords`), in Chrome's order (the last result after `stop()`, then
// `end`); voices that keep what they are asked to say (`__said`) and take
// `__sayMs` saying each; and every microphone stream the page opens.
const standIns = () => {
  window.__recs = [];
  class Recognition {
    constructor() { window.__recs.push(this); this.lang = ''; }
    start() { this.live = true; window.__recLang = this.lang; }
    stop() {
      this.live = false;
      // `__stopMs`: how long its last words take to come (`B1726` holds them
      // long enough to see the box say "Transcribing . . .").
      setTimeout(() => {
        if (window.__testWords && this.onresult) {
          const r = [{ transcript: window.__testWords }]; r.isFinal = true;
          this.onresult({ resultIndex: 0, results: [r] });
        }
        setTimeout(() => { if (this.onend) this.onend(); }, 30);
      }, window.__stopMs || 200);
    }
    abort() { this.live = false; setTimeout(() => { if (this.onend) this.onend(); }, 0); }
  }
  window.SpeechRecognition = Recognition;
  window.webkitSpeechRecognition = Recognition;
  window.__hear = (text) => {
    const rec = [...window.__recs].reverse().find((r) => r.live && r.onresult);
    if (!rec) return false;
    const r = [{ transcript: text }]; r.isFinal = true;
    rec.onresult({ resultIndex: 0, results: [r] });
    return true;
  };

  window.__said = [];
  window.__sayMs = 900;
  const voices = [{ name: 'Samantha', lang: 'en-US', default: true, localService: true, voiceURI: 'Samantha' },
                  { name: 'Daniel', lang: 'en-GB', default: false, localService: true, voiceURI: 'Daniel' }];
  let queue = [];
  let timer = null;
  const next = () => {
    if (timer || !queue.length || synth.paused) return;
    synth.speaking = true;
    timer = setTimeout(() => {
      timer = null;
      const u = queue.shift();
      synth.speaking = queue.length > 0;
      if (u && u.onend) u.onend({ type: 'end' });
      next();
    }, window.__sayMs);
  };
  const synth = {
    speaking: false, pending: false, paused: false,
    getVoices: () => voices.slice(),
    speak(u) { window.__said.push({ text: u.text, rate: u.rate, voice: u.voice ? u.voice.name : null }); queue.push(u); next(); },
    cancel() {
      clearTimeout(timer); timer = null;
      const dropped = queue; queue = []; synth.speaking = false;
      for (const u of dropped) if (u.onerror) u.onerror({ type: 'error', error: 'interrupted' });
    },
    pause() { synth.paused = true; },
    resume() { synth.paused = false; next(); },
    addEventListener() {}, removeEventListener() {},
  };
  Object.defineProperty(window, 'speechSynthesis', { value: synth, configurable: true });
  window.SpeechSynthesisUtterance = class { constructor(text) { this.text = text; this.rate = 1; this.pitch = 1; this.volume = 1; this.voice = null; this.lang = ''; } };

  window.__streams = [];
  const md = navigator.mediaDevices;
  if (md && md.getUserMedia) {
    const ask = md.getUserMedia.bind(md);
    md.getUserMedia = async (c) => { const s = await ask(c); window.__streams.push(s); return s; };
  }
  window.__voiceSettings = [];
  window.addEventListener('pantheon:voice-settings', (e) => window.__voiceSettings.push(e.detail));
  window.__toasts = [];
  document.addEventListener('DOMContentLoaded', () => {
    const toast = document.getElementById('toast');
    if (toast) new MutationObserver(() => {
      const text = (toast.querySelector('span') || toast).textContent;
      if (text && window.__toasts[window.__toasts.length - 1] !== text) window.__toasts.push(text);
    }).observe(toast, { childList: true, subtree: true, characterData: true });
  });
};

async function open(browser, who, { size = [1280, 860], theme = 'dark' } = {}) {
  const phone = size[0] < 500;
  const ctx = await browser.newContext({ viewport: { width: size[0], height: size[1] }, isMobile: phone,
    hasTouch: phone, serviceWorkers: 'block', permissions: ['microphone'] });
  ctx.setDefaultTimeout(60000);
  ctx.setDefaultNavigationTimeout(120000);
  await ctx.addInitScript((a) => {
    try {
      localStorage.setItem('pantheon-theme', a.theme);
      localStorage.setItem('pantheon-hint-drag-to-snap-seen', '1');
      localStorage.setItem('pantheon-ui-visibility', JSON.stringify({ 'first-run-tours': false }));
    } catch (_) {}
  }, { theme: JSON.stringify({ name: theme, colors: COLOURS[theme] }) });
  await ctx.addInitScript(standIns);
  const r = await ctx.request.post(C.base + '/api/auth/login',
    { data: { username: who.username, password: who.password, remember: true }, timeout: 120000 });
  if (!r.ok()) throw new Error('login ' + who.username + ' ' + r.status());
  const page = await ctx.newPage();
  page.on('pageerror', (e) => out.errors.push(`${who.username}: ${String((e && e.message) || e)}`));
  await page.goto(C.base + '/', { waitUntil: 'load' });
  await until(page, 'the app started', () => window.__pantheonAppStarted === true, 120000);
  await until(page, 'the speech settings were read', () => window.__voiceSettings.length > 0);
  return { ctx, page };
}

const buttons = (page) => page.evaluate(() => {
  const shown = (id) => { const b = document.getElementById(id); return !!b && !b.hidden && b.getBoundingClientRect().width > 0; };
  return { mic: shown('composer-mic-btn'), call: shown('composer-call-btn') };
});

const api = async (ctx, method, p, data) => {
  const res = await ctx.request[method](C.base + p, data ? { data } : undefined);
  return method === 'get' ? res.json() : res.status();
};

// The composer and a little above it (the call bar sits there).
const composerClip = (page) => page.evaluate(() => {
  const r = document.querySelector('.chat-input-bar').getBoundingClientRect();
  const top = Math.max(0, r.top - 90);
  return { x: 0, y: top, width: window.innerWidth, height: Math.min(window.innerHeight, r.bottom + 12) - top };
});

async function shot(page, name, clip) {
  // The bar's entrance and its lamp's colour change finished: a picture of
  // the slab half faded in says nothing about how it looks.
  await until(page, `${name}: the bar settled`, () => {
    const bar = document.getElementById('voice-call-bar');
    if (!bar || bar.hidden) return true;
    const lamp = bar.querySelector('.voice-call-lamp');
    const moving = (el) => el.getAnimations().some((a) => a.playState === 'running'
      && (a instanceof CSSTransition || (a.effect && a.effect.getTiming().iterations !== Infinity)));
    return !moving(bar) && !(lamp && moving(lamp));
  }, 10000);
  const file = path.join(C.shots, name + '.png');
  await page.screenshot({ path: file, clip: clip || undefined });
  out.shots.push(file);
}

// What the page looks like at its width: nothing scrolls sideways, and the
// composer's row and the call bar sit inside the window.
const layout = (page) => page.evaluate(() => {
  const inside = (el) => {
    if (!el || el.hidden) return null;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.left >= -0.5 && r.right <= window.innerWidth + 0.5;
  };
  return {
    sideways: document.documentElement.scrollWidth > window.innerWidth + 1,
    bar: inside(document.getElementById('voice-call-bar')),
    mic: inside(document.getElementById('composer-mic-btn')),
    call: inside(document.getElementById('composer-call-btn')),
    send: inside(document.querySelector('.send-btn')),
  };
});

const menuOpen = () => {
  const m = document.getElementById('model-picker-menu');
  return !!m && !m.classList.contains('hidden') && !m.classList.contains('closing');
};

async function pick(page, model) {
  await page.evaluate(() => document.activeElement && document.activeElement.blur && document.activeElement.blur());
  if (!(await page.evaluate(menuOpen))) await page.click('#model-picker-btn', { timeout: 60000 });
  await until(page, 'the model picker opened', menuOpen);
  const item = page.locator('.model-switch-item', { hasText: model }).first();
  await item.waitFor({ state: 'visible', timeout: 60000 });
  await item.click();
  await until(page, `${model} chosen and the picker shut`, (m) => {
    const label = document.getElementById('model-picker-label');
    const menu = document.getElementById('model-picker-menu');
    return !window.__pantheonModelSwitchPromise && !!label && label.textContent.includes(m)
      && menu.classList.contains('hidden');
  }, 60000, model);
}

const words = (page) => page.evaluate(() => (document.getElementById('voice-call-state') || {}).textContent || '');

// `B1726`. What the message box says about dictation: its prompt, the pill
// beside the words when it has some, and the microphone button.
const boxSays = (page) => page.evaluate(() => {
  const m = document.getElementById('message');
  const pill = document.getElementById('dictation-status');
  const mic = document.getElementById('composer-mic-btn');
  const r = pill && !pill.hidden ? pill.getBoundingClientRect() : null;
  const bar = document.querySelector('.chat-input-bar').getBoundingClientRect();
  return {
    prompt: m.getAttribute('placeholder'),
    value: m.value,
    state: m.dataset.dictation || '',
    pill: r && r.width > 0 ? pill.textContent.replace(/\s+/g, ' ').trim() : null,
    pillState: pill ? (pill.dataset.state || '') : '',
    pillInside: r ? (r.left >= bar.left - 0.5 && r.right <= bar.right + 0.5
      && r.top >= bar.top - 0.5 && r.bottom <= bar.bottom + 0.5) : null,
    lamp: r ? getComputedStyle(pill, '::before').animationName : null,
    mic: { pressed: mic.getAttribute('aria-pressed'), state: mic.dataset.state || '' },
    // The words keep their room: the box's width, and nothing of them scrolled out of sight.
    textWidth: Math.round(m.getBoundingClientRect().width),
    textHidden: m.scrollHeight > m.clientHeight + 1,
    picker: getComputedStyle(document.getElementById('model-picker-wrap')).display !== 'none',
    toast: document.getElementById('toast').classList.contains('show'),
    sideways: document.documentElement.scrollWidth > window.innerWidth + 1,
  };
});
const promptIs = (re) => new RegExp(re).test(document.getElementById('message').getAttribute('placeholder') || '');
const pillIs = (state) => {
  const p = document.getElementById('dictation-status');
  return !!p && !p.hidden && p.dataset.state === state;
};
const twoFrames = (page) => page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))));
const waited = async (page, what, ms) => {
  const t0 = await page.evaluate(() => performance.now());
  await until(page, what, (a) => performance.now() - a[0] > a[1], ms + 5000, [t0, ms]);
};
const barShown = (page) => page.evaluate(() => { const b = document.getElementById('voice-call-bar'); return !!b && !b.hidden; });

// A choice on the Voice page, and the word its card says once it is saved.
async function saveOn(page, msgId, act, what) {
  await page.evaluate((id) => {
    window.__msgs = window.__msgs || {};
    window.__msgs[id] = [];
    const msg = document.getElementById(id);
    if (!msg.__watched) {
      msg.__watched = true;
      new MutationObserver(() => { if (msg.textContent) window.__msgs[id].push(msg.textContent); })
        .observe(msg, { childList: true, characterData: true, subtree: true });
    }
  }, msgId);
  await act();
  await until(page, `${what} saved`, (id) => (window.__msgs[id] || []).length > 0, 30000, msgId);
  const said = await page.evaluate((id) => window.__msgs[id].splice(0), msgId);
  if (!said.includes('Saved')) out.errors.push(`${what}: the card said ${JSON.stringify(said)}`);
}

(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox', '--use-fake-ui-for-media-stream',
    '--use-fake-device-for-media-stream', '--use-file-for-fake-audio-capture=' + C.silence] });
  const admin = { username: C.user, password: C.password };
  const member = C.member;

  // ── Nothing set up: a member sees neither button, an admin the call button ──
  let s = await open(browser, member);
  out.memberBefore = await buttons(s.page);
  await s.ctx.close();

  s = await open(browser, admin);
  let { ctx, page } = s;
  out.adminBefore = await buttons(page);
  await shot(page, 'composer-admin-nothing-set-up-dark', await composerClip(page));
  await page.click('#composer-call-btn');
  await until(page, 'the press said why it cannot hear', () => window.__toasts.length > 0 && !window.__pantheonVoiceCall);
  out.refusal = await page.evaluate(() => ({
    toast: window.__toasts.slice(),
    action: [...document.querySelectorAll('#toast button')].map((b) => b.textContent.trim()),
    bar: !document.getElementById('voice-call-bar').hidden,
    streams: window.__streams.length,
  }));
  await page.locator('#toast button', { hasText: 'Voice settings' }).click();
  await until(page, 'Settings opened on Voice', () => {
    const p = document.querySelector('[data-settings-panel="voice"]');
    return !!p && !p.classList.contains('hidden') && p.getBoundingClientRect().height > 0;
  });
  await until(page, 'the Voice page read what is saved', () =>
    !!(document.getElementById('set-sttProviderNote') || {}).textContent
    && !!(document.getElementById('set-ttsProviderNote') || {}).textContent);
  out.page = await page.evaluate(() => {
    const panel = document.querySelector('[data-settings-panel="voice"]');
    const nav = document.querySelector('#settings-modal .settings-nav-item[data-settings-tab="voice"]');
    const opts = (id) => [...document.getElementById(id).options].map((o) => [o.value, o.textContent.trim()]);
    return {
      headings: [...panel.querySelectorAll('.admin-card h2')].map((h) => h.textContent.trim()),
      nav: nav ? nav.textContent.trim() : null,
      navCurrent: nav ? (nav.getAttribute('aria-current') || String(nav.classList.contains('active'))) : null,
      voices: opts('set-ttsProviderSelect'),
      pauses: opts('set-voiceChatPauseSelect'),
      voiceChat: document.getElementById('set-voiceChatEnabledToggle').checked,
      bargeIn: document.getElementById('set-voiceChatBargeInToggle').checked,
      readAloud: document.getElementById('set-ttsReadAloudToggle').checked,
      voice: document.getElementById('set-ttsProviderSelect').value,
      stt: document.getElementById('set-sttProviderSelect').value,
    };
  });
  await shot(page, 'settings-voice-fresh-dark');

  // ── Settings → Voice: each control saved and read back ──
  await saveOn(page, 'set-sttSettingsMsg', () => page.selectOption('#set-sttProviderSelect', 'browser'), 'speech to text: the browser');
  await page.evaluate((w) => { window.__testWords = w; }, C.tested);
  await page.click('#set-sttTestBtn');
  await until(page, 'the test heard something', () =>
    /^Heard:|Nothing was heard|recognition/.test((document.getElementById('set-sttTestResult') || {}).textContent || ''), 30000);
  out.tested = await page.evaluate(() => document.getElementById('set-sttTestResult').textContent);
  await page.evaluate(() => { window.__testWords = ''; });

  await saveOn(page, 'set-ttsSettingsMsg', () => page.selectOption('#set-ttsProviderSelect', 'browser'), 'the voice: the browser');
  await saveOn(page, 'set-ttsSettingsMsg', async () => {
    await page.fill('#set-ttsVoiceInput', 'daniel');
    await page.press('#set-ttsVoiceInput', 'Tab');
  }, 'the speaker');
  await saveOn(page, 'set-ttsSettingsMsg', () => page.selectOption('#set-ttsSpeedSelect', '1.25'), 'the speed');
  out.voiceList = await page.evaluate(() => [...document.querySelectorAll('#set-ttsVoiceList option')].map((o) => o.value));
  await page.evaluate(() => { window.__said = []; });
  await page.click('#set-ttsPreviewBtn');
  await until(page, 'the preview was said', () => /That is the voice/.test(document.getElementById('set-ttsSettingsMsg').textContent), 30000);
  out.preview = await page.evaluate(() => window.__said.slice());

  await saveOn(page, 'set-ttsSettingsMsg', () => page.selectOption('#set-voiceChatPauseSelect', 'relaxed'), 'the pause');
  await saveOn(page, 'set-ttsSettingsMsg', () => page.click('#set-voiceChatBargeInToggle + .admin-slider'), 'talking over: off');
  out.serverBargeOff = (await api(ctx, 'get', '/api/stt/stats')).voice_chat;
  await saveOn(page, 'set-ttsSettingsMsg', () => page.click('#set-voiceChatBargeInToggle + .admin-slider'), 'talking over: on');
  await saveOn(page, 'set-ttsSettingsMsg', () => page.click('#set-ttsReadAloudToggle + .admin-slider'), 'read aloud: on');
  await saveOn(page, 'set-ttsSettingsMsg', () => page.click('#set-voiceChatEnabledToggle + .admin-slider'), 'voice chat: off');
  await until(page, 'the call button went with voice chat', () => document.getElementById('composer-call-btn').hidden);
  out.chatOff = { buttons: await buttons(page), server: (await api(ctx, 'get', '/api/stt/stats')).voice_chat };
  await saveOn(page, 'set-ttsSettingsMsg', () => page.click('#set-voiceChatEnabledToggle + .admin-slider'), 'voice chat: on');
  await until(page, 'the call button came back', () => !document.getElementById('composer-call-btn').hidden);
  const saved = await api(ctx, 'get', '/api/auth/settings');
  out.saved = {
    stt_enabled: saved.stt_enabled, stt_provider: saved.stt_provider,
    tts_enabled: saved.tts_enabled, tts_provider: saved.tts_provider, tts_voice: saved.tts_voice, tts_speed: saved.tts_speed,
    voice_chat_enabled: saved.voice_chat_enabled, voice_chat_pause: saved.voice_chat_pause,
    voice_chat_barge_in: saved.voice_chat_barge_in, tts_read_aloud: saved.tts_read_aloud,
  };
  out.sttStats = await api(ctx, 'get', '/api/stt/stats');
  out.ttsStats = await api(ctx, 'get', '/api/tts/stats');
  await shot(page, 'settings-voice-set-up-dark');
  out.memberRefused = (await (await browser.newContext()).request.post(C.base + '/api/auth/settings',
    { data: { voice_chat_enabled: false } })).status();
  await ctx.close();

  // ── A member, once speech-to-text is set up ──
  s = await open(browser, member);
  out.memberAfter = await buttons(s.page);
  const asMember = await s.ctx.request.post(C.base + '/api/auth/settings', { data: { voice_chat_enabled: false } });
  out.memberSave = asMember.status();
  await s.ctx.close();

  // ── A call, at a desk ──
  s = await open(browser, admin);
  ({ ctx, page } = s);
  out.adminAfter = await buttons(page);
  await pick(page, C.model);
  await page.click('#composer-call-btn');
  await until(page, 'the call is listening', () =>
    (document.getElementById('voice-call-state') || {}).textContent === 'Listening.', 30000);
  out.listening = await page.evaluate(() => ({
    phase: document.getElementById('voice-call-bar').dataset.phase,
    pressed: document.getElementById('composer-call-btn').getAttribute('aria-pressed'),
    lang: window.__recLang === undefined ? null : window.__recLang,
    streams: window.__streams.length,
    live: window.__streams.flatMap((st) => st.getAudioTracks()).filter((t) => t.readyState === 'live').length,
  }));
  await shot(page, 'call-listening-desktop-dark');
  await page.evaluate(() => { window.__said = []; });
  await until(page, 'the browser heard the question', (t) => window.__hear(t), 10000, C.asked);
  await until(page, 'the question was sent as the person\'s message', (t) =>
    [...document.querySelectorAll('.msg-user')].some((m) => m.textContent.includes(t)), 30000, C.asked);
  await until(page, 'the first sentence was said', () => window.__said.length > 0, 60000);
  out.firstSaid = await page.evaluate(() => ({
    said: window.__said.map((u) => u.text),
    words: document.getElementById('voice-call-state').textContent,
    // Still being written when its first sentence went.
    writing: !!document.querySelector('.send-btn[data-mode="streaming"]'),
  }));
  await shot(page, 'call-speaking-desktop-dark');
  await until(page, 'the reply was said and the call listens again', () =>
    document.getElementById('voice-call-state').textContent === 'Listening.'
    && !document.querySelector('.send-btn[data-mode="streaming"]'), 90000);
  out.reply = await page.evaluate(() => {
    const body = [...document.querySelectorAll('.msg-ai .body')].pop();
    return {
      said: window.__said.map((u) => [u.text, u.rate, u.voice]),
      shown: body ? body.textContent.trim() : '',
      readAloud: !!document.querySelector('.msg-ai .ai-tts-button'),
      composer: document.getElementById('message').value,
    };
  });
  await page.click('#voice-call-mute');
  out.muted = { words: await words(page), pressed: await page.getAttribute('#voice-call-mute', 'aria-pressed') };
  await page.click('#voice-call-mute');
  out.unmuted = await words(page);
  await page.click('#voice-call-end');
  await until(page, 'the call ended', () => document.getElementById('voice-call-bar').hidden && !window.__pantheonVoiceCall);
  out.ended = await page.evaluate(() => ({
    pressed: document.getElementById('composer-call-btn').getAttribute('aria-pressed'),
    live: window.__streams.flatMap((st) => st.getAudioTracks()).filter((t) => t.readyState === 'live').length,
    toasts: window.__toasts.slice(),
  }));
  out.desk = await layout(page);

  // ── Dictation at a desk (`B1726`): the box says what it is doing ──
  // The browser's own recognition (as saved above), its last words held
  // 3.2 s after the stop so that "Transcribing . . ." can be seen.
  await page.evaluate((w) => { window.__stopMs = 3200; window.__testWords = w; }, C.dictated);
  await page.fill('#message', '');
  const d = out.dictation = { before: await boxSays(page) };
  await page.click('#composer-mic-btn');
  await until(page, 'the empty box says it is listening', promptIs, 15000, '^Listening( \\.){1,3}$');
  d.listening = await boxSays(page);
  await until(page, 'the dots stepped', (p) => document.getElementById('message').getAttribute('placeholder') !== p,
    5000, d.listening.prompt);
  d.stepped = (await boxSays(page)).prompt;
  await shot(page, 'dictation-listening-desktop-dark', await composerClip(page));
  // Made narrow while it listens: the box keeps saying it, and gets the prompt
  // for its new width when dictation ends.
  await page.setViewportSize({ width: 380, height: 860 });
  await until(page, 'the composer is narrow', () => document.querySelector('.chat-input-top').clientWidth < 400);
  await twoFrames(page);
  d.narrow = await boxSays(page);
  await page.click('#composer-mic-btn');
  await until(page, 'the narrow box says it is transcribing', promptIs, 15000, '^Transcribing');
  d.narrowTranscribing = await boxSays(page);
  await until(page, 'the words were written into the narrow box', (w) => document.getElementById('message').value.includes(w), 15000, C.dictated);
  await twoFrames(page);
  d.narrowDone = await boxSays(page);
  await page.setViewportSize({ width: 1280, height: 860 });
  await until(page, 'the composer is wide again', () => document.querySelector('.chat-input-top').clientWidth > 600);
  await page.fill('#message', '');
  await twoFrames(page);
  d.wideAgain = (await boxSays(page)).prompt;
  await page.click('#composer-mic-btn');
  await until(page, 'listening again', promptIs, 15000, '^Listening');
  await page.click('#composer-mic-btn');
  await until(page, 'the empty box says it is transcribing', promptIs, 15000, '^Transcribing');
  d.transcribing = await boxSays(page);
  await shot(page, 'dictation-transcribing-desktop-dark', await composerClip(page));
  await until(page, 'the words were written in', (w) => document.getElementById('message').value === w, 15000, C.dictated);
  await twoFrames(page);
  d.done = await boxSays(page);
  // A box with words in it says the same in a pill beside them.
  await page.fill('#message', C.typed);
  await page.click('#composer-mic-btn');
  await until(page, 'the pill says it is listening', pillIs, 15000, 'listening');
  await twoFrames(page);
  d.pillListening = await boxSays(page);
  await shot(page, 'dictation-pill-listening-desktop-dark', await composerClip(page));
  await page.click('#composer-mic-btn');
  await until(page, 'the pill says it is transcribing', pillIs, 15000, 'transcribing');
  await twoFrames(page);
  d.pillTranscribing = await boxSays(page);
  await shot(page, 'dictation-pill-transcribing-desktop-dark', await composerClip(page));
  await until(page, 'the words joined the typed ones', (w) => document.getElementById('message').value === w,
    15000, C.typed + ' ' + C.dictated);
  d.pillDone = await boxSays(page);
  await page.evaluate(() => { window.__stopMs = 0; window.__testWords = ''; });
  await page.fill('#message', '');
  await ctx.close();

  // ── A call on a phone, in the light ──
  s = await open(browser, admin, { size: [360, 780], theme: 'light' });
  ({ ctx, page } = s);
  out.phoneButtons = await buttons(page);
  out.phoneComposer = await layout(page);
  await pick(page, C.model);
  await page.evaluate(() => { window.__sayMs = 2500; });
  await page.click('#composer-call-btn');
  await until(page, 'the phone call is listening', () =>
    (document.getElementById('voice-call-state') || {}).textContent === 'Listening.', 30000);
  await shot(page, 'call-listening-phone-light');
  await page.evaluate(() => { window.__said = []; });
  await until(page, 'the browser heard the phone question', (t) => window.__hear(t), 10000, C.askedOnAPhone);
  await until(page, 'the phone reply is being said', () => window.__said.length > 0
    && document.getElementById('voice-call-state').textContent === 'Speaking.', 60000);
  out.phone = await layout(page);
  out.phoneCaption = await page.evaluate(() => document.getElementById('voice-call-caption').textContent);
  await shot(page, 'call-speaking-phone-light');
  await page.click('#voice-call-skip');
  await until(page, 'skipping stopped the voice', () => document.getElementById('voice-call-state').textContent !== 'Speaking.', 15000);
  out.skipped = await page.evaluate(() => ({ words: document.getElementById('voice-call-state').textContent, said: window.__said.length }));
  await page.click('#voice-call-end');
  await until(page, 'the phone call ended', () => document.getElementById('voice-call-bar').hidden);
  await ctx.close();

  // ── The page in the light at a desk, for the eye ──
  s = await open(browser, admin, { theme: 'light' });
  ({ ctx, page } = s);
  await page.click('#composer-call-btn');
  await until(page, 'the light call is listening', () =>
    (document.getElementById('voice-call-state') || {}).textContent === 'Listening.', 30000);
  await shot(page, 'call-listening-desktop-light');
  await page.click('#voice-call-end');
  await until(page, 'the light call ended', () => document.getElementById('voice-call-bar').hidden && !window.__pantheonVoiceCall);
  // `B1726`: the pill in the light.
  await page.evaluate((w) => { window.__stopMs = 3200; window.__testWords = w; }, C.dictated);
  await page.fill('#message', C.typed);
  await page.click('#composer-mic-btn');
  await until(page, 'the light pill says it is listening', pillIs, 15000, 'listening');
  await twoFrames(page);
  out.lightPill = { listening: await boxSays(page) };
  await shot(page, 'dictation-pill-listening-desktop-light', await composerClip(page));
  await page.click('#composer-mic-btn');
  await until(page, 'the light pill says it is transcribing', pillIs, 15000, 'transcribing');
  await twoFrames(page);
  out.lightPill.transcribing = await boxSays(page);
  await shot(page, 'dictation-pill-transcribing-desktop-light', await composerClip(page));
  await until(page, 'the light words joined the typed ones', (w) => document.getElementById('message').value === w,
    15000, C.typed + ' ' + C.dictated);
  await page.evaluate(() => { window.__stopMs = 0; window.__testWords = ''; });
  await page.fill('#message', '');
  await page.click('#user-bar-settings');
  await page.click('#settings-modal .settings-nav-item[data-settings-tab="voice"]');
  await until(page, 'Settings → Voice in the light', () =>
    !!(document.getElementById('set-ttsProviderNote') || {}).textContent);
  await shot(page, 'settings-voice-light');
  // Speech to text from here on is the server's: an endpoint is chosen for it.
  out.endpointSaved = await api(ctx, 'post', '/api/auth/settings', { stt_provider: 'endpoint:' + C.endpoint });
  await ctx.close();
  await browser.close();

  // ── Speech to text on the server (`B1726`): "Transcribing . . ." for as long as it takes ──
  // What the endpoint would answer is stood in at the page's door and held
  // until the drive lets it go: no speech model can be fetched here. This
  // browser's microphone plays a voice-like sound (a 130 Hz voice with two
  // formants, in syllables) after a second and a half of silence, through
  // the call's real capture and turn detector.
  const talker = await chromium.launch({ args: ['--no-sandbox', '--use-fake-ui-for-media-stream',
    '--use-fake-device-for-media-stream', '--use-file-for-fake-audio-capture=' + C.voiced] });
  const holdWords = async (page) => {
    const held = [];
    await page.route('**/api/stt/transcribe', (route) => { held.push(route); });
    return {
      held,
      answer: (text) => held.shift().fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ text }) }),
    };
  };
  s = await open(talker, admin);
  ({ ctx, page } = s);
  let words$ = await holdWords(page);
  const c = out.serverCall = { provider: await page.evaluate(() => window.__voiceSettings[window.__voiceSettings.length - 1].provider) };
  await pick(page, C.model);
  await page.click('#composer-call-btn');
  await until(page, 'the server call is listening', () => document.getElementById('voice-call-state').textContent === 'Listening.', 30000);
  await until(page, 'the call heard the voice', () => document.getElementById('voice-call-state').textContent === 'Hearing you.', 20000);
  c.heard = await words(page);
  await until(page, 'the call is writing out what it heard', () =>
    document.getElementById('voice-call-state').textContent.startsWith('Transcribing'), 20000);
  c.transcribing = await page.evaluate(() => {
    const bar = document.getElementById('voice-call-bar');
    return { words: document.getElementById('voice-call-state').textContent, phase: bar.dataset.phase,
      lamp: getComputedStyle(bar.querySelector('.voice-call-lamp')).animationName };
  });
  c.asked = words$.held.length;
  await shot(page, 'call-transcribing-desktop-dark');
  await waited(page, 'three seconds with the words not back', 3000);
  c.still = await words(page);
  await words$.answer(C.asked);
  await until(page, 'the words were sent as the person\'s message', (t) =>
    [...document.querySelectorAll('.msg-user')].some((m) => m.textContent.includes(t)), 30000, C.asked);
  await until(page, 'the call went on to the reply', () =>
    /^(Thinking|Speaking)\.$/.test(document.getElementById('voice-call-state').textContent), 30000);
  c.after = await words(page);
  await page.click('#voice-call-end');
  await until(page, 'the server call ended', () => document.getElementById('voice-call-bar').hidden && !window.__pantheonVoiceCall);
  await ctx.close();

  // Dictation through the server on a phone, in the light: it says
  // "Transcribing . . ." after the toast has gone.
  s = await open(talker, admin, { size: [360, 780], theme: 'light' });
  ({ ctx, page } = s);
  words$ = await holdWords(page);
  const p = out.phoneDictation = {};
  await page.click('#composer-mic-btn');
  await until(page, 'the phone box says it is listening', promptIs, 15000, '^Listening');
  p.listening = await boxSays(page);
  await shot(page, 'dictation-listening-phone-light', await composerClip(page));
  await page.click('#composer-mic-btn');
  await until(page, 'the phone box says it is transcribing', promptIs, 15000, '^Transcribing');
  await waited(page, 'the toast\'s five seconds', 5600);
  p.transcribing = await boxSays(page);
  p.asked = words$.held.length;
  await shot(page, 'dictation-transcribing-phone-light', await composerClip(page));
  await words$.answer(C.dictated);
  await until(page, 'the phone words were written in', (w) => document.getElementById('message').value === w, 15000, C.dictated);
  await twoFrames(page);
  p.done = await boxSays(page);
  await page.click('#composer-mic-btn');
  await until(page, 'the phone pill says it is listening', pillIs, 15000, 'listening');
  await page.click('#composer-mic-btn');
  await until(page, 'the phone pill says it is transcribing', pillIs, 15000, 'transcribing');
  await twoFrames(page);
  p.pill = await boxSays(page);
  p.layout = await layout(page);
  await shot(page, 'dictation-pill-transcribing-phone-light', await composerClip(page));
  await words$.answer(C.dictated);
  await until(page, 'the phone words joined the first ones', (w) => document.getElementById('message').value === w,
    15000, C.dictated + ' ' + C.dictated);
  p.pillDone = await boxSays(page);
  await ctx.close();

  console.log(JSON.stringify(out));
  await talker.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


def _silence(path: Path, seconds: float = 3.0, rate: int = 48000) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack(f"<{int(seconds * rate)}h", *([0] * int(seconds * rate))))


def _voiced(path: Path, lead: float = 1.5, talk: float = 2.2, tail: float = 22.0, rate: int = 48000) -> None:
    """`B1726`. Something a turn detector hears as a person: a 130 Hz voice
    with two formants where an "ah" has them, in syllables at 4 Hz, after
    `lead` seconds of silence and before a long one (the fake microphone
    loops the file). It comes through Chromium's echo cancelling, noise
    suppression and gain control at about -18 dBFS, measured."""
    import math

    harmonics = []
    for k in range(1, 31):
        f = 130.0 * k
        if f > 4000:
            break
        harmonics.append((f, math.exp(-((f - 750) / 220) ** 2) + 0.6 * math.exp(-((f - 1200) / 260) ** 2) + 0.15 / k))
    norm = sum(a for _, a in harmonics)
    n = int(talk * rate)
    samples = []
    for i in range(n):
        t = i / rate
        vibrato = 1 + 0.01 * math.sin(2 * math.pi * 5 * t)
        s = sum(a * math.sin(2 * math.pi * f * vibrato * t) for f, a in harmonics) / norm
        syllables = 0.5 - 0.5 * math.cos(2 * math.pi * 4 * t)
        edge = min(1.0, t / 0.05, (talk - t) / 0.05)
        samples.append(int(max(-1.0, min(1.0, 0.35 * s * syllables * edge)) * 32767))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(lead * rate) + struct.pack(f"<{n}h", *samples) + b"\x00\x00" * int(tail * rate))


@pytest.fixture(scope="module")
def drive(tmp_path_factory):
    import capture
    import httpx

    work = tmp_path_factory.mktemp("voicechat")
    data = work / "data"
    data.mkdir()
    shots = Path(__import__("os").environ.get("PANTHEON_VOICE_SHOTS") or (work / "shots"))
    shots.mkdir(parents=True, exist_ok=True)
    _silence(work / "silence.wav")
    _voiced(work / "voiced.wav")
    server = capture.Server(sys.executable, data, capture._free_port(), extra_env={"PANTHEON_DISABLE_MCP": "1"})
    try:
        server.start(timeout=300)
    except RuntimeError as e:
        server.stop()
        pytest.fail(f"{e}\n{server.log_path.read_text(encoding='utf-8', errors='replace')[-3000:]}")
    log: list = []
    try:
        client = httpx.Client(base_url=server.base, timeout=180)
        password = secrets.token_urlsafe(18)
        seed.setup_admin(client, password)
        seed._ok(client.post("/api/auth/users", json={**MEMBER, "is_admin": False}), "a member")
        with demo_model.DemoModel(log=log, conversations=SCRIPT, pace=0.03) as model:
            endpoint = seed._ok(client.post("/api/model-endpoints", data={
                "name": "Demo box", "base_url": model.base_url, "supports_tools": "true",
                "require_models": "true"}), "the model")
            config = {"base": server.base, "user": seed.PERSON["username"], "password": password,
                      "member": MEMBER, "model": demo_model.MODEL_ID, "asked": ASKED,
                      "askedOnAPhone": ASKED_ON_A_PHONE, "tested": TESTED,
                      "dictated": DICTATED, "typed": TYPED, "endpoint": endpoint["id"],
                      "silence": str(work / "silence.wav"), "voiced": str(work / "voiced.wav"),
                      "shots": str(shots)}
            (work / "config.json").write_text(json.dumps(config))
            (work / "drive.cjs").write_text(_DRIVE)
            proc = subprocess.run([NODE, str(work / "drive.cjs"), str(work / "config.json")],
                                  capture_output=True, text=True, timeout=900, cwd=ROOT)
            assert proc.returncode == 0, proc.stderr[-4000:] + "\n" + server.log_path.read_text(
                encoding="utf-8", errors="replace")[-2000:]
            out = json.loads(proc.stdout.strip().splitlines()[-1])
        out["asked"] = [e for e in log if e.get("stream")]
        yield out
    finally:
        server.stop()


def test_nothing_set_up_shows_an_admin_the_call_button_and_a_member_nothing(drive):
    assert drive["memberBefore"] == {"mic": False, "call": False}
    assert drive["adminBefore"] == {"mic": False, "call": True}
    assert drive["errors"] == [], drive["errors"]


def test_a_press_with_nothing_set_up_says_why_and_opens_the_voice_page(drive):
    refusal = drive["refusal"]
    assert refusal["toast"][-1] == ("Voice chat needs speech-to-text. Choose one in "
                                    "Settings → Voice → Speech to text."), refusal["toast"]
    assert "Voice settings" in refusal["action"]
    assert refusal["bar"] is False
    assert refusal["streams"] == 0, "no microphone was opened for a call that could not hear"
    page = drive["page"]
    assert page["headings"] == ["Speech to Text", "Voice Chat"]
    assert page["nav"] == "Voice"
    # `B1728`: "Automatic" (Chatterbox on a GPU, else Kokoro), Kokoro and
    # Chatterbox join the voices this server can speak with.
    assert [v for v, _ in page["voices"]] == ["disabled", "auto", "kokoro", "chatterbox",
                                              "piper", "browser", "local"]
    assert [v for v, _ in page["pauses"]] == ["short", "normal", "relaxed"]
    assert (page["voiceChat"], page["bargeIn"], page["readAloud"]) == (True, True, False)
    # `B1728`: a fresh server speaks with "Automatic", which never reaches the
    # internet for a model (`Law 16`); hearing stays off until it is chosen.
    assert (page["voice"], page["stt"]) == ("auto", "disabled")


def test_every_control_on_the_voice_page_saves_and_reads_back(drive):
    assert drive["saved"] == {
        "stt_enabled": True, "stt_provider": "browser",
        "tts_enabled": True, "tts_provider": "browser", "tts_voice": "daniel", "tts_speed": "1.25",
        "voice_chat_enabled": True, "voice_chat_pause": "relaxed", "voice_chat_barge_in": True,
        "tts_read_aloud": True,
    }
    assert drive["serverBargeOff"]["barge_in"] is False
    assert drive["chatOff"]["server"]["enabled"] is False
    assert drive["chatOff"]["buttons"]["call"] is False, "voice chat off takes the call button away"
    assert drive["sttStats"]["voice_chat"] == {"enabled": True, "pause": "relaxed", "barge_in": True}
    assert drive["ttsStats"]["provider"] == "browser" and drive["ttsStats"]["voice"] == "daniel"
    assert drive["voiceList"] == ["Samantha", "Daniel"], "the browser's voices are offered by name"
    assert drive["memberRefused"] in (401, 403)
    assert drive["memberSave"] == 403


def test_the_test_button_hears_and_the_preview_speaks_as_chosen(drive):
    assert drive["tested"] == f"Heard: “{TESTED}”"
    assert drive["preview"] == [{"text": "Hello. This is how replies sound in a voice chat.",
                                 "rate": 1.25, "voice": "Daniel"}]


def test_a_member_sees_both_buttons_once_speech_to_text_is_set_up(drive):
    assert drive["memberAfter"] == {"mic": True, "call": True}
    assert drive["adminAfter"] == {"mic": True, "call": True}


def test_a_call_hears_the_question_sends_it_and_says_the_reply_while_it_is_written(drive):
    listening = drive["listening"]
    assert listening["phase"] == "listening"
    assert listening["pressed"] == "true"
    assert listening["live"] >= 1, "the call's microphone is open"
    sent = [e for e in drive["asked"] if ASKED in json.dumps(e.get("messages", []))]
    assert sent, "the heard words reached the model as the person's message"
    first = drive["firstSaid"]
    assert first["said"][0].startswith("The tallest mountain in Africa is Kilimanjaro"), first
    assert first["writing"] is True, "the first sentence is said before the reply is finished"
    reply = drive["reply"]
    said = [t for t, _, _ in reply["said"]]
    assert " ".join(said) == ANSWER, said
    assert all(rate == 1.25 and voice == "Daniel" for _, rate, voice in reply["said"]), reply["said"]
    assert reply["shown"].startswith("The tallest mountain in Africa"), reply["shown"]
    assert reply["readAloud"] is True, "read aloud was switched on, so its button is under the reply"
    assert reply["composer"] == "", "the spoken turn did not stay in the message box"


def test_a_call_mutes_and_closes_the_microphone_when_it_ends(drive):
    assert drive["muted"] == {"words": "Muted.", "pressed": "true"}
    assert drive["unmuted"] == "Listening."
    ended = drive["ended"]
    assert ended["pressed"] == "false"
    assert ended["live"] == 0, "every microphone track the page opened is stopped"
    assert not any("Voice chat ended" in t for t in ended["toasts"]), "a person's own End is not announced"


def test_the_bar_and_the_buttons_fit_a_phone_and_a_desk(drive):
    for where in ("desk", "phoneComposer", "phone"):
        assert drive[where]["sideways"] is False, (where, drive[where])
    assert drive["phoneButtons"] == {"mic": True, "call": True}
    for key in ("mic", "call", "send"):
        assert drive["phoneComposer"][key] is True, (key, drive["phoneComposer"])
    assert drive["phone"]["bar"] is True, drive["phone"]
    assert drive["phoneCaption"].startswith("The longest river in Africa is the Nile"), drive["phoneCaption"]
    assert drive["skipped"]["words"] in ("Listening.", "Thinking."), drive["skipped"]
    assert len(drive["shots"]) == 19


# ── `B1726`: while speech is turned into text, the page says so ──

# The composer's own prompts, by its width (`app.js`, `setComposerPlaceholder`).
PROMPTS = ("Message…", "Message Pantheon…", "Message Pantheon  ·  / commands  ·  @ agents")


def test_dictation_says_listening_and_transcribing_in_the_box(drive):
    d = drive["dictation"]
    own = d["before"]["prompt"]
    assert own in PROMPTS, d["before"]
    assert re.fullmatch(r"Listening( \.){1,3}", d["listening"]["prompt"] or ""), d["listening"]
    assert d["listening"]["state"] == "listening"
    assert d["listening"]["pill"] is None, "an empty box says it in its prompt"
    assert d["listening"]["mic"]["pressed"] == "true"
    assert d["stepped"] != d["listening"]["prompt"] and d["stepped"].startswith("Listening"), "the dots step"
    assert re.fullmatch(r"Transcribing( \.){1,3}", d["transcribing"]["prompt"] or ""), d["transcribing"]
    assert d["transcribing"]["mic"] == {"pressed": "false", "state": "transcribing"}
    assert d["done"]["value"] == DICTATED
    assert (d["done"]["prompt"], d["done"]["state"], d["done"]["pill"]) == (own, "", None), d["done"]
    for key in ("listening", "transcribing", "done"):
        assert d[key]["sideways"] is False, (key, d[key])


def test_a_box_with_words_says_it_in_a_pill_inside_the_composer(drive):
    for where in (drive["dictation"], drive["lightPill"]):
        for key, word, lamp in (("pillListening", "Listening", "none"), ("pillTranscribing", "Transcribing", "ck-pulse")):
            pill = where.get(key) or where[key.replace("pill", "").lower()]
            assert re.fullmatch(word + r"( \.){1,3}", pill["pill"] or ""), pill
            assert pill["pillState"] == word.lower()
            assert pill["pillInside"] is True, pill
            assert pill["lamp"] == lamp, pill
            assert pill["value"].startswith(TYPED)
            # It takes the model picker's place, and the words keep their room.
            assert pill["picker"] is False, pill
            assert pill["textWidth"] >= 150 and pill["textHidden"] is False, pill
    done = drive["dictation"]["pillDone"]
    assert done["value"] == f"{TYPED} {DICTATED}"
    assert done["pill"] is None


def test_the_box_keeps_saying_it_when_the_window_narrows_and_then_takes_its_prompt(drive):
    d = drive["dictation"]
    # Red before: the composer's own prompt, kept to its width, wrote over it.
    assert d["narrow"]["prompt"].startswith("Listening"), d["narrow"]
    assert d["narrowTranscribing"]["prompt"].startswith("Transcribing"), d["narrowTranscribing"]
    assert d["narrowDone"]["prompt"] == "Message…", d["narrowDone"]
    assert d["wideAgain"] == d["before"]["prompt"]


def test_a_call_says_transcribing_while_the_server_writes_out_what_was_said(drive):
    assert drive["endpointSaved"] == 200
    c = drive["serverCall"]
    assert c["provider"].startswith("endpoint:"), c
    assert c["heard"] == "Hearing you."
    assert c["transcribing"] == {"words": "Transcribing . . .", "phase": "transcribing", "lamp": "ck-pulse"}, c
    assert c["asked"] == 1
    assert c["still"] == "Transcribing . . .", "three seconds on, it still says so"
    assert c["after"] in ("Thinking.", "Speaking."), c


def test_dictation_through_the_server_says_transcribing_after_its_toast_has_gone(drive):
    p = drive["phoneDictation"]
    assert p["listening"]["prompt"].startswith("Listening"), p["listening"]
    assert p["transcribing"]["prompt"].startswith("Transcribing"), p["transcribing"]
    assert p["transcribing"]["toast"] is False, "the toast's five seconds are over; the box still says it"
    assert p["asked"] == 1
    assert (p["done"]["value"], p["done"]["state"], p["done"]["prompt"]) == (DICTATED, "", "Message…"), p["done"]
    assert re.fullmatch(r"Transcribing( \.){1,3}", p["pill"]["pill"] or ""), p["pill"]
    assert p["pill"]["pillInside"] is True, p["pill"]
    # Red before it took the picker's place: the phone's hidden picker kept its
    # width, and the words had none.
    assert p["pill"]["textWidth"] >= 120 and p["pill"]["textHidden"] is False, p["pill"]
    assert p["layout"]["sideways"] is False, p["layout"]
    for key in ("mic", "send"):
        assert p["layout"][key] is True, (key, p["layout"])
    assert p["pillDone"]["value"] == f"{DICTATED} {DICTATED}"
