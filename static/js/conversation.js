// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `B1730`. Conversation: the agent says every reply out loud while it is
// written, in the voice this person chose (Settings → Conversation).
//
// The owner, 2026-11-01, on the switch that does it: *"This should be a
// "Conversation" switch not speak replies aloud - we make it
// personal-able"*. So it is each person's own, kept with their account
// (`PUT /api/prefs/conversation`, beside their shortcuts) and mirrored in
// this browser so the chip is right before the server answers; an admin's
// part is only whether this server speaks at all (Settings → Voice), and
// while it does not, the chip is not shown. Every control that is this
// switch carries `data-conversation-switch` — the composer's chip, and the
// one at the top of Settings → Conversation — and is kept in step here.
//
// Saying it is `aiTTSManager`'s (`tts-ai.js`): `autoPlay` on, and chat.js
// speaks each sentence as it arrives. A voice chat says replies itself, so
// it is never doubled (`chat.js`, `window.__pantheonVoiceCall`).

import { showToast } from './ui.js';

const PREF = 'conversation';
const MIRROR = 'pantheon.conversation';
const CHIP = 'conversation-toggle-btn';

let _on = false;
let _wired = false;
const _listeners = new Set();

function _readMirror() {
  try { return localStorage.getItem(MIRROR) === '1'; } catch (_) { return false; }
}

function _writeMirror(on) {
  try { localStorage.setItem(MIRROR, on ? '1' : '0'); } catch (_) { /* private mode: the account keeps it */ }
}

/** Whether Conversation is on for this person, here. */
export function conversationOn() { return _on; }

/** `fn(on)` each time it changes; the return value stops it. */
export function onConversationChange(fn) {
  _listeners.add(fn);
  return () => _listeners.delete(fn);
}

function _manager() { return window.aiTTSManager || null; }

/** Draw `on` on every switch, and tell the speaker. */
function _apply(on) {
  _on = !!on;
  const mgr = _manager();
  if (mgr) {
    mgr.autoPlay = _on;
    // Off while it speaks: it stops, as the off of any voice does.
    if (!_on && (mgr.isPlaying || mgr._processing)) mgr.stop();
  }
  document.querySelectorAll('[data-conversation-switch]').forEach((n) => {
    if (n.type === 'checkbox') n.checked = _on;
    else {
      n.classList.toggle('active', _on);
      n.setAttribute('aria-pressed', String(_on));
    }
  });
  _listeners.forEach((fn) => { try { fn(_on); } catch (_) { /* a listener's own trouble */ } });
}

/**
 * Turn Conversation on or off for this person and keep it with their
 * account. `true` once the account has it; `false` when the server did not
 * take it (it is still on in this browser, and said so by the caller).
 */
export async function setConversation(on, { save = true } = {}) {
  _apply(on);
  _writeMirror(_on);
  // On: the voice is loaded now, so the first reply is not the one that waits.
  const mgr = _manager();
  if (_on && mgr) mgr.checkAvailability({ warm: true });
  if (!save) return true;
  try {
    const res = await fetch('/api/prefs/' + PREF, {
      method: 'PUT',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ value: _on }),
    });
    return res.ok;
  } catch (_) {
    return false;
  }
}

/** What the chip does when pressed: on only when a voice can speak, and
 *  otherwise says why (`Law 13`: a switch that would say nothing is not
 *  turned on). */
export async function toggleConversation() {
  const next = !_on;
  const mgr = _manager();
  if (next && mgr && mgr.checked && !mgr.speaks) {
    showToast(mgr.reason || 'No voice can speak here yet. Settings → Conversation says why.', 5000);
    return false;
  }
  const kept = await setConversation(next);
  showToast(next ? (kept ? 'Conversation on' : 'Conversation on here; your account did not keep it')
                 : 'Conversation off', 1800);
  return next;
}

/** The chip shows while this server speaks, and says why it cannot when it cannot. */
function _drawChip(detail) {
  const chip = document.getElementById(CHIP);
  if (!chip) return;
  const off = !!(detail && detail.off);
  const changed = chip.hidden !== off;
  chip.hidden = off;
  chip.style.display = off ? 'none' : '';
  // The composer's row measures its chips again: one more, or one fewer.
  if (changed) document.dispatchEvent(new CustomEvent('overflow-state-change'));
  const why = detail && !detail.speaks && detail.reason ? String(detail.reason) : '';
  chip.classList.toggle('conversation-cannot', !!why);
  chip.title = why ? `Conversation: ${why}` : 'Conversation: the agent says its replies out loud';
}

/** Wire the chip and read the account's answer. Once per page. */
export function initConversation() {
  if (_wired) return;
  _wired = true;
  _apply(_readMirror());
  const chip = document.getElementById(CHIP);
  if (chip) chip.addEventListener('click', (e) => { e.preventDefault(); toggleConversation(); });
  window.addEventListener('pantheon:speech', (e) => _drawChip(e.detail));
  const mgr = _manager();
  if (mgr && mgr.checked) _drawChip({ speaks: mgr.speaks, off: mgr.off, reason: mgr.reason });
  // What the account says wins over this browser's mirror: the switch is
  // the person's, on every device they sign in on.
  fetch('/api/prefs/' + PREF, { credentials: 'same-origin' })
    .then((r) => (r.ok ? r.json() : null))
    .then((body) => {
      const value = body ? body.value : undefined;
      if (typeof value === 'boolean' && value !== _on) {
        _apply(value);
        _writeMirror(value);
      }
      if (_on && mgr) mgr.checkAvailability({ warm: true });
    })
    .catch(() => { /* offline: the mirror stands */ });
}

export default { initConversation, setConversation, toggleConversation, conversationOn, onConversationChange };
