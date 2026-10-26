// SPDX-License-Identifier: AGPL-3.0-or-later
const API_BASE = window.location.origin;

export function emailAccountQuery(prefix = '&') {
  const accountId = window.__pantheonActiveEmailAccount || '';
  if (!accountId) return '';
  const lead = prefix === '?' ? '?' : '&';
  return `${lead}account_id=${encodeURIComponent(accountId)}`;
}

export function emailApiUrl(path, params = {}) {
  const url = new URL(`${API_BASE}${path}`);
  const accountId = window.__pantheonActiveEmailAccount || '';
  if (accountId) url.searchParams.set('account_id', accountId);
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return;
    url.searchParams.set(key, String(value));
  });
  return url.toString();
}

// ── `B812` · how many unread, in whichever state the mail window is in ──────
//
// The count existed only on the minimized dock chip (`_syncUnreadTabBadge`,
// `emailLibrary.js`) — the middle of three states. With the window closed
// there is no chip, and `#email-unread-dot` was a dot with no number; open,
// the count is in the window. So the dot carries the number now, whenever
// there is unread mail, and keeps its glow for mail that is new since the
// person last looked. No permanent dock chip: unread mail is not work in
// progress (`P9-11`). The words are here once, for the chip and the dot.

/** `"7 unread"`, capped `"999+ unread"` — the chip's label and the dot's name. */
export function unreadLabel(count) {
  const n = Math.max(0, Math.floor(Number(count) || 0));
  return n > 999 ? '999+ unread' : `${n} unread`;
}

/** What fits inside the dot: `"7"`, capped `"99+"`. */
export function unreadShort(count) {
  const n = Math.max(0, Math.floor(Number(count) || 0));
  return n > 99 ? '99+' : String(n);
}

/**
 * Draw `#email-unread-dot` for `unreadCount` unread messages. `isNew` keeps the
 * breathing glow for mail above the last-seen mark; `tint` is the urgency
 * colour (`_urgencyColor`), drawn with dark text, which white on its orange
 * would not be readable as.
 */
export function paintUnreadDot(dot, { unreadCount = 0, isNew = false, tint = '' } = {}) {
  if (!dot) return;
  const n = Math.max(0, Math.floor(Number(unreadCount) || 0));
  if (n <= 0) {
    dot.style.display = 'none';
    dot.textContent = '';
    dot.classList.remove('has-count', 'is-new');
    dot.removeAttribute('role');
    dot.removeAttribute('aria-label');
    dot.title = '';
    dot.style.backgroundColor = '';
    dot.style.color = '';
    return;
  }
  const label = unreadLabel(n) + (isNew ? ' — new since you last looked' : '');
  dot.textContent = unreadShort(n);
  dot.classList.add('has-count');
  dot.classList.toggle('is-new', !!isNew);
  dot.title = label;
  dot.setAttribute('role', 'img');
  dot.setAttribute('aria-label', label);
  dot.style.backgroundColor = tint || '';
  dot.style.color = tint ? '#111' : '';
  dot.style.display = '';
}
