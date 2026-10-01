// SPDX-License-Identifier: AGPL-3.0-or-later
export const TOOL_WINDOW_SELECTOR = 'body > .modal, body > .research-overlay, body > .notes-pane-backdrop';

// `B1068` — the z a window was given, not the one it is passing through.
// Under `prefers-reduced-motion`, `P1-12`'s guard (style.css) gives every
// element a 0.01ms transition, and on a window whose `transition-property` is
// the initial `all` — the Workbench and the Forge — that includes `z-index`:
// until a frame is painted, `getComputedStyle().zIndex` answers the value it
// is moving FROM. `ui.js`'s auto-promote read it inside its own
// MutationObserver, never saw the window on top, and raised it again, forever,
// in microtasks: measured 501 writes before a probe's breaker, no frame ever
// painted, the tab frozen. Every z this product gives a window is written
// inline with `!important`, which nothing but a transition outranks, so that
// is the settled value; a window without one is read as before. `NaN` when
// neither says (callers already treat that as 0).
export function toolWindowZ(el, getStyle = globalThis.getComputedStyle) {
  const own = el?.style;
  if (own && typeof own.getPropertyPriority === 'function'
      && own.getPropertyPriority('z-index') === 'important') {
    const z = parseInt(own.getPropertyValue('z-index'), 10);
    if (Number.isFinite(z)) return z;
  }
  return typeof getStyle === 'function' ? parseInt(getStyle(el).zIndex, 10) : NaN;
}

export function topToolWindowZ(options = {}) {
  const {
    exclude = null,
    root = globalThis.document,
    getStyle = globalThis.getComputedStyle,
    floor = 250,
  } = options;
  let top = floor;
  if (!root || typeof root.querySelectorAll !== 'function' || typeof getStyle !== 'function') return top;
  root.querySelectorAll(TOOL_WINDOW_SELECTOR).forEach(el => {
    if (!el || el === exclude) return;
    if (el.classList?.contains('hidden') || el.classList?.contains('modal-minimized')) return;
    const cs = getStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') return;
    const z = toolWindowZ(el, () => cs);
    if (Number.isFinite(z)) top = Math.max(top, z);
  });
  return top;
}

export function nextToolWindowZ(options = {}) {
  const { current = null } = options;
  const top = topToolWindowZ(options);
  const currentZ = parseInt(current, 10);
  if (Number.isFinite(currentZ) && currentZ > top) return currentZ;
  return top + 1;
}

// Dock chips pinned by the minimized-dock drag interactions reach z 10030
// (free-drag) / 10020 (mobile rest) — see modalManager.js. A body-portaled
// dropdown has to clear those too, not just the open tool-window stack, so this
// floor keeps it above a chip even when no modal is currently raised.
const DOCK_OVERLAY_FLOOR = 10030;

// The z a body-portaled dropdown/menu needs so it always sits just above every
// open tool window (and the dock chips) right now. Tool modals get a
// monotonically increasing z from the bring-to-front counter (modalManager),
// which climbs unbounded over a long session — so the hardcoded `z-index: 10001`
// these dropdowns historically used eventually rendered them BEHIND their own
// modal (#4720). Derive the value from the live stack instead, sharing the same
// single source of truth as nextToolWindowZ().
export function topPortalZ(options = {}) {
  return Math.max(topToolWindowZ(options), DOCK_OVERLAY_FLOOR) + 1;
}
