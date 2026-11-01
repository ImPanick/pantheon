// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/reactions.js
//
// `B1736`. Emoji reactions, both ways.
//
//   * The person reacts to a reply from its footer (the smile button) or from
//     the reaction pill under it. One reaction per reply; picking the same one
//     again takes it off. Saved through POST /api/session/{id}/react, and the
//     model hears of it on its next turn (src/message_reactions.py).
//   * The model reacts to the person's message by opening its reply with a
//     hidden marker; the server sends a `reaction` event (chat.js) and saves it
//     on the person's message. It shows as a small badge on the bubble's corner.
//
// Emoji are drawn as the product's own monochrome line glyphs (svgifyEmoji),
// never colour, so a reaction reads as part of the cockpit, not a sticker.

import uiModule from './ui.js';
import { svgifyEmoji } from './markdown.js';
import { bindMenuDismiss } from './escMenuStack.js';
import { prefersReducedMotion } from './motion.js';

/** Mirrors `USER_REACTIONS` / `MODEL_REACTIONS` in `src/message_reactions.py`
 *  (a test pins them equal). */
export const USER_REACTIONS = ['👍', '❤️', '😂', '🎉', '🤔', '👎'];
export const MODEL_REACTIONS = ['👍', '❤️', '😂', '🎉', '🤔'];

const NAMES = {
  '👍': 'Thumbs up',
  '❤️': 'Heart',
  '😂': 'Laugh',
  '🎉': 'Celebrate',
  '🤔': 'Hmm',
  '👎': 'Thumbs down',
};
/** What a model reaction says, on hover. */
const MODEL_MEANING = {
  '👍': 'acknowledged',
  '❤️': 'loved the detail',
  '😂': 'laughed',
  '🎉': 'celebrated',
  '🤔': 'is mulling it over',
};

const SMILE_ICON = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20.8 11.2A8.8 8.8 0 1 1 12.8 3.2"/><path d="M8.5 14.5c.9 1.1 2.1 1.7 3.5 1.7s2.6-.6 3.5-1.7"/><path d="M9 9.5h.01M15 9.5h.01"/><path d="M19 2.5v5M16.5 5h5"/></svg>';

function glyph(emoji) {
  return svgifyEmoji(uiModule.esc(String(emoji)));
}


// The open chat's id, told by chat.js (`useSessionId`). Not an import of
// sessions.js: the renderer imports this module, and its node harness stubs
// only what the renderer itself names.
let _sessionId = () => null;
export function useSessionId(fn) {
  if (typeof fn === 'function') _sessionId = fn;
}

function sessionId() {
  try { return _sessionId(); } catch { return null; }
}

/** The saved id of the reply a footer sits under. An agent reply drawn as
 *  several bubbles carries its id on each; a live one may have it only on an
 *  earlier bubble of the same turn. */
export function replyIdFor(msgElement) {
  if (!msgElement) return '';
  if (msgElement.dataset && msgElement.dataset.dbId) return msgElement.dataset.dbId;
  let el = msgElement.previousElementSibling;
  while (el) {
    if (el.classList && el.classList.contains('msg-user')) break;
    if (el.classList && el.classList.contains('msg-ai') && el.dataset.dbId) return el.dataset.dbId;
    el = el.previousElementSibling;
  }
  return '';
}

function reactionsOf(msgElement) {
  const r = msgElement && msgElement._reactions;
  return (r && typeof r === 'object') ? r : {};
}

// ── the person's reaction on a reply ───────────────────────────────────────

/** The pill under a reply showing the person's reaction; empty when none. */
export function renderReplyReaction(msgElement) {
  if (!msgElement) return null;
  let pill = msgElement.querySelector(':scope > .msg-reaction-pill');
  const emoji = reactionsOf(msgElement).user;
  if (!emoji) {
    if (pill) pill.remove();
    return null;
  }
  if (!pill) {
    pill = document.createElement('button');
    pill.type = 'button';
    pill.className = 'msg-reaction-pill';
    pill.addEventListener('click', (e) => {
      e.stopPropagation();
      openPalette(pill, msgElement);
    });
    const footer = msgElement.querySelector(':scope > .msg-footer');
    if (footer) msgElement.insertBefore(pill, footer); else msgElement.appendChild(pill);
  }
  pill.innerHTML = `<span class="msg-reaction-glyph">${glyph(emoji)}</span><span class="msg-reaction-label">You</span>`;
  pill.title = `You reacted ${NAMES[emoji] || emoji}. Click to change it.`;
  pill.setAttribute('aria-label', `Your reaction: ${NAMES[emoji] || emoji}. Change it`);
  return pill;
}

async function saveReaction(msgElement, emoji) {
  const sid = sessionId();
  const msgId = replyIdFor(msgElement);
  if (!sid || !msgId) {
    uiModule.showError('That reply has no saved copy on this page yet. Reload the chat, then react.');
    return false;
  }
  const before = { ...reactionsOf(msgElement) };
  // Drawn first, so the click feels instant; put back if the save fails.
  msgElement._reactions = { ...before };
  if (emoji) msgElement._reactions.user = emoji; else delete msgElement._reactions.user;
  renderReplyReaction(msgElement);
  pop(msgElement.querySelector(':scope > .msg-reaction-pill'));
  try {
    const res = await fetch(`${window.location.origin}/api/session/${encodeURIComponent(sid)}/react`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ msg_id: msgId, emoji: emoji || null }),
    });
    if (!res.ok) {
      let sentence = 'Could not save that reaction. Try again.';
      try { const j = await res.json(); if (j && typeof j.detail === 'string') sentence = j.detail; } catch { /* keep */ }
      throw new Error(sentence);
    }
    return true;
  } catch (err) {
    msgElement._reactions = before;
    renderReplyReaction(msgElement);
    uiModule.showError(err && err.message ? err.message : 'Could not reach Pantheon to save that reaction.');
    return false;
  }
}

function closePalette() {
  const open = document.querySelector('.reaction-palette');
  if (open) {
    if (typeof open._dismiss === 'function') open._dismiss(); else open.remove();
  }
  return open;
}

/** The six-emoji palette, above `anchor`. */
export function openPalette(anchor, msgElement) {
  const existing = closePalette();
  if (existing && existing._trigger === anchor) return null;
  const current = reactionsOf(msgElement).user;
  const palette = document.createElement('div');
  palette.className = 'reaction-palette ck-pop';
  palette.setAttribute('role', 'menu');
  palette.setAttribute('aria-label', 'React to this reply');
  let close = () => palette.remove();
  USER_REACTIONS.forEach((emoji, i) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'reaction-option' + (emoji === current ? ' is-picked' : '');
    b.setAttribute('role', 'menuitemradio');
    b.setAttribute('aria-checked', emoji === current ? 'true' : 'false');
    b.title = emoji === current ? `${NAMES[emoji]} (click to take it off)` : NAMES[emoji];
    b.setAttribute('aria-label', b.title);
    b.style.setProperty('--i', String(i));
    b.innerHTML = glyph(emoji);
    b.addEventListener('click', (e) => {
      e.stopPropagation();
      close();
      saveReaction(msgElement, emoji === current ? null : emoji);
    });
    palette.appendChild(b);
  });
  palette._trigger = anchor;
  document.body.appendChild(palette);
  const r = anchor.getBoundingClientRect();
  const w = palette.offsetWidth;
  const h = palette.offsetHeight;
  let top = r.top - h - 6;
  if (top < 8) top = r.bottom + 6;
  let left = r.left + r.width / 2 - w / 2;
  left = Math.max(8, Math.min(left, window.innerWidth - w - 8));
  palette.style.top = `${top}px`;
  palette.style.left = `${left}px`;
  close = bindMenuDismiss(palette, () => palette.remove(),
    (ev) => !palette.contains(ev.target) && ev.target !== anchor && !anchor.contains(ev.target));
  const first = palette.querySelector('.reaction-option.is-picked') || palette.querySelector('.reaction-option');
  if (first) first.focus({ preventScroll: true });
  palette.addEventListener('keydown', (e) => {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
    const opts = Array.from(palette.querySelectorAll('.reaction-option'));
    const at = opts.indexOf(document.activeElement);
    const next = opts[(at + (e.key === 'ArrowRight' ? 1 : opts.length - 1)) % opts.length];
    if (next) { e.preventDefault(); next.focus(); }
  });
  return palette;
}

/** The smile button at the head of a reply's actions. */
export function reactButton(msgElement) {
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'msg-action-btn msg-react-btn';
  btn.dataset.action = 'react';
  btn.title = 'React';
  btn.setAttribute('aria-label', 'React to this reply');
  btn.innerHTML = SMILE_ICON;
  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    openPalette(btn, msgElement);
  });
  return btn;
}

// ── the model's reaction on the person's message ───────────────────────────

/** The badge on a person's bubble showing the model's reaction. */
export function renderModelReaction(userElement, { animate = false } = {}) {
  if (!userElement) return null;
  let badge = userElement.querySelector(':scope > .msg-reaction-badge');
  const emoji = reactionsOf(userElement).assistant;
  if (!emoji) {
    if (badge) badge.remove();
    return null;
  }
  if (!badge) {
    badge = document.createElement('span');
    badge.className = 'msg-reaction-badge';
    badge.setAttribute('role', 'img');
    userElement.appendChild(badge);
  }
  badge.innerHTML = glyph(emoji);
  const said = `Pantheon ${MODEL_MEANING[emoji] || 'reacted'}`;
  badge.title = said;
  badge.setAttribute('aria-label', `${said} (${NAMES[emoji] || emoji})`);
  if (animate) pop(badge);
  return badge;
}

/** The live stream's `reaction` event: the model reacted to `userElement`. */
export function showModelReaction(userElement, emoji) {
  if (!userElement || !MODEL_REACTIONS.includes(emoji)) return null;
  userElement._reactions = { ...reactionsOf(userElement), assistant: emoji };
  return renderModelReaction(userElement, { animate: true });
}

function pop(el) {
  if (!el || prefersReducedMotion()) return;
  el.classList.remove('reaction-popping');
  void el.offsetWidth;
  el.classList.add('reaction-popping');
  el.addEventListener('animationend', () => el.classList.remove('reaction-popping'), { once: true });
}

/** Draw whatever reactions a bubble's saved metadata carries. */
export function drawSavedReactions(msgElement, metadata) {
  if (!msgElement) return;
  const r = metadata && metadata.reactions;
  if (!r || typeof r !== 'object') return;
  msgElement._reactions = { ...r };
  if (msgElement.classList.contains('msg-user')) renderModelReaction(msgElement);
  else renderReplyReaction(msgElement);
}

// ── the person's switch (Settings → Chat Area → Reactions) ─────────────────

const PREF = 'reactions_enabled';

/** Binds the Settings switch to the person's `reactions_enabled` preference.
 *  Off, the agent is not offered a reaction and is not told of the person's;
 *  the person can still react, and what they left stays drawn. */
export async function bindReactionsSwitch(root = document) {
  const toggle = root && root.getElementById ? root.getElementById('reactions-toggle') : null;
  if (!toggle || toggle.dataset.bound) return;
  toggle.dataset.bound = '1';
  try {
    const res = await fetch(`${window.location.origin}/api/prefs/${PREF}`);
    if (res.ok) {
      const data = await res.json();
      toggle.checked = !(data && data.value === false);
    }
  } catch { /* stays as drawn: on */ }
  toggle.addEventListener('change', async () => {
    const want = toggle.checked;
    try {
      const res = await fetch(`${window.location.origin}/api/prefs/${PREF}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ value: want }),
      });
      if (!res.ok) throw new Error(String(res.status));
      uiModule.showToast(want ? 'Reactions on' : 'Reactions off');
    } catch {
      toggle.checked = !want;
      uiModule.showError('Could not save that. Try again.');
    }
  });
}

if (typeof document !== 'undefined') {
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => { bindReactionsSwitch(); }, { once: true });
  } else {
    bindReactionsSwitch();
  }
}

export default {
  bindReactionsSwitch,
  useSessionId,
  USER_REACTIONS,
  MODEL_REACTIONS,
  reactButton,
  openPalette,
  renderReplyReaction,
  renderModelReaction,
  showModelReaction,
  drawSavedReactions,
  replyIdFor,
};
