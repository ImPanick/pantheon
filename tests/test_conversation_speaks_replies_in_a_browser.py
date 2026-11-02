# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1728`, `B1730` — Conversation, as a person meets it: their own switch,
their own voice, and every reply said out loud in it while it is written.

The owner, 2026-11-01: *"Need something for realistic voice synthesis for the
LLM's response back to the user (toggleable)"*, the card's *"Kokoro, plus
Chatterbox for a GPU"*, and on the switch: *"This should be a "Conversation"
switch not speak replies aloud - we make it personal-able"*.

Driven (`Law 20`) in the real app: `capture.Server` boots this checkout's
`app.py` with sign-in on and Kokoro's real model where the image bakes it
(`PANTHEON_SEED_MODELS/kokoro`), so the server's voice is "Automatic" and
every sentence is spoken by Kokoro on this machine's processor. The chat's
model is the showcase's scripted stand-in (`demo_model.DemoModel`), and a
headless Chromium does what a person does. Nothing about the speech is stood
in for: the WAVs are Kokoro's, and the page plays them through its own
`<audio>`; the drive only keeps what was asked, what came back and what played.

What is read: a member's Conversation chip; Settings → Conversation listing
the voices this server speaks with; a voice and a speed kept with the account
and read back; "Hear it" speaking the chosen voice without keeping anything;
the card's switch being the chip; a reply said sentence by sentence in that
voice while it is written, and not said once Conversation is off; the admin,
who chose no voice, hearing the server's (Kokoro's Heart) instead; the admin's
Voice page saying "Automatic" speaks with Kokoro; the switch and the voice
following the member to a phone; and speech turned off for everyone taking the
chip away. Desk and phone, dark and light, with no sideways scroll.
"""
from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

import pytest

from test_the_command_palette_in_a_browser import NODE, _SKIP  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SHOWCASE = ROOT / "scripts" / "showcase"
sys.path.insert(0, str(SHOWCASE))

import demo_model  # noqa: E402
import seed  # noqa: E402

from services.tts.kokoro_cpu import KOKORO_FILES, KOKORO_MODEL, KOKORO_VOICES  # noqa: E402


def _kokoro_seed():
    """The folder whose `kokoro/` holds Kokoro's real model, or `None`."""
    folder = Path(os.environ.get("PANTHEON_SEED_MODELS") or "/nonexistent")
    for name in (KOKORO_MODEL, KOKORO_VOICES):
        path = folder / "kokoro" / name
        if not path.is_file() or path.stat().st_size != KOKORO_FILES[name][1]:
            return None
    return folder


def _speaks_here():
    import importlib.util
    return all(importlib.util.find_spec(m) is not None for m in ("piper", "onnxruntime"))


SEED_MODELS = _kokoro_seed()
pytestmark = [
    pytest.mark.skipif(NODE is None, reason=_SKIP or ""),
    pytest.mark.skipif(SEED_MODELS is None, reason="Kokoro's model is not on this machine (PANTHEON_SEED_MODELS/kokoro)"),
    pytest.mark.skipif(not _speaks_here(), reason="the voice packages are not installed (requirements-voice.txt)"),
]

ASKED = "Tell me about the Moon"
ANSWER = ("The Moon is about a quarter of the size of the Earth. "
          "It takes about twenty-seven days to go around us once. "
          "Its pull on the oceans is what makes the tides.")
ASKED_OFF = "And what about the Sun"
ANSWER_OFF = "The Sun is the star at the centre of our solar system. Its light takes about eight minutes to reach us."
ASKED_BY_ADMIN = "What is a comet"
ANSWER_BY_ADMIN = "A comet is a ball of ice and dust that goes around the Sun. Near the Sun it grows a long glowing tail."
SCRIPT = [{"key": "conversation", "title": "The sky", "turns": [
    {"user": ASKED, "steps": [{"say": ANSWER}]},
    {"user": ASKED_OFF, "steps": [{"say": ANSWER_OFF}]},
    {"user": ASKED_BY_ADMIN, "steps": [{"say": ANSWER_BY_ADMIN}]},
]}]
MEMBER = {"username": "mira", "password": "mira-pass-" + secrets.token_hex(4)}

_DRIVE = r"""
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const C = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const out = { errors: [], shots: [], synth: [] };
const COLOURS = { dark: { bg: '#282c34', fg: '#9cdef2', panel: '#111111', border: '#355a66', red: '#e06c75' },
                  light: { bg: '#f0ebe3', fg: '#5a5248', panel: '#faf6f0', border: '#d4cdc2', red: '#c47d5a' } };

async function until(page, what, fn, ms = 60000, arg = null) {
  try { await page.waitForFunction(fn, arg, { timeout: ms, polling: 100 }); }
  catch (e) {
    const seen = await page.evaluate(() => {
      const m = window.aiTTSManager || {};
      return { speaks: m.speaks, provider: m._provider, autoPlay: m.autoPlay, processing: m._processing,
               queue: (m._queue || []).length, played: (window.__played || []).length,
               status: (document.getElementById('conv-status') || {}).textContent,
               toasts: (window.__toasts || []).slice(-3) };
    }).catch(() => null);
    const why = /Timeout/.test(String(e && e.name) + String(e && e.message)) ? `not within ${ms / 1000} s`
      : String((e && e.message) || e).split('\n')[0];
    throw new Error(`${what}: ${why}; ${JSON.stringify(seen)}; synth ${JSON.stringify(out.synth.slice(-3))}`);
  }
}

// What the page plays, kept: each sound's start, and whether it played to
// its end. The sound is the page's own <audio>, untouched.
const keepWhatPlays = () => {
  window.__played = [];
  const play = HTMLMediaElement.prototype.play;
  HTMLMediaElement.prototype.play = function () {
    const rec = { src: this.src, ended: false, error: null };
    window.__played.push(rec);
    this.addEventListener('ended', () => { rec.ended = true; rec.duration = this.duration; });
    this.addEventListener('error', () => { rec.error = 'media error ' + (this.error && this.error.code); });
    return play.call(this).catch((e) => { rec.error = e.name; throw e; });
  };
  // This device's own voices, two of them, so the card lists what a
  // browser offers without asking Google for any.
  const voices = [{ name: 'Samantha', lang: 'en-US', default: true, localService: true, voiceURI: 'Samantha' },
                  { name: 'Daniel', lang: 'en-GB', default: false, localService: true, voiceURI: 'Daniel' }];
  const synth = { speaking: false, pending: false, paused: false, getVoices: () => voices.slice(),
    speak(u) { setTimeout(() => u.onend && u.onend({ type: 'end' }), 300); }, cancel() {}, pause() {}, resume() {},
    addEventListener() {}, removeEventListener() {} };
  Object.defineProperty(window, 'speechSynthesis', { value: synth, configurable: true });
  window.SpeechSynthesisUtterance = class { constructor(t) { this.text = t; this.rate = 1; this.voice = null; } };
  window.__toasts = [];
  document.addEventListener('DOMContentLoaded', () => {
    const toast = document.getElementById('toast');
    if (toast) new MutationObserver(() => {
      const text = (toast.querySelector('span') || toast).textContent;
      if (text && window.__toasts[window.__toasts.length - 1] !== text) window.__toasts.push(text);
    }).observe(toast, { childList: true, subtree: true, characterData: true });
  });
};

// A WAV's seconds, from its header and its data chunk.
function seconds(buf) {
  if (buf.length < 44 || buf.toString('ascii', 0, 4) !== 'RIFF') return null;
  const rate = buf.readUInt32LE(24), bytes = buf.readUInt16LE(34) / 8, channels = buf.readUInt16LE(22);
  for (let i = 12; i + 8 <= buf.length;) {
    const id = buf.toString('ascii', i, i + 4), size = buf.readUInt32LE(i + 4);
    if (id === 'data') return { rate, seconds: size / (rate * bytes * channels) };
    i += 8 + size;
  }
  return null;
}

async function open(browser, who, { size = [1280, 860], theme = 'dark' } = {}) {
  const phone = size[0] < 500;
  const ctx = await browser.newContext({ viewport: { width: size[0], height: size[1] }, isMobile: phone,
    hasTouch: phone, serviceWorkers: 'block' });
  ctx.setDefaultTimeout(60000);
  ctx.setDefaultNavigationTimeout(120000);
  await ctx.addInitScript((a) => {
    try {
      localStorage.setItem('pantheon-theme', a.theme);
      localStorage.setItem('pantheon-hint-drag-to-snap-seen', '1');
      localStorage.setItem('pantheon-ui-visibility', JSON.stringify({ 'first-run-tours': false }));
    } catch (_) {}
  }, { theme: JSON.stringify({ name: theme, colors: COLOURS[theme] }) });
  await ctx.addInitScript(keepWhatPlays);
  const r = await ctx.request.post(C.base + '/api/auth/login',
    { data: { username: who.username, password: who.password, remember: true }, timeout: 120000 });
  if (!r.ok()) throw new Error('login ' + who.username + ' ' + r.status());
  const page = await ctx.newPage();
  page.on('pageerror', (e) => out.errors.push(`${who.username}: ${String((e && e.message) || e)}`));
  // Every sentence the page asked the server to say, who asked, which voice
  // said it (the server's own header), and the WAV, kept to hear later. The
  // request goes on to the server unchanged and its answer comes back to the
  // page unchanged; it passes through here because Chromium hands a body the
  // page reads with `blob()` straight to blob storage, and `response.body()`
  // on the page's own copy comes back empty.
  await page.route('**/api/tts/synthesize', async (route) => {
    let asked = {};
    try { asked = JSON.parse(route.request().postData() || '{}'); } catch (_) {}
    const rec = { who: who.username, text: asked.text, preview: 'engine' in asked,
                  asked: { engine: asked.engine ?? null, voice: asked.voice ?? null, speed: asked.speed ?? null } };
    let res;
    try { res = await route.fetch({ timeout: 120000 }); } catch (e) {
      rec.fetchError = String(e);
      out.synth.push(rec);
      return route.abort();
    }
    const headers = res.headers();
    Object.assign(rec, { status: res.status(), voice: headers['x-pantheon-voice'] || null,
                         type: headers['content-type'] || '' });
    const body = await res.body();
    Object.assign(rec, seconds(body) || {});
    if (res.status() === 200) {
      rec.file = path.join(C.wavs, `${String(out.synth.length).padStart(2, '0')}-${who.username}.wav`);
      fs.writeFileSync(rec.file, body);
    } else rec.body = body.toString('utf8').slice(0, 300);
    out.synth.push(rec);
    await route.fulfill({ response: res, body });
  });
  await page.goto(C.base + '/', { waitUntil: 'load' });
  await until(page, 'the app started', () => window.__pantheonAppStarted === true, 120000);
  await until(page, 'the page asked which voice speaks', () => !!(window.aiTTSManager && window.aiTTSManager.checked));
  return { ctx, page };
}

const api = async (ctx, method, p, data) => {
  const res = await ctx.request[method](C.base + p, data ? { data } : undefined);
  return method === 'get' ? res.json() : res.status();
};

const composerClip = (page) => page.evaluate(() => {
  const r = document.querySelector('.chat-input-bar').getBoundingClientRect();
  const top = Math.max(0, r.top - 24);
  return { x: 0, y: top, width: window.innerWidth, height: Math.min(window.innerHeight, r.bottom + 12) - top };
});

async function shot(page, name, clip) {
  await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))));
  const file = path.join(C.shots, name + '.png');
  await page.screenshot({ path: file, clip: clip || undefined });
  out.shots.push(file);
}

const layout = (page) => page.evaluate(() => {
  const inside = (el) => {
    if (!el || el.hidden) return null;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.left >= -0.5 && r.right <= window.innerWidth + 0.5;
  };
  return {
    sideways: document.documentElement.scrollWidth > window.innerWidth + 1,
    send: inside(document.querySelector('.send-btn')),
    panel: inside(document.querySelector('[data-settings-panel="conversation"]:not(.hidden)')),
  };
});

// The Conversation chip, as the composer shows it.
const chip = (page) => page.evaluate(() => {
  const b = document.getElementById('conversation-toggle-btn');
  const r = b.getBoundingClientRect();
  const offered = !b.hidden && b.style.display !== 'none';
  return { offered, shown: offered && r.width > 0 && !b.classList.contains('toolbar-collapsed'),
           collapsed: b.classList.contains('toolbar-collapsed'), pressed: b.getAttribute('aria-pressed'),
           cannot: b.classList.contains('conversation-cannot'), title: b.title, label: b.textContent.trim(),
           inside: r.width > 0 ? (r.left >= 0 && r.right <= window.innerWidth) : null };
});

// Settings → Conversation, as it is drawn.
const card = (page) => page.evaluate(() => {
  const sel = document.getElementById('conv-voice');
  const nav = document.querySelector('#settings-modal .settings-nav-item[data-settings-tab="conversation"]');
  return {
    nav: nav ? nav.textContent.trim() : null,
    heading: (document.querySelector('[data-settings-panel="conversation"] h2') || {}).textContent.trim(),
    first: sel.options.length ? [sel.options[0].value, sel.options[0].textContent] : null,
    groups: [...sel.querySelectorAll('optgroup')].map((g) => ({ label: g.label,
      options: [...g.querySelectorAll('option')].map((o) => [o.value, o.textContent, o.disabled]) })),
    value: sel.value, speed: document.getElementById('conv-speed').value,
    note: document.getElementById('conv-voice-note').textContent,
    status: document.getElementById('conv-status').textContent,
    switchOn: document.getElementById('conv-switch').checked,
    disabled: sel.disabled,
    // drawn as it is: a control that cannot be used is dimmed (`B1730`)
    dim: ['conv-voice', 'conv-speed', 'conv-preview'].map((id) => getComputedStyle(document.getElementById(id)).opacity),
  };
});

async function openCard(page, { byHand = true } = {}) {
  if (byHand) {
    await page.click('#user-bar-settings');
    await page.click('#settings-modal .settings-nav-item[data-settings-tab="conversation"]');
  } else {
    // A phone's Settings, opened where the app opens it from.
    await page.evaluate(async () => (await import('/static/js/settings.js')).open('conversation'));
  }
  await until(page, 'Settings → Conversation drew what the server offers', () => {
    const p = document.querySelector('[data-settings-panel="conversation"]');
    const sel = document.getElementById('conv-voice');
    return !!p && !p.classList.contains('hidden') && p.getBoundingClientRect().height > 0
      && sel.options.length > 0 && !!document.getElementById('conv-voice-note').textContent;
  });
}

async function closeSettings(page) {
  await page.click('#settings-modal .modal-header .close-btn');
  await until(page, 'Settings closed', () => document.getElementById('settings-modal').classList.contains('hidden'));
}

// Conversation flipped from the composer: its chip while the row shows it,
// else the + menu's Modes, where a folded chip is.
async function flipConversation(page) {
  if ((await chip(page)).shown) { await page.click('#conversation-toggle-btn'); return { via: 'chip', modes: null }; }
  await page.click('#overflow-plus-btn');
  await page.click('#overflow-modes-btn');
  const row = page.locator('.composer-submenu .composer-submenu-row', { hasText: 'Conversation' }).first();
  await row.waitFor({ state: 'visible', timeout: 15000 });
  await row.click();
  // The row stays open, redrawn with the mode's new state.
  await page.waitForTimeout(300);
  const modes = await page.evaluate(() => [...document.querySelectorAll('.composer-submenu .composer-submenu-row')]
    .map((b) => [b.textContent.replace(/\s+/g, ' ').trim(), b.getAttribute('aria-checked')]));
  await page.keyboard.press('Escape');
  await page.keyboard.press('Escape');
  await until(page, 'the + menu closed', () => {
    const m = document.getElementById('overflow-menu');
    return !m || m.classList.contains('hidden') || getComputedStyle(m).display === 'none';
  }, 10000);
  return { via: 'plus-menu', modes };
}

// A choice on the card, and the card saying it was kept.
async function keep(page, act, what) {
  await page.evaluate(() => { document.getElementById('conv-status').textContent = ''; });
  await act();
  await until(page, `${what} kept`, () => /^Kept\./.test(document.getElementById('conv-status').textContent), 30000);
}

const MENU_OPEN = () => { const m = document.getElementById('model-picker-menu'); return !!m && !m.classList.contains('hidden') && !m.classList.contains('closing'); };
async function pick(page, model) {
  await page.evaluate(() => document.activeElement && document.activeElement.blur && document.activeElement.blur());
  if (!(await page.evaluate(MENU_OPEN))) await page.click('#model-picker-btn', { timeout: 60000 });
  await until(page, 'the model picker opened', MENU_OPEN);
  const item = page.locator('.model-switch-item', { hasText: model }).first();
  await item.waitFor({ state: 'visible', timeout: 60000 });
  await item.click();
  await until(page, `${model} chosen`, (m) => {
    const label = document.getElementById('model-picker-label');
    return !window.__pantheonModelSwitchPromise && !!label && label.textContent.includes(m)
      && document.getElementById('model-picker-menu').classList.contains('hidden');
  }, 60000, model);
}

// Ask, and wait for the reply to be written in full.
async function ask(page, words, first) {
  await page.fill('#message', words);
  await page.press('#message', 'Enter');
  await until(page, `the reply to “${words}” was written`, (f) => {
    const body = [...document.querySelectorAll('.msg-ai .body')].pop();
    return !!body && body.textContent.includes(f) && !document.querySelector('.send-btn[data-mode="streaming"]');
  }, 90000, first);
}

(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const admin = { username: C.user, password: C.password };
  const member = C.member;

  // ── A member, at a desk, in the dark ──
  let { ctx, page } = await open(browser, member);
  out.chipBefore = await chip(page);
  out.statsBefore = await api(ctx, 'get', '/api/tts/stats');
  await shot(page, 'composer-member-desk-dark', await composerClip(page));

  await openCard(page);
  out.cardFresh = await card(page);
  await shot(page, 'settings-conversation-member-dark');
  await keep(page, () => page.selectOption('#conv-voice', 'kokoro:bf_emma'), 'Emma');
  out.noteEmma = (await card(page)).note;
  await keep(page, () => page.selectOption('#conv-speed', '1.1'), 'the speed');
  out.kept = (await api(ctx, 'get', '/api/prefs/conversation_voice')).value;

  // Hear it: Emma says the card's sentence, and nothing is kept by hearing.
  const heardFrom = out.synth.length;
  await page.click('#conv-preview');
  await until(page, 'Hear it spoke', () => /^Speaking with /.test(document.getElementById('conv-status').textContent), 90000);
  await until(page, 'Hear it played to its end', () => document.getElementById('conv-preview').textContent === 'Hear it'
    && window.__played.length > 0 && window.__played[window.__played.length - 1].ended, 60000);
  out.heard = { status: (await card(page)).status, synth: out.synth.slice(heardFrom),
                played: await page.evaluate(() => window.__played.slice(-1)) };
  out.keptAfterHearing = (await api(ctx, 'get', '/api/prefs/conversation_voice')).value;

  // The card's switch is the composer's chip.
  await page.click('#conv-switch + .admin-slider');
  await until(page, 'Conversation on, on the card and the chip', () =>
    document.getElementById('conv-status').textContent === 'Conversation on.'
    && document.getElementById('conversation-toggle-btn').getAttribute('aria-pressed') === 'true');
  out.switchKept = (await api(ctx, 'get', '/api/prefs/conversation')).value;
  out.cardChosen = await card(page);
  await shot(page, 'settings-conversation-member-chosen-dark');
  out.deskCard = await layout(page);
  await closeSettings(page);

  // A reply, said in Emma's voice while it is written.
  await pick(page, C.model);
  const replyFrom = out.synth.length;
  const playedFrom = await page.evaluate(() => window.__played.length);
  await ask(page, C.asked, 'The Moon is about');
  await until(page, 'every sentence of the reply was said', (n) =>
    window.__played.length >= n[0] + 3 && window.__played.slice(n[0]).every((p) => p.ended || p.error)
    && !window.aiTTSManager._processing, 120000, [playedFrom]);
  out.reply = { synth: out.synth.slice(replyFrom),
                played: await page.evaluate((n) => window.__played.slice(n), playedFrom),
                chip: await chip(page) };
  await shot(page, 'conversation-reply-desk-dark', await composerClip(page));

  // A reply in the chat brings the context meter into the composer's row, and
  // the row folds its first chip away: Conversation, still on, and the + says
  // so with its lamp, drawn where a person sees it, not only a class.
  const plusLamp = () => page.evaluate(() => {
    const b = document.getElementById('overflow-plus-btn'), d = b.querySelector('.plus-active-dot');
    const r = d ? d.getBoundingClientRect() : { width: 0, height: 0 };
    return { folded: document.getElementById('conversation-toggle-btn').classList.contains('toolbar-collapsed'),
             on: b.classList.contains('has-active'),
             lit: !!d && getComputedStyle(d).display !== 'none' && r.width >= 5 && r.height >= 5 };
  });
  out.plusDot = await plusLamp();
  // Off from where the composer shows it: the next reply is not said.
  ({ via: out.offVia, modes: out.offModes } = await flipConversation(page));
  await until(page, 'Conversation off', () => document.getElementById('conversation-toggle-btn').getAttribute('aria-pressed') === 'false');
  out.plusDotOff = await plusLamp();
  out.switchOff = (await api(ctx, 'get', '/api/prefs/conversation')).value;
  const offFrom = out.synth.length;
  await ask(page, C.askedOff, 'The Sun is the star');
  await page.waitForTimeout(2500);
  out.saidWhileOff = out.synth.slice(offFrom);
  await ctx.close();

  // ── The admin, in the light: chose no voice of their own, so hears the server's ──
  ({ ctx, page } = await open(browser, admin, { theme: 'light' }));
  await page.click('#user-bar-settings');
  await page.click('#settings-modal .settings-nav-item[data-settings-tab="voice"]');
  await until(page, 'the Voice page said what speaks', () =>
    /Speaking with Kokoro now/.test((document.getElementById('set-ttsProviderNote') || {}).textContent || ''), 60000);
  out.adminVoice = await page.evaluate(() => ({
    value: document.getElementById('set-ttsProviderSelect').value,
    label: document.getElementById('set-ttsProviderSelect').selectedOptions[0].textContent.trim(),
    note: document.getElementById('set-ttsProviderNote').textContent,
    speaker: [document.getElementById('set-ttsVoiceInput').value, document.getElementById('set-ttsVoiceInput').placeholder] }));
  await shot(page, 'settings-voice-automatic-light');
  await page.click('#settings-modal .settings-nav-item[data-settings-tab="conversation"]');
  await until(page, 'the admin\'s Conversation card drew', () => (document.getElementById('conv-voice').options || []).length > 1);
  out.adminCard = await card(page);
  await shot(page, 'settings-conversation-admin-light');
  await closeSettings(page);
  out.adminOnVia = (await flipConversation(page)).via;
  await until(page, 'the admin\'s Conversation on', () => document.getElementById('conversation-toggle-btn').getAttribute('aria-pressed') === 'true');
  await pick(page, C.model);
  const adminFrom = out.synth.length;
  const adminPlayed = await page.evaluate(() => window.__played.length);
  await ask(page, C.askedByAdmin, 'A comet is a ball');
  await until(page, 'the admin\'s reply was said', (n) =>
    window.__played.length >= n[0] + 2 && window.__played.slice(n[0]).every((p) => p.ended || p.error)
    && !window.aiTTSManager._processing, 120000, [adminPlayed]);
  out.adminReply = out.synth.slice(adminFrom);
  await shot(page, 'conversation-reply-desk-light', await composerClip(page));
  await ctx.close();

  // ── The member on a phone: the switch and the voice came with the account ──
  for (const theme of ['light', 'dark']) {
    ({ ctx, page } = await open(browser, member, { size: [390, 844], theme }));
    const phone = { chip: await chip(page), layout: await layout(page) };
    await shot(page, `composer-member-phone-${theme}`, await composerClip(page));
    await page.click('#overflow-plus-btn');
    await page.click('#overflow-modes-btn');
    await until(page, 'the Modes list opened', () => [...document.querySelectorAll('.composer-submenu button, .composer-submenu [role="menuitemcheckbox"]')]
      .some((b) => /Conversation/.test(b.textContent)), 15000);
    phone.modes = await page.evaluate(() => [...document.querySelectorAll('.composer-submenu button, .composer-submenu [role="menuitemcheckbox"]')]
      .map((b) => [b.textContent.replace(/\s+/g, ' ').trim(), b.getAttribute('aria-checked') || b.getAttribute('aria-pressed')]));
    await shot(page, `plus-modes-phone-${theme}`);
    await page.keyboard.press('Escape');
    await page.keyboard.press('Escape');
    await openCard(page, { byHand: false });
    phone.card = await card(page);
    phone.cardLayout = await layout(page);
    await shot(page, `settings-conversation-phone-${theme}`);
    out[`phone_${theme}`] = phone;
    await ctx.close();
  }

  // ── Speech off for everyone: the chip goes, and the card says why ──
  ({ ctx, page } = await open(browser, admin));
  out.offSaved = await api(ctx, 'post', '/api/auth/settings', { tts_enabled: false, tts_provider: 'disabled' });
  await ctx.close();
  ({ ctx, page } = await open(browser, member));
  out.chipOff = await chip(page);
  await openCard(page);
  out.cardOff = await card(page);
  await shot(page, 'settings-conversation-speech-off-dark');
  await ctx.close();

  await browser.close();
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e && e.stack || e); console.log(JSON.stringify(out)); process.exit(1); });
"""


@pytest.fixture(scope="module")
def drive(tmp_path_factory):
    import capture
    import httpx

    work = tmp_path_factory.mktemp("conversation")
    data = work / "data"
    data.mkdir()
    shots = Path(os.environ.get("PANTHEON_CONVERSATION_SHOTS") or (work / "shots"))
    wavs = Path(os.environ.get("PANTHEON_CONVERSATION_WAVS") or (work / "wavs"))
    shots.mkdir(parents=True, exist_ok=True)
    wavs.mkdir(parents=True, exist_ok=True)
    server = capture.Server(sys.executable, data, capture._free_port(), extra_env={
        "PANTHEON_DISABLE_MCP": "1", "PANTHEON_SEED_MODELS": str(SEED_MODELS)})
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
            endpoint = {"name": "Demo box", "base_url": model.base_url, "supports_tools": "true",
                        "require_models": "true"}
            # Shared, as an endpoint is unless an admin says otherwise: the
            # member chats with it too.
            seed._ok(client.post("/api/model-endpoints", data=endpoint), "the model")
            config = {"base": server.base, "user": seed.PERSON["username"], "password": password,
                      "member": MEMBER, "model": demo_model.MODEL_ID, "asked": ASKED, "askedOff": ASKED_OFF,
                      "askedByAdmin": ASKED_BY_ADMIN, "shots": str(shots), "wavs": str(wavs)}
            (work / "config.json").write_text(json.dumps(config))
            (work / "drive.cjs").write_text(_DRIVE)
            proc = subprocess.run([NODE, str(work / "drive.cjs"), str(work / "config.json")],
                                  capture_output=True, text=True, timeout=1200, cwd=ROOT)
            assert proc.returncode == 0, proc.stderr[-4000:] + "\n" + server.log_path.read_text(
                encoding="utf-8", errors="replace")[-2000:]
            out = json.loads(proc.stdout.strip().splitlines()[-1])
        yield out
    finally:
        server.stop()


def _sentences(text):
    import re
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def test_a_member_is_offered_the_conversation_chip_off_with_the_server_speaking(drive):
    c = drive["chipBefore"]
    assert (c["offered"], c["shown"], c["pressed"], c["cannot"]) == (True, True, "false", False), c
    assert c["label"] == "Conversation" and c["inside"] is True
    assert c["title"] == "Conversation: the agent says its replies out loud"
    stats = drive["statsBefore"]
    assert (stats["chosen"], stats["provider"], stats["voice"], stats["available"]) == (
        "auto", "kokoro", "af_heart", True), "a fresh install speaks with Kokoro, baked where the image bakes it"
    assert drive["errors"] == [], drive["errors"]


def test_settings_conversation_offers_kokoros_voices_by_language_and_this_devices(drive):
    card = drive["cardFresh"]
    assert card["nav"] == "Conversation" and card["heading"] == "Conversation"
    assert card["dim"] == ["1", "1", "1"], "everything here can be used"
    assert card["first"] == ["", "Pantheon’s voice (Kokoro, Heart · American English, woman)"]
    labels = [g["label"] for g in card["groups"]]
    assert labels[:7] == ["Kokoro · American English", "Kokoro · British English", "Kokoro · Spanish",
                          "Kokoro · French", "Kokoro · Hindi", "Kokoro · Italian",
                          "Kokoro · Brazilian Portuguese"], labels
    british = card["groups"][1]["options"]
    assert ["kokoro:bf_emma", "Emma · British English, woman", False] in british
    assert sum(len(g["options"]) for g in card["groups"][:7]) == 41
    chatterbox = next(g for g in card["groups"] if g["label"].startswith("Chatterbox"))
    assert chatterbox["options"] == [["chatterbox:", "Chatterbox is not running here", True]], (
        "no GPU sidecar on this install: shown, and not choosable")
    assert card["groups"][-1] == {"label": "This device’s voices", "options": [
        ["browser:Samantha", "Samantha", False], ["browser:Daniel", "Daniel", False]]}
    assert (card["value"], card["speed"], card["switchOn"]) == ("", "", False)
    assert card["note"].startswith("The voice an admin chose for everyone")


def test_a_voice_and_a_speed_are_kept_with_the_account_and_hearing_keeps_nothing(drive):
    assert drive["kept"] == {"engine": "kokoro", "voice": "bf_emma", "speed": 1.1}
    assert drive["noteEmma"] == "Kokoro speaks on this server’s own processor, so a reply’s words stay here."
    heard = drive["heard"]
    assert heard["status"] == "Speaking with Kokoro, Emma · British English, woman.", heard["status"]
    (said,) = heard["synth"]
    assert said["status"] == 200 and said["voice"] == "kokoro/bf_emma" and said["type"] == "audio/wav"
    assert said["preview"] is True and said["asked"] == {"engine": "kokoro", "voice": "bf_emma", "speed": 1.1}
    assert said["rate"] == 24000 and 2.5 < said["seconds"] < 12, said
    assert heard["played"][0]["ended"] is True and heard["played"][0]["error"] is None
    assert drive["keptAfterHearing"] == drive["kept"]


def test_the_cards_switch_is_the_chip_and_is_kept_with_the_account(drive):
    assert drive["switchKept"] is True
    assert drive["cardChosen"]["switchOn"] is True and drive["cardChosen"]["value"] == "kokoro:bf_emma"
    assert drive["deskCard"]["sideways"] is False and drive["deskCard"]["panel"] is True


def test_a_reply_is_said_sentence_by_sentence_in_the_voice_the_member_chose(drive):
    reply = drive["reply"]
    said = [s for s in reply["synth"] if not s["preview"]]
    assert [s["text"] for s in said] == _sentences(ANSWER), [s["text"] for s in said]
    for s in said:
        assert (s["status"], s["voice"], s["rate"]) == (200, "kokoro/bf_emma", 24000), s
        assert s["asked"] == {"engine": None, "voice": None, "speed": None}, "the server reads whose voice it is"
        assert 1.0 < s["seconds"] < 10, s
    assert len(reply["played"]) == 3 and all(p["ended"] and not p["error"] for p in reply["played"]), reply["played"]
    assert reply["chip"]["pressed"] == "true"


def test_turned_off_from_the_composer_the_next_reply_is_not_said(drive):
    # The reply brought the context meter into the row, which folded the
    # chip into the + menu (this window's chat column has no room for it):
    # on, and the + lights its lamp, drawn, so a person sees it.
    assert drive["plusDot"] == {"folded": True, "on": True, "lit": True}, \
        f"a mode that is on is visible somewhere: {drive['plusDot']}"
    assert drive["offVia"] in ("chip", "plus-menu")
    if drive["offVia"] == "plus-menu":
        assert ["ConversationReplies said out loud", "false"] in drive["offModes"], drive["offModes"]
    assert drive["plusDotOff"]["on"] is False and drive["plusDotOff"]["lit"] is False, \
        f"nothing in the menu is on any more: {drive['plusDotOff']}"
    assert drive["switchOff"] is False
    assert drive["saidWhileOff"] == []


def test_the_admin_who_chose_no_voice_hears_the_servers_kokoro_heart(drive):
    voice = drive["adminVoice"]
    assert voice["value"] == "auto" and voice["label"].startswith("Automatic")
    assert "Speaking with Kokoro now" in voice["note"] and "Heart" in voice["note"], voice["note"]
    # The stored speaker is still `alloy`, an endpoint's, which no engine here
    # has: the field shows the voice that speaks instead of that name.
    assert voice["speaker"] == ["", "af_heart"], voice["speaker"]
    said = drive["adminReply"]
    assert [s["text"] for s in said] == _sentences(ANSWER_BY_ADMIN)
    assert all(s["voice"] == "kokoro/af_heart" and s["status"] == 200 for s in said), said
    card = drive["adminCard"]
    assert card["value"] == "" and card["first"][1].startswith("Pantheon’s voice (Kokoro, Heart")


def test_on_a_phone_the_voice_came_with_the_account_and_the_chip_is_in_the_plus_menu(drive):
    for theme in ("light", "dark"):
        phone = drive[f"phone_{theme}"]
        assert phone["layout"]["sideways"] is False and phone["layout"]["send"] is True, phone["layout"]
        assert phone["chip"]["offered"] is True and phone["chip"]["pressed"] == "false", phone["chip"]
        assert phone["chip"]["shown"] or phone["chip"]["collapsed"], phone["chip"]
        assert any(label.startswith("Conversation") for label, _state in phone["modes"]), phone["modes"]
        card = phone["card"]
        assert (card["value"], card["speed"], card["switchOn"]) == ("kokoro:bf_emma", "1.1", False), card
        assert phone["cardLayout"]["sideways"] is False and phone["cardLayout"]["panel"] is True, phone["cardLayout"]


def test_speech_off_for_everyone_takes_the_chip_away_and_the_card_says_why(drive):
    assert drive["offSaved"] == 200
    assert drive["chipOff"]["offered"] is False
    card = drive["cardOff"]
    assert card["disabled"] is True and card["first"] == ["", "No voice: speech is off on this server"]
    assert card["dim"] == ["0.5", "0.5", "0.5"], "drawn as it is: nothing here can be used"
    assert "an admin chose “None” in Settings → Voice" in card["note"]


def test_every_picture_was_taken(drive):
    assert len(drive["shots"]) == 14, drive["shots"]
    assert drive["errors"] == [], drive["errors"]
