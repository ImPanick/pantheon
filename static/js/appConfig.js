// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/appConfig.js
//
// One shared, invalidatable cache for the two config endpoints that every
// module wants at startup.
//
// Before this, /api/auth/settings was fetched independently by six modules and
// /api/tools by three, none of them aware of the others — 4 and 3 requests on a
// single cold load. Worse than the requests: each caller could observe a
// different snapshot of the same object. Caching here fixes both, because the
// cache lives in one module every caller imports by the same specifier.
//
// CORRECTED 2026-08-29 (P3-11). This header used to add that chatRenderer.js
// was imported under three different ?v= query strings, so it was three
// separate module instances each issuing its own /api/tools fetch. That was
// true when this file was written. It is not a workaround for that any more:
// P3-11 unified all eleven forked modules and check-specifiers.py fails CI on
// a reappearance. The duplicate-fetch reason above still stands on its own.
//
// URLs are bare paths on purpose. The callers that used `${API_BASE}/api/...`
// resolved to the identical URL — API_BASE is `window.location.origin`
// (app.js) — so nothing about the request changes for them.
//
// WRITERS MUST INVALIDATE. Anything that POSTs /api/auth/settings calls
// invalidateSettings(); anything that POSTs /api/tools calls invalidateTools()
// *and* invalidateSettings(), because that route persists `disabled_tools`
// into the same settings store (routes/model_routes.py). Miss one and the UI
// serves a stale settings object for the rest of the session, which is worse
// than the duplicate fetches this replaces.
//
// The resolved object is shared by reference, so treat it as read-only: copy
// before mutating (`{ ...await getSettings() }`).

// Written by login.html immediately before it redirects to '/', so the first
// load after a login can skip the request entirely. Consumed once per page
// load, by whichever module asks for settings first.
const PREFETCH_KEY = 'pan-prefetch-settings';

const _URLS = { settings: '/api/auth/settings', tools: '/api/tools' };
const _cache = { settings: null, tools: null };

function _readPrefetchedSettings() {
  try {
    const raw = sessionStorage.getItem(PREFETCH_KEY);
    if (!raw) return null;
    sessionStorage.removeItem(PREFETCH_KEY);
    return JSON.parse(raw);
  } catch (_) {
    return null;
  }
}

// A rejected promise must not stay in the slot. Plain `??=` memoisation would
// keep it, so one transient blip during boot would leave keybinds, TTS and the
// search provider on their defaults for the whole session with no retry. Clear
// the slot on failure — unless a later invalidate/refetch already replaced it —
// and rethrow, so every caller's existing .catch() still runs exactly as before.
function _get(key) {
  if (_cache[key]) return _cache[key];
  const pending = fetch(_URLS[key], { credentials: 'same-origin' })
    .then(r => r.json())
    .catch(err => {
      if (_cache[key] === pending) _cache[key] = null;
      throw err;
    });
  _cache[key] = pending;
  return pending;
}

/** GET /api/auth/settings, once per page load (or once per invalidation). */
export function getSettings() {
  if (!_cache.settings) {
    const prefetched = _readPrefetchedSettings();
    if (prefetched) _cache.settings = Promise.resolve(prefetched);
  }
  return _get('settings');
}

/** GET /api/tools, once per page load (or once per invalidation). */
export function getTools() {
  return _get('tools');
}

/** Call after any write that can change settings. */
export function invalidateSettings() {
  _cache.settings = null;
  // `B1228`: the default chat is derived from settings (`default_model` and
  // its endpoint), so its remembered answer goes with them.
  _settled.delete('/api/default-chat');
}

/** Call after any write that can change the tool enable/disable state. */
export function invalidateTools() {
  _cache.tools = null;
}

// ── `B1228`: the boot reads that were asked twice ──────────────────────────
//
// Measured on one cold load in Chromium (`tests/test_a_page_load_asks_each_
// boot_read_once.py`): `GET /api/auth/status` twice (`init.js`, `app.js`),
// `/api/auth/features` twice (`app.js`, `censor.js`), `/api/default-chat` four
// times (the composer's inline script, `app.js`, `modelPicker.js`,
// `sessions.js`) and `/api/notes` twice (`notes.js`, its badge and its
// reminders). They live here now, beside `getSettings` and `getTools`, and
// their call sites read them from here. Two shapes, because the answers age
// differently:
//
//   * **status and features** are cached like settings — until a writer
//     invalidates them (`invalidateAuthFeatures` after a feature switch; a
//     sign-in or sign-out loads a new page). A fresh page asks once.
//   * **default chat and notes** change under the person's hands (a pick in
//     Settings, a note saved), so they are *shared while in flight*: every
//     caller that asks while a request is out gets that request's answer.
//     Notes are not kept past that — the next ask is a new request, so nothing
//     can be served stale and no writer has to remember to invalidate (the
//     failure the header above warns about); `notes.js`'s reminders reuse the
//     list its badge already read. The default chat is kept for
//     `DEFAULT_CHAT_REUSE_MS`, because its three boot readers ask one after
//     another, and a settings write drops it.
//
// Each answers the parsed JSON (a refusal's body included), never the
// Response, so callers test the fields they need rather than `res.ok`.

const _BOOT_URLS = {
  status: '/api/auth/status',
  features: '/api/auth/features',
  defaultChat: '/api/default-chat',
  notes: '/api/notes',
};
const _boot = { status: null, features: null };
const _inFlight = new Map();
const _settled = new Map();   // url -> { at, value }: an answer, and when it came

function _bootGet(key) {
  if (_boot[key]) return _boot[key];
  const pending = fetch(_BOOT_URLS[key], { credentials: 'same-origin' })
    .then(r => r.json())
    .catch(err => {
      if (_boot[key] === pending) _boot[key] = null;
      throw err;
    });
  _boot[key] = pending;
  return pending;
}

/** `url`, asked once however many callers want it while it is out — and,
 *  with `maxAgeMs`, an answer that came back within that long is reused. */
function _shared(url, adopt, maxAgeMs = 0) {
  const kept = _settled.get(url);
  if (maxAgeMs > 0 && kept && Date.now() - kept.at <= maxAgeMs) return Promise.resolve(kept.value);
  if (_inFlight.has(url)) return _inFlight.get(url);
  const started = adopt || fetch(url, { credentials: 'same-origin' });
  const pending = Promise.resolve(started)
    // A request that never arrived is marked the way `presets.markUnreached`
    // marks one, so a caller's `quietIfUnreached` can tell offline (said once,
    // quietly) from an answer that came back unreadable (an error).
    .catch((e) => { if (e && typeof e === 'object') e.unreached = true; throw e; })
    .then(r => (r && typeof r.json === 'function' ? r.json() : r))
    .then((value) => { _settled.set(url, { at: Date.now(), value }); return value; })
    .finally(() => { if (_inFlight.get(url) === pending) _inFlight.delete(url); });
  _inFlight.set(url, pending);
  return pending;
}

/** How long a default-chat answer is the page's answer. The boot asks it from
 *  three modules over a couple of seconds (`app.js`, then `modelPicker.js` and
 *  `sessions.js` as the chat list draws), so in-flight sharing alone left two
 *  requests; a pick saved in Settings drops it (`invalidateSettings`). */
export const DEFAULT_CHAT_REUSE_MS = 5000;

/** GET /api/auth/status — who is signed in and what they may do. */
export function getAuthStatus() {
  return _bootGet('status');
}

/** GET /api/auth/features — the admin's feature switches. Consumes the
 *  snapshot `login.html` leaves for the first load after a sign-in. */
export function getAuthFeatures() {
  if (!_boot.features) {
    try {
      const raw = sessionStorage.getItem('pan-prefetch-features');
      if (raw) {
        sessionStorage.removeItem('pan-prefetch-features');
        _boot.features = Promise.resolve(JSON.parse(raw));
      }
    } catch (_) { /* no storage, or a torn value: ask the server */ }
  }
  return _bootGet('features');
}

/** Call after any write to the feature switches. */
export function invalidateAuthFeatures() {
  _boot.features = null;
}

/** GET /api/default-chat — shared while in flight. The composer's inline
 *  script starts this read before any module loads and leaves its promise on
 *  `window.__pantheonDefaultChatBoot`; the first caller here adopts it. */
export function getDefaultChat() {
  let adopt = null;
  try {
    if (typeof window !== 'undefined' && window.__pantheonDefaultChatBoot) {
      adopt = window.__pantheonDefaultChatBoot;
      window.__pantheonDefaultChatBoot = null;
    }
  } catch (_) { /* no window: a worker or a test */ }
  return _shared(_BOOT_URLS.defaultChat, adopt, DEFAULT_CHAT_REUSE_MS);
}

/** GET /api/notes (`?archived=true` when asked) — shared while in flight. */
export function getNotes({ archived = false } = {}) {
  return _shared(_BOOT_URLS.notes + (archived ? '?archived=true' : ''));
}
