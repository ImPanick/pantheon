// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/escMenuStack.js
//
// Dismissal registry for transient, ad-hoc overlays — dropdown menus and
// context popups that are built on the fly and appended to <body>, living
// OUTSIDE the .modal system. The global Escape arbiter in ui.js can find
// modals but not these, so each menu registers a dismiss callback here while
// it is open and unregisters when it closes.
//
// The stack is LIFO: dismissTopMenu() closes the most-recently-opened menu
// first, so a dropdown opened on top of a modal closes before the modal does.
// Deliberately DOM-free so it can be unit-tested under plain node (see
// tests/test_esc_menu_stack_js.py).

const _stack = [];

/**
 * Register a menu's dismiss callback. Returns an unregister function that the
 * menu MUST call from its own teardown (outside-click close, item click, etc.)
 * so the stack never holds a stale entry. Calling the returned function more
 * than once, or after the menu was already dismissed via Escape, is safe.
 */
export function registerMenuDismiss(dismissFn) {
  if (typeof dismissFn !== 'function') return () => {};
  const entry = { dismissFn };
  _stack.push(entry);
  return () => {
    const i = _stack.indexOf(entry);
    if (i !== -1) _stack.splice(i, 1);
  };
}

/**
 * Dismiss the most-recently-registered menu, if any. Returns true when a menu
 * was dismissed (so the caller can swallow the Escape key), false when nothing
 * was open. The entry is popped BEFORE its callback runs, so even if a
 * dismissFn forgets to unregister or throws, a single Escape closes exactly
 * one menu and the stack never gets stuck.
 */
export function dismissTopMenu() {
  const entry = _stack.pop();
  if (!entry) return false;
  try { entry.dismissFn(); } catch {}
  return true;
}

/** Test/debug helper: number of currently-registered menus. */
export function _openMenuCount() {
  return _stack.length;
}

/**
 * Tear a transient menu down through its registered dismiss callback if it has
 * one (releasing its Escape-stack entry and any listeners), else fall back to a
 * plain node removal. Use this anywhere menus are cleared in bulk — scroll /
 * swipe / modal-dismiss cleanup, or a "close the previous one" reopen sweep —
 * instead of a raw `el.remove()`, which would strand the stack entry.
 */
export function dismissOrRemove(el) {
  if (!el) return;
  if (typeof el._dismiss === 'function') el._dismiss();
  else el.remove();
}

// ── DOM convenience wrapper ──────────────────────────────────────────────
// The registry above is intentionally DOM-free (and unit-tested as such).
// bindMenuDismiss is the thin DOM layer most callers actually want: it wires
// the ubiquitous "overlay appended to <body>, closes on an outside click"
// idiom to BOTH the outside-click listener AND the Escape stack in one call,
// so a menu only has to describe how to tear itself down once.
//
//   const close = bindMenuDismiss(popup, () => popup.remove());
//   // outside-click and Escape now both call close(); call it yourself from
//   // item handlers too.
//
// `onClose` runs exactly once (idempotent) and owns the actual teardown
// (removing/hiding the node, clearing anchor state, …). `isOutside(ev)`
// defaults to "the click landed outside `el`"; override it when extra anchors
// should count as inside the menu. The returned idempotent close() is also
// stashed on `el._dismiss`, so bulk removers (see dismissOrRemove) can tear the
// menu down through its real teardown rather than orphaning its stack entry.
//
// `P10-06` — a menu opened FROM THE KEYBOARD is operated from the keyboard.
// These menus are built on the fly and most are appended to <body>, which puts
// them at the END of the tab order: Enter on the button that opens one leaves
// the focus on that button, and the next Tab walks away from the menu instead
// of into it. Measured 2026-09-27 in Chromium on the Workshop's two kebabs, a
// skill's and a task's: the menu opened, Tab went to the next card's controls
// and then out of the window, and no item was ever reached — so Run, Edit,
// History and Delete on a task, and Publish, Edit, Test and Delete on a skill,
// had no keyboard path at all. This wrapper is where all 29 such menus already
// meet, so it is fixed here once rather than in each of them (`Law 14`):
//
//   * the first item takes the focus when the menu opens;
//   * ArrowDown/ArrowUp walk the items (wrapping), Home/End jump to the ends,
//     and Tab walks them too, in the browser's own order;
//   * whatever closes it — Escape through the arbiter's dismissTopMenu(), an
//     item, an outside click — gives the focus back to the button, if the focus
//     was still in the menu;
//   * Tab past the last item closes it and the browser carries on from the
//     button, and Shift+Tab before the first closes it onto the button — which
//     is where the menu sits in the order a person expects, not at the end of
//     <body> where it was appended.
//
// A menu opened with the mouse is left exactly as it was. The opener only
// counts when it is the focused control AND matches `:focus-visible`, which a
// clicked button does not in Chromium or Firefox (Safari does not focus a
// clicked button at all). A text field is never an opener — it is always
// `:focus-visible` and it owns the typing, so a search dropdown keeps its input
// — and neither is a menu that has already taken the focus itself.
const _MENU_ITEM = 'button, [role="menuitem"], [role="menuitemradio"], '
  + '[role="menuitemcheckbox"], a[href], summary, input, select, textarea, [tabindex]';
const _NOT_TEXT = ['button', 'submit', 'reset', 'checkbox', 'radio', 'range', 'color',
  'file', 'image'];
const _MENU_KEYS = ['Tab', 'ArrowDown', 'ArrowUp', 'Home', 'End'];

function _isTextEntry(node) {
  if (!node || !node.tagName) return false;
  const tag = String(node.tagName).toUpperCase();
  if (tag === 'TEXTAREA' || tag === 'SELECT') return true;
  if (tag === 'INPUT') return !_NOT_TEXT.includes(String(node.type || 'text').toLowerCase());
  return !!node.isContentEditable;
}

/** Rendered, by the browser's own answer where it has one. */
function _shown(node) {
  if (typeof node.checkVisibility === 'function') return node.checkVisibility();
  for (let n = node; n && n.style; n = n.parentNode) {
    if (n.hidden || n.style.display === 'none' || n.style.visibility === 'hidden') return false;
  }
  return true;
}

function _menuItems(el) {
  return Array.prototype.filter.call(el.querySelectorAll(_MENU_ITEM), (n) =>
    !n.disabled
    && n.getAttribute('tabindex') !== '-1'
    && n.getAttribute('aria-disabled') !== 'true'
    && String(n.type || '').toLowerCase() !== 'hidden'
    && _shown(n));
}

function _keyboardOpener(el) {
  if (typeof document === 'undefined') return null;
  const a = document.activeElement;
  if (!a || a === document.body || a === document.documentElement) return null;
  if (typeof el.contains === 'function' && el.contains(a)) return null;
  if (_isTextEntry(a)) return null;
  try { return a.matches(':focus-visible') ? a : null; } catch (_) { return null; }
}

export function bindMenuDismiss(el, onClose, isOutside) {
  let done = false;
  let unreg = () => {};
  const opener = _keyboardOpener(el);
  const onDocClick = (ev) => {
    const outside = typeof isOutside === 'function' ? isOutside(ev) : !el.contains(ev.target);
    if (outside) close();
  };
  // Keyboard-opened menus only (see above). Listening on the menu itself
  // rather than on `document` keeps it out of every other key's way, and a
  // handler inside the menu that already answered the key is left alone.
  const onKey = (ev) => {
    if (done || ev.defaultPrevented || !_MENU_KEYS.includes(ev.key)) return;
    const items = _menuItems(el);
    const i = items.indexOf(ev.target);
    if (ev.key === 'Tab') {
      // Inside the menu the browser's own Tab is right. At either end it is
      // not: past the last item it would run on into whatever else hangs off
      // <body>, and before the first it would skip the button.
      if (ev.shiftKey ? i <= 0 : i === items.length - 1) {
        close();
        if (ev.shiftKey) ev.preventDefault();
      }
      return;
    }
    if (_isTextEntry(ev.target)) return;
    if (!items.length) return;
    let next = null;
    if (ev.key === 'ArrowDown') next = items[(i + 1) % items.length];
    else if (ev.key === 'ArrowUp') next = items[i <= 0 ? items.length - 1 : i - 1];
    else if (ev.key === 'Home') next = items[0];
    else if (ev.key === 'End') next = items[items.length - 1];
    if (!next) return;
    ev.preventDefault();
    try { next.focus(); } catch (_) {}
  };
  function close() {
    if (done) return;
    done = true;
    // Asked BEFORE the teardown: once `onClose` removes the menu the browser
    // has already moved the focus to <body>, and "was it in the menu" can no
    // longer be told from "was it anywhere".
    const held = !!(opener && typeof el.contains === 'function' && el.contains(document.activeElement));
    unreg(); unreg = () => {};
    document.removeEventListener('click', onDocClick, true);
    if (opener) el.removeEventListener('keydown', onKey);
    try { if (typeof onClose === 'function') onClose(); } catch {}
    if (held && opener.isConnected !== false) {
      try { opener.focus(); } catch (_) {}
    }
  }
  // Defer attaching the outside-click listener so the opening click doesn't
  // immediately close the menu. Skip the attach if close() already ran in the
  // same tick (e.g. an instant Escape) so we never leave a dangling listener.
  setTimeout(() => { if (!done) document.addEventListener('click', onDocClick, true); }, 0);
  unreg = registerMenuDismiss(close);
  el._dismiss = close;
  if (opener) {
    el.addEventListener('keydown', onKey);
    // Deferred like the listener above: several callers bind before they
    // append or position the menu, and an item that is not rendered yet
    // cannot take the focus.
    setTimeout(() => {
      if (done) return;
      const first = _menuItems(el)[0];
      if (first) { try { first.focus(); } catch (_) {} }
    }, 0);
  }
  return close;
}
