// SPDX-License-Identifier: AGPL-3.0-or-later
// Pip is an opt-in, local ASCII companion. Model events can choose one of four
// expressions; they cannot supply markup, script, dialogue, or storage values.
import Storage from './storage.js';
import { prefersReducedMotion } from './motion.js';

const KEY = 'pantheon-companion-enabled';
const POSES = Object.freeze({
  greet: { face: '( ^>^ )', line: 'Pip is glad you stopped by.' },
  cheer: { face: '( *>*)', line: 'Pip is rooting for you.' },
  ponder: { face: '( o>o )', line: 'Pip is thinking it over.' },
  rest: { face: '( ->- )', line: 'Pip is taking a tiny break.' },
});
let resetTimer = null;

function placeCompanion() {
  const stage = document.getElementById('companion-stage');
  const composer = document.querySelector?.('.chat-input-bar');
  if (!stage || stage.hidden || !composer || typeof window === 'undefined') return;
  // Keep the CSS edge position until the composer actually reaches Pip's column.
  stage.style.bottom = '';
  const pip = stage.getBoundingClientRect();
  const input = composer.getBoundingClientRect();
  if (pip.left < input.right && pip.right > input.left && pip.bottom > input.top && pip.top < input.bottom) {
    stage.style.bottom = `${Math.ceil(window.innerHeight - input.top + 12)}px`;
  }
}

export function isCompanionEnabled() {
  return Storage.get(KEY, 'off') === 'on';
}

function renderEnabled() {
  const stage = document.getElementById('companion-stage');
  const toggle = document.getElementById('companion-toggle');
  const enabled = isCompanionEnabled();
  if (stage) stage.hidden = !enabled;
  if (toggle) toggle.checked = enabled;
  if (!enabled && resetTimer) { clearTimeout(resetTimer); resetTimer = null; }
  if (enabled) placeCompanion();
}

export function setCompanionEnabled(enabled) {
  Storage.set(KEY, enabled ? 'on' : 'off');
  renderEnabled();
  if (enabled) companionAction('rest');
}

export function companionAction(action) {
  if (!isCompanionEnabled() || !Object.hasOwn(POSES, action)) return false;
  const stage = document.getElementById('companion-stage');
  if (!stage) return false;
  const face = stage.querySelector('.companion-face');
  const line = stage.querySelector('.companion-line');
  if (!face || !line) return false;
  if (resetTimer) clearTimeout(resetTimer);
  face.textContent = POSES[action].face;
  line.textContent = POSES[action].line;
  stage.dataset.pose = action;
  // Repeated actions replace the previous one. No frame loop or model call.
  if (action !== 'rest') {
    resetTimer = setTimeout(() => {
      resetTimer = null;
      if (isCompanionEnabled()) companionAction('rest');
    }, prefersReducedMotion() ? 2500 : 5000);
  }
  return true;
}

export function initCompanion() {
  const toggle = document.getElementById('companion-toggle');
  const stage = document.getElementById('companion-stage');
  if (!toggle || !stage || toggle.dataset.bound === '1') return;
  toggle.dataset.bound = '1';
  toggle.addEventListener('change', () => setCompanionEnabled(toggle.checked));
  stage.querySelector('.companion-character')?.addEventListener('click', () => companionAction('greet'));
  stage.querySelector('.companion-cheer')?.addEventListener('click', () => companionAction('cheer'));
  stage.querySelector('.companion-rest')?.addEventListener('click', () => companionAction('rest'));
  stage.querySelector('.companion-hide')?.addEventListener('click', () => setCompanionEnabled(false));
  const composer = document.querySelector?.('.chat-input-bar');
  if (composer && typeof ResizeObserver !== 'undefined') new ResizeObserver(placeCompanion).observe(composer);
  if (typeof window !== 'undefined') window.addEventListener('resize', placeCompanion);
  renderEnabled();
  if (isCompanionEnabled()) companionAction('rest');
}

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initCompanion);
else initCompanion();
