// SPDX-License-Identifier: AGPL-3.0-or-later
// tourAutoplay.js — auto-fires the matching `/tour-<x>` slash command the
// first time the user opens a tool modal. One-shot per modal: dismissed or
// not, the marker is set so reopens never auto-trigger again.
//
// Pairs with the existing tourHints.js (which shows a single global "drag
// title bar to snap" hint). Tours are richer per-feature walkthroughs.
//
// Mobile is excluded — tours position halos by rect math that doesn't fit
// the bottom-sheet layout cleanly.
//
// This was switched off between 2025 and 2026-09-08 with the note "Disabled for
// v1 stability: opening ordinary app windows must never auto-spawn tour
// overlays or interfere with close/backdrop behavior", and nobody recorded what
// the instability was. `P3-10b` found it, and it was not the overlays:
// `handleSlashCommand` echoes the command as a **user message and persists it**,
// and `_persistMsg` materialises a pending session when there is none — so
// opening Settings for the first time on a fresh install created a chat in the
// sidebar containing `/tour-settings`, a command the user never typed. Firing a
// tour is now explicitly `{ echo: false, persist: false }`.
//
// Four gates decide whether a tour may play, and three of them deliberately do
// **not** mark the tour seen, so a walkthrough skipped because the moment was
// wrong is still waiting the next time the moment is right:
//
//   preference   the user turned first-run tours off (Settings → Appearance)
//   mobile       the header has always claimed this and never implemented it
//   composer     there is a draft in the chat box — every tour begins by
//                clearing it, which is right when you typed the command there
//                and is destroying your work when you did not
//   setup        the first-run setup wizard owns the screen
//
// Only the preference gate marks nothing and re-reads live, so turning tours
// back on in Settings takes effect without a reload.

import { handleSlashCommand, getSetupMode } from './slashCommands.js?v=20260815approvalsave1';
import uiModule from './ui.js';

// Modal id → slash command to fire (without the leading "/"). Add to this
// map when a new feature picks up a `tour-*` command.
const TOUR_FOR_MODAL = {
  'doclib-modal':           'tour-library',
  'cookbook-modal':         'tour-cookbook',
  'research-overlay':       'tour-research',
  'compare-model-overlay':  'tour-compare',
  'theme-modal':            'tour-theme',
  'settings-modal':         'tour-settings',
  'gallery-modal':          'tour-gallery',
};

const SEEN_KEY = (tour) => `pantheon-tour-autoplay-seen-${tour}`;

// Settings → Appearance writes this into the shared UI-preferences map that
// `app.js` owns (`loadUIVis`/`saveUIVis`). Read through the same key here, at
// fire time rather than at boot, so switching tours off takes effect at once.
// Absent means on: a preference nobody has expressed is the default, and the
// default for onboarding is that it happens.
export const TOURS_ENABLED_KEY = 'first-run-tours';
const UI_VIS_STORAGE_KEY = 'pantheon-ui-visibility';

// The one width the product agrees on (`B50` / `P3-07`).
const MOBILE_MAX_WIDTH = 768;

export function toursEnabled() {
  try {
    const raw = localStorage.getItem(UI_VIS_STORAGE_KEY);
    if (!raw) return true;
    return JSON.parse(raw)[TOURS_ENABLED_KEY] !== false;
  } catch (_) {
    return true;
  }
}

/** Clears every per-tour marker, so the walkthroughs play again. */
export function resetSeenTours() {
  Object.values(TOUR_FOR_MODAL).forEach(tour => {
    try { localStorage.removeItem(SEEN_KEY(tour)); } catch (_) {}
  });
}

function _composerHasDraft() {
  const el = document.getElementById('message');
  return !!(el && String(el.value || '').trim());
}

function _isMobile() {
  return window.innerWidth <= MOBILE_MAX_WIDTH;
}

let _initialized = false;
// Suppress re-fire if a tour is already active or another modal opens while
// we're mid-tour. The slash command itself adds `body.tour-active` for the
// duration of its halos.
function _tourActive() {
  return document.body.classList.contains('tour-active');
}

function _isVisible(el) {
  if (!el || el.classList.contains('hidden')) return false;
  if (el.style.display === 'none') return false;
  const r = el.getBoundingClientRect();
  return r.width > 0 && r.height > 0;
}

async function _maybeFire(modal) {
  const id = modal.id;
  const tour = TOUR_FOR_MODAL[id];
  if (!tour) return;
  if (_tourActive()) {
    try { window.cancelActiveTour?.('modal-opened'); } catch (_) {}
    return;
  }
  // The three "wrong moment" gates. None of them marks the tour seen — a
  // walkthrough skipped because the window was narrow, or because there was a
  // half-written message in the composer, is one the user has still never had.
  if (!toursEnabled()) return;
  if (_isMobile()) return;
  if (_composerHasDraft()) return;
  try { if (getSetupMode()) return; } catch (_) {}
  let seen = false;
  try { seen = localStorage.getItem(SEEN_KEY(tour)) === '1'; } catch (_) {}
  if (seen) return;
  // Mark immediately so a quick double-trigger (e.g. modal-class observer
  // fires twice during animation) can't queue two tours.
  try { localStorage.setItem(SEEN_KEY(tour), '1'); } catch (_) {}
  // Let the modal's own enter-animation settle before halos try to position
  // off the title bar / first card / etc. ~400ms matches tourHints.
  setTimeout(() => {
    if (_tourActive()) return;
    try {
      // Not conversation: no echoed command, nothing written to the session.
      handleSlashCommand('/' + tour, { echo: false, persist: false });
    } catch (e) {
      // If firing fails we don't unmark — re-attempting on every modal open
      // would be more annoying than a missed tour. User can run `/tour-x`
      // manually from the chat input.
      // eslint-disable-next-line no-console
      console.warn(`Tour autoplay failed for ${id}:`, e);
    }
  }, 400);
}

function _watchModals() {
  if (typeof MutationObserver === 'undefined') return;
  const observer = new MutationObserver((muts) => {
    for (const m of muts) {
      if (m.attributeName !== 'class' && m.attributeName !== 'style') continue;
      const el = m.target;
      if (!(el instanceof HTMLElement)) continue;
      if (!(el.id in TOUR_FOR_MODAL)) continue;
      const wasHidden = !m.oldValue
        || /\bhidden\b/.test(m.oldValue)
        || /display:\s*none/.test(m.oldValue);
      if (wasHidden && _isVisible(el)) _maybeFire(el);
    }
  });
  // Observe each known target if it exists at boot…
  Object.keys(TOUR_FOR_MODAL).forEach(id => {
    const el = document.getElementById(id);
    if (el) {
      observer.observe(el, {
        attributes: true,
        attributeOldValue: true,
        attributeFilter: ['class', 'style'],
      });
    }
  });
  // …and also for any matching modal added later (research overlay is
  // appended on demand, for example).
  const docObserver = new MutationObserver((muts) => {
    for (const m of muts) {
      m.addedNodes.forEach(node => {
        if (!(node instanceof HTMLElement)) return;
        if (node.id in TOUR_FOR_MODAL) {
          observer.observe(node, {
            attributes: true,
            attributeOldValue: true,
            attributeFilter: ['class', 'style'],
          });
          if (_isVisible(node)) _maybeFire(node);
        }
      });
    }
  });
  docObserver.observe(document.body, { childList: true, subtree: false });
}

// Settings → Appearance carries the "Show again" button next to the tours
// toggle. It is bound here rather than in `settings.js` because this module
// owns the markers it clears, and because importing this file from there would
// close a cycle: settings.js -> tourAutoplay.js -> slashCommands.js ->
// settings.js. `P3-11` is this project's record of what module-identity trouble
// costs, so the cycle is worth one comment in each file to avoid.
function _bindReplayButton() {
  const btn = document.getElementById('set-replay-tours');
  if (!btn || btn.dataset.tourReplayBound === '1') return;
  btn.dataset.tourReplayBound = '1';
  btn.addEventListener('click', () => {
    resetSeenTours();
    // Resetting while the preference is off would clear the markers and show
    // nothing, which reads as a broken button. Turn tours back on, through the
    // checkbox, so the preference is saved by the handler that owns it.
    const toggle = document.querySelector('[data-ui-key="' + TOURS_ENABLED_KEY + '"]');
    if (toggle && !toggle.checked) {
      toggle.checked = true;
      toggle.dispatchEvent(new Event('change', { bubbles: true }));
    }
    try { uiModule?.showToast?.('Walkthroughs reset — open a tool to see its tour.'); } catch (_) {}
  });
}

export function init() {
  // The observers go on once — a second set fires every tour twice. The
  // button binding must NOT sit behind that latch: this module can be imported
  // before the Settings markup exists, and then the single call that would
  // have bound it is the one that returned early. `_bindReplayButton` carries
  // its own guard, so calling `init()` again is safe and does the right thing.
  if (!_initialized) {
    _initialized = true;
    // The observers are always attached; `_maybeFire` decides. Gating here
    // instead would freeze the preference at page load, so a user who turned
    // tours back on would have to reload to see one.
    _watchModals();
  }
  _bindReplayButton();
}

if (typeof window !== 'undefined') {
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
}

export default { init, toursEnabled, resetSeenTours, TOURS_ENABLED_KEY };
